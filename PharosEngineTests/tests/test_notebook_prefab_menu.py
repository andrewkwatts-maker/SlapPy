"""Tests for :class:`NotebookPrefabMenu` (Z2 sprint).

Covers:

* Construction + defaults + auto-bootstrapped baked library.
* Category filter reduces visible-card count.
* Search box filters by name + category.
* :meth:`set_library` swap rebuilds the grid.
* Click card invokes :attr:`on_spawn` with the prefab name.
* Right-click Spawn / Spawn N / Copy Name / View YAML flows.
* Empty library shows the empty-state placeholder.
* Panel builds without crashing under a stub DPG.
* Lazy registration in the editor ``__init__`` alphabetically ordered.
"""
from __future__ import annotations

import sys
import types

import pytest

from pharos_engine.prefabs import Prefab, PrefabLibrary


# ---------------------------------------------------------------------------
# Headless DPG stub (mirrors the Z1 test rig — every DPG call is guarded).
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
        self.clipboard: str | None = None

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

    def set_clipboard_text(self, text, *a, **kw):
        self._track("set_clipboard_text", (text,), kw)
        self.clipboard = text


@pytest.fixture
def stub_dpg(monkeypatch):
    """Install a stub ``dearpygui.dearpygui`` module."""
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    for name in (
        "group", "child_window", "window",
        "add_text", "add_button", "add_input_text", "add_combo",
        "add_separator",
        "does_item_exist", "delete_item", "set_clipboard_text",
    ):
        setattr(mod, name, getattr(stub, name))

    def _fallback(name: str):
        def _noop(*a, **kw):
            stub.calls.setdefault(name, []).append((a, kw))
        return _noop
    mod.__getattr__ = _fallback

    # Test-side context probe: stub DPG opts into the "live" gate.
    mod.__slappy_stub__ = True

    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


# ---------------------------------------------------------------------------
# Prefab library helpers
# ---------------------------------------------------------------------------


def _make_prefab(name: str, category: str = "props", kind: str = "circle") -> Prefab:
    body_spec: dict = {"kind": kind}
    if kind == "circle":
        body_spec["radius"] = 1.0
    elif kind == "rope":
        body_spec["node_count"] = 3
        body_spec["total_length"] = 2.0
    return Prefab(
        name=name,
        category=category,
        body_spec=body_spec,
    )


def _make_library(*prefabs: Prefab) -> PrefabLibrary:
    lib = PrefabLibrary()
    for p in prefabs:
        lib.register(p)
    return lib


def _make_menu(**kwargs):
    from pharos_editor.ui.editor.notebook_prefab_menu import NotebookPrefabMenu

    return NotebookPrefabMenu(**kwargs)


# ===========================================================================
# Construction
# ===========================================================================


class TestConstruction:
    def test_defaults_bootstrap_baked_library(self):
        menu = _make_menu()
        # The baked directory ships 6 prefabs — the bootstrap loader
        # should have picked them up (plus any user overlay).
        assert len(menu.library) >= 6
        assert menu.category == "All"
        assert menu.search == ""

    def test_explicit_empty_library(self):
        lib = PrefabLibrary()
        menu = _make_menu(library=lib)
        assert menu.is_empty()
        assert menu.visible_count() == 0

    def test_rejects_bad_library_type(self):
        with pytest.raises(TypeError):
            _make_menu(library="not-a-library")

    def test_rejects_bad_on_spawn(self):
        lib = _make_library(_make_prefab("a"))
        with pytest.raises((TypeError, ValueError)):
            _make_menu(library=lib, on_spawn="not-callable")

    def test_title_constant(self):
        from pharos_editor.ui.editor.notebook_prefab_menu import (
            NotebookPrefabMenu,
        )
        assert NotebookPrefabMenu.TITLE == "Prefab Library"

    def test_min_size_constants(self):
        from pharos_editor.ui.editor.notebook_prefab_menu import (
            NotebookPrefabMenu,
        )
        assert NotebookPrefabMenu.MIN_WIDTH >= 200
        assert NotebookPrefabMenu.MIN_HEIGHT >= 200


