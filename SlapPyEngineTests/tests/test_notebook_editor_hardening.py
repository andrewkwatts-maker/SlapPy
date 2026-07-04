"""Silent-acceptance hardening tests for notebook editor panels (W2 sprint).

Covers four panels:

* :class:`slappyengine.ui.editor.notebook_material_editor.NotebookMaterialEditor`
* :class:`slappyengine.ui.editor.notebook_theming_editor.NotebookThemingEditor`
* :class:`slappyengine.ui.editor.notebook_spawn_menu.NotebookSpawnMenu`
* :class:`slappyengine.ui.editor.notebook_diary_page.NotebookDiaryPage`

Silent-acceptance = a mutation method that returns a "success"-shaped
value (``None``, ``True``, etc.) without actually doing anything (e.g.
saving to a null path, applying an empty diff, updating a widget that
doesn't exist). Prior sprint runs found ~28 such bugs.

Each hardened method should:

1. Validate its inputs (raise ``ValueError`` / ``TypeError`` on garbage).
2. Log a warning when a target widget / dependency is missing.
3. Return a status (``bool`` / status object) the caller can check.

These tests exercise the invalid-input branch, the missing-widget
branch, and the happy path for every mutation method.
"""
from __future__ import annotations

import logging
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub — modules ``import dearpygui.dearpygui as dpg`` at call
# time, so a stubbed module has to survive the whole test.
# ---------------------------------------------------------------------------


class _StubCM:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StubDPG:
    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: set[str] = set()

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    def group(self, *a, **kw):
        self._track("group", a, kw)
        return _StubCM()

    def child_window(self, *a, **kw):
        self._track("child_window", a, kw)
        return _StubCM()

    def collapsing_header(self, *a, **kw):
        self._track("collapsing_header", a, kw)
        return _StubCM()

    def window(self, *a, **kw):
        self._track("window", a, kw)
        return _StubCM()

    def popup(self, *a, **kw):
        self._track("popup", a, kw)
        return _StubCM()

    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)

    def add_button(self, *a, **kw):
        self._track("add_button", a, kw)

    def add_checkbox(self, *a, **kw):
        self._track("add_checkbox", a, kw)

    def add_separator(self, *a, **kw):
        self._track("add_separator", a, kw)

    def add_input_text(self, *a, **kw):
        self._track("add_input_text", a, kw)

    def add_input_int(self, *a, **kw):
        self._track("add_input_int", a, kw)

    def add_input_float(self, *a, **kw):
        self._track("add_input_float", a, kw)

    def add_input_floatx(self, *a, **kw):
        self._track("add_input_floatx", a, kw)

    def add_color_edit(self, *a, **kw):
        self._track("add_color_edit", a, kw)

    def add_child_window(self, *a, **kw):
        self._track("add_child_window", a, kw)

    def add_combo(self, *a, **kw):
        self._track("add_combo", a, kw)

    def add_drawlist(self, *a, **kw):
        self._track("add_drawlist", a, kw)

    def add_draw_layer(self, *a, **kw):
        self._track("add_draw_layer", a, kw)

    def add_listbox(self, *a, **kw):
        self._track("add_listbox", a, kw)

    def add_slider_float(self, *a, **kw):
        self._track("add_slider_float", a, kw)

    def configure_item(self, *a, **kw):
        self._track("configure_item", a, kw)

    def delete_item(self, tag, *a, **kw):
        self._track("delete_item", (tag,), kw)
        if isinstance(tag, str):
            self.items.discard(tag)

    def does_item_exist(self, tag, *a, **kw):
        return tag in self.items

    def set_value(self, *a, **kw):
        self._track("set_value", a, kw)

    def get_item_children(self, *a, **kw):
        return []


