"""Tests for :class:`NotebookHotkeyHelp` (BB7).

Covers:

* Construction + defaults + editor ``__init__`` lazy hook.
* :meth:`set_hotkey_map` populates rows.
* Category filter buttons hide / show rows.
* Search box substring filter (matches combo OR action_id).
* Reset button reloads :func:`default_hotkey_map`.
* Preset dropdown swaps the visible map source.
* Rebind flow fires the :meth:`on_binding_changed` subscriber.
* Unknown action_id renders as ``"(unknown action)"``.
* Empty-state placeholder text when the map has no bindings.
* Headless-safe under a stub DPG.
"""
from __future__ import annotations

import sys
import types

import pytest

from pharos_engine.tool_router import REGISTRY, ToolAction, ToolRouter
from pharos_engine.ui.hotkey_remap import (
    HotkeyBinding,
    HotkeyMap,
    default_hotkey_map,
)


# ---------------------------------------------------------------------------
# Headless DPG stub (mirrors the Z1 / Z2 test rigs — every DPG call
# funnelled through :func:`_safe_dpg` on the panel side).
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

    def add_combo(self, *a, **kw):
        self._track("add_combo", a, kw)

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
        "add_text", "add_button", "add_input_text", "add_combo",
        "add_separator",
        "does_item_exist", "delete_item", "get_item_children",
        "set_value", "configure_item",
    ):
        setattr(mod, name, getattr(stub, name))

    def _fallback(name: str):
        def _noop(*a, **kw):
            stub.calls.setdefault(name, []).append((a, kw))
        return _noop
    mod.__getattr__ = _fallback

    # Opt into the "live" gate — the panel funnels every DPG call
    # through _safe_dpg() which checks for __slappy_stub__.
    mod.__slappy_stub__ = True

    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


# ---------------------------------------------------------------------------
# Panel factory helpers
# ---------------------------------------------------------------------------


def _make_map(*rows: tuple[str, str, str]) -> HotkeyMap:
    """Build a :class:`HotkeyMap` from ``(combo, action_id, category?)`` tuples."""
    m = HotkeyMap()
    for row in rows:
        combo, action_id = row[0], row[1]
        m.add(HotkeyBinding(
            combo=combo, action_id=action_id, source="user",
        ))
    return m


def _make_panel(**kwargs):
    from pharos_engine.ui.editor.notebook_hotkey_help import NotebookHotkeyHelp
    return NotebookHotkeyHelp(**kwargs)


def _fake_router(action_map: dict[str, tuple[str, str]]) -> ToolRouter:
    """Build a ToolRouter pre-populated with the given ``{aid: (label, cat)}``."""
    router = ToolRouter()
    for aid, (label, category) in action_map.items():
        router.register(ToolAction(
            action_id=aid,
            label=label,
            category=category,
        ))
    return router


# ===========================================================================
# Construction
# ===========================================================================


class TestConstruction:
    def test_defaults_load_default_hotkey_map(self):
        panel = _make_panel()
        assert len(panel.hotkey_map) > 0
        assert panel.category == "All"
        assert panel.search == ""
        assert panel.preset == "Default"

    def test_explicit_map_overrides_default(self):
        m = _make_map(("ctrl+q", "editor.save"))
        panel = _make_panel(hotkey_map=m)
        assert panel.hotkey_map is m
        assert len(panel.hotkey_map) == 1

    def test_rejects_bad_hotkey_map_type(self):
        with pytest.raises(TypeError):
            _make_panel(hotkey_map="not-a-map")

    def test_rejects_bad_on_binding_changed(self):
        with pytest.raises((TypeError, ValueError)):
            _make_panel(on_binding_changed="not-callable")

    def test_rejects_bad_initial_category(self):
        with pytest.raises(ValueError):
            _make_panel(initial_category="BogusCategory")

    def test_rejects_empty_initial_category(self):
        with pytest.raises((TypeError, ValueError)):
            _make_panel(initial_category="")

    def test_title_constant(self):
        from pharos_engine.ui.editor.notebook_hotkey_help import (
            NotebookHotkeyHelp,
        )
        assert NotebookHotkeyHelp.TITLE == "Hotkey Help"

    def test_min_size_constants(self):
        from pharos_engine.ui.editor.notebook_hotkey_help import (
            NotebookHotkeyHelp,
        )
        assert NotebookHotkeyHelp.MIN_WIDTH >= 200
        assert NotebookHotkeyHelp.MIN_HEIGHT >= 200


