"""Regression tests for the TAA round-5 motion-vector-aware history rejection.

Round 5 (Karis Siggraph 2014 + Andersson INSIDE 2015) consults the
depth and normal G-buffers at the *reprojected* previous-frame location
and drops the history sample when geometry has changed there.  The
colour-clamp AABB (rounds 1-4) cannot catch a stale sample whose colour
happens to sit inside the current neighbourhood envelope — depth and
normals are the canonical secondary signals.

The targeted artifact is **disocclusion ghosting**: a camera pan reveals
geometry that was hidden behind an occluder last frame.  The motion
vectors point to a location that wasn't visible, so the colour read
from history is whatever was rendered there (the occluder).  Without
depth/normal rejection the temporal blend smears that stale occluder
colour across the freshly-revealed surface, producing a multi-frame
ghost band.

All tests run on the pure-numpy ``resolve_numpy`` reference that mirrors
the WGSL shader, so no GPU is required.
"""
from __future__ import annotations

import numpy as np
import pytest

from slappyengine.post_process.taa import TAAPass


# ---------------------------------------------------------------------------
# Synthetic disocclusion scene helpers
# ---------------------------------------------------------------------------


def _make_disocclusion_scene(
    *,
    height: int = 32,
    width: int = 32,
    occluder_left_prev: int = 8,
    occluder_left_cur: int = 16,
    occluder_width: int = 8,
    occluder_color: float = 0.9,
    background_color: float = 0.15,
    occluder_depth: float = 0.2,
    background_depth: float = 0.8,
    seed: int = 0,
) -> dict:
    """Camera-pan disocclusion: a foreground occluder slides right.

    Returns a dict with keys ``current``, ``history``, ``motion_uv``,
    ``current_depth``, ``history_depth``, ``current_normal``,
    ``history_normal``, ``disocclusion_band`` (a bool mask marking the
    columns that were occluder last frame and background this frame —
    the canonical disocclusion region where rejection should fire).

    Geometry:
        - Background: uniform colour, depth = ``background_depth``,
          normal = +Z (camera-facing).
        - Occluder: vertical band, colour ``occluder_color``, depth =
          ``occluder_depth`` (in front), normal = +Z.

    Between the two frames the occluder moved from
    ``[occluder_left_prev : occluder_left_prev + occluder_width]`` to
    ``[occluder_left_cur : occluder_left_cur + occluder_width]``.  The
    motion vectors are *background* motion (zero) — i.e. the camera
    panned and the background is static in world-space.  This is the
    classic case where naive colour-only TAA samples the occluder's
    colour for a freshly-disoccluded background pixel.
    """
    rng = np.random.RandomState(seed)

    def _paint(occ_left: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        img = np.full((height, width, 3), background_color, dtype=np.float32)
        # Subtle noise so the YCoCg AABB has non-zero volume (otherwise
        # the variance clip collapses to a single point and trivially
        # rejects everything by clamping to the mean).
        img += 0.02 * rng.rand(height, width, 3).astype(np.float32)
        depth = np.full((height, width), background_depth, dtype=np.float32)
        normal = np.zeros((height, width, 3), dtype=np.float32)
        normal[..., 2] = 1.0  # camera-facing
        occ_cols = slice(occ_left, occ_left + occluder_width)
        img[:, occ_cols, :] = occluder_color
        depth[:, occ_cols] = occluder_depth
        # Same normal direction (both planes face the camera) — the
        # disocclusion signal here is depth, not normal.
        return img, depth, normal

    current, current_depth, current_normal = _paint(occluder_left_cur)
    history, history_depth, history_normal = _paint(occluder_left_prev)

    # Motion vector = zero everywhere (background is what we're testing;
    # the moving occluder's correct MV is irrelevant for this scene).
    motion_uv = np.zeros((height, width, 2), dtype=np.float32)

    # The disocclusion band is the columns that were occluder last frame
    # but are background this frame — those reprojected reads will hit
    # the occluder colour/depth in history.
    band = np.zeros(width, dtype=bool)
    prev_occ = slice(occluder_left_prev, occluder_left_prev + occluder_width)
    cur_occ  = slice(occluder_left_cur,  occluder_left_cur  + occluder_width)
    band[prev_occ] = True
    band[cur_occ]  = False  # still occluder in current frame — not a disocclusion
    disocclusion_band = np.broadcast_to(band[None, :], (height, width)).copy()

    return {
        "current": current,
        "history": history,
        "motion_uv": motion_uv,
        "current_depth": current_depth,
        "history_depth": history_depth,
        "current_normal": current_normal,
        "history_normal": history_normal,
        "disocclusion_band": disocclusion_band,
        "background_color": background_color,
    }


# ---------------------------------------------------------------------------
# 1. Rejection rate on a disocclusion band
# ---------------------------------------------------------------------------


def test_depth_rejection_fires_on_disocclusion_band() -> None:
    """In a disoccluded region the depth-disagreement gate must reject
    at least 30 % of the pixels (target documented in Sprint 5R brief).

    Scene: foreground occluder pans right by 8 px.  Reprojected
    history samples on the disoccluded columns (8..15) read the
    occluder depth from history (0.2) but the current depth is the
    background (0.8) — |Δd| = 0.6 ≫ 0.1 threshold → reject.
    """
    scene = _make_disocclusion_scene()
    taa = TAAPass(
        alpha=0.1,
        # Isolate the depth gate by disabling the normal gate (the
        # synthetic scene uses identical normals across frames so the
        # normal gate would be a no-op anyway, but pin the policy
        # explicitly for clarity).
        reject_on_depth_disocclusion=True,
        depth_disocclusion_threshold=0.1,
        reject_on_normal_disocclusion=False,
    )
    _, mask = taa.resolve_numpy(
        scene["current"],
        scene["history"],
        motion_uv=scene["motion_uv"],
        current_depth=scene["current_depth"],
        history_depth=scene["history_depth"],
        return_rejection_mask=True,
    )
    band = scene["disocclusion_band"]
    band_rejections = mask & band
    rate = float(band_rejections.sum()) / float(band.sum())
    assert rate >= 0.30, (
        f"depth rejection should fire on >= 30 % of the disocclusion "
        f"band, got {rate * 100:.1f}%"
    )


def test_normal_rejection_fires_on_normal_flip() -> None:
    """Normal-disagreement gate must catch surface flips even when
    depth is unchanged.

    Scene: a wall behind a thin pole.  Current and history depths are
    identical (the pole and wall happen to be at the same depth), but
    the surface normal flipped from +X (pole side) to +Z (wall) — a
    25.5 % silhouette disocclusion.
    """
    H, W = 16, 16
    cur = np.full((H, W, 3), 0.3, dtype=np.float32)
    hist = np.full((H, W, 3), 0.6, dtype=np.float32)  # stale wall colour
    depth = np.full((H, W), 0.5, dtype=np.float32)
    cur_n = np.zeros((H, W, 3), dtype=np.float32)
    cur_n[..., 2] = 1.0   # wall: +Z
    hist_n = np.zeros((H, W, 3), dtype=np.float32)
    hist_n[..., 0] = 1.0  # pole: +X — orthogonal to wall, dot = 0
    motion_uv = np.zeros((H, W, 2), dtype=np.float32)

    taa = TAAPass(
        alpha=0.1,
        reject_on_depth_disocclusion=False,    # isolate the normal gate
        reject_on_normal_disocclusion=True,
        normal_disocclusion_threshold=0.9,
    )
    _, mask = taa.resolve_numpy(
        cur, hist,
        motion_uv=motion_uv,
        current_normal=cur_n,
        history_normal=hist_n,
        return_rejection_mask=True,
    )
    assert mask.all(), (
        "every pixel has an orthogonal normal flip (dot = 0 < 0.9) — "
        "rejection should fire everywhere"
    )


# ---------------------------------------------------------------------------
# 2. No false rejections on static scenes
# ---------------------------------------------------------------------------


def test_no_rejection_on_static_scene() -> None:
    """On an identical-frame static scene the rejection mask must be
    entirely zero — depth and normals match, motion is zero, so the
    gates have no reason to fire.

    A false-positive here would defeat the whole point of TAA: the
    history would never accumulate and the output would be noisy
    forever.
    """
    H, W = 24, 24
    rng = np.random.RandomState(13)
    cur = rng.rand(H, W, 3).astype(np.float32) * 0.5 + 0.2
    hist = cur.copy()
    depth = np.full((H, W), 0.5, dtype=np.float32)
    normal = np.zeros((H, W, 3), dtype=np.float32)
    normal[..., 2] = 1.0
    motion_uv = np.zeros((H, W, 2), dtype=np.float32)

    taa = TAAPass(
        alpha=0.1,
        reject_on_depth_disocclusion=True,
        reject_on_normal_disocclusion=True,
    )
    _, mask = taa.resolve_numpy(
        cur, hist,
        motion_uv=motion_uv,
        current_depth=depth,
        history_depth=depth,
        current_normal=normal,
        history_normal=normal,
        return_rejection_mask=True,
    )
    assert not mask.any(), (
        f"static scene must produce zero rejections; got "
        f"{int(mask.sum())} false-positive rejections"
    )


def test_below_threshold_depth_break_does_not_reject() -> None:
    """A small depth gradient (smooth surface curvature) must sit below
    the rejection threshold — otherwise TAA would constantly reset on
    every curved wall.

    Tests the *threshold* part of the contract specifically: the gate
    must use ``> threshold``, not ``> 0``.
    """
    H, W = 16, 16
    cur = np.full((H, W, 3), 0.4, dtype=np.float32)
    hist = cur.copy()
    cur_depth = np.full((H, W), 0.5, dtype=np.float32)
    # Smooth depth ramp: 0.5 .. 0.55 — well below the 0.1 threshold.
    hist_depth = cur_depth + np.linspace(0.0, 0.05, W, dtype=np.float32)[None, :]
    motion_uv = np.zeros((H, W, 2), dtype=np.float32)

    taa = TAAPass(
        alpha=0.1,
        reject_on_depth_disocclusion=True,
        depth_disocclusion_threshold=0.1,
        reject_on_normal_disocclusion=False,
    )
    _, mask = taa.resolve_numpy(
        cur, hist,
        motion_uv=motion_uv,
        current_depth=cur_depth,
        history_depth=hist_depth,
        return_rejection_mask=True,
    )
    assert not mask.any(), (
        f"smooth depth gradient must stay below the threshold; got "
        f"{int(mask.sum())} false rejections"
    )


# ---------------------------------------------------------------------------
# 3. Headline PSNR — round 5 beats round 4 on disocclusion bands
# ---------------------------------------------------------------------------


def _psnr(reference: np.ndarray, candidate: np.ndarray) -> float:
    """Peak signal-to-noise ratio (HDR-safe, peak = max(reference))."""
    mse = float(np.mean((reference - candidate) ** 2))
    if mse <= 1.0e-12:
        return 120.0
    peak = float(np.max(reference)) or 1.0
    return 10.0 * float(np.log10(peak * peak / mse))


def test_round5_improves_disocclusion_psnr_over_round4() -> None:
    """End-to-end PSNR over the disocclusion band: round 5 (motion-aware
    rejection on) must measurably out-PSNR round 4 (rejection off).

    Methodology:
      - Render the disocclusion scene above as the "current" frame.
      - Use a history frame that still shows the occluder at its old
        position (the classic 1-frame stale).
      - Resolve once with round 4 (depth/normal rejection OFF) and
        once with round 5 (both gates ON).
      - Ground truth on the disocclusion band is the background
        colour ``0.15`` — the round-5 resolve must converge closer to
        it because the depth gate ejects the occluder ghost outright.
    """
    scene = _make_disocclusion_scene()
    band = scene["disocclusion_band"]
    bg = scene["background_color"]

    round4 = TAAPass(
        alpha=0.1,
        tight_variance_clip=True,
        variance_clip_gamma=1.0,
        reject_on_depth_disocclusion=False,
        reject_on_normal_disocclusion=False,
    )
    round5 = TAAPass(
        alpha=0.1,
        tight_variance_clip=True,
        variance_clip_gamma=1.0,
        reject_on_depth_disocclusion=True,
        depth_disocclusion_threshold=0.1,
        reject_on_normal_disocclusion=True,
        normal_disocclusion_threshold=0.9,
    )

    out4 = round4.resolve_numpy(
        scene["current"], scene["history"], motion_uv=scene["motion_uv"],
    )
    out5 = round5.resolve_numpy(
        scene["current"], scene["history"], motion_uv=scene["motion_uv"],
        current_depth=scene["current_depth"],
        history_depth=scene["history_depth"],
        current_normal=scene["current_normal"],
        history_normal=scene["history_normal"],
    )

    gt = np.full_like(scene["current"], bg)
    band3 = np.broadcast_to(band[..., None], scene["current"].shape)
    psnr4 = _psnr(gt[band3].reshape(-1, 3), out4[band3].reshape(-1, 3))
    psnr5 = _psnr(gt[band3].reshape(-1, 3), out5[band3].reshape(-1, 3))

    delta = psnr5 - psnr4
    assert delta >= 1.0, (
        f"round-5 disocclusion rejection should improve disocclusion PSNR "
        f">= 1 dB over round-4; got delta={delta:.2f} dB "
        f"(round4={psnr4:.2f}, round5={psnr5:.2f})"
    )


# ---------------------------------------------------------------------------
# 4. Validation contract
# ---------------------------------------------------------------------------


def test_taa_rejects_non_bool_depth_flag() -> None:
    with pytest.raises(TypeError, match="reject_on_depth_disocclusion"):
        TAAPass(reject_on_depth_disocclusion=1)  # type: ignore[arg-type]


def test_taa_rejects_non_bool_normal_flag() -> None:
    with pytest.raises(TypeError, match="reject_on_normal_disocclusion"):
        TAAPass(reject_on_normal_disocclusion=0)  # type: ignore[arg-type]


def test_taa_rejects_negative_depth_threshold() -> None:
    with pytest.raises(ValueError, match="depth_disocclusion_threshold"):
        TAAPass(depth_disocclusion_threshold=-0.01)


def test_taa_rejects_negative_normal_threshold() -> None:
    with pytest.raises(ValueError, match="normal_disocclusion_threshold"):
        TAAPass(normal_disocclusion_threshold=-0.5)


def test_taa_round5_defaults_on() -> None:
    """Both rejection toggles default on (Round 5 is the v0.3.2 default)."""
    p = TAAPass()
    assert p.reject_on_depth_disocclusion is True
    assert p.reject_on_normal_disocclusion is True
    assert p.depth_disocclusion_threshold == pytest.approx(0.1)
    assert p.normal_disocclusion_threshold == pytest.approx(0.9)
