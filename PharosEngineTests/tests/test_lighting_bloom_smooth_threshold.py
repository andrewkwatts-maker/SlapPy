"""Lottes 2017 smooth-threshold bloom — regression + visual baseline.

Round-3 lighting/post-process work: replaces the legacy hard luminance
cutoff with a soft-knee curve so bright pixels ramp into the bloom
buffer instead of popping on/off binary at the threshold boundary.

These tests run entirely on the CPU reference (``BloomPass.apply_cpu``)
which mirrors ``shaders/bloom_threshold.wgsl`` arithmetic exactly.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pharos_engine.post_process.bloom import (
    BloomPass,
    smooth_threshold,
    synth_hdr_strip,
)


# ---------------------------------------------------------------------------
# Synthetic HDR strip — the five-pixel regression spec
# ---------------------------------------------------------------------------

# Threshold and knee chosen so the ramp band is (0.8, 1.2) — pixel 1.0 sits
# exactly on the legacy hard-cutoff boundary, 1.1 is mid-ramp, 1.2 is the
# upper edge of the knee, and 2.0 is firmly in the linear regime.
REG_THRESHOLD = 1.0
REG_KNEE = 0.2
REG_LUMAS = (0.5, 1.0, 1.1, 1.2, 2.0)


def test_smooth_threshold_below_cutoff_is_zero() -> None:
    """Pixel at luma 0.5 must contribute exactly zero bloom."""
    rgb = synth_hdr_strip([0.5])
    out = smooth_threshold(rgb, REG_THRESHOLD, REG_KNEE)
    assert np.allclose(out, 0.0), f"expected 0 below threshold, got {out!r}"


def test_smooth_threshold_at_cutoff_is_barely_nonzero() -> None:
    """Pixel at luma == threshold must be small but strictly positive.

    With knee=0.2 the soft branch at luma=1.0 evaluates to
    ``0.2**2 / (4*0.2 + eps) = 0.04 / 0.8 = 0.05`` luma units of contribution,
    so the extracted colour is ~5% of input.
    """
    rgb = synth_hdr_strip([1.0])
    out = smooth_threshold(rgb, REG_THRESHOLD, REG_KNEE)
    val = float(out.max())
    assert 0.0 < val < 0.1, f"expected tiny nonzero at threshold, got {val!r}"
    # Lottes formula gives exactly 0.05 here.
    assert val == pytest.approx(0.05, abs=1e-6)


def test_smooth_threshold_in_knee_ramped() -> None:
    """Pixel at luma 1.1 (mid-knee) must sit between 0 and full contribution.

    At luma=1.1 the soft term is ``(1.1 - 1.0 + 0.2)**2 / 0.8 = 0.09/0.8 = 0.1125``.
    The hard term is ``0.1``.  max(soft, hard) = 0.1125.
    """
    rgb = synth_hdr_strip([1.1])
    out = smooth_threshold(rgb, REG_THRESHOLD, REG_KNEE)
    val = float(out.max())
    # Bounds: bigger than the at-threshold value, smaller than 2.0 case.
    assert val > 0.05
    assert val < 1.0
    assert val == pytest.approx(0.1125, abs=1e-6)


def test_smooth_threshold_monotone_increasing_across_knee() -> None:
    """Bloom contribution must be non-decreasing along the ramp."""
    rgb = synth_hdr_strip(REG_LUMAS)
    out = smooth_threshold(rgb, REG_THRESHOLD, REG_KNEE)
    contribs = out[0, :, 0]  # grey strip — pick any channel
    for i in range(len(contribs) - 1):
        assert contribs[i] <= contribs[i + 1] + 1e-7, (
            f"non-monotone at idx {i}: "
            f"{contribs[i]!r} > {contribs[i+1]!r}"
        )
    # And the 1.2 sample must be >= the 1.1 sample (explicit task spec).
    assert contribs[3] >= contribs[2]


def test_smooth_threshold_above_knee_matches_hard() -> None:
    """Well above the knee (luma=2.0), soft and hard agree exactly.

    Once ``luma - threshold > knee`` the soft branch saturates and the
    ``max`` clamp picks the linear (hard) branch.  The extracted colour
    equals ``input * (luma - threshold) / luma``.
    """
    rgb = synth_hdr_strip([2.0])
    soft_out = smooth_threshold(rgb, REG_THRESHOLD, REG_KNEE)
    hard_out = smooth_threshold(rgb, REG_THRESHOLD, 0.0)
    assert np.allclose(soft_out, hard_out, atol=1e-7)
    # Numeric check: (2.0 - 1.0) / 2.0 == 0.5, applied to colour 2.0 → 1.0.
    assert float(soft_out.max()) == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Backward compatibility — knee=0 reproduces the legacy hard cutoff exactly
# ---------------------------------------------------------------------------

def test_knee_zero_matches_legacy_hard_cutoff() -> None:
    """knee=0 must reproduce the old ``max(luma - threshold, 0)`` shape.

    For every test sample, the bloom contribution is either zero (luma <=
    threshold) or ``colour * (luma - threshold) / luma`` exactly.
    """
    lumas = np.array([0.0, 0.5, 0.999, 1.0, 1.0001, 1.5, 2.0, 5.0], dtype=np.float32)
    rgb = synth_hdr_strip(lumas)
    out = smooth_threshold(rgb, REG_THRESHOLD, knee=0.0)

    for i, luma in enumerate(lumas):
        got = float(out[0, i, 0])
        if luma <= REG_THRESHOLD:
            assert got == 0.0, (
                f"hard cutoff violated at luma={luma}: got {got!r}, expected 0"
            )
        else:
            expected = float(luma) * (luma - REG_THRESHOLD) / float(luma)
            assert got == pytest.approx(expected, abs=1e-6), (
                f"hard cutoff numeric mismatch at luma={luma}: "
                f"got {got!r}, expected {expected!r}"
            )


def test_bloom_pass_knee_zero_matches_legacy() -> None:
    """The BloomPass wrapper with knee=0 must reproduce the same behaviour."""
    rgb = synth_hdr_strip([0.5, 1.0, 1.5, 2.0])
    hard_pass = BloomPass(threshold=REG_THRESHOLD, knee=0.0, intensity=1.0)
    out = hard_pass.apply_cpu(rgb)
    # Below threshold → zero; above → linear extraction.
    assert float(out[0, 0, 0]) == 0.0           # luma 0.5
    assert float(out[0, 1, 0]) == 0.0           # luma 1.0 — sits exactly on the cutoff
    assert float(out[0, 2, 0]) == pytest.approx(0.5, abs=1e-6)  # luma 1.5
    assert float(out[0, 3, 0]) == pytest.approx(1.0, abs=1e-6)  # luma 2.0


# ---------------------------------------------------------------------------
# BloomPass — parameter wiring + sanity
# ---------------------------------------------------------------------------

def test_bloom_pass_default_knee_is_lottes() -> None:
    """Default ``BloomPass()`` uses knee=0.2 — the documented Lottes width."""
    bp = BloomPass()
    assert bp.threshold == 1.0
    assert bp.knee == 0.2
    assert bp.intensity == 1.0


def test_bloom_pass_negative_knee_rejected() -> None:
    """Negative knees produce nonsense; the constructor must reject them."""
    with pytest.raises(ValueError):
        BloomPass(threshold=1.0, knee=-0.1)


def test_bloom_pass_make_pass_packs_params() -> None:
    """make_pass must emit raw_params_bytes containing (threshold, knee, intensity)."""
    import struct
    bp = BloomPass(threshold=0.7, knee=0.3, intensity=1.5)
    pp = bp.make_pass()
    assert pp.shader_path == "bloom_threshold.wgsl"
    assert pp.entry_point == "main"
    assert pp.label == "bloom"
    assert pp.raw_params_bytes is not None
    assert len(pp.raw_params_bytes) == 16
    t, k, i, _pad = struct.unpack("<ffff", pp.raw_params_bytes)
    assert t == pytest.approx(0.7)
    assert k == pytest.approx(0.3)
    assert i == pytest.approx(1.5)


def test_bloom_pass_intensity_scales_output() -> None:
    """``intensity`` multiplies the extracted glow."""
    rgb = synth_hdr_strip([2.0])
    base = BloomPass(threshold=1.0, knee=0.2, intensity=1.0).apply_cpu(rgb)
    boosted = BloomPass(threshold=1.0, knee=0.2, intensity=3.0).apply_cpu(rgb)
    assert np.allclose(boosted, base * 3.0, atol=1e-6)


def test_bloom_pass_full_regression_strip() -> None:
    """End-to-end check of the (0.5, 1.0, 1.1, 1.2, 2.0) regression spec.

    Mirrors the task's required assertion list:
      - 0.5 → exact zero
      - 1.0 → barely nonzero
      - 1.1 → ramped (0 < val < full)
      - 1.2 → >= 1.1
      - 2.0 → full contribution (matches hard-cutoff arithmetic)
    """
    bp = BloomPass(threshold=REG_THRESHOLD, knee=REG_KNEE)
    rgb = synth_hdr_strip(REG_LUMAS)
    out = bp.apply_cpu(rgb)
    vals = [float(out[0, i, 0]) for i in range(len(REG_LUMAS))]

    assert vals[0] == 0.0, f"luma 0.5 leaked bloom: {vals[0]!r}"
    assert 0.0 < vals[1] < 0.1, f"luma 1.0 should be barely nonzero: {vals[1]!r}"
    assert 0.0 < vals[2] < 1.0, f"luma 1.1 should be ramped: {vals[2]!r}"
    assert vals[3] >= vals[2], f"luma 1.2 should be >= luma 1.1: {vals[3]!r} vs {vals[2]!r}"

    # luma 2.0 sits above the knee, so soft and hard branches agree;
    # extracted colour equals (luma - threshold) = 1.0 per channel.
    assert vals[4] == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Visual baseline — representative HDR scene
# ---------------------------------------------------------------------------

REF_DIR = Path(__file__).parent / "visual" / "reference" / "bloom_smooth"
OUT_DIR = Path(__file__).parent / "visual" / "output"  / "bloom_smooth"


def _make_hdr_scene(width: int = 64, height: int = 64) -> np.ndarray:
    """Build a deterministic HDR scene with a bright disc + dim background."""
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    cx, cy = (width - 1) * 0.5, (height - 1) * 0.5
    r2 = (xx - cx) ** 2 + (yy - cy) ** 2
    radius = min(width, height) * 0.25

    # Dim ambient + a hot emissive disc that ramps from 0.9 (just below
    # threshold) at its edge to ~2.5 (well above the knee) at its centre.
    bg = np.full((height, width), 0.3, dtype=np.float32)
    disc = np.maximum(0.0, 1.0 - r2 / (radius * radius))
    luma = bg + disc * 2.2

    rgb = np.stack([luma, luma * 0.85, luma * 0.6], axis=-1)  # warm tint
    return rgb


def _assert_scene_matches(
    out: np.ndarray,
    ref_path: Path,
    out_path: Path,
    atol: float = 1.0e-5,
) -> None:
    """Local visual baseline check — saves on first run, asserts thereafter.

    Stored as ``.npy`` so HDR magnitudes survive a lossless round-trip;
    PIL's RGB modes only support 8-bit channels.  On the first run the
    reference is written and the test self-skips; thereafter the captured
    glow buffer is compared element-wise.
    """
    out = np.asarray(out, dtype=np.float32)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(out_path, out)

    if not ref_path.exists():
        ref_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(ref_path, out)
        pytest.skip(f"baseline written: {ref_path}")

    ref = np.load(ref_path).astype(np.float32)
    if ref.shape != out.shape:
        raise AssertionError(
            f"baseline shape mismatch: ref {ref.shape} vs out {out.shape}"
        )
    diff = float(np.max(np.abs(ref - out)))
    assert diff <= atol, f"visual diff exceeded atol={atol}: max abs diff {diff!r}"


def test_bloom_visual_baseline_hdr_scene() -> None:
    """Visual regression on a representative HDR scene.

    Captures the smooth-knee bloom extraction so any future change to the
    Lottes formula (or its packing) will trip the baseline.  On first run
    the test writes the reference and self-skips; subsequent runs compare.
    """
    scene = _make_hdr_scene(64, 64)
    bp = BloomPass(threshold=REG_THRESHOLD, knee=REG_KNEE, intensity=1.0)
    glow = bp.apply_cpu(scene)

    ref_path = REF_DIR / "hdr_disc_smooth.npy"
    out_path = OUT_DIR / "hdr_disc_smooth.npy"
    _assert_scene_matches(glow, ref_path, out_path)


def test_bloom_visual_baseline_hard_cutoff_for_comparison() -> None:
    """Same scene with knee=0 — used to verify the soft path differs visibly.

    The smooth-knee result must NOT match the hard-cutoff result pixel-for-pixel
    in the transition band, otherwise the new code is a no-op.
    """
    scene = _make_hdr_scene(64, 64)
    soft = BloomPass(threshold=REG_THRESHOLD, knee=REG_KNEE).apply_cpu(scene)
    hard = BloomPass(threshold=REG_THRESHOLD, knee=0.0).apply_cpu(scene)
    # Pixels in the transition band (luma just above threshold) must differ.
    diff = np.abs(soft - hard).max()
    assert diff > 0.01, (
        "smooth and hard knee should differ visibly in the transition band; "
        f"max abs diff was {diff!r}"
    )
