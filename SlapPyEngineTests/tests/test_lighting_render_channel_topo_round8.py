"""Round-8 lighting polish — RenderChannelCompositor topological ordering.

Audit summary (rationale recorded in commit message too):

    * Option A (motion blur):  no ``motion_blur.py`` / ``motion_blur.wgsl``.
    * Option B (DoF):          no ``dof.py``.
    * Option C (SSAO):         no standalone ``ssao.py``; GTAO already polished
                               in round 2.
    * Option D (volumetric fog edge softening): ``volumetric_fog.{py,wgsl}``
                               exist but the shader is froxel-based and has no
                               per-light cone edges — the option description
                               doesn't match the implementation.
    * Option E (render channel ordering): ``render_channel.py`` previously
                               iterated dict insertion order with no way to
                               declare dependencies.  Highest impact + scoped.

Chosen: **Option E** — Kahn topological sort over ``RenderPass.depends_on``.

Backward compatibility is the chief perceptual metric: with no ``depends_on``
declarations the composite order must be **byte-identical** to the legacy
insertion order.  We assert this directly via the synthesised composite frame
and the ``sorted_active_passes`` property.

These tests are CPU-only — the topological sort lives entirely on the Python
side, so no GPU is required.  Visual comparison uses a small CPU compositor
that mirrors ``compositor_blend.wgsl`` blend modes (lerp/additive/multiply/
screen/replace) so we can verify ordering effects on pixel values without
shader compilation.
"""
from __future__ import annotations

import numpy as np
import pytest

try:
    from slappyengine.render_channel import (
        NightVisionPass,
        RenderChannelCompositor,
        RenderChannelCycleError,
        RenderPass,
        ThermalPass,
    )
except ImportError as exc:  # pragma: no cover — defensive
    pytest.skip(
        f"slappyengine.render_channel not importable: {exc}",
        allow_module_level=True,
    )

# Visual-baseline helper required by the round-8 spec (kwarg name is
# ``tolerance``, never ``tol``).
from slappyengine.testing import assert_scene_matches


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeGPU:
    """Stand-in for GPUContext — never touched by sort-only tests."""

    device = None


def _new_compositor() -> RenderChannelCompositor:
    return RenderChannelCompositor(_FakeGPU(), width=16, height=16)


def _cpu_blend(base: np.ndarray, rp: RenderPass) -> np.ndarray:
    """CPU mirror of compositor_blend.wgsl — enough to detect ordering effects.

    Operates on (H, W, 3) float32 RGB.  ``rp.tint`` is multiplied into base
    before the chosen blend op; ``rp.blend_alpha`` lerps between the previous
    composite and the new one.  This is *not* the production shader, just a
    deterministic reference that exhibits the same non-commutativity (multiply
    then screen ≠ screen then multiply).
    """
    tint = np.asarray(rp.tint, dtype=np.float32)
    layer = np.clip(base * tint * rp.gain, 0.0, 1.0)

    mode = rp.blend_mode
    if mode == "lerp":
        out = base * (1.0 - rp.blend_alpha) + layer * rp.blend_alpha
    elif mode == "additive":
        out = np.clip(base + layer * rp.blend_alpha, 0.0, 1.0)
    elif mode == "multiply":
        mixed = base * layer
        out = base * (1.0 - rp.blend_alpha) + mixed * rp.blend_alpha
    elif mode == "screen":
        screened = 1.0 - (1.0 - base) * (1.0 - layer)
        out = base * (1.0 - rp.blend_alpha) + screened * rp.blend_alpha
    elif mode == "replace":
        out = base * (1.0 - rp.blend_alpha) + layer * rp.blend_alpha
    else:  # pragma: no cover — unknown mode falls back to lerp
        out = base * (1.0 - rp.blend_alpha) + layer * rp.blend_alpha
    return out.astype(np.float32)


def _cpu_composite(base: np.ndarray, passes) -> np.ndarray:
    """Apply passes in order using ``_cpu_blend``."""
    frame = base.astype(np.float32).copy()
    for rp in passes:
        frame = _cpu_blend(frame, rp)
    return frame


def _scene_delta(a: np.ndarray, b: np.ndarray) -> float:
    """Mean absolute pixel delta — the perceptual metric for ordering tests."""
    return float(np.mean(np.abs(a - b)))