# ===========================================================================
# Category filter
# ===========================================================================


class TestCategoryFilter:
    def test_all_category_shows_everything(self):
        lib = _make_library(
            _make_prefab("crate", "props"),
            _make_prefab("hero", "characters"),
            _make_prefab("car", "vehicles"),
        )
        menu = _make_menu(library=lib)
        assert menu.visible_count() == 3

    def test_category_filter_reduces_visible_count(self):
        lib = _make_library(
            _make_prefab("crate", "props"),
            _make_prefab("barrel", "props"),
            _make_prefab("hero", "characters"),
        )
        menu = _make_menu(library=lib)
        assert menu.visible_count() == 3
        menu.set_category("Props")
        assert menu.visible_count() == 2

    def test_category_options_include_all_five_plus_all(self):
        from pharos_editor.ui.editor.notebook_prefab_menu import (
            CATEGORY_OPTIONS,
        )
        assert CATEGORY_OPTIONS[0] == "All"
        assert "Props" in CATEGORY_OPTIONS
        assert "Characters" in CATEGORY_OPTIONS
        assert "Vehicles" in CATEGORY_OPTIONS
        assert "Particles" in CATEGORY_OPTIONS
        assert "Structural" in CATEGORY_OPTIONS

    def test_set_category_rejects_unknown(self):
        menu = _make_menu(library=PrefabLibrary())
        with pytest.raises(ValueError):
            menu.set_category("BogusCategory")

    def test_set_category_rejects_empty(self):
        menu = _make_menu(library=PrefabLibrary())
        with pytest.raises((TypeError, ValueError)):
            menu.set_category("")


# ===========================================================================
# Search box
# ===========================================================================


class TestSearch:
    def test_search_filters_by_name(self):
        lib = _make_library(
            _make_prefab("crate", "props"),
            _make_prefab("barrel", "props"),
            _make_prefab("hero", "characters"),
        )
        menu = _make_menu(library=lib)
        menu.set_search("crate")
        assert menu.visible_count() == 1
        assert menu.visible_prefabs()[0].name == "crate"

    def test_search_is_case_insensitive(self):
        lib = _make_library(_make_prefab("Crate", "props"))
        menu = _make_menu(library=lib)
        menu.set_search("CRATE")
        assert menu.visible_count() == 1

    def test_search_matches_category_field(self):
        lib = _make_library(
            _make_prefab("thing", "vehicles"),
        )
        menu = _make_menu(library=lib)
        menu.set_search("vehic")
        assert menu.visible_count() == 1

    def test_search_empty_string_shows_all(self):
        lib = _make_library(_make_prefab("a"), _make_prefab("b"))
        menu = _make_menu(library=lib)
        menu.set_search("")
        assert menu.visible_count() == 2

    def test_search_rejects_non_string(self):
        menu = _make_menu(library=PrefabLibrary())
        with pytest.raises(TypeError):
            menu.set_search(123)  # type: ignore[arg-type]

    def test_search_combined_with_category(self):
        lib = _make_library(
            _make_prefab("crate", "props"),
            _make_prefab("hero", "characters"),
        )
        menu = _make_menu(library=lib)
        menu.set_category("Props")
        menu.set_search("hero")
        # 'hero' is not in Props, so nothing should match.
        assert menu.visible_count() == 0


# ===========================================================================
# set_library
# ===========================================================================


class TestSetLibrary:
    def test_set_library_swaps_in_new_library(self):
        lib_a = _make_library(_make_prefab("a"))
        lib_b = _make_library(_make_prefab("b1"), _make_prefab("b2"))
        menu = _make_menu(library=lib_a)
        assert menu.visible_count() == 1
        menu.set_library(lib_b)
        assert menu.library is lib_b
        assert menu.visible_count() == 2

    def test_set_library_resets_filter_state(self):
        lib_a = _make_library(_make_prefab("a", "props"))
        lib_b = _make_library(_make_prefab("b", "characters"))
        menu = _make_menu(library=lib_a)
        menu.set_category("Props")
        menu.set_search("stale")
        menu.set_library(lib_b)
        assert menu.category == "All"
        assert menu.search == ""

    def test_set_library_rejects_bad_type(self):
        menu = _make_menu(library=PrefabLibrary())
        with pytest.raises(TypeError):
            menu.set_library({"not": "a library"})  # type: ignore[arg-type]

    def test_set_library_logs_call(self):
        menu = _make_menu(library=PrefabLibrary())
        lib_b = _make_library(_make_prefab("a"))
        menu.set_library(lib_b)
        assert any(
            entry[0] == "set_library" for entry in menu.call_log
        )


