"""Tests for :mod:`slappyengine.ui.theme.wgsl_backgrounds`.

The WGSL background hook lets themes drive procedural panel
backgrounds through the engine's compute pipeline instead of only the
CPU-side numpy helpers. These tests cover:

* :class:`WGSLShaderSpec` construction + validation.
* :func:`compile_wgsl_background` end-to-end shape / dtype guarantees.
* The animated re-bake tick via :class:`WGSLBackgroundTicker`.
* Numpy fallback when ``wgpu`` isn't installed.
* Uniform propagation.
* The five entries in :data:`BUILTIN_BACKGROUNDS`.
* :class:`ThemeSpec` accepting a WGSL background side-by-side with the
  legacy :class:`ShaderEffect`.

Every test is GPU-free — the WGSL path falls back to numpy under the
soft-import policy so headless CI can exercise the full surface.
"""
from __future__ import annotations

import numpy as np
import pytest

try:
    from slappyengine.ui.theme import (
        Color,
        Gradient,
        SemanticTokens,
        ShaderEffect,
        ThemeSpec,
        WGSLShaderSpec,
        WGSLBackgroundTicker,
        BUILTIN_BACKGROUNDS,
        apply_theme,
        compile_wgsl_background,
        get_baked_background,
        has_wgpu,
        register_theme,
        resolve_background,
    )
    from slappyengine.ui.theme import _reset_registry_for_tests
    from slappyengine.ui.theme import wgsl_backgrounds as _wgsl_mod