# ===========================================================================
# Editor __init__ registration
# ===========================================================================


class TestEditorRegistration:
    def test_lazy_import_via_editor_init(self):
        from pharos_engine.ui.editor import NotebookHotkeyHelp
        panel = NotebookHotkeyHelp(hotkey_map=HotkeyMap())
        assert panel.hotkey_map is not None

    def test_all_contains_hotkey_help_alphabetically(self):
        import pharos_engine.ui.editor as ed
        assert "NotebookHotkeyHelp" in ed.__all__
        # __all__ ordering: NotebookHotkeyHelp between NotebookDiaryPage
        # and NotebookInspector.
        i_dp = ed.__all__.index("NotebookDiaryPage")
        i_hh = ed.__all__.index("NotebookHotkeyHelp")
        i_in = ed.__all__.index("NotebookInspector")
        assert i_dp < i_hh < i_in

    def test_lazy_map_contains_module_path(self):
        from pharos_engine.ui.editor import _LAZY_MAP
        assert _LAZY_MAP["NotebookHotkeyHelp"] == ".notebook_hotkey_help"


# ===========================================================================
# set_hotkey_map
# ===========================================================================


class TestSetHotkeyMap:
    def test_swaps_source_map(self):
        panel = _make_panel(hotkey_map=HotkeyMap())
        assert len(panel.hotkey_map) == 0
        m = _make_map(
            ("ctrl+s", "editor.save"),
            ("ctrl+z", "editor.undo"),
        )
        panel.set_hotkey_map(m)
        assert panel.hotkey_map is m
        assert len(panel.hotkey_map) == 2

    def test_rebuilds_rows(self):
        panel = _make_panel(hotkey_map=HotkeyMap())
        assert panel.visible_count() == 0
        panel.set_hotkey_map(_make_map(("ctrl+s", "editor.save")))
        assert panel.visible_count() == 1

    def test_rejects_bad_type(self):
        panel = _make_panel(hotkey_map=HotkeyMap())
        with pytest.raises(TypeError):
            panel.set_hotkey_map({"not": "a map"})

    def test_logs_call(self):
        panel = _make_panel(hotkey_map=HotkeyMap())
        panel.set_hotkey_map(_make_map(("ctrl+s", "editor.save")))
        assert any(
            e[0] == "set_hotkey_map" for e in panel.call_log
        )


# ===========================================================================
# Category filter
# ===========================================================================


class TestCategoryFilter:
    def _panel_with_mixed_categories(self):
        m = _make_map(
            ("ctrl+s", "editor.save"),         # file
            ("ctrl+z", "editor.undo"),         # edit
            ("ctrl+shift+t", "editor.cycle_theme"),  # theme
        )
        return _make_panel(hotkey_map=m, router=REGISTRY)

    def test_all_shows_every_row(self):
        panel = self._panel_with_mixed_categories()
        assert panel.category == "All"
        assert panel.visible_count() == 3

    def test_filter_by_file_hides_others(self):
        panel = self._panel_with_mixed_categories()
        panel.set_category("File")
        rows = panel.visible_rows()
        assert len(rows) == 1
        assert rows[0].action_id == "editor.save"

    def test_filter_by_edit_hides_others(self):
        panel = self._panel_with_mixed_categories()
        panel.set_category("Edit")
        assert panel.visible_count() == 1

    def test_filter_by_theme_shows_theme_row(self):
        panel = self._panel_with_mixed_categories()
        panel.set_category("Theme")
        rows = panel.visible_rows()
        assert len(rows) == 1
        assert rows[0].action_id == "editor.cycle_theme"

    def test_category_options_include_all_required(self):
        from pharos_engine.ui.editor.notebook_hotkey_help import (
            CATEGORY_OPTIONS,
        )
        assert CATEGORY_OPTIONS[0] == "All"
        for cat in ("File", "Edit", "View", "Tool", "Panel", "Theme", "Spawn"):
            assert cat in CATEGORY_OPTIONS

    def test_set_category_rejects_unknown(self):
        panel = _make_panel(hotkey_map=HotkeyMap())
        with pytest.raises(ValueError):
            panel.set_category("Bogus")

    def test_set_category_rejects_empty(self):
        panel = _make_panel(hotkey_map=HotkeyMap())
        with pytest.raises((TypeError, ValueError)):
            panel.set_category("")


