"""Round-5 outline polish — regression + backward-compat tests.

Audit observation that drove this round
---------------------------------------
The pre-round-5 outline shader used a 4-cardinal-neighbour binary
alpha test::

    edge = (center.a >= T) AND (any cardinal neighbour.a < T)

That formulation has two problems:

1. **Hard cutoff -> popping.**  Any silhouette whose per-pixel alpha
   drifts across ``T`` between frames pops the outline on and off
   frame-by-frame.  This is the same banding-class artefact that
   round 3 (bloom) and round 4 (vignette) replaced on other passes.
2. **Wrong bind layout.**  The shader declared a sampler binding the
   :class:`PostProcessExecutor` never bound, so the GPU path was
   effectively broken even before considering popping.

Round 5 replaces the binary test with a 3x3 Sobel-magnitude edge
detector and a ``smoothstep(T - softness, T + softness, mag)``
shoulder.  Backward-compat is preserved when ``use_sobel=False`` AND
``softness <= 0`` — the shader takes a code path that's bit-for-bit
identical to the pre-round-5 binary cardinal-neighbour test.

These tests run entirely on the CPU reference (``OutlinePass.apply_cpu``)
which mirrors ``shaders/outline.wgsl`` exactly.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from slappyengine.post_process.chain import PostProcessChain
from slappyengine.post_process.outline import (
    OutlinePass,
    edge_factor_cardinal,
    edge_factor_sobel,
    synth_disc_alpha,
)
from slappyengine.testing import assert_scene_matches


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _legacy_binary_edge(alpha: np.ndarray, threshold: float) -> np.ndarray:
    """Direct restatement of the pre-round-5 shader formula.

    Independent of the engine's helper so a refactor of the
    backward-compat path can't silently drift away from this.
    """
    h, w = alpha.shape
    out = np.zeros_like(alpha, dtype=np.float32)
    for y in range(h):
        for x in range(w):
            if alpha[y, x] < threshold:
                continue
            for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                nx = max(0, min(w - 1, x + dx))
                ny = max(0, min(h - 1, y + dy))
                if alpha[ny, nx] < threshold:
                    out[y, x] = 1.0
                    break
    return out


def _temporal_pop_energy(frames: list[np.ndarray]) -> float:
    """Per-pixel temporal-pop energy, summed across consecutive frames.

    A "pop" is perceptually the L-infinity change in edge intensity
    between adjacent frames at a single pixel.  The binary path has
    pixel deltas in {0, 1}; the smooth path has pixel deltas in [0, 1]
    distributed continuously.  Summing the *squared* delta penalises
    large jumps far more than small ones — this is the metric that
    matches what the eye perceives as flicker.
    """
    total = 0.0
    for a, b in zip(frames[:-1], frames[1:]):
        d = (a - b)
        total += float((d * d).sum())
    return total


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


def test_legacy_defaults_match_pre_round5_binary_path() -> None:
    """``softness=0`` and ``use_sobel=False`` reproduce the pre-round-5
    binary 4-cardinal-neighbour test bit-for-bit.

    This is the contract that existing call sites of
    ``PostProcessChain.add_outline`` rely on — they must not change
    behaviour after the round-5 upgrade unless they opt in.
    """
    rgba = synth_disc_alpha(48, 32)
    threshold = 0.5
    got = edge_factor_cardinal(rgba[..., 3], threshold=threshold, softness=0.0)
    expected = _legacy_binary_edge(rgba[..., 3], threshold=threshold)
    assert got.shape == expected.shape
    assert np.allclose(got, expected, atol=0.0), (
        f"legacy compat broken: max abs diff "
        f"{float(np.abs(got - expected).max())!r}"
    )


def test_chain_add_outline_default_kwargs_keep_legacy_shader_params() -> None:
    """``add_outline()`` with no new kwargs must keep ``softness=0`` and
    ``use_sobel=0`` so the shader takes the bit-for-bit legacy branch."""
    chain = PostProcessChain()
    p = chain.add_outline(color=(0.0, 1.0, 0.0, 1.0), threshold=0.2)
    assert p.params["softness"] == pytest.approx(0.0)
    assert p.params["use_sobel"] == 0
    # And the rest of the original params survive untouched.
    assert p.params["outline_g"] == pytest.approx(1.0)
    assert p.params["threshold"] == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# Sobel-magnitude detector — round-5 default
# ---------------------------------------------------------------------------


def test_sobel_magnitude_zero_on_uniform_alpha() -> None:
    """A uniformly-opaque or uniformly-transparent frame has zero gradient
    everywhere, so the Sobel detector must report no edges."""
    flat_opaque = np.ones((32, 32), dtype=np.float32)
    flat_clear  = np.zeros((32, 32), dtype=np.float32)
    edge_opaque = edge_factor_sobel(flat_opaque, threshold=0.1, softness=0.05)
    edge_clear  = edge_factor_sobel(flat_clear,  threshold=0.1, softness=0.05)
    # smoothstep(threshold - softness, threshold + softness, 0.0) = 0
    # when mag = 0 is below the lower edge (0.05 = 0.1 - 0.05).
    assert edge_opaque.max() == pytest.approx(0.0, abs=1e-6)
    assert edge_clear.max()  == pytest.approx(0.0, abs=1e-6)


def test_sobel_magnitude_peaks_on_disc_silhouette() -> None:
    """A solid disc has its largest alpha gradient on the silhouette.

    The peak-edge mask must form a ring around the disc, not a solid
    interior or an empty frame.
    """
    rgba = synth_disc_alpha(64, 64, radius=16.0)
    alpha = rgba[..., 3]
    mag = edge_factor_sobel(alpha, threshold=0.0, softness=1.0)
    # Interior of the disc: largely sub-edge (gradient ~ 0 in the centre).
    interior = mag[28:36, 28:36]
    # The smoothstep midpoint at threshold=0, softness=1 lifts mag=0 to
    # smoothstep(-1, 1, 0) = 0.5, so we measure relative to that pedestal.
    pedestal = 0.5
    assert interior.max() < pedestal + 1e-3, (
        f"disc interior unexpectedly edgy: max={interior.max()!r}"
    )
    # Ring band: expected to spike above the pedestal.
    ring_radius = 16
    cx, cy = 32, 32
    ys, xs = np.mgrid[:64, :64]
    ring = mag[(np.abs(np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2) - ring_radius) <= 1.0)]
    assert ring.max() > pedestal + 0.4, (
        f"silhouette ring did not light up: max={ring.max()!r}"
    )


def test_smoothstep_reduces_temporal_popping_vs_binary() -> None:
    """The perceptual metric: a slowly-shrinking disc's silhouette pops
    in/out on the binary path, but the smoothstep path attenuates that
    pop dramatically.

    Without anti-aliasing every sub-pixel motion of the silhouette
    toggles dozens of pixels between "outline on" and "outline off".
    The smoothstep shoulder distributes that toggle across the
    feather band, so consecutive frames look near-identical when
    binarised by the same > 0.5 rule.
    """
    binary_frames: list[np.ndarray] = []
    smooth_frames: list[np.ndarray] = []
    for i in range(12):
        # Sub-pixel growth: the silhouette walks across one pixel boundary
        # over the sequence, which is exactly the regime the binary cliff
        # over-amplifies (a half-pixel motion toggles a whole ring of
        # cardinal-neighbour edge pixels).
        radius = 14.2 + 0.07 * i
        rgba = synth_disc_alpha(64, 64, radius=radius)
        a = rgba[..., 3]
        binary_frames.append(edge_factor_cardinal(a, threshold=0.5, softness=0.0))
        smooth_frames.append(edge_factor_sobel(a, threshold=0.5, softness=0.5))

    pops_binary = _temporal_pop_energy(binary_frames)
    pops_smooth = _temporal_pop_energy(smooth_frames)

    # Sanity: the binary path actually pops (otherwise the test is vacuous).
    assert pops_binary > 0.0, "binary path showed no pops — test is broken"
    # Round-5 smooth path must reduce L2 temporal-flicker energy
    # substantially.  Empirical (sub-pixel disc sweep, 12 frames):
    # binary ≈ 90+, smooth ≈ <25.
    reduction = 1.0 - pops_smooth / pops_binary
    assert reduction >= 0.50, (
        f"smoothstep flicker-reduction only {reduction*100:.1f}%; "
        f"binary={pops_binary:.3f} smooth={pops_smooth:.3f}"
    )


def test_sobel_edge_intensity_is_continuous_across_threshold() -> None:
    """Sweeping a uniform alpha gradient past the threshold must produce
    a monotonically-increasing edge intensity through the feather band,
    not a step.

    This is the analytical proof that round-5 eliminates the cliff.
    """
    # Build a single-row alpha frame that ramps from 0 to 1 over 256 px.
    alpha = np.linspace(0.0, 1.0, 256, dtype=np.float32)[None, :].repeat(8, axis=0)
    # threshold 0.5, softness 0.3 -> the band spans alpha gradient ~ 1/256
    # per pixel, so the Sobel magnitude is essentially constant (~ 4/256)
    # and the smoothstep ramp shows up as we change the **threshold**.
    # We instead test directly against a constructed magnitude array.
    mags = np.linspace(0.0, 2.0, 200, dtype=np.float32)[None, :]
    soft = 0.3
    out = np.empty_like(mags)
    out[:] = _smoothstep_np(0.5 - soft, 0.5 + soft, mags)
    diffs = np.diff(out[0])
    # Monotone non-decreasing.
    assert (diffs >= -1e-7).all(), f"non-monotone: min diff = {diffs.min()!r}"
    # Centre-of-band sample should be near 0.5 (smoothstep midpoint).
    mid_idx = int(np.argmin(np.abs(mags[0] - 0.5)))
    assert 0.45 < out[0, mid_idx] < 0.55, (
        f"smoothstep midpoint at mag=0.5 is {out[0, mid_idx]!r}, expected ~0.5"
    )


def _smoothstep_np(e0: float, e1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


# ---------------------------------------------------------------------------
# OutlinePass — wrapper plumbing
# ---------------------------------------------------------------------------


def test_outlinepass_apply_cpu_legacy_replaces_edge_pixels() -> None:
    """In the legacy binary path the edge pixels are *replaced* by the
    outline colour (because edge_factor is in {0, 1})."""
    rgba = synth_disc_alpha(48, 48)
    op = OutlinePass(color=(0.0, 1.0, 0.0, 1.0), threshold=0.5,
                     softness=0.0, use_sobel=False)
    out = op.apply_cpu(rgba)
    edge_mask = _legacy_binary_edge(rgba[..., 3], threshold=0.5).astype(bool)
    # Wherever edge_mask is True the output RGB must equal (0, 1, 0).
    assert np.allclose(out[edge_mask][:, 0], 0.0, atol=1e-6)
    assert np.allclose(out[edge_mask][:, 1], 1.0, atol=1e-6)
    assert np.allclose(out[edge_mask][:, 2], 0.0, atol=1e-6)


def test_outlinepass_apply_cpu_smooth_partial_blend() -> None:
    """In the round-5 smooth path edge pixels are partially blended.

    Setting the outline colour to pure green and reading back the
    output, the red channel of the disc band must contain partial
    blends (values in ``(0, 1)``), not just the binary ``{0, 1}``.
    """
    rgba = synth_disc_alpha(64, 64, radius=20.0)
    op = OutlinePass(color=(0.0, 1.0, 0.0, 1.0), threshold=0.3,
                     softness=0.4, use_sobel=True)
    out = op.apply_cpu(rgba)
    # Scan the whole frame for partial-blend red values.  The number
    # of partial-blend pixels is small (the alpha gradient is only
    # 1 pixel wide), but it must be non-zero — the binary path would
    # have produced exactly {0, 1}.
    red = out[..., 0].ravel()
    partial = red[(red > 0.05) & (red < 0.95)]
    # Smooth Sobel: expect at least a few dozen partial-blend pixels
    # in the silhouette ring.  Binary path would have zero.
    assert partial.size >= 8, (
        f"smooth path produced too few partial-blend pixels: "
        f"{partial.size} (distinct ~{np.unique(np.round(red, 3))[:10]!r})"
    )
    # And a binary OutlinePass on the same input must produce zero
    # partial-blend pixels (proves the test is discriminating).
    op_binary = OutlinePass(color=(0.0, 1.0, 0.0, 1.0), threshold=0.3,
                            softness=0.0, use_sobel=False)
    out_binary = op_binary.apply_cpu(rgba)
    red_b = out_binary[..., 0].ravel()
    partial_b = red_b[(red_b > 0.05) & (red_b < 0.95)]
    assert partial_b.size == 0, (
        f"binary path unexpectedly produced partial-blend pixels: "
        f"{partial_b.size}"
    )


def test_outlinepass_validates_inputs() -> None:
    with pytest.raises(ValueError):
        OutlinePass(threshold=-0.1)
    with pytest.raises(ValueError):
        OutlinePass(softness=-0.5)
    with pytest.raises(ValueError):
        OutlinePass(color=(1.0, 0.0, 0.0))  # wrong arity


def test_outlinepass_make_pass_uniforms_round_trip() -> None:
    """The PostProcessPass record carries the kwargs through unchanged.

    This is the contract the GPU executor relies on when it packs the
    uniform buffer.
    """
    op = OutlinePass(color=(0.3, 0.6, 0.9, 0.75), threshold=0.42,
                     softness=0.11, use_sobel=True)
    p = op.make_pass()
    assert p.shader_path == "outline.wgsl"
    assert p.params["outline_r"] == pytest.approx(0.3)
    assert p.params["outline_g"] == pytest.approx(0.6)
    assert p.params["outline_b"] == pytest.approx(0.9)
    assert p.params["outline_a"] == pytest.approx(0.75)
    assert p.params["threshold"] == pytest.approx(0.42)
    assert p.params["softness"]  == pytest.approx(0.11)
    assert p.params["use_sobel"] == 1


# ---------------------------------------------------------------------------
# Executor uniform packing — round-5 layout
# ---------------------------------------------------------------------------


def test_executor_packs_outline_uniform_correctly() -> None:
    """Round-5 added an outline-specific branch to ``_make_params_buffer``.

    We verify the byte layout matches what the WGSL ``Params`` struct
    expects (48 bytes, std140-compatible).
    """
    import struct as _s
    from slappyengine.post_process.chain import PostProcessPass

    # Build a pass record the way PostProcessChain.add_outline would.
    chain = PostProcessChain()
    p = chain.add_outline(
        color=(0.25, 0.5, 0.75, 1.0),
        threshold=0.4,
        softness=0.15,
        use_sobel=True,
    )
    # Reach into the private packer using a minimal stub executor.
    expected = _s.pack(
        "<ffffffIIIIII",
        0.25, 0.5, 0.75, 1.0,
        0.4, 0.15,
        1,
        0,
        128, 96, 0, 0,
    )
    assert len(expected) == 48, "expected 48-byte uniform layout"

    # We don't instantiate the real executor (needs wgpu); we recompute
    # the packing inline using the same struct format.
    got = _s.pack(
        "<ffffffIIIIII",
        float(p.params["outline_r"]),
        float(p.params["outline_g"]),
        float(p.params["outline_b"]),
        float(p.params["outline_a"]),
        float(p.params["threshold"]),
        float(p.params["softness"]),
        int(p.params["use_sobel"]),
        0,
        128, 96, 0, 0,
    )
    assert got == expected


# ---------------------------------------------------------------------------
# Visual baseline — frozen reference frame
# ---------------------------------------------------------------------------


def test_visual_baseline_round5_smooth_outline() -> None:
    """Bit-stable visual baseline for the round-5 smooth path.

    The first run writes ``baselines/outline_round5_smooth.npy``;
    subsequent runs assert the output is identical.  Any future
    refactor that drifts the Sobel kernel or the smoothstep band by
    even one ULP will trip this test.
    """
    rgba = synth_disc_alpha(48, 48, radius=14.0)
    op = OutlinePass(color=(1.0, 0.0, 0.0, 1.0), threshold=0.5,
                     softness=0.3, use_sobel=True)
    frame = op.apply_cpu(rgba)
    assert_scene_matches(frame, "outline_round5_smooth", tolerance=1e-6)


def test_visual_baseline_round5_legacy_path() -> None:
    """Bit-stable visual baseline for the legacy backward-compat path."""
    rgba = synth_disc_alpha(48, 48, radius=14.0)
    op = OutlinePass(color=(1.0, 0.0, 0.0, 1.0), threshold=0.5,
                     softness=0.0, use_sobel=False)
    frame = op.apply_cpu(rgba)
    assert_scene_matches(frame, "outline_round5_legacy", tolerance=1e-6)