except Exception as exc:  # pragma: no cover - skip when extension absent
    pytest.skip(
        f"slappyengine.ui.theme not importable: {exc}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_semantic() -> SemanticTokens:
    primary = Color(120, 80, 200, 1.0)
    lighter = Color(160, 130, 220, 1.0)
    return SemanticTokens(
        primary=primary,
        primary_gradient=Gradient(start=primary, end=lighter, angle_deg=135.0),
        secondary=Color(80, 120, 200, 1.0),
        accent=Color(255, 180, 0, 1.0),
        background=Color(20, 20, 28, 1.0),
        surface=Color(28, 28, 36, 0.95),
        surface_hover=Color(36, 36, 48, 0.95),
        border=Color(60, 60, 70, 1.0),
        text_primary=Color(240, 240, 245, 1.0),
        text_secondary=Color(180, 180, 190, 1.0),
        text_disabled=Color(120, 120, 130, 1.0),
        success=Color(0, 200, 100, 1.0),
        warning=Color(255, 180, 0, 1.0),
        error=Color(220, 60, 60, 1.0),
        info=Color(80, 160, 220, 1.0),
        focus_ring=Color(255, 180, 0, 1.0),
        glass_bg=Color(255, 255, 255, 0.1),
        glass_blur_px=8.0,
    )


@pytest.fixture
def reset_registry():
    """Reset the theme registry between tests so applied themes don't leak."""
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


@pytest.fixture
def simple_wgsl_source() -> str:
    return BUILTIN_BACKGROUNDS["ruled_paper_wgsl"]


# ---------------------------------------------------------------------------
# WGSLShaderSpec construction
# ---------------------------------------------------------------------------


def test_wgsl_shader_spec_construction_defaults(simple_wgsl_source):
    spec = WGSLShaderSpec(source=simple_wgsl_source)
    assert spec.source == simple_wgsl_source
    assert spec.entry_point == "fs_main"
    assert spec.output_size == (128, 128)
    assert spec.animated is False
    assert spec.frame_ms == 100.0
    assert spec.uniforms == {}


def test_wgsl_shader_spec_custom_fields(simple_wgsl_source):
    spec = WGSLShaderSpec(
        source=simple_wgsl_source,
        entry_point="my_entry",
        output_size=(64, 32),
        animated=True,
        frame_ms=250.0,
        uniforms={"u_time": 0.0, "u_amp": 0.5},
    )
    assert spec.entry_point == "my_entry"
    assert spec.output_size == (64, 32)
    assert spec.animated is True
    assert spec.frame_ms == 250.0
    assert spec.uniforms["u_amp"] == 0.5


def test_wgsl_shader_spec_rejects_empty_source():
    with pytest.raises(ValueError):
        WGSLShaderSpec(source="")


def test_wgsl_shader_spec_rejects_bad_animated_flag(simple_wgsl_source):
    with pytest.raises(TypeError):
        WGSLShaderSpec(source=simple_wgsl_source, animated="yes")  # type: ignore[arg-type]


def test_wgsl_shader_spec_rejects_negative_frame_ms(simple_wgsl_source):
    with pytest.raises(ValueError):
        WGSLShaderSpec(source=simple_wgsl_source, animated=True, frame_ms=-1.0)


def test_wgsl_shader_spec_rejects_bad_output_size(simple_wgsl_source):
    with pytest.raises((TypeError, ValueError)):
        WGSLShaderSpec(source=simple_wgsl_source, output_size="128x128")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        WGSLShaderSpec(source=simple_wgsl_source, output_size=(0, 32))


def test_wgsl_shader_spec_output_size_from_list(simple_wgsl_source):
    """YAML round-trip yields a list — the spec should coerce to a tuple."""
    spec = WGSLShaderSpec(source=simple_wgsl_source, output_size=[16, 24])  # type: ignore[arg-type]
    assert spec.output_size == (16, 24)


def test_wgsl_shader_spec_uniform_keys_must_be_strings(simple_wgsl_source):
    with pytest.raises(TypeError):
        WGSLShaderSpec(source=simple_wgsl_source, uniforms={1: 2.0})  # type: ignore[dict-item]


def test_wgsl_shader_spec_effective_frame_ms_clamps(simple_wgsl_source):
    """The animated tick cap is 10 Hz (100 ms/bake)."""
    spec = WGSLShaderSpec(
        source=simple_wgsl_source, animated=True, frame_ms=10.0,
    )
    assert spec.effective_frame_ms() == 100.0
    slow = WGSLShaderSpec(
        source=simple_wgsl_source, animated=True, frame_ms=500.0,
    )
    assert slow.effective_frame_ms() == 500.0


def test_wgsl_shader_spec_yaml_roundtrip(simple_wgsl_source):
    spec = WGSLShaderSpec(
        source=simple_wgsl_source,
        entry_point="fs_main",
        output_size=(32, 32),
        animated=True,
        frame_ms=150.0,
        uniforms={"u_amp": 0.7},
    )
    payload = spec.to_dict()
    restored = WGSLShaderSpec.from_dict(payload)
    assert restored.source == spec.source
    assert restored.entry_point == spec.entry_point
    assert restored.output_size == spec.output_size
    assert restored.animated == spec.animated
    assert restored.frame_ms == spec.frame_ms
    assert restored.uniforms == spec.uniforms


# ---------------------------------------------------------------------------
# compile_wgsl_background
# ---------------------------------------------------------------------------


def test_compile_returns_valid_rgba_array(simple_wgsl_source):
    spec = WGSLShaderSpec(source=simple_wgsl_source, output_size=(32, 24))
    out = compile_wgsl_background(spec)
    assert isinstance(out, np.ndarray)
    assert out.dtype == np.uint8
    assert out.ndim == 3
    assert out.shape == (24, 32, 4)


def test_compile_rejects_non_spec():
    with pytest.raises(TypeError):
        compile_wgsl_background({"source": "..."})  # type: ignore[arg-type]


def test_compile_respects_output_size(simple_wgsl_source):
    spec = WGSLShaderSpec(source=simple_wgsl_source, output_size=(48, 16))
    out = compile_wgsl_background(spec)
    # numpy shape is (H, W, C); spec.output_size is (W, H)
    assert out.shape == (16, 48, 4)


def test_compile_all_builtin_shaders_produce_valid_arrays():
    for name, source in BUILTIN_BACKGROUNDS.items():
        spec = WGSLShaderSpec(source=source, output_size=(16, 16))
        out = compile_wgsl_background(spec)
        assert out.shape == (16, 16, 4), name
        assert out.dtype == np.uint8, name


# ---------------------------------------------------------------------------
# Numpy fallback path
# ---------------------------------------------------------------------------


def test_fallback_when_wgpu_missing(simple_wgsl_source, monkeypatch):
    """Force the fallback path by faking wgpu as absent."""
    monkeypatch.setattr(_wgsl_mod, "_HAS_WGPU", False)
    spec = WGSLShaderSpec(source=simple_wgsl_source, output_size=(24, 24))
    out = compile_wgsl_background(spec)
    # Fallback = ruled_paper of the requested size.
    assert out.shape == (24, 24, 4)
    assert out.dtype == np.uint8
    # Paper base colour (252, 250, 240) should appear on non-line rows.
    # Row 0 sits above the first ruled line at y=spacing=24, so it must
    # match the paper fill.
    assert tuple(out[0, 0, :3].tolist()) == (252, 250, 240)


def test_has_wgpu_flag_is_bool():
    assert isinstance(has_wgpu(), bool)


# ---------------------------------------------------------------------------
# Uniform propagation
# ---------------------------------------------------------------------------


def test_uniforms_survive_yaml_roundtrip(simple_wgsl_source):
    spec = WGSLShaderSpec(
        source=simple_wgsl_source,
        uniforms={"u_time": 1.25, "u_theme_accent": [1.0, 0.5, 0.0, 1.0]},
    )
    restored = WGSLShaderSpec.from_dict(spec.to_dict())
    assert restored.uniforms["u_time"] == 1.25
    assert restored.uniforms["u_theme_accent"] == [1.0, 0.5, 0.0, 1.0]


def test_uniforms_default_empty(simple_wgsl_source):
    spec = WGSLShaderSpec(source=simple_wgsl_source)
    # Uniform dict must be independently mutable per instance.
    spec.uniforms["u_x"] = 1.0
    spec2 = WGSLShaderSpec(source=simple_wgsl_source)
    assert spec2.uniforms == {}


# ---------------------------------------------------------------------------
# BUILTIN_BACKGROUNDS
# ---------------------------------------------------------------------------


def test_builtin_backgrounds_has_five_entries():
    assert len(BUILTIN_BACKGROUNDS) == 5


def test_builtin_backgrounds_expected_keys():
    expected = {
        "ruled_paper_wgsl",
        "dot_grid_wgsl",
        "sparkle_wgsl",
        "watercolor_wgsl",
        "aurora_wgsl",
    }
    assert set(BUILTIN_BACKGROUNDS) == expected


def test_builtin_shader_sources_are_non_empty_strings():
    for name, src in BUILTIN_BACKGROUNDS.items():
        assert isinstance(src, str), name
        assert src.strip(), name
        assert "fs_main" in src, name


def test_aurora_shader_is_animated_capable():
    """The aurora shader declares a time uniform — flag it as animated."""
    spec = WGSLShaderSpec(
        source=BUILTIN_BACKGROUNDS["aurora_wgsl"],
        animated=True,
        frame_ms=200.0,
        uniforms={"u_time": 0.0, "u_size": [128.0, 128.0]},
    )
    assert spec.animated
    assert "u_time" in spec.source


# ---------------------------------------------------------------------------
# Animated tick loop
# ---------------------------------------------------------------------------


def test_animated_ticker_refreshes_after_interval(simple_wgsl_source):
    spec = WGSLShaderSpec(
        source=simple_wgsl_source, animated=True, frame_ms=100.0,
    )
    # Anchor the ticker at t=0 so the explicit ``now`` values below
    # land in the same clock as the ticker's internal reference.
    ticker = WGSLBackgroundTicker(spec, initial_bake=True, now=0.0)
    assert ticker.bake_count == 1
    assert ticker.current is not None
    # Immediately re-tick: cadence not elapsed → no bake.
    assert ticker.tick(now=0.001) is None
    # Advance past the cadence: re-bake fires.
    baked = ticker.tick(now=spec.effective_frame_ms() / 1000.0 + 0.01)
    assert baked is not None
    assert ticker.bake_count == 2


def test_ticker_rejects_non_animated_spec(simple_wgsl_source):
    spec = WGSLShaderSpec(source=simple_wgsl_source, animated=False)
    with pytest.raises(ValueError):
        WGSLBackgroundTicker(spec)


def test_ticker_rejects_bad_spec():
    with pytest.raises(TypeError):
        WGSLBackgroundTicker({"source": "..."})  # type: ignore[arg-type]


def test_ticker_no_initial_bake(simple_wgsl_source):
    spec = WGSLShaderSpec(
        source=simple_wgsl_source, animated=True, frame_ms=100.0,
    )
    ticker = WGSLBackgroundTicker(spec, initial_bake=False)
    assert ticker.current is None
    assert ticker.bake_count == 0


def test_animated_flag_toggles_refresh_loop(simple_wgsl_source):
    """Non-animated specs should not be admissible to the ticker."""
    static = WGSLShaderSpec(source=simple_wgsl_source, animated=False)
    with pytest.raises(ValueError):
        WGSLBackgroundTicker(static)
    live = WGSLShaderSpec(
        source=simple_wgsl_source, animated=True, frame_ms=100.0,
    )
    ticker = WGSLBackgroundTicker(live)
    assert isinstance(ticker.current, np.ndarray)


# ---------------------------------------------------------------------------
# ThemeSpec integration
# ---------------------------------------------------------------------------


def test_theme_with_wgsl_background_constructs(simple_wgsl_source):
    spec = WGSLShaderSpec(source=simple_wgsl_source)
    theme = ThemeSpec(
        name="wgsl-demo",
        semantic=_make_semantic(),
        background_shader=spec,
    )
    assert theme.background_shader is spec


def test_theme_with_shader_effect_still_constructs():
    """Legacy path: :class:`ShaderEffect` must keep working side-by-side."""
    theme = ThemeSpec(
        name="numpy-demo",
        semantic=_make_semantic(),
        background_shader=ShaderEffect(name="ruled_paper", params={
            "width": 32, "height": 32,
        }),
    )
    assert theme.background_shader.name == "ruled_paper"


def test_theme_rejects_bad_background_shader():
    with pytest.raises(TypeError):
        ThemeSpec(
            name="bad",
            semantic=_make_semantic(),
            background_shader=42,  # type: ignore[arg-type]
        )


def test_apply_theme_bakes_wgsl_background(reset_registry, simple_wgsl_source):
    spec = WGSLShaderSpec(source=simple_wgsl_source, output_size=(32, 16))
    theme = ThemeSpec(
        name="wgsl-apply",
        semantic=_make_semantic(),
        background_shader=spec,
    )
    register_theme(theme)
    apply_theme("wgsl-apply")
    baked = get_baked_background()
    assert isinstance(baked, np.ndarray)
    assert baked.shape == (16, 32, 4)


def test_apply_theme_bakes_shader_effect_background(reset_registry):
    theme = ThemeSpec(
        name="numpy-apply",
        semantic=_make_semantic(),
        background_shader=ShaderEffect(name="ruled_paper", params={
            "width": 8, "height": 8,
        }),
    )
    register_theme(theme)
    apply_theme("numpy-apply")
    baked = get_baked_background()
    assert isinstance(baked, np.ndarray)
    assert baked.shape == (8, 8, 4)


def test_theme_switch_between_numpy_and_wgsl(reset_registry, simple_wgsl_source):
    numpy_theme = ThemeSpec(
        name="np",
        semantic=_make_semantic(),
        background_shader=ShaderEffect(name="ruled_paper", params={
            "width": 12, "height": 12,
        }),
    )
    wgsl_theme = ThemeSpec(
        name="wg",
        semantic=_make_semantic(),
        background_shader=WGSLShaderSpec(
            source=simple_wgsl_source, output_size=(20, 20),
        ),
    )
    register_theme(numpy_theme)
    register_theme(wgsl_theme)

    apply_theme("np")
    assert get_baked_background().shape == (12, 12, 4)

    apply_theme("wg")
    assert get_baked_background().shape == (20, 20, 4)

    apply_theme("np")
    assert get_baked_background().shape == (12, 12, 4)


def test_theme_yaml_roundtrip_preserves_wgsl_spec(simple_wgsl_source):
    theme = ThemeSpec(
        name="rt",
        semantic=_make_semantic(),
        background_shader=WGSLShaderSpec(
            source=simple_wgsl_source,
            entry_point="fs_main",
            output_size=(48, 48),
            animated=True,
            frame_ms=150.0,
            uniforms={"u_time": 0.0},
        ),
    )
    payload = theme.to_dict()
    restored = ThemeSpec.from_dict(payload)
    assert isinstance(restored.background_shader, WGSLShaderSpec)
    assert restored.background_shader.source == simple_wgsl_source
    assert restored.background_shader.animated is True
    assert restored.background_shader.output_size == (48, 48)


def test_theme_yaml_roundtrip_preserves_shader_effect():
    theme = ThemeSpec(
        name="rt-legacy",
        semantic=_make_semantic(),
        background_shader=ShaderEffect(name="ruled_paper", params={
            "width": 8, "height": 8,
        }),
    )
    restored = ThemeSpec.from_dict(theme.to_dict())
    assert isinstance(restored.background_shader, ShaderEffect)
    assert restored.background_shader.name == "ruled_paper"


# ---------------------------------------------------------------------------
# resolve_background dispatcher
# ---------------------------------------------------------------------------


def test_resolve_background_handles_none():
    assert resolve_background(None) is None


def test_resolve_background_dispatches_wgsl(simple_wgsl_source):
    spec = WGSLShaderSpec(source=simple_wgsl_source, output_size=(16, 16))
    out = resolve_background(spec)
    assert isinstance(out, np.ndarray)
    assert out.shape == (16, 16, 4)


def test_resolve_background_dispatches_shader_effect():
    fx = ShaderEffect(name="ruled_paper", params={"width": 8, "height": 8})
    out = resolve_background(fx)
    assert isinstance(out, np.ndarray)
    assert out.shape == (8, 8, 4)


def test_resolve_background_unknown_shader_effect_returns_none():
    fx = ShaderEffect(name="does_not_exist", params={})
    assert resolve_background(fx) is None
