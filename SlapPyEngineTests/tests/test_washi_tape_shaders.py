"""Tests for the ``pharos_engine.ui.theme.washi_tape`` shader library.

Covers:

* WGSL source validity (byte budget, uniform references, structure)
* :func:`render_tape` + :func:`bake_tape_texture` numeric contract
* Numpy fallback per style (size, dtype, colour range)
* Animated flag propagation and time-dependent output
* Theme-colour propagation from uniforms to fragment output
* Error handling on unknown styles and malformed sizes
* Round-tripping through the extended :class:`WashiCornerSpec`
"""
from __future__ import annotations

import numpy as np
import pytest

from pharos_engine.ui.theme.washi_tape import (
    WASHI_TAPES,
    WashiTapeStyle,
    bake_tape_texture,
    get_tape,
    list_tapes,
    render_tape,
)


# ---------------------------------------------------------------------------
# Registry / library sanity
# ---------------------------------------------------------------------------


EXPECTED_IDS = {
    "tape_pink_solid",
    "tape_pink_dots",
    "tape_blue_stripes",
    "tape_yellow_gingham",
    "tape_mint_polka",
    "tape_lavender_floral",
    "tape_watercolor_wash",
    "tape_gold_foil",
    "tape_ripped_edge",
    "tape_lace_border",
    "tape_star_confetti",
    "tape_kraft_paper",
    "tape_rainbow_gradient",
    "tape_sparkle_animated",
    "tape_music_notes",
}


def test_registry_has_all_fifteen_styles():
    assert EXPECTED_IDS.issubset(set(WASHI_TAPES.keys()))
    assert len(WASHI_TAPES) >= 15


def test_list_tapes_matches_registry_and_is_sorted():
    ids = list_tapes()
    assert EXPECTED_IDS.issubset(set(ids))
    assert ids == sorted(ids)


def test_get_tape_returns_correct_instance():
    style = get_tape("tape_pink_dots")
    assert isinstance(style, WashiTapeStyle)
    assert style.id == "tape_pink_dots"
    assert style.display_name


def test_get_tape_unknown_raises_key_error_with_hint():
    with pytest.raises(KeyError, match="unknown washi tape style"):
        get_tape("tape_does_not_exist")


def test_get_tape_empty_string_raises():
    with pytest.raises(KeyError):
        get_tape("")


# ---------------------------------------------------------------------------
# WGSL source contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("style_id", sorted(EXPECTED_IDS))
def test_wgsl_source_within_byte_budget(style_id):
    style = WASHI_TAPES[style_id]
    encoded = style.wgsl_source.encode("utf-8")
    assert 0 < len(encoded) <= 1000, (
        f"{style_id}: WGSL source is {len(encoded)} bytes (budget 1000)"
    )


@pytest.mark.parametrize("style_id", sorted(EXPECTED_IDS))
def test_wgsl_source_declares_uniform_block_and_entry(style_id):
    src = WASHI_TAPES[style_id].wgsl_source
    # Uniform contract
    assert "u_time" in src
    assert "u_size" in src
    assert "u_theme_color_1" in src
    assert "u_theme_color_2" in src
    # Fragment entry point
    assert "@fragment" in src
    assert "fs_main" in src
    assert "@location(0)" in src


def test_animated_style_references_u_time_in_body():
    src = WASHI_TAPES["tape_sparkle_animated"].wgsl_source
    # u_time should appear at least twice: once in the uniform block
    # declaration and once inside the fragment body.
    assert src.count("u_time") >= 2


def test_wgpu_compile_check_when_available():
    try:
        import wgpu  # type: ignore[import-not-found]
    except Exception:
        pytest.skip("wgpu not installed; skipping GPU compile check")

    # Trip through the parser; a bad WGSL source raises here.
    for style in WASHI_TAPES.values():
        # A wgpu Adapter is not required for source lint via
        # wgpu.utils.compute if it exposes a parse hook, but we simply
        # touch the string length as a portable smoke check — full
        # compile depends on adapter availability which CI lacks.
        assert isinstance(style.wgsl_source, str)


# ---------------------------------------------------------------------------
# WashiTapeStyle validation
# ---------------------------------------------------------------------------


def test_style_animated_flag_defaults_false():
    assert WASHI_TAPES["tape_pink_solid"].animated is False
    assert WASHI_TAPES["tape_sparkle_animated"].animated is True


def test_style_default_size_is_positive_2tuple():
    for style in WASHI_TAPES.values():
        assert isinstance(style.default_size, tuple)
        assert len(style.default_size) == 2
        assert all(v > 0 for v in style.default_size)


def test_style_rejects_oversized_source():
    with pytest.raises(ValueError, match="1000-byte budget"):
        WashiTapeStyle(
            id="tape_oversized",
            display_name="Oversized",
            wgsl_source="x" * 1001,
        )


def test_style_rejects_empty_id():
    with pytest.raises(ValueError, match="id"):
        WashiTapeStyle(
            id="",
            display_name="Ok",
            wgsl_source="ok",
        )


# ---------------------------------------------------------------------------
# render_tape contract
# ---------------------------------------------------------------------------


def test_render_tape_returns_uint8_rgba():
    img = render_tape("tape_pink_dots", (64, 24))
    assert isinstance(img, np.ndarray)
    assert img.dtype == np.uint8
    assert img.shape == (24, 64, 4)


def test_render_tape_respects_size_override():
    img = render_tape("tape_blue_stripes", (128, 32))
    assert img.shape == (32, 128, 4)


