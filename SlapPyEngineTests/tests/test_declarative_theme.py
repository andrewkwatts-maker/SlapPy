"""Tests for the HTML5-like declarative theme parser.

Coverage:

* Minimal-theme parse.
* Named colours, hex 3/6/8, rgba().
* Nested sections (``frames.default`` → ``PanelFrameSet.default``).
* Shader specs → :class:`ShaderEffect`.
* Compound values (``padding: 10px 8px``, ``shadow: 4px rgba(...)``).
* Round-trip: ``parse → dump → parse → equal``.
* Malformed input raises :class:`DeclarativeThemeError` with line
  numbers.
* ``${...}`` interpolation via ``pharos_engine.math.evaluate``.
* Built-in themes export as declarative + re-parse identically.
* Registry integration: ``load_declarative`` registers a theme.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pharos_editor.ui.theme import (
    Color,
    DeclarativeTheme,
    DeclarativeThemeError,
    ShaderEffect,
    ThemeSpec,
    list_registered_themes,
    load_declarative,
)
from pharos_editor.ui.theme.themes import (
    BULLET_JOURNAL,
    COZY_DIARY,
    TEENGIRL_NOTEBOOK,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


MINIMAL = '''@theme "min" { palette { primary: #FF0000; } }'''


COZY_LIKE = '''
@theme "my_cozy_theme" {
    palette {
        primary: #FF6FB5;
        secondary: #E7DDF1;
        background: #FBF7EC;
        ink: #1F2F66;
    }
    fonts {
        header: "Caveat", 20;
        body: "Quicksand", 14;
        code: "Fira Code", 12;
    }
    frames.default {
        border-size: 2px;
        rounding: 12px;
        padding: 10px 8px;
        shadow: 4px 0px rgba(255, 111, 181, 0.3);
    }
    panels.sidebar {
        background: #FBF7EC;
        border: 1px solid #E7DDF1;
    }
    shader.background {
        kind: "ruled_paper";
        line-color: #A7E7C7;
    }
    creatures {
        fox_01, butterfly_01;
    }
}
'''


# ---------------------------------------------------------------------------
# Minimal-parse tests
# ---------------------------------------------------------------------------


def test_parse_minimal_theme() -> None:
    theme = DeclarativeTheme.parse(MINIMAL)
    assert isinstance(theme, ThemeSpec)
    assert theme.name == "min"
    assert theme.palette["primary"] == Color(r=255, g=0, b=0, a=1.0)


def test_parse_returns_themespec_with_semantic() -> None:
    theme = DeclarativeTheme.parse(MINIMAL)
    assert theme.semantic is not None
    assert theme.semantic.primary == Color(r=255, g=0, b=0, a=1.0)


# ---------------------------------------------------------------------------
# Colour parsing
# ---------------------------------------------------------------------------


def test_hex_3_digit_expands_to_6() -> None:
    src = '@theme "t" { palette { primary: #F0A; } }'
    color = DeclarativeTheme.parse(src).palette["primary"]
    assert color == Color(r=255, g=0, b=170, a=1.0)


def test_hex_6_digit() -> None:
    src = '@theme "t" { palette { primary: #A1B2C3; } }'
    color = DeclarativeTheme.parse(src).palette["primary"]
    assert color == Color(r=161, g=178, b=195, a=1.0)


def test_hex_8_digit_carries_alpha() -> None:
    src = '@theme "t" { palette { primary: #A1B2C380; } }'
    color = DeclarativeTheme.parse(src).palette["primary"]
    assert color.r == 161
    assert color.g == 178
    assert color.b == 195
    assert 0.4 < color.a < 0.6


def test_rgba_call() -> None:
    src = '@theme "t" { palette { primary: rgba(10, 20, 30, 0.5); } }'
    color = DeclarativeTheme.parse(src).palette["primary"]
    assert color == Color(r=10, g=20, b=30, a=0.5)


def test_named_color_resolves() -> None:
    src = '@theme "t" { palette { primary: bubblegum-pink; } }'
    color = DeclarativeTheme.parse(src).palette["primary"]
    assert color == Color(r=255, g=111, b=181, a=1.0)


def test_unknown_named_color_raises() -> None:
    src = '@theme "t" { palette { primary: not-a-real-color; } }'
    with pytest.raises(DeclarativeThemeError, match="unknown named colour"):
        DeclarativeTheme.parse(src)


# ---------------------------------------------------------------------------
# Nested sections + frames
# ---------------------------------------------------------------------------


def test_frames_default_maps_to_panel_frame_set_default() -> None:
    theme = DeclarativeTheme.parse(COZY_LIKE)
    assert theme.frames.default.border_size == pytest.approx(2.0)
    assert theme.frames.default.rounding == pytest.approx(12.0)


def test_padding_compound_two_values() -> None:
    theme = DeclarativeTheme.parse(COZY_LIKE)
    # Grammar: "padding: 10px 8px" — first is x, second is y.
    assert theme.frames.default.padding_x == 10
    assert theme.frames.default.padding_y == 8


def test_shadow_extracts_size_and_color() -> None:
    theme = DeclarativeTheme.parse(COZY_LIKE)
    fs = theme.frames.default
    assert fs.shadow_size == pytest.approx(4.0)
    assert fs.shadow_color is not None
    assert fs.shadow_color.r == 255
    assert fs.shadow_color.g == 111
    assert fs.shadow_color.b == 181


def test_frames_toolbar_subsection() -> None:
    src = '''
    @theme "t" {
        palette { primary: #FF0000; }
        frames.toolbar {
            border-size: 3px;
            rounding: 5px;
        }
    }
    '''
    theme = DeclarativeTheme.parse(src)
    assert theme.frames.toolbar is not None
    assert theme.frames.toolbar.border_size == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# Shader specs
# ---------------------------------------------------------------------------


def test_shader_background_creates_shader_effect() -> None:
    theme = DeclarativeTheme.parse(COZY_LIKE)
    assert isinstance(theme.background_shader, ShaderEffect)
    assert theme.background_shader.name == "ruled_paper"


def test_shader_params_carry_colours() -> None:
    theme = DeclarativeTheme.parse(COZY_LIKE)
    assert theme.background_shader is not None
    params = theme.background_shader.params
    assert "line_color" in params
    r, g, b, a = params["line_color"]
    assert (r, g, b) == (167, 231, 199)


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------


def test_fonts_family_and_size() -> None:
    theme = DeclarativeTheme.parse(COZY_LIKE)
    assert theme.fonts["header"].family == "Caveat"
    assert theme.fonts["header"].size == 20
    assert theme.fonts["body"].family == "Quicksand"
    assert theme.fonts["body"].size == 14


# ---------------------------------------------------------------------------
# Creatures / list-style sections
# ---------------------------------------------------------------------------


def test_creatures_populates_metadata() -> None:
    theme = DeclarativeTheme.parse(COZY_LIKE)
    roster = theme.metadata.get("creature_roster", "")
    assert "fox_01" in roster
    assert "butterfly_01" in roster


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_dump_produces_reparsable_string() -> None:
    theme = DeclarativeTheme.parse(COZY_LIKE)
    dumped = DeclarativeTheme.dump(theme)
    assert dumped.startswith('@theme "my_cozy_theme"')
    reparsed = DeclarativeTheme.parse(dumped)
    assert reparsed.name == theme.name


def test_round_trip_palette_preserved() -> None:
    theme = DeclarativeTheme.parse(COZY_LIKE)
    dumped = DeclarativeTheme.dump(theme)
    reparsed = DeclarativeTheme.parse(dumped)
    for key, color in theme.palette.items():
        assert reparsed.palette[key] == color


def test_round_trip_frames_preserved() -> None:
    theme = DeclarativeTheme.parse(COZY_LIKE)
    reparsed = DeclarativeTheme.parse(DeclarativeTheme.dump(theme))
    assert reparsed.frames.default.border_size == theme.frames.default.border_size
    assert reparsed.frames.default.padding_x == theme.frames.default.padding_x
    assert reparsed.frames.default.padding_y == theme.frames.default.padding_y


# ---------------------------------------------------------------------------
# Malformed input
# ---------------------------------------------------------------------------


def test_missing_at_theme_raises() -> None:
    with pytest.raises(DeclarativeThemeError, match="@theme"):
        DeclarativeTheme.parse('palette { primary: #FF0000; }')


def test_unterminated_string_raises_with_line() -> None:
    with pytest.raises(DeclarativeThemeError) as excinfo:
        DeclarativeTheme.parse('@theme "unterminated { }')
    assert "unterminated" in str(excinfo.value).lower()


def test_unterminated_interpolation_raises() -> None:
    with pytest.raises(DeclarativeThemeError, match="interpolation"):
        DeclarativeTheme.parse('@theme "t" { palette { primary: ${1+1; } }')


def test_missing_semi_raises_with_line() -> None:
    src = '@theme "t" {\n    palette {\n        primary: #FF0000\n    }\n}'
    with pytest.raises(DeclarativeThemeError) as excinfo:
        DeclarativeTheme.parse(src)
    # Line number must appear in the error message.
    assert "line" in str(excinfo.value).lower()


def test_unknown_directive_raises() -> None:
    with pytest.raises(DeclarativeThemeError, match="unknown directive"):
        DeclarativeTheme.parse('@bogus "t" { }')


def test_unexpected_character_raises() -> None:
    with pytest.raises(DeclarativeThemeError, match="unexpected character"):
        DeclarativeTheme.parse('@theme "t" { palette { primary: `nope`; } }')


# ---------------------------------------------------------------------------
# Python interpolation (${...})
# ---------------------------------------------------------------------------


def test_interpolation_evaluates_arithmetic() -> None:
    src = '''
    @theme "t" {
        palette {
            primary: rgba(${100 + 55}, ${10 * 2}, 50, ${1.0 / 2}); }
    }
    '''
    color = DeclarativeTheme.parse(src).palette["primary"]
    assert color.r == 155
    assert color.g == 20
    assert color.b == 50
    assert color.a == pytest.approx(0.5)


def test_interpolation_sandbox_blocks_import() -> None:
    src = '@theme "t" { palette { primary: rgba(${__import__("os")}, 0, 0, 1); } }'
    with pytest.raises(DeclarativeThemeError, match="interpolation"):
        DeclarativeTheme.parse(src)


def test_interpolation_quoted_hex_passes_through() -> None:
    src = '@theme "t" { palette { primary: ${"#AABBCC"}; } }'
    color = DeclarativeTheme.parse(src).palette["primary"]
    assert color == Color(r=170, g=187, b=204, a=1.0)


# ---------------------------------------------------------------------------
# Built-in theme export
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("theme_const", [
    COZY_DIARY, TEENGIRL_NOTEBOOK, BULLET_JOURNAL,
])
def test_builtin_theme_round_trips(theme_const: ThemeSpec) -> None:
    dumped = DeclarativeTheme.dump(theme_const)
    reparsed = DeclarativeTheme.parse(dumped)
    assert reparsed.name == theme_const.name
    for key, color in theme_const.palette.items():
        rp = reparsed.palette[key.replace("-", "_")]
        # Colours must survive verbatim (rounding to integer channels).
        assert rp.r == color.r
        assert rp.g == color.g
        assert rp.b == color.b


# ---------------------------------------------------------------------------
# Registry integration + parse_file
# ---------------------------------------------------------------------------


def test_parse_file_reads_theme_from_disk(tmp_path: Path) -> None:
    path = tmp_path / "sample.theme.css"
    path.write_text(MINIMAL, encoding="utf-8")
    theme = DeclarativeTheme.parse_file(path)
    assert theme.name == "min"


def test_load_declarative_registers_theme(tmp_path: Path) -> None:
    path = tmp_path / "custom.theme.css"
    path.write_text(
        '@theme "declarative_custom_theme" { palette { primary: #123456; } }',
        encoding="utf-8",
    )
    name = load_declarative(path)
    assert name == "declarative_custom_theme"
    assert name in list_registered_themes()


# ---------------------------------------------------------------------------
# Grammar edge cases
# ---------------------------------------------------------------------------


def test_comments_are_ignored() -> None:
    src = '''
    // top-level line comment
    @theme "commented" {
        /* block comment
           spanning lines */
        palette {
            // inline
            primary: #ABCDEF;
        }
    }
    '''
    theme = DeclarativeTheme.parse(src)
    assert theme.name == "commented"
    assert theme.palette["primary"].r == 0xAB


def test_multiple_creature_entries_accumulate() -> None:
    src = '''
    @theme "t" {
        palette { primary: #FF0000; }
        creatures { fox_01, bee_02; }
    }
    '''
    theme = DeclarativeTheme.parse(src)
    roster = theme.metadata["creature_roster"]
    assert "fox_01" in roster and "bee_02" in roster


def test_empty_palette_still_produces_theme() -> None:
    src = '@theme "empty_pal" { palette { } }'
    theme = DeclarativeTheme.parse(src)
    assert theme.name == "empty_pal"
    assert theme.palette == {}


def test_source_must_be_str() -> None:
    with pytest.raises(DeclarativeThemeError, match="must be a str"):
        DeclarativeTheme.parse(42)  # type: ignore[arg-type]


def test_dump_rejects_non_themespec() -> None:
    with pytest.raises(DeclarativeThemeError, match="ThemeSpec"):
        DeclarativeTheme.dump("not a theme")  # type: ignore[arg-type]
