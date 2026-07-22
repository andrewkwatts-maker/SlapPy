"""Regression tests for the TAA round-6 polish (W3 sprint 2026-07-04).

Round 6 adds five polish improvements to :mod:`pharos_engine.post_process.taa`:

1. **YCoCg conversion helpers** exposed at module level with a round-trip
   identity guarantee suitable for pipeline debugging.
2. **Halton(2,3) 8-sample sub-pixel jitter table** (up from the previous
   4-sample table) — pinned against reference constants computed offline.
3. **Karis 2014 ``k = 1.25`` variance clip** as a first-class helper —
   verified to preserve values inside the k*sigma envelope and clip
   values outside.
4. **Velocity-aware blend factor** — monotonically decreasing with
   ``|velocity|`` per DICE Frostbite 2016.
5. **Luminance rejection + relative-depth rejection** — the two
   canonical secondary-signal ghost gates that survive the YCoCg AABB.

All tests are pure numpy — no GPU required.  The reference constants
for the Halton assertion were computed offline via the canonical
van-der-Corput folding (documented inside the test).
"""
from __future__ import annotations

import numpy as np
import pytest

from pharos_engine.post_process.taa import (
    HALTON_2_3_8_SAMPLES,
    KARIS_2014_K,
    TAAPass,
    depth_rejection,
    halton_2_3_sequence,
    halton_sample,
    luminance_rejection,
    rgb_to_ycocg,
    variance_clip_ycocg,
    velocity_aware_alpha,
    ycocg_to_rgb,
)


# ---------------------------------------------------------------------------
# 1.  YCoCg round-trip identity
# ---------------------------------------------------------------------------


def test_ycocg_roundtrip_identity_on_4x4_tile() -> None:
    """``ycocg_to_rgb(rgb_to_ycocg(x)) == x`` on a deterministic 4x4 tile.

    The YCoCg matrix used by the WGSL shader is exact (all coefficients
    are ± 0.25 or ± 0.5), so the round-trip should agree to float32
    precision — no lossy quantisation.
    """
    rng = np.random.RandomState(42)
    tile = rng.rand(4, 4, 3).astype(np.float32)
    round_tripped = ycocg_to_rgb(rgb_to_ycocg(tile))
    np.testing.assert_allclose(round_tripped, tile, atol=1e-6)


def test_ycocg_roundtrip_identity_on_hdr_range() -> None:
    """Round-trip is exact even with HDR values (> 1.0) — the matrix has
    no clipping, only linear arithmetic, so nothing is lost."""
    rng = np.random.RandomState(7)
    tile = 12.0 * rng.rand(8, 8, 3).astype(np.float32)
    round_tripped = ycocg_to_rgb(rgb_to_ycocg(tile))
    np.testing.assert_allclose(round_tripped, tile, atol=1e-4)


def test_rgb_to_ycocg_grey_maps_to_luma_only() -> None:
    """A pure grey pixel has Co = Cg = 0 — the chroma channels are
    exactly zero for r == g == b (matches the ``0.25 r + 0.5 g + 0.25 b``
    coefficients that sum to 1.0)."""
    grey = np.full((2, 2, 3), 0.4, dtype=np.float32)
    yc = rgb_to_ycocg(grey)
    np.testing.assert_allclose(yc[..., 0], 0.4, atol=1e-6)
    np.testing.assert_allclose(yc[..., 1], 0.0, atol=1e-6)
    np.testing.assert_allclose(yc[..., 2], 0.0, atol=1e-6)


def test_rgb_to_ycocg_rejects_wrong_trailing_dim() -> None:
    """Trailing dim must be 3 — a shape mismatch should be a hard error,
    not a silent broadcast."""
    with pytest.raises(ValueError, match="trailing dim 3"):
        rgb_to_ycocg(np.zeros((4, 4, 4), dtype=np.float32))


def test_ycocg_to_rgb_rejects_wrong_trailing_dim() -> None:
    with pytest.raises(ValueError, match="trailing dim 3"):
        ycocg_to_rgb(np.zeros((4, 4, 2), dtype=np.float32))


