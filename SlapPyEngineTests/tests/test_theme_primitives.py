"""Tests for the ``slappyengine.ui.theme`` PRIMITIVE infrastructure.

Coverage:

* :class:`NineSlice` corner / edge / centre tiling at multiple target sizes.
* :meth:`NineSlice.render_procedural` border-only and pattern-fill paths.
* :class:`SVGIcon` parsing for rect / circle / line / polygon / path,
  caching, and YAML round-trip.
* :mod:`shader_effects` shape, dtype, and colour-range guarantees.
* :class:`ThemeSpec` YAML round-trip.
* Registry contract: :func:`register_theme` + :func:`apply_theme`.

GPU-free — every test runs on numpy arrays. PIL is required only for
the image-backed nine-slice path; we synthesise the source array
directly to avoid an external dep.
"""
from __future__ import annotations

import numpy as np
import pytest

try:
    from slappyengine.ui.theme import (
        Color,
        Font,
        NineSlice,
        Palette,
        SVGIcon,
        ShaderEffect,
        ThemeSpec,
        apply_theme,
        get_active_theme,
        highlighter_stroke,
        list_registered_themes,
        noise_glitter,
        paper_shadow,
        register_theme,
        ruled_paper,
    )
    from slappyengine.ui.theme import _reset_registry_for_tests
    from slappyengine.ui.theme.svg_icon import clear_cache as clear_svg_cache