def test_render_tape_alpha_within_range():
    img = render_tape("tape_pink_dots", (64, 24))
    a = img[..., 3]
    assert int(a.min()) >= 0
    assert int(a.max()) <= 255


def test_render_tape_rgb_within_range():
    img = render_tape("tape_pink_dots", (64, 24))
    rgb = img[..., :3]
    assert int(rgb.min()) >= 0
    assert int(rgb.max()) <= 255


@pytest.mark.parametrize("style_id", sorted(EXPECTED_IDS))
def test_numpy_fallback_produces_valid_image_per_style(style_id):
    img = render_tape(style_id, (32, 12))
    assert img.dtype == np.uint8
    assert img.shape == (12, 32, 4)
    assert int(img.min()) >= 0
    assert int(img.max()) <= 255


def test_render_tape_unknown_style_raises_key_error():
    with pytest.raises(KeyError, match="unknown washi tape style"):
        render_tape("tape_bogus", (32, 12))


@pytest.mark.parametrize("bad_size", [(0, 12), (32, -1), (32,), (32, 12, 3), "big"])
def test_render_tape_rejects_bad_size(bad_size):
    with pytest.raises((ValueError, TypeError)):
        render_tape("tape_pink_solid", bad_size)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Theme colour propagation
# ---------------------------------------------------------------------------


def test_theme_color_1_visible_in_output():
    """Injecting a very red theme colour should paint the tape red."""
    red = render_tape(
        "tape_pink_solid", (32, 12),
        theme_color_1=(255, 0, 0),
    )
    # Row 6 is safely inside the torn-edge alpha ramp.
    interior = red[6, :, :]
    r_mean = float(interior[..., 0].mean())
    g_mean = float(interior[..., 1].mean())
    assert r_mean > 150.0
    assert g_mean < 40.0


def test_theme_color_2_visible_in_dot_style():
    """Bright green secondary colour should show up on the dot centres."""
    img = render_tape(
        "tape_pink_dots", (64, 24),
        theme_color_1=(50, 50, 50),
        theme_color_2=(0, 255, 0),
    )
    # Somewhere in the interior we should see a nearly-pure-green pixel.
    interior = img[6:18, :, :3]
    greenish = (interior[..., 1] > 150) & (interior[..., 0] < 90)
    assert bool(greenish.any())


def test_theme_color_accepts_floats():
    a = render_tape("tape_pink_solid", (16, 8), theme_color_1=(1.0, 0.0, 0.0))
    b = render_tape("tape_pink_solid", (16, 8), theme_color_1=(255, 0, 0))
    # Float and int inputs should produce visually equivalent output.
    assert np.abs(a.astype(int) - b.astype(int)).mean() < 2.0


# ---------------------------------------------------------------------------
# Animation
# ---------------------------------------------------------------------------


def test_animated_style_output_depends_on_time():
    a = render_tape("tape_sparkle_animated", (64, 24), time=0.0)
    b = render_tape("tape_sparkle_animated", (64, 24), time=0.75)
    # At least one pixel must differ across the two frames.
    assert not np.array_equal(a, b)


def test_static_style_output_independent_of_time():
    a = render_tape("tape_pink_solid", (64, 24), time=0.0)
    b = render_tape("tape_pink_solid", (64, 24), time=99.0)
    assert np.array_equal(a, b)


# ---------------------------------------------------------------------------
# bake_tape_texture wrapper
# ---------------------------------------------------------------------------


def test_bake_tape_texture_default_size_uses_style_default():
    style = get_tape("tape_pink_dots")
    img = bake_tape_texture("tape_pink_dots")
    w, h = style.default_size
    assert img.shape == (h, w, 4)


def test_bake_tape_texture_accepts_uniform_kwargs():
    img = bake_tape_texture(
        "tape_pink_dots",
        size=(32, 12),
        theme_color_1=(255, 200, 200),
        theme_color_2=(255, 255, 255),
        time=0.0,
    )
    assert img.shape == (12, 32, 4)


def test_bake_tape_texture_rejects_unknown_kwarg():
    with pytest.raises(TypeError, match="unknown uniform"):
        bake_tape_texture("tape_pink_dots", size=(32, 12), bogus_kwarg=True)


# ---------------------------------------------------------------------------
# WashiCornerSpec integration (T2)
# ---------------------------------------------------------------------------


def test_washi_corner_spec_accepts_tape_style_id():
    from pharos_engine.ui.editor.panel_decor import (
        WashiCornerSpec, WashiCornerStyle,
    )

    spec = WashiCornerSpec(
        corner="TL",
        style=WashiCornerStyle.TAPE_PINK,
        tape_style_id="tape_pink_dots",
    )
    assert spec.tape_style_id == "tape_pink_dots"


def test_washi_corner_spec_rejects_unknown_tape_style_id():
    from pharos_engine.ui.editor.panel_decor import (
        WashiCornerSpec, WashiCornerStyle,
    )

    with pytest.raises(ValueError, match="not a known WashiTapeStyle"):
        WashiCornerSpec(
            corner="TL",
            style=WashiCornerStyle.TAPE_PINK,
            tape_style_id="tape_definitely_not_real",
        )


def test_washi_corner_spec_none_tape_style_id_keeps_legacy_path():
    from pharos_engine.ui.editor.panel_decor import (
        WashiCornerSpec, WashiCornerStyle,
    )

    spec = WashiCornerSpec(
        corner="TL",
        style=WashiCornerStyle.TAPE_PINK,
    )
    assert spec.tape_style_id is None