# ===========================================================================
# Click card → on_spawn
# ===========================================================================


class TestClickCard:
    def test_click_card_invokes_on_spawn(self):
        lib = _make_library(_make_prefab("crate"))
        received: list[str] = []
        menu = _make_menu(library=lib, on_spawn=received.append)
        assert menu.click_card("crate") is True
        assert received == ["crate"]

    def test_click_card_unknown_returns_false(self):
        lib = _make_library(_make_prefab("crate"))
        menu = _make_menu(library=lib, on_spawn=lambda name: None)
        assert menu.click_card("does_not_exist") is False

    def test_click_card_swallows_callback_exception(self):
        lib = _make_library(_make_prefab("crate"))

        def boom(name: str) -> None:
            raise RuntimeError("kaboom")

        menu = _make_menu(library=lib, on_spawn=boom)
        # Return False on callback failure — the menu keeps state.
        assert menu.click_card("crate") is False

    def test_click_card_default_handler_without_world_soft_fails(self):
        # No callback + no world → soft-fail with a warning.
        lib = _make_library(_make_prefab("crate"))
        menu = _make_menu(library=lib)
        assert menu.click_card("crate") is False

    def test_set_on_spawn_installs_callback(self):
        lib = _make_library(_make_prefab("crate"))
        received: list[str] = []
        menu = _make_menu(library=lib)
        menu.set_on_spawn(received.append)
        menu.click_card("crate")
        assert received == ["crate"]

    def test_set_on_spawn_rejects_non_callable(self):
        menu = _make_menu(library=PrefabLibrary())
        with pytest.raises((TypeError, ValueError)):
            menu.set_on_spawn("not-callable")  # type: ignore[arg-type]


# ===========================================================================
# Right-click context menu
# ===========================================================================