@pytest.fixture
def stub_dpg(monkeypatch):
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    method_names = (
        "group", "child_window", "collapsing_header", "popup", "window",
        "add_text", "add_button", "add_checkbox", "add_separator",
        "add_input_text", "add_input_int", "add_input_float",
        "add_input_floatx", "add_color_edit", "add_child_window",
        "add_combo", "add_drawlist", "add_draw_layer", "add_listbox",
        "add_slider_float", "configure_item", "delete_item",
        "does_item_exist", "set_value", "get_item_children",
    )
    for name in method_names:
        setattr(mod, name, getattr(stub, name))

    def _fallback(name: str):
        def _noop(*a, **kw):
            stub.calls.setdefault(name, []).append((a, kw))
        return _noop
    mod.__getattr__ = _fallback

    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


@pytest.fixture(autouse=True)
def clear_notebook_theme():
    """Reset notebook widget theme listeners between tests."""
    try:
        from slappyengine.ui.widgets import notebook_theme
        from slappyengine.ui.widgets.notebook_theme import set_active_theme

        set_active_theme(None)
        notebook_theme._theme_listeners.clear()
        yield
        set_active_theme(None)
        notebook_theme._theme_listeners.clear()
    except Exception:
        yield


# ---------------------------------------------------------------------------
# Dataclass targets — passed to the material editor's set_target path.
# ---------------------------------------------------------------------------


@dataclass
class _StubSoftbodyMaterial:
    name: str = "rubber"
    render_color: tuple = (180, 40, 40)
    damage_color: tuple = (60, 20, 20)


@dataclass
class _StubFluidMaterial:
    name: str = "water"
    rest_density: float = 1000.0
    viscosity: float = 0.5
    surface_tension: float = 0.2
    render_color: tuple = (60, 140, 220)
    halo_color: tuple = (180, 220, 255)


# ---------------------------------------------------------------------------
# NotebookMaterialEditor hardening
# ---------------------------------------------------------------------------


class TestNotebookMaterialEditorHardening:
    def _make(self, target: Any = None):
        from slappyengine.ui.editor.notebook_material_editor import (
            NotebookMaterialEditor,
        )
        return NotebookMaterialEditor(target=target)

    def test_set_target_valid_returns_true(self):
        editor = self._make()
        assert editor.set_target(_StubSoftbodyMaterial()) is True

    def test_set_target_rejects_empty_kind_string(self):
        editor = self._make()
        with pytest.raises(ValueError):
            editor.set_target(_StubSoftbodyMaterial(), kind="")

    def test_set_target_rejects_unknown_kind(self):
        editor = self._make()
        with pytest.raises(ValueError):
            editor.set_target(_StubSoftbodyMaterial(), kind="not_a_kind")

    def test_set_target_rejects_non_string_kind(self):
        editor = self._make()
        with pytest.raises(TypeError):
            editor.set_target(_StubSoftbodyMaterial(), kind=123)

    def test_set_material_returns_true(self):
        editor = self._make()
        assert editor.set_material(_StubFluidMaterial()) is True

    def test_build_rejects_empty_string_parent_tag(self):
        editor = self._make()
        with pytest.raises(ValueError):
            editor.build("")

    def test_build_rejects_none_parent_tag(self):
        editor = self._make()
        with pytest.raises(TypeError):
            editor.build(None)  # type: ignore[arg-type]

    def test_build_returns_true_headless(self):
        editor = self._make()
        # No DPG installed — headless path — still marks built + returns True.
        assert editor.build("root_parent") is True
        assert editor._built is True

    def test_refresh_before_build_returns_false(self):
        editor = self._make()
        # Not built yet — refresh must not lie about doing work.
        assert editor.refresh() is False

    def test_on_theme_change_before_build_returns_false(self):
        editor = self._make()
        assert editor.on_theme_change() is False

    def test_validate_state_ok_by_default(self):
        editor = self._make()
        assert editor._validate_state() is True

    def test_validate_state_flags_bad_kind(self):
        editor = self._make()
        editor._kind = "bogus_kind"
        with pytest.raises(RuntimeError):
            editor._validate_state()


# ---------------------------------------------------------------------------
# NotebookThemingEditor hardening
# ---------------------------------------------------------------------------