# ===========================================================================
# Search filter
# ===========================================================================


class TestSearch:
    def test_search_by_action_id(self):
        m = _make_map(
            ("ctrl+s", "editor.save"),
            ("ctrl+z", "editor.undo"),
        )
        panel = _make_panel(hotkey_map=m, router=REGISTRY)
        panel.set_search("save")
        assert panel.visible_count() == 1
        assert panel.visible_rows()[0].action_id == "editor.save"

    def test_search_by_combo(self):
        m = _make_map(
            ("ctrl+s", "editor.save"),
            ("ctrl+z", "editor.undo"),
        )
        panel = _make_panel(hotkey_map=m, router=REGISTRY)
        panel.set_search("ctrl+z")
        assert panel.visible_count() == 1

    def test_search_is_case_insensitive(self):
        m = _make_map(("ctrl+s", "editor.save"))
        panel = _make_panel(hotkey_map=m, router=REGISTRY)
        panel.set_search("SAVE")
        assert panel.visible_count() == 1

    def test_empty_search_shows_all(self):
        m = _make_map(
            ("ctrl+s", "editor.save"),
            ("ctrl+z", "editor.undo"),
        )
        panel = _make_panel(hotkey_map=m, router=REGISTRY)
        panel.set_search("")
        assert panel.visible_count() == 2

    def test_search_rejects_non_string(self):
        panel = _make_panel(hotkey_map=HotkeyMap())
        with pytest.raises(TypeError):
            panel.set_search(123)  # type: ignore[arg-type]

    def test_search_combined_with_category(self):
        m = _make_map(
            ("ctrl+s", "editor.save"),  # file
            ("ctrl+z", "editor.undo"),  # edit
        )
        panel = _make_panel(hotkey_map=m, router=REGISTRY)
        panel.set_category("File")
        panel.set_search("undo")
        # 'undo' action is in the Edit category — File+undo yields nothing.
        assert panel.visible_count() == 0


# ===========================================================================
# Preset dropdown
# ===========================================================================


class TestPreset:
    def test_default_preset_swaps_source_map(self):
        panel = _make_panel(hotkey_map=HotkeyMap())
        panel.set_preset("Default")
        # The default hotkey map has many bindings — we should now see them.
        assert len(panel.hotkey_map) > 0
        assert panel.preset == "Default"

    def test_vim_preset_swaps_source_map(self):
        panel = _make_panel(hotkey_map=HotkeyMap())
        panel.set_preset("Vim")
        assert panel.preset == "Vim"
        # Vim preset adds hjkl bindings on top of default.
        combos = panel.hotkey_map.combos()
        assert "h" in combos or "j" in combos

    def test_emacs_preset_swaps_source_map(self):
        panel = _make_panel(hotkey_map=HotkeyMap())
        panel.set_preset("Emacs")
        assert panel.preset == "Emacs"

    def test_preset_options_are_three(self):
        from pharos_engine.ui.editor.notebook_hotkey_help import PRESET_OPTIONS
        assert PRESET_OPTIONS == ("Default", "Vim", "Emacs")

    def test_set_preset_rejects_unknown(self):
        panel = _make_panel(hotkey_map=HotkeyMap())
        with pytest.raises(ValueError):
            panel.set_preset("Bogus")


# ===========================================================================
# Reset + Reload
# ===========================================================================


