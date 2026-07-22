"""Regression tests for the BBB5 AAA-quality page-lining shader upgrade.

Covers:

* Each upgraded preset (``ruled_paper``, ``dot_grid``, ``graph_grid``,
  ``blank_cream``) renders with ``AAAShaderQualityPreset.HIGH`` without
  exception.
* Output shape unchanged across all quality tiers.
* ``LOW`` preset is deterministic (two runs identical).
* ``HIGH`` preset shows luma variance (std > 3.0) proving grain
  actually reaches the pixels.
* ``shader_effects.ruled_paper`` accepts the three new kwargs and
  falls back to legacy pixel-perfect output when all AAA kwargs default
  to ``0.0``.
* Deterministic re-run at ``HIGH`` (same size + inputs → same bytes).
"""
from __future__ import annotations

import numpy as np
import pytest

from pharos_editor.ui.theme.page_linings import (
    AAAShaderQualityPreset,
    DEFAULT_AAA_PRESET,
    render_lining,
)
from pharos_editor.ui.theme.shader_effects import ruled_paper


AAA_UPGRADED_PRESETS = ("ruled_paper", "dot_grid", "graph_grid", "blank_cream")


# ---------------------------------------------------------------------------
# Preset dataclass sanity
# ---------------------------------------------------------------------------


def test_quality_preset_exposes_three_tiers():
    """LOW / MEDIUM / HIGH are all wired up as class attributes."""
    for tier in ("LOW", "MEDIUM", "HIGH"):
        preset = getattr(AAAShaderQualityPreset, tier)
        assert isinstance(preset, AAAShaderQualityPreset)
        assert preset.tier == tier.lower()


def test_default_preset_is_high():
    """The module-level default corresponds to the HIGH tier."""
    assert DEFAULT_AAA_PRESET is AAAShaderQualityPreset.HIGH


def test_low_preset_is_all_zeros():
    """LOW must have every knob at 0.0 so it matches legacy output byte-for-byte."""
    low = AAAShaderQualityPreset.LOW
    assert low.grain_intensity == 0.0
    assert low.line_aa_px == 0.0
    assert low.jitter_px == 0.0
    assert low.warm_tint == 0.0
    assert low.dot_alpha_variance == 0.0
    assert low.ink_bleed == 0.0


def test_high_preset_enables_grain_and_jitter():
    """HIGH must enable the four AAA effects called out in the sprint spec."""
    high = AAAShaderQualityPreset.HIGH
    assert high.grain_intensity > 0.0
    assert high.line_aa_px > 0.0
    assert high.jitter_px > 0.0
    assert high.warm_tint > 0.0


# ---------------------------------------------------------------------------
# Render each upgraded preset at HIGH quality without exception
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("style_id", AAA_UPGRADED_PRESETS)
def test_high_quality_renders_without_exception(style_id):
    """Each upgraded preset must render at HIGH quality without exception."""
    arr = render_lining(
        style_id,
        (64, 48),
        force_fallback=True,
        quality=AAAShaderQualityPreset.HIGH,
    )
    assert arr.shape == (48, 64, 4)
    assert arr.dtype == np.uint8


@pytest.mark.parametrize("style_id", AAA_UPGRADED_PRESETS)
def test_output_shape_unchanged_across_tiers(style_id):
    """The (H, W, 4) shape is invariant under quality tier."""
    for tier in (
        AAAShaderQualityPreset.LOW,
        AAAShaderQualityPreset.MEDIUM,
        AAAShaderQualityPreset.HIGH,
    ):
        arr = render_lining(
            style_id, (64, 48), force_fallback=True, quality=tier,
        )
        assert arr.shape == (48, 64, 4)
        assert arr.dtype == np.uint8
        assert np.all(arr[..., 3] == 255)


# ---------------------------------------------------------------------------
# LOW preset determinism — two runs identical
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("style_id", AAA_UPGRADED_PRESETS)
def test_low_preset_deterministic(style_id):
    """LOW must be byte-for-byte reproducible."""
    a = render_lining(
        style_id, (48, 32), force_fallback=True,
        quality=AAAShaderQualityPreset.LOW,
    )
    b = render_lining(
        style_id, (48, 32), force_fallback=True,
        quality=AAAShaderQualityPreset.LOW,
    )
    assert np.array_equal(a, b), f"{style_id}: LOW preset not deterministic"