class _StubStore:
    """Minimal user-store stub used to exercise happy paths."""

    def __init__(self) -> None:
        self.saved: list[tuple[str, dict]] = []
        self.reset_calls: list[str] = []

    def save(self, name: str, snapshot: dict) -> str:
        self.saved.append((name, snapshot))
        return f"/tmp/{name}.theme.yaml"

    def save_as(self, name: str, snapshot: dict) -> str:
        self.saved.append((name, snapshot))
        return f"/tmp/{name}.theme.yaml"

    def revert_to_baked(self, name: str) -> None:
        self.reset_calls.append(name)


class TestNotebookThemingEditorHardening:
    def _make(self, store: Any = None):
        from slappyengine.ui.editor.notebook_theming_editor import (
            NotebookThemingEditor,
        )
        return NotebookThemingEditor(theme_store=store)

    def test_set_active_theme_rejects_empty(self):
        editor = self._make()
        with pytest.raises(ValueError):
            editor.set_active_theme("")

    def test_set_active_theme_rejects_non_string(self):
        editor = self._make()
        with pytest.raises(TypeError):
            editor.set_active_theme(42)  # type: ignore[arg-type]

    def test_set_active_theme_returns_false_when_registry_missing(
        self, monkeypatch, caplog,
    ):
        # Force the soft-imported apply_theme to be None.
        editor = self._make()
        editor._apply_theme = None
        with caplog.at_level(logging.WARNING):
            result = editor.set_active_theme("some_theme")
        assert result is False
        assert editor.active_theme_name == "some_theme"
        assert any(
            "theme registry unavailable" in rec.message
            for rec in caplog.records
        )

    def test_save_as_new_missing_store_logs_and_returns_none(self, caplog):
        editor = self._make(store=None)
        with caplog.at_level(logging.WARNING):
            result = editor.save_as_new("mytheme")
        assert result is None
        assert any("user store missing" in rec.message for rec in caplog.records)

    def test_save_as_new_rejects_empty_name(self):
        editor = self._make()
        with pytest.raises(ValueError):
            editor.save_as_new("")

    def test_save_as_new_happy_path_returns_path(self):
        store = _StubStore()
        editor = self._make(store=store)
        result = editor.save_as_new("mytheme")
        assert result is not None
        assert store.saved and store.saved[-1][0] == "mytheme"

    def test_reset_to_default_missing_store_returns_false(self, caplog):
        editor = self._make(store=None)
        with caplog.at_level(logging.WARNING):
            assert editor.reset_to_default() is False
        assert any("user store missing" in rec.message for rec in caplog.records)

    def test_reset_to_default_no_active_theme_returns_false(self, caplog):
        editor = self._make(store=_StubStore())
        editor._active_theme_name = None
        with caplog.at_level(logging.WARNING):
            assert editor.reset_to_default() is False
        assert any("no active theme" in rec.message for rec in caplog.records)

    def test_reset_to_default_happy_path(self):
        store = _StubStore()
        editor = self._make(store=store)
        editor._active_theme_name = "custom"
        assert editor.reset_to_default() is True
        assert store.reset_calls == ["custom"]

    def test_on_theme_selected_rejects_non_string(self, caplog):
        editor = self._make()
        with caplog.at_level(logging.WARNING):
            result = editor._on_theme_selected(None, 42, None)
        assert result is False
        assert any(
            "ignored non-string app_data" in rec.message
            for rec in caplog.records
        )

    def test_style_callback_rejects_non_string(self, caplog):
        editor = self._make()
        cb = editor._make_style_callback("page_lining")
        with caplog.at_level(logging.WARNING):
            result = cb(None, 42, None)
        assert result is False
        assert any(
            "ignored non-string app_data" in rec.message
            for rec in caplog.records
        )

    def test_palette_callback_rejects_bad_rgba(self, caplog):
        editor = self._make()
        cb = editor._make_palette_callback("primary")
        with caplog.at_level(logging.WARNING):
            result = cb(None, "not-a-list", None)
        assert result is False
        assert any(
            "ignored non-numeric" in rec.message for rec in caplog.records
        )

    def test_validate_state_ok_by_default(self):
        editor = self._make()
        assert editor._validate_state() is True

    def test_validate_state_flags_missing_role(self):
        editor = self._make()
        editor._palette.pop("primary")
        with pytest.raises(RuntimeError):
            editor._validate_state()

    def test_apply_color_still_raises_for_unknown_role(self):
        editor = self._make()
        with pytest.raises(KeyError):
            editor.apply_color("not_a_role", (10, 20, 30, 255))