class TestContextMenu:
    def test_open_context_menu_records_prefab(self):
        lib = _make_library(_make_prefab("crate"))
        menu = _make_menu(library=lib, on_spawn=lambda n: None)
        assert menu.open_context_menu("crate") is True
        assert menu.context_prefab == "crate"

    def test_open_context_menu_unknown_returns_false(self):
        lib = _make_library(_make_prefab("crate"))
        menu = _make_menu(library=lib, on_spawn=lambda n: None)
        assert menu.open_context_menu("phantom") is False

    def test_context_spawn_dispatches_once(self):
        lib = _make_library(_make_prefab("crate"))
        received: list[str] = []
        menu = _make_menu(library=lib, on_spawn=received.append)
        menu.open_context_menu("crate")
        assert menu.context_spawn() is True
        assert received == ["crate"]
        # Menu closes after action.
        assert menu.context_prefab is None

    def test_context_spawn_n_calls_callback_n_times(self):
        lib = _make_library(_make_prefab("crate"))
        received: list[str] = []
        menu = _make_menu(library=lib, on_spawn=received.append)
        menu.open_context_menu("crate")
        assert menu.context_spawn_n(4) is True
        assert received == ["crate"] * 4

    def test_context_spawn_n_rejects_bad_count(self):
        lib = _make_library(_make_prefab("crate"))
        menu = _make_menu(library=lib, on_spawn=lambda n: None)
        menu.open_context_menu("crate")
        with pytest.raises((TypeError, ValueError)):
            menu.context_spawn_n(0)
        with pytest.raises((TypeError, ValueError)):
            menu.context_spawn_n(-3)

    def test_context_copy_name_returns_prefab_id(self, stub_dpg):
        lib = _make_library(_make_prefab("crate"))
        menu = _make_menu(library=lib, on_spawn=lambda n: None)
        menu.open_context_menu("crate")
        result = menu.context_copy_name()
        assert result == "crate"
        assert stub_dpg.clipboard == "crate"

    def test_context_copy_name_headless_still_returns(self):
        # No stub_dpg fixture — real DPG with no live context. The
        # clipboard write is skipped by design (Z1 hardening — real
        # ``set_clipboard_text`` access-violates without a viewport),
        # but the method still returns the prefab id so callers can
        # branch on it.
        lib = _make_library(_make_prefab("crate"))
        menu = _make_menu(library=lib, on_spawn=lambda n: None)
        menu.open_context_menu("crate")
        assert menu.context_copy_name() == "crate"

    def test_context_view_yaml_returns_yaml_text(self):
        lib = _make_library(_make_prefab("crate", "props", "box"))
        menu = _make_menu(library=lib, on_spawn=lambda n: None)
        menu.open_context_menu("crate")
        text = menu.context_view_yaml()
        assert text is not None
        assert "name: crate" in text
        assert "category: props" in text

    def test_context_view_yaml_opens_modal(self):
        lib = _make_library(_make_prefab("crate", "props", "box"))
        menu = _make_menu(library=lib, on_spawn=lambda n: None)
        menu.open_context_menu("crate")
        menu.context_view_yaml()
        assert menu.yaml_modal is not None
        assert menu.yaml_modal["name"] == "crate"

    def test_close_yaml_modal(self):
        lib = _make_library(_make_prefab("crate", "props", "box"))
        menu = _make_menu(library=lib, on_spawn=lambda n: None)
        menu.open_context_menu("crate")
        menu.context_view_yaml()
        assert menu.close_yaml_modal() is True
        assert menu.yaml_modal is None

    def test_close_context_menu_without_open(self):
        # No raise even when nothing is open.
        lib = _make_library(_make_prefab("crate"))
        menu = _make_menu(library=lib, on_spawn=lambda n: None)
        menu.close_context_menu()
        assert menu.context_prefab is None


# ===========================================================================
# Empty library placeholder
# ===========================================================================


class TestEmptyState:
    def test_empty_library_reports_is_empty(self):
        menu = _make_menu(library=PrefabLibrary())
        assert menu.is_empty() is True

    def test_non_empty_library_is_not_empty(self):
        lib = _make_library(_make_prefab("a"))
        menu = _make_menu(library=lib)
        assert menu.is_empty() is False

    def test_empty_state_renders_placeholder_text(self, stub_dpg):
        menu = _make_menu(library=PrefabLibrary())
        menu.build(parent_tag="root")
        text_calls = stub_dpg.calls.get("add_text", [])
        # Look for the empty-library heading.
        found = any(
            "No prefabs registered" in (call[0][0] if call[0] else "")
            for call in text_calls
        )
        assert found

    def test_no_match_state_when_filter_hides_all(self, stub_dpg):
        lib = _make_library(_make_prefab("crate", "props"))
        menu = _make_menu(library=lib)
        menu.set_search("no_such_prefab")
        menu.build(parent_tag="root")
        text_calls = stub_dpg.calls.get("add_text", [])
        found = any(
            "No prefabs match" in (call[0][0] if call[0] else "")
            for call in text_calls
        )
        assert found


# ===========================================================================
# Build lifecycle
# ===========================================================================


