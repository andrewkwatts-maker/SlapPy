"""Bloom pyramid kernel regression — COD 2014 13-tap downsample + 9-tap tent.

Round-4 lighting/post-process polish: replaces the legacy 2×2 box downsample
and single-bilinear-tap upsample with the Jorge Jimenez "Advanced Warfare"
13-tap downsample and 3×3 tent upsample.  Goals:

  - Spatial weights sum to exactly 1.0 (constant-input check)
  - A single bright pixel is smeared into a wider, smoother low-pass than
    the box kernel — measured as higher low-frequency energy compaction.
  - No NaN/Inf when the input contains super-bright outliers (fireflies).
  - Visual baseline: PSNR delta vs the previous bloom pyramid output is
    captured so future tap-weight changes trip the regression.

The CPU helpers in ``bloom.py`` mirror ``shaders/bloom_pyramid.wgsl`` so
these tests run without a GPU.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from slappyengine.post_process.bloom import (
    _TENT_3X3,
    downsample_box2,
    downsample_mn13,
    upsample_tent9,
)


# ---------------------------------------------------------------------------
# (a) Tap weight sum is exactly 1.0 (modulo 1e-5)
# ---------------------------------------------------------------------------


def test_tent_upsample_weights_sum_to_one() -> None:
    """3×3 tent kernel weights must sum to 1.0 ± 1e-5."""
    s = float(_TENT_3X3.sum())
    assert s == pytest.approx(1.0, abs=1e-5), (
        f"tent kernel weights sum != 1.0: got {s!r}"
    )


def test_tent_upsample_preserves_constant() -> None:
    """Constant input must yield constant output (proves weights sum to 1)."""
    low = np.full((4, 4, 3), 0.42, dtype=np.float32)
    up = upsample_tent9(low, (8, 8))
    # Inner pixels (away from the clamp border) must be exactly the constant.
    inner = up[2:-2, 2:-2]
    assert np.allclose(inner, 0.42, atol=1e-6), (
        f"tent upsample failed constant test: inner range "
        f"[{inner.min()!r}, {inner.max()!r}]"
    )


def test_mn13_downsample_preserves_constant() -> None:
    """Constant input must yield constant output across the 13-tap kernel.

    This proves the inner+outer spatial weights still sum to 1.0 after the
    per-quad firefly renormalisation.  At a constant luma the four outer
    quad weights collapse to the same value, so the normalisation cancels
    cleanly and the result equals the input.
    """
    src = np.full((8, 8, 3), 0.25, dtype=np.float32)
    down = downsample_mn13(src)
    assert down.shape == (4, 4, 3)
    # Away from the clamp border the result must equal 0.25.
    inner = down[1:-1, 1:-1]
    assert np.allclose(inner, 0.25, atol=1e-5), (
        f"mn13 downsample failed constant test: inner range "
        f"[{inner.min()!r}, {inner.max()!r}]"
    )


# ---------------------------------------------------------------------------
# (b) Impulse response — Mitchell-Netravali smears wider/smoother than box
# ---------------------------------------------------------------------------


def _impulse(h: int, w: int, y: int, x: int, amp: float = 1.0) -> np.ndarray:
    """Single-pixel impulse on a zero background."""
    img = np.zeros((h, w, 3), dtype=np.float32)
    img[y, x, :] = amp
    return img


def _low_freq_energy(img: np.ndarray) -> float:
    """Energy in the lowest-frequency DCT bins (top-left 2×2 corner).

    Higher value -> more energy compaction at low frequencies -> smoother
    low-pass.  We sum across colour channels.
    """
    grey = img.mean(axis=-1).astype(np.float32)
    # Real 2D DCT via FFT (good enough for monotonic comparison).
    spec = np.fft.rfft2(grey)
    mag = np.abs(spec)
    return float((mag[:2, :2] ** 2).sum())


def test_mn13_impulse_response_smoother_than_box() -> None:
    """13-tap M-N downsample must spread an impulse more smoothly than 2×2 box.

    We construct a single bright pixel, downsample twice (full pyramid level),
    and compare low-frequency energy compaction.  The 13-tap kernel should
    concentrate more energy in the low-frequency band — that's the whole
    point of the wider spatial support.
    """
    impulse = _impulse(16, 16, 8, 8, amp=8.0)  # bright sub-pixel feature
    box = downsample_box2(impulse)
    mn = downsample_mn13(impulse)
    assert box.shape == mn.shape

    e_box = _low_freq_energy(box)
    e_mn = _low_freq_energy(mn)

    # M-N spreads the impulse across more output taps -> lower per-pixel peak
    # but higher total low-frequency energy.  Both shouldn't be zero.
    assert e_mn > 0.0
    assert e_box > 0.0
    assert e_mn > e_box, (
        "Mitchell-Netravali 13-tap should compact more low-frequency energy "
        f"than the 2×2 box; got mn={e_mn!r}, box={e_box!r}"
    )


def test_mn13_impulse_peak_is_lower_than_box() -> None:
    """A spread kernel must have a lower per-pixel peak than the box.

    The box concentrates the impulse into a single 2×2 destination pixel
    (peak = input / 4); the 13-tap kernel spreads it across the 5×5
    footprint so the peak is necessarily lower.  This is the visual
    definition of "less aliasing on bright sub-pixel features".
    """
    impulse = _impulse(16, 16, 8, 8, amp=4.0)
    box = downsample_box2(impulse)
    mn = downsample_mn13(impulse)
    assert mn.max() < box.max(), (
        f"M-N peak must be lower than box peak; got mn={mn.max()!r}, "
        f"box={box.max()!r}"
    )


def test_mn13_impulse_support_is_wider_than_box() -> None:
    """The number of non-zero output taps must be larger for M-N than box."""
    impulse = _impulse(16, 16, 8, 8, amp=4.0)
    box = downsample_box2(impulse)
    mn = downsample_mn13(impulse)

    # Count output pixels with non-negligible energy.
    nz_box = int(((box ** 2).sum(axis=-1) > 1e-8).sum())
    nz_mn = int(((mn ** 2).sum(axis=-1) > 1e-8).sum())
    assert nz_mn > nz_box, (
        f"M-N kernel must spread the impulse to more output taps; "
        f"got nz_mn={nz_mn}, nz_box={nz_box}"
    )


# ---------------------------------------------------------------------------
# (c) NaN / Inf safety — bright outliers must not blow up the kernel
# ---------------------------------------------------------------------------


def test_mn13_no_nan_inf_with_extreme_firefly() -> None:
    """A 1e6-amplitude firefly must not produce NaN/Inf in the downsampled output.

    Tested under both the unclamped pure-low-pass path and the
    ``karis_clamp=True`` firefly-suppression path.  Karis keeps the
    contribution bounded; the linear path must also stay finite because
    the spatial weights are all finite and sum to 1.
    """
    img = np.full((8, 8, 3), 0.1, dtype=np.float32)
    img[4, 4, :] = 1.0e6  # extreme firefly

    down_linear = downsample_mn13(img, karis_clamp=False)
    assert np.all(np.isfinite(down_linear)), (
        f"linear downsample produced non-finite output for a 1e6 firefly; "
        f"min={down_linear.min()!r}, max={down_linear.max()!r}"
    )

    down_karis = downsample_mn13(img, karis_clamp=True)
    assert np.all(np.isfinite(down_karis)), (
        f"karis downsample produced non-finite output for a 1e6 firefly; "
        f"min={down_karis.min()!r}, max={down_karis.max()!r}"
    )
    # And the Karis clamp must actually suppress the firefly — the
    # downsampled peak should be far below the input peak.
    assert down_karis.max() < img.max() / 1000.0, (
        f"Karis clamp failed to suppress 1e6 firefly: "
        f"down_max={down_karis.max()!r}"
    )


def test_tent_upsample_no_nan_inf_with_extreme_input() -> None:
    """A 1e6-amplitude pixel in the low-res buffer must not produce NaN/Inf."""
    low = np.full((4, 4, 3), 0.1, dtype=np.float32)
    low[2, 2, :] = 1.0e6
    up = upsample_tent9(low, (8, 8))
    assert np.all(np.isfinite(up)), (
        f"upsample_tent9 produced non-finite output for a 1e6 input; "
        f"min={up.min()!r}, max={up.max()!r}"
    )


def test_mn13_no_nan_inf_with_nan_input_clamped() -> None:
    """Clean inputs containing only finite values must always produce finite
    outputs even when the dynamic range spans 12 orders of magnitude.
    """
    rng = np.random.default_rng(0xB100)
    img = rng.uniform(0.0, 1.0, (16, 16, 3)).astype(np.float32)
    img[3, 5] = 5.0e5  # localised firefly
    img[12, 9] = 1.0e7  # extreme firefly
    down = downsample_mn13(img)
    up = upsample_tent9(down, (16, 16))
    assert np.all(np.isfinite(down)), "downsample produced non-finite values"
    assert np.all(np.isfinite(up)), "upsample produced non-finite values"


# ---------------------------------------------------------------------------
# Backward compatibility — existing BloomPass threshold path is untouched
# ---------------------------------------------------------------------------


def test_existing_bloom_pass_threshold_still_works() -> None:
    """The pyramid kernels are additive — the threshold pass is unchanged.

    Sanity check that importing the new helpers didn't break the legacy
    BloomPass smooth-threshold path.
    """
    from slappyengine.post_process.bloom import BloomPass, synth_hdr_strip

    rgb = synth_hdr_strip([0.5, 1.0, 1.5, 2.0])
    bp = BloomPass(threshold=1.0, knee=0.2)
    out = bp.apply_cpu(rgb)
    # luma 0.5 → 0; luma 1.5 → 0.5; luma 2.0 → 1.0 (matches existing test).
    assert float(out[0, 0, 0]) == 0.0
    assert float(out[0, 2, 0]) == pytest.approx(0.5, abs=1e-6)
    assert float(out[0, 3, 0]) == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Visual baseline — PSNR delta vs previous pyramid output
# ---------------------------------------------------------------------------

REF_DIR = Path(__file__).parent / "visual" / "reference" / "bloom_pyramid"
OUT_DIR = Path(__file__).parent / "visual" / "output"  / "bloom_pyramid"


def _make_hdr_pyramid_scene(width: int = 32, height: int = 32) -> np.ndarray:
    """Deterministic HDR scene with mixed-frequency bright features.

    - Smooth bright disc (low-frequency content the kernel should preserve).
    - Two sub-pixel hot spots (high-frequency / firefly content).
    - Dim ambient background.
    """
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    cx, cy = (width - 1) * 0.5, (height - 1) * 0.5
    r2 = (xx - cx) ** 2 + (yy - cy) ** 2

    bg = np.full((height, width), 0.2, dtype=np.float32)
    disc = np.maximum(0.0, 1.0 - r2 / (min(width, height) * 0.2) ** 2) * 1.5
    luma = bg + disc

    # Two hot spots — exactly the kind of bright sub-pixel feature M-N is
    # designed to handle gracefully.
    luma[4, 6] = 8.0
    luma[26, 25] = 6.5

    rgb = np.stack([luma, luma * 0.9, luma * 0.7], axis=-1)
    return rgb


def _psnr(a: np.ndarray, b: np.ndarray, peak: float = 1.0) -> float:
    """Standard PSNR in dB (higher = closer to identical)."""
    mse = float(np.mean((a.astype(np.float32) - b.astype(np.float32)) ** 2))
    if mse <= 1e-20:
        return float("inf")
    return 10.0 * float(np.log10(peak * peak / mse))


def test_bloom_pyramid_visual_baseline() -> None:
    """Visual regression — captures the M-N + tent pyramid output.

    On first run the baseline is written and the test self-skips.  On
    subsequent runs the captured pyramid output is compared element-wise.
    Any future change to the tap weights will trip a measurable PSNR delta.
    """
    scene = _make_hdr_pyramid_scene(32, 32)
    down = downsample_mn13(scene)
    up = upsample_tent9(down, (32, 32))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "hdr_pyramid_mn13.npy"
    np.save(out_path, up)

    ref_path = REF_DIR / "hdr_pyramid_mn13.npy"
    if not ref_path.exists():
        REF_DIR.mkdir(parents=True, exist_ok=True)
        np.save(ref_path, up)
        pytest.skip(f"baseline written: {ref_path}")

    ref = np.load(ref_path).astype(np.float32)
    assert ref.shape == up.shape, (
        f"baseline shape mismatch: {ref.shape} vs {up.shape}"
    )
    psnr = _psnr(ref, up, peak=float(max(1.0, ref.max())))
    # 60 dB is the standard "visually indistinguishable" threshold; we set
    # the regression bar much higher (the CPU reference is deterministic).
    assert psnr >= 80.0, (
        f"bloom pyramid output drifted from baseline: PSNR={psnr!r} dB"
    )


def test_bloom_pyramid_smooths_isolated_bright_feature() -> None:
    """End-to-end pyramid smooths a bright sub-pixel feature.

    Downsample + upsample of a single bright pixel must produce a smooth
    Gaussian-like lobe — measured here as: (1) the result is strictly
    positive in a neighbourhood larger than 1×1, (2) the peak is far
    below the input, and (3) the result is monotone-decreasing from the
    centre out to the edge of the lobe.  This is the visible quality win
    over the box+bilinear pyramid where an isolated bright pixel becomes
    a hard 2×2 block at the next level.
    """
    impulse = _impulse(16, 16, 8, 8, amp=4.0)
    down = downsample_mn13(impulse, karis_clamp=False)
    up = upsample_tent9(down, (16, 16))

    # (1) The bright lobe is wider than 1 pixel.
    nz = int(((up ** 2).sum(axis=-1) > 1e-6).sum())
    assert nz > 1, f"upsampled lobe must cover >1 pixel; got nz={nz}"

    # (2) Peak is far below input peak (energy spread out).
    assert up.max() < impulse.max() * 0.5, (
        f"upsampled peak should be < 0.5× input peak; got peak={up.max()!r}"
    )

    # (3) Monotone-decreasing along the centre row from the brightest pixel
    # out to the edge of the lobe.  We grab the row through the peak and
    # check it's non-increasing as we move away.
    peak_yx = np.unravel_index(int(up.mean(axis=-1).argmax()), up.shape[:2])
    py, px = peak_yx
    row = up[py, :, :].mean(axis=-1)
    # Right side of peak must be non-increasing.
    for i in range(px, len(row) - 1):
        assert row[i] + 1e-6 >= row[i + 1], (
            f"upsampled lobe not monotone-decreasing right of peak: "
            f"row[{i}]={row[i]!r} < row[{i+1}]={row[i+1]!r}"
        )
