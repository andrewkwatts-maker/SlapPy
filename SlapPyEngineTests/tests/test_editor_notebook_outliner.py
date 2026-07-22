"""Tests for the notebook-themed scene outliner (NotebookOutliner).

The outliner mirrors the Nova3D ``SceneOutliner`` data contract but
rebrands every row as a hand-drawn field-journal entry.  These tests
exercise the data layer (``iter_rows`` + ``classify_entity``) plus the
DPG ``build()`` path under a headless stub.

Coverage:

* Empty world → renders the "drop a creature in from the spawn menu"
  empty state.
* Mixed world (rope + ragdoll + camera) → renders three rows.
* Each row resolves to the correct badge kind.
* Click on a row routes through the ``on_select`` callback.
* Visibility toggle mutates ``entity.visible``.
* Lock toggle mutates ``entity.locked``.
* Search filter shrinks the visible row list.
* Theme switch updates the cached row palette.
* The currently-selected row carries a highlighter overlay.

The DPG stub follows the same pattern as
``test_editor_scene_outliner_dynamics`` so the tests run on CI without
a real GUI context.
"""
from __future__ import annotations

import sys
import types
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

    def collapsing_header(self, *a, **kw):
        self._track("collapsing_header", a, kw)
        return _StubCM()

    def group(self, *a, **kw):
        self._track("group", a, kw)
        return _StubCM()

    def child_window(self, *a, **kw):
        self._track("child_window", a, kw)
        return _StubCM()

    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)

    def add_button(self, *a, **kw):
        self._track("add_button", a, kw)

    def add_checkbox(self, *a, **kw):
        self._track("add_checkbox", a, kw)

    def add_input_text(self, *a, **kw):
        self._track("add_input_text", a, kw)

    def add_separator(self, *a, **kw):
        self._track("add_separator", a, kw)

    def does_item_exist(self, tag, *a, **kw):
        return tag in self.items

    def delete_item(self, tag, *a, **kw):
        self._track("delete_item", (tag,), kw)
        if isinstance(tag, str):
            self.items.discard(tag)

    def get_item_children(self, *a, **kw):
        return []


