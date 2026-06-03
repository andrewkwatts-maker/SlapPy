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
        Gradient,
        NineSlice,
        Palette,
        RadiusScale,
        SemanticTokens,
        SpacingScale,
        SVGIcon,
        ShaderEffect,
        ThemeSpec,
        TransitionScale,
        ZIndexScale,
        apply_theme,
        dot_grid,
        frosted_panel,
        get_active_theme,
        glass_blur,
        highlighter_stroke,
        list_registered_themes,
        noise_glitter,
        paper_shadow,
        parchment,
        register_theme,
        ruled_paper,
        watercolor_wash,
    )
    from slappyengine.ui.theme import _reset_registry_for_tests
    from slappyengine.ui.theme.svg_icon import clear_cache as clear_svg_cache
except Exception as e:  # pragma: no cover - skip when extension absent
    pytest.skip(
        f"slappyengine.ui.theme not importable: {e}", allow_module_level=True
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_semantic() -> SemanticTokens:
    """Build a minimal, valid SemanticTokens for tests that don't care
    about specific token values (they just need a ThemeSpec to construct).
    """
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
        text_disabled=Color(100, 100, 110, 1.0),
        success=Color(80, 200, 120, 1.0),
        warning=Color(240, 180, 60, 1.0),
        error=Color(220, 70, 70, 1.0),
        info=Color(80, 160, 240, 1.0),
        focus_ring=Color(120, 200, 255, 1.0),
        glass_bg=Color(255, 255, 255, 0.1),
        glass_blur_px=10.0,
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
        semantic=_make_semantic(),
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
        semantic=_make_semantic(),
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
    spec = ThemeSpec(name="alpha", semantic=_make_semantic())
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
    register_theme(ThemeSpec(name="known", semantic=_make_semantic()))
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


# ===========================================================================
# 21. shader_effects.glass_blur — dims preserved + tint visible
# ===========================================================================


def _solid_source(w: int, h: int, rgba: tuple[int, int, int, int]) -> np.ndarray:
    out = np.empty((h, w, 4), dtype=np.uint8)
    out[:, :, :] = rgba
    return out


def test_glass_blur_dims_match_source():
    src = _solid_source(32, 24, (40, 80, 160, 255))
    out = glass_blur(src, blur_radius=5, opacity=0.1)
    assert out.shape == src.shape
    assert out.dtype == np.uint8


def test_glass_blur_default_tint_brightens_dark_source():
    src = _solid_source(40, 40, (10, 10, 10, 255))
    out = glass_blur(src, blur_radius=3, opacity=0.5)
    # White-default tint at 50% must lift the dark backdrop substantially.
    assert int(out[20, 20, 0]) > 100
    assert int(out[20, 20, 1]) > 100
    assert int(out[20, 20, 2]) > 100


def test_glass_blur_tint_color_applied():
    src = _solid_source(40, 40, (0, 0, 0, 255))
    out = glass_blur(src, blur_radius=3, opacity=0.8, tint=(255, 0, 0, 255))
    # Heavy red tint over a black backdrop must be predominantly red.
    px = out[20, 20]
    assert int(px[0]) > 150
    assert int(px[1]) < 60
    assert int(px[2]) < 60


def test_glass_blur_rejects_negative_radius():
    src = _solid_source(8, 8, (0, 0, 0, 255))
    with pytest.raises(ValueError, match=">= 1"):
        glass_blur(src, blur_radius=-2, opacity=0.1)


# ===========================================================================
# 22. shader_effects.frosted_panel — non-zero output + border drawn
# ===========================================================================


def test_frosted_panel_produces_non_zero_output():
    tex = frosted_panel(width=48, height=32, blur_radius=5, opacity=0.1)
    assert tex.shape == (32, 48, 4)
    assert tex.dtype == np.uint8
    # Interior must carry colour (not the all-zero default).
    interior = tex[8:24, 8:40, :3]
    assert interior.mean() > 50


def test_frosted_panel_border_color_visible():
    tex = frosted_panel(
        width=32, height=24, blur_radius=4, opacity=0.1,
        border_color=(255, 0, 0, 255),
    )
    # Top + bottom rows, left + right columns wear the border colour.
    assert tuple(tex[0, 15, :]) == (255, 0, 0, 255)
    assert tuple(tex[23, 15, :]) == (255, 0, 0, 255)
    assert tuple(tex[10, 0, :]) == (255, 0, 0, 255)
    assert tuple(tex[10, 31, :]) == (255, 0, 0, 255)


def test_frosted_panel_rejects_nan_opacity():
    with pytest.raises(ValueError, match="finite"):
        frosted_panel(width=16, height=16, opacity=float("nan"))


# ===========================================================================
# 23. shader_effects.dot_grid — dot count + bg fill
# ===========================================================================


def test_dot_grid_dot_count_matches_lattice():
    # 80 / 8 = 10 columns, 64 / 8 = 8 rows → 80 dots.
    tex = dot_grid(
        width=80, height=64,
        dot_color=(255, 255, 255, 255),
        dot_radius=1, spacing=8,
    )
    assert tex.shape == (64, 80, 4)
    lit = tex[:, :, 3] > 0
    assert lit.sum() == 80


def test_dot_grid_background_fill():
    tex = dot_grid(
        width=32, height=32,
        dot_color=(255, 255, 255, 255),
        dot_radius=1, spacing=8,
        bg_color=(20, 40, 60, 255),
    )
    # A pixel not on the dot lattice must carry the background colour.
    assert tuple(tex[1, 1, :]) == (20, 40, 60, 255)


def test_dot_grid_rejects_zero_spacing():
    with pytest.raises(ValueError, match=">= 1"):
        dot_grid(width=16, height=16, dot_color=(1, 1, 1, 255), spacing=0)


# ===========================================================================
# 24. shader_effects.parchment — dims + edges darker than centre
# ===========================================================================


def test_parchment_dims_and_edges_darker():
    tex = parchment(
        width=64, height=64,
        base_color=(220, 200, 160, 255),
        edge_dark=0.7, noise_amount=0.02,
    )
    assert tex.shape == (64, 64, 4)
    assert tex.dtype == np.uint8
    centre = tex[28:36, 28:36, :3].astype(np.float32).mean()
    corners = np.concatenate([
        tex[:4, :4, :3].reshape(-1, 3),
        tex[:4, -4:, :3].reshape(-1, 3),
        tex[-4:, :4, :3].reshape(-1, 3),
        tex[-4:, -4:, :3].reshape(-1, 3),
    ]).astype(np.float32).mean()
    assert centre > corners + 5  # noise band ≪ vignette


def test_parchment_rejects_out_of_range_edge_dark():
    with pytest.raises(ValueError, match=r"in \[0, 1\]"):
        parchment(width=16, height=16, base_color=(200, 180, 140, 255),
                  edge_dark=1.5)


# ===========================================================================
# 25. shader_effects.watercolor_wash — dims + each wash contributes
# ===========================================================================


def test_watercolor_wash_dims_and_coverage():
    palette = [
        (255, 120, 120, 255),
        (120, 200, 255, 255),
        (200, 255, 160, 255),
    ]
    tex = watercolor_wash(
        width=64, height=48, color_palette=palette,
        wash_count=3, opacity=0.4, seed=7,
    )
    assert tex.shape == (48, 64, 4)
    assert tex.dtype == np.uint8
    # Some pixels must have non-zero alpha (washes covered ground).
    assert (tex[:, :, 3] > 0).sum() > 100


def test_watercolor_wash_each_wash_contributes():
    palette_one = [(255, 0, 0, 255)]
    one = watercolor_wash(
        width=48, height=48, color_palette=palette_one,
        wash_count=1, opacity=0.4, seed=123,
    )
    three = watercolor_wash(
        width=48, height=48, color_palette=palette_one,
        wash_count=3, opacity=0.4, seed=123,
    )
    # Three overlapping washes cover more area than one.
    assert (three[:, :, 3] > 0).sum() >= (one[:, :, 3] > 0).sum()


def test_watercolor_wash_rejects_empty_palette():
    with pytest.raises(ValueError, match="non-empty"):
        watercolor_wash(width=16, height=16, color_palette=[],
                        wash_count=1, opacity=0.3)


def test_watercolor_wash_rejects_negative_count():
    with pytest.raises(ValueError, match=">= 1"):
        watercolor_wash(
            width=16, height=16,
            color_palette=[(255, 0, 0, 255)],
            wash_count=-1, opacity=0.3,
        )


# ===========================================================================
# Semantic tokens + design-system primitives (EyesOfAzrael influence)
# ===========================================================================


# 1. SpacingScale — defaults + rejects negatives
def test_spacing_scale_defaults_and_validation():
    s = SpacingScale()
    assert s.xs == 4.0 and s.sm == 8.0 and s.md == 16.0
    assert s.lg == 24.0 and s.xl == 32.0 and s.xxl == 48.0
    # Zero is allowed; negative is not.
    SpacingScale(xs=0.0)
    with pytest.raises(ValueError, match=">= 0"):
        SpacingScale(xs=-1.0)


# 2. RadiusScale — defaults + rejects negatives
def test_radius_scale_defaults_and_validation():
    r = RadiusScale()
    assert r.sm == 4.0 and r.md == 8.0 and r.lg == 12.0
    assert r.xl == 16.0 and r.pill == 999.0
    with pytest.raises(ValueError, match=">= 0"):
        RadiusScale(pill=-1.0)


# 3. TransitionScale — defaults + rejects zero / negative
def test_transition_scale_defaults_and_rejects_zero():
    t = TransitionScale()
    assert t.fast == 0.15 and t.normal == 0.25 and t.slow == 0.5
    with pytest.raises(ValueError, match="> 0"):
        TransitionScale(fast=0.0)
    with pytest.raises(ValueError, match="> 0"):
        TransitionScale(normal=-0.1)


# 4. ZIndexScale — defaults + rejects non-monotonic tiers
def test_zindex_scale_defaults_and_monotonic():
    z = ZIndexScale()
    assert z.base == 1 and z.dropdown == 100
    assert z.modal == 1000 and z.toast == 2000
    with pytest.raises(ValueError, match="monotonic"):
        ZIndexScale(base=1, dropdown=2000, modal=1000, toast=2000)


# 5. Gradient.sample at t=0 returns start
def test_gradient_sample_t0_returns_start():
    start = Color(10, 20, 30, 1.0)
    end = Color(200, 210, 220, 0.5)
    g = Gradient(start=start, end=end, angle_deg=90.0)
    out = g.sample(0.0)
    assert (out.r, out.g, out.b) == (10, 20, 30)
    assert abs(out.a - 1.0) < 1e-9


# 6. Gradient.sample at t=1 returns end
def test_gradient_sample_t1_returns_end():
    start = Color(10, 20, 30, 1.0)
    end = Color(200, 210, 220, 0.5)
    g = Gradient(start=start, end=end, angle_deg=135.0)
    out = g.sample(1.0)
    assert (out.r, out.g, out.b) == (200, 210, 220)
    assert abs(out.a - 0.5) < 1e-9


# 7. Gradient.sample at t=0.5 interpolates linearly in RGB
def test_gradient_sample_t05_linear_midpoint():
    start = Color(0, 100, 200, 0.0)
    end = Color(100, 200, 0, 1.0)
    g = Gradient(start=start, end=end)
    out = g.sample(0.5)
    assert out.r == 50
    assert out.g == 150
    assert out.b == 100
    assert abs(out.a - 0.5) < 1e-9


# 8. Gradient validation rejects bad endpoints + out-of-range t
def test_gradient_validation():
    c = Color(0, 0, 0, 1.0)
    with pytest.raises(TypeError, match="start must be a Color"):
        Gradient(start=(0, 0, 0, 1.0), end=c)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="end must be a Color"):
        Gradient(start=c, end=(0, 0, 0, 1.0))  # type: ignore[arg-type]
    g = Gradient(start=c, end=Color(255, 255, 255, 1.0))
    with pytest.raises(ValueError, match=r"in \[0, 1\]"):
        g.sample(1.5)


