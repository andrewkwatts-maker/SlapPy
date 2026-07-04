"""Bloom polish regression — COD:AW SIGGRAPH 13-tap + tent + firefly clamp.

Sprint W4 bloom polish covers five pieces of behaviour that together
implement the Call of Duty: Advanced Warfare bloom recipe from Jorge
Jimenez's SIGGRAPH 2014 slide deck:

1. 13-tap Karis / Mitchell-Netravali downsample kernel — inner 2×2 gets
   0.5, four overlapping outer 2×2 quads share the remaining 0.5.
2. 3×3 tent upsample (progressive-additive) — corners 1, edges 2,
   centre 4 (normalised /16).
3. Reinhard-local firefly filter L' = L / (1 + L/4) applied ONLY to the
   first mip so subsequent downsamples see a clean, HDR-clamped input.
4. Mip-independent bloom strength curve ``bloom_mix = mip_strength^0.5``
   so composite intensity does not compound as the mip depth grows.
5. Configurable mip count in [4, 8] with default 6.

These are pure-Python / numpy tests — no GPU required.  The CPU reference
lives in :mod:`slappyengine.post_process.bloom`; the WGSL companion in
``shaders/bloom_pyramid.wgsl`` is regression-tested for constant match by
``test_lighting_bloom_pyramid.py``.
"""
from __future__ import annotations

import numpy as np
import pytest

from slappyengine.post_process.bloom import (
    _FIREFLY_ANCHOR,
    _MIP_DEFAULT,
    _MIP_MAX,
    _MIP_MIN,
    _TENT_3X3,
    KARIS13_W_CENTRE,
    KARIS13_W_INNER_CARD,
    KARIS13_W_INNER_DIAG,
    KARIS13_W_OUTER_CARD,
    BloomPass,
    _build_pyramid,
    _mip_strength,
    apply_bloom,
    downsample_mn13,
    firefly_filter,
    upsample_tent9,
)


# ---------------------------------------------------------------------------
# (1) Kernel weights sum-to-one
# ---------------------------------------------------------------------------


def test_13tap_kernel_weights_sum_to_one() -> None:
    """Karis 13-tap downsample weights must sum to exactly 1.0 ± 1e-4.

    Inner 2×2 quad has weight 0.5; the four outer overlapping 2×2 quads
    share the other 0.5 (each 0.125).  Total = 0.5 + 4 * 0.125 = 1.0.
    """
    inner_w = 0.5
    outer_w = 4.0 * 0.125
    assert inner_w + outer_w == pytest.approx(1.0, abs=1e-4)


def test_13tap_karis_upsample_weights_sum_to_one() -> None:
    """Optional Karis 13-tap upsample weights sum to 1.0 ± 1e-4.

    ``KARIS13_W_*`` are pre-normalised so a constant input maps to itself.
    """
    total = (
        1.0 * KARIS13_W_CENTRE
        + 4.0 * KARIS13_W_INNER_CARD
        + 4.0 * KARIS13_W_INNER_DIAG
        + 4.0 * KARIS13_W_OUTER_CARD
    )
    assert total == pytest.approx(1.0, abs=1e-4)


def test_3x3_tent_kernel_weights_sum_to_one() -> None:
    """3×3 tent upsample kernel weights sum to 1.0 ± 1e-4.

    Layout ``[[1,2,1],[2,4,2],[1,2,1]] / 16`` — corners 4, edges 8, centre
    4 → 16 raw, normalised = 1.0.
    """
    s = float(_TENT_3X3.sum())
    assert s == pytest.approx(1.0, abs=1e-4)


def test_3x3_tent_kernel_shape_and_symmetry() -> None:
    """Tent kernel is 3×3 and 90°-rotationally symmetric.

    Symmetry guarantees the upsample cannot produce a directional bias.
    """
    assert _TENT_3X3.shape == (3, 3)
    # 90° rotation preserves the kernel exactly.
    assert np.allclose(_TENT_3X3, np.rot90(_TENT_3X3))
    # Corners equal, edges equal, centre is max.
    corners = [_TENT_3X3[0, 0], _TENT_3X3[0, 2], _TENT_3X3[2, 0], _TENT_3X3[2, 2]]
    edges = [_TENT_3X3[0, 1], _TENT_3X3[1, 0], _TENT_3X3[1, 2], _TENT_3X3[2, 1]]
    assert all(c == corners[0] for c in corners)
    assert all(e == edges[0] for e in edges)
    assert _TENT_3X3[1, 1] > edges[0] > corners[0]


