"""Tests for the three v0.4 Phase C extended :class:`ThemeSpec` variants.

Covers ``scrapbook_summer``, ``cottagecore_garden``, ``kawaii_planner``:
the second batch of diary-family themes built on the theme primitive
infrastructure. Verifies palette / font / nine-slice / icon / shader /
metadata wiring, the bulk register helper, YAML round-trip, the
expected default creature roster, and the 500-byte SVG sprint cap.

GPU-free — every assertion runs on numpy arrays + pure-Python data.
"""
from __future__ import annotations

import pytest

try:
    from pharos_engine.ui.theme import (
        Color,
        Font,
        NineSlice,
        ShaderEffect,
        ThemeSpec,
        SVGIcon,
        apply_theme,
        get_active_theme,
        list_registered_themes,
    )
    from pharos_engine.ui.theme import _reset_registry_for_tests
    from pharos_engine.ui.theme.svg_icon import clear_cache as clear_svg_cache
    from pharos_engine.ui.theme.themes import (
        COTTAGECORE_GARDEN,
        KAWAII_PLANNER,
        SCRAPBOOK_SUMMER,
        register_all_themes,
        register_starter_themes,
    )
except Exception as e:  # pragma: no cover - skip if subpackage missing
    pytest.skip(
        f"pharos_engine.ui.theme.themes extended variants not importable: {e}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_registry():
    _reset_registry_for_tests()
    clear_svg_cache()
    yield
    _reset_registry_for_tests()
    clear_svg_cache()


EXTENDED_THEMES = (SCRAPBOOK_SUMMER, COTTAGECORE_GARDEN, KAWAII_PLANNER)
EXTENDED_NAMES = {"scrapbook_summer", "cottagecore_garden", "kawaii_planner"}
EXPECTED_BG_SHADER = {
    "scrapbook_summer": "watercolor_wash",
    "cottagecore_garden": "parchment",
    "kawaii_planner": "dot_grid",
}
EXPECTED_ROSTER = {
    "scrapbook_summer": ["golden_01", "butterfly_01", "bee_01"],
    "cottagecore_garden": ["rabbit_01", "deer_01", "mushroom_01",
                           "flower_01"],
    "kawaii_planner": ["cat_01", "panda_01", "porcupine_01"],
}
EXPECTED_PALETTE_KEYS = {
    "scrapbook_summer": {"sky_blue", "sunshine_yellow", "watermelon_pink",
                         "grass_green", "paper_white", "ink_charcoal"},
    "cottagecore_garden": {"mossy_green", "cream", "lavender", "peach",
                           "sage", "ink_sepia"},
    "kawaii_planner": {"pastel_pink", "mint", "lavender", "butter_yellow",
                       "neon_rose", "ink_warm_grey"},
}


# ===========================================================================
# 1. Each constant is a valid ThemeSpec
# ===========================================================================


@pytest.mark.parametrize("theme", EXTENDED_THEMES)
def test_extended_is_themespec_instance(theme):
    assert isinstance(theme, ThemeSpec), (
        f"expected ThemeSpec, got {type(theme).__name__}"
    )


@pytest.mark.parametrize("theme", EXTENDED_THEMES)
def test_extended_name_is_nonempty_string(theme):
    assert isinstance(theme.name, str)
    assert theme.name.strip(), "theme name must be non-empty"


def test_extended_names_unique_and_expected():
    names = {t.name for t in EXTENDED_THEMES}
    assert names == EXTENDED_NAMES


# ===========================================================================
# 2. Palette named entries present + colour types
# ===========================================================================


@pytest.mark.parametrize("theme", EXTENDED_THEMES)
def test_palette_named_entries_present(theme):
    p = theme.palette
    for required in EXPECTED_PALETTE_KEYS[theme.name]:
        assert required in p, (
            f"{theme.name}: missing palette entry {required!r}"
        )


def test_scrapbook_summer_palette_hex_matches():
    p = SCRAPBOOK_SUMMER.palette
    assert (p["sky_blue"].r, p["sky_blue"].g, p["sky_blue"].b) == (
        0x87, 0xCE, 0xEB
    )
    assert (p["sunshine_yellow"].r, p["sunshine_yellow"].g,
            p["sunshine_yellow"].b) == (0xFF, 0xD9, 0x3D)
    assert (p["watermelon_pink"].r, p["watermelon_pink"].g,
            p["watermelon_pink"].b) == (0xFF, 0x6B, 0x9D)


def test_cottagecore_garden_palette_hex_matches():
    p = COTTAGECORE_GARDEN.palette
    assert (p["mossy_green"].r, p["mossy_green"].g,
            p["mossy_green"].b) == (0x8D, 0xA7, 0x7C)
    assert (p["lavender"].r, p["lavender"].g,
            p["lavender"].b) == (0xB8, 0xA8, 0xD5)
    assert (p["peach"].r, p["peach"].g, p["peach"].b) == (0xFF, 0xB0, 0x7A)


def test_kawaii_planner_palette_hex_matches():
    p = KAWAII_PLANNER.palette
    assert (p["pastel_pink"].r, p["pastel_pink"].g,
            p["pastel_pink"].b) == (0xFF, 0xC0, 0xCB)
    assert (p["mint"].r, p["mint"].g, p["mint"].b) == (0xA8, 0xE6, 0xCF)
    assert (p["neon_rose"].r, p["neon_rose"].g,
            p["neon_rose"].b) == (0xFF, 0x80, 0xAB)


@pytest.mark.parametrize("theme", EXTENDED_THEMES)
def test_palette_entries_are_colors(theme):
    assert theme.palette, f"{theme.name}: palette must be non-empty"
    for k, v in theme.palette.items():
        assert isinstance(v, Color), (
            f"{theme.name}: palette[{k!r}] should be Color, "
            f"got {type(v).__name__}"
        )


# ===========================================================================
# 3. SemanticTokens block populated
# ===========================================================================

REQUIRED_SEMANTIC_PALETTE_TOKENS = (
    "surface", "on_surface", "primary", "secondary", "accent",
)


@pytest.mark.parametrize("theme", EXTENDED_THEMES)
def test_semantic_palette_aliases_present(theme):
    for tok in REQUIRED_SEMANTIC_PALETTE_TOKENS:
        assert tok in theme.palette, (
            f"{theme.name}: missing semantic palette alias {tok!r}"
        )
        assert isinstance(theme.palette[tok], Color)


@pytest.mark.parametrize("theme", EXTENDED_THEMES)
def test_semantic_tokens_block_populated(theme):
    s = theme.semantic
    # Every field must be a non-None Color (Gradient for primary_gradient).
    for name in ("primary", "secondary", "accent", "background", "surface",
                 "surface_hover", "border", "text_primary", "text_secondary",
                 "text_disabled", "success", "warning", "error", "info",
                 "focus_ring", "glass_bg"):
        c = getattr(s, name)
        assert isinstance(c, Color), (
            f"{theme.name}: semantic.{name} is {type(c).__name__}, "
            "expected Color"
        )
    assert s.glass_blur_px > 0.0
    assert s.primary_gradient is not None


# ===========================================================================
# 4. Fonts wired per design
# ===========================================================================


def test_scrapbook_summer_fonts():
    f = SCRAPBOOK_SUMMER.fonts
    assert f["header"].family == "Caveat"
    assert f["body"].family == "Quicksand"
    assert f["mono"].family == "Fira Code"


def test_cottagecore_garden_fonts():
    f = COTTAGECORE_GARDEN.fonts
    # Patrick Hand is the "looser script" header pick per the brief.
    assert f["header"].family == "Patrick Hand"
    assert f["body"].family == "Quicksand"


def test_kawaii_planner_fonts():
    f = KAWAII_PLANNER.fonts
    assert f["header"].family == "Caveat"
    # Comfortaa is the rounded body pick per the brief.
    assert f["body"].family == "Comfortaa"
    assert f["mono"].family == "Fira Code"


@pytest.mark.parametrize("theme", EXTENDED_THEMES)
def test_fonts_are_font_instances(theme):
    for k, v in theme.fonts.items():
        assert isinstance(v, Font), f"{theme.name}: fonts[{k!r}] not a Font"
        assert v.size > 0


# ===========================================================================
# 5. Background shader is the expected type
# ===========================================================================


@pytest.mark.parametrize("theme", EXTENDED_THEMES)
def test_background_shader_is_expected_type(theme):
    bg = theme.background_shader
    assert isinstance(bg, ShaderEffect), (
        f"{theme.name}: background_shader missing / wrong type"
    )
    assert bg.name == EXPECTED_BG_SHADER[theme.name], (
        f"{theme.name}: expected {EXPECTED_BG_SHADER[theme.name]!r}, "
        f"got {bg.name!r}"
    )


def test_scrapbook_summer_shader_carries_palette():
    bg = SCRAPBOOK_SUMMER.background_shader
    palette = bg.params.get("color_palette")
    assert isinstance(palette, list) and len(palette) >= 2
    # Sky blue + sunshine yellow wash colours per brief.
    assert (135, 206, 235, 255) in palette
    assert (255, 217, 61, 255) in palette
    assert bg.params.get("opacity") == 0.3


def test_kawaii_planner_shader_dot_spacing_16():
    bg = KAWAII_PLANNER.background_shader
    assert bg.params.get("spacing") == 16
    assert "confetti" in bg.params  # noise_glitter confetti overlay decl.


def test_cottagecore_garden_shader_parchment_base():
    bg = COTTAGECORE_GARDEN.background_shader
    base = bg.params.get("base_color")
    # Cream / fresh-linen base — #F5EDDD.
    assert base == (245, 237, 221, 255)


# ===========================================================================
# 6. Nine-slice + icons populated; SVGs ≤ 500 bytes
# ===========================================================================


@pytest.mark.parametrize("theme", EXTENDED_THEMES)
def test_nine_slices_populated(theme):
    assert theme.nine_slices, f"{theme.name}: nine_slices empty"
    for k, v in theme.nine_slices.items():
        assert isinstance(v, NineSlice), (
            f"{theme.name}: nine_slices[{k!r}] not a NineSlice"
        )


@pytest.mark.parametrize("theme", EXTENDED_THEMES)
def test_icons_populated_with_inline_svg(theme):
    assert theme.icons, f"{theme.name}: icons empty"
    assert len(theme.icons) >= 3, (
        f"{theme.name}: should ship ≥ 3 starter icons"
    )
    for k, v in theme.icons.items():
        assert isinstance(v, SVGIcon)
        # Sprint constraint: each inline SVG ≤ 500 bytes.
        assert len(v.svg_xml.encode("utf-8")) <= 500, (
            f"{theme.name}: icon {k!r} SVG exceeds 500 bytes "
            f"({len(v.svg_xml.encode('utf-8'))} bytes)"
        )


def test_scrapbook_summer_sticker_icons_present():
    for name in ("sun", "watermelon", "beach_ball"):
        assert name in SCRAPBOOK_SUMMER.icons, (
            f"scrapbook_summer should ship {name!r} sticker icon"
        )


def test_cottagecore_garden_sticker_icons_present():
    for name in ("daisy", "sprig", "embroidery_hoop"):
        assert name in COTTAGECORE_GARDEN.icons, (
            f"cottagecore_garden should ship {name!r} sticker icon"
        )


def test_kawaii_planner_sticker_icons_present():
    for name in ("rainbow_bow", "kawaii_face", "star_burst"):
        assert name in KAWAII_PLANNER.icons, (
            f"kawaii_planner should ship {name!r} sticker icon"
        )


# ===========================================================================
# 7. Creature roster metadata matches the sprint brief
# ===========================================================================


@pytest.mark.parametrize("theme", EXTENDED_THEMES)
def test_creature_roster_metadata(theme):
    md = theme.metadata
    roster = md.get("creature_roster", "")
    parts = [p.strip() for p in roster.split(",") if p.strip()]
    assert parts == EXPECTED_ROSTER[theme.name], (
        f"{theme.name}: roster mismatch — got {parts}, "
        f"expected {EXPECTED_ROSTER[theme.name]}"
    )


# ===========================================================================
# 8. Bulk register helper registers all six themes
# ===========================================================================


def test_register_all_themes_includes_extended_variants():
    names = register_all_themes()
    assert set(names) >= EXTENDED_NAMES
    assert set(list_registered_themes()) >= EXTENDED_NAMES


def test_register_starter_themes_now_includes_extended_variants():
    # The legacy starter helper now delegates to register_all_themes
    # so callers automatically pick up the v0.4 Phase C additions.
    names = register_starter_themes()
    assert set(names) >= EXTENDED_NAMES


def test_register_all_themes_idempotent():
    register_all_themes()
    names = register_all_themes()
    assert set(names) >= EXTENDED_NAMES


# ===========================================================================
# 9. YAML round-trip each theme
# ===========================================================================


@pytest.mark.parametrize("theme", EXTENDED_THEMES)
def test_yaml_roundtrip_each_extended_theme(theme):
    yaml_text = theme.to_yaml()
    assert isinstance(yaml_text, str)
    assert theme.name in yaml_text
    restored = ThemeSpec.from_yaml(yaml_text)
    assert isinstance(restored, ThemeSpec)
    assert restored.name == theme.name
    # Palette names survive the round-trip.
    assert set(restored.palette) == set(theme.palette)
    # Shader name survives.
    if theme.background_shader is not None:
        assert restored.background_shader is not None
        assert restored.background_shader.name == theme.background_shader.name


# ===========================================================================
# 10. Switching active theme actually changes get_active_theme().name
# ===========================================================================


def test_apply_extended_themes_changes_active_name():
    register_all_themes()
    apply_theme("scrapbook_summer")
    assert get_active_theme().name == "scrapbook_summer"
    apply_theme("cottagecore_garden")
    assert get_active_theme().name == "cottagecore_garden"
    apply_theme("kawaii_planner")
    assert get_active_theme().name == "kawaii_planner"


# ===========================================================================
# 11. Metadata declares the diary family
# ===========================================================================


@pytest.mark.parametrize("theme", EXTENDED_THEMES)
def test_metadata_declares_family(theme):
    assert theme.metadata.get("family") == "diary"
    assert theme.metadata.get("variant") == "light"
    # Each theme must point back to the design doc.
    assert "theme_diary_family" in theme.metadata.get("source_doc", "")