class TestResetReload:
    def test_reset_reloads_default_map(self):
        panel = _make_panel(hotkey_map=HotkeyMap())
        assert len(panel.hotkey_map) == 0
        panel.reset_to_default()
        # After reset, the default_hotkey_map should be loaded.
        assert len(panel.hotkey_map) > 0
        assert panel.preset == "Default"

    def test_reset_logs_call(self):
        panel = _make_panel(hotkey_map=HotkeyMap())
        panel.reset_to_default()
        assert any(e[0] == "reset_to_default" for e in panel.call_log)

    def test_reload_re_applies_current_preset(self):
        panel = _make_panel(hotkey_map=HotkeyMap())
        panel.set_preset("Vim")
        n_before = len(panel.hotkey_map)
        panel.reload()
        assert len(panel.hotkey_map) == n_before
        assert panel.preset == "Vim"

    def test_reset_matches_default_hotkey_map_size(self):
        panel = _make_panel(hotkey_map=HotkeyMap())
        panel.reset_to_default()
        assert len(panel.hotkey_map) == len(default_hotkey_map())


# ===========================================================================
# Rebind flow
# ===========================================================================


class TestRebind:
    def test_start_rebind_records_combo(self):
        m = _make_map(("ctrl+s", "editor.save"))
        panel = _make_panel(hotkey_map=m)
        assert panel.pending_rebind is None
        assert panel.start_rebind("ctrl+s") is True
        assert panel.pending_rebind == "ctrl+s"

    def test_start_rebind_unknown_combo_returns_false(self):
        m = _make_map(("ctrl+s", "editor.save"))
        panel = _make_panel(hotkey_map=m)
        assert panel.start_rebind("ctrl+q") is False
        assert panel.pending_rebind is None

    def test_capture_key_commits_new_binding(self):
        received: list[HotkeyBinding] = []
        m = _make_map(("ctrl+s", "editor.save"))
        panel = _make_panel(
            hotkey_map=m, on_binding_changed=received.append,
        )
        panel.start_rebind("ctrl+s")
        new_binding = panel.capture_key("ctrl+shift+s")
        assert new_binding is not None
        assert new_binding.combo == "ctrl+shift+s"
        assert new_binding.action_id == "editor.save"
        assert received == [new_binding]

    def test_capture_key_no_pending_returns_none(self):
        panel = _make_panel(hotkey_map=HotkeyMap())
        assert panel.capture_key("ctrl+q") is None

    def test_commit_rebind_swaps_combo(self):
        m = _make_map(("ctrl+s", "editor.save"))
        panel = _make_panel(hotkey_map=m)
        new_binding = panel.commit_rebind("ctrl+s", "ctrl+shift+s")
        assert new_binding is not None
        assert "ctrl+shift+s" in panel.hotkey_map
        assert "ctrl+s" not in panel.hotkey_map

    def test_commit_rebind_fires_subscriber(self):
        received: list[HotkeyBinding] = []
        m = _make_map(("ctrl+s", "editor.save"))
        panel = _make_panel(
            hotkey_map=m, on_binding_changed=received.append,
        )
        panel.commit_rebind("ctrl+s", "ctrl+shift+s")
        assert len(received) == 1
        assert received[0].combo == "ctrl+shift+s"

    def test_commit_rebind_unknown_old_returns_none(self):
        m = _make_map(("ctrl+s", "editor.save"))
        panel = _make_panel(hotkey_map=m)
        assert panel.commit_rebind("ctrl+q", "ctrl+shift+s") is None

    def test_cancel_rebind_clears_pending(self):
        m = _make_map(("ctrl+s", "editor.save"))
        panel = _make_panel(hotkey_map=m)
        panel.start_rebind("ctrl+s")
        assert panel.pending_rebind is not None
        panel.cancel_rebind()
        assert panel.pending_rebind is None

    def test_on_binding_changed_subscriber_can_be_swapped(self):
        m = _make_map(("ctrl+s", "editor.save"))
        panel = _make_panel(hotkey_map=m)
        events: list[HotkeyBinding] = []
        panel.on_binding_changed(events.append)
        panel.commit_rebind("ctrl+s", "ctrl+shift+s")
        assert len(events) == 1

    def test_subscriber_exception_swallowed(self):
        m = _make_map(("ctrl+s", "editor.save"))

        def boom(_binding: HotkeyBinding) -> None:
            raise RuntimeError("subscriber blew up")

        panel = _make_panel(hotkey_map=m, on_binding_changed=boom)
        new_binding = panel.commit_rebind("ctrl+s", "ctrl+shift+s")
        # Rebind still succeeds even though the subscriber crashed.
        assert new_binding is not None

    def test_commit_rebind_preserves_action_id(self):
        m = _make_map(("ctrl+s", "editor.save"))
        panel = _make_panel(hotkey_map=m)
        panel.commit_rebind("ctrl+s", "f9")
        binding = panel.hotkey_map.get("f9")
        assert binding is not None
        assert binding.action_id == "editor.save"

    def test_commit_rebind_marks_source_as_user(self):
        m = HotkeyMap([HotkeyBinding(
            combo="ctrl+s", action_id="editor.save", source="default",
        )])
        panel = _make_panel(hotkey_map=m)
        new_binding = panel.commit_rebind("ctrl+s", "ctrl+shift+s")
        assert new_binding is not None
        assert new_binding.source == "user"