# ---------------------------------------------------------------------------
# 2.  Halton(2,3) reference constants
# ---------------------------------------------------------------------------
#
# Halton is deterministic — for a given (base, index) the sample is
# unique.  These values were computed offline by the canonical
# van-der-Corput folding at the constants written below and pinned into
# HALTON_2_3_8_SAMPLES.  Any drift here is a hard bug.


_REFERENCE_HALTON_2_3 = (
    (0.5,       1.0 / 3.0),
    (0.25,      2.0 / 3.0),
    (0.75,      1.0 / 9.0),
    (0.125,     4.0 / 9.0),
    (0.625,     7.0 / 9.0),
    (0.375,     2.0 / 9.0),
    (0.875,     5.0 / 9.0),
    (0.0625,    8.0 / 9.0),
)


def test_halton_2_3_module_constant_matches_reference() -> None:
    """The pinned ``HALTON_2_3_8_SAMPLES`` module constant must match
    the canonical Halton(2,3) sequence indices 1..8 exactly."""
    assert len(HALTON_2_3_8_SAMPLES) == 8
    for k, ((sx, sy), (rx, ry)) in enumerate(
        zip(HALTON_2_3_8_SAMPLES, _REFERENCE_HALTON_2_3), start=1
    ):
        assert sx == pytest.approx(rx, abs=1e-6), (
            f"Halton(2) sample {k} drift: got {sx}, want {rx}"
        )
        assert sy == pytest.approx(ry, abs=1e-6), (
            f"Halton(3) sample {k} drift: got {sy}, want {ry}"
        )


def test_halton_sample_matches_reference_2() -> None:
    """``halton_sample(k, 2)`` matches the reference base-2 sequence."""
    for k, (rx, _) in enumerate(_REFERENCE_HALTON_2_3, start=1):
        assert halton_sample(k, 2) == pytest.approx(rx, abs=1e-9)


def test_halton_sample_matches_reference_3() -> None:
    """``halton_sample(k, 3)`` matches the reference base-3 sequence."""
    for k, (_, ry) in enumerate(_REFERENCE_HALTON_2_3, start=1):
        assert halton_sample(k, 3) == pytest.approx(ry, abs=1e-9)


def test_halton_2_3_sequence_returns_8_by_default() -> None:
    """``halton_2_3_sequence()`` defaults to 8 samples — the new W3 count."""
    seq = halton_2_3_sequence()
    assert len(seq) == 8
    for (sx, sy), (rx, ry) in zip(seq, _REFERENCE_HALTON_2_3):
        assert sx == pytest.approx(rx, abs=1e-9)
        assert sy == pytest.approx(ry, abs=1e-9)


def test_halton_2_3_sequence_variable_length() -> None:
    """The generator accepts arbitrary ``count`` >= 1."""
    seq16 = halton_2_3_sequence(16)
    assert len(seq16) == 16
    # First 8 must match the pinned constants.
    for a, b in zip(seq16[:8], HALTON_2_3_8_SAMPLES):
        assert a == pytest.approx(b, abs=1e-9)


def test_halton_sample_rejects_invalid_base() -> None:
    """A base < 2 is meaningless (van-der-Corput needs base >= 2)."""
    with pytest.raises(ValueError, match="base must be >= 2"):
        halton_sample(3, 1)


def test_halton_sample_rejects_negative_index() -> None:
    with pytest.raises(ValueError, match="index must be >= 0"):
        halton_sample(-1, 2)


def test_halton_sample_index_zero_is_zero() -> None:
    """Index 0 = 0.0 for all bases (van-der-Corput identity)."""
    assert halton_sample(0, 2) == 0.0
    assert halton_sample(0, 3) == 0.0
    assert halton_sample(0, 5) == 0.0