# 9. SemanticTokens construction + attribute access
def test_semantic_tokens_construction_and_access():
    tokens = _make_semantic()
    assert tokens.primary.r == 120 and tokens.primary.g == 80
    assert tokens.glass_blur_px == 10.0
    assert isinstance(tokens.primary_gradient, Gradient)
    assert tokens.success.g == 200
    assert tokens.error.r == 220


# 10. SemanticTokens — rejects non-Color members + bad blur value
def test_semantic_tokens_validation():
    primary = Color(120, 80, 200, 1.0)
    lighter = Color(160, 130, 220, 1.0)
    base_kwargs = dict(
        primary=primary,
        primary_gradient=Gradient(start=primary, end=lighter),
        secondary=Color(0, 0, 0, 1.0),
        accent=Color(0, 0, 0, 1.0),
        background=Color(0, 0, 0, 1.0),
        surface=Color(0, 0, 0, 1.0),
        surface_hover=Color(0, 0, 0, 1.0),
        border=Color(0, 0, 0, 1.0),
        text_primary=Color(0, 0, 0, 1.0),
        text_secondary=Color(0, 0, 0, 1.0),
        text_disabled=Color(0, 0, 0, 1.0),
        success=Color(0, 0, 0, 1.0),
        warning=Color(0, 0, 0, 1.0),
        error=Color(0, 0, 0, 1.0),
        info=Color(0, 0, 0, 1.0),
        focus_ring=Color(0, 0, 0, 1.0),
        glass_bg=Color(0, 0, 0, 1.0),
        glass_blur_px=8.0,
    )
    # Happy path constructs cleanly.
    SemanticTokens(**base_kwargs)
    # Replace a Color field with a tuple → TypeError.
    bad = dict(base_kwargs)
    bad["accent"] = (255, 0, 0, 1.0)
    with pytest.raises(TypeError, match="accent must be a Color"):
        SemanticTokens(**bad)
    # Negative blur → ValueError.
    bad2 = dict(base_kwargs)
    bad2["glass_blur_px"] = -1.0
    with pytest.raises(ValueError, match=">= 0"):
        SemanticTokens(**bad2)


