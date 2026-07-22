"""Tests for the notebook-editor usability-polish sprint.

Coverage
--------

* :class:`TooltipRegistry` — register / retrieve / bulk fill /
  ``install_dpg_hover`` wiring.
* :class:`NotebookOutliner` context menu — right-click opens, actions
  fire callbacks (rename / delete / duplicate / group / copy / paste).
* :class:`NotebookOutliner` multi-select — Ctrl+click adds, Shift+click
  range-extends, Escape clears, ``selection`` returns Entity list.
* :class:`NotebookContentBrowser` breadcrumb — segments, click routes
  to the correct ancestor.
* :class:`NotebookSpawnMenu` recents — persist to
  ``<project>/.slappy/recent_spawns.yaml`` across sessions, LRU-capped
  at 5.
* :class:`UndoStack` round-trip — push / undo / redo restore state.
* :class:`SaveOnQuitPrompt` — fires on dirty, resolves to
  save / discard / cancel.

The tests deliberately avoid a real DPG import; a lightweight stub
matches the pattern used by other ``test_editor_notebook_*.py`` files.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# DPG stub — accepts both context-manager and plain method calls.
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
        if len(args) >= 1 and isinstance(args[0], str) and name in {
            "delete_item",
        }:
            self.items.discard(args[0])

    # Context-manager returns.
    def collapsing_header(self, *a, **kw):
        self._track("collapsing_header", a, kw)
        return _StubCM()

    def group(self, *a, **kw):
        self._track("group", a, kw)
        return _StubCM()

    def child_window(self, *a, **kw):
        self._track("child_window", a, kw)
        return _StubCM()

    def window(self, *a, **kw):
        self._track("window", a, kw)
        return _StubCM()

    def tooltip(self, *a, **kw):
        self._track("tooltip", a, kw)
        return _StubCM()

    # Plain adds — always register the tag so does_item_exist agrees.
    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)

    def add_button(self, *a, **kw):
        self._track("add_button", a, kw)

    def add_checkbox(self, *a, **kw):
        self._track("add_checkbox", a, kw)

    def add_input_text(self, *a, **kw):
        self._track("add_input_text", a, kw)

    def add_tooltip(self, *a, **kw):
        self._track("add_tooltip", a, kw)

    def add_separator(self, *a, **kw):
        self._track("add_separator", a, kw)

    def add_item_clicked_handler(self, *a, **kw):
        self._track("add_item_clicked_handler", a, kw)

    def does_item_exist(self, tag, *a, **kw):
        return isinstance(tag, str) and tag in self.items

    def delete_item(self, tag, *a, **kw):
        self._track("delete_item", (tag,), kw)
        if isinstance(tag, str):
            self.items.discard(tag)

    def get_item_children(self, *a, **kw):
        return []

    def bind_item_font(self, *a, **kw):
        self._track("bind_item_font", a, kw)

    def last_item(self, *a, **kw):
        return "last_item_stub"


@pytest.fixture
def stub_dpg(monkeypatch):
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    for name in (
        "collapsing_header", "group", "child_window", "window", "tooltip",
        "add_text", "add_button", "add_checkbox", "add_input_text",
        "add_tooltip", "add_separator", "add_item_clicked_handler",
        "does_item_exist", "delete_item", "get_item_children",
        "bind_item_font", "last_item",
    ):
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
def clear_theme(monkeypatch):
    """Reset theme + sticker registry between tests."""
    try:
        from pharos_editor.ui.widgets import notebook_theme
        from pharos_editor.ui.widgets.notebook_theme import set_active_theme
        from pharos_editor.ui.widgets.sticker_corner import _active_stickers
    except Exception:
        yield
        return
    set_active_theme(None)
    notebook_theme._theme_listeners.clear()
    _active_stickers.clear()
    yield
    set_active_theme(None)
    notebook_theme._theme_listeners.clear()
    _active_stickers.clear()


# ---------------------------------------------------------------------------
# Fake entities
# ---------------------------------------------------------------------------


class _FakeEntity:
    def __init__(
        self,
        name: str,
        kind: str = "entity",
        eid: str | None = None,
    ) -> None:
        self.name = name
        self.kind = kind
        self.visible = True
        self.locked = False
        if eid is not None:
            self.id = eid


class _FakeWorld:
    def __init__(self, entities: list[Any] | None = None) -> None:
        self.entities: list[Any] = list(entities or [])


# ===========================================================================
# TooltipRegistry
# ===========================================================================


class TestTooltipRegistry:
    def test_register_stores_entry(self):
        from pharos_editor.ui.editor.tooltip_registry import TooltipRegistry

        reg = TooltipRegistry()
        reg.register("btn_save", "Save the scene")
        assert len(reg) == 1
        assert "btn_save" in reg
        assert reg.text_for("btn_save") == "Save the scene"

    def test_register_defaults_to_500ms(self):
        from pharos_editor.ui.editor.tooltip_registry import (
            DEFAULT_DELAY_MS,
            TooltipRegistry,
        )

        reg = TooltipRegistry()
        reg.register("btn", "hello")
        assert reg.get("btn").delay_ms == DEFAULT_DELAY_MS == 500

    def test_register_rejects_empty_tag(self):
        from pharos_editor.ui.editor.tooltip_registry import TooltipRegistry

        reg = TooltipRegistry()
        with pytest.raises(ValueError):
            reg.register("", "some text")

    def test_register_rejects_empty_text(self):
        from pharos_editor.ui.editor.tooltip_registry import TooltipRegistry

        reg = TooltipRegistry()
        with pytest.raises(ValueError):
            reg.register("btn", "")

    def test_register_rejects_negative_delay(self):
        from pharos_editor.ui.editor.tooltip_registry import TooltipRegistry

        reg = TooltipRegistry()
        with pytest.raises(ValueError):
            reg.register("btn", "hi", delay_ms=-1)

    def test_register_overwrites_existing(self):
        from pharos_editor.ui.editor.tooltip_registry import TooltipRegistry

        reg = TooltipRegistry()
        reg.register("btn", "old")
        reg.register("btn", "new")
        assert reg.text_for("btn") == "new"
        assert len(reg) == 1

    def test_register_many_bulk(self):
        from pharos_editor.ui.editor.tooltip_registry import TooltipRegistry

        reg = TooltipRegistry()
        reg.register_many([("a", "one"), ("b", "two"), ("c", "three")])
        assert len(reg) == 3

    def test_unregister_returns_true_on_remove(self):
        from pharos_editor.ui.editor.tooltip_registry import TooltipRegistry

        reg = TooltipRegistry()
        reg.register("btn", "hi")
        assert reg.unregister("btn") is True
        assert reg.unregister("btn") is False

    def test_default_registry_covers_toolbar_and_outliner(self):
        from pharos_editor.ui.editor.tooltip_registry import (
            build_default_registry,
        )

        reg = build_default_registry()
        assert "notebook_toolbar_save" in reg
        assert "notebook_outliner_search" in reg
        assert "notebook_cb_breadcrumb" in reg
        assert "notebook_spawn_summon" in reg

    def test_install_dpg_hover_returns_zero_when_dpg_none(self):
        from pharos_editor.ui.editor.tooltip_registry import TooltipRegistry

        reg = TooltipRegistry()
        reg.register("btn", "hi")
        assert reg.install_dpg_hover(None) == 0

    def test_install_dpg_hover_installs_only_existing_widgets(self, stub_dpg):
        from pharos_editor.ui.editor.tooltip_registry import TooltipRegistry

        # Widget "btn_existing" is pre-registered in DPG; "btn_missing" isn't.
        stub_dpg.items.add("btn_existing")
        reg = TooltipRegistry()
        reg.register("btn_existing", "shown")
        reg.register("btn_missing", "never rendered")

        import dearpygui.dearpygui as dpg
        installed = reg.install_dpg_hover(dpg)
        assert installed == 1
        # The tooltip child call should have run for the existing widget.
        tooltip_calls = stub_dpg.calls.get("tooltip", [])
        assert any(
            kw.get("parent") == "btn_existing" for _, kw in tooltip_calls
        )


# ===========================================================================
# NotebookOutliner right-click + multi-select
# ===========================================================================


class TestOutlinerContextMenu:
    def _make(self, entities: list[Any] | None = None):
        from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner
        world = _FakeWorld(entities or [
            _FakeEntity("e0", kind="rope", eid="e0"),
            _FakeEntity("e1", kind="ragdoll", eid="e1"),
            _FakeEntity("e2", kind="camera", eid="e2"),
        ])
        return NotebookOutliner(lambda: world, lambda e: None), world

    def test_open_context_menu_marks_menu_open(self, stub_dpg):
        out, world = self._make()
        state = out.open_context_menu(world.entities[0])
        assert state["open"] is True
        assert out.is_context_menu_open() is True
        assert "rename" in state["actions"]
        assert "delete" in state["actions"]
        assert "duplicate" in state["actions"]

    def test_close_context_menu_clears_state(self, stub_dpg):
        out, world = self._make()
        out.open_context_menu(world.entities[0])
        out.close_context_menu()
        assert out.is_context_menu_open() is False

    def test_invoke_rename_calls_callback(self, stub_dpg):
        out, world = self._make()
        captured: list[tuple] = []
        out.set_context_callbacks(
            on_rename=lambda ent, name: captured.append((ent, name)),
        )
        out.open_context_menu(world.entities[0])
        out.invoke_context_action("rename", "brand_new_name")
        assert captured == [(world.entities[0], "brand_new_name")]

    def test_invoke_delete_calls_callback(self, stub_dpg):
        out, world = self._make()
        captured: list[Any] = []
        out.set_context_callbacks(on_delete=captured.append)
        out.open_context_menu(world.entities[0])
        out.invoke_context_action("delete")
        assert captured == [world.entities[0]]

    def test_invoke_duplicate_calls_callback_and_suffixes_name(self, stub_dpg):
        out, world = self._make()
        def duplicate(ent):
            clone = _FakeEntity(ent.name, kind=ent.kind, eid=ent.name + "_dup")
            return clone
        out.set_context_callbacks(on_duplicate=duplicate)
        out.open_context_menu(world.entities[0])
        clone = out.invoke_context_action("duplicate")
        assert clone is not None
        assert clone.name.endswith(" (copy)")

    def test_invoke_group_calls_callback_with_selection(self, stub_dpg):
        out, world = self._make()
        captured: list[list[Any]] = []
        out.set_context_callbacks(on_group=captured.append)
        # Build up a multi-selection first.
        out.toggle_in_selection("e0")
        out.toggle_in_selection("e1")
        out.open_context_menu(world.entities[0])
        out.invoke_context_action("group")
        assert len(captured) == 1
        assert len(captured[0]) >= 2  # at least the two selected + target

    def test_group_action_appears_only_when_multi_selected(self, stub_dpg):
        out, world = self._make()
        out.open_context_menu(world.entities[0])
        # Only one entity in selection → no "group" action.
        assert "group" not in out.context_menu_actions()
        out.toggle_in_selection("e1")
        assert "group" in out.context_menu_actions()

    def test_invoke_copy_calls_callback(self, stub_dpg):
        out, world = self._make()
        captured: list[list[Any]] = []
        out.set_context_callbacks(on_copy=captured.append)
        out.open_context_menu(world.entities[0])
        out.invoke_context_action("copy")
        assert len(captured) == 1
        assert world.entities[0] in captured[0]

    def test_invoke_paste_returns_pasted_entities(self, stub_dpg):
        out, world = self._make()
        fresh = [_FakeEntity("pasted", kind="rope", eid="pasted")]
        out.set_context_callbacks(on_paste=lambda: fresh)
        out.open_context_menu(world.entities[0])
        result = out.invoke_context_action("paste")
        assert result == fresh


class TestOutlinerMultiSelect:
    def _make(self):
        from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner
        world = _FakeWorld([
            _FakeEntity("e0", kind="rope", eid="e0"),
            _FakeEntity("e1", kind="ragdoll", eid="e1"),
            _FakeEntity("e2", kind="camera", eid="e2"),
            _FakeEntity("e3", kind="light", eid="e3"),
        ])
        return NotebookOutliner(lambda: world, lambda e: None), world

    def test_ctrl_click_toggles_membership(self, stub_dpg):
        out, world = self._make()
        out.toggle_in_selection("e0")
        out.toggle_in_selection("e2")
        ids = out.selection_ids
        assert set(ids) == {"e0", "e2"}
        assert out.selection_count == 2

    def test_ctrl_click_second_time_removes(self, stub_dpg):
        out, world = self._make()
        out.toggle_in_selection("e0")
        out.toggle_in_selection("e0")
        assert out.selection_ids == []
        assert out.selection_count == 0

    def test_selection_returns_entity_list(self, stub_dpg):
        out, world = self._make()
        out.toggle_in_selection("e0")
        out.toggle_in_selection("e2")
        sel = out.selection
        names = {e.name for e in sel}
        assert names == {"e0", "e2"}

    def test_shift_click_range_extends(self, stub_dpg):
        out, world = self._make()
        # Set anchor at e0 via a normal click; then shift-click e2 to
        # extend the selection over e0..e2.
        out.handle_row_click("e0")
        out.extend_selection_to("e2")
        assert out.selection_count == 3
        assert set(out.selection_ids) >= {"e0", "e1", "e2"}

    def test_shift_click_reversed_range_still_works(self, stub_dpg):
        out, world = self._make()
        out.handle_row_click("e3")
        out.extend_selection_to("e1")
        assert set(out.selection_ids) == {"e1", "e2", "e3"}

    def test_escape_clears_selection(self, stub_dpg):
        out, world = self._make()
        out.toggle_in_selection("e0")
        out.toggle_in_selection("e2")
        out.handle_escape()
        assert out.selection_ids == []
        assert out.is_context_menu_open() is False

    def test_plain_click_replaces_selection(self, stub_dpg):
        out, world = self._make()
        out.toggle_in_selection("e0")
        out.toggle_in_selection("e2")
        out.handle_row_click("e1")
        assert out.selection_ids == ["e1"]

    def test_right_click_opens_menu_via_handle_row_click(self, stub_dpg):
        out, world = self._make()
        out.handle_row_click("e0", button=1)
        assert out.is_context_menu_open() is True


# ===========================================================================
# NotebookContentBrowser breadcrumb
# ===========================================================================


class TestBreadcrumb:
    def test_no_root_bound_returns_projects_default(self):
        from pharos_editor.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        cb = NotebookContentBrowser(
            on_open_scene=lambda p: None,
            on_open_script=lambda p: None,
            on_open_asset=lambda p: None,
        )
        segs = cb.breadcrumb_segments()
        assert segs and segs[0][0] == "projects"

    def test_breadcrumb_with_root_only(self, tmp_path):
        from pharos_editor.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        cb = NotebookContentBrowser(
            on_open_scene=lambda p: None,
            on_open_script=lambda p: None,
            on_open_asset=lambda p: None,
        )
        (tmp_path / "MyGame").mkdir()
        cb.set_root(tmp_path / "MyGame")
        segs = cb.breadcrumb_segments()
        assert [s[0] for s in segs] == ["projects", "MyGame"]

    def test_breadcrumb_after_navigating_into_subdir(self, tmp_path):
        from pharos_editor.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        cb = NotebookContentBrowser(
            on_open_scene=lambda p: None,
            on_open_script=lambda p: None,
            on_open_asset=lambda p: None,
        )
        proj = tmp_path / "MyGame"
        (proj / "scenes").mkdir(parents=True)
        cb.set_root(proj)
        cb.set_cwd(proj / "scenes")
        labels = [s[0] for s in cb.breadcrumb_segments()]
        assert labels == ["projects", "MyGame", "scenes"]

    def test_navigate_to_segment_clears_cwd_at_root(self, tmp_path):
        from pharos_editor.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        cb = NotebookContentBrowser(
            on_open_scene=lambda p: None,
            on_open_script=lambda p: None,
            on_open_asset=lambda p: None,
        )
        proj = tmp_path / "MyGame"
        (proj / "scenes").mkdir(parents=True)
        cb.set_root(proj)
        cb.set_cwd(proj / "scenes")
        # Clicking segment index 1 (the root) should clear the cwd.
        cb.navigate_to_segment(1)
        assert cb.get_cwd() is None

    def test_navigate_to_segment_sets_cwd_to_ancestor(self, tmp_path):
        from pharos_editor.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        cb = NotebookContentBrowser(
            on_open_scene=lambda p: None,
            on_open_script=lambda p: None,
            on_open_asset=lambda p: None,
        )
        proj = tmp_path / "MyGame"
        deep = proj / "scenes" / "levels"
        deep.mkdir(parents=True)
        cb.set_root(proj)
        cb.set_cwd(deep)
        cb.navigate_to_segment(2)  # jump to "scenes"
        assert cb.get_cwd() == proj / "scenes"

    def test_set_cwd_outside_root_raises(self, tmp_path):
        from pharos_editor.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        cb = NotebookContentBrowser(
            on_open_scene=lambda p: None,
            on_open_script=lambda p: None,
            on_open_asset=lambda p: None,
        )
        proj = tmp_path / "MyGame"
        proj.mkdir()
        other = tmp_path / "OtherProject"
        other.mkdir()
        cb.set_root(proj)
        with pytest.raises(ValueError):
            cb.set_cwd(other)

    def test_iter_files_respects_cwd(self, tmp_path):
        from pharos_editor.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        cb = NotebookContentBrowser(
            on_open_scene=lambda p: None,
            on_open_script=lambda p: None,
            on_open_asset=lambda p: None,
        )
        proj = tmp_path / "MyGame"
        (proj / "scenes").mkdir(parents=True)
        (proj / "scripts").mkdir(parents=True)
        (proj / "scenes" / "main.scene.yaml").write_text("dummy")
        (proj / "scripts" / "boot.py").write_text("pass")
        cb.set_root(proj)
        # No cwd → both files show.
        assert len(cb.iter_files()) == 2
        cb.set_cwd(proj / "scenes")
        files = cb.iter_files()
        assert len(files) == 1
        assert files[0].name == "main.scene.yaml"


# ===========================================================================
# NotebookSpawnMenu recents
# ===========================================================================


class TestSpawnRecents:
    def _make(self):
        from pharos_editor.ui.editor.notebook_spawn_menu import NotebookSpawnMenu

        return NotebookSpawnMenu(on_spawn=lambda cid, spec: None)

    def test_record_recent_persists_across_sessions(self, tmp_path):
        menu = self._make()
        menu.set_project_root(tmp_path)
        menu.record_recent("rope")
        menu.record_recent("ragdoll")

        # New instance — reload the same project.
        menu2 = self._make()
        menu2.set_project_root(tmp_path)
        assert menu2.get_recent_ids() == ["rope", "ragdoll"]

    def test_record_recent_lru_capped_at_five(self, tmp_path):
        menu = self._make()
        menu.set_project_root(tmp_path)
        for cid in ("rope", "ragdoll", "humanoid", "ik_chain",
                    "zone_rect", "zone_threshold", "light_point"):
            menu.record_recent(cid)
        assert len(menu.get_recent_ids()) == 5
        # The oldest two ("rope", "ragdoll") fell off the front.
        assert "rope" not in menu.get_recent_ids()
        assert menu.get_recent_ids()[-1] == "light_point"

    def test_record_recent_moves_duplicates_to_top(self, tmp_path):
        menu = self._make()
        menu.set_project_root(tmp_path)
        menu.record_recent("rope")
        menu.record_recent("ragdoll")
        menu.record_recent("rope")
        assert menu.get_recent_ids() == ["ragdoll", "rope"]

    def test_recent_cards_returns_spawncard_objects(self, tmp_path):
        from pharos_editor.ui.editor.notebook_spawn_menu import SpawnCard

        menu = self._make()
        menu.set_project_root(tmp_path)
        menu.record_recent("rope")
        cards = menu.recent_cards()
        assert cards and all(isinstance(c, SpawnCard) for c in cards)

    def test_summon_bumps_recents(self, stub_dpg, tmp_path):
        menu = self._make()
        menu.set_project_root(tmp_path)
        menu.summon("rope")
        assert "rope" in menu.get_recent_ids()

    def test_recents_yaml_at_expected_location(self, tmp_path):
        menu = self._make()
        menu.set_project_root(tmp_path)
        menu.record_recent("rope")
        yaml_path = tmp_path / ".slappy" / "recent_spawns.yaml"
        assert yaml_path.exists()
        text = yaml_path.read_text(encoding="utf-8")
        assert "rope" in text


# ===========================================================================
# UndoStack round-trip
# ===========================================================================


class TestUndoStack:
    def test_push_undo_redo_round_trip(self):
        from pharos_editor.ui.editor.editor_undo import UndoStack

        state = {"count": 0}
        stack = UndoStack()
        stack.push(
            "increment",
            forward=lambda: state.__setitem__("count", state["count"] + 1),
            reverse=lambda: state.__setitem__("count", state["count"] - 1),
        )
        # After push, state is expected to already be at "post-forward"
        # (the caller ran forward before the push).
        state["count"] = 1
        assert stack.can_undo()
        stack.undo()
        assert state["count"] == 0
        assert stack.can_redo()
        stack.redo()
        assert state["count"] == 1

    def test_push_clears_redo(self):
        from pharos_editor.ui.editor.editor_undo import UndoStack

        stack = UndoStack()
        stack.push("a", lambda: None, lambda: None)
        stack.undo()
        assert stack.can_redo()
        stack.push("b", lambda: None, lambda: None)
        assert not stack.can_redo()

    def test_capacity_trims_from_bottom(self):
        from pharos_editor.ui.editor.editor_undo import UndoStack

        stack = UndoStack(capacity=2)
        stack.push("a", lambda: None, lambda: None)
        stack.push("b", lambda: None, lambda: None)
        stack.push("c", lambda: None, lambda: None)
        assert stack.undo_depth == 2
        top = stack.peek_undo()
        assert top is not None and top.action_id == "c"

    def test_undo_on_empty_returns_none(self):
        from pharos_editor.ui.editor.editor_undo import UndoStack

        stack = UndoStack()
        assert stack.undo() is None
        assert stack.redo() is None

    def test_clear_empties_both_stacks(self):
        from pharos_editor.ui.editor.editor_undo import UndoStack

        stack = UndoStack()
        stack.push("a", lambda: None, lambda: None)
        stack.undo()
        stack.clear()
        assert stack.undo_depth == 0
        assert stack.redo_depth == 0


# ===========================================================================
# EntityClipboard
# ===========================================================================


class TestEntityClipboard:
    def test_copy_stores_snapshot(self):
        from pharos_editor.ui.editor.entity_clipboard import EntityClipboard

        clip = EntityClipboard()
        ent = _FakeEntity("hero", kind="body", eid="hero")
        assert clip.copy(ent) == 1
        assert len(clip) == 1
        snap = clip.snapshots()[0]
        assert snap["name"] == "hero"

    def test_paste_suffixes_name(self):
        from pharos_editor.ui.editor.entity_clipboard import EntityClipboard

        clip = EntityClipboard()
        clip.copy(_FakeEntity("hero", kind="body", eid="hero"))
        pasted = clip.paste()
        assert pasted[0]["name"] == "hero (paste)"

    def test_singleton_reset(self):
        from pharos_editor.ui.editor.entity_clipboard import (
            get_active_clipboard,
            reset_active_clipboard,
        )

        a = get_active_clipboard()
        b = get_active_clipboard()
        assert a is b
        reset_active_clipboard()
        c = get_active_clipboard()
        assert c is not a


# ===========================================================================
# SaveOnQuitPrompt
# ===========================================================================


class TestSaveOnQuitPrompt:
    def test_clean_scene_quits_directly(self):
        from pharos_editor.ui.editor.save_on_quit import SaveOnQuitPrompt

        quit_called: list[bool] = []
        p = SaveOnQuitPrompt(
            is_dirty=lambda: False,
            save_scene=lambda: None,
            quit_app=lambda: quit_called.append(True),
        )
        result = p.request_close()
        assert result is True
        assert quit_called == [True]
        assert p.is_open is False

    def test_dirty_scene_opens_prompt(self, stub_dpg):
        from pharos_editor.ui.editor.save_on_quit import SaveOnQuitPrompt

        p = SaveOnQuitPrompt(
            is_dirty=lambda: True,
            save_scene=lambda: None,
            quit_app=lambda: None,
        )
        result = p.request_close()
        assert result is False
        assert p.is_open is True

    def test_resolve_save_calls_save_then_quit(self, stub_dpg):
        from pharos_editor.ui.editor.save_on_quit import (
            SaveOnQuitPrompt,
            SavePromptChoice,
        )

        order: list[str] = []
        p = SaveOnQuitPrompt(
            is_dirty=lambda: True,
            save_scene=lambda: order.append("save"),
            quit_app=lambda: order.append("quit"),
        )
        p.request_close()
        result = p.resolve(SavePromptChoice.SAVE)
        assert result is True
        assert order == ["save", "quit"]

    def test_resolve_discard_skips_save(self, stub_dpg):
        from pharos_editor.ui.editor.save_on_quit import (
            SaveOnQuitPrompt,
            SavePromptChoice,
        )

        order: list[str] = []
        p = SaveOnQuitPrompt(
            is_dirty=lambda: True,
            save_scene=lambda: order.append("save"),
            quit_app=lambda: order.append("quit"),
        )
        p.request_close()
        p.resolve(SavePromptChoice.DISCARD)
        assert order == ["quit"]

    def test_resolve_cancel_aborts(self, stub_dpg):
        from pharos_editor.ui.editor.save_on_quit import (
            SaveOnQuitPrompt,
            SavePromptChoice,
        )

        order: list[str] = []
        p = SaveOnQuitPrompt(
            is_dirty=lambda: True,
            save_scene=lambda: order.append("save"),
            quit_app=lambda: order.append("quit"),
        )
        p.request_close()
        result = p.resolve(SavePromptChoice.CANCEL)
        assert result is False
        assert order == []
        assert p.is_open is False

    def test_resolve_wrong_type_raises(self):
        from pharos_editor.ui.editor.save_on_quit import SaveOnQuitPrompt

        p = SaveOnQuitPrompt(
            is_dirty=lambda: False,
            save_scene=lambda: None,
            quit_app=lambda: None,
        )
        with pytest.raises(TypeError):
            p.resolve("save")  # type: ignore[arg-type]