# ---------------------------------------------------------------------------
# NotebookSpawnMenu hardening
# ---------------------------------------------------------------------------


class TestNotebookSpawnMenuHardening:
    def _make(self, on_spawn=None):
        from slappyengine.ui.editor.notebook_spawn_menu import (
            NotebookSpawnMenu,
        )
        return NotebookSpawnMenu(
            on_spawn=on_spawn if on_spawn is not None else (lambda *_: None),
        )

    def test_record_recent_unknown_id_logs_and_returns_false(self, caplog):
        menu = self._make()
        with caplog.at_level(logging.WARNING):
            result = menu.record_recent("not_a_card")
        assert result is False
        assert any(
            "unknown card_id" in rec.message for rec in caplog.records
        )

    def test_record_recent_valid_id_returns_true(self):
        menu = self._make()
        assert menu.record_recent("rope") is True
        assert menu.get_recent_ids() == ["rope"]

    def test_record_recent_rejects_empty(self):
        menu = self._make()
        with pytest.raises(ValueError):
            menu.record_recent("")

    def test_set_hover_unknown_id_clears_and_warns(self, caplog):
        menu = self._make()
        with caplog.at_level(logging.WARNING):
            result = menu.set_hover("not_a_card")
        assert result is False
        assert menu.hovered_card is None
        assert any(
            "unknown card_id" in rec.message for rec in caplog.records
        )

    def test_set_hover_valid_returns_true(self):
        menu = self._make()
        assert menu.set_hover("rope") is True
        assert menu.hovered_card == "rope"

    def test_set_hover_none_returns_false(self):
        menu = self._make()
        assert menu.set_hover(None) is False

    def test_set_hover_rejects_empty_string(self):
        menu = self._make()
        with pytest.raises(TypeError):
            menu.set_hover("")

    def test_submit_modal_without_open_modal_logs_and_returns_false(
        self, caplog,
    ):
        menu = self._make()
        with caplog.at_level(logging.WARNING):
            result = menu.submit_modal()
        assert result is False
        assert any(
            "no modal is open" in rec.message for rec in caplog.records
        )

    def test_cancel_modal_without_open_modal_returns_false(self):
        menu = self._make()
        assert menu.cancel_modal() is False

    def test_set_project_root_none_returns_false(self):
        menu = self._make()
        assert menu.set_project_root(None) is False

    def test_set_project_root_valid_returns_true(self, tmp_path):
        menu = self._make()
        assert menu.set_project_root(tmp_path) is True

    def test_set_project_root_rejects_bad_type(self):
        menu = self._make()
        with pytest.raises(TypeError):
            menu.set_project_root(1234)  # type: ignore[arg-type]

    def test_set_project_root_rejects_empty_string(self):
        menu = self._make()
        with pytest.raises(ValueError):
            menu.set_project_root("")

    def test_build_rejects_empty_parent_tag(self):
        menu = self._make()
        with pytest.raises(ValueError):
            menu.build("")

    def test_build_rejects_none_parent_tag(self):
        menu = self._make()
        with pytest.raises(TypeError):
            menu.build(None)  # type: ignore[arg-type]

    def test_build_returns_true_headless(self):
        menu = self._make()
        assert menu.build("root_parent") is True

    def test_save_recents_no_project_root_returns_false(self):
        menu = self._make()
        # Ensure project root is unset.
        menu._project_root = None
        assert menu.save_recents() is False

    def test_save_recents_happy_path(self, tmp_path):
        menu = self._make()
        menu.set_project_root(tmp_path)
        menu.record_recent("rope")
        # record_recent already saves; re-invoke explicitly for coverage.
        assert menu.save_recents() is True
        assert (tmp_path / menu.RECENT_YAML_RELPATH).exists()

    def test_validate_state_ok_by_default(self):
        menu = self._make()
        assert menu._validate_state() is True

    def test_validate_state_flags_alien_recent(self):
        menu = self._make()
        menu._recent_ids = ["not_a_card"]
        with pytest.raises(RuntimeError):
            menu._validate_state()


