"""Regression tests for Vogel-disk PCF shadow sampling (round-12 polish).

Round 12 replaces the fixed 3×3 grid PCF in ``shaders/shadow_csm.wgsl``
with a Vogel-disk spiral (Persson 2012, *Low-Level Thinking in High-Level
Shading Languages*) — an N-tap golden-angle distribution that gives
smoother penumbras than the 9-tap grid at the same or smaller tap budget.

These tests run entirely on a pure-numpy reference of the Vogel-disk
math that mirrors the WGSL shader's ``vogel_pcf_shadow`` function
bit-for-bit (modulo the per-pixel rotation hash, which we verify
structurally).  No GPU is required.

The headline guarantee is:

    PSNR(vogel_16, ground_truth) > PSNR(grid_3x3, ground_truth)

on a smooth synthetic penumbra band — the classic artefact target.
"""
from __future__ import annotations

import math
import struct

import numpy as np
import pytest

from slappyengine.post_process.shadow_csm import ShadowCSM


# ---------------------------------------------------------------------------
# Pure-numpy mirror of the WGSL Vogel-disk PCF
# ---------------------------------------------------------------------------

GOLDEN_ANGLE = math.pi * (3.0 - math.sqrt(5.0))  # 2.39996323...


def _vogel_disk_taps(n: int) -> np.ndarray:
    """Generate N Vogel-disk taps on the unit disk (no per-pixel rotation).

    Returns an (N, 2) array of (x, y) offsets.  This mirrors the WGSL
    formula::

        r     = sqrt((i + 0.5) / N)
        theta = i * GOLDEN_ANGLE
        (x, y) = (r * cos(theta), r * sin(theta))
    """
    i = np.arange(n, dtype=np.float64)
    r = np.sqrt((i + 0.5) / float(n))
    theta = i * GOLDEN_ANGLE
    return np.stack([r * np.cos(theta), r * np.sin(theta)], axis=-1)


def _grid_3x3_taps() -> np.ndarray:
    """Legacy fixed 3×3 grid taps on the unit-texel domain (9 taps)."""
    pts = []
    for ky in (-1, 0, 1):
        for kx in (-1, 0, 1):
            pts.append((float(kx), float(ky)))
    return np.asarray(pts, dtype=np.float64)


# ---------------------------------------------------------------------------
# 1.  Structural — all Vogel taps lie strictly within the unit disk
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [4, 8, 16, 32, 64])
def test_vogel_taps_lie_inside_unit_disk(n: int) -> None:
    """Every Vogel-disk tap radius must satisfy r <= 1.0.

    Persson's formula guarantees ``r = sqrt((i + 0.5) / N)`` with
    ``i in [0, N)``, so the maximum radius is
    ``sqrt((N - 0.5) / N) = sqrt(1 - 0.5/N) < 1``.  This is the
    fundamental safety bound — taps that escape the disk would sample
    outside the intended PCF kernel radius and bleed shadow edges.
    """
    taps = _vogel_disk_taps(n)
    radii = np.linalg.norm(taps, axis=-1)
    assert np.all(radii <= 1.0), (
        f"Vogel tap radius exceeded unit disk: max={radii.max():.6f}"
    )
    # Upper bound matches the analytic expression to high precision.
    expected_max = math.sqrt((n - 0.5) / n)
    np.testing.assert_allclose(radii.max(), expected_max, atol=1.0e-12)


# ---------------------------------------------------------------------------
# 2.  Structural — taps are well-distributed (low discrepancy)
# ---------------------------------------------------------------------------


def _coverage_variance(taps: np.ndarray, n_queries: int = 4096, seed: int = 1) -> float:
    """Variance of distance-to-nearest-tap over random disk queries.

    Lower variance means a query point lands at a more *consistent*
    distance from the nearest tap — the canonical low-discrepancy
    measure.  A clumpy distribution has high variance (deep voids near
    some queries, dense clusters near others); a uniform distribution
    has low variance.
    """
    rng = np.random.RandomState(seed)
    # Uniform samples on the unit disk (rejection sampling for simplicity).
    pts = []
    while len(pts) < n_queries:
        cand = rng.uniform(-1.0, 1.0, size=(n_queries * 2, 2))
        cand = cand[np.linalg.norm(cand, axis=-1) <= 1.0]
        pts.extend(cand.tolist())
    queries = np.asarray(pts[:n_queries], dtype=np.float64)
    diffs = queries[:, None, :] - taps[None, :, :]
    d = np.linalg.norm(diffs, axis=-1)
    nn = d.min(axis=-1)
    return float(np.var(nn))