# ===========================================================================
# Unknown action_id
# ===========================================================================


class TestUnknownAction:
    def test_unknown_action_renders_placeholder(self):
        m = _make_map(("ctrl+q", "some.nonexistent.action"))
        panel = _make_panel(hotkey_map=m, router=REGISTRY)
        rows = panel.rows()
        assert len(rows) == 1
        assert rows[0].label == "(unknown action)"
        assert rows[0].known is False

    def test_unknown_action_still_visible_in_all_filter(self):
        m = _make_map(("ctrl+q", "some.nonexistent.action"))
        panel = _make_panel(hotkey_map=m, router=REGISTRY)
        # "All" category shows every row including unknowns.
        assert panel.visible_count() == 1

    def test_unknown_action_category_defaults_to_misc(self):
        m = _make_map(("ctrl+q", "some.nonexistent.action"))
        panel = _make_panel(hotkey_map=m, router=REGISTRY)
        rows = panel.rows()
        assert rows[0].category == "misc"


# ===========================================================================
# Router binding
# ===========================================================================


class TestRouter:
    def test_set_router_rebinds_metadata(self):
        m = _make_map(("ctrl+t", "custom.thing"))
        panel = _make_panel(hotkey_map=m, router=REGISTRY)
        # Under the real registry, "custom.thing" is unknown.
        assert panel.rows()[0].label == "(unknown action)"
        # Swap in a fake router that knows about it.
        fake = _fake_router({"custom.thing": ("Custom Thing", "tool")})
        panel.set_router(fake)
        rows = panel.rows()
        assert rows[0].label == "Custom Thing"
        assert rows[0].category == "tool"
        assert rows[0].known is True

    def test_set_router_rejects_none(self):
        panel = _make_panel(hotkey_map=HotkeyMap())
        with pytest.raises(TypeError):
            panel.set_router(None)

    def test_set_router_rejects_no_get_method(self):
        panel = _make_panel(hotkey_map=HotkeyMap())
        with pytest.raises(TypeError):
            panel.set_router(object())

    def test_lazy_router_resolves_registry(self):
        m = _make_map(("ctrl+s", "editor.save"))
        panel = _make_panel(hotkey_map=m)  # No router given.
        # Should still resolve editor.save via the module-level REGISTRY.
        rows = panel.rows()
        assert rows[0].known is True
        assert rows[0].label == "Save"


# ===========================================================================
# Empty state
# ===========================================================================


class TestEmptyState:
    def test_empty_map_reports_zero_visible(self):
        panel = _make_panel(hotkey_map=HotkeyMap())
        assert panel.is_empty()
        assert panel.visible_count() == 0

    def test_empty_state_renders_placeholder_text(self, stub_dpg):
        panel = _make_panel(hotkey_map=HotkeyMap())
        panel.build("parent")
        # Every add_text call captured — look for the empty placeholder.
        texts = [args[0] for (args, _kw) in stub_dpg.calls.get("add_text", [])]
        assert any("No hotkeys registered" in str(t) for t in texts)


# ===========================================================================
# Build under stub DPG
# ===========================================================================


