"""Tests for :class:`NotebookCommandPalette` (CC7 sprint).

Covers:

* Construction + defaults + REGISTRY binding.
* ``open`` / ``close`` / ``toggle`` lifecycle.
* Fuzzy match (substring + acronym + priority + tie-breakers).
* Recent-actions ring buffer (max 8, MRU, dedup).
* Enter → dispatches the highlighted action.
* Escape (``close``) → no dispatch.
* Arrow keys → highlight moves + clamps.
* Empty search → recent strip on top.
* Unknown action_ids filtered out.
* Lazy registration in the editor ``__init__`` alphabetical.
* Build under a stub DPG without crashing.
"""
from __future__ import annotations

import sys
import types

import pytest

from slappyengine.tool_router import REGISTRY, ToolAction, ToolRouter


# ---------------------------------------------------------------------------
# Headless DPG stub (mirrors ``notebook_prefab_menu`` test rig).
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

    def window(self, *a, **kw):
        self._track("window", a, kw)
        return _StubCM()

    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)

    def add_button(self, *a, **kw):
        self._track("add_button", a, kw)

    def add_input_text(self, *a, **kw):
        self._track("add_input_text", a, kw)

    def add_separator(self, *a, **kw):
        self._track("add_separator", a, kw)

    def add_selectable(self, *a, **kw):
        self._track("add_selectable", a, kw)

    def does_item_exist(self, tag, *a, **kw):
        return tag in self.items

    def delete_item(self, tag, *a, **kw):
        self._track("delete_item", (tag,), kw)
        if isinstance(tag, str):
            self.items.discard(tag)


@pytest.fixture
def stub_dpg(monkeypatch):
    """Install a stub ``dearpygui.dearpygui`` module."""
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    for name in (
        "group", "child_window", "window",
        "add_text", "add_button", "add_input_text",
        "add_selectable", "add_separator",
        "does_item_exist", "delete_item",
    ):
        setattr(mod, name, getattr(stub, name))

    def _fallback(name: str):
        def _noop(*a, **kw):
            stub.calls.setdefault(name, []).append((a, kw))
        return _noop
    mod.__getattr__ = _fallback

    mod.__slappy_stub__ = True

    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


# ---------------------------------------------------------------------------
# Router helpers
# ---------------------------------------------------------------------------


def _make_router(*actions: ToolAction) -> ToolRouter:
    r = ToolRouter()
    for a in actions:
        r.register(a)
    return r


def _make_action(
    action_id: str,
    label: str | None = None,
    category: str = "file",
) -> ToolAction:
    return ToolAction(
        action_id=action_id,
        label=label if label is not None else action_id,
        rust_backing=None,
        python_fallback=lambda ctx: ("called", action_id),
        required_args=[],
        category=category,
    )


def _make_palette(**kwargs):
    from slappyengine.ui.editor.notebook_command_palette import (
        NotebookCommandPalette,
    )
    return NotebookCommandPalette(**kwargs)


# ===========================================================================
# Construction
# ===========================================================================


class TestConstruction:
    def test_default_router_is_registry(self):
        palette = _make_palette()
        assert palette.router is REGISTRY

    def test_custom_router_accepted(self):
        router = _make_router(_make_action("editor.save", "Save"))
        palette = _make_palette(router=router)
        assert palette.router is router

    def test_router_type_check(self):
        with pytest.raises(TypeError):
            _make_palette(router="not-a-router")

    def test_dispatcher_type_check(self):
        with pytest.raises((TypeError, ValueError)):
            _make_palette(dispatcher="not-callable")

    def test_starts_closed(self):
        palette = _make_palette()
        assert palette.is_open is False
        assert palette.is_built is False

    def test_title_constant(self):
        from slappyengine.ui.editor.notebook_command_palette import (
            NotebookCommandPalette,
        )
        assert NotebookCommandPalette.TITLE == "Command Palette"

    def test_recent_buffer_size_constant(self):
        from slappyengine.ui.editor.notebook_command_palette import (
            RECENT_BUFFER_SIZE,
        )
        assert RECENT_BUFFER_SIZE == 8

    def test_max_visible_rows_constant(self):
        from slappyengine.ui.editor.notebook_command_palette import (
            MAX_VISIBLE_ROWS,
        )
        assert MAX_VISIBLE_ROWS == 15

    def test_category_priority_ordered(self):
        from slappyengine.ui.editor.notebook_command_palette import (
            CATEGORY_PRIORITY,
        )
        assert CATEGORY_PRIORITY[:3] == ("file", "edit", "tool")


# ===========================================================================
# Open / close / toggle lifecycle
# ===========================================================================