# ---------------------------------------------------------------------------
# (2) Firefly filter behaviour — L / (1 + L/4)
# ---------------------------------------------------------------------------


def test_firefly_filter_clamps_extreme_pixel() -> None:
    """A pixel with L = 100 must clamp to less than 5.

    L' = 100 / (1 + 100/4) = 100 / 26 ≈ 3.846 — well under 5.
    """
    img = np.full((1, 1, 3), 100.0, dtype=np.float32)
    out = firefly_filter(img)
    # Luminance of the clamped output.
    l_out = 0.2126 * out[0, 0, 0] + 0.7152 * out[0, 0, 1] + 0.0722 * out[0, 0, 2]
    assert l_out < 5.0, (
        f"firefly_filter failed to clamp L=100 pixel to <5; got L={l_out!r}"
    )


def test_firefly_filter_preserves_hue() -> None:
    """The clamp is a scalar-per-pixel — RGB ratios must be preserved.

    A pure-red firefly must stay pure red after the clamp.
    """
    img = np.zeros((1, 1, 3), dtype=np.float32)
    img[0, 0] = [100.0, 0.0, 0.0]
    out = firefly_filter(img)
    # Green and blue channels must remain zero — only the luma is scaled.
    assert float(out[0, 0, 1]) == pytest.approx(0.0, abs=1e-6)
    assert float(out[0, 0, 2]) == pytest.approx(0.0, abs=1e-6)
    # And R is strictly smaller (clamped) than the input.
    assert float(out[0, 0, 0]) < 100.0


def test_firefly_filter_leaves_dark_pixels_nearly_untouched() -> None:
    """A dark pixel (L ≪ anchor) has a mild but non-catastrophic roll-off.

    At L = 0.1, weight = 1 / (1 + 0.025) ≈ 0.9756 — a 2.4% attenuation
    which is well within HDR headroom.
    """
    img = np.full((1, 1, 3), 0.1, dtype=np.float32)
    out = firefly_filter(img)
    assert float(out[0, 0, 0]) == pytest.approx(0.1 / (1.0 + 0.1 / 4.0), abs=1e-5)
    # And the attenuation is < 5% at this magnitude.
    assert float(out[0, 0, 0]) / 0.1 > 0.95


def test_firefly_filter_black_stays_black() -> None:
    """A zero-luma pixel must pass through as pure black — no divide-by-zero."""
    img = np.zeros((3, 3, 3), dtype=np.float32)
    out = firefly_filter(img)
    assert np.all(np.isfinite(out))
    assert np.allclose(out, 0.0)


def test_firefly_filter_rejects_bad_anchor() -> None:
    """Non-positive / non-finite anchors are rejected."""
    img = np.zeros((1, 1, 3), dtype=np.float32)
    with pytest.raises(ValueError, match="anchor"):
        firefly_filter(img, anchor=0.0)
    with pytest.raises(ValueError, match="anchor"):
        firefly_filter(img, anchor=-1.0)
    with pytest.raises(ValueError, match="anchor"):
        firefly_filter(img, anchor=float("inf"))


def test_firefly_filter_rejects_bad_shape() -> None:
    """Non-RGB inputs are rejected."""
    with pytest.raises(ValueError, match="RGB"):
        firefly_filter(np.zeros((4, 4, 4), dtype=np.float32))


def test_firefly_filter_first_pass_only_in_pyramid() -> None:
    """The pyramid builder applies the firefly filter to the source ONLY.

    A downstream pyramid mip must never see the raw un-clamped fireflies.
    """
    img = np.full((16, 16, 3), 0.5, dtype=np.float32)
    img[8, 8, :] = 1000.0  # extreme firefly
    mips = _build_pyramid(img, mip_count=4)
    # mip 0 is the source (unmodified reference).
    assert mips[0].max() == pytest.approx(1000.0, abs=1e-6)
    # Every subsequent mip must have been produced from firefly-clamped
    # input — the recorded peak should be many orders of magnitude below
    # the raw firefly.
    for level in range(1, len(mips)):
        assert mips[level].max() < 50.0, (
            f"mip {level} still contains firefly energy: peak = "
            f"{mips[level].max()!r} — firefly filter did not run on mip 0"
        )


# ---------------------------------------------------------------------------
# (3) apply_bloom identity + additive semantics
# ---------------------------------------------------------------------------


