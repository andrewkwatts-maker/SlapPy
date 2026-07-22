"""Input-validation tests for the post-process pass constructors.

Covers :class:`BloomPass`, :class:`VignettePass`, :class:`GTAOPass`,
:class:`TAAPass`. Positive paths live in the various
``tests/test_lighting_*.py`` files; this file covers the rejection
contract only.
"""
from __future__ import annotations

import math

import pytest

from pharos_engine.post_process.bloom import BloomPass
from pharos_engine.post_process.gtao import GTAOPass
from pharos_engine.post_process.taa import TAAPass
from pharos_engine.post_process.vignette import VignettePass


# ---------------------------------------------------------------------------
# BloomPass(threshold, knee, intensity)
# ---------------------------------------------------------------------------
def test_bloom_rejects_negative_threshold():
    with pytest.raises(ValueError, match="threshold"):
        BloomPass(threshold=-0.1)


def test_bloom_rejects_negative_knee():
    with pytest.raises(ValueError, match="knee"):
        BloomPass(knee=-0.01)


def test_bloom_rejects_negative_intensity():
    """Negative intensity would invert the glow — silently darken instead."""
    with pytest.raises(ValueError, match="intensity"):
        BloomPass(intensity=-1.0)


def test_bloom_rejects_nan_threshold():
    """NaN threshold passes through the luma compare silently — refuse."""
    with pytest.raises(ValueError, match="threshold"):
        BloomPass(threshold=float("nan"))


def test_bloom_rejects_inf_knee():
    with pytest.raises(ValueError, match="knee"):
        BloomPass(knee=float("inf"))


def test_bloom_rejects_string_threshold():
    with pytest.raises(TypeError, match="threshold"):
        BloomPass(threshold="1.0")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# VignettePass(strength, inner_radius, feather)
# ---------------------------------------------------------------------------
def test_vignette_rejects_negative_strength():
    with pytest.raises(ValueError, match="strength"):
        VignettePass(strength=-0.5)


def test_vignette_rejects_inner_radius_above_one():
    """inner_radius is a normalised radius — outside [0,1] is meaningless."""
    with pytest.raises(ValueError, match="inner_radius"):
        VignettePass(inner_radius=1.5)


def test_vignette_rejects_negative_inner_radius():
    with pytest.raises(ValueError, match="inner_radius"):
        VignettePass(inner_radius=-0.1)


def test_vignette_rejects_negative_feather():
    with pytest.raises(ValueError, match="feather"):
        VignettePass(feather=-0.01)


def test_vignette_rejects_nan_strength():
    with pytest.raises(ValueError, match="strength"):
        VignettePass(strength=float("nan"))


def test_vignette_rejects_inf_feather():
    with pytest.raises(ValueError, match="feather"):
        VignettePass(feather=float("inf"))


# ---------------------------------------------------------------------------
# GTAOPass — numerous positive-only params
# ---------------------------------------------------------------------------
def test_gtao_rejects_zero_num_directions():
    """num_directions==0 would div-by-zero inside the AO integrator."""
    with pytest.raises(ValueError, match="num_directions"):
        GTAOPass(num_directions=0)


def test_gtao_rejects_negative_num_steps():
    with pytest.raises(ValueError, match="num_steps"):
        GTAOPass(num_steps=-1)


def test_gtao_rejects_zero_radius():
    """radius==0 leads to a degenerate AO kernel — refuse loudly."""
    with pytest.raises(ValueError, match="radius"):
        GTAOPass(radius=0.0)


def test_gtao_rejects_zero_intensity():
    """power=1/intensity would div-by-near-zero — caught at boundary."""
    with pytest.raises(ValueError, match="intensity"):
        GTAOPass(intensity=0.0)


def test_gtao_rejects_negative_bias():
    with pytest.raises(ValueError, match="bias"):
        GTAOPass(bias=-0.01)


def test_gtao_rejects_min_radius_scale_above_one():
    with pytest.raises(ValueError, match="min_radius_scale"):
        GTAOPass(min_radius_scale=1.5)


def test_gtao_rejects_inv_proj_wrong_length():
    with pytest.raises(ValueError, match="inv_proj"):
        GTAOPass(inv_proj=(1.0, 0.0, 0.0))  # type: ignore[arg-type]


def test_gtao_rejects_inv_proj_with_nan():
    bad = list((1.0,) * 16)
    bad[5] = float("nan")
    with pytest.raises(ValueError, match="inv_proj"):
        GTAOPass(inv_proj=tuple(bad))


def test_gtao_rejects_float_num_directions():
    with pytest.raises(TypeError, match="num_directions"):
        GTAOPass(num_directions=8.0)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# TAAPass(alpha, karis_weight)
# ---------------------------------------------------------------------------
def test_taa_rejects_alpha_above_one():
    """``self.alpha`` used as a lerp factor — outside [0,1] gives bogus blends."""
    with pytest.raises(ValueError, match="alpha"):
        TAAPass(alpha=1.5)


def test_taa_rejects_negative_alpha():
    with pytest.raises(ValueError, match="alpha"):
        TAAPass(alpha=-0.1)


def test_taa_rejects_nan_alpha():
    with pytest.raises(ValueError, match="alpha"):
        TAAPass(alpha=float("nan"))


def test_taa_rejects_non_bool_karis_weight():
    """Truthy int silently coerced through `bool()` — refuse at boundary."""
    with pytest.raises(TypeError, match="karis_weight"):
        TAAPass(karis_weight=1)  # type: ignore[arg-type]


def test_taa_rejects_string_karis_weight():
    with pytest.raises(TypeError, match="karis_weight"):
        TAAPass(karis_weight="yes")  # type: ignore[arg-type]


def test_taa_rejects_negative_variance_clip_gamma():
    """``max(0, gamma-1)`` would silently coerce negative input — refuse."""
    with pytest.raises(ValueError, match="variance_clip_gamma"):
        TAAPass(variance_clip_gamma=-0.5)


def test_taa_rejects_inf_motion_weight():
    with pytest.raises(ValueError, match="motion_weight"):
        TAAPass(motion_weight=float("inf"))
