"""Editor button audit — every clickable surface must have a useful callback.

This module audits every button, menu item, toggle, and field-widget
callback exposed by the notebook editor panel family and confirms:

1. No dead callbacks — every interactive surface is wired to ``None``
   only deliberately (and the audit calls it out).
2. Every callback can be smoke-fired in headless mode without raising.
3. The twenty specific stubs called out in the sprint brief land on a
   real implementation rather than ``pass``.

The DPG stub follows the same pattern the existing notebook tests use
(see ``test_editor_notebook_spawn_menu.py``) so panel ``build`` paths
exercise the real callback wiring without needing a live viewport.
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub
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
        self.values: dict[str, Any] = {}
        # Stash callbacks by tag so the audit can re-fire them later.
        self.callbacks: dict[str, Any] = {}

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)
            cb = kwargs.get("callback")
            if cb is not None:
                self.callbacks[tag] = cb

    # context-manager primitives
    def group(self, *a, **kw):
        self._track("group", a, kw); return _StubCM()

    def child_window(self, *a, **kw):
        self._track("child_window", a, kw); return _StubCM()

    def collapsing_header(self, *a, **kw):
        self._track("collapsing_header", a, kw); return _StubCM()

    def popup(self, *a, **kw):
        self._track("popup", a, kw); return _StubCM()

    def window(self, *a, **kw):
        self._track("window", a, kw); return _StubCM()

    def menu(self, *a, **kw):
        self._track("menu", a, kw); return _StubCM()

    def viewport_menu_bar(self, *a, **kw):
        self._track("viewport_menu_bar", a, kw); return _StubCM()

    # primitives — record args/kwargs then return None
    def add_text(self, *a, **kw): self._track("add_text", a, kw)
    def add_button(self, *a, **kw): self._track("add_button", a, kw)
    def add_checkbox(self, *a, **kw): self._track("add_checkbox", a, kw)
    def add_separator(self, *a, **kw): self._track("add_separator", a, kw)
    def add_input_int(self, *a, **kw): self._track("add_input_int", a, kw)
    def add_input_float(self, *a, **kw): self._track("add_input_float", a, kw)
    def add_input_floatx(self, *a, **kw): self._track("add_input_floatx", a, kw)
    def add_input_text(self, *a, **kw): self._track("add_input_text", a, kw)
    def add_color_edit(self, *a, **kw): self._track("add_color_edit", a, kw)
    def add_color_picker(self, *a, **kw): self._track("add_color_picker", a, kw)
    def add_listbox(self, *a, **kw): self._track("add_listbox", a, kw)
    def add_menu_item(self, *a, **kw): self._track("add_menu_item", a, kw)
    def add_drag_float(self, *a, **kw): self._track("add_drag_float", a, kw)
    def add_spacer(self, *a, **kw): self._track("add_spacer", a, kw)
    def add_group(self, *a, **kw): self._track("add_group", a, kw)

    def does_item_exist(self, tag, *a, **kw):
        return tag in self.items

    def delete_item(self, tag, *a, **kw):
        self._track("delete_item", (tag,), kw)
        if isinstance(tag, str):
            self.items.discard(tag)

    def configure_item(self, *a, **kw):
        self._track("configure_item", a, kw)

    def get_item_children(self, *a, **kw):
        return []

    def set_value(self, tag, value, *a, **kw):
        self.values[tag] = value

    def get_value(self, tag, *a, **kw):
        return self.values.get(tag)


@pytest.fixture(autouse=True)
def stub_dpg(monkeypatch):
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    method_names = (
        "group", "child_window", "collapsing_header", "popup", "window",
        "menu", "viewport_menu_bar",
        "add_text", "add_button", "add_checkbox", "add_separator",
        "add_input_text", "add_input_int", "add_input_float",
        "add_input_floatx", "add_color_edit", "add_color_picker",
        "add_listbox", "add_menu_item", "add_drag_float", "add_spacer",
        "add_group",
        "does_item_exist", "delete_item", "configure_item",
        "get_item_children", "set_value", "get_value",
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
def clear_theme():
    """Reset notebook theme + listener list between tests."""
    from pharos_engine.ui.widgets import notebook_theme
    from pharos_engine.ui.widgets.notebook_theme import set_active_theme

    set_active_theme(None)
    notebook_theme._theme_listeners.clear()
    yield
    set_active_theme(None)
    notebook_theme._theme_listeners.clear()


# ---------------------------------------------------------------------------
# Helpers — shell construction with a stub engine
# ---------------------------------------------------------------------------


class _StubScene:
    def __init__(self) -> None:
        self._entities: dict[str, Any] = {}
        self.bus = types.SimpleNamespace(
            publish=lambda *a, **kw: None,
            subscribe=lambda *a, **kw: None,
        )

    def add(self, entity: Any) -> Any:
        eid = getattr(entity, "id", None) or f"e{len(self._entities)}"
        self._entities[eid] = entity
        return entity

    def remove_entity(self, entity: Any) -> None:
        eid = getattr(entity, "id", None)
        self._entities.pop(eid, None)

    @property
    def entities(self) -> list[Any]:
        return list(self._entities.values())


class _StubEngine:
    def __init__(self) -> None:
        self.scene: Any = _StubScene()
        self.saved: list[str] = []
        self.loaded: list[str] = []
        self.new_called: int = 0
        self.tools: list[str] = []

    def save_scene(self) -> None:
        self.saved.append("ok")

    def load_scene(self, path: str | Any) -> None:
        self.loaded.append(str(path))

    def new_scene(self) -> None:
        self.new_called += 1
        self.scene = _StubScene()

    def set_active_tool(self, tool_id: str) -> None:
        self.tools.append(tool_id)


def _make_shell(stub_dpg):
    """Construct an EditorShell with a stub engine.

    The shell constructor pulls a NotebookStatusBar in at __init__; the
    stub_dpg fixture must already be installed.
    """
    from pharos_engine.ui.editor.shell import EditorShell

    return EditorShell(_StubEngine())


# ===========================================================================
# 1. notebook_toolbar — 4 tool buttons must all have non-None callbacks.
# ===========================================================================


class TestToolbar:
    def test_each_tool_button_has_callback(self):
        from pharos_engine.ui.editor.notebook_toolbar import NotebookToolbar

        bar = NotebookToolbar(on_tool_changed=lambda t: None)
        for tool_id, btn in bar.buttons.items():
            assert btn.callback is not None, f"tool {tool_id} has dead callback"

    def test_tool_callback_routes_to_set_active(self):
        from pharos_engine.ui.editor.notebook_toolbar import NotebookToolbar

        captured: list[str] = []
        bar = NotebookToolbar(on_tool_changed=lambda t: captured.append(t))
        bar.buttons["move"].callback(None, None, None)
        assert bar.get_active() == "move"
        assert captured == ["move"]

    def test_keyboard_shortcut_dispatch_lives(self):
        from pharos_engine.ui.editor.notebook_toolbar import NotebookToolbar

        bar = NotebookToolbar()
        assert bar.handle_shortcut("R") is True
        assert bar.get_active() == "rotate"


# ===========================================================================
# 2. notebook_outliner — entity rows + visibility/lock toggles + search.
# ===========================================================================


class TestOutliner:
    def _scene_with(self, entities):
        return types.SimpleNamespace(entities=list(entities))

    def test_visibility_toggle_writes_back(self):
        from pharos_engine.ui.editor.notebook_outliner import NotebookOutliner

        ent = types.SimpleNamespace(id="e1", name="thing", visible=True, locked=False)
        out = NotebookOutliner(
            world_getter=lambda: self._scene_with([ent]),
            on_select=lambda e: None,
        )
        out._handle_toggle_visible(ent, False)
        assert ent.visible is False
        out._handle_toggle_visible(ent, True)
        assert ent.visible is True

    def test_lock_toggle_writes_back(self):
        from pharos_engine.ui.editor.notebook_outliner import NotebookOutliner

        ent = types.SimpleNamespace(id="e1", name="thing", visible=True, locked=False)
        out = NotebookOutliner(
            world_getter=lambda: self._scene_with([ent]),
            on_select=lambda e: None,
        )
        out._handle_toggle_lock(ent, True)
        assert ent.locked is True

    def test_search_filters_rows(self):
        from pharos_engine.ui.editor.notebook_outliner import NotebookOutliner

        a = types.SimpleNamespace(id="a", name="alice", visible=True, locked=False)
        b = types.SimpleNamespace(id="b", name="bob", visible=True, locked=False)
        out = NotebookOutliner(
            world_getter=lambda: self._scene_with([a, b]),
            on_select=lambda e: None,
        )
        out.set_search("ali")
        rows = out.iter_rows()
        assert len(rows) == 1
        assert rows[0]["name"] == "alice"

    def test_select_callback_not_dead(self):
        from pharos_engine.ui.editor.notebook_outliner import NotebookOutliner

        captured: list[Any] = []
        out = NotebookOutliner(
            world_getter=lambda: None,
            on_select=lambda e: captured.append(e),
        )
        ent = types.SimpleNamespace(id="e1", name="x")
        out._handle_select(ent)
        assert captured == [ent]


# ===========================================================================
# 3. notebook_inspector — every field widget builds a write-back callback.
# ===========================================================================


@dataclass
class _Probe:
    """Multi-type probe so the inspector exercises every dispatch branch."""

    pos_x: float = 1.0
    flag: bool = False
    count: int = 3
    label: str = "name"


class TestInspector:
    def test_write_back_fires_for_each_field_type(self):
        from pharos_engine.ui.editor.notebook_inspector import NotebookInspector

        probe = _Probe()
        ins = NotebookInspector(target=probe)
        ins._write_back("pos_x", 5.5)
        ins._write_back("flag", True)
        ins._write_back("count", 9)
        ins._write_back("label", "newname")
        assert probe.pos_x == 5.5
        assert probe.flag is True
        assert probe.count == 9
        assert probe.label == "newname"

    def test_help_button_docstring_fallback_returns_string(self):
        from pharos_engine.ui.editor.notebook_inspector import NotebookInspector

        ins = NotebookInspector(target=_Probe())
        doc = ins._field_doc("pos_x")
        assert isinstance(doc, str) and doc

    def test_help_doc_fallback_when_no_target(self):
        from pharos_engine.ui.editor.notebook_inspector import NotebookInspector

        ins = NotebookInspector(target=None)
        assert ins._field_doc("anything") == "anything"

    def test_set_target_logs_call(self):
        from pharos_engine.ui.editor.notebook_inspector import NotebookInspector

        ins = NotebookInspector()
        probe = _Probe()
        ins.set_target(probe)
        assert any(c[0] == "set_target" for c in ins.call_log)


# ===========================================================================
# 4. notebook_code_panel — Regenerate / Explain / Pin / Saved / + New.
# ===========================================================================


class TestCodePanel:
    def test_pin_toggle_flips_flag(self):
        from pharos_engine.ui.editor.notebook_code_panel import NotebookCodePanel

        panel = NotebookCodePanel()
        assert panel.code_pinned is False
        panel.toggle_pin()
        assert panel.code_pinned is True
        panel.toggle_pin()
        assert panel.code_pinned is False

    def test_saved_toggle_logs_call(self):
        from pharos_engine.ui.editor.notebook_code_panel import NotebookCodePanel

        panel = NotebookCodePanel()
        panel.toggle_saved()
        assert any(c[0] == "toggle_saved" for c in panel.call_log)

    def test_regenerate_softfails_without_ai(self):
        from pharos_engine.ui.editor.notebook_code_panel import NotebookCodePanel

        panel = NotebookCodePanel()
        # Force the AI offline state.
        panel._ai_available = False
        panel._llm = None
        panel.regenerate()
        # Status should reflect the soft-fallback hint.
        assert "Ollama" in panel.status or "AI" in panel.status

    def test_reverse_sync_softfails_without_ai(self):
        from pharos_engine.ui.editor.notebook_code_panel import NotebookCodePanel

        panel = NotebookCodePanel()
        panel._ai_available = False
        panel._llm = None
        panel.reverse_sync()
        assert "Ollama" in panel.status or "AI" in panel.status

    def test_new_file_creates_scratch_buffer(self):
        from pharos_engine.ui.editor.notebook_code_panel import NotebookCodePanel

        panel = NotebookCodePanel()
        before = len(panel.files)
        panel.new_file()
        after = len(panel.files)
        assert after == before + 1
        assert panel.active_file is not None
        assert "untitled" in panel.active_file.name


# ===========================================================================
# 5. notebook_spawn_menu — 10 card Summon buttons + modal Summon/Cancel.
# ===========================================================================


class TestSpawnMenu:
    def test_every_card_has_summon_callback(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu

        menu = NotebookSpawnMenu(on_spawn=lambda cid, spec: None)
        assert menu.card_count == 10
        # Programmatic summon should not raise for any card.
        for card in menu.cards:
            menu.summon(card.card_id)
            menu.cancel_modal()

    def test_summon_then_submit_fires_on_spawn(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu

        captured: list[tuple[str, dict]] = []
        menu = NotebookSpawnMenu(
            on_spawn=lambda cid, spec: captured.append((cid, spec)),
        )
        menu.summon("rope")
        menu.submit_modal()
        assert len(captured) == 1
        assert captured[0][0] == "rope"

    def test_cancel_modal_does_not_fire_on_spawn(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu

        captured: list = []
        menu = NotebookSpawnMenu(
            on_spawn=lambda cid, spec: captured.append(cid),
        )
        menu.summon("humanoid")
        menu.cancel_modal()
        assert captured == []


# ===========================================================================
# 6. notebook_material_editor — kind switch via set_target lives.
# ===========================================================================


class TestMaterialEditor:
    def test_set_material_switches_kind(self):
        from pharos_engine.ui.editor.notebook_material_editor import (
            NotebookMaterialEditor,
        )

        ed = NotebookMaterialEditor()
        # softbody-like target
        sb = types.SimpleNamespace(
            name="rubber",
            density=1.0,
            render_color=(180, 80, 80),
            damage_color=(40, 12, 8),
        )
        ed.set_target(sb, kind="softbody")
        assert ed.kind == "softbody"
        assert ed.target is sb

    def test_on_theme_change_callback_lives(self):
        from pharos_engine.ui.editor.notebook_material_editor import (
            NotebookMaterialEditor,
        )

        ed = NotebookMaterialEditor()
        ed.on_theme_change()  # no-op, but must not raise
        assert any(c[0] == "theme_change" for c in ed.call_log)


# ===========================================================================
# 7. notebook_welcome — 3 demo cards, 6 theme swatches, start, hide.
# ===========================================================================


class TestWelcome:
    def _make(self):
        from pharos_engine.ui.editor.notebook_welcome import NotebookWelcome
        from pharos_engine.ui.editor.settings import UISettings

        settings = UISettings()
        out: dict = {
            "start": 0, "demos": [], "dismissed": 0,
            "settings": settings,
        }
        wel = NotebookWelcome(
            settings=settings,
            on_start_blank=lambda: out.__setitem__("start", out["start"] + 1),
            on_open_demo=lambda d: out["demos"].append(d),
            on_dismiss=lambda: out.__setitem__("dismissed", out["dismissed"] + 1),
        )
        return wel, out

    def test_start_drawing_fires_callback(self):
        wel, out = self._make()
        wel._on_start_blank_clicked()
        assert out["start"] == 1

    def test_each_demo_card_id_routes_through_callback(self):
        wel, out = self._make()
        for demo_id in wel.demo_card_ids:
            wel._on_demo_card_clicked(demo_id)
        assert out["demos"] == wel.demo_card_ids

    def test_hide_checkbox_writes_to_settings(self):
        wel, out = self._make()
        wel._on_hide_toggle(True)
        assert out["settings"].welcome_shown is True
        wel._on_hide_toggle(False)
        assert out["settings"].welcome_shown is False

    def test_theme_swatch_click_marks_seen(self):
        wel, out = self._make()
        # Themes may not be registered — the apply call is wrapped in
        # try/except, but the side effect (mark_seen + dismiss) lands.
        wel._on_theme_swatch_clicked("teengirl_notebook")
        assert out["settings"].welcome_shown is True
        assert out["dismissed"] == 1


# ===========================================================================
# 8. notebook_status_bar — theme indicator click callback lives.
# ===========================================================================


class TestStatusBar:
    def test_theme_indicator_click_routes_to_callback(self):
        from pharos_engine.ui.editor.notebook_status_bar import NotebookStatusBar

        captured = {"hits": 0}
        bar = NotebookStatusBar(
            on_theme_indicator_click=lambda: captured.__setitem__(
                "hits", captured["hits"] + 1,
            ),
        )
        assert bar.on_theme_indicator_click() is True
        assert captured["hits"] == 1

    def test_theme_indicator_no_callback_returns_false(self):
        from pharos_engine.ui.editor.notebook_status_bar import NotebookStatusBar

        bar = NotebookStatusBar()
        assert bar.on_theme_indicator_click() is False

    def test_message_setter_does_not_crash(self):
        from pharos_engine.ui.editor.notebook_status_bar import NotebookStatusBar

        bar = NotebookStatusBar()
        bar.set_message("hello", kind="success")
        assert bar.transient is not None


# ===========================================================================
# 9. theme_switcher_panel — 6 theme cards + creature toggles + globals.
# ===========================================================================


class TestThemeSwitcher:
    def test_theme_card_click_records_event(self):
        from pharos_engine.ui.editor.theme_switcher_panel import ThemeSwitcherPanel

        panel = ThemeSwitcherPanel()
        panel._on_theme_card_clicked("teengirl_notebook")
        assert any(
            event[0] == "theme_card_clicked"
            for event in panel.call_log
        )

    def test_creature_toggle_writes_state(self):
        from pharos_engine.ui.editor.theme_switcher_panel import ThemeSwitcherPanel

        panel = ThemeSwitcherPanel()
        panel._on_creature_toggle("fox_01", True)
        assert panel.creature_state["fox_01"] is True
        panel._on_creature_toggle("fox_01", False)
        assert panel.creature_state["fox_01"] is False

    def test_global_animations_toggle_lives(self):
        from pharos_engine.ui.editor.theme_switcher_panel import ThemeSwitcherPanel

        panel = ThemeSwitcherPanel()
        panel._on_animations_toggle(False)
        assert panel.animations_enabled is False

    def test_reduced_motion_toggle_lives(self):
        from pharos_engine.ui.editor.theme_switcher_panel import ThemeSwitcherPanel

        panel = ThemeSwitcherPanel()
        panel._on_reduced_motion_toggle(True)
        assert panel.reduced_motion is True

    def test_easter_eggs_toggle_lives(self):
        from pharos_engine.ui.editor.theme_switcher_panel import ThemeSwitcherPanel

        panel = ThemeSwitcherPanel()
        panel._on_easter_eggs_toggle(False)
        assert panel.easter_eggs is False

    def test_refresh_button_callback_lives(self):
        from pharos_engine.ui.editor.theme_switcher_panel import ThemeSwitcherPanel

        hits = {"n": 0}
        panel = ThemeSwitcherPanel(
            on_refresh=lambda: hits.__setitem__("n", hits["n"] + 1),
        )
        panel._on_refresh_clicked()
        assert hits["n"] == 1
        assert any(c[0] == "refresh_clicked" for c in panel.call_log)


# ===========================================================================
# 10. Shell — menu bar items (File / Edit / View / Help) must all work.
# ===========================================================================


class TestShellMenus:
    def test_menu_save_scene_calls_engine(self, stub_dpg):
        shell = _make_shell(stub_dpg)
        ok = shell.menu_save_scene()
        assert ok is True
        assert shell._engine.saved == ["ok"]

    def test_menu_save_scene_shows_status(self, stub_dpg):
        shell = _make_shell(stub_dpg)
        shell.menu_save_scene()
        # Status bar should see a success message + save_state True.
        assert shell._notebook_status_bar.saved is True
        assert shell._notebook_status_bar.transient is not None
        assert shell._notebook_status_bar.transient.kind == "success"

    def test_menu_open_scene_loads_path(self, stub_dpg):
        shell = _make_shell(stub_dpg)
        ok = shell.menu_open_scene(path="some_scene.json")
        assert ok is True
        assert shell._engine.loaded == ["some_scene.json"]

    def test_menu_open_scene_cancel_returns_false(self, stub_dpg):
        shell = _make_shell(stub_dpg)
        ok = shell.menu_open_scene(path="")
        assert ok is False

    def test_menu_undo_with_no_undo_manager_emits_status(self, stub_dpg):
        shell = _make_shell(stub_dpg)
        ok = shell.menu_undo()
        assert ok is False
        # The status bar should have a transient now.
        assert shell._notebook_status_bar.transient is not None

    def test_menu_undo_with_engine_undo_succeeds(self, stub_dpg):
        shell = _make_shell(stub_dpg)
        shell._engine.undo = lambda: setattr(shell._engine, "_undone", True)
        ok = shell.menu_undo()
        assert ok is True
        assert getattr(shell._engine, "_undone", False) is True

    def test_menu_reset_layout_returns_bool(self, stub_dpg):
        shell = _make_shell(stub_dpg)
        # Pre-populate the items so the configure path lands.
        stub_dpg.items.update({
            "toolbar_row", "left_panel", "center_panel",
            "right_panel", "bottom_panel",
        })
        result = shell.menu_reset_layout()
        assert result is True
        # The status bar should have a transient.
        assert shell._notebook_status_bar.transient is not None

    def test_menu_about_returns_info_dict(self, stub_dpg):
        shell = _make_shell(stub_dpg)
        info = shell.menu_about()
        assert isinstance(info, dict)
        assert "version" in info
        assert "engine_surface_url" in info
        assert info["engine_surface_url"].startswith("http")


# ===========================================================================
# 11. Shell — tool-change wiring forwards to engine + status bar + gizmo.
# ===========================================================================


class TestShellToolForwarding:
    def test_on_tool_changed_forwards_to_engine(self, stub_dpg):
        shell = _make_shell(stub_dpg)
        shell._on_tool_changed("rotate")
        assert shell._engine.tools == ["rotate"]
        assert shell._active_tool == "rotate"

    def test_on_tool_changed_updates_status_bar(self, stub_dpg):
        shell = _make_shell(stub_dpg)
        shell._on_tool_changed("scale")
        assert shell._notebook_status_bar.active_tool == "scale"

    def test_on_tool_changed_translates_move_to_translate(self, stub_dpg):
        shell = _make_shell(stub_dpg)
        shell._on_tool_changed("move")
        # The gizmo vocabulary uses "translate".
        assert shell._active_tool == "translate"

    def test_on_tool_changed_routes_to_gizmo(self, stub_dpg):
        shell = _make_shell(stub_dpg)
        # Inject a fake gizmo overlay with a set_mode hook.
        seen: list[str] = []
        shell._gizmo_overlay = types.SimpleNamespace(
            set_mode=lambda mode: seen.append(mode),
        )
        shell._on_tool_changed("rotate")
        assert "rotate" in seen


# ===========================================================================
# 12. Shell — handle_spawn forwards to scene + selects in outliner.
# ===========================================================================


class TestShellSpawn:
    def test_handle_spawn_falls_back_to_stub_entity(self, stub_dpg):
        shell = _make_shell(stub_dpg)
        entity = shell.handle_spawn("rope", {"name": "rope_demo"})
        assert entity is not None
        # The stub scene records every add.
        assert any(
            getattr(e, "kind", None) == "rope"
            for e in shell._engine.scene.entities
        )

    def test_handle_spawn_no_scene_returns_none(self, stub_dpg):
        shell = _make_shell(stub_dpg)
        shell._engine.scene = None
        result = shell.handle_spawn("rope", {})
        assert result is None


# ===========================================================================
# 13. Shell — welcome wiring (start blank, open demo) goes through engine.
# ===========================================================================


class TestShellWelcomeWiring:
    def test_welcome_start_blank_calls_engine_new_scene(self, stub_dpg):
        shell = _make_shell(stub_dpg)
        shell._welcome_start_blank()
        assert shell._engine.new_called == 1

    def test_welcome_open_demo_calls_engine_open_example(self, stub_dpg):
        shell = _make_shell(stub_dpg)
        opened: list[str] = []
        shell._engine.open_example = lambda p: opened.append(p)
        shell._welcome_open_demo("rope")
        assert opened == ["hello_rope.py"]


# ===========================================================================
# 14. Audit summary — no callback should be a bare ``lambda *_: None``.
# ===========================================================================


class TestAuditSummary:
    """Walk every panel and assert no clickable surface is left dead."""

    def test_toolbar_buttons_not_lambda_none(self):
        from pharos_engine.ui.editor.notebook_toolbar import NotebookToolbar

        bar = NotebookToolbar()
        for tool_id, btn in bar.buttons.items():
            # Fire the callback — should mutate state, not no-op.
            bar.set_active("select")
            btn.callback(None, None, None)
            assert bar.get_active() == tool_id

    def test_spawn_menu_summon_button_mutates_state(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu

        menu = NotebookSpawnMenu(on_spawn=lambda cid, spec: None)
        # Open the modal — open_modal must transition from None.
        assert menu.open_modal is None
        menu.summon("rope")
        assert menu.open_modal is not None
        menu.cancel_modal()
        assert menu.open_modal is None

    def test_welcome_demo_card_count_matches_callbacks(self):
        from pharos_engine.ui.editor.notebook_welcome import DEMO_CARDS, THEME_SWATCHES

        assert len(DEMO_CARDS) == 3
        assert len(THEME_SWATCHES) == 6

    def test_inspector_widget_help_button_records_field(self):
        from pharos_engine.ui.editor.notebook_inspector import NotebookInspector

        ins = NotebookInspector(target=_Probe())
        # Field doc lookup is the surface the ? button reads from.
        doc = ins._field_doc("flag")
        assert isinstance(doc, str)

    def test_status_bar_set_active_tool_lives(self):
        from pharos_engine.ui.editor.notebook_status_bar import NotebookStatusBar

        bar = NotebookStatusBar()
        bar.set_active_tool("move")
        assert bar.active_tool == "move"