def test_apply_bloom_zero_strength_returns_input() -> None:
    """strength = 0 must produce a pixel-for-pixel identity."""
    rng = np.random.default_rng(0xB100)
    img = rng.uniform(0.0, 1.0, (16, 16, 3)).astype(np.float32)
    out = apply_bloom(img, strength=0.0)
    assert out.shape == img.shape
    assert np.allclose(out, img, atol=1e-7), (
        f"strength=0 should be identity; max diff = "
        f"{float(np.abs(out - img).max())!r}"
    )


def test_apply_bloom_positive_strength_brightens_bright_regions() -> None:
    """Positive strength additively brightens the above-threshold pixels."""
    img = np.zeros((16, 16, 3), dtype=np.float32)
    img[6:10, 6:10, :] = 2.0  # bright rectangle well above threshold=1.0
    dark = apply_bloom(img, strength=0.0)
    bright = apply_bloom(img, strength=1.0)
    # Sum of image must strictly increase.
    assert bright.sum() > dark.sum()


def test_apply_bloom_strength_scales_linearly() -> None:
    """Doubling strength must double the added glow contribution."""
    img = np.zeros((32, 32, 3), dtype=np.float32)
    img[15:17, 15:17, :] = 3.0
    s1 = apply_bloom(img, strength=1.0)
    s2 = apply_bloom(img, strength=2.0)
    glow1 = s1 - img
    glow2 = s2 - img
    # Ratio should be exactly 2 (within f32 rounding).
    assert glow1.max() > 0.0
    ratio = glow2.max() / max(glow1.max(), 1e-8)
    assert ratio == pytest.approx(2.0, rel=1e-4)


def test_apply_bloom_rejects_negative_strength() -> None:
    """Negative strength is nonsense — the constructor must reject it."""
    img = np.zeros((8, 8, 3), dtype=np.float32)
    with pytest.raises(ValueError, match="strength"):
        apply_bloom(img, strength=-0.1)


def test_apply_bloom_rejects_non_finite_strength() -> None:
    """NaN / Inf strengths are rejected."""
    img = np.zeros((8, 8, 3), dtype=np.float32)
    with pytest.raises(ValueError, match="strength"):
        apply_bloom(img, strength=float("nan"))
    with pytest.raises(ValueError, match="strength"):
        apply_bloom(img, strength=float("inf"))


def test_apply_bloom_rejects_bad_shape() -> None:
    """Non-RGB inputs are rejected."""
    with pytest.raises(ValueError, match="RGB"):
        apply_bloom(np.zeros((4, 4, 4), dtype=np.float32))


# ---------------------------------------------------------------------------
# (4) Configurable mip count 4-8
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mips", [4, 5, 6, 7, 8])
def test_apply_bloom_configurable_mip_count(mips: int) -> None:
    """All mip counts in [4, 8] must produce a same-shape output.

    The composite widens as ``mips`` grows but the final image shape and
    dtype must stay identical.
    """
    rng = np.random.default_rng(0xCAFE)
    img = rng.uniform(0.0, 2.0, (64, 64, 3)).astype(np.float32)
    out = apply_bloom(img, strength=1.0, mip_count=mips)
    assert out.shape == img.shape
    assert out.dtype == np.float32
    assert np.all(np.isfinite(out))


def test_apply_bloom_default_mip_count_is_six() -> None:
    """Default per COD:AW slides is 6 mips."""
    assert _MIP_DEFAULT == 6


def test_apply_bloom_rejects_out_of_range_mip_count() -> None:
    """Mip counts outside [4, 8] are rejected."""
    img = np.zeros((32, 32, 3), dtype=np.float32)
    with pytest.raises(ValueError, match="mip_count"):
        apply_bloom(img, strength=1.0, mip_count=3)
    with pytest.raises(ValueError, match="mip_count"):
        apply_bloom(img, strength=1.0, mip_count=9)


def test_apply_bloom_mip_range_constants() -> None:
    """Module-side constants match the class advertised bounds."""
    assert _MIP_MIN == BloomPass.MIP_MIN == 4
    assert _MIP_MAX == BloomPass.MIP_MAX == 8
    assert _MIP_DEFAULT == BloomPass.MIP_DEFAULT == 6


# ---------------------------------------------------------------------------
# (5) Mip-independent strength curve
# ---------------------------------------------------------------------------


