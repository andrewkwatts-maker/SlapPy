"""Tests for :mod:`pharos_engine.ui.theme.edge_strokes`.

Covers the 15-style hand-drawn border library:

* Registry integrity — every style has a valid WGSL source string and
  the 1000-byte per-shader budget is enforced.
* Renderer output — RGBA shape, dtype, thickness respected.
* Per-style alpha character — pencil / chalk / highlighter each read
  in the correct opacity band.
* Numpy fallback keeps working with no GPU present (default state).
* Theme colour propagation — ink colour actually reaches the output.
* :class:`FrameStyle` integration — ``edge_stroke`` accepts an
  :class:`EdgeStrokeStyle` and rejects everything else.

Every test is GPU-free; the renderer's numpy path is the source of
truth for headless CI.
"""
from __future__ import annotations

import numpy as np
import pytest

try:
    from pharos_engine.ui.theme import (
        Color,
        FrameStyle,
    )
    from pharos_engine.ui.theme.edge_strokes import (
        EDGE_STROKES,
        EdgeStrokeStyle,
        bake_stroke_texture,
        get_stroke,
        has_wgpu,
        list_strokes,
        render_stroke_border,
    )
except Exception as exc:  # pragma: no cover
    pytest.skip(
        f"pharos_engine.ui.theme.edge_strokes not importable: {exc}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Expected registry entries
# ---------------------------------------------------------------------------


EXPECTED_STYLES = {
    "ballpoint_pen",
    "gel_pen",
    "pencil_2b",
    "pencil_hb",
    "marker_thick",
    "highlighter",
    "brush_watercolor",
    "chalk",
    "charcoal",
    "crayon",
    "ink_wash",
    "sharpie",
    "colored_pencil",
    "fountain_pen",
    "quill",
}


# ---------------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------------


def test_registry_has_all_15_styles() -> None:
    assert set(EDGE_STROKES.keys()) == EXPECTED_STYLES
    assert len(EDGE_STROKES) == 15
    assert set(list_strokes()) == EXPECTED_STYLES


@pytest.mark.parametrize("style_id", sorted(EXPECTED_STYLES))
def test_style_has_valid_wgsl_source(style_id: str) -> None:
    style = EDGE_STROKES[style_id]
    assert isinstance(style, EdgeStrokeStyle)
    assert style.style_id == style_id
    src = style.wgsl_source
    # Must be non-empty and contain a fragment entry point.
    assert isinstance(src, str) and len(src) > 0
    assert "@fragment" in src
    assert "fn fs_main" in src
    # Budget: source must fit under 1000 bytes.
    assert len(src.encode("utf-8")) <= 1000, (
        f"{style_id} wgsl_source exceeds 1000-byte budget "
        f"({len(src.encode('utf-8'))} bytes)"
    )
    # Shader must declare the shared uniform contract.
    assert "u_theme_color_1" in src
    assert "u_theme_color_2" in src


def test_get_stroke_returns_the_registry_entry() -> None:
    style = get_stroke("pencil_2b")
    assert style is EDGE_STROKES["pencil_2b"]


def test_get_stroke_unknown_raises_keyerror() -> None:
    with pytest.raises(KeyError, match="available"):
        get_stroke("nope_not_a_stroke")


# ---------------------------------------------------------------------------
# Canonical thickness
# ---------------------------------------------------------------------------


def test_canonical_thicknesses_match_brief() -> None:
    # Values called out explicitly in the sprint brief.
    assert EDGE_STROKES["ballpoint_pen"].thickness_px == pytest.approx(1.5)
    assert EDGE_STROKES["pencil_2b"].thickness_px == pytest.approx(2.0)
    assert EDGE_STROKES["marker_thick"].thickness_px == pytest.approx(4.0)
    assert EDGE_STROKES["highlighter"].thickness_px == pytest.approx(8.0)
    assert EDGE_STROKES["brush_watercolor"].thickness_px == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# Renderer output shape / dtype
# ---------------------------------------------------------------------------


def test_render_stroke_border_returns_four_strips() -> None:
    strips = render_stroke_border("pencil_2b", (64, 48))
    assert set(strips.keys()) == {"top", "right", "bottom", "left"}
    for strip in strips.values():
        assert isinstance(strip, np.ndarray)
        assert strip.dtype == np.uint8
        assert strip.ndim == 3
        assert strip.shape[-1] == 4


def test_render_stroke_border_thickness_respected() -> None:
    strips = render_stroke_border("pencil_2b", (64, 48), width_px=7)
    # Top / bottom shape: (thickness, width, 4)
    assert strips["top"].shape == (7, 64, 4)
    assert strips["bottom"].shape == (7, 64, 4)
    # Left / right shape: (height, thickness, 4)
    assert strips["left"].shape == (48, 7, 4)
    assert strips["right"].shape == (48, 7, 4)


def test_render_stroke_border_default_thickness_from_style() -> None:
    strips = render_stroke_border("marker_thick", (32, 32))
    # marker_thick is 4 px canonical.
    assert strips["top"].shape == (4, 32, 4)


def test_bake_stroke_texture_shape() -> None:
    tex = bake_stroke_texture("sharpie", (40, 30))
    assert tex.shape == (30, 40, 4)
    assert tex.dtype == np.uint8


# ---------------------------------------------------------------------------
# Alpha character per style
# ---------------------------------------------------------------------------


def test_pencil_alpha_in_soft_band() -> None:
    strips = render_stroke_border("pencil_2b", (256, 32))
    alpha = strips["top"][..., 3].astype(np.float32) / 255.0
    # Sanity: pencil should average roughly 0.7..1.0 (0.7 + noise*0.3),
    # then attenuated slightly by the anisotropic cross-noise.
    mean = float(alpha.mean())
    assert 0.55 < mean < 0.95, f"pencil mean alpha off: {mean}"
    # Real texture must vary — not a flat fill.
    assert float(alpha.std()) > 0.02


def test_highlighter_alpha_is_low() -> None:
    strips = render_stroke_border("highlighter", (256, 32))
    alpha = strips["top"][..., 3].astype(np.float32) / 255.0
    mean = float(alpha.mean())
    assert 0.2 < mean < 0.45, f"highlighter mean alpha off: {mean}"


def test_sharpie_alpha_is_opaque() -> None:
    strips = render_stroke_border("sharpie", (256, 32))
    alpha = strips["top"][..., 3]
    # Sharpie is a solid felt-tip; every pixel opaque.
    assert int(alpha.min()) == 255
    assert int(alpha.max()) == 255


def test_chalk_alpha_is_dry_and_crumbly() -> None:
    strips = render_stroke_border("chalk", (256, 32))
    alpha = strips["top"][..., 3].astype(np.float32) / 255.0
    # Chalk: base ~0.15 with occasional crumb peaks up to 0.7ish.
    mean = float(alpha.mean())
    assert 0.3 < mean < 0.7, f"chalk mean alpha off: {mean}"
    # Must have real variation — not a solid stroke.
    assert float(alpha.std()) > 0.05


# ---------------------------------------------------------------------------
# Numpy fallback / soft-import
# ---------------------------------------------------------------------------


def test_numpy_fallback_available_without_wgpu() -> None:
    # In the default headless environment wgpu is absent — the renderer
    # falls back to numpy and every style must still succeed.
    for style_id in list_strokes():
        strips = render_stroke_border(style_id, (32, 24))
        # Every strip is a well-formed uint8 RGBA array.
        for strip in strips.values():
            assert strip.dtype == np.uint8
            assert strip.shape[-1] == 4


def test_has_wgpu_returns_bool() -> None:
    assert isinstance(has_wgpu(), bool)


# ---------------------------------------------------------------------------
# Theme colour propagation
# ---------------------------------------------------------------------------


def test_theme_color_reaches_output() -> None:
    magenta = Color(255, 0, 200, 1.0)
    strips = render_stroke_border(
        "marker_thick", (32, 16), color_1=magenta
    )
    top = strips["top"]
    # marker_thick fills with color_1 at ~0.98 alpha — the R and B
    # channels must lead over G.
    r = float(top[..., 0].mean())
    g = float(top[..., 1].mean())
    b = float(top[..., 2].mean())
    assert r > g + 50
    assert b > g + 50


def test_theme_color_accepts_4_sequence() -> None:
    strips = render_stroke_border(
        "sharpie", (16, 16), color_1=(0, 128, 255, 255)
    )
    top = strips["top"]
    # sharpie is opaque; the pixel colour must match the input.
    assert int(top[0, 0, 0]) == 0
    assert int(top[0, 0, 1]) == 128
    assert int(top[0, 0, 2]) == 255


# ---------------------------------------------------------------------------
# FrameStyle integration
# ---------------------------------------------------------------------------


def test_framestyle_accepts_edge_stroke() -> None:
    pencil = get_stroke("pencil_2b")
    fs = FrameStyle(edge_stroke=pencil)
    assert fs.edge_stroke is pencil


def test_framestyle_default_edge_stroke_is_none() -> None:
    fs = FrameStyle()
    assert fs.edge_stroke is None


def test_framestyle_rejects_non_stroke_edge_stroke() -> None:
    with pytest.raises(TypeError, match="edge_stroke"):
        FrameStyle(edge_stroke="not a stroke")


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


def test_render_stroke_border_rejects_bad_bounds() -> None:
    with pytest.raises((TypeError, ValueError)):
        render_stroke_border("pencil_2b", (0, 32))
    with pytest.raises(TypeError):
        render_stroke_border("pencil_2b", "not a tuple")  # type: ignore[arg-type]


def test_render_stroke_border_rejects_bad_width_px() -> None:
    with pytest.raises(ValueError):
        render_stroke_border("pencil_2b", (32, 32), width_px=0)


def test_edge_stroke_style_rejects_oversize_wgsl() -> None:
    with pytest.raises(ValueError, match="1000-byte"):
        EdgeStrokeStyle(
            style_id="huge",
            thickness_px=1.0,
            alpha=1.0,
            wgsl_source="x" * 1500,
        )


def test_edge_stroke_style_rejects_bad_alpha() -> None:
    with pytest.raises((TypeError, ValueError)):
        EdgeStrokeStyle(
            style_id="bad",
            thickness_px=1.0,
            alpha=2.5,
            wgsl_source="@fragment fn fs_main() {}",
        )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_numpy_fallback_is_deterministic() -> None:
    a = render_stroke_border("pencil_2b", (64, 48))
    b = render_stroke_border("pencil_2b", (64, 48))
    for key in a:
        assert np.array_equal(a[key], b[key])
