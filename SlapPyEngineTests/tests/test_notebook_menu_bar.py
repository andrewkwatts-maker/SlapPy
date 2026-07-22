"""Tests for :class:`NotebookMenuBar` (EE3).

Covers:

* Construction + defaults + editor ``__init__`` lazy hook.
* :meth:`set_router` populates every canonical category submenu.
* Each menu's items match ``router.list_by_category(cat)``.
* Hotkey shortcut column is resolved through the bound hotkey_map.
* Click dispatches the correct action via the router.
* :meth:`refresh` rebuilds when a new action is added.
* Empty registry -> empty menu but stable group structure.
* Type-ahead filter (push / pop / clear).
* Headless-safe under a stub DPG.
"""
from __future__ import annotations

import sys
import types

import pytest

from pharos_engine.tool_router import ToolAction, ToolRouter
from pharos_engine.ui.hotkey_remap import HotkeyBinding, HotkeyMap


# ---------------------------------------------------------------------------
# Headless DPG stub (Z2 pattern)
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
        self.values: dict[str, object] = {}
        self.menu_items: list[dict] = []

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

    def menu_bar(self, *a, **kw):
        self._track("menu_bar", a, kw)
        return _StubCM()

    def menu(self, *a, **kw):
        self._track("menu", a, kw)
        return _StubCM()

    def add_menu_item(self, *a, **kw):
        self._track("add_menu_item", a, kw)
        self.menu_items.append(kw)

    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)

    def add_button(self, *a, **kw):
        self._track("add_button", a, kw)

    def add_separator(self, *a, **kw):
        self._track("add_separator", a, kw)

    def does_item_exist(self, tag, *a, **kw):
        return tag in self.items

    def delete_item(self, tag, *a, **kw):
        self._track("delete_item", (tag,), kw)
        if isinstance(tag, str):
            self.items.discard(tag)

    def get_item_children(self, tag, *a, **kw):
        return []

    def set_value(self, tag, value, *a, **kw):
        self._track("set_value", (tag, value), kw)
        self.values[tag] = value

    def configure_item(self, tag, *a, **kw):
        self._track("configure_item", (tag,), kw)


