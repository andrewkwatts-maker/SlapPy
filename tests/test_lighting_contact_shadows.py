"""Regression tests for the round-13 screen-space contact-shadow pass.

Round 13 adds :class:`ContactShadowsPass`
(``python/slappyengine/post_process/contact_shadows.py``) plus the
matching WGSL shader (``shaders/contact_shadows_depth.wgsl``) following
Bouvier 2014, *Contact Shadows in The Order: 1886* (GDC 2014).

The pass complements the round-12 Vogel-disk PCF (R2S3-D) by adding
short-range contact darkening that the CSM cannot resolve at typical
shadow-map resolutions.

Three invariants are locked here:

  1. *Structural*: with the documented ``samples=6`` default, exactly
     six depth-buffer reads happen along the marched ray.
  2. *Numerical*: a pixel directly under another pixel at less than
     ``max_distance`` registers a positive contact-shadow strength.
  3. *Back-compat*: ``samples=0`` makes the pass a strict no-op — the
     main shadow term is forwarded unchanged.

All tests run on the pure-Python mirror of the WGSL algorithm
(``ray_march_contact_shadow``), so no wgpu adapter is required.
"""
from __future__ import annotations

import struct

import pytest

from slappyengine.post_process.contact_shadows import (
    ContactShadowsPass,
    _exponential_step_distance,
    compose_with_main_shadow,
    ray_march_contact_shadow,
)


# ---------------------------------------------------------------------------
# Test instrumentation — counts depth-buffer reads inside the marcher.
# ---------------------------------------------------------------------------


class _CountingDepthBuffer:
    """List-like wrapper that counts each ``__getitem__`` access.

    The pure-Python mirror passes an explicit ``occluder_depths`` list to
    ``ray_march_contact_shadow``; wrapping that list in this counter lets
    us assert how many depth reads the marcher does for a given sample
    count.  In the WGSL shader this corresponds to N ``textureLoad`` calls.
    """

    def __init__(self, values: list[float]) -> None:
        self._values = values
        self.reads = 0

    def __getitem__(self, idx: int) -> float:
        self.reads += 1
        return self._values[idx]

    def __len__(self) -> int:
        return len(self._values)


# ---------------------------------------------------------------------------
# 1. Structural — six ray-march samples → six depth reads.
# ---------------------------------------------------------------------------


def test_six_samples_produce_six_depth_reads() -> None:
    """Default ``samples=6`` performs exactly six depth-buffer reads.

    Bouvier 2014 prescribes a fixed budget of 6 march steps per pixel
    on the GPU; the Python mirror must read each occluder slot once
    until either (a) it finds an occluder or (b) it exhausts the budget.

    Locking this number guards against silent loop-bounds drift that
    would either undersample (visible banding) or oversample (perf
    regression).  We feed the marcher a ray that escapes (the depth
    buffer is far away) so it traverses the full six steps and we
    observe all six reads — the worst case for the perf budget.
    """
    samples = 6
    # Occluder lies far behind the ray at every step → no early-out,
    # the marcher must visit every sample.
    occluders = _CountingDepthBuffer([1.0e6] * samples)

    strength = ray_march_contact_shadow(
        surface_depth=1.0,
        occluder_depths=occluders,  # type: ignore[arg-type]
        samples=samples,
        max_distance=1.0,
        thickness_threshold=0.1,
    )

    assert occluders.reads == samples, (
        f"expected {samples} depth reads, got {occluders.reads}"
    )
    # Ray clears every occluder → contact shadow is zero.
    assert strength == 0.0


# ---------------------------------------------------------------------------
# 2. Numerical — a pixel directly under another pixel at < max_distance
#    produces contact_shadow > 0.
# ---------------------------------------------------------------------------