class TestLifecycle:
    def test_open_flips_is_open(self):
        palette = _make_palette()
        palette.open()
        assert palette.is_open is True

    def test_open_is_idempotent(self):
        palette = _make_palette()
        palette.open()
        palette.open()
        # No exception + still open.
        assert palette.is_open is True

    def test_close_flips_is_open(self):
        palette = _make_palette()
        palette.open()
        palette.close()
        assert palette.is_open is False

    def test_close_when_closed_is_noop(self):
        palette = _make_palette()
        # Never opened — close should be a silent no-op.
        palette.close()
        assert palette.is_open is False

    def test_toggle_opens_closed_palette(self):
        palette = _make_palette()
        assert palette.toggle() is True
        assert palette.is_open is True

    def test_toggle_closes_open_palette(self):
        palette = _make_palette()
        palette.open()
        assert palette.toggle() is False
        assert palette.is_open is False

    def test_close_clears_search(self):
        palette = _make_palette()
        palette.open()
        palette.set_search("undo")
        palette.close()
        assert palette.search == ""

    def test_build_marks_is_built(self):
        palette = _make_palette()
        palette.build("some-parent-tag")
        assert palette.is_built is True

    def test_build_rejects_bad_parent_tag(self):
        palette = _make_palette()
        with pytest.raises(TypeError):
            palette.build(3.14)  # type: ignore[arg-type]


# ===========================================================================
# Fuzzy match
# ===========================================================================


class TestFuzzyMatch:
    def test_substring_beats_acronym(self):
        router = _make_router(
            _make_action("editor.save", "Save", category="file"),
            _make_action("scene.animate.value", "SAV", category="tool"),
        )
        palette = _make_palette(router=router)
        palette.set_search("sav")
        ids = [a.action_id for a in palette.matches()]
        # "Save" — substring at index 0 — beats the acronym-match.
        assert ids[0] == "editor.save"

    def test_substring_earlier_index_wins(self):
        router = _make_router(
            _make_action("editor.save", "Save Project", category="file"),
            _make_action("editor.export_asset_save", "Export Save", category="file"),
        )
        palette = _make_palette(router=router)
        palette.set_search("save")
        # "Save Project" — hit at 0 — comes before "Export Save".
        assert palette.matches()[0].action_id == "editor.save"

    def test_acronym_match_hits(self):
        router = _make_router(
            _make_action("tool.select_all", "Select All", category="tool"),
        )
        palette = _make_palette(router=router)
        palette.set_search("sat")
        # "select_all_tool" contains initials s-a-t via action_id.
        # (action_id "tool.select_all" → initials t-s-a).
        # The label "Select All" splits to s-a; try "sa".
        palette.set_search("sa")
        assert any(
            a.action_id == "tool.select_all" for a in palette.matches()
        )

    def test_acronym_multi_token(self):
        router = _make_router(
            _make_action("select_all_tool", "Select All Tool", category="tool"),
        )
        palette = _make_palette(router=router)
        palette.set_search("sat")
        ids = [a.action_id for a in palette.matches()]
        assert "select_all_tool" in ids

    def test_no_match_returns_empty(self):
        router = _make_router(_make_action("editor.save", "Save"))
        palette = _make_palette(router=router)
        palette.set_search("zzzzzz")
        assert palette.matches() == []

    def test_case_insensitive(self):
        router = _make_router(_make_action("editor.save", "Save"))
        palette = _make_palette(router=router)
        palette.set_search("SAVE")
        assert len(palette.matches()) == 1

    def test_top_n_limit(self):
        acts = [_make_action(f"cat.thing_{i}", f"Thing {i}") for i in range(30)]
        router = _make_router(*acts)
        palette = _make_palette(router=router)
        palette.set_search("thing")
        assert len(palette.matches()) <= 15

    def test_category_priority_breaks_ties(self):
        # Two identical-label actions in different categories — the
        # "file" one should win the tie against a "spawn" one.
        router = _make_router(
            _make_action("spawn.item", "Item", category="spawn"),
            _make_action("file.item", "Item", category="file"),
        )
        palette = _make_palette(router=router)
        palette.set_search("item")
        assert palette.matches()[0].action_id == "file.item"


# ===========================================================================
# Recent-actions ring buffer
# ===========================================================================