# 11. SemanticTokens — to_dict / from_dict round-trip
def test_semantic_tokens_dict_roundtrip():
    tokens = _make_semantic()
    data = tokens.to_dict()
    rebuilt = SemanticTokens.from_dict(data)
    assert rebuilt.primary.r == tokens.primary.r
    assert rebuilt.glass_blur_px == tokens.glass_blur_px
    assert rebuilt.primary_gradient.angle_deg == tokens.primary_gradient.angle_deg
    assert rebuilt.primary_gradient.start.r == tokens.primary_gradient.start.r
    assert rebuilt.primary_gradient.end.b == tokens.primary_gradient.end.b


# 12. ThemeSpec — full round-trip with semantic + scales
def test_themespec_full_roundtrip_with_semantic_and_scales():
    spec = ThemeSpec(
        name="full",
        semantic=_make_semantic(),
        palette={"primary": Color(120, 80, 200, 1.0)},
        spacing=SpacingScale(xs=2.0, sm=6.0, md=12.0, lg=20.0, xl=28.0, xxl=40.0),
        radius=RadiusScale(sm=2.0, md=6.0, lg=10.0, xl=14.0, pill=512.0),
        transitions=TransitionScale(fast=0.1, normal=0.2, slow=0.4),
        z_index=ZIndexScale(base=1, dropdown=50, modal=500, toast=5000),
    )
    data = spec.to_dict()
    rebuilt = ThemeSpec.from_dict(data)
    assert rebuilt.name == "full"
    assert rebuilt.spacing.md == 12.0
    assert rebuilt.radius.pill == 512.0
    assert rebuilt.transitions.slow == 0.4
    assert rebuilt.z_index.toast == 5000
    assert rebuilt.semantic.primary.r == 120
    # Backwards compat: palette dict access still works.
    assert rebuilt.palette["primary"].r == 120