def test_pixel_under_occluder_gets_contact_shadow() -> None:
    """A pixel beneath another pixel at < max_distance is in contact shadow.

    Scenario: the shaded surface is at depth = 1.0 m.  Directly above it
    along the dominant-light vector sits an occluder at depth = 0.5 m
    (the occluder is closer to the camera than the surface), so the
    ray-marched depth at the first sample (which moves *into* the scene
    away from the light, i.e. towards more depth) exceeds the depth
    buffer's hit by far more than the thickness threshold.  The marcher
    must register a contact-shadow hit.

    The numerical guarantee: strength > 0 (we make no claim about the
    exact value beyond the boolean "occluded" semantics of the 1-D
    mirror).
    """
    samples = 6
    surface_depth = 1.0
    # Every reprojected sample lands on a piece of geometry at depth 0.5
    # — well above the shaded surface (closer to the camera) → ray
    # passes "through" it and the thickness test fires.
    occluders = [0.5] * samples

    strength = ray_march_contact_shadow(
        surface_depth=surface_depth,
        occluder_depths=occluders,
        samples=samples,
        max_distance=1.0,
        thickness_threshold=0.1,
    )

    assert strength > 0.0, (
        "pixel under a clear occluder at < max_distance must register "
        f"a positive contact-shadow strength; got {strength}"
    )

    # Sanity: composing with a fully-lit main shadow must darken it.
    composed = compose_with_main_shadow(
        main_shadow=1.0,
        contact_strength=strength,
        blend=0.7,
    )
    assert composed < 1.0


# ---------------------------------------------------------------------------
# 3. Back-compat — samples=0 is a strict no-op.
# ---------------------------------------------------------------------------


def test_samples_zero_is_noop_in_python_mirror() -> None:
    """``samples=0`` short-circuits to ``0.0`` with zero depth reads.

    The back-compat opt-out path lets existing scenes upgrade to the
    round-13 release without paying *any* runtime cost.  The Python
    mirror must agree with the WGSL early-return: no depth reads, no
    contact-shadow contribution.
    """
    # Empty occluder list — the no-op path must not touch it.
    counter = _CountingDepthBuffer([])
    strength = ray_march_contact_shadow(
        surface_depth=1.0,
        occluder_depths=counter,  # type: ignore[arg-type]
        samples=0,
        max_distance=1.0,
        thickness_threshold=0.1,
    )
    assert strength == 0.0
    assert counter.reads == 0


def test_samples_zero_is_noop_in_pass_metadata() -> None:
    """``ContactShadowsPass(samples=0).is_noop()`` reports True.

    The executor uses :meth:`ContactShadowsPass.is_noop` to skip the
    dispatch entirely.  The Python-side flag and the WGSL early-return
    must agree.
    """
    p = ContactShadowsPass(samples=0)
    assert p.is_noop() is True
    # Composition rule on a no-op: main shadow forwarded unchanged.
    composed = compose_with_main_shadow(
        main_shadow=0.42, contact_strength=0.0, blend=p.blend,
    )
    assert composed == 0.42


def test_samples_default_is_six() -> None:
    """Default ``samples`` matches Bouvier 2014's six-step recommendation."""
    p = ContactShadowsPass()
    assert p.samples == 6
    assert not p.is_noop()


# ---------------------------------------------------------------------------
# 4. Composition — contact shadows can only DARKEN the main term.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("main_shadow", [0.0, 0.25, 0.5, 0.75, 1.0])
@pytest.mark.parametrize("contact_strength", [0.0, 0.5, 1.0])
def test_composition_never_brightens_main_shadow(
    main_shadow: float, contact_strength: float,
) -> None:
    """``compose_with_main_shadow`` is monotonically darkening.

    Per Bouvier 2014 §4, contact shadows are an *additive darkening*
    on the main shadow term — never a replacement.  The composition
    rule ``min(main_shadow, 1.0 - contact_strength * blend)``
    enforces this: the result can never exceed the main shadow.
    """
    composed = compose_with_main_shadow(
        main_shadow=main_shadow,
        contact_strength=contact_strength,
        blend=0.7,
    )
    assert composed <= main_shadow + 1.0e-9, (
        f"composition must not brighten the main shadow: "
        f"main={main_shadow}, contact={contact_strength}, "
        f"composed={composed}"
    )


# ---------------------------------------------------------------------------
# 5. Uniform packing — 32-byte ContactShadowsParams struct, std140-compatible.
# ---------------------------------------------------------------------------