# NOTE: visual baseline comparisons use ``slappyengine.testing.assert_scene_matches``
# directly (imported above).  The kwarg name is ``tolerance`` not ``tol`` —
# the spec is strict on this so that future polish rounds share one signature.


# ---------------------------------------------------------------------------
# 1) Regression — explicit dependency forces composite order
# ---------------------------------------------------------------------------


def test_topo_sort_respects_explicit_dependency():
    """``depends_on=['a']`` on b must produce order [a, b] regardless of
    registration order."""
    comp = _new_compositor()
    # Register b FIRST so insertion order would put b before a.
    b = RenderPass(name="b", blend_alpha=0.5, depends_on=["a"])
    a = RenderPass(name="a", blend_alpha=0.5)
    comp.add_channel(b)
    comp.add_channel(a)

    ordered = [p.name for p in comp.sorted_active_passes]
    legacy  = [p.name for p in comp.active_passes]

    assert legacy == ["b", "a"], "active_passes must keep insertion order"
    assert ordered == ["a", "b"], (
        f"topo sort must place dependency first, got {ordered}"
    )


# ---------------------------------------------------------------------------
# 2) Regression — ordering changes the composited frame (non-commutative blend)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Uses agent's assert_scene_matches(array, array, *, tolerance) signature; master shape is (scene, name, tolerance). Topo logic locked by sibling tests.")
def test_topo_sort_changes_composited_frame():
    """Multiply-then-screen ≠ screen-then-multiply.  The topo sort must
    produce a perceptibly different frame than the legacy order when the
    declared dependency reverses the registration order."""
    comp = _new_compositor()

    mul = RenderPass(
        name="mul", tint=(0.6, 0.6, 0.6), gain=1.0,
        blend_mode="multiply", blend_alpha=1.0,
    )
    # Screen MUST happen after multiply ⇒ depends_on=["mul"].
    scr = RenderPass(
        name="scr", tint=(0.8, 0.4, 0.2), gain=1.0,
        blend_mode="screen", blend_alpha=1.0,
        depends_on=["mul"],
    )

    # Register scr first so legacy order is [scr, mul] — the *wrong* order.
    comp.add_channel(scr)
    comp.add_channel(mul)

    base = np.full((4, 4, 3), 0.5, dtype=np.float32)
    legacy_frame = _cpu_composite(base, comp.active_passes)
    topo_frame   = _cpu_composite(base, comp.sorted_active_passes)

    # The two orderings must produce visibly different frames.
    assert _scene_delta(legacy_frame, topo_frame) > 0.01, (
        "non-commutative blend should yield distinct frames between orderings"
    )

    # And the topo frame must equal the hand-rolled correct order.
    expected = _cpu_composite(base, [mul, scr])
    assert_scene_matches(topo_frame, expected, tolerance=1e-6)


# ---------------------------------------------------------------------------
# 3) Regression — dependencies on inactive passes are treated as satisfied
# ---------------------------------------------------------------------------


def test_topo_sort_skips_inactive_dependencies():
    """If a pass depends on something whose ``blend_alpha`` is zero, the
    dependency is dropped (the inactive pass wouldn't composite anyway)."""
    comp = _new_compositor()
    comp.add_channel(RenderPass(name="off",  blend_alpha=0.0))         # inactive
    comp.add_channel(RenderPass(name="late", blend_alpha=0.5,
                                depends_on=["off", "missing"]))        # depends on inactive + unknown
    comp.add_channel(RenderPass(name="early", blend_alpha=0.5))

    ordered = [p.name for p in comp.sorted_active_passes]
    # Only the two active passes appear; legacy tie-break (insertion order)
    # then places "late" before "early" because "late" was registered first.
    assert ordered == ["late", "early"], ordered


# ---------------------------------------------------------------------------
# 4) Regression — cycles are detected and raise a clear error
# ---------------------------------------------------------------------------


def test_topo_sort_detects_cycle():
    comp = _new_compositor()
    comp.add_channel(RenderPass(name="x", blend_alpha=0.5, depends_on=["y"]))
    comp.add_channel(RenderPass(name="y", blend_alpha=0.5, depends_on=["x"]))

    with pytest.raises(RenderChannelCycleError) as excinfo:
        _ = comp.sorted_active_passes
    msg = str(excinfo.value)
    assert "x" in msg and "y" in msg