@pytest.fixture(autouse=True)
def stub_dpg(monkeypatch):
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    for name in (
        "collapsing_header", "group", "child_window",
        "add_text", "add_button", "add_checkbox", "add_input_text",
        "add_separator", "does_item_exist", "delete_item",
        "get_item_children",
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
def clear_theme(stub_dpg):
    """Reset theme + sticker registry + theme-listener list between tests.

    Depends on ``stub_dpg`` so the stub stays installed during teardown
    (theme-listener cleanup fires ``set_active_theme(None)`` which may
    re-enter the outliner's refresh path).

    Also clears the global theme-listener registry to drop any
    ``NotebookOutliner`` references left over from the previous test —
    otherwise their ``_on_theme_changed`` hook fires when the next test
    sets a theme and surfaces stale row state.
    """
    from pharos_editor.ui.widgets import notebook_theme
    from pharos_editor.ui.widgets.notebook_theme import set_active_theme
    from pharos_editor.ui.widgets.sticker_corner import _active_stickers

    set_active_theme(None)
    notebook_theme._theme_listeners.clear()
    _active_stickers.clear()
    yield
    set_active_theme(None)
    notebook_theme._theme_listeners.clear()
    _active_stickers.clear()


# ---------------------------------------------------------------------------
# Lightweight fakes — the outliner only reads `.name`, `.kind`, `.visible`,
# `.locked`, `.id`, so we don't need the full dynamics machinery here.
# ---------------------------------------------------------------------------

class _FakeEntity:
    def __init__(
        self,
        name: str,
        kind: str = "entity",
        visible: bool = True,
        locked: bool = False,
        eid: str | None = None,
    ) -> None:
        self.name = name
        self.kind = kind
        self.visible = visible
        self.locked = locked
        if eid is not None:
            self.id = eid


class _FakeWorld:
    def __init__(self, entities: list[Any] | None = None) -> None:
        self.entities: list[Any] = list(entities or [])


# ---------------------------------------------------------------------------
# Construction / validators
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_constructs_with_callables(self):
        from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner

        out = NotebookOutliner(_FakeWorld, lambda e: None)
        assert out.TITLE == "Scene"
        assert out.get_selected() is None

    def test_rejects_non_callable_world_getter(self):
        from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner

        with pytest.raises(TypeError):
            NotebookOutliner("not callable", lambda e: None)  # type: ignore[arg-type]

    def test_rejects_non_callable_on_select(self):
        from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner

        with pytest.raises(TypeError):
            NotebookOutliner(lambda: None, "not callable")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Entity classification → badge kind
# ---------------------------------------------------------------------------

class TestClassifyEntity:
    def test_rope_classifies_as_rope(self):
        from pharos_editor.ui.editor.notebook_outliner import classify_entity

        ent = _FakeEntity("R1", kind="rope")
        assert classify_entity(ent) == "rope"

    def test_ragdoll_classifies_as_ragdoll(self):
        from pharos_editor.ui.editor.notebook_outliner import classify_entity

        ent = _FakeEntity("R1", kind="ragdoll")
        assert classify_entity(ent) == "ragdoll"

    def test_humanoid_via_parameters_tag(self):
        from pharos_editor.ui.editor.notebook_outliner import classify_entity

        ent = _FakeEntity("H1", kind="ragdoll")
        ent.parameters = {"humanoid": True}
        assert classify_entity(ent) == "humanoid"

    def test_unknown_kind_falls_back_to_entity(self):
        from pharos_editor.ui.editor.notebook_outliner import classify_entity

        ent = _FakeEntity("X1", kind="totally_unknown")
        assert classify_entity(ent) == "entity"

    def test_class_name_sniff_for_no_kind(self):
        from pharos_editor.ui.editor.notebook_outliner import classify_entity

        class CameraThing:
            pass

        assert classify_entity(CameraThing()) == "camera"


# ---------------------------------------------------------------------------
# Badge SVGs
# ---------------------------------------------------------------------------

class TestBadges:
    def test_every_kind_has_svg_under_500b(self):
        from pharos_editor.ui.editor.notebook_outliner import _BADGE_SVGS

        expected = {
            "entity", "body", "joint", "light", "camera", "mesh",
            "humanoid", "material", "rope", "ragdoll", "zone",
        }
        assert set(_BADGE_SVGS.keys()) == expected
        for kind, svg in _BADGE_SVGS.items():
            assert len(svg.encode("utf-8")) <= 500, (
                f"badge {kind!r} is too large: {len(svg)} bytes"
            )

    def test_badge_svg_falls_back_to_entity_for_unknown(self):
        from pharos_editor.ui.editor.notebook_outliner import badge_svg, _BADGE_SVGS

        assert badge_svg("not_a_real_kind") == _BADGE_SVGS["entity"]

    def test_make_badge_icon_returns_svgicon(self):
        from pharos_editor.ui.editor.notebook_outliner import make_badge_icon
        from pharos_editor.ui.theme.svg_icon import SVGIcon

        icon = make_badge_icon("rope", size=16)
        assert isinstance(icon, SVGIcon)
        assert icon.size == 16


# ---------------------------------------------------------------------------
# Empty world → empty state row
# ---------------------------------------------------------------------------

class TestEmptyState:
    def test_empty_world_iter_rows_is_empty(self):
        from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner

        world = _FakeWorld()
        out = NotebookOutliner(lambda: world, lambda e: None)
        assert out.iter_rows() == []

    def test_empty_world_build_renders_empty_state(self, stub_dpg):
        from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner

        world = _FakeWorld()
        out = NotebookOutliner(lambda: world, lambda e: None)
        out.build("sidebar")

        # The empty-state text must hit add_text at least once and include
        # the spawn-menu hint substring.
        texts = [args for args, _ in stub_dpg.calls.get("add_text", [])]
        flat = " ".join(str(a) for a in texts)
        assert "spawn menu" in flat

    def test_no_world_getter_returns_empty_rows(self):
        from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner

        out = NotebookOutliner(lambda: None, lambda e: None)
        assert out.iter_rows() == []


# ---------------------------------------------------------------------------
# Multi-entity world → row enumeration
# ---------------------------------------------------------------------------

class TestRowEnumeration:
    def _world_with_three(self) -> _FakeWorld:
        return _FakeWorld(entities=[
            _FakeEntity("rope_0",    kind="rope",    eid="rope_0"),
            _FakeEntity("ragdoll_0", kind="ragdoll", eid="ragdoll_0"),
            _FakeEntity("camera_0",  kind="camera",  eid="camera_0"),
        ])

    def test_three_entities_yield_three_rows(self):
        from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner

        world = self._world_with_three()
        out = NotebookOutliner(lambda: world, lambda e: None)
        rows = out.iter_rows()
        assert len(rows) == 3

    def test_each_row_carries_correct_badge_kind(self):
        from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner

        world = self._world_with_three()
        out = NotebookOutliner(lambda: world, lambda e: None)
        rows = out.iter_rows()
        kinds = {r["name"]: r["kind"] for r in rows}
        assert kinds == {
            "rope_0":    "rope",
            "ragdoll_0": "ragdoll",
            "camera_0":  "camera",
        }

    def test_world_with_three_renders_button_rows(self, stub_dpg):
        from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner

        world = self._world_with_three()
        out = NotebookOutliner(lambda: world, lambda e: None)
        out.build("sidebar")

        # Three entity name buttons should have been added.
        buttons = stub_dpg.calls.get("add_button", [])
        labels = [kw.get("label") for _, kw in buttons]
        assert "rope_0" in labels
        assert "ragdoll_0" in labels
        assert "camera_0" in labels


# ---------------------------------------------------------------------------
# Selection callback
# ---------------------------------------------------------------------------

class TestSelectionCallback:
    def test_click_routes_through_on_select(self):
        from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner

        world = _FakeWorld(entities=[_FakeEntity("R1", kind="rope")])
        captured: list[Any] = []
        out = NotebookOutliner(lambda: world, captured.append)

        ent = world.entities[0]
        out._handle_select(ent)

        assert captured == [ent]
        assert out.get_selected() == "R1"

    def test_set_selected_updates_selection_state(self):
        from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner

        out = NotebookOutliner(lambda: _FakeWorld(), lambda e: None)
        out.set_selected("my_id")
        assert out.get_selected() == "my_id"


# ---------------------------------------------------------------------------
# Visibility + lock toggles
# ---------------------------------------------------------------------------

class TestToggles:
    def test_visibility_toggle_updates_entity_visible(self):
        from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner

        ent = _FakeEntity("V1", kind="body", visible=True)
        out = NotebookOutliner(lambda: _FakeWorld([ent]), lambda e: None)
        out._handle_toggle_visible(ent, False)
        assert ent.visible is False
        out._handle_toggle_visible(ent, True)
        assert ent.visible is True

    def test_lock_toggle_updates_entity_locked(self):
        from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner

        ent = _FakeEntity("L1", kind="body", locked=False)
        out = NotebookOutliner(lambda: _FakeWorld([ent]), lambda e: None)
        out._handle_toggle_lock(ent, True)
        assert ent.locked is True
        out._handle_toggle_lock(ent, False)
        assert ent.locked is False


# ---------------------------------------------------------------------------
# Search filter
# ---------------------------------------------------------------------------

class TestSearch:
    def test_search_filter_shrinks_rows(self):
        from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner

        world = _FakeWorld([
            _FakeEntity("rope_player", kind="rope"),
            _FakeEntity("ragdoll_enemy", kind="ragdoll"),
            _FakeEntity("camera_main",   kind="camera"),
        ])
        out = NotebookOutliner(lambda: world, lambda e: None)

        assert len(out.iter_rows()) == 3
        out.set_search("rope")
        rows = out.iter_rows()
        assert len(rows) == 1
        assert rows[0]["name"] == "rope_player"

    def test_search_matches_kind_as_well_as_name(self):
        from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner

        world = _FakeWorld([
            _FakeEntity("alpha", kind="rope"),
            _FakeEntity("beta",  kind="ragdoll"),
        ])
        out = NotebookOutliner(lambda: world, lambda e: None)
        out.set_search("ragdoll")
        rows = out.iter_rows()
        assert len(rows) == 1
        assert rows[0]["name"] == "beta"

    def test_empty_search_shows_everything(self):
        from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner

        world = _FakeWorld([
            _FakeEntity("a", kind="rope"),
            _FakeEntity("b", kind="rope"),
        ])
        out = NotebookOutliner(lambda: world, lambda e: None)
        out.set_search("xyz")
        assert out.iter_rows() == []
        out.set_search("")
        assert len(out.iter_rows()) == 2


# ---------------------------------------------------------------------------
# Theme handling
# ---------------------------------------------------------------------------

class TestThemeIntegration:
    def test_theme_switch_updates_cached_palette(self):
        from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner
        from pharos_editor.ui.widgets.notebook_theme import (
            NotebookTheme,
            set_active_theme,
        )

        out = NotebookOutliner(lambda: _FakeWorld(), lambda e: None)
        # Switch the active theme — the outliner's cached snapshot should
        # follow via the theme-listener bridge.
        theme = NotebookTheme(
            name="loud",
            palette={"accent": (1, 2, 3, 255), "ink": (4, 5, 6, 255)},
        )
        set_active_theme(theme)
        assert out._theme.color("accent") == (1, 2, 3, 255)

    def test_destroy_unregisters_listener(self):
        from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner
        from pharos_editor.ui.widgets.notebook_theme import (
            NotebookTheme,
            set_active_theme,
        )

        out = NotebookOutliner(lambda: _FakeWorld(), lambda e: None)
        out.destroy()
        # Should not raise when subsequent theme changes fire.
        set_active_theme(NotebookTheme(name="post"))


# ---------------------------------------------------------------------------
# Highlighter overlay for the selected row
# ---------------------------------------------------------------------------

class TestSelectedHighlight:
    def test_selected_row_emits_highlighter_overlay(self, stub_dpg):
        from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner

        ent = _FakeEntity("only", kind="rope", eid="only")
        out = NotebookOutliner(lambda: _FakeWorld([ent]), lambda e: None)
        out.set_selected("only")
        out.build("sidebar")

        # The highlighter overlay is a coloured "|" prefix text — assert
        # at least one add_text call carries it.
        texts = [args for args, _ in stub_dpg.calls.get("add_text", [])]
        flat = [a[0] if a else "" for a in texts]
        assert any(t == "|" for t in flat), (
            "expected '|' highlighter overlay for the selected row; "
            f"got texts: {flat!r}"
        )

    def test_unselected_rows_have_no_highlighter(self, stub_dpg):
        from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner

        ent = _FakeEntity("only", kind="rope", eid="only")
        out = NotebookOutliner(lambda: _FakeWorld([ent]), lambda e: None)
        # Do NOT set_selected — the row is unselected.
        out.build("sidebar")

        texts = [args for args, _ in stub_dpg.calls.get("add_text", [])]
        flat = [a[0] if a else "" for a in texts]
        assert not any(t == "|" for t in flat)


# ---------------------------------------------------------------------------
# Sticker decoration on the first top-level entity
# ---------------------------------------------------------------------------

class TestStickerDecoration:
    def test_first_top_level_row_gets_sparkle_sticker(self, stub_dpg):
        from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner
        from pharos_editor.ui.widgets.sticker_corner import list_sticker_corners

        world = _FakeWorld([
            _FakeEntity("first", kind="rope", eid="first"),
            _FakeEntity("second", kind="rope", eid="second"),
        ])
        out = NotebookOutliner(lambda: world, lambda e: None)
        out.build("sidebar")

        # At least one sticker handle should be tracked on the row.
        active = list_sticker_corners()
        # Expect a sparkle corner on the "first" row.
        assert any("sparkle" in s and "first" in s for s in active), (
            f"expected sparkle on first row; got {active!r}"
        )

    def test_empty_state_drops_fox_sticker(self, stub_dpg):
        from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner
        from pharos_editor.ui.widgets.sticker_corner import list_sticker_corners

        out = NotebookOutliner(lambda: _FakeWorld(), lambda e: None)
        out.build("sidebar")
        active = list_sticker_corners()
        assert any("fox" in s for s in active), (
            f"expected fox sticker on empty state; got {active!r}"
        )