class TestRecentBuffer:
    def _router(self) -> ToolRouter:
        return _make_router(
            *[_make_action(f"a.action_{i}", f"Action {i}") for i in range(20)]
        )

    def test_empty_by_default(self):
        palette = _make_palette(router=self._router())
        assert palette.recent_action_ids == []

    def test_dispatch_pushes_recent(self):
        palette = _make_palette(router=self._router())
        palette.set_search("action 0")
        palette.dispatch_selected()
        assert "a.action_0" in palette.recent_action_ids

    def test_buffer_capped_at_eight(self):
        palette = _make_palette(router=self._router())
        for i in range(12):
            palette.set_search(f"action {i}")
            palette.dispatch_selected()
        assert len(palette.recent_action_ids) == 8

    def test_dedup_moves_to_front(self):
        palette = _make_palette(router=self._router())
        palette.set_search("action 1")
        palette.dispatch_selected()
        palette.set_search("action 2")
        palette.dispatch_selected()
        palette.set_search("action 1")
        palette.dispatch_selected()
        assert palette.recent_action_ids[0] == "a.action_1"
        assert palette.recent_action_ids.count("a.action_1") == 1

    def test_clear_recent(self):
        palette = _make_palette(router=self._router())
        palette.set_search("action 0")
        palette.dispatch_selected()
        assert palette.recent_action_ids
        palette.clear_recent()
        assert palette.recent_action_ids == []

    def test_empty_search_shows_recent_first(self):
        palette = _make_palette(router=self._router())
        palette.set_search("action 5")
        palette.dispatch_selected()
        palette.set_search("")  # empty
        matches = palette.matches()
        # Recent (a.action_5) is first, others follow.
        assert matches[0].action_id == "a.action_5"


# ===========================================================================
# Enter dispatch
# ===========================================================================


class TestDispatch:
    def test_enter_invokes_dispatcher(self):
        seen: list[str] = []
        router = _make_router(_make_action("editor.save", "Save"))
        palette = _make_palette(
            router=router, dispatcher=lambda aid: seen.append(aid),
        )
        palette.open()
        palette.set_search("save")
        rv = palette.dispatch_selected()
        assert rv == "editor.save"
        assert seen == ["editor.save"]

    def test_enter_closes_palette(self):
        router = _make_router(_make_action("editor.save", "Save"))
        palette = _make_palette(router=router, dispatcher=lambda aid: None)
        palette.open()
        palette.set_search("save")
        palette.dispatch_selected()
        assert palette.is_open is False

    def test_enter_empty_matches_returns_none(self):
        router = _make_router(_make_action("editor.save", "Save"))
        palette = _make_palette(router=router, dispatcher=lambda aid: None)
        palette.open()
        palette.set_search("zzzz")  # no match
        rv = palette.dispatch_selected()
        assert rv is None

    def test_dispatcher_exception_swallowed(self):
        def boom(_aid: str) -> None:
            raise RuntimeError("boom")
        router = _make_router(_make_action("editor.save", "Save"))
        palette = _make_palette(router=router, dispatcher=boom)
        palette.open()
        palette.set_search("save")
        # Should not raise + should still close the palette.
        palette.dispatch_selected()
        assert palette.is_open is False

    def test_default_dispatcher_uses_router(self):
        # No explicit dispatcher — should route via the router.
        recorded: list[dict] = []
        action = ToolAction(
            action_id="editor.save",
            label="Save",
            rust_backing=None,
            python_fallback=lambda ctx: recorded.append(ctx),
            required_args=[],
            category="file",
        )
        router = _make_router(action)
        palette = _make_palette(router=router)
        palette.set_search("save")
        palette.dispatch_selected()
        assert recorded == [{}]

    def test_dispatch_by_action_id_directly(self):
        seen: list[str] = []
        router = _make_router(_make_action("editor.save", "Save"))
        palette = _make_palette(
            router=router, dispatcher=lambda aid: seen.append(aid),
        )
        palette.dispatch_by_action_id("editor.save")
        assert seen == ["editor.save"]

    def test_dispatch_unknown_action_id_noop(self):
        router = _make_router(_make_action("editor.save", "Save"))
        palette = _make_palette(router=router, dispatcher=lambda aid: None)
        rv = palette.dispatch_by_action_id("does.not.exist")
        assert rv is None


# ===========================================================================
# Highlight movement
# ===========================================================================


class TestHighlight:
    def test_default_highlight_zero(self):
        router = _make_router(
            *[_make_action(f"a.act_{i}") for i in range(5)]
        )
        palette = _make_palette(router=router)
        assert palette.highlight == 0

    def test_move_down(self):
        router = _make_router(
            *[_make_action(f"a.act_{i}") for i in range(5)]
        )
        palette = _make_palette(router=router)
        palette.move_highlight(1)
        assert palette.highlight == 1

    def test_move_up_clamps_to_zero(self):
        router = _make_router(
            *[_make_action(f"a.act_{i}") for i in range(5)]
        )
        palette = _make_palette(router=router)
        palette.move_highlight(-3)
        assert palette.highlight == 0

    def test_move_down_clamps_to_last(self):
        router = _make_router(
            *[_make_action(f"a.act_{i}") for i in range(3)]
        )
        palette = _make_palette(router=router)
        palette.move_highlight(99)
        assert palette.highlight == 2  # 3 items → last index is 2.

    def test_move_on_empty_stays_zero(self):
        router = _make_router()
        palette = _make_palette(router=router)
        palette.move_highlight(5)
        assert palette.highlight == 0

    def test_search_resets_highlight(self):
        router = _make_router(
            *[_make_action(f"a.act_{i}") for i in range(5)]
        )
        palette = _make_palette(router=router)
        palette.move_highlight(2)
        palette.set_search("act")
        # Search change resets highlight to 0.
        assert palette.highlight == 0