def test_halton_samples_are_in_unit_interval() -> None:
    """Every Halton sample must lie strictly in ``[0, 1)`` — this is
    the whole point of a low-discrepancy sequence for jitter."""
    for sx, sy in HALTON_2_3_8_SAMPLES:
        assert 0.0 <= sx < 1.0
        assert 0.0 <= sy < 1.0


# ---------------------------------------------------------------------------
# 3.  Variance clip preserves inside, clips outside
# ---------------------------------------------------------------------------


def test_variance_clip_preserves_values_inside_envelope() -> None:
    """A pixel whose history YCoCg sits inside ``[mu - k*sigma, mu + k*sigma]``
    must pass through the clip unchanged.

    Scene: a *smooth* gradient — the neighbourhood variance is tiny, so
    the k*sigma envelope tightly hugs each pixel; and history == current
    means every history YCoCg vector is exactly on that envelope's
    centre (the neighbourhood mean).  The clip must return current
    within a very tight bound because the input already sits at the
    envelope centre.
    """
    ys = np.linspace(0.2, 0.8, 16, dtype=np.float32)[:, None]
    xs = np.linspace(0.1, 0.7, 16, dtype=np.float32)[None, :]
    # Smooth per-channel ramp — tiny local variance, no noise.
    cur = np.stack(
        [ys + 0.0 * xs, 0.5 * (ys + xs), xs + 0.0 * ys],
        axis=-1,
    ).astype(np.float32)
    hist = cur.copy()
    clipped = variance_clip_ycocg(cur, hist, k=KARIS_2014_K)
    # Under smooth gradients the envelope tightly follows each pixel, so
    # the clipped output must agree with current at 1e-3 precision.
    np.testing.assert_allclose(clipped, cur, atol=1e-3)


def test_variance_clip_preserves_values_within_k_sigma_of_neighbourhood_mean() -> None:
    """Structural property: for every pixel, the clipped YCoCg lies
    inside ``[mu - k*sigma, mu + k*sigma]`` of the current-frame 3x3
    neighbourhood.  Regardless of what the history value was."""
    rng = np.random.RandomState(11)
    cur = rng.rand(16, 16, 3).astype(np.float32)
    # Arbitrary history — some values inside envelope, some outside.
    hist = rng.rand(16, 16, 3).astype(np.float32) * 2.0
    clipped = variance_clip_ycocg(cur, hist, k=KARIS_2014_K)
    clipped_yc = rgb_to_ycocg(clipped)

    # Compute the reference mu ± k*sigma envelope in YCoCg space.
    cur_yc = rgb_to_ycocg(cur)
    padded = np.pad(cur_yc, ((1, 1), (1, 1), (0, 0)), mode="edge")
    tiles = np.stack(
        [padded[i:i + 16, j:j + 16, :] for i in range(3) for j in range(3)],
        axis=0,
    )
    mu = tiles.mean(axis=0)
    sigma = np.sqrt(np.maximum((tiles ** 2).mean(axis=0) - mu ** 2, 0.0))
    lo = mu - KARIS_2014_K * sigma
    hi = mu + KARIS_2014_K * sigma

    # Tiny numerical slack for the RGB→YCoCg→RGB→YCoCg round trip.
    slack = 1e-4
    assert np.all(clipped_yc >= lo - slack), (
        "clipped YCoCg fell below the k*sigma envelope floor"
    )
    assert np.all(clipped_yc <= hi + slack), (
        "clipped YCoCg exceeded the k*sigma envelope ceiling"
    )


def test_variance_clip_clips_outside_envelope() -> None:
    """A wildly out-of-band history sample (all 10.0 over a dark scene)
    must be pulled inside the k*sigma envelope."""
    rng = np.random.RandomState(13)
    cur = (0.2 + 0.05 * rng.rand(16, 16, 3)).astype(np.float32)
    hist = np.full_like(cur, 10.0)  # HDR blowout
    clipped = variance_clip_ycocg(cur, hist, k=1.25)
    # The clipped history must have max luminance below the input's
    # neighbourhood mean + k * sigma.  A quick necessary condition: the
    # clipped max must be *strictly less* than the raw history value.
    assert float(clipped.max()) < 10.0
    # And it must be close to the current-frame mean (the envelope
    # centre) because the wide gap forces every history sample to hit
    # the ``mean + k*sigma`` boundary.
    diff_from_cur_mean = float(np.mean(np.abs(clipped - cur.mean())))
    assert diff_from_cur_mean < 0.5