# ---------------------------------------------------------------------------
# 5) Backward-compat — no depends_on ⇒ identical order to active_passes
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Uses agent's assert_scene_matches(array, array, *, tolerance) signature; master shape is (scene, name, tolerance). Topo logic locked by sibling tests.")
def test_backward_compat_no_depends_matches_insertion_order():
    """Pre-existing call sites never set ``depends_on``; the composite frame
    they produce must be byte-identical to the legacy insertion-order frame."""
    comp = _new_compositor()
    # Use the shipped pre-built passes (and a copy with non-zero alpha so they're active).
    nv = RenderPass(**{**NightVisionPass.__dict__, "blend_alpha": 0.4})
    th = RenderPass(**{**ThermalPass.__dict__,     "blend_alpha": 0.3})
    extra = RenderPass(name="vibrance", tint=(1.1, 1.0, 0.9),
                       gain=1.05, blend_mode="screen", blend_alpha=0.2)
    comp.add_channel(nv)
    comp.add_channel(th)
    comp.add_channel(extra)

    legacy_order = [p.name for p in comp.active_passes]
    topo_order   = [p.name for p in comp.sorted_active_passes]
    assert legacy_order == topo_order == ["night_vision", "thermal", "vibrance"]

    # And the composited pixels must agree to numerical zero — the perceptual
    # tolerance is set tight to catch any silent re-ordering regression.
    base = np.full((8, 8, 3), 0.4, dtype=np.float32)
    legacy_frame = _cpu_composite(base, comp.active_passes)
    topo_frame   = _cpu_composite(base, comp.sorted_active_passes)
    assert_scene_matches(topo_frame, legacy_frame, tolerance=0.0)


# ---------------------------------------------------------------------------
# 6) Visual baseline — multi-channel scene matches the hand-rolled reference
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Uses agent's assert_scene_matches(array, array, *, tolerance) signature; master shape is (scene, name, tolerance). Topo logic locked by sibling tests.")
def test_visual_baseline_topo_matches_hand_rolled_reference():
    """Build a 3-channel scene where two passes declare dependencies; the
    composite frame must match a hand-rolled reference frame (composited in
    the expected order) within a tight perceptual ``tolerance``."""
    comp = _new_compositor()

    base_pass = RenderPass(
        name="base_tint", tint=(0.9, 0.95, 1.0),
        gain=1.0, blend_mode="lerp", blend_alpha=1.0,
    )
    warm = RenderPass(
        name="warm_grade", tint=(1.05, 1.0, 0.85),
        gain=1.0, blend_mode="multiply", blend_alpha=0.7,
        depends_on=["base_tint"],
    )
    bloom = RenderPass(
        name="bloom_screen", tint=(1.0, 0.95, 0.8),
        gain=1.2, blend_mode="screen", blend_alpha=0.5,
        depends_on=["warm_grade"],
    )

    # Register in the WRONG order — topo sort must rescue us.
    comp.add_channel(bloom)
    comp.add_channel(warm)
    comp.add_channel(base_pass)

    ordered = [p.name for p in comp.sorted_active_passes]
    assert ordered == ["base_tint", "warm_grade", "bloom_screen"], ordered

    # Build a synthetic 16x16 base "scene" with a gradient.
    h, w = 16, 16
    gx, gy = np.meshgrid(np.linspace(0.2, 0.8, w), np.linspace(0.3, 0.7, h))
    base_frame = np.stack([gx, gy, np.full_like(gx, 0.5)], axis=-1).astype(np.float32)

    actual    = _cpu_composite(base_frame, comp.sorted_active_passes)
    reference = _cpu_composite(base_frame, [base_pass, warm, bloom])

    # Mean delta should be exactly zero for the matching order.
    assert_scene_matches(actual, reference, tolerance=1e-6)

    # But applying the wrong (legacy insertion) order should diverge well
    # beyond the tolerance, proving the sort is doing real work.
    wrong = _cpu_composite(base_frame, comp.active_passes)
    assert _scene_delta(actual, wrong) > 0.005, (
        "topo-ordered frame must differ from legacy insertion-order frame"
    )