except Exception as e:  # pragma: no cover - skip when extension absent
    pytest.skip(
        f"slappyengine.ui.theme not importable: {e}", allow_module_level=True
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Each test gets a fresh registry to avoid cross-contamination."""
    _reset_registry_for_tests()
    clear_svg_cache()
    yield
    _reset_registry_for_tests()
    clear_svg_cache()


def _checkerboard(w: int = 16, h: int = 16) -> np.ndarray:
    """Build a 16x16 RGBA checkerboard whose corners differ from centre."""
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    arr[:, :, 3] = 255
    arr[:, :, 0] = 200  # red base
    # paint each corner a unique colour so corner-preservation is testable
    arr[:4, :4, :] = (255, 0, 0, 255)        # top-left
    arr[:4, w - 4:, :] = (0, 255, 0, 255)    # top-right
    arr[h - 4:, :4, :] = (0, 0, 255, 255)    # bottom-left
    arr[h - 4:, w - 4:, :] = (255, 255, 0, 255)  # bottom-right
    arr[4:h - 4, 4:w - 4, :] = (128, 128, 128, 255)  # centre fill
    return arr


# ===========================================================================
# 1. NineSlice — image-backed render preserves corners
# ===========================================================================


def test_nineslice_corners_preserved_on_render():
    src = _checkerboard()
    ns = NineSlice(source=src, insets=(4, 4, 4, 4))
    out = ns.render(target_size=(64, 32))
    assert out.shape == (32, 64, 4)
    assert out.dtype == np.uint8
    # Corner pixels are byte-identical to source corners.
    assert tuple(out[0, 0, :]) == (255, 0, 0, 255)
    assert tuple(out[0, 63, :]) == (0, 255, 0, 255)
    assert tuple(out[31, 0, :]) == (0, 0, 255, 255)
    assert tuple(out[31, 63, :]) == (255, 255, 0, 255)


# ===========================================================================
# 2. NineSlice — edges tile, do not stretch
# ===========================================================================


def test_nineslice_edges_tile_at_large_size():
    # A 12px-wide source with 4px insets has a 4px-wide centre column
    # that must repeat to fill any wider target.
    src = np.zeros((12, 12, 4), dtype=np.uint8)
    src[:, :, 3] = 255
    src[:, :, 0] = 100
    # Mark a single column inside the centre band so we can detect tiling.
    src[6, 6, :] = (255, 255, 255, 255)
    ns = NineSlice(source=src, insets=(4, 4, 4, 4))
    out = ns.render(target_size=(128, 64))
    assert out.shape == (64, 128, 4)
    # The tiled centre must appear at least twice somewhere in the band.
    band = out[28:32, 4:124, :]
    whites = np.any(np.all(band == (255, 255, 255, 255), axis=-1), axis=0)
    assert whites.sum() >= 2


# ===========================================================================
# 3. NineSlice — render rejects too-small targets
# ===========================================================================


def test_nineslice_render_rejects_undersized_target():
    src = _checkerboard()
    ns = NineSlice(source=src, insets=(4, 4, 4, 4))
    with pytest.raises(ValueError, match="too small for insets"):
        ns.render(target_size=(4, 4))


# ===========================================================================
# 4. NineSlice — render_procedural without pattern_fn draws solid border
# ===========================================================================


def test_nineslice_procedural_solid_fill():
    ns = NineSlice(source=None, insets=(2, 2, 2, 2))
    out = ns.render_procedural(
        size=(20, 20), color=(50, 100, 150, 255), pattern_fn=None
    )
    assert out.shape == (20, 20, 4)
    # Border pixel
    assert tuple(out[0, 10, :]) == (50, 100, 150, 255)
    # Centre pixel also filled (no pattern -> solid)
    assert tuple(out[10, 10, :]) == (50, 100, 150, 255)


# ===========================================================================
# 5. NineSlice — render_procedural with pattern_fn populates centre
# ===========================================================================


def test_nineslice_procedural_with_pattern_fn():
    ns = NineSlice(source=None, insets=(2, 2, 2, 2))

    def pattern(w: int, h: int) -> np.ndarray:
        arr = np.zeros((h, w, 4), dtype=np.uint8)
        arr[:, :, 0] = 240
        arr[:, :, 1] = 30
        arr[:, :, 2] = 30
        arr[:, :, 3] = 255
        return arr

    out = ns.render_procedural(
        size=(20, 20), color=(0, 0, 0, 255), pattern_fn=pattern
    )
    # Border is black
    assert tuple(out[0, 10, :]) == (0, 0, 0, 255)
    # Centre is the pattern colour
    assert tuple(out[10, 10, :]) == (240, 30, 30, 255)


# ===========================================================================
# 6. NineSlice — bad insets raise
# ===========================================================================


def test_nineslice_rejects_bad_insets():
    with pytest.raises(ValueError, match="length 4"):
        NineSlice(source=None, insets=(1, 2, 3))


# ===========================================================================
# 7. SVGIcon — rect produces non-empty texture
# ===========================================================================


def test_svgicon_rect_produces_non_empty_texture():
    svg = (
        '<svg viewBox="0 0 16 16">'
        '<rect x="2" y="2" width="12" height="12" fill="red"/>'
        '</svg>'
    )
    icon = SVGIcon(svg_xml=svg, size=32)
    tex = icon.rasterize()
    assert tex.shape == (32, 32, 4)
    assert tex.dtype == np.uint8
    # A centre pixel must be red.
    assert tuple(tex[16, 16, :]) == (255, 0, 0, 255)
    # A corner outside the rect remains zero.
    assert tex[0, 0, 3] == 0


# ===========================================================================
# 8. SVGIcon — circle, line, polygon all parse
# ===========================================================================


def test_svgicon_circle_line_polygon():
    svg = (
        '<svg viewBox="0 0 32 32">'
        '<circle cx="16" cy="16" r="8" fill="#00ff00"/>'
        '<line x1="0" y1="0" x2="32" y2="32" stroke="black"/>'
        '<polygon points="0,32 16,16 32,32" fill="blue"/>'
        '</svg>'
    )
    icon = SVGIcon(svg_xml=svg, size=64)
    tex = icon.rasterize()
    # Circle centre at (32, 32) is overdrawn by the diagonal line; sample an
    # off-diagonal interior pixel of the green disc instead.
    assert tuple(tex[32, 36, :]) == (0, 255, 0, 255)
    # Polygon vertex region should carry some blue.
    polygon_band = tex[60:64, 30:34, :]
    blues = np.any(polygon_band[..., 2] > 200)
    assert blues


# ===========================================================================
# 9. SVGIcon — path with M/L/Z draws a filled triangle
# ===========================================================================


def test_svgicon_path_basic_commands():
    svg = (
        '<svg viewBox="0 0 32 32">'
        '<path d="M 4 28 L 16 4 L 28 28 Z" fill="#ff8800"/>'
        '</svg>'
    )
    icon = SVGIcon(svg_xml=svg, size=32)
    tex = icon.rasterize()
    # Interior triangle pixel.
    px = tuple(tex[20, 16, :])
    assert px[0] > 100 and px[1] > 50


# ===========================================================================
# 10. SVGIcon — cache returns same array
# ===========================================================================


def test_svgicon_cache_dedupes_identical_xml():
    svg = '<svg viewBox="0 0 8 8"><rect width="8" height="8" fill="white"/></svg>'
    icon_a = SVGIcon(svg_xml=svg, size=16)
    icon_b = SVGIcon(svg_xml=svg, size=16)
    tex_a = icon_a.rasterize()
    tex_b = icon_b.rasterize()
    assert tex_a is tex_b


# ===========================================================================
# 11. SVGIcon — to_dict / from_dict round-trip
# ===========================================================================


def test_svgicon_dict_roundtrip():
    svg = '<svg viewBox="0 0 4 4"><rect width="4" height="4" fill="red"/></svg>'
    icon = SVGIcon(svg_xml=svg, size=8)
    data = icon.to_dict()
    rebuilt = SVGIcon.from_dict(data)
    assert rebuilt.size == icon.size
    assert rebuilt.svg_xml == icon.svg_xml


# ===========================================================================
# 12. shader_effects.ruled_paper — shape + paper colour majority
# ===========================================================================


def test_ruled_paper_shape_and_paper_dominates():
    tex = ruled_paper(
        width=128, height=96,
        line_color=(0, 0, 255, 255),
        line_spacing=24,
        margin_color=(255, 0, 0, 255),
        margin_x=32,
        paper_color=(250, 250, 240, 255),
    )
    assert tex.shape == (96, 128, 4)
    assert tex.dtype == np.uint8
    # Most pixels must be paper-coloured (not lines).
    paper_pixels = np.all(tex[:, :, :3] == (250, 250, 240), axis=-1)
    assert paper_pixels.mean() > 0.9
    # Ruled lines exist at the expected y values.
    assert tuple(tex[24, 0, :]) == (0, 0, 255, 255)


# ===========================================================================
# 13. shader_effects.highlighter_stroke — alpha peaks at centre
# ===========================================================================


def test_highlighter_stroke_alpha_peaks_at_band_centre():
    tex = highlighter_stroke(width=64, height=20, color=(255, 230, 90, 200))
    assert tex.shape == (20, 64, 4)
    # Centre row alpha should be high relative to edges.
    centre_alpha = tex[10, :, 3].mean()
    edge_alpha = tex[0, :, 3].mean()
    assert centre_alpha > edge_alpha + 50


# ===========================================================================
# 14. shader_effects.paper_shadow — centre alpha higher than corner
# ===========================================================================


def test_paper_shadow_falloff():
    tex = paper_shadow(width=32, height=32, blur_radius=6,
                       color=(0, 0, 0, 200))
    assert tex.shape == (32, 32, 4)
    centre_a = int(tex[16, 16, 3])
    corner_a = int(tex[0, 0, 3])
    assert centre_a > corner_a


# ===========================================================================
# 15. shader_effects.noise_glitter — sparkle density matches density param
# ===========================================================================


def test_noise_glitter_density_matches_param():
    tex = noise_glitter(width=200, height=200, density=0.05,
                        color=(255, 255, 255, 255), seed=42)
    assert tex.shape == (200, 200, 4)
    lit = tex[:, :, 3] > 0
    fraction = lit.mean()
    assert 0.03 < fraction < 0.07  # within 40% of requested density


# ===========================================================================
# 16. ThemeSpec — to_dict / from_dict YAML-safe round-trip
# ===========================================================================


def test_themespec_dict_roundtrip():
    pal = {
        "primary": Color(120, 160, 255, 1.0),
        "surface": Color(28, 28, 40, 0.85),
    }
    fonts = {"body": Font(family="Inter", size=14, weight="regular")}
    bg = ShaderEffect(name="ruled_paper", params={"line_spacing": 24})
    spec = ThemeSpec(
        name="generic",
        palette=pal,
        fonts=fonts,
        nine_slices={"panel": NineSlice(source=None, insets=(4, 4, 4, 4))},
        icons={
            "check": SVGIcon(
                svg_xml='<svg viewBox="0 0 8 8"><rect width="8" height="8" fill="black"/></svg>',
                size=16,
            )
        },
        background_shader=bg,
        metadata={"author": "test"},
    )
    data = spec.to_dict()
    rebuilt = ThemeSpec.from_dict(data)
    assert rebuilt.name == "generic"
    assert rebuilt.palette["primary"].r == 120
    assert rebuilt.fonts["body"].family == "Inter"
    assert rebuilt.nine_slices["panel"].insets == (4, 4, 4, 4)
    assert isinstance(rebuilt.icons["check"], SVGIcon)
    assert rebuilt.background_shader is not None
    assert rebuilt.background_shader.name == "ruled_paper"
    assert rebuilt.metadata["author"] == "test"


# ===========================================================================
# 17. ThemeSpec YAML round-trip (requires PyYAML; skip otherwise)
# ===========================================================================


def test_themespec_yaml_roundtrip():
    pytest.importorskip("yaml")
    spec = ThemeSpec(
        name="yaml-test",
        palette={"primary": Color(255, 100, 50, 0.5)},
        fonts={"body": Font(family="Inter", size=12, weight="bold")},
        background_shader=ShaderEffect(
            name="paper_shadow", params={"blur_radius": 8}
        ),
    )
    text = spec.to_yaml()
    assert "yaml-test" in text
    rebuilt = ThemeSpec.from_yaml(text)
    assert rebuilt.name == "yaml-test"
    assert rebuilt.palette["primary"].g == 100
    assert rebuilt.fonts["body"].weight == "bold"
    assert rebuilt.background_shader is not None
    assert rebuilt.background_shader.params["blur_radius"] == 8


# ===========================================================================
# 18. register_theme + apply_theme + get_active_theme contract
# ===========================================================================


def test_register_apply_get_active_contract():
    spec = ThemeSpec(name="alpha")
    register_theme(spec)
    # apply_theme returns the resolved spec.
    out = apply_theme("alpha")
    assert out is spec
    assert get_active_theme() is spec
    # list_registered_themes reports the name.
    assert "alpha" in list_registered_themes()


def test_get_active_theme_raises_before_apply():
    with pytest.raises(LookupError, match="no theme active"):
        get_active_theme()


def test_apply_theme_unknown_name_raises():
    register_theme(ThemeSpec(name="known"))
    with pytest.raises(LookupError, match="no theme named"):
        apply_theme("missing")


def test_register_theme_rejects_non_themespec():
    with pytest.raises(TypeError, match="must be a ThemeSpec"):
        register_theme({"name": "bad"})  # type: ignore[arg-type]


# ===========================================================================
# 19. Palette construction validates entry types
# ===========================================================================


def test_palette_rejects_non_color_entries():
    with pytest.raises(TypeError, match="must be a Color"):
        Palette(name="bad", entries={"primary": (255, 0, 0)})  # type: ignore[dict-item]


# ===========================================================================
# 20. Color validation
# ===========================================================================


def test_color_rejects_out_of_range_channel():
    with pytest.raises(ValueError, match="<= 255"):
        Color(r=300)


def test_color_rejects_invalid_alpha():
    with pytest.raises(ValueError, match=r"in \[0, 1\]"):
        Color(r=10, g=10, b=10, a=1.5)
