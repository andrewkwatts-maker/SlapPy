"""Tests for :class:`NotebookSpawnMenu` — the trading-card spawn deck.

The menu reskins the Nova3D ``+ Add`` modal as a deck of "trading cards"
where each spawn entry is a card with a portrait + summon button. These
tests exercise the data layer (card table, SVG byte budget, spec types)
plus the headless-DPG build / hover / summon paths.

Every ``dpg.*`` call is stubbed with a no-op recorder so the menu builds
cleanly in CI without a real GUI context.
"""
from __future__ import annotations

import sys
import types
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub — accepts context-manager and plain method calls.
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

    # context managers
    def group(self, *a, **kw):
        self._track("group", a, kw)
        return _StubCM()

    def child_window(self, *a, **kw):
        self._track("child_window", a, kw)
        return _StubCM()

    def collapsing_header(self, *a, **kw):
        self._track("collapsing_header", a, kw)
        return _StubCM()

    def popup(self, *a, **kw):
        self._track("popup", a, kw)
        return _StubCM()

    def window(self, *a, **kw):
        self._track("window", a, kw)
        return _StubCM()

    # primitives
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

    def add_listbox(self, *a, **kw):
        self._track("add_listbox", a, kw)

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

    def set_value(self, *a, **kw):
        self._track("set_value", a, kw)


