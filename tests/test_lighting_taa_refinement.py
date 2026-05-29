"""Regression tests for the TAA round-3 Karis luminance-inverse blend.

The new code path adds a `karis_weight` flag to `TAAPass` that switches the
temporal blend from the legacy ``mix(history, current, alpha)`` linear mix to
a Karis 2014 luminance-inverse weighted average.  These tests are entirely
CPU-side: they exercise the pure-numpy ``resolve_numpy`` reference that mirrors
the WGSL shader's blend math so that the regression suite needs no GPU.

The tests cover:

1. Uniform-buffer layout — flag is packed at the expected offset, legacy bytes
   are unchanged when the flag is off.
2. Backward compatibility — ``karis_weight=False`` reproduces the legacy
   blend bit-for-bit (within float tolerance).
3. Reduced ghosting on a moving bright sprite — the perceptual metric (mean
   absolute pixel diff against the ground-truth frame in the trailing region)
   drops by at least 20 %.
4. Visual baseline lock — a representative scene matches a recorded numpy
   golden master under ``tests/reference/taa_karis/``.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest

from slappyengine.post_process.taa import TAAPass


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _render_sprite_scene(
    sprite_x: int,
    *,
    height: int = 64,
    width: int = 64,
    background: float = 0.2,
    brightness: float = 8.0,
    radius_sq: int = 16,
    seed: int = 0,
) -> np.ndarray:
    """Deterministic scene: noisy grey background with a bright disk.

    A bright HDR-style disk is rendered at ``(sprite_x, 32)`` over a noisy
    grey background.  The noise is seeded so every call with the same seed
    produces identical pixels — this keeps the regression test stable.
    """
    rng = np.random.RandomState(seed)
    img = np.full((height, width, 3), background, dtype=np.float32)
    img += 0.05 * rng.rand(height, width, 3).astype(np.float32)
    ys, xs = np.indices((height, width))
    disk = (xs - sprite_x) ** 2 + (ys - height // 2) ** 2 < radius_sq
    img[disk] = brightness
    return img.astype(np.float32)


def _disk_mask(centre_x: int, *, height: int = 64, width: int = 64,
               radius_sq: int = 16) -> np.ndarray:
    ys, xs = np.indices((height, width))
    return (xs - centre_x) ** 2 + (ys - height // 2) ** 2 < radius_sq


# ---------------------------------------------------------------------------
# 1.  Uniform-buffer layout
# ---------------------------------------------------------------------------


def test_taa_uniform_layout_default_disables_karis():
    """Legacy callers (no flag) must see karis_weight = 0 in the uniform."""
    pass_ = TAAPass(alpha=0.1)
    pp = pass_.make_pass(frame_tex="frame", history_tex="history", motion_tex="motion")
    assert pp.raw_params_bytes is not None
    assert len(pp.raw_params_bytes) == 24, "TaaParams must be 24 bytes (round 3)"
    alpha, sharp, w, h, karis, _pad = struct.unpack("<ffIIII", pp.raw_params_bytes)
    assert alpha == pytest.approx(0.1)
    assert sharp == pytest.approx(0.0)
    assert w == 0 and h == 0  # executor splices these at runtime
    assert karis == 0, "default must keep the legacy blend"


def test_taa_uniform_layout_enables_karis_flag():
    pass_ = TAAPass(alpha=0.2, karis_weight=True)
    pp = pass_.make_pass(frame_tex="frame", history_tex="history", motion_tex="motion")
    _, _, _, _, karis, _ = struct.unpack("<ffIIII", pp.raw_params_bytes)
    assert karis == 1


# ---------------------------------------------------------------------------
# 2.  Backward-compatibility — flag OFF matches legacy linear blend
# ---------------------------------------------------------------------------


def test_taa_karis_off_matches_legacy_linear_blend():
    """With ``karis_weight=False`` the resolve must equal the legacy
    ``mix(history_clipped, current, alpha)`` blend within float tolerance.
    """
    np.random.seed(123)
    cur = np.random.rand(32, 32, 3).astype(np.float32) * 0.6 + 0.2
    hist = np.random.rand(32, 32, 3).astype(np.float32) * 0.6 + 0.2

    pass_legacy = TAAPass(alpha=0.1, karis_weight=False)
    out = pass_legacy.resolve_numpy(cur, hist)

    # Hand-rolled reference: replicate the YCoCg neighbourhood clip then
    # apply the linear blend.  This is the exact behaviour from rounds 1/2.
    padded = np.pad(cur, ((1, 1), (1, 1), (0, 0)), mode="edge")
    y = 0.25 * padded[..., 0] + 0.5 * padded[..., 1] + 0.25 * padded[..., 2]
    co = 0.5 * padded[..., 0] - 0.5 * padded[..., 2]
    cg = -0.25 * padded[..., 0] + 0.5 * padded[..., 1] - 0.25 * padded[..., 2]
    h, w, _ = cur.shape
    y_min = np.minimum.reduce([y[i:i + h, j:j + w] for i in range(3) for j in range(3)])
    y_max = np.maximum.reduce([y[i:i + h, j:j + w] for i in range(3) for j in range(3)])
    co_min = np.minimum.reduce([co[i:i + h, j:j + w] for i in range(3) for j in range(3)])
    co_max = np.maximum.reduce([co[i:i + h, j:j + w] for i in range(3) for j in range(3)])
    cg_min = np.minimum.reduce([cg[i:i + h, j:j + w] for i in range(3) for j in range(3)])
    cg_max = np.maximum.reduce([cg[i:i + h, j:j + w] for i in range(3) for j in range(3)])
    hr, hg, hb = hist[..., 0], hist[..., 1], hist[..., 2]
    hy = np.clip(0.25 * hr + 0.5 * hg + 0.25 * hb, y_min, y_max)
    hco = np.clip(0.5 * hr - 0.5 * hb, co_min, co_max)
    hcg = np.clip(-0.25 * hr + 0.5 * hg - 0.25 * hb, cg_min, cg_max)
    tmp = hy - hcg
    hist_clipped = np.stack([tmp + hco, hy + hcg, tmp - hco], axis=-1)
    legacy = np.maximum(0.9 * hist_clipped + 0.1 * cur, 0.0).astype(np.float32)

    np.testing.assert_allclose(out, legacy, atol=1e-6)


# ---------------------------------------------------------------------------
# 3.  Reduced ghosting on a bright moving sprite
# ---------------------------------------------------------------------------


def test_taa_karis_reduces_sprite_trailing_ghost_by_20_percent():
    """The headline regression: ghosting at the trailing edge of a moving
    bright sprite must drop by at least 20 % with the Karis blend on.
    """
    xs = [14, 17, 20, 24, 28]
    H, W = 64, 64
    ground_truth = _render_sprite_scene(xs[-1], height=H, width=W)

    pass_legacy = TAAPass(alpha=0.1, karis_weight=False)
    pass_karis = TAAPass(alpha=0.1, karis_weight=True)
    hist_l = _render_sprite_scene(xs[0], height=H, width=W)
    hist_k = hist_l.copy()
    for x in xs[1:]:
        cur = _render_sprite_scene(x, height=H, width=W)
        hist_l = pass_legacy.resolve_numpy(cur, hist_l)
        hist_k = pass_karis.resolve_numpy(cur, hist_k)

    # Trailing region: union of all past sprite positions, minus the
    # current one.  These pixels are where ghosting would show up.
    trailing = np.zeros((H, W), dtype=bool)
    for x in xs[:-1]:
        trailing |= _disk_mask(x, height=H, width=W)
    trailing &= ~_disk_mask(xs[-1], height=H, width=W)
    assert trailing.sum() > 10, "test geometry must leave a measurable trail"

    ghost_legacy = float(np.mean(np.abs(hist_l[trailing] - ground_truth[trailing])))
    ghost_karis = float(np.mean(np.abs(hist_k[trailing] - ground_truth[trailing])))

    # Sanity: legacy must show some residual ghost (otherwise the test is
    # meaningless because there's nothing for Karis to improve).
    assert ghost_legacy > 0.05, (
        f"control run shows no ghosting ({ghost_legacy:.4f}); "
        "test scene needs a brighter sprite"
    )
    # Headline assertion.
    reduction = 1.0 - ghost_karis / ghost_legacy
    assert reduction >= 0.20, (
        f"Karis blend should reduce trailing-edge ghost by ≥ 20 %, "
        f"got {reduction * 100:.1f}% (legacy={ghost_legacy:.4f}, "
        f"karis={ghost_karis:.4f})"
    )


# ---------------------------------------------------------------------------
# 4.  Visual baseline lock — golden numpy snapshot
# ---------------------------------------------------------------------------


_BASELINE_PATH = (
    Path(__file__).parent / "reference" / "taa_karis" / "moving_sprite_resolved.npy"
)


def _render_baseline_scene() -> np.ndarray:
    """A deterministic, representative scene used for the visual baseline."""
    xs = [14, 17, 20, 24, 28]
    H, W = 64, 64
    pass_karis = TAAPass(alpha=0.1, karis_weight=True)
    hist = _render_sprite_scene(xs[0], height=H, width=W)
    for x in xs[1:]:
        cur = _render_sprite_scene(x, height=H, width=W)
        hist = pass_karis.resolve_numpy(cur, hist)
    return hist


def test_taa_karis_visual_baseline_matches():
    """Locks the Karis-resolved frame against a recorded golden master.

    The reference lives at ``tests/reference/taa_karis/moving_sprite_resolved.npy``
    so any unintended change to the temporal blend will trip this guard.
    The tolerance (mean abs diff ≤ 1e-5) is tight because the scene is
    deterministic — both the noise seed and the resolve are pure-numpy.
    """
    rendered = _render_baseline_scene()

    if not _BASELINE_PATH.exists():
        _BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        np.save(_BASELINE_PATH, rendered)
        pytest.skip(
            f"baseline written to {_BASELINE_PATH}; re-run to verify match"
        )

    baseline = np.load(_BASELINE_PATH)
    assert baseline.shape == rendered.shape, (
        f"baseline shape {baseline.shape} does not match rendered "
        f"{rendered.shape}"
    )
    diff = float(np.mean(np.abs(baseline - rendered)))
    assert diff <= 1e-5, (
        f"visual baseline mismatch: mean abs diff {diff:.6e} > 1e-5; "
        f"either the resolve changed or the seed broke determinism"
    )