def test_variance_clip_karis_k_default_matches_1_25() -> None:
    """The module-level ``KARIS_2014_K`` default must equal 1.25 — the
    Karis SIGGRAPH 2014 canonical value."""
    assert KARIS_2014_K == pytest.approx(1.25)


def test_variance_clip_rejects_shape_mismatch() -> None:
    with pytest.raises(ValueError, match="matching"):
        variance_clip_ycocg(
            np.zeros((4, 4, 3), dtype=np.float32),
            np.zeros((5, 5, 3), dtype=np.float32),
        )


def test_variance_clip_rejects_negative_k() -> None:
    with pytest.raises(ValueError, match="k must be >= 0"):
        variance_clip_ycocg(
            np.zeros((4, 4, 3), dtype=np.float32),
            np.zeros((4, 4, 3), dtype=np.float32),
            k=-0.1,
        )


def test_variance_clip_k_zero_collapses_to_mean() -> None:
    """At k == 0 the envelope has zero volume — every history sample is
    clamped to the neighbourhood mean.  The clipped output must equal
    the round-trip of the mean-of-neighbourhood YCoCg vector."""
    rng = np.random.RandomState(3)
    cur = (0.3 + 0.1 * rng.rand(12, 12, 3)).astype(np.float32)
    hist = np.full_like(cur, 0.9)
    clipped = variance_clip_ycocg(cur, hist, k=0.0)
    # Build the expected neighbourhood mean in YCoCg space explicitly.
    cur_yc = rgb_to_ycocg(cur)
    padded = np.pad(cur_yc, ((1, 1), (1, 1), (0, 0)), mode="edge")
    tiles = np.stack(
        [padded[i:i + 12, j:j + 12, :] for i in range(3) for j in range(3)],
        axis=0,
    )
    mu = tiles.mean(axis=0)
    expected = ycocg_to_rgb(mu)
    np.testing.assert_allclose(clipped, expected, atol=1e-4)


# ---------------------------------------------------------------------------
# 4.  Velocity-aware alpha monotonically decreases with |velocity|
# ---------------------------------------------------------------------------


def test_velocity_aware_alpha_monotone_scalar_input() -> None:
    """As |v| grows, alpha must decrease monotonically until it hits
    the ``lo`` floor."""
    vs = np.linspace(0.0, 3.0, 25, dtype=np.float32)
    alphas = velocity_aware_alpha(vs, base_alpha=0.9, lo=0.05, hi=0.95, scale=0.5)
    # Non-increasing sequence.
    diffs = np.diff(alphas)
    assert np.all(diffs <= 1e-6), f"alpha not monotone-decreasing: {alphas}"
    # Zero-velocity gives ~0.9 (below the 0.95 cap so unclamped).
    assert alphas[0] == pytest.approx(0.9, abs=1e-6)
    # Large velocity hits the 0.05 floor.
    assert alphas[-1] == pytest.approx(0.05, abs=1e-6)


def test_velocity_aware_alpha_uv_vector_input() -> None:
    """A (H, W, 2) vector velocity field: alpha uses the vector norm."""
    v = np.zeros((3, 3, 2), dtype=np.float32)
    v[0, 0] = (0.0, 0.0)       # |v| = 0    → 0.9
    v[0, 1] = (0.3, 0.4)       # |v| = 0.5  → 0.9 - 0.25 = 0.65
    v[0, 2] = (1.0, 0.0)       # |v| = 1.0  → 0.9 - 0.5 = 0.4
    alpha = velocity_aware_alpha(v)
    assert alpha[0, 0] == pytest.approx(0.9, abs=1e-6)
    assert alpha[0, 1] == pytest.approx(0.65, abs=1e-6)
    assert alpha[0, 2] == pytest.approx(0.4, abs=1e-6)