@pytest.fixture(autouse=True)
def stub_dpg(monkeypatch):
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    method_names = (
        "group", "child_window", "collapsing_header", "popup", "window",
        "add_text", "add_button", "add_checkbox", "add_separator",
        "add_input_text", "add_input_int", "add_input_float",
        "add_input_floatx", "add_color_edit", "add_listbox",
        "does_item_exist", "delete_item", "configure_item",
        "get_item_children", "set_value",
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
def clear_theme(stub_dpg):
    """Reset notebook theme + listener list between tests."""
    from pharos_engine.ui.widgets import notebook_theme
    from pharos_engine.ui.widgets.notebook_theme import set_active_theme

    set_active_theme(None)
    notebook_theme._theme_listeners.clear()
    yield
    set_active_theme(None)
    notebook_theme._theme_listeners.clear()


# ---------------------------------------------------------------------------
# 1. Construction — menu builds with all 10 cards.
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_menu_constructs_with_callback(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu

        menu = NotebookSpawnMenu(on_spawn=lambda cid, spec: None)
        assert menu.TITLE == "+ Add"
        assert menu.card_count == 10

    def test_menu_rejects_non_callable_on_spawn(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu

        with pytest.raises(TypeError):
            NotebookSpawnMenu(on_spawn="not callable")  # type: ignore[arg-type]

    def test_menu_has_all_ten_expected_card_ids(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu

        menu = NotebookSpawnMenu(on_spawn=lambda cid, spec: None)
        ids = {card.card_id for card in menu.cards}
        expected = {
            "rope", "ragdoll", "humanoid", "ik_chain",
            "zone_rect", "zone_threshold",
            "light_point", "light_directional",
            "material", "emitter",
        }
        assert ids == expected


# ---------------------------------------------------------------------------
# 2. Portrait SVGs ≤ 500 B each
# ---------------------------------------------------------------------------


class TestPortraitSVGs:
    def test_each_card_has_portrait_under_500_bytes(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu

        menu = NotebookSpawnMenu(on_spawn=lambda cid, spec: None)
        for card in menu.cards:
            assert card.portrait_svg, f"card {card.card_id!r} has empty SVG"
            n = len(card.portrait_svg.encode("utf-8"))
            assert n <= 500, (
                f"portrait for {card.card_id!r} is too large: {n} bytes"
            )

    def test_spawn_cards_module_constant_carries_all_ten_entries(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import SPAWN_CARDS

        assert len(SPAWN_CARDS) == 10
        # Each entry is the canonical (id, title, svg, description) tuple.
        for entry in SPAWN_CARDS:
            assert len(entry) == 4
            cid, title, svg, desc = entry
            assert isinstance(cid, str) and cid
            assert isinstance(title, str) and title
            assert svg.startswith("<svg")
            assert isinstance(desc, str) and desc


# ---------------------------------------------------------------------------
# 3. Build path + card grid
# ---------------------------------------------------------------------------


class TestBuildPath:
    def test_build_records_in_call_log(self, stub_dpg):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu

        menu = NotebookSpawnMenu(on_spawn=lambda cid, spec: None)
        menu.build("sidebar")
        assert any(event[0] == "build" for event in menu.call_log)

    def test_build_renders_title_text(self, stub_dpg):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu

        menu = NotebookSpawnMenu(on_spawn=lambda cid, spec: None)
        menu.build("sidebar")

        texts = [args for args, _ in stub_dpg.calls.get("add_text", [])]
        flat = [a[0] if a else "" for a in texts]
        assert "+ Add" in flat

    def test_build_renders_card_titles(self, stub_dpg):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu

        menu = NotebookSpawnMenu(on_spawn=lambda cid, spec: None)
        menu.build("sidebar")

        texts = [args for args, _ in stub_dpg.calls.get("add_text", [])]
        flat = [a[0] if a else "" for a in texts]
        # A handful of card titles should have hit add_text.
        for needle in ("Rope", "Ragdoll", "Humanoid", "Sun"):
            assert needle in flat, f"expected card title {needle!r} in render"


# ---------------------------------------------------------------------------
# 4. Summon click fires the on_spawn callback with (card_id, spec_dict).
# ---------------------------------------------------------------------------


class TestSummonCallback:
    def test_summon_then_submit_fires_on_spawn(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu

        captured: list[tuple[str, dict]] = []
        menu = NotebookSpawnMenu(
            on_spawn=lambda cid, spec: captured.append((cid, spec)),
        )
        menu.summon("rope")
        menu.submit_modal()

        assert len(captured) == 1
        cid, spec = captured[0]
        assert cid == "rope"
        # Rope spec carries node_count + total_length + anchor_a/b.
        assert "node_count" in spec
        assert "anchor_a" in spec
        assert "anchor_b" in spec

    def test_summon_unknown_card_raises(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu

        menu = NotebookSpawnMenu(on_spawn=lambda cid, spec: None)
        with pytest.raises(ValueError):
            menu.summon("not_a_real_card")

    def test_cancel_modal_does_not_fire_on_spawn(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu

        captured: list = []
        menu = NotebookSpawnMenu(
            on_spawn=lambda cid, spec: captured.append((cid, spec)),
        )
        menu.summon("ragdoll")
        menu.cancel_modal()
        assert captured == []
        assert menu.open_modal is None


# ---------------------------------------------------------------------------
# 5. Hover state adds the shimmer overlay.
# ---------------------------------------------------------------------------


class TestHoverShimmer:
    def test_hover_caches_shimmer_overlay(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu

        menu = NotebookSpawnMenu(on_spawn=lambda cid, spec: None)
        assert menu.shimmer_overlay("rope") is None
        menu.set_hover("rope")
        # The overlay should be cached after a hover-enter.
        assert menu.shimmer_overlay("rope") is not None
        assert menu.hovered_card == "rope"

    def test_hover_clear_resets_state(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu

        menu = NotebookSpawnMenu(on_spawn=lambda cid, spec: None)
        menu.set_hover("rope")
        menu.set_hover(None)
        assert menu.hovered_card is None

    def test_hover_scale_factor_is_above_one(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu

        menu = NotebookSpawnMenu(on_spawn=lambda cid, spec: None)
        scale = menu.hover_scale()
        assert scale > 1.0
        assert scale <= 1.5  # sane upper bound — cards shouldn't balloon

    def test_unknown_hover_id_silently_clears(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu

        menu = NotebookSpawnMenu(on_spawn=lambda cid, spec: None)
        menu.set_hover("not_a_real_card")
        assert menu.hovered_card is None


# ---------------------------------------------------------------------------
# 6. Theme switch updates the card backgrounds + drops shimmer cache.
# ---------------------------------------------------------------------------


class TestThemeIntegration:
    def test_theme_switch_updates_card_background(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu
        from pharos_engine.ui.widgets.notebook_theme import (
            NotebookTheme,
            set_active_theme,
        )

        menu = NotebookSpawnMenu(on_spawn=lambda cid, spec: None)
        theme = NotebookTheme(
            name="loud",
            palette={
                "paper":  (10, 20, 30, 255),
                "ink":    (200, 210, 220, 255),
                "accent": (1, 2, 3, 255),
                "washi":  (4, 5, 6, 255),
            },
        )
        set_active_theme(theme)
        assert menu.card_background == (10, 20, 30, 255)
        # Shimmer cache should drop on theme change so the next hover
        # re-bakes against the new accent colour.
        assert menu.shimmer_overlay("rope") is None

    def test_theme_listener_detached_on_destroy(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu
        from pharos_engine.ui.widgets.notebook_theme import (
            NotebookTheme,
            set_active_theme,
        )

        menu = NotebookSpawnMenu(on_spawn=lambda cid, spec: None)
        menu.destroy()
        # Subsequent theme changes must not crash.
        set_active_theme(NotebookTheme(name="post"))


# ---------------------------------------------------------------------------
# 7. Modal opens on summon and is bound to the right spec template.
# ---------------------------------------------------------------------------


class TestModalSpecTemplate:
    def test_summon_opens_modal_with_correct_spec_type(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu
        from pharos_engine.ui.editor.spawn_menu import RopeSpawnSpec

        menu = NotebookSpawnMenu(on_spawn=lambda cid, spec: None)
        menu.summon("rope")
        modal = menu.open_modal
        assert modal is not None
        assert modal["card_id"] == "rope"
        assert isinstance(modal["spec"], RopeSpawnSpec)

    def test_summon_humanoid_uses_humanoid_spawn_spec(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu
        from pharos_engine.ui.editor.spawn_menu import HumanoidSpawnSpec

        menu = NotebookSpawnMenu(on_spawn=lambda cid, spec: None)
        menu.summon("humanoid")
        modal = menu.open_modal
        assert modal is not None
        assert isinstance(modal["spec"], HumanoidSpawnSpec)

    def test_summon_zone_rect_uses_rect_zone_spec(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import (
            NotebookSpawnMenu,
            RectZoneSpec,
        )

        menu = NotebookSpawnMenu(on_spawn=lambda cid, spec: None)
        menu.summon("zone_rect")
        modal = menu.open_modal
        assert modal is not None
        assert isinstance(modal["spec"], RectZoneSpec)

    def test_summon_light_directional_uses_directional_spec(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import (
            DirectionalLightSpec,
            NotebookSpawnMenu,
        )

        menu = NotebookSpawnMenu(on_spawn=lambda cid, spec: None)
        menu.summon("light_directional")
        modal = menu.open_modal
        assert modal is not None
        assert isinstance(modal["spec"], DirectionalLightSpec)

    def test_modal_carries_inspector_handle(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu

        menu = NotebookSpawnMenu(on_spawn=lambda cid, spec: None)
        menu.summon("emitter")
        modal = menu.open_modal
        assert modal is not None
        # The inspector key should be present (may be None if NotebookInspector
        # is unavailable, but the key itself is part of the contract).
        assert "inspector" in modal


# ---------------------------------------------------------------------------
# 8. open() / close() / is_open lifecycle
# ---------------------------------------------------------------------------


class TestOpenCloseLifecycle:
    def test_open_marks_menu_open(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu

        menu = NotebookSpawnMenu(on_spawn=lambda cid, spec: None)
        assert menu.is_open is False
        menu.open()
        assert menu.is_open is True

    def test_close_resets_open_flag_and_modal(self):
        from pharos_engine.ui.editor.notebook_spawn_menu import NotebookSpawnMenu

        menu = NotebookSpawnMenu(on_spawn=lambda cid, spec: None)
        menu.open()
        menu.summon("material")
        assert menu.open_modal is not None
        menu.close()
        assert menu.is_open is False
        assert menu.open_modal is None