class TestBuild:
    def test_build_flips_flag(self):
        menu = _make_menu(library=_make_library(_make_prefab("crate")))
        menu.build(parent_tag="root")
        assert menu.is_built is True

    def test_build_headless_safe(self):
        # No stub_dpg — real headless path.
        menu = _make_menu(library=_make_library(_make_prefab("crate")))
        result = menu.build(parent_tag="root")
        assert result is True

    def test_build_registers_header_widgets(self, stub_dpg):
        menu = _make_menu(library=_make_library(_make_prefab("crate")))
        menu.build(parent_tag="root")
        assert "add_combo" in stub_dpg.calls
        assert "add_input_text" in stub_dpg.calls

    def test_build_renders_a_card_per_visible_prefab(self, stub_dpg):
        lib = _make_library(
            _make_prefab("a"), _make_prefab("b"), _make_prefab("c"),
        )
        menu = _make_menu(library=lib)
        menu.build(parent_tag="root")
        # 3 prefabs → 3 card-window tags.
        card_tags = [t for t in stub_dpg.items if "prefab_card_" in t]
        assert len(card_tags) == 3

    def test_build_rejects_bad_parent_tag(self):
        menu = _make_menu(library=PrefabLibrary())
        with pytest.raises(TypeError):
            menu.build(parent_tag=1.5)  # type: ignore[arg-type]

    def test_build_rejects_empty_string_parent_tag(self):
        menu = _make_menu(library=PrefabLibrary())
        with pytest.raises((TypeError, ValueError)):
            menu.build(parent_tag="")

    def test_open_close_lifecycle(self):
        menu = _make_menu(library=PrefabLibrary())
        assert menu.is_open is False
        menu.open()
        assert menu.is_open is True
        menu.close()
        assert menu.is_open is False

    def test_destroy_resets_built(self):
        menu = _make_menu(library=PrefabLibrary())
        menu.build(parent_tag="root")
        menu.destroy()
        assert menu.is_built is False


# ===========================================================================
# Badge helper
# ===========================================================================


class TestBadge:
    def test_badge_circle_reports_one_node_zero_joints(self):
        from pharos_editor.ui.editor.notebook_prefab_menu import _prefab_badge
        prefab = _make_prefab("ball", "props", "circle")
        assert _prefab_badge(prefab) == "1n / 0j"

    def test_badge_box_reports_four_nodes_six_joints(self):
        from pharos_editor.ui.editor.notebook_prefab_menu import _prefab_badge
        prefab = Prefab(
            name="crate",
            category="props",
            body_spec={"kind": "box", "width": 1.0, "height": 1.0},
        )
        assert _prefab_badge(prefab) == "4n / 6j"

    def test_badge_rope_reports_node_count_plus_edges(self):
        from pharos_editor.ui.editor.notebook_prefab_menu import _prefab_badge
        prefab = Prefab(
            name="bridge",
            category="structural",
            body_spec={"kind": "rope", "node_count": 5, "total_length": 4.0},
        )
        assert _prefab_badge(prefab) == "5n / 4j"


# ===========================================================================
# Lazy registration
# ===========================================================================


class TestLazyRegistration:
    def test_lazy_import_works(self):
        import pharos_editor.ui.editor as editor_pkg
        assert "NotebookPrefabMenu" in editor_pkg.__all__
        cls = editor_pkg.NotebookPrefabMenu
        assert cls.__name__ == "NotebookPrefabMenu"

    def test_all_alphabetically_ordered_neighbors(self):
        import pharos_editor.ui.editor as editor_pkg
        idx = editor_pkg.__all__.index("NotebookPrefabMenu")
        prev_entry = editor_pkg.__all__[idx - 1]
        next_entry = editor_pkg.__all__[idx + 1]
        assert prev_entry <= "NotebookPrefabMenu" <= next_entry

    def test_lazy_map_wired(self):
        from pharos_editor.ui.editor import _LAZY_MAP
        assert _LAZY_MAP.get("NotebookPrefabMenu") == ".notebook_prefab_menu"


# ===========================================================================
# DPG context-live sentinel
# ===========================================================================


class TestDpgContextSentinel:
    def test_mark_dpg_context_live_toggle(self):
        from pharos_editor.ui.editor import notebook_prefab_menu as mod
        # Snapshot + restore.
        prev = mod._DPG_CONTEXT_LIVE
        try:
            mod.mark_dpg_context_live(True)
            assert mod._DPG_CONTEXT_LIVE is True
            mod.mark_dpg_context_live(False)
            assert mod._DPG_CONTEXT_LIVE is False
        finally:
            mod.mark_dpg_context_live(prev)

    def test_mark_dpg_context_live_exported(self):
        from pharos_editor.ui.editor.notebook_prefab_menu import (
            __all__ as prefab_all,
        )
        assert "mark_dpg_context_live" in prefab_all