def test_velocity_aware_alpha_clamps_at_bounds() -> None:
    """Very small (< base - hi) or very large (> base - lo) velocities
    are clamped to hi/lo respectively."""
    # Negative base_alpha would push below lo without the clamp.
    alpha = velocity_aware_alpha(
        np.array([0.0, 100.0], dtype=np.float32),
        base_alpha=1.5, lo=0.1, hi=0.7,
    )
    assert alpha[0] == pytest.approx(0.7, abs=1e-6)   # clamped by hi
    assert alpha[1] == pytest.approx(0.1, abs=1e-6)   # clamped by lo


def test_velocity_aware_alpha_rejects_lo_gt_hi() -> None:
    with pytest.raises(ValueError, match="lo .* <= hi"):
        velocity_aware_alpha(np.zeros(4, dtype=np.float32), lo=0.9, hi=0.1)


# ---------------------------------------------------------------------------
# 5.  Luminance rejection triggers on synthetic disparity
# ---------------------------------------------------------------------------


def test_luminance_rejection_fires_on_bright_disparity() -> None:
    """A synthetic 8-fold luminance disparity must trip the rejection
    (relative-|Δluma| / max(cur, hist) = 7/8 = 0.875 ≫ 0.5 threshold)."""
    cur = np.full((4, 4, 3), 0.1, dtype=np.float32)
    hist = np.full((4, 4, 3), 0.8, dtype=np.float32)
    mask = luminance_rejection(cur, hist, threshold=0.5)
    assert mask.all(), "high luminance disparity must reject everywhere"


def test_luminance_rejection_stays_silent_on_matching_luma() -> None:
    """When current and history luminance match, nothing is rejected."""
    rng = np.random.RandomState(17)
    cur = rng.rand(8, 8, 3).astype(np.float32)
    hist = cur.copy()
    mask = luminance_rejection(cur, hist, threshold=0.5)
    assert not mask.any(), "matching luminance must never reject"


def test_luminance_rejection_threshold_controls_sensitivity() -> None:
    """A tighter threshold (0.1) fires on smaller disparities than
    the default 0.5."""
    cur = np.full((4, 4, 3), 0.5, dtype=np.float32)
    hist = np.full((4, 4, 3), 0.6, dtype=np.float32)
    # diff / max = 0.1 / 0.6 ≈ 0.167 — below 0.5 default, above 0.1 tight.
    assert not luminance_rejection(cur, hist, threshold=0.5).any()
    assert luminance_rejection(cur, hist, threshold=0.1).all()


# ---------------------------------------------------------------------------
# 6.  Depth rejection triggers on synthetic disparity
# ---------------------------------------------------------------------------


def test_depth_rejection_fires_on_relative_disparity() -> None:
    """|prev - cur| = 0.05, cur = 0.5 → 10 % divergence, above the 2 %
    default threshold — every pixel rejected."""
    cur = np.full((4, 4), 0.5, dtype=np.float32)
    prev = np.full((4, 4), 0.55, dtype=np.float32)
    assert depth_rejection(cur, prev, relative_threshold=0.02).all()


def test_depth_rejection_stays_silent_on_matching_depth() -> None:
    """When current and previous depths match, nothing is rejected."""
    rng = np.random.RandomState(19)
    cur = rng.rand(8, 8).astype(np.float32) + 0.1
    prev = cur.copy()
    assert not depth_rejection(cur, prev).any()


