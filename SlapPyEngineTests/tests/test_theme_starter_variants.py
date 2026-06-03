"""Tests for the three starter :class:`ThemeSpec` variants.

Covers ``teengirl_notebook``, ``cozy_diary``, ``bullet_journal``: the
first concrete diary-family themes built on the theme primitive
infrastructure. Verifies palette / font / nine-slice / icon / shader /
metadata wiring, the bulk register helper, YAML round-trip, and that
swapping the active theme actually changes ``get_active_theme().name``.

GPU-free — every assertion runs on ``numpy`` arrays + pure-Python data.
"""
from __future__ import annotations

import pytest

try:
    from slappyengine.ui.theme import (
        Color,
        Font,
        NineSlice,
        ShaderEffect,
        ThemeSpec,
        SVGIcon,
        apply_theme,
        get_active_theme,
        list_registered_themes,
        register_theme,
    )
    from slappyengine.ui.theme import _reset_registry_for_tests
    from slappyengine.ui.theme.svg_icon import clear_cache as clear_svg_cache
    from slappyengine.ui.theme.themes import (
        BULLET_JOURNAL,
        COZY_DIARY,
        TEENGIRL_NOTEBOOK,
        register_starter_themes,
    )
except Exception as e:  # pragma: no cover - skip if subpackage missing
    pytest.skip(
        f"slappyengine.ui.theme.themes not importable: {e}",
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


ALL_STARTERS = (TEENGIRL_NOTEBOOK, COZY_DIARY, BULLET_JOURNAL)
EXPECTED_NAMES = {"teengirl_notebook", "cozy_diary", "bullet_journal"}


# ===========================================================================
# 1. Each constant is a valid ThemeSpec
# ===========================================================================


@pytest.mark.parametrize("theme", ALL_STARTERS)
def test_starter_is_themespec_instance(theme):
    assert isinstance(theme, ThemeSpec), (
        f"expected ThemeSpec, got {type(theme).__name__}"
    )


@pytest.mark.parametrize("theme", ALL_STARTERS)
def test_starter_name_is_nonempty_string(theme):
    assert isinstance(theme.name, str)
    assert theme.name.strip(), "theme name must be non-empty"


def test_starter_names_unique_and_expected():
    names = {t.name for t in ALL_STARTERS}
    assert names == EXPECTED_NAMES


# ===========================================================================
# 2. Palette names from the design doc are present
# ===========================================================================


def test_teengirl_palette_named_entries_present():
    p = TEENGIRL_NOTEBOOK.palette
    # Per docs/theme_teengirl_notebook_2026_06_03.md §1.1.
    for required in ("cream", "lilac", "bubblegum_pink",
                     "highlighter_yellow", "mint", "ink_navy"):
        assert required in p, f"missing palette entry {required!r}"
    # Spot-check the hex matches the design doc (cream #FBF7EC).
    assert p["cream"].r == 0xFB
    assert p["cream"].g == 0xF7
    assert p["cream"].b == 0xEC
    # bubblegum pink #FF6FB5.
    assert (p["bubblegum_pink"].r, p["bubblegum_pink"].g,
            p["bubblegum_pink"].b) == (0xFF, 0x6F, 0xB5)


def test_cozy_diary_palette_named_entries_present():
    p = COZY_DIARY.palette
    for required in ("dusty_rose", "caramel", "sage", "cream", "ink"):
        assert required in p, f"missing palette entry {required!r}"
    # dusty rose #D8A2A8.
    assert (p["dusty_rose"].r, p["dusty_rose"].g,
            p["dusty_rose"].b) == (0xD8, 0xA2, 0xA8)


def test_bullet_journal_palette_named_entries_present():
    p = BULLET_JOURNAL.palette
    for required in ("white", "soft_black", "pastel_pink",
                     "pastel_mint", "pastel_lavender", "pastel_butter"):
        assert required in p, f"missing palette entry {required!r}"
    assert (p["white"].r, p["white"].g, p["white"].b) == (255, 255, 255)
    assert (p["soft_black"].r, p["soft_black"].g,
            p["soft_black"].b) == (0x2A, 0x2A, 0x2A)


@pytest.mark.parametrize("theme", ALL_STARTERS)
def test_palette_entries_are_colors(theme):
    assert theme.palette, f"{theme.name}: palette must be non-empty"
    for k, v in theme.palette.items():
        assert isinstance(v, Color), (
            f"{theme.name}: palette[{k!r}] should be Color, "
            f"got {type(v).__name__}"
        )


# ===========================================================================
# 3. Semantic tokens populated
# ===========================================================================

REQUIRED_SEMANTIC_TOKENS = (
    "surface", "on_surface", "primary", "secondary",
)


@pytest.mark.parametrize("theme", ALL_STARTERS)
def test_semantic_tokens_present(theme):
    for tok in REQUIRED_SEMANTIC_TOKENS:
        assert tok in theme.palette, (
            f"{theme.name}: missing semantic token {tok!r}"
        )
        assert isinstance(theme.palette[tok], Color)


# ===========================================================================
# 4. Fonts wired per design
# ===========================================================================


def test_teengirl_fonts_are_caveat_quicksand_firacode():
    f = TEENGIRL_NOTEBOOK.fonts
    assert f["header"].family == "Caveat"
    assert f["body"].family == "Quicksand"
    assert f["mono"].family == "Fira Code"


def test_cozy_diary_fonts_lean_handwritten():
    f = COZY_DIARY.fonts
    # Per design doc: Patrick Hand header for the journal feel.
    assert f["header"].family == "Patrick Hand"
    assert f["body"].family == "Quicksand"


def test_bullet_journal_fonts_no_script():
    f = BULLET_JOURNAL.fonts
    # Quicksand throughout (per doc §3.4 / sprint brief).
    assert f["header"].family == "Quicksand"
    assert f["body"].family == "Quicksand"
    # And the mono pick.
    assert f["mono"].family in ("Cascadia Code", "Cascadia Mono")


@pytest.mark.parametrize("theme", ALL_STARTERS)
def test_fonts_are_font_instances(theme):
    for k, v in theme.fonts.items():
        assert isinstance(v, Font), f"{theme.name}: fonts[{k!r}] not a Font"
        assert v.size > 0


# ===========================================================================
# 5. Background shader is the expected type
# ===========================================================================


def test_teengirl_background_is_ruled_paper():
    bg = TEENGIRL_NOTEBOOK.background_shader
    assert isinstance(bg, ShaderEffect)
    assert bg.name == "ruled_paper"
    assert "line_color" in bg.params
    assert "margin_color" in bg.params


def test_cozy_diary_background_is_parchment_via_ruled_paper():
    bg = COZY_DIARY.background_shader
    assert isinstance(bg, ShaderEffect)
    # Renders as a parametrised ruled-paper.
    assert bg.name == "ruled_paper"


def test_bullet_journal_background_is_dot_grid():
    bg = BULLET_JOURNAL.background_shader
    assert isinstance(bg, ShaderEffect)
    assert bg.name == "dot_grid"
    assert bg.params.get("spacing") == 8


# ===========================================================================
# 6. Nine-slice + icons populated
# ===========================================================================


@pytest.mark.parametrize("theme", ALL_STARTERS)
def test_nine_slices_populated(theme):
    assert theme.nine_slices, f"{theme.name}: nine_slices empty"
    for k, v in theme.nine_slices.items():
        assert isinstance(v, NineSlice), (
            f"{theme.name}: nine_slices[{k!r}] not a NineSlice"
        )


@pytest.mark.parametrize("theme", ALL_STARTERS)
def test_icons_populated_with_inline_svg(theme):
    assert theme.icons, f"{theme.name}: icons empty"
    assert len(theme.icons) >= 3, (
        f"{theme.name}: should ship ≥ 3 starter icons"
    )
    for k, v in theme.icons.items():
        assert isinstance(v, SVGIcon)
        # Sprint constraint: each inline SVG ≤ 500 bytes.
        assert len(v.svg_xml.encode("utf-8")) <= 500, (
            f"{theme.name}: icon {k!r} SVG exceeds 500 bytes"
        )


def test_teengirl_starter_icons_present():
    for name in ("heart", "star", "sparkle"):
        assert name in TEENGIRL_NOTEBOOK.icons, (
            f"teengirl_notebook should ship {name!r} icon"
        )


# ===========================================================================
# 7. Creature roster metadata
# ===========================================================================


def test_teengirl_creature_roster_metadata():
    md = TEENGIRL_NOTEBOOK.metadata
    roster = md.get("creature_roster", "")
    parts = [p.strip() for p in roster.split(",") if p.strip()]
    assert parts == ["fox_01", "butterfly_01"]


def test_cozy_diary_creature_roster_metadata():
    parts = [p.strip() for p in COZY_DIARY.metadata.get(
        "creature_roster", "").split(",") if p.strip()]
    assert parts == ["red_panda_01", "fox_01", "leaf_01"]


def test_bullet_journal_creature_roster_metadata():
    parts = [p.strip() for p in BULLET_JOURNAL.metadata.get(
        "creature_roster", "").split(",") if p.strip()]
    assert parts == ["hedgehog_01", "porcupine_01"]


# ===========================================================================
# 8. register_starter_themes registers all three
# ===========================================================================


def test_register_starter_themes_registers_all_three():
    names = register_starter_themes()
    assert set(names) == EXPECTED_NAMES
    assert set(list_registered_themes()) >= EXPECTED_NAMES


def test_register_starter_themes_idempotent():
    register_starter_themes()
    # Second call must not raise — re-registration is allowed.
    names = register_starter_themes()
    assert set(names) == EXPECTED_NAMES


# ===========================================================================
# 9. YAML round-trip each theme
# ===========================================================================


@pytest.mark.parametrize("theme", ALL_STARTERS)
def test_yaml_roundtrip_each_theme(theme):
    yaml_text = theme.to_yaml()
    assert isinstance(yaml_text, str)
    assert theme.name in yaml_text
    restored = ThemeSpec.from_yaml(yaml_text)
    assert isinstance(restored, ThemeSpec)
    assert restored.name == theme.name
    # Palette names survive.
    assert set(restored.palette) == set(theme.palette)
    # Shader name survives.
    if theme.background_shader is not None:
        assert restored.background_shader is not None
        assert restored.background_shader.name == theme.background_shader.name


# ===========================================================================
# 10. Switching active theme actually changes get_active_theme().name
# ===========================================================================


def test_apply_theme_changes_active_name():
    register_starter_themes()
    apply_theme("teengirl_notebook")
    assert get_active_theme().name == "teengirl_notebook"
    apply_theme("cozy_diary")
    assert get_active_theme().name == "cozy_diary"
    apply_theme("bullet_journal")
    assert get_active_theme().name == "bullet_journal"


def test_apply_unknown_theme_raises():
    register_starter_themes()
    with pytest.raises(LookupError):
        apply_theme("not_a_real_theme")