@pytest.fixture
def stub_dpg(monkeypatch):
    """Install a stub ``dearpygui.dearpygui`` module."""
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    for name in (
        "group", "child_window", "window",
        "menu_bar", "menu", "add_menu_item",
        "add_text", "add_button", "add_separator",
        "does_item_exist", "delete_item", "get_item_children",
        "set_value", "configure_item",
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
# Router / map factories
# ---------------------------------------------------------------------------


def _fake_router(rows: list[tuple[str, str, str]]) -> ToolRouter:
    """Build a ToolRouter from ``(action_id, label, category)`` tuples."""
    router = ToolRouter()
    for aid, label, cat in rows:
        router.register(ToolAction(
            action_id=aid,
            label=label,
            category=cat,
        ))
    return router


def _fake_map(rows: list[tuple[str, str]]) -> HotkeyMap:
    """Build a HotkeyMap from ``(combo, action_id)`` tuples."""
    m = HotkeyMap()
    for combo, aid in rows:
        m.add(HotkeyBinding(combo=combo, action_id=aid))
    return m


def _make_bar(**kwargs):
    from pharos_engine.ui.editor.notebook_menu_bar import NotebookMenuBar
    return NotebookMenuBar(**kwargs)


# ===========================================================================
# Construction
# ===========================================================================


class TestConstruction:
    def test_defaults(self):
        bar = _make_bar()
        assert bar.router is None
        assert bar.hotkey_map is None
        assert bar.dispatch_ctx == {}
        assert bar.active_menu is None

    def test_router_from_ctor(self):
        r = _fake_router([("editor.save", "Save", "file")])
        bar = _make_bar(router=r)
        assert bar.router is r

    def test_hotkey_map_from_ctor(self):
        r = _fake_router([("editor.save", "Save", "file")])
        m = _fake_map([("ctrl+s", "editor.save")])
        bar = _make_bar(router=r, hotkey_map=m)
        assert bar.hotkey_map is m

    def test_dispatch_ctx_from_ctor_is_copied(self):
        ctx = {"shell": object()}
        bar = _make_bar(dispatch_ctx=ctx)
        assert bar.dispatch_ctx == ctx
        assert bar.dispatch_ctx is not ctx  # defensive copy

    def test_rejects_non_dict_ctx(self):
        with pytest.raises(TypeError):
            _make_bar(dispatch_ctx="not-a-dict")

    def test_rejects_non_callable_on_dispatch(self):
        with pytest.raises(TypeError):
            _make_bar(on_dispatch="not-callable")


# ===========================================================================
# Menu order + glyphs
# ===========================================================================


class TestMenuOrder:
    def test_menu_order_is_canonical(self):
        from pharos_engine.ui.editor.notebook_menu_bar import MENU_ORDER
        assert MENU_ORDER == (
            "file", "edit", "view", "tool", "panel", "theme", "spawn", "help",
        )

    def test_category_glyphs_cover_menu_order(self):
        from pharos_engine.ui.editor.notebook_menu_bar import (
            CATEGORY_GLYPHS,
            MENU_ORDER,
        )
        for cat in MENU_ORDER:
            assert cat in CATEGORY_GLYPHS
            assert isinstance(CATEGORY_GLYPHS[cat], str)
            assert CATEGORY_GLYPHS[cat] != ""

    def test_diary_glyph_values(self):
        from pharos_engine.ui.editor.notebook_menu_bar import CATEGORY_GLYPHS
        assert CATEGORY_GLYPHS["file"] == "✎"
        assert CATEGORY_GLYPHS["edit"] == "✂"
        assert CATEGORY_GLYPHS["view"] == "◇"
        assert CATEGORY_GLYPHS["tool"] == "✧"
        assert CATEGORY_GLYPHS["panel"] == "▤"
        assert CATEGORY_GLYPHS["theme"] == "✿"
        assert CATEGORY_GLYPHS["spawn"] == "✱"
        assert CATEGORY_GLYPHS["help"] == "?"

    def test_group_display_title_prefixes_glyph(self):
        r = _fake_router([("editor.save", "Save", "file")])
        bar = _make_bar(router=r)
        file_group = next(g for g in bar.groups() if g.category == "file")
        assert file_group.display_title.startswith("✎")
        assert "File" in file_group.display_title


# ===========================================================================
# Editor __init__ registration
# ===========================================================================


class TestEditorRegistration:
    def test_lazy_import_via_editor_init(self):
        from pharos_engine.ui.editor import NotebookMenuBar
        bar = NotebookMenuBar()
        assert bar.router is None

    def test_all_contains_menu_bar_alphabetically(self):
        import pharos_engine.ui.editor as ed
        assert "NotebookMenuBar" in ed.__all__
        i_me = ed.__all__.index("NotebookMaterialEditor")
        i_mb = ed.__all__.index("NotebookMenuBar")
        i_ml = ed.__all__.index("NotebookMessageLog")
        assert i_me < i_mb < i_ml

    def test_lazy_map_contains_module_path(self):
        from pharos_engine.ui.editor import _LAZY_MAP
        assert _LAZY_MAP["NotebookMenuBar"] == ".notebook_menu_bar"


# ===========================================================================
# set_router populates menus
# ===========================================================================


class TestSetRouter:
    def test_set_router_populates_groups(self):
        bar = _make_bar()
        assert all(len(g) == 0 for g in bar.groups())
        r = _fake_router([
            ("editor.save", "Save", "file"),
            ("editor.undo", "Undo", "edit"),
        ])
        bar.set_router(r)
        file_group = next(g for g in bar.groups() if g.category == "file")
        edit_group = next(g for g in bar.groups() if g.category == "edit")
        assert len(file_group) == 1
        assert len(edit_group) == 1

    def test_set_router_rejects_none(self):
        bar = _make_bar()
        with pytest.raises(TypeError):
            bar.set_router(None)

    def test_set_router_rejects_missing_list_actions(self):
        bar = _make_bar()

        class _Bad:
            def dispatch(self, aid, ctx):
                return None
        with pytest.raises(TypeError):
            bar.set_router(_Bad())

    def test_set_router_rejects_missing_dispatch(self):
        bar = _make_bar()

        class _Bad:
            def list_actions(self):
                return []
        with pytest.raises(TypeError):
            bar.set_router(_Bad())


# ===========================================================================
# Items match router.list_by_category(cat)
# ===========================================================================


class TestCategoryPartition:
    def test_each_category_matches_router(self):
        r = _fake_router([
            ("editor.save", "Save", "file"),
            ("editor.open", "Open", "file"),
            ("editor.undo", "Undo", "edit"),
            ("view.zoom_in", "Zoom In", "view"),
            ("tool.pan", "Pan", "tool"),
            ("panel.close_all", "Close All", "panel"),
            ("theme.cycle", "Cycle", "theme"),
            ("spawn.rope", "Rope", "spawn"),
        ])
        bar = _make_bar(router=r)
        from pharos_engine.ui.editor.notebook_menu_bar import MENU_ORDER
        for cat in MENU_ORDER:
            if cat == "help":
                # Help has no direct actions in this fixture — skip.
                continue
            group = next(g for g in bar.groups() if g.category == cat)
            expected_ids = {a.action_id for a in r.list_by_category(cat)}
            got_ids = {i.action_id for i in group.items}
            # Every router row should be in the group.
            assert expected_ids <= got_ids, cat

    def test_out_of_order_registration_still_sorted_by_label(self):
        r = _fake_router([
            ("editor.zzzz", "Zebra", "file"),
            ("editor.aaaa", "Apple", "file"),
            ("editor.mmmm", "Middle", "file"),
        ])
        bar = _make_bar(router=r)
        file_group = next(g for g in bar.groups() if g.category == "file")
        labels = [i.label for i in file_group.items]
        assert labels == ["Apple", "Middle", "Zebra"]

    def test_extra_categories_go_to_extra_bucket(self):
        r = _fake_router([
            ("editor.save", "Save", "file"),
            ("editor.easter_x", "Feed", "easter"),
            ("editor.reset_layout", "Reset", "layout"),
        ])
        bar = _make_bar(router=r)
        extras = bar.extra_categories()
        assert "easter" in extras
        assert "layout" in extras

    def test_unknown_category_absent_from_canonical_groups(self):
        r = _fake_router([("editor.easter_x", "Feed", "easter")])
        bar = _make_bar(router=r)
        for group in bar.groups():
            for item in group.items:
                assert item.category != "easter"


# ===========================================================================
# Hotkey shortcut resolution
# ===========================================================================


class TestShortcutResolution:
    def test_shortcut_resolved_from_hotkey_map(self):
        r = _fake_router([("editor.save", "Save", "file")])
        m = _fake_map([("ctrl+s", "editor.save")])
        bar = _make_bar(router=r, hotkey_map=m)
        file_items = next(
            g.items for g in bar.groups() if g.category == "file"
        )
        assert file_items[0].shortcut == "Ctrl+S"

    def test_shortcut_blank_without_hotkey_map(self):
        r = _fake_router([("editor.save", "Save", "file")])
        bar = _make_bar(router=r)
        file_items = next(
            g.items for g in bar.groups() if g.category == "file"
        )
        assert file_items[0].shortcut == ""

    def test_multi_modifier_shortcut(self):
        r = _fake_router([("editor.save_project", "Save Project", "file")])
        m = _fake_map([("ctrl+shift+s", "editor.save_project")])
        bar = _make_bar(router=r, hotkey_map=m)
        items = next(g.items for g in bar.groups() if g.category == "file")
        assert items[0].shortcut == "Ctrl+Shift+S"

    def test_disabled_binding_skipped(self):
        r = _fake_router([("editor.save", "Save", "file")])
        m = HotkeyMap()
        m.add(HotkeyBinding(
            combo="ctrl+s", action_id="editor.save", enabled=False,
        ))
        bar = _make_bar(router=r, hotkey_map=m)
        items = next(g.items for g in bar.groups() if g.category == "file")
        assert items[0].shortcut == ""

    def test_display_string_includes_shortcut(self):
        r = _fake_router([("editor.save", "Save", "file")])
        m = _fake_map([("ctrl+s", "editor.save")])
        bar = _make_bar(router=r, hotkey_map=m)
        items = next(g.items for g in bar.groups() if g.category == "file")
        assert "Save" in items[0].display
        assert "Ctrl+S" in items[0].display

    def test_hotkey_map_none_clears(self):
        r = _fake_router([("editor.save", "Save", "file")])
        m = _fake_map([("ctrl+s", "editor.save")])
        bar = _make_bar(router=r, hotkey_map=m)
        bar.set_hotkey_map(None)
        items = next(g.items for g in bar.groups() if g.category == "file")
        assert items[0].shortcut == ""


# ===========================================================================
# Click dispatch
# ===========================================================================


class TestDispatch:
    def test_click_dispatches_via_router(self):
        seen: list[str] = []

        def _fb(ctx):
            seen.append("dispatched")
            return "ok"

        router = ToolRouter()
        router.register(ToolAction(
            action_id="editor.save",
            label="Save",
            python_fallback=_fb,
            category="file",
        ))
        bar = _make_bar(router=router)
        result = bar.dispatch("editor.save")
        assert result == "ok"
        assert seen == ["dispatched"]

    def test_dispatch_passes_ctx(self):
        seen: list[dict] = []

        def _fb(ctx):
            seen.append(dict(ctx))
            return None

        router = ToolRouter()
        router.register(ToolAction(
            action_id="editor.save",
            label="Save",
            python_fallback=_fb,
            category="file",
        ))
        sentinel = object()
        bar = _make_bar(
            router=router,
            dispatch_ctx={"shell": sentinel, "extra": 42},
        )
        bar.dispatch("editor.save")
        assert seen[0]["shell"] is sentinel
        assert seen[0]["extra"] == 42

    def test_dispatch_unknown_returns_none(self):
        r = _fake_router([("editor.save", "Save", "file")])
        bar = _make_bar(router=r)
        assert bar.dispatch("nope.does_not_exist") is None

    def test_dispatch_no_router_returns_none(self):
        bar = _make_bar()
        assert bar.dispatch("editor.save") is None

    def test_on_dispatch_callback_fires(self):
        seen: list[tuple[str, object]] = []

        def _fb(ctx):
            return "R"

        router = ToolRouter()
        router.register(ToolAction(
            action_id="editor.save",
            label="Save",
            python_fallback=_fb,
            category="file",
        ))
        bar = _make_bar(router=router)
        bar.on_dispatch(lambda aid, res: seen.append((aid, res)))
        bar.dispatch("editor.save")
        assert seen == [("editor.save", "R")]

    def test_dispatch_swallows_router_exceptions(self):
        def _fb(ctx):
            raise RuntimeError("boom")

        router = ToolRouter()
        router.register(ToolAction(
            action_id="editor.save",
            label="Save",
            python_fallback=_fb,
            category="file",
        ))
        bar = _make_bar(router=router)
        # Should not propagate.
        assert bar.dispatch("editor.save") is None


# ===========================================================================
# Refresh
# ===========================================================================


class TestRefresh:
    def test_refresh_rebuilds_when_action_added(self):
        r = _fake_router([("editor.save", "Save", "file")])
        bar = _make_bar(router=r)
        bar.build("root")
        # No change yet.
        assert bar.refresh() is False
        # Add a new action.
        r.register(ToolAction(
            action_id="editor.open",
            label="Open",
            category="file",
        ))
        assert bar.refresh() is True

    def test_refresh_noop_when_registry_unchanged(self):
        r = _fake_router([("editor.save", "Save", "file")])
        bar = _make_bar(router=r)
        bar.build("root")
        # Multiple no-op refreshes stay noops.
        for _ in range(3):
            assert bar.refresh() is False

    def test_refresh_after_unregister(self):
        r = _fake_router([
            ("editor.save", "Save", "file"),
            ("editor.open", "Open", "file"),
        ])
        bar = _make_bar(router=r)
        bar.build("root")
        r.unregister("editor.open")
        assert bar.refresh() is True

    def test_force_refresh_always_rebuilds(self):
        r = _fake_router([("editor.save", "Save", "file")])
        bar = _make_bar(router=r)
        bar.build("root")
        before_len = len(bar.call_log)
        bar.force_refresh()
        assert any(
            entry[0] == "force_refresh" for entry in bar.call_log
        )
        assert len(bar.call_log) > before_len


# ===========================================================================
# Empty registry
# ===========================================================================


class TestEmptyRegistry:
    def test_empty_router_yields_stable_groups(self):
        bar = _make_bar(router=ToolRouter())
        groups = bar.groups()
        from pharos_engine.ui.editor.notebook_menu_bar import MENU_ORDER
        # All canonical categories still present.
        cats = [g.category for g in groups]
        assert cats == list(MENU_ORDER)
        # But every group is empty.
        for g in groups:
            assert len(g) == 0

    def test_no_router_yields_stable_groups(self):
        bar = _make_bar()
        groups = bar.groups()
        assert all(len(g) == 0 for g in groups)

    def test_is_empty(self):
        bar = _make_bar(router=ToolRouter())
        assert bar.is_empty() is True

    def test_not_empty_after_registration(self):
        r = ToolRouter()
        r.register(ToolAction(
            action_id="editor.save", label="Save", category="file",
        ))
        bar = _make_bar(router=r)
        assert bar.is_empty() is False


# ===========================================================================
# Type-ahead search
# ===========================================================================


class TestTypeAhead:
    def _bar_with_file(self):
        r = _fake_router([
            ("editor.save", "Save", "file"),
            ("editor.save_project", "Save Project", "file"),
            ("editor.open", "Open Scene", "file"),
            ("editor.new", "New Scene", "file"),
        ])
        bar = _make_bar(router=r)
        bar.open_menu("file")
        return bar

    def test_type_ahead_filters(self):
        bar = self._bar_with_file()
        bar.push_type_ahead_char("s")
        visible = bar.items_for("file")
        labels = [i.label for i in visible]
        # "s" should match Save, Save Project, plus Open Scene / New Scene.
        assert "Save" in labels
        assert "Save Project" in labels

    def test_type_ahead_narrows(self):
        bar = self._bar_with_file()
        bar.push_type_ahead_char("s")
        bar.push_type_ahead_char("a")
        visible = bar.items_for("file")
        labels = [i.label for i in visible]
        assert "Save" in labels
        assert "Save Project" in labels
        # "sa" should NOT match Open Scene / New Scene.
        assert "Open Scene" not in labels
        assert "New Scene" not in labels

    def test_pop_type_ahead(self):
        bar = self._bar_with_file()
        bar.push_type_ahead_char("s")
        bar.push_type_ahead_char("a")
        bar.push_type_ahead_char("v")
        assert bar.get_type_ahead("file") == "sav"
        bar.pop_type_ahead_char()
        assert bar.get_type_ahead("file") == "sa"

    def test_clear_type_ahead(self):
        bar = self._bar_with_file()
        bar.push_type_ahead_char("s")
        bar.push_type_ahead_char("a")
        bar.clear_type_ahead()
        assert bar.get_type_ahead("file") == ""

    def test_open_new_menu_resets_type_ahead(self):
        bar = self._bar_with_file()
        bar.push_type_ahead_char("s")
        bar.open_menu("file")  # re-open
        assert bar.get_type_ahead("file") == ""

    def test_close_menu_clears_active(self):
        bar = self._bar_with_file()
        bar.push_type_ahead_char("x")
        bar.close_menu()
        assert bar.active_menu is None

    def test_push_without_active_menu_noop(self):
        bar = _make_bar()
        assert bar.push_type_ahead_char("x") == ""


# ===========================================================================
# Build + refresh under stub DPG
# ===========================================================================


class TestBuild:
    def test_build_headless_safe_without_dpg(self):
        r = _fake_router([("editor.save", "Save", "file")])
        bar = _make_bar(router=r)
        bar.build("root")  # no DPG installed
        assert any(entry[0] == "build" for entry in bar.call_log)

    def test_build_with_stub_dpg_emits_menu_calls(self, stub_dpg):
        r = _fake_router([
            ("editor.save", "Save", "file"),
            ("editor.undo", "Undo", "edit"),
        ])
        bar = _make_bar(router=r)
        bar.build("root")
        assert "menu_bar" in stub_dpg.calls
        assert "menu" in stub_dpg.calls
        assert "add_menu_item" in stub_dpg.calls

    def test_build_menu_items_have_click_callback(self, stub_dpg):
        r = _fake_router([("editor.save", "Save", "file")])
        bar = _make_bar(router=r)
        bar.build("root")
        item = stub_dpg.menu_items[0]
        assert "callback" in item
        assert callable(item["callback"])

    def test_menu_item_click_dispatches(self, stub_dpg):
        seen: list[str] = []
        router = ToolRouter()
        router.register(ToolAction(
            action_id="editor.save",
            label="Save",
            python_fallback=lambda ctx: seen.append("saved"),
            category="file",
        ))
        bar = _make_bar(router=router)
        bar.build("root")
        # Trigger the recorded callback like DPG would on click.
        cb = stub_dpg.menu_items[0]["callback"]
        cb()
        assert seen == ["saved"]


# ===========================================================================
# Category count
# ===========================================================================


class TestCategoryCount:
    def test_eight_canonical_categories(self):
        from pharos_engine.ui.editor.notebook_menu_bar import MENU_ORDER
        assert len(MENU_ORDER) == 8

    def test_groups_return_eight_entries(self):
        r = _fake_router([("editor.save", "Save", "file")])
        bar = _make_bar(router=r)
        assert len(bar.groups()) == 8


# ===========================================================================
# Format shortcut helper
# ===========================================================================


class TestFormatShortcut:
    def test_none_returns_empty(self):
        from pharos_engine.ui.editor.notebook_menu_bar import format_shortcut
        assert format_shortcut(None) == ""

    def test_empty_returns_empty(self):
        from pharos_engine.ui.editor.notebook_menu_bar import format_shortcut
        assert format_shortcut("") == ""

    def test_single_key(self):
        from pharos_engine.ui.editor.notebook_menu_bar import format_shortcut
        assert format_shortcut("ctrl+s") == "Ctrl+S"

    def test_multi_chord(self):
        from pharos_engine.ui.editor.notebook_menu_bar import format_shortcut
        assert format_shortcut("ctrl+x ctrl+s") == "Ctrl+X Ctrl+S"

    def test_function_key(self):
        from pharos_engine.ui.editor.notebook_menu_bar import format_shortcut
        assert format_shortcut("f1") == "F1"


# ===========================================================================
# Real REGISTRY integration smoke test
# ===========================================================================


class TestRealRegistry:
    def test_real_registry_populates_every_menu(self):
        from pharos_engine.tool_router import REGISTRY
        bar = _make_bar(router=REGISTRY)
        groups = {g.category: g for g in bar.groups()}
        # Every canonical category with real actions should be populated.
        assert len(groups["file"]) > 0
        assert len(groups["edit"]) > 0
        assert len(groups["view"]) > 0
        assert len(groups["tool"]) > 0
        assert len(groups["panel"]) > 0
        assert len(groups["theme"]) > 0
        assert len(groups["spawn"]) > 0
        # "help" comes from the editor.help alias.
        assert len(groups["help"]) >= 1

    def test_help_alias_includes_editor_help(self):
        from pharos_engine.tool_router import REGISTRY
        bar = _make_bar(router=REGISTRY)
        help_group = next(g for g in bar.groups() if g.category == "help")
        assert any(i.action_id == "editor.help" for i in help_group.items)