# 13. ThemeSpec — YAML round-trip carries semantic + scales
def test_themespec_yaml_roundtrip_with_semantic_and_scales():
    pytest.importorskip("yaml")
    spec = ThemeSpec(
        name="yaml-full",
        semantic=_make_semantic(),
        spacing=SpacingScale(md=14.0),
        radius=RadiusScale(lg=11.0),
        transitions=TransitionScale(fast=0.12),
        z_index=ZIndexScale(toast=3000),
    )
    text = spec.to_yaml()
    rebuilt = ThemeSpec.from_yaml(text)
    assert rebuilt.spacing.md == 14.0
    assert rebuilt.radius.lg == 11.0
    assert rebuilt.transitions.fast == 0.12
    assert rebuilt.z_index.toast == 3000
    assert rebuilt.semantic.warning.r == 240


# 14. ThemeSpec — missing semantic raises a clear required-field error
def test_themespec_missing_semantic_raises():
    with pytest.raises(TypeError, match="semantic"):
        ThemeSpec(name="no-semantic")  # type: ignore[call-arg]


# 15. Backwards compat — palette["primary"] still works after extension
def test_themespec_palette_backwards_compat():
    spec = ThemeSpec(
        name="bc",
        semantic=_make_semantic(),
        palette={"primary": Color(11, 22, 33, 0.5)},
    )
    # Old contract: theme.palette["primary"] returns a Color.
    assert isinstance(spec.palette["primary"], Color)
    assert spec.palette["primary"].r == 11
    assert spec.palette["primary"].a == 0.5


# 16. ThemeSpec — rejects wrong type for spacing / transitions
def test_themespec_rejects_wrong_scale_types():
    with pytest.raises(TypeError, match="spacing must be a SpacingScale"):
        ThemeSpec(
            name="bad-scale",
            semantic=_make_semantic(),
            spacing={"xs": 4},  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError, match="transitions must be a TransitionScale"):
        ThemeSpec(
            name="bad-transitions",
            semantic=_make_semantic(),
            transitions=0.25,  # type: ignore[arg-type]
        )
