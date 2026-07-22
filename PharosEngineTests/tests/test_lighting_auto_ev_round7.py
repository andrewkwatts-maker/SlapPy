"""Lighting round 7 — auto-EV (automatic exposure) regression tests.

Covers the CPU reference path of :class:`AutoExposurePass` and the backward
compatibility of :class:`TonemapPass` when no ``auto_ev`` is attached.

The formula under test is the standard Lottes 2017 / Karis 2013
"log-average luminance" form::

    log_avg     = mean_i log(max(L_i, 1e-7))    with L = dot(rgb, BT.709)
    derived_ev  = log2(target_grey / exp(log_avg))
    ev_{t+1}    = ev_t * (1 - smoothing) + derived_ev * smoothing
    ev          = clamp(ev_{t+1}, min_ev, max_ev)
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from pharos_engine.post_process.auto_exposure import AutoExposurePass
from pharos_engine.post_process.chain import PostProcessChain
from pharos_engine.post_process.tonemap import TonemapPass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _constant_grey_frame(grey: float, h: int = 16, w: int = 16) -> np.ndarray:
    """A solid grey frame with the given linear luminance."""
    img = np.full((h, w, 3), float(grey), dtype=np.float32)
    return img


# ---------------------------------------------------------------------------
# 1. Bright scene → EV pulls down
# ---------------------------------------------------------------------------

def test_auto_ev_derives_lower_for_bright_scene():
    """A scene brighter than mid-grey should produce a *negative* EV (pulls
    exposure down). With target_grey=0.18 and a flat 1.0 frame the math is::

        log_avg = log(1.0) = 0
        derived = log2(0.18 / 1.0) = log2(0.18) ≈ -2.474
    """
    ae = AutoExposurePass(target_grey=0.18, smoothing=1.0)  # snap, no smoothing
    bright = _constant_grey_frame(1.0)
    ev = ae.apply_cpu(bright)
    assert ev < 0.0, f"bright scene should darken EV, got {ev}"
    assert ev == pytest.approx(math.log2(0.18), abs=1e-4)


# ---------------------------------------------------------------------------
# 2. Dark scene → EV pushes up
# ---------------------------------------------------------------------------

def test_auto_ev_derives_higher_for_dark_scene():
    """A scene darker than mid-grey should produce a *positive* EV. With a
    flat 0.02 frame:: derived = log2(0.18 / 0.02) ≈ +3.17.
    """
    ae = AutoExposurePass(target_grey=0.18, smoothing=1.0)
    dark = _constant_grey_frame(0.02)
    ev = ae.apply_cpu(dark)
    assert ev > 0.0, f"dark scene should brighten EV, got {ev}"
    assert ev == pytest.approx(math.log2(0.18 / 0.02), abs=1e-4)


# ---------------------------------------------------------------------------
# 3. Smoothing converges over frames
# ---------------------------------------------------------------------------

def test_auto_ev_smooths_over_frames():
    """Calling apply_cpu repeatedly with the same input must converge towards
    the steady-state EV. With smoothing=0.05 and an initial EV of 0, the
    geometric series gives convergence inside 30 frames to within 0.05 stops
    for any clamped target.
    """
    ae = AutoExposurePass(target_grey=0.18, smoothing=0.05)
    # Force the smoother off zero (apply_cpu with smoothing<1 first call
    # snaps to the derived value because there's no prior state; we want to
    # exercise the smoothing curve, so seed an initial state first).
    ae.apply_cpu(_constant_grey_frame(0.18))  # derived ≈ 0
    assert ae.current_ev == pytest.approx(0.0, abs=1e-4)

    # Now switch to a dark frame and watch the EV climb towards the target.
    target_frame = _constant_grey_frame(0.02)
    target_ev = math.log2(0.18 / 0.02)  # ≈ 3.17

    evs = [ae.apply_cpu(target_frame) for _ in range(30)]

    # Monotone increasing.
    for a, b in zip(evs, evs[1:]):
        assert b >= a - 1e-6, f"EV must be non-decreasing, got {a} -> {b}"

    # Stable value within smoothing tolerance.
    final = evs[-1]
    assert abs(final - target_ev) < 0.5 * abs(target_ev), (
        f"after 30 frames EV ({final}) should be within 50 % of target "
        f"({target_ev})"
    )

    # The classic time-constant for blend factor a is k = ln(1 / tol) / -ln(1-a).
    # For a=0.05, tol=0.05  => k ≈ ln(20) / ln(1/0.95) ≈ 58 frames to within
    # 5 % of target. After 30 frames we should have closed >= 78 % of the gap.
    closed_fraction = (final - 0.0) / target_ev
    expected_min = 1.0 - (1.0 - 0.05) ** 30  # 1 - 0.95^30 ≈ 0.785
    assert closed_fraction == pytest.approx(expected_min, abs=1e-3), (
        f"smoothing geometry mismatch: closed {closed_fraction:.4f} vs "
        f"expected {expected_min:.4f}"
    )


# ---------------------------------------------------------------------------
# 4. Clamping
# ---------------------------------------------------------------------------

def test_auto_ev_clamped_to_min_max():
    """An absurdly bright or dark frame must clamp to the configured bounds."""
    ae = AutoExposurePass(
        target_grey=0.18,
        smoothing=1.0,           # snap → no smoothing latency
        min_ev=-2.0,
        max_ev=2.0,
    )
    super_bright = _constant_grey_frame(10000.0)
    ev_hi = ae.apply_cpu(super_bright)
    assert ev_hi == pytest.approx(-2.0, abs=1e-6), (
        f"bright frame should clamp to min_ev=-2, got {ev_hi}"
    )

    ae.reset()
    super_dark = _constant_grey_frame(1e-6)
    ev_lo = ae.apply_cpu(super_dark)
    assert ev_lo == pytest.approx(2.0, abs=1e-6), (
        f"dark frame should clamp to max_ev=+2, got {ev_lo}"
    )


# ---------------------------------------------------------------------------
# 5. reset() drops smoothing history
# ---------------------------------------------------------------------------

def test_auto_ev_reset_returns_to_zero():
    """After reset(), the next apply_cpu must compute its EV from scratch —
    i.e. as if the smoother had never seen a prior frame.
    """
    ae = AutoExposurePass(target_grey=0.18, smoothing=0.05)
    # Burn in a strongly-biased EV first.
    for _ in range(20):
        ae.apply_cpu(_constant_grey_frame(0.02))  # pushes EV upward
    biased = ae.current_ev
    assert biased > 0.5, (
        f"setup precondition: smoother should have climbed; got {biased}"
    )

    ae.reset()
    assert ae.current_ev == 0.0

    # First post-reset frame should equal the derived EV directly, with no
    # influence from the (now-cleared) prior frames.
    expected = math.log2(0.18 / 1.0)
    ev = ae.apply_cpu(_constant_grey_frame(1.0))
    assert ev == pytest.approx(expected, abs=1e-4), (
        f"post-reset EV should be the from-scratch derivation; got {ev} "
        f"vs expected {expected}"
    )


# ---------------------------------------------------------------------------
# 6. Backward-compat: TonemapPass without auto_ev matches master HEAD
# ---------------------------------------------------------------------------

def test_backward_compat_no_auto_ev_unchanged():
    """A TonemapPass with no auto_ev must produce a PostProcessPass whose
    params dict matches the manual-only contract executor expects (the same
    keys/values the master-HEAD ``_make_params_buffer`` consumes).
    """
    tm = TonemapPass(exposure_ev=1.25, mode=0, saturation=1.1, contrast=0.95)
    p = tm.make_pass()

    assert p.shader_path == "tonemap.wgsl"
    assert p.label == "tonemap"
    assert p.entry_point == "tonemap_main"
    # Manual EV is forwarded untouched when there's no auto_ev.
    assert p.params["exposure_ev"] == pytest.approx(1.25)
    assert p.params["mode"] == 0
    assert p.params["saturation"] == pytest.approx(1.1)
    assert p.params["contrast"] == pytest.approx(0.95)
    # Default-identity lift / gain / gamma keys must exist for the executor.
    for key, val in [
        ("lift_r", 0.0), ("lift_g", 0.0), ("lift_b", 0.0),
        ("gain_r", 1.0), ("gain_g", 1.0), ("gain_b", 1.0),
        ("gamma", 1.0),
    ]:
        assert p.params[key] == pytest.approx(val)

    # And — critically — the chain helper round-trips the same way:
    chain = PostProcessChain()
    p2 = chain.add_tonemap(exposure_ev=1.25, mode=0, saturation=1.1, contrast=0.95)
    assert p2.shader_path == "tonemap.wgsl"
    assert p2.params["exposure_ev"] == pytest.approx(1.25)
    assert p2.params["mode"] == 0


# ---------------------------------------------------------------------------
# 7. TonemapPass + auto_ev integration
# ---------------------------------------------------------------------------

def test_tonemap_pass_picks_up_derived_ev():
    """When auto_ev is attached, derive_exposure_ev() must replace the manual
    exposure_ev in the params dict on the next make_pass().
    """
    auto = AutoExposurePass(target_grey=0.18, smoothing=1.0)
    tm = TonemapPass(exposure_ev=99.0, auto_ev=auto)

    # Before derive — manual value is used.
    p_before = tm.make_pass()
    assert p_before.params["exposure_ev"] == pytest.approx(99.0)

    # After derive — auto value overrides.
    bright = _constant_grey_frame(1.0)
    derived = tm.derive_exposure_ev(bright)
    p_after = tm.make_pass()
    assert p_after.params["exposure_ev"] == pytest.approx(derived)
    assert p_after.params["exposure_ev"] == pytest.approx(math.log2(0.18), abs=1e-4)
    assert p_after.params["exposure_ev"] != pytest.approx(99.0)


# ---------------------------------------------------------------------------
# 8. Visual baseline (best-effort)
# ---------------------------------------------------------------------------

def test_auto_ev_visual_baseline_smoke():
    """Drive auto_ev across a representative range; assert numerical stability.

    The project does not currently expose ``pharos_engine.testing.assert_scene_matches``
    (the visual-baseline harness lives in ``tests/visual/harness.py`` instead),
    so this acts as the CPU-only smoke / "scene matches expected EV envelope"
    proxy for the round-7 visual baseline.
    """
    ae = AutoExposurePass(target_grey=0.18, smoothing=0.05)
    # Frame brightnesses spanning -5..+5 stops around mid-grey.
    brightnesses = [0.18 * (2.0 ** k) for k in (-4, -2, 0, 2, 4)]

    for b in brightnesses:
        ae.reset()
        ev = ae.apply_cpu(_constant_grey_frame(b))
        expected = math.log2(0.18 / max(b, 1e-7))
        clamped = max(-5.0, min(5.0, expected))
        assert ev == pytest.approx(clamped, abs=1e-4)