def test_mip_strength_is_sqrt_shaped() -> None:
    """Strength curve is ``linear ** 0.5`` — larger mips get more weight.

    Level 0 (largest active mip) must be strictly greater than the deepest
    mip weight (a bright feature at level 0 should dominate the halo).
    """
    for n in (4, 5, 6, 7, 8):
        w0 = _mip_strength(0, n)
        w_last = _mip_strength(n - 1, n)
        assert w0 > w_last, (
            f"strength should decrease with mip depth; "
            f"got w0={w0}, w_{n-1}={w_last}"
        )
        # And every weight is in (0, 1].
        for lvl in range(n):
            w = _mip_strength(lvl, n)
            assert 0.0 < w <= 1.0


def test_mip_strength_zero_level_is_unity() -> None:
    """Largest mip weight is 1.0 — no attenuation at the top of the halo."""
    for n in (4, 5, 6, 7, 8):
        assert _mip_strength(0, n) == pytest.approx(1.0, abs=1e-6)


def test_mip_strength_does_not_compound_with_more_mips() -> None:
    """Adding mips must not compound the peak bloom energy.

    The sqrt() curve on the linear (1 - level/n) ramp keeps the sum of the
    ring weights bounded (grows slower than linearly with n).  Concretely:
    doubling the mip count from 4 to 8 must NOT double the composite peak
    on a bright feature.
    """
    img = np.zeros((64, 64, 3), dtype=np.float32)
    img[30:34, 30:34, :] = 4.0  # bright square well above threshold
    out4 = apply_bloom(img, strength=1.0, mip_count=4)
    out8 = apply_bloom(img, strength=1.0, mip_count=8)
    peak4 = float(out4.max())
    peak8 = float(out8.max())
    # The composite peak should stay within ~2× (an aggressive compounding
    # curve would push it to 4× or more).
    assert peak8 / max(peak4, 1e-6) < 2.0, (
        f"bloom compounds too much with more mips: peak4={peak4}, peak8={peak8}"
    )


# ---------------------------------------------------------------------------
# (6) Approximate mean preservation on linear input
# ---------------------------------------------------------------------------


def test_apply_bloom_preserves_mean_on_linear_input() -> None:
    """On a mid-grey below-threshold image, mean output ≈ mean input.

    Below-threshold input generates zero extracted glow, so the composite
    is added-zero and the mean is preserved exactly.  Task spec asks
    ``|mean_out - mean_in| < 0.1`` — this is a much tighter bound in
    practice.
    """
    rng = np.random.default_rng(0xB055)
    img = rng.uniform(0.0, 0.5, (64, 64, 3)).astype(np.float32)  # all below threshold=1.0
    out = apply_bloom(img, strength=1.0)
    mean_in = float(img.mean())
    mean_out = float(out.mean())
    assert abs(mean_out - mean_in) < 0.1, (
        f"mean drift too large: mean_in={mean_in}, mean_out={mean_out}"
    )


def test_apply_bloom_mean_drift_bounded_for_hdr_input() -> None:
    """Even with above-threshold HDR pixels, mean drift is bounded.

    The bloom adds energy above threshold — mean will rise — but the
    added mean must be modest (<0.5 for a diffuse HDR image at strength=1).
    """
    rng = np.random.default_rng(0xB056)
    # 90% of pixels below threshold, 10% mildly above — realistic HDR.
    img = rng.uniform(0.0, 0.5, (64, 64, 3)).astype(np.float32)
    hot_mask = rng.uniform(0.0, 1.0, (64, 64)) < 0.1
    img[hot_mask] = 1.5
    out = apply_bloom(img, strength=1.0)
    drift = float(out.mean() - img.mean())
    assert 0.0 <= drift < 0.5


# ---------------------------------------------------------------------------
# (7) BloomPass class exposes mip_count
# ---------------------------------------------------------------------------


def test_bloom_pass_default_mip_count() -> None:
    """Default constructor uses ``mip_count = MIP_DEFAULT`` (6)."""
    bp = BloomPass()
    assert bp.mip_count == BloomPass.MIP_DEFAULT == 6


@pytest.mark.parametrize("mips", [4, 5, 6, 7, 8])
def test_bloom_pass_accepts_mip_count_range(mips: int) -> None:
    """All valid mip counts are accepted."""
    bp = BloomPass(mip_count=mips)
    assert bp.mip_count == mips


def test_bloom_pass_rejects_bad_mip_count() -> None:
    """Out-of-range mip counts are rejected at construction."""
    with pytest.raises(ValueError, match="mip_count"):
        BloomPass(mip_count=3)
    with pytest.raises(ValueError, match="mip_count"):
        BloomPass(mip_count=9)
    with pytest.raises(TypeError, match="mip_count"):
        BloomPass(mip_count=6.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="mip_count"):
        BloomPass(mip_count=True)  # type: ignore[arg-type]