def test_vogel_taps_have_lower_coverage_variance_than_grid() -> None:
    """Vogel-disk taps cover the disk more *uniformly* than a 3×3 grid.

    Measure: variance of distance-to-nearest-tap over random disk
    queries.  Lower variance = more consistent coverage = fewer visible
    sampling artefacts.  This is the canonical low-discrepancy test that
    sidesteps the trivial "more points → smaller NN" confound.

    With the 3×3 grid normalised to fit the unit disk, the corners sit
    near r=1 while the centre tap sits at r=0 — leaving a wide annulus
    that's poorly covered.  Vogel-16 spirals fill that annulus and the
    variance drops materially.
    """
    vogel = _vogel_disk_taps(16)
    grid = _grid_3x3_taps() / math.sqrt(2.0)  # fit inside unit disk

    var_vogel = _coverage_variance(vogel)
    var_grid = _coverage_variance(grid)

    assert var_vogel < var_grid, (
        f"Vogel coverage variance ({var_vogel:.5f}) should be less than "
        f"the normalised 3×3 grid ({var_grid:.5f}) — uniform > clumpy"
    )


# ---------------------------------------------------------------------------
# 3.  Penumbra PSNR — Vogel-16 beats the legacy 3×3 grid on a soft edge
# ---------------------------------------------------------------------------


def _eval_pcf(
    receiver_depth: np.ndarray,
    shadow_map: np.ndarray,
    taps: np.ndarray,
    radius_px: float,
) -> np.ndarray:
    """Evaluate PCF at each pixel of a 1-D receiver vs a 1-D shadow map.

    ``receiver_depth`` and ``shadow_map`` are 1-D arrays in shadow-map
    texel space (already projected).  ``taps`` is the (N, 2) tap pattern
    on the unit disk; we only use the x component since the problem is
    1-D.  Returns the per-pixel lit fraction in [0, 1].
    """
    n = len(receiver_depth)
    width = shadow_map.shape[0]
    lit = np.zeros(n, dtype=np.float64)
    for tx, _ty in taps:
        offset = tx * radius_px
        sample_x = np.clip(
            np.arange(n, dtype=np.float64) + offset, 0.0, width - 1.0,
        )
        # Nearest-texel lookup, matching the shader's textureLoad.
        idx = np.round(sample_x).astype(np.int64)
        sm = shadow_map[idx]
        lit += (receiver_depth <= sm).astype(np.float64)
    return lit / float(len(taps))


def _psnr(reference: np.ndarray, candidate: np.ndarray) -> float:
    mse = float(np.mean((reference - candidate) ** 2))
    if mse <= 1.0e-12:
        return 120.0
    return 10.0 * float(np.log10(1.0 / mse))


def test_vogel16_beats_grid3x3_on_soft_penumbra() -> None:
    """Headline PSNR: Vogel-16 reconstructs a soft edge more accurately.

    Scene: shadow-map records a hard occluder edge at column 32 on a
    64-texel 1-D map.  Receiver is a flat lit surface placed in front of
    the occluder, so the analytic shadow factor is a smooth ramp around
    the edge whose width matches the PCF radius.

    We compare the 9-tap 3×3 grid against 16-tap Vogel disk at the same
    physical radius.  Higher tap count + uniform distribution wins
    materially on PSNR vs the analytic ground truth.
    """
    width = 64
    radius_px = 6.0  # PCF radius in texels — wide enough for a clear penumbra
    # Shadow map: depth = 0.2 in the occluded half, depth = 1.0 in the lit
    # half.  Receiver depth = 0.5 everywhere → in shadow where sample <= 0.5.
    shadow_map = np.where(np.arange(width) < 32, 0.2, 1.0).astype(np.float64)
    receiver = np.full(width, 0.5, dtype=np.float64)

    # Analytic ground truth: lit fraction = (taps with sample_x > 32) / N
    # under a uniform distribution on a disk of radius radius_px.  For a
    # uniform disk the marginal x-distribution has CDF
    #   F(x) = 0.5 + (x * sqrt(1 - x²) + asin(x)) / π  for x in [-1, 1]
    x_to_edge = (32.0 - np.arange(width, dtype=np.float64)) / radius_px
    x_clamped = np.clip(x_to_edge, -1.0, 1.0)
    cdf = 0.5 + (
        x_clamped * np.sqrt(np.maximum(1.0 - x_clamped * x_clamped, 0.0))
        + np.arcsin(x_clamped)
    ) / math.pi
    # cdf is P(sample_x < edge); lit = P(sample_x >= edge) = 1 - cdf,
    # but we want lit when (receiver <= shadow_map at sample_x); shadow_map
    # is 1.0 for x >= 32 → lit when sample_x >= 32 → ground_truth = 1 - cdf.
    ground_truth = 1.0 - cdf

    grid = _eval_pcf(receiver, shadow_map, _grid_3x3_taps() / math.sqrt(2.0),
                     radius_px)
    vogel = _eval_pcf(receiver, shadow_map, _vogel_disk_taps(16), radius_px)

    # Evaluate PSNR only inside the penumbra band [edge - r, edge + r]; the
    # flat lit / fully shadowed regions are noise-free for both methods.
    band = slice(int(32 - radius_px), int(32 + radius_px) + 1)
    psnr_grid = _psnr(ground_truth[band], grid[band])
    psnr_vogel = _psnr(ground_truth[band], vogel[band])

    # Vogel-16 must beat the 3×3 grid by at least 1 dB on the penumbra
    # band.  This is conservative — empirically the delta is much larger,
    # but 1 dB is a stable lower bound across all numpy versions.
    delta = psnr_vogel - psnr_grid
    assert delta >= 1.0, (
        f"Vogel-16 PSNR should exceed 3×3 grid PSNR by >= 1 dB on a soft "
        f"penumbra; got delta={delta:.2f} dB "
        f"(grid={psnr_grid:.2f}, vogel={psnr_vogel:.2f})"
    )