def test_uniform_buffer_layout() -> None:
    """The packed uniform buffer is exactly 32 bytes in the documented layout.

    Drift in this layout would silently mis-bind the WGSL ``params``
    block; we lock the size and the trailing fields so any change to
    the struct trips this test before the GPU silently mis-reads it.
    """
    p = ContactShadowsPass(
        samples=6,
        max_distance=1.5,
        thickness_threshold=0.2,
        blend=0.7,
        light_dir=(0.0, -1.0, 0.0),
    )
    raw = p.make_pass().raw_params_bytes
    assert raw is not None
    assert len(raw) == 32, f"expected 32 bytes, got {len(raw)}"

    # Trailing fields: samples (u32) at offset 12, then max_distance,
    # thickness, blend (f32) at offsets 16, 20, 24.
    samples = struct.unpack_from("<I", raw, 12)[0]
    max_dist = struct.unpack_from("<f", raw, 16)[0]
    thickness = struct.unpack_from("<f", raw, 20)[0]
    blend = struct.unpack_from("<f", raw, 24)[0]
    assert samples == 6
    assert max_dist == pytest.approx(1.5)
    assert thickness == pytest.approx(0.2)
    assert blend == pytest.approx(0.7)


def test_light_dir_is_normalised_at_construction() -> None:
    """A non-unit ``light_dir`` is normalised once at construction.

    The WGSL shader skips a per-pixel ``normalize`` because the light
    direction is uniform.  If the CPU side ever forgets to normalise,
    the ray-march step distances would be off by ‖light_dir‖, producing
    a subtly-wrong ``max_distance``.
    """
    p = ContactShadowsPass(light_dir=(0.0, -2.0, 0.0))  # |L| = 2
    nrm2 = sum(c * c for c in p.light_dir)
    assert nrm2 == pytest.approx(1.0, abs=1.0e-9)


# ---------------------------------------------------------------------------
# 6. Validation — bad config refused loudly at the boundary.
# ---------------------------------------------------------------------------


def test_negative_samples_rejected() -> None:
    with pytest.raises(ValueError, match="samples"):
        ContactShadowsPass(samples=-1)


def test_non_int_samples_rejected() -> None:
    with pytest.raises(TypeError, match="samples"):
        ContactShadowsPass(samples=6.0)  # type: ignore[arg-type]


def test_bool_samples_rejected() -> None:
    """``bool`` is a subclass of ``int`` in Python — refuse it explicitly
    so callers can't pass ``samples=True`` and silently get N=1."""
    with pytest.raises(TypeError, match="samples"):
        ContactShadowsPass(samples=True)  # type: ignore[arg-type]


def test_blend_out_of_range_rejected() -> None:
    with pytest.raises(ValueError, match="blend"):
        ContactShadowsPass(blend=1.5)


def test_negative_max_distance_rejected() -> None:
    with pytest.raises(ValueError, match="max_distance"):
        ContactShadowsPass(max_distance=-0.5)


# ---------------------------------------------------------------------------
# 7. Step-distance schedule — exponential ramp covers max_distance exactly.
# ---------------------------------------------------------------------------


def test_step_distance_last_sample_equals_max_distance() -> None:
    """``t_{N-1} == max_distance`` — the final sample reaches the cap.

    The exponential schedule ``t_i = max_distance * (2^((i+1)/N) - 1)``
    is constructed so that the last sample lands exactly on the budget.
    This guards against a fenceposting bug in the WGSL ``step_distance``.
    """
    for n in (4, 6, 8, 16):
        last = _exponential_step_distance(n - 1, n, max_distance=1.0)
        assert last == pytest.approx(1.0, abs=1.0e-9), (
            f"last step at N={n} should equal max_distance, got {last}"
        )


def test_step_distance_is_strictly_increasing() -> None:
    """Each successive step is farther from the surface than the previous.

    A monotonic schedule is what guarantees that contact shadows
    "expand outward" from the surface — a non-monotonic schedule would
    cause sample 2 to land closer to the surface than sample 1, which
    would double-test the same depth-buffer region for a small contact
    contribution while skipping the larger one.
    """
    samples = 6
    distances = [
        _exponential_step_distance(i, samples, max_distance=1.0)
        for i in range(samples)
    ]
    for a, b in zip(distances, distances[1:]):
        assert b > a, f"non-monotonic step schedule: {distances}"