@pytest.mark.parametrize("style_id", AAA_UPGRADED_PRESETS)
def test_low_matches_no_quality_arg(style_id):
    """LOW output must match the default (no quality arg) legacy path exactly."""
    low = render_lining(
        style_id, (48, 32), force_fallback=True,
        quality=AAAShaderQualityPreset.LOW,
    )
    legacy = render_lining(style_id, (48, 32), force_fallback=True)
    assert np.array_equal(low, legacy), (
        f"{style_id}: LOW preset diverged from legacy output"
    )


# ---------------------------------------------------------------------------
# HIGH preset introduces luma variance — proves grain is actually applied
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("style_id", AAA_UPGRADED_PRESETS)
def test_high_preset_shows_luma_variance(style_id):
    """HIGH must produce a per-pixel luma std > 3.0 so grain is visible."""
    arr = render_lining(
        style_id, (128, 96), force_fallback=True,
        quality=AAAShaderQualityPreset.HIGH,
    )
    # Rec.709 luma = 0.2126 R + 0.7152 G + 0.0722 B.
    luma = (
        0.2126 * arr[..., 0].astype(np.float32)
        + 0.7152 * arr[..., 1].astype(np.float32)
        + 0.0722 * arr[..., 2].astype(np.float32)
    )
    std = float(luma.std())
    assert std > 3.0, (
        f"{style_id}: HIGH luma std {std:.2f} is too flat — grain not applied?"
    )


@pytest.mark.parametrize("style_id", AAA_UPGRADED_PRESETS)
def test_high_preset_deterministic_across_runs(style_id):
    """HIGH must still be deterministic (seeded RNG) — two runs identical."""
    a = render_lining(
        style_id, (64, 48), force_fallback=True,
        quality=AAAShaderQualityPreset.HIGH,
    )
    b = render_lining(
        style_id, (64, 48), force_fallback=True,
        quality=AAAShaderQualityPreset.HIGH,
    )
    assert np.array_equal(a, b), f"{style_id}: HIGH preset not deterministic"


# ---------------------------------------------------------------------------
# shader_effects.ruled_paper — new kwargs preserve backward compatibility
# ---------------------------------------------------------------------------


def test_ruled_paper_defaults_preserve_legacy_output():
    """Default kwargs (all AAA extras zero) must match the legacy path exactly."""
    tex = ruled_paper(width=128, height=96)
    # Row 24 must still be the exact line colour (default = (180, 200, 230, 255)).
    assert tuple(tex[24, 0, :]) == (180, 200, 230, 255)
    # Row 0 must be exactly the default paper colour (252, 250, 240, 255).
    assert tuple(tex[0, 0, :]) == (252, 250, 240, 255)


def test_ruled_paper_grain_kwarg_introduces_variance():
    """A non-zero grain_intensity kwarg must add luma variance."""
    tex_flat = ruled_paper(width=64, height=48)
    tex_grainy = ruled_paper(width=64, height=48, grain_intensity=0.05)
    assert tex_flat.shape == tex_grainy.shape
    flat_std = float(tex_flat[..., :3].astype(np.float32).std())
    grain_std = float(tex_grainy[..., :3].astype(np.float32).std())
    assert grain_std > flat_std + 1.0


def test_ruled_paper_jitter_kwarg_accepted():
    """jitter_px kwarg must be accepted + preserve output shape."""
    tex = ruled_paper(width=64, height=48, jitter_px=0.5)
    assert tex.shape == (48, 64, 4)


def test_ruled_paper_warm_tint_kwarg_accepted():
    """warm_tint kwarg must be accepted + preserve output shape."""
    tex = ruled_paper(width=64, height=48, warm_tint=0.05)
    assert tex.shape == (48, 64, 4)


def test_ruled_paper_all_aaa_kwargs_together():
    """All three new AAA kwargs coexist without error."""
    tex = ruled_paper(
        width=64, height=48,
        grain_intensity=0.02,
        jitter_px=0.5,
        warm_tint=0.05,
    )
    assert tex.shape == (48, 64, 4)
    assert tex.dtype == np.uint8


def test_ruled_paper_rejects_out_of_range_kwargs():
    """The new kwargs must validate their ranges."""
    with pytest.raises((ValueError, TypeError)):
        ruled_paper(width=32, height=32, grain_intensity=2.0)
    with pytest.raises((ValueError, TypeError)):
        ruled_paper(width=32, height=32, jitter_px=99.0)
    with pytest.raises((ValueError, TypeError)):
        ruled_paper(width=32, height=32, warm_tint=-0.5)