# ===========================================================================
# Empty search / router edge cases
# ===========================================================================


class TestEmptySearch:
    def test_empty_search_returns_all_within_max(self):
        router = _make_router(
            *[_make_action(f"a.act_{i}") for i in range(30)]
        )
        palette = _make_palette(router=router)
        palette.set_search("")
        assert len(palette.matches()) <= 15

    def test_empty_search_no_recent_alphabetical(self):
        router = _make_router(
            _make_action("z.last"),
            _make_action("a.first"),
        )
        palette = _make_palette(router=router)
        palette.set_search("")
        matches = palette.matches()
        assert matches[0].action_id == "a.first"

    def test_unknown_recent_id_filtered_out(self):
        # Simulate a stale recent entry by pushing directly, then
        # unregister so ``recompute`` should skip it.
        router = _make_router(
            _make_action("a.stays"),
            _make_action("b.leaves"),
        )
        palette = _make_palette(router=router)
        palette.set_search("leaves")
        palette.dispatch_selected()
        # Unregister the recently-invoked action so it goes stale.
        router.unregister("b.leaves")
        palette.set_search("")
        ids = [a.action_id for a in palette.matches()]
        assert "b.leaves" not in ids


# ===========================================================================
# Wiring
# ===========================================================================


class TestWiring:
    def test_set_router_replaces_source(self):
        r1 = _make_router(_make_action("r1.thing"))
        r2 = _make_router(_make_action("r2.thing"))
        palette = _make_palette(router=r1)
        assert palette.router is r1
        palette.set_router(r2)
        assert palette.router is r2

    def test_set_router_type_check(self):
        palette = _make_palette()
        with pytest.raises(TypeError):
            palette.set_router("not-a-router")

    def test_set_dispatcher(self):
        seen: list[str] = []
        palette = _make_palette()
        palette.set_dispatcher(lambda aid: seen.append(aid))
        router = _make_router(_make_action("editor.save"))
        palette.set_router(router)
        palette.set_search("save")
        palette.dispatch_selected()
        assert seen == ["editor.save"]

    def test_set_dispatcher_type_check(self):
        palette = _make_palette()
        with pytest.raises((TypeError, ValueError)):
            palette.set_dispatcher("not-callable")

    def test_set_shortcuts(self):
        palette = _make_palette()
        palette.set_shortcuts({"editor.save": "Ctrl+S"})
        assert palette._shortcuts == {"editor.save": "Ctrl+S"}

    def test_set_shortcuts_type_check(self):
        palette = _make_palette()
        with pytest.raises(TypeError):
            palette.set_shortcuts("not-a-dict")


# ===========================================================================
# Headless DPG smoke
# ===========================================================================


class TestHeadlessDPG:
    def test_build_open_close_under_stub_dpg(self, stub_dpg):
        router = _make_router(
            _make_action("editor.save"),
            _make_action("editor.new"),
        )
        palette = _make_palette(router=router)
        palette.build("parent-tag")
        palette.open()
        palette.close()
        # No exceptions is the pass condition; also check the DPG stub
        # recorded at least the modal window creation on open.
        assert "window" in stub_dpg.calls

    def test_search_recompute_under_stub_dpg(self, stub_dpg):
        router = _make_router(
            _make_action("editor.save"),
            _make_action("editor.new"),
        )
        palette = _make_palette(router=router)
        palette.build("parent-tag")
        palette.open()
        palette.set_search("save")
        assert len(palette.matches()) == 1


# ===========================================================================
# Registration in editor __init__ __all__ + lazy map
# ===========================================================================


class TestRegistration:
    def test_all_exports_contains_palette(self):
        import slappyengine.ui.editor as editor_pkg
        assert "NotebookCommandPalette" in editor_pkg.__all__

    def test_lazy_map_has_palette(self):
        import slappyengine.ui.editor as editor_pkg
        assert "NotebookCommandPalette" in editor_pkg._LAZY_MAP

    def test_lazy_import_yields_class(self):
        from slappyengine.ui.editor import NotebookCommandPalette
        assert NotebookCommandPalette.__name__ == "NotebookCommandPalette"

    def test_all_list_is_sorted(self):
        # Sanity — the alphabetical ordering the sprint asks for.
        import slappyengine.ui.editor as editor_pkg
        names = editor_pkg.__all__
        idx = names.index("NotebookCommandPalette")
        assert names[idx - 1] < "NotebookCommandPalette"
        assert names[idx + 1] > "NotebookCommandPalette"