# ---------------------------------------------------------------------------
# NotebookDiaryPage hardening
# ---------------------------------------------------------------------------


class TestNotebookDiaryPageHardening:
    def _make(self):
        from slappyengine.ui.editor.notebook_diary_page import (
            NotebookDiaryPage,
        )
        return NotebookDiaryPage()

    def test_set_source_rejects_non_string(self):
        page = self._make()
        with pytest.raises(TypeError):
            page.set_source(1234)  # type: ignore[arg-type]

    def test_set_source_returns_true(self):
        page = self._make()
        assert page.set_source("print('hi')") is True

    def test_set_mode_rejects_bad_value(self):
        page = self._make()
        with pytest.raises(ValueError):
            page.set_mode("invalid_mode")

    def test_set_mode_rejects_non_string(self):
        page = self._make()
        with pytest.raises(TypeError):
            page.set_mode(3.14)  # type: ignore[arg-type]

    def test_set_mode_idempotent_returns_false(self):
        page = self._make()
        # Default mode is "python"; toggling to same value must not lie.
        assert page.set_mode("python") is False

    def test_set_mode_toggle_returns_true(self):
        page = self._make()
        assert page.set_mode("nodes") is True

    def test_open_diary_rejects_bad_type(self):
        page = self._make()
        with pytest.raises(TypeError):
            page.open_diary(1234)  # type: ignore[arg-type]

    def test_open_diary_rejects_empty_string(self):
        page = self._make()
        with pytest.raises(ValueError):
            page.open_diary("")

    def test_open_diary_returns_true(self, tmp_path):
        page = self._make()
        p = tmp_path / "test.diary.py"
        assert page.open_diary(p) is True

    def test_save_without_active_path_logs_and_returns_false(self, caplog):
        page = self._make()
        with caplog.at_level(logging.WARNING):
            result = page.save()
        assert result is False
        assert any(
            "no active diary bound" in rec.message for rec in caplog.records
        )

    def test_save_happy_path_returns_true(self, tmp_path):
        page = self._make()
        p = tmp_path / "diary.diary.py"
        page.open_diary(p)
        page.set_source("# script\n")
        assert page.save() is True
        assert p.exists()

    def test_run_script_studio_missing_returns_false(self, monkeypatch, caplog):
        page = self._make()
        # Force _try_import_studio to return None.
        import slappyengine.ui.editor.notebook_diary_page as mod

        monkeypatch.setattr(mod, "_try_import_studio", lambda: None)
        with caplog.at_level(logging.WARNING):
            result = page.run_script()
        assert result is False

    def test_stop_script_when_nothing_running_returns_false(self):
        page = self._make()
        # Nothing running yet.
        assert page.stop_script() is False

    def test_build_rejects_empty_parent_tag(self):
        page = self._make()
        with pytest.raises(ValueError):
            page.build("")

    def test_build_rejects_none_parent_tag(self):
        page = self._make()
        with pytest.raises(TypeError):
            page.build(None)  # type: ignore[arg-type]

    def test_build_returns_true_headless(self):
        page = self._make()
        assert page.build("some_parent") is True

    def test_refresh_theme_returns_bool(self):
        page = self._make()
        result = page.refresh_theme()
        assert isinstance(result, bool)

    def test_validate_state_ok_by_default(self):
        page = self._make()
        assert page._validate_state() is True

    def test_validate_state_flags_bad_mode(self):
        page = self._make()
        page._mode = "not_a_mode"
        with pytest.raises(RuntimeError):
            page._validate_state()