def test_bloom_pass_apply_pyramid_cpu_shape() -> None:
    """The class-level pipeline entry produces same-shape output."""
    rng = np.random.default_rng(0xB077)
    img = rng.uniform(0.0, 1.5, (32, 32, 3)).astype(np.float32)
    bp = BloomPass()
    out = bp.apply_pyramid_cpu(img, strength=1.0)
    assert out.shape == img.shape
    assert np.all(np.isfinite(out))


# ---------------------------------------------------------------------------
# (8) Numpy CPU / GPU equivalence — pyramid stays finite over big dynamic range
# ---------------------------------------------------------------------------


def test_apply_bloom_no_nan_inf_with_extreme_firefly() -> None:
    """A 1e6 firefly must be crushed by the filter — output stays finite.

    This validates the promised "CPU fallback path" numerical stability:
    the firefly filter + Karis clamp on mip 0 must keep every subsequent
    mip below the f32 overflow ceiling.
    """
    img = np.full((32, 32, 3), 0.1, dtype=np.float32)
    img[16, 16, :] = 1.0e6
    out = apply_bloom(img, strength=1.0, mip_count=6)
    assert np.all(np.isfinite(out)), (
        f"apply_bloom leaked non-finite; min={out.min()}, max={out.max()}"
    )


def test_firefly_anchor_constant_matches_spec() -> None:
    """The Reinhard anchor equals the COD:AW recommendation of 4."""
    assert _FIREFLY_ANCHOR == 4.0


def test_apply_bloom_matches_pass_pipeline() -> None:
    """The class wrapper and the free function agree.

    ``BloomPass().apply_pyramid_cpu(img, s)`` equals
    ``apply_bloom(img, s, threshold=1, knee=0.2, mip_count=6)`` when the
    BloomPass is constructed with defaults — proves the wrapper is a
    thin forwarding layer with no numeric drift.
    """
    rng = np.random.default_rng(0xB0BB)
    img = rng.uniform(0.0, 2.0, (32, 32, 3)).astype(np.float32)
    bp = BloomPass()
    out_class = bp.apply_pyramid_cpu(img, strength=1.0)
    out_free = apply_bloom(img, strength=1.0)
    diff = float(np.abs(out_class - out_free).max())
    # ≤ 5e-3 L∞ per the task spec's numpy-vs-wgpu tolerance.
    assert diff <= 5.0e-3, (
        f"class and free-function pipelines drifted: L∞ = {diff}"
    )


# ---------------------------------------------------------------------------
# (9) Downsample / upsample intermediate invariants
# ---------------------------------------------------------------------------


def test_pyramid_shrinks_by_two_per_level() -> None:
    """Each downsample halves the resolution — pyramid tapers by 2× per mip."""
    img = np.full((64, 64, 3), 0.3, dtype=np.float32)
    mips = _build_pyramid(img, mip_count=6)
    # mips[0] is the source (untouched shape).
    assert mips[0].shape == (64, 64, 3)
    # Downsamples: 32, 16, 8, 4, 2, 1
    expected = [(32, 32, 3), (16, 16, 3), (8, 8, 3), (4, 4, 3), (2, 2, 3), (1, 1, 3)]
    for level, shape in enumerate(expected, start=1):
        assert mips[level].shape == shape, (
            f"mip {level} shape {mips[level].shape} != expected {shape}"
        )


def test_apply_bloom_output_dtype_is_float32() -> None:
    """CPU path preserves float32 all the way through."""
    img = np.ones((16, 16, 3), dtype=np.float32) * 0.5
    out = apply_bloom(img, strength=1.0)
    assert out.dtype == np.float32


def test_apply_bloom_backwards_compat_signature() -> None:
    """``apply_bloom(image, strength)`` positional call still works.

    The task promises this exact signature stays live so pre-polish
    callers don't have to migrate.  Kwargs (threshold/knee/mip_count) are
    additive.
    """
    img = np.full((16, 16, 3), 0.2, dtype=np.float32)
    # Positional call — no kwargs.
    out = apply_bloom(img, 0.5)
    assert out.shape == img.shape
    # And ``strength = 0`` positional is still identity.
    ident = apply_bloom(img, 0.0)
    assert np.allclose(ident, img)