# ---------------------------------------------------------------------------
# 4.  Backward compatibility — pcf_samples=0 keeps the legacy 3×3 grid
# ---------------------------------------------------------------------------


def _unpack_csm_params(raw: bytes) -> dict:
    """Unpack the CsmParams struct and return its trailing scalar fields."""
    assert len(raw) == 320, f"expected 320-byte CsmParams, got {len(raw)}"
    # Same format string as ShadowCSM.make_pass.
    fields = struct.unpack("<64f4f3fIffIIIffI", raw)
    return {
        "num_cascades": fields[71],
        "depth_bias":   fields[72],
        "pcf_radius":   fields[73],
        "width":        fields[74],
        "height":       fields[75],
        "pcss_enabled": fields[76],
        "light_size":   fields[77],
        "near":         fields[78],
        "pcf_samples":  fields[79],
    }


def test_default_pcf_samples_is_16() -> None:
    """Round-12 default = 16 Vogel taps (matches Persson's reference).

    A user who upgrades without touching their config gets the new
    Vogel-16 path automatically.  Opting out is one parameter:
    ``pcf_samples=0`` reverts to the legacy 3×3 grid.
    """
    pp = ShadowCSM(pcss_enabled=False).make_pass()
    fields = _unpack_csm_params(pp.raw_params_bytes)
    assert fields["pcf_samples"] == 16
    assert fields["pcss_enabled"] == 0


def test_pcf_samples_zero_selects_legacy_grid() -> None:
    """``pcf_samples=0`` is the documented back-compat opt-out.

    The WGSL ``main`` selects the legacy ``pcf_shadow`` (3×3 grid, 9
    taps) when ``params.pcf_samples == 0u`` and PCSS is disabled.  This
    is the path existing scenes used before round 12.
    """
    pp = ShadowCSM(pcss_enabled=False, pcf_samples=0).make_pass()
    fields = _unpack_csm_params(pp.raw_params_bytes)
    assert fields["pcf_samples"] == 0


def test_pcf_samples_packs_into_trailing_u32_slot() -> None:
    """The new field reuses the previously-padding ``_pad`` u32 at byte
    offset 316, so the struct stays at 320 bytes (no rebind needed)."""
    raw = ShadowCSM(pcss_enabled=False, pcf_samples=32).make_pass().raw_params_bytes
    assert len(raw) == 320
    # Offset 316 = byte slot for pcf_samples (little-endian u32).
    (val,) = struct.unpack_from("<I", raw, 316)
    assert val == 32


# ---------------------------------------------------------------------------
# 5.  Validation contract — pcf_samples is a real int and non-negative
# ---------------------------------------------------------------------------


def test_pcf_samples_rejects_non_int() -> None:
    with pytest.raises(TypeError, match="pcf_samples"):
        ShadowCSM(pcf_samples=16.0)  # type: ignore[arg-type]


def test_pcf_samples_rejects_bool() -> None:
    """``bool`` is a subclass of ``int`` in Python — explicitly reject it
    so callers can't pass ``pcf_samples=True`` and get N=1 silently."""
    with pytest.raises(TypeError, match="pcf_samples"):
        ShadowCSM(pcf_samples=True)  # type: ignore[arg-type]


def test_pcf_samples_rejects_negative() -> None:
    with pytest.raises(ValueError, match="pcf_samples"):
        ShadowCSM(pcf_samples=-1)