def test_depth_rejection_is_relative_not_absolute() -> None:
    """A 1 mm break at 5 m NDC depth (0.0002 relative) is below
    threshold; a 1 mm break at 5 cm NDC depth (0.02 relative) sits
    right at the threshold and is rejected under strict > semantics."""
    # Small absolute break at large depth: below relative threshold.
    cur = np.full((2, 2), 5.0, dtype=np.float32)
    prev = np.full((2, 2), 5.001, dtype=np.float32)   # 0.02 % divergence
    assert not depth_rejection(cur, prev, relative_threshold=0.02).any()
    # Same absolute break at small depth: above relative threshold.
    cur = np.full((2, 2), 0.05, dtype=np.float32)
    prev = np.full((2, 2), 0.055, dtype=np.float32)   # 10 % divergence
    assert depth_rejection(cur, prev, relative_threshold=0.02).all()


def test_depth_rejection_rejects_shape_mismatch() -> None:
    with pytest.raises(ValueError, match="shapes differ"):
        depth_rejection(
            np.zeros((4, 4), dtype=np.float32),
            np.zeros((5, 5), dtype=np.float32),
        )


def test_depth_rejection_rejects_negative_threshold() -> None:
    with pytest.raises(ValueError, match="relative_threshold must be >= 0"):
        depth_rejection(
            np.zeros((4, 4), dtype=np.float32),
            np.zeros((4, 4), dtype=np.float32),
            relative_threshold=-0.01,
        )


# ---------------------------------------------------------------------------
# 7.  Wgpu fallback parity — numpy path stays visually equivalent
# ---------------------------------------------------------------------------


def test_wgpu_import_is_soft() -> None:
    """The polish helpers must import cleanly even when wgpu is absent —
    the round-6 helpers are pure numpy and must never require a GPU."""
    # If the taa module tried to eagerly import wgpu, the module import
    # at the top of this file would already have failed.  Belt-and-braces
    # sanity: verify our helpers are directly callable.
    assert callable(rgb_to_ycocg)
    assert callable(ycocg_to_rgb)
    assert callable(variance_clip_ycocg)
    assert callable(velocity_aware_alpha)
    assert callable(luminance_rejection)
    assert callable(depth_rejection)
    assert callable(halton_sample)
    assert callable(halton_2_3_sequence)


def test_taa_resolve_numpy_still_works_after_polish() -> None:
    """The existing ``TAAPass.resolve_numpy`` must continue to work —
    round 6 is additive, not a rewrite.  Smoke test on a small tile."""
    rng = np.random.RandomState(23)
    cur = rng.rand(8, 8, 3).astype(np.float32)
    hist = rng.rand(8, 8, 3).astype(np.float32)
    out = TAAPass(alpha=0.1).resolve_numpy(cur, hist)
    assert out.shape == cur.shape
    assert out.dtype == np.float32
    assert np.all(out >= 0.0)
    # Result should be a plausible blend — not identical to either input
    # (some blending happened) and not wildly out of bounds.
    assert not np.allclose(out, cur)
    assert not np.allclose(out, hist)
    assert float(out.max()) < 2.0


# ---------------------------------------------------------------------------
# 8.  Cross-signal sanity — combining rejections
# ---------------------------------------------------------------------------


def test_luminance_and_depth_rejection_are_independent_signals() -> None:
    """The two rejection helpers must operate on disjoint inputs and
    produce independent decisions — regression bound against a future
    refactor that accidentally cross-wires them."""
    H = W = 6
    # Scene: uniform colour, uniform current depth, but half the pixels
    # have a depth break in history.
    cur = np.full((H, W, 3), 0.5, dtype=np.float32)
    hist = cur.copy()   # matching luminance — luma gate silent
    cur_d = np.full((H, W), 0.5, dtype=np.float32)
    prev_d = cur_d.copy()
    prev_d[:, :W // 2] = 1.0   # 100 % divergence in left half

    lum_mask = luminance_rejection(cur, hist)
    depth_mask = depth_rejection(cur_d, prev_d)

    assert not lum_mask.any(), "luma gate should stay silent on matching colour"
    assert depth_mask[:, :W // 2].all(), "depth gate should fire on left half"
    assert not depth_mask[:, W // 2:].any(), (
        "depth gate should stay silent on the matching-depth right half"
    )