class TestBuild:
    def test_builds_without_crashing_headless(self):
        panel = _make_panel()
        # Without any DPG stubbed, build() still marks the panel built.
        panel.build("parent")
        assert panel._built is True

    def test_builds_with_stub_dpg(self, stub_dpg):
        panel = _make_panel()
        panel.build("parent")
        # Preset combo should have been added.
        combos = stub_dpg.calls.get("add_combo", [])
        assert len(combos) >= 1

    def test_builds_status_text(self, stub_dpg):
        panel = _make_panel()
        panel.build("parent")
        # Status text is added — look for the count-marker pattern.
        texts = [args[0] for (args, _kw) in stub_dpg.calls.get("add_text", [])]
        assert any("bindings" in str(t) for t in texts)

    def test_build_adds_category_buttons(self, stub_dpg):
        panel = _make_panel()
        panel.build("parent")
        # Should register 8 buttons for CATEGORY_OPTIONS + preset chrome.
        buttons = stub_dpg.calls.get("add_button", [])
        # Reset + Reload + 8 category buttons + N change buttons.
        assert len(buttons) >= 10

    def test_build_search_input(self, stub_dpg):
        panel = _make_panel()
        panel.build("parent")
        assert len(stub_dpg.calls.get("add_input_text", [])) >= 1

    def test_destroy_flips_built(self, stub_dpg):
        panel = _make_panel()
        panel.build("parent")
        assert panel._built is True
        panel.destroy()
        assert panel._built is False


# ===========================================================================
# Keycap rendering
# ===========================================================================


class TestKeycaps:
    def test_render_simple_combo(self):
        from pharos_engine.ui.editor.notebook_hotkey_help import render_keycaps
        assert render_keycaps("ctrl+s") == "[Ctrl] + [S]"

    def test_render_multi_modifier(self):
        from pharos_engine.ui.editor.notebook_hotkey_help import render_keycaps
        out = render_keycaps("ctrl+shift+t")
        assert "[Ctrl]" in out and "[Shift]" in out and "[T]" in out

    def test_render_function_key(self):
        from pharos_engine.ui.editor.notebook_hotkey_help import render_keycaps
        assert render_keycaps("f5") == "[F5]"

    def test_render_multi_chord(self):
        from pharos_engine.ui.editor.notebook_hotkey_help import render_keycaps
        out = render_keycaps("ctrl+x ctrl+s")
        # Chord separator: comma-space between the two chords.
        assert "," in out
        assert out.count("[Ctrl]") == 2

    def test_empty_combo_returns_empty(self):
        from pharos_engine.ui.editor.notebook_hotkey_help import render_keycaps
        assert render_keycaps("") == ""

    def test_non_string_returns_empty(self):
        from pharos_engine.ui.editor.notebook_hotkey_help import render_keycaps
        assert render_keycaps(None) == ""  # type: ignore[arg-type]

    def test_row_keycaps_reflects_binding(self):
        m = _make_map(("ctrl+s", "editor.save"))
        panel = _make_panel(hotkey_map=m)
        rows = panel.rows()
        assert "[Ctrl]" in rows[0].keycaps
        assert "[S]" in rows[0].keycaps


# ===========================================================================
# Grouped display
# ===========================================================================


class TestGrouping:
    def test_groups_by_category(self):
        m = _make_map(
            ("ctrl+s", "editor.save"),  # file
            ("ctrl+z", "editor.undo"),  # edit
            ("ctrl+shift+t", "editor.cycle_theme"),  # theme
        )
        panel = _make_panel(hotkey_map=m, router=REGISTRY)
        groups = panel.grouped_visible_rows()
        cats = {cat for cat, _rows in groups}
        assert "file" in cats
        assert "edit" in cats
        assert "theme" in cats

    def test_grouping_respects_filter(self):
        m = _make_map(
            ("ctrl+s", "editor.save"),  # file
            ("ctrl+z", "editor.undo"),  # edit
        )
        panel = _make_panel(hotkey_map=m, router=REGISTRY)
        panel.set_category("File")
        groups = panel.grouped_visible_rows()
        cats = {cat for cat, _rows in groups}
        assert cats == {"file"}
