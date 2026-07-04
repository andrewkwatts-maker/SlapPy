"""Tests for :class:`NotebookThemingEditor`.

Coverage:

* Panel constructs + exposes expected dropdown option sources.
* Dropdowns are populated from the real U1/U3/U4/T2 registries (with
  fallbacks when a registry is not installed).
* Preview methods mutate the active selection and populate the
  ``preview_cache``.
* :meth:`apply_color` clamps + rebinds palette entries on the active
  :class:`ThemeSpec`.
* Persistence hooks: :meth:`save_as_new` / :meth:`reset_to_default` /
  :meth:`export_yaml` / :meth:`import_yaml` behave with and without a
  :class:`UserThemeStore`-like handle.
* Theme switch updates the panel palette.
* Panel builds under a stub DPG and marks itself ``built``.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

try:
    from slappyengine.ui.editor.notebook_theming_editor import (
        NotebookThemingEditor,
        PALETTE_ROLES,
        STYLE_KEYS,
        _fallback_yaml_dump,
        _fallback_yaml_load,
    )
    from slappyengine.ui.editor.panel_decor import DividerStyle
    from slappyengine.ui.theme import (
        Color,
        Font,
        Gradient,
        SemanticTokens,
        ThemeSpec,
        _reset_registry_for_tests,
        apply_theme,
        register_theme,
    )
    from slappyengine.ui.theme.washi_tape.library import list_tapes
except Exception as exc:  # pragma: no cover - skip when deps missing
    pytest.skip(
        f"notebook_theming_editor dependencies unavailable: {exc}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


def _make_themespec(
    name: str,
    *,
    primary_rgba: tuple[int, int, int, int] = (255, 111, 181, 255),
    accent_rgba: tuple[int, int, int, int] = (255, 224, 102, 220),
    ink_rgba: tuple[int, int, int, int] = (31, 47, 102, 255),
    background_rgba: tuple[int, int, int, int] = (251, 247, 236, 255),
) -> ThemeSpec:
    """Construct a minimal :class:`ThemeSpec` for a test theme."""
    def _c(rgba: tuple[int, int, int, int]) -> Color:
        return Color(rgba[0], rgba[1], rgba[2], rgba[3] / 255)

    primary = _c(primary_rgba)
    accent = _c(accent_rgba)
    ink = _c(ink_rgba)
    background = _c(background_rgba)
    return ThemeSpec(
        name=name,
        semantic=SemanticTokens(
            primary=primary,
            primary_gradient=Gradient(start=primary, end=ink, angle_deg=135.0),
            secondary=primary,
            accent=accent,
            background=background,
            surface=background,
            surface_hover=Color(231, 221, 241, 1.0),
            border=Color(184, 176, 160, 1.0),
            text_primary=ink,
            text_secondary=Color(59, 59, 69, 1.0),
            text_disabled=Color(177, 172, 184, 1.0),
            success=Color(91, 193, 138, 1.0),
            warning=Color(242, 187, 85, 1.0),
            error=Color(232, 90, 108, 1.0),
            info=Color(127, 200, 232, 1.0),
            focus_ring=primary,
            glass_bg=background,
            glass_blur_px=12.0,
        ),
        palette={},
        fonts={"body": Font(family="Quicksand", size=14, weight="500")},
        metadata={"creature_roster": "fox_01,butterfly_01"},
    )


@pytest.fixture(autouse=True)
def _isolated_theme_registry():
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


@pytest.fixture
def two_themes():
    a = _make_themespec("theme_a", primary_rgba=(255, 111, 181, 255))
    b = _make_themespec("theme_b", primary_rgba=(0xB0, 0x7A, 0x5C, 255),
                        ink_rgba=(46, 41, 38, 255))
    register_theme(a)
    register_theme(b)
    apply_theme("theme_a")
    return a, b


@pytest.fixture
def stub_dpg(monkeypatch):
    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class _NoOp:
        def __getattr__(self, name):
            return lambda *a, **kw: None

        def does_item_exist(self, *a, **kw):
            return False

        def child_window(self, *a, **kw):
            return _Ctx()

        def group(self, *a, **kw):
            return _Ctx()

    stub = _NoOp()
    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = stub
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", stub)
    yield stub


class _FakeStore:
    """Minimal :class:`UserThemeStore` stand-in used by the persistence tests."""

    def __init__(self) -> None:
        self.saved: list[tuple[str, dict]] = []
        self.reverted: list[str] = []

    def save(self, name: str, payload: dict) -> Path:
        self.saved.append((name, payload))
        return Path.home() / ".slappyengine" / "themes" / f"{name}.theme.yaml"

    def save_as(self, name: str, payload: dict) -> Path:
        return self.save(name, payload)

    def revert_to_baked(self, name: str | None) -> None:
        self.reverted.append(name or "")


# ---------------------------------------------------------------------------
# 1. Construction
# ---------------------------------------------------------------------------


def test_panel_constructs_without_arguments():
    editor = NotebookThemingEditor()
    assert editor.TITLE == "Theming"
    assert editor.is_open is False
    assert isinstance(editor.panel_tag, str) and editor.panel_tag


def test_palette_roles_seeded_with_defaults():
    editor = NotebookThemingEditor()
    for role in PALETTE_ROLES:
        rgba = editor.palette[role]
        assert isinstance(rgba, tuple) and len(rgba) == 4
        for channel in rgba:
            assert 0 <= channel <= 255


def test_style_keys_present_in_selection():
    editor = NotebookThemingEditor()
    for key in STYLE_KEYS:
        assert key in editor.selection
        assert isinstance(editor.selection[key], str)
        assert editor.selection[key]


# ---------------------------------------------------------------------------
# 2. Dropdown option sourcing (U1/U3/U4/T2)
# ---------------------------------------------------------------------------


def test_washi_tape_options_populated_from_registry():
    editor = NotebookThemingEditor()
    assert set(list_tapes()).issubset(set(editor.washi_tape_options))


def test_divider_options_match_panel_decor_registry():
    editor = NotebookThemingEditor()
    expected = {m.value for m in DividerStyle}
    assert expected.issubset(set(editor.divider_options))


def test_page_lining_options_non_empty_list():
    editor = NotebookThemingEditor()
    opts = editor.page_lining_options
    assert isinstance(opts, list) and opts
    for entry in opts:
        assert isinstance(entry, str) and entry


def test_edge_stroke_options_non_empty_list():
    editor = NotebookThemingEditor()
    opts = editor.edge_stroke_options
    assert isinstance(opts, list) and opts


def test_creature_options_include_fox():
    editor = NotebookThemingEditor()
    assert "fox_01" in editor.creature_options


def test_theme_options_reflects_registry(two_themes):
    editor = NotebookThemingEditor()
    assert "theme_a" in editor.theme_options
    assert "theme_b" in editor.theme_options


# ---------------------------------------------------------------------------
# 3. Preview machinery
# ---------------------------------------------------------------------------


def test_preview_page_lining_updates_selection_and_cache():
    editor = NotebookThemingEditor()
    editor.preview_page_lining("dot_grid")
    assert editor.selection["page_lining"] == "dot_grid"
    assert "page_lining" in editor.preview_cache
    assert editor.preview_count >= 1


def test_preview_edge_stroke_updates_selection():
    editor = NotebookThemingEditor()
    editor.preview_edge_stroke("ballpoint_pen")
    assert editor.selection["edge_stroke"] == "ballpoint_pen"
    assert "edge_stroke" in editor.preview_cache


def test_preview_washi_tape_updates_selection():
    editor = NotebookThemingEditor()
    editor.preview_washi_tape("tape_gold_foil")
    assert editor.selection["washi_tape"] == "tape_gold_foil"


def test_preview_divider_updates_selection():
    editor = NotebookThemingEditor()
    editor.preview_divider("heart_chain")
    assert editor.selection["divider"] == "heart_chain"


def test_preview_returns_rgba_tile_when_numpy_available():
    np = pytest.importorskip("numpy")
    editor = NotebookThemingEditor()
    tile = editor.preview_page_lining("ruled_paper")
    assert isinstance(tile, np.ndarray)
    assert tile.shape == (
        NotebookThemingEditor.PREVIEW_HEIGHT,
        NotebookThemingEditor.PREVIEW_WIDTH,
        4,
    )
    assert tile.dtype == np.uint8


def test_preview_count_increments_on_repeated_calls():
    editor = NotebookThemingEditor()
    editor.preview_page_lining("dot_grid")
    editor.preview_edge_stroke("ballpoint_pen")
    editor.preview_washi_tape("tape_pink_solid")
    assert editor.preview_count >= 3


# ---------------------------------------------------------------------------
# 4. Palette mutation
# ---------------------------------------------------------------------------


def test_apply_color_mutates_active_palette(two_themes):
    editor = NotebookThemingEditor()
    editor.set_active_theme("theme_a")
    editor.apply_color("primary", (10, 20, 30, 255))
    assert editor.palette["primary"] == (10, 20, 30, 255)


def test_apply_color_clamps_out_of_range_channels():
    editor = NotebookThemingEditor()
    editor.apply_color("accent", (999, -50, 300, 512))
    r, g, b, a = editor.palette["accent"]
    assert (r, g, b, a) == (255, 0, 255, 255)


def test_apply_color_rejects_unknown_role():
    editor = NotebookThemingEditor()
    with pytest.raises(KeyError):
        editor.apply_color("mystery", (0, 0, 0, 255))


def test_apply_color_mutates_active_theme_semantic(two_themes):
    editor = NotebookThemingEditor()
    editor.set_active_theme("theme_a")
    editor.apply_color("primary", (12, 34, 56, 255))
    active = two_themes[0]
    assert (active.semantic.primary.r, active.semantic.primary.g,
            active.semantic.primary.b) == (12, 34, 56)


# ---------------------------------------------------------------------------
# 5. Theme switch propagation
# ---------------------------------------------------------------------------


def test_set_active_theme_updates_palette_snapshot(two_themes):
    editor = NotebookThemingEditor()
    editor.set_active_theme("theme_a")
    a_primary = editor.palette["primary"]
    editor.set_active_theme("theme_b")
    b_primary = editor.palette["primary"]
    assert a_primary != b_primary
    assert b_primary[:3] == (0xB0, 0x7A, 0x5C)


def test_set_active_theme_updates_active_name(two_themes):
    editor = NotebookThemingEditor()
    editor.set_active_theme("theme_b")
    assert editor.active_theme_name == "theme_b"


def test_set_active_theme_syncs_creature_roster(two_themes):
    editor = NotebookThemingEditor()
    editor.set_active_theme("theme_a")
    # theme_a metadata roster is "fox_01,butterfly_01" — both must be on,
    # every other creature must be off.
    assert editor.creatures_enabled.get("fox_01") is True
    assert editor.creatures_enabled.get("butterfly_01") is True
    others = [
        cid for cid, on in editor.creatures_enabled.items()
        if on and cid not in {"fox_01", "butterfly_01"}
    ]
    assert others == []


# ---------------------------------------------------------------------------
# 6. Creature roster
# ---------------------------------------------------------------------------


def test_toggle_creature_flips_state():
    editor = NotebookThemingEditor()
    assert editor.toggle_creature("fox_01") is True
    assert editor.toggle_creature("fox_01") is False


# ---------------------------------------------------------------------------
# 7. Persistence — save / reset
# ---------------------------------------------------------------------------


def test_save_as_new_writes_via_store(two_themes):
    store = _FakeStore()
    editor = NotebookThemingEditor(theme_store=store)
    editor.set_active_theme("theme_a")
    editor.apply_color("primary", (1, 2, 3, 255))
    editor.save_as_new("my_custom")
    # Any call — including the passive persistence path — records to
    # the store. We only require that the explicit save_as landed with
    # the requested name.
    assert any(entry[0] == "my_custom" for entry in store.saved)


def test_save_as_new_noop_without_store():
    editor = NotebookThemingEditor(theme_store=None)
    # No store — this must return ``None`` without raising.
    assert editor.save_as_new("anonymous") is None


def test_reset_to_default_delegates_to_store_revert(two_themes):
    store = _FakeStore()
    editor = NotebookThemingEditor(theme_store=store)
    editor.set_active_theme("theme_a")
    editor.reset_to_default()
    assert store.reverted == ["theme_a"]


# ---------------------------------------------------------------------------
# 8. Export / import
# ---------------------------------------------------------------------------


def test_export_yaml_writes_valid_yaml(tmp_path: Path, two_themes):
    editor = NotebookThemingEditor()
    editor.set_active_theme("theme_a")
    editor.apply_color("primary", (10, 20, 30, 255))
    target = tmp_path / "exported.theme.yaml"
    out = editor.export_yaml(target)
    assert out == target
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert "theme_a" in text
    assert "primary" in text
    # Round-trip through the fallback loader to sanity-check structure.
    parsed = _fallback_yaml_load(text)
    assert parsed.get("name") == "theme_a"


def test_import_yaml_loads_and_applies(tmp_path: Path, two_themes):
    editor = NotebookThemingEditor()
    editor.set_active_theme("theme_a")
    editor.apply_color("primary", (200, 100, 50, 255))
    target = tmp_path / "snapshot.theme.yaml"
    editor.export_yaml(target)

    fresh = NotebookThemingEditor()
    parsed = fresh.import_yaml(target)
    assert isinstance(parsed, dict)
    assert fresh.palette["primary"][:3] == (200, 100, 50)


def test_fallback_yaml_round_trip():
    payload = {
        "name": "custom",
        "selection": {"washi_tape": "tape_pink_solid"},
        "palette": {"primary": [10, 20, 30, 255]},
        "creatures": ["fox_01", "butterfly_01"],
    }
    text = _fallback_yaml_dump(payload)
    parsed = _fallback_yaml_load(text)
    assert parsed["name"] == "custom"
    assert parsed["palette"]["primary"] == [10, 20, 30, 255]


# ---------------------------------------------------------------------------
# 9. Build + lifecycle
# ---------------------------------------------------------------------------


def test_build_with_stub_dpg_marks_panel_built(stub_dpg):
    editor = NotebookThemingEditor()
    editor.build("theming_parent")
    assert editor.is_open is True
    # After build every style dimension has a preview tile cached.
    for key in STYLE_KEYS:
        assert key in editor.preview_cache


def test_build_headless_no_dpg_is_noop(monkeypatch):
    broken = types.ModuleType("dearpygui.dearpygui")
    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = broken
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", broken)
    editor = NotebookThemingEditor()
    editor.build("some_parent")
    assert editor.is_open is True
    # Still able to preview / apply colours from the headless path.
    editor.preview_page_lining("dot_grid")
    editor.apply_color("primary", (10, 20, 30, 255))


def test_close_toggles_flags():
    editor = NotebookThemingEditor()
    editor.open()
    assert editor.is_open is True
    editor.close()
    assert editor.is_open is False
