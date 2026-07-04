"""Tests for the X7 batch of notebook widget primitives.

Covers the six new primitives added in the X7 sprint:

* ``GlitterProgressBar``
* ``RibbonTab``
* ``PaperClipAttachment``
* ``WashiTapeDivider``
* ``SketchButton``
* ``InkStampBadge``

Every widget is exercised in a *headless* DPG context using a shared
``_StubDPG`` stub identical in spirit to
``test_ui_widgets_notebook.py``.  For each widget we assert:

1. It instantiates + mounts headlessly.
2. ``set_theme`` actually rebinds the cached palette / property.
3. ``set_enabled`` toggles the ``_enabled`` flag.
4. The event callback fires when triggered (either via the DPG stub or
   by calling the widget's private handler directly).

That's 4 tests × 6 widgets = 24 tests minimum.  A few extra tests
cover pickle round-trips and constructor validation.
"""
from __future__ import annotations

import pickle
import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub — same protocol as test_ui_widgets_notebook.py.
# ---------------------------------------------------------------------------

class _StubCM:
    def __init__(self, recorder: dict, name: str) -> None:
        self._recorder = recorder
        self._name = name

    def __enter__(self):
        self._recorder.setdefault("contexts", []).append(self._name)
        return self

    def __exit__(self, *exc):
        return False


class _StubDPG:
    """Minimal DPG surface with call-tracking."""

    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: set[str] = set()
        self.values: dict[str, object] = {}
        self.configs: dict[str, dict] = {}

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    # context managers
    def group(self, *args, **kwargs):
        self._track("group", args, kwargs)
        return _StubCM(self.calls, "group")

    def child_window(self, *args, **kwargs):
        self._track("child_window", args, kwargs)
        return _StubCM(self.calls, "child_window")

    def collapsing_header(self, *args, **kwargs):
        self._track("collapsing_header", args, kwargs)
        return _StubCM(self.calls, "collapsing_header")

    # plain items
    def add_text(self, *args, **kwargs):
        self._track("add_text", args, kwargs)

    def add_button(self, *args, **kwargs):
        self._track("add_button", args, kwargs)

    def add_progress_bar(self, *args, **kwargs):
        self._track("add_progress_bar", args, kwargs)
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.values[tag] = kwargs.get("default_value")

    def add_drawlist(self, *args, **kwargs):
        self._track("add_drawlist", args, kwargs)

    def add_selectable(self, *args, **kwargs):
        self._track("add_selectable", args, kwargs)
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.values[tag] = kwargs.get("default_value")

    def add_separator(self, *args, **kwargs):
        self._track("add_separator", args, kwargs)

    def add_slider_float(self, *args, **kwargs):
        self._track("add_slider_float", args, kwargs)

    def add_checkbox(self, *args, **kwargs):
        self._track("add_checkbox", args, kwargs)

    def set_value(self, tag, value, *args, **kwargs):
        self._track("set_value", (tag, value), kwargs)
        if isinstance(tag, str):
            self.values[tag] = value

    def get_value(self, tag, *args, **kwargs):
        return self.values.get(tag)

    def configure_item(self, tag, **kwargs):
        self._track("configure_item", (tag,), kwargs)
        if isinstance(tag, str):
            self.configs.setdefault(tag, {}).update(kwargs)

    def enable_item(self, tag, *args, **kwargs):
        self._track("enable_item", (tag,), kwargs)
        if isinstance(tag, str):
            self.configs.setdefault(tag, {})["enabled"] = True

    def disable_item(self, tag, *args, **kwargs):
        self._track("disable_item", (tag,), kwargs)
        if isinstance(tag, str):
            self.configs.setdefault(tag, {})["enabled"] = False

    def delete_item(self, tag, *args, **kwargs):
        self._track("delete_item", (tag,), kwargs)
        if isinstance(tag, str):
            self.items.discard(tag)

    def does_item_exist(self, tag, *args, **kwargs):
        return tag in self.items


@pytest.fixture(autouse=True)
def stub_dpg(monkeypatch):
    """Install a fresh ``_StubDPG`` for every test."""
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")

    def _fallback(name):
        if hasattr(stub, name):
            return getattr(stub, name)

        def _noop(*a, **kw):
            stub.calls.setdefault(name, []).append((a, kw))

        return _noop

    mod.__getattr__ = _fallback
    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    for name in (
        "group", "child_window", "collapsing_header",
        "add_text", "add_button", "add_progress_bar", "add_drawlist",
        "add_selectable", "add_separator", "add_slider_float",
        "add_checkbox",
        "set_value", "get_value", "configure_item",
        "enable_item", "disable_item",
        "delete_item", "does_item_exist",
    ):
        setattr(mod, name, getattr(stub, name))
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


@pytest.fixture(autouse=True)
def clear_theme():
    """Reset the active theme + sticker registry between tests."""
    from slappyengine.ui.widgets.notebook_theme import set_active_theme
    from slappyengine.ui.widgets.sticker_corner import _active_stickers

    set_active_theme(None)
    _active_stickers.clear()
    yield
    set_active_theme(None)
    _active_stickers.clear()


# ===========================================================================
# GlitterProgressBar
# ===========================================================================

class TestGlitterProgressBar:
    def test_instantiates_and_mounts(self, stub_dpg):
        from slappyengine.ui.widgets import GlitterProgressBar

        bar = GlitterProgressBar("HP", 0.4, intensity="medium")
        assert bar.value == 0.4
        assert bar.particle_count == 12
        bar.mount("parent")
        assert bar.root_tag is not None
        assert "add_progress_bar" in stub_dpg.calls

    def test_set_theme_rebinds_palette(self):
        from slappyengine.ui.widgets import (
            GlitterProgressBar,
            NotebookTheme,
        )

        bar = GlitterProgressBar("HP", 0.4, intensity="low")
        original = bar.accent_color
        theme = NotebookTheme(
            name="hot_pink",
            palette={"accent": (255, 0, 128, 255)},
        )
        bar.set_theme(theme)
        assert bar.accent_color == (255, 0, 128, 255)
        assert bar.accent_color != original

    def test_set_enabled_toggles_state(self, stub_dpg):
        from slappyengine.ui.widgets import GlitterProgressBar

        bar = GlitterProgressBar("HP", 0.4)
        bar.mount("parent")
        assert bar.enabled is True
        bar.set_enabled(False)
        assert bar.enabled is False
        # Either configure_item or disable_item should have been invoked.
        assert (
            "configure_item" in stub_dpg.calls
            or "disable_item" in stub_dpg.calls
        )
        bar.set_enabled(True)
        assert bar.enabled is True

    def test_on_change_fires_on_set_value(self):
        from slappyengine.ui.widgets import GlitterProgressBar

        seen: list[float] = []
        bar = GlitterProgressBar(
            "HP", 0.0, intensity="high", on_change=lambda v: seen.append(v),
        )
        bar.set_value(0.75)
        assert seen == [0.75]
        assert bar.value == 0.75

    def test_intensity_change_resizes_emitter(self):
        from slappyengine.ui.widgets import GlitterProgressBar

        bar = GlitterProgressBar("HP", 0.0, intensity="low")
        assert bar.particle_count == 5
        bar.set_intensity("high")
        assert bar.particle_count == 20

    def test_pickle_roundtrip_drops_live_tags(self, stub_dpg):
        from slappyengine.ui.widgets import GlitterProgressBar

        bar = GlitterProgressBar("HP", 0.5, intensity="medium")
        bar.mount("parent")
        raw = pickle.dumps(bar)
        restored = pickle.loads(raw)
        assert restored.value == 0.5
        assert restored.particle_count == 12
        assert restored.root_tag is None


# ===========================================================================
# RibbonTab
# ===========================================================================

class TestRibbonTab:
    def test_instantiates_and_mounts(self, stub_dpg):
        from slappyengine.ui.widgets import RibbonTab

        tab = RibbonTab("Overview")
        tab.mount("parent")
        assert tab.root_tag is not None
        assert "add_selectable" in stub_dpg.calls

    def test_set_theme_rebinds_palette(self):
        from slappyengine.ui.widgets import (
            NotebookTheme,
            RibbonTab,
        )

        tab = RibbonTab("Overview")
        original = tab.accent_color
        tab.set_theme(
            NotebookTheme(palette={"accent": (10, 200, 50, 255)}),
        )
        assert tab.accent_color == (10, 200, 50, 255)
        assert tab.accent_color != original

    def test_set_enabled_toggles_state(self):
        from slappyengine.ui.widgets import RibbonTab

        tab = RibbonTab("Overview")
        assert tab.enabled is True
        tab.set_enabled(False)
        assert tab.enabled is False
        assert tab.state == "disabled"

    def test_on_click_fires_via_stub(self):
        from slappyengine.ui.widgets import RibbonTab

        seen: list[str] = []
        tab = RibbonTab(
            "Overview",
            on_click=lambda w: seen.append(w.label),
        )
        tab._on_selectable("tag", True, None)
        assert seen == ["Overview"]
        assert tab.selected is True

    def test_on_change_fires_when_state_changes(self):
        from slappyengine.ui.widgets import RibbonTab

        changes: list[tuple] = []
        tab = RibbonTab(
            "Overview",
            on_change=lambda sel, en: changes.append((sel, en)),
        )
        tab.set_selected(True)
        assert changes == [(True, True)]
        tab.set_enabled(False)
        assert changes[-1] == (True, False)


# ===========================================================================
# PaperClipAttachment
# ===========================================================================

class TestPaperClipAttachment:
    def test_instantiates_and_mounts(self, stub_dpg):
        from slappyengine.ui.widgets import PaperClipAttachment

        pc = PaperClipAttachment("Notes", [lambda: None])
        assert pc.expanded is False
        pc.mount("parent")
        assert pc.root_tag is not None
        # Either collapsing_header or a fallback group should have been used.
        assert (
            "collapsing_header" in stub_dpg.calls
            or "group" in stub_dpg.calls
            or "add_text" in stub_dpg.calls
        )

    def test_set_theme_rebinds_palette(self):
        from slappyengine.ui.widgets import (
            NotebookTheme,
            PaperClipAttachment,
        )

        pc = PaperClipAttachment("Notes")
        original = pc.paper_color
        pc.set_theme(
            NotebookTheme(palette={"paper": (255, 250, 200, 255)}),
        )
        assert pc.paper_color == (255, 250, 200, 255)
        assert pc.paper_color != original

    def test_set_enabled_gates_toggle(self):
        from slappyengine.ui.widgets import PaperClipAttachment

        pc = PaperClipAttachment("Notes")
        pc.set_enabled(False)
        # Toggle is a no-op while disabled.
        pc.toggle()
        assert pc.expanded is False
        pc.set_enabled(True)
        pc.toggle()
        assert pc.expanded is True

    def test_toggle_fires_callbacks(self):
        from slappyengine.ui.widgets import PaperClipAttachment

        clicks: list[bool] = []
        changes: list[bool] = []
        pc = PaperClipAttachment(
            "Notes",
            on_click=lambda v: clicks.append(v),
            on_change=lambda v: changes.append(v),
        )
        pc.toggle()
        assert clicks == [True]
        assert changes == [True]

    def test_add_child_appends(self):
        from slappyengine.ui.widgets import PaperClipAttachment

        pc = PaperClipAttachment("Notes")
        pc.add_child(lambda: None)
        pc.add_child(lambda: None)
        assert len(pc.children) == 2


# ===========================================================================
# WashiTapeDivider
# ===========================================================================

class TestWashiTapeDivider:
    def test_instantiates_and_mounts(self, stub_dpg):
        from slappyengine.ui.widgets import WashiTapeDivider

        w = WashiTapeDivider("tape_pink_dots", length_px=100)
        w.mount("parent")
        assert w.root_tag is not None
        assert "add_text" in stub_dpg.calls or "add_separator" in stub_dpg.calls

    def test_set_theme_rebinds_palette(self):
        from slappyengine.ui.widgets import (
            NotebookTheme,
            WashiTapeDivider,
        )

        w = WashiTapeDivider("tape_pink_dots", length_px=100)
        original = w.washi_color
        w.set_theme(
            NotebookTheme(palette={"washi": (200, 100, 255, 255)}),
        )
        assert w.washi_color == (200, 100, 255, 255)
        assert w.washi_color != original

    def test_set_enabled_toggles_state(self, stub_dpg):
        from slappyengine.ui.widgets import WashiTapeDivider

        w = WashiTapeDivider("tape_pink_dots", length_px=100)
        w.mount("parent")
        w.set_enabled(False)
        assert w.enabled is False
        w.set_enabled(True)
        assert w.enabled is True

    def test_tape_style_resolves_via_soft_import(self):
        from slappyengine.ui.widgets import WashiTapeDivider

        w = WashiTapeDivider("tape_pink_dots", length_px=100)
        # T2 library ships this id.
        assert w.tape_resolved is True
        assert w.tape_display_name != "tape_pink_dots"

    def test_unknown_tape_id_falls_back(self):
        from slappyengine.ui.widgets import WashiTapeDivider

        w = WashiTapeDivider("tape_does_not_exist", length_px=100)
        assert w.tape_resolved is False
        assert w.tape_display_name == "tape_does_not_exist"

    def test_rotation_clamped(self):
        from slappyengine.ui.widgets import WashiTapeDivider

        w = WashiTapeDivider(
            "tape_pink_dots", length_px=100, rotation_deg=180.0,
        )
        assert w.rotation_deg == 45.0
        w.set_rotation(-999.0)
        assert w.rotation_deg == -45.0


# ===========================================================================
# SketchButton
# ===========================================================================

class TestSketchButton:
    def test_instantiates_and_mounts(self, stub_dpg):
        from slappyengine.ui.widgets import SketchButton

        sb = SketchButton("OK", lambda *a: None)
        sb.mount("parent")
        assert sb.root_tag is not None
        assert "add_button" in stub_dpg.calls

    def test_set_theme_rebinds_palette(self):
        from slappyengine.ui.widgets import (
            NotebookTheme,
            SketchButton,
        )

        sb = SketchButton("OK", lambda *a: None)
        original = sb.accent_color
        sb.set_theme(
            NotebookTheme(palette={"accent": (0, 128, 255, 255)}),
        )
        assert sb.accent_color == (0, 128, 255, 255)
        assert sb.accent_color != original

    def test_set_enabled_gates_click(self):
        from slappyengine.ui.widgets import SketchButton

        clicks: list = []
        sb = SketchButton("OK", lambda *a: clicks.append(1))
        sb.set_enabled(False)
        sb.click()
        assert clicks == []  # click gated by disabled state
        sb.set_enabled(True)
        sb.click()
        assert clicks == [1]

    def test_hover_ramps_wobble(self):
        from slappyengine.ui.widgets import SketchButton

        sb = SketchButton("OK", lambda *a: None, wobble_amount=4.0)
        assert sb.wobble_scale == 1.0
        sb.set_hover(True)
        assert sb.wobble_scale == 1.25
        sb.set_hover(False)
        assert sb.wobble_scale == 1.0

    def test_wobble_polyline_length_matches_segments(self):
        from slappyengine.ui.widgets import SketchButton

        sb = SketchButton("OK", lambda *a: None, segments=16)
        pts = sb.wobble_polyline()
        assert len(pts) == 16
        # Deterministic — same seed produces the same polyline.
        assert pts == sb.wobble_polyline()


# ===========================================================================
# InkStampBadge
# ===========================================================================

class TestInkStampBadge:
    def test_instantiates_and_mounts(self, stub_dpg):
        from slappyengine.ui.widgets import InkStampBadge

        badge = InkStampBadge("DONE", icon="*")
        badge.mount("parent")
        assert badge.root_tag is not None
        assert "add_button" in stub_dpg.calls

    def test_set_theme_rebinds_palette(self):
        from slappyengine.ui.widgets import (
            InkStampBadge,
            NotebookTheme,
        )

        badge = InkStampBadge("DONE", color_slot="accent")
        original = badge.stamp_color
        badge.set_theme(
            NotebookTheme(palette={"accent": (255, 0, 0, 255)}),
        )
        assert badge.stamp_color == (255, 0, 0, 255)
        assert badge.stamp_color != original
        # Rim is a darkened stamp.
        assert badge.rim_color[0] < badge.stamp_color[0] or badge.stamp_color[0] == 0

    def test_set_enabled_gates_click(self):
        from slappyengine.ui.widgets import InkStampBadge

        clicks: list = []
        badge = InkStampBadge(
            "DONE", on_click=lambda w: clicks.append(w.label),
        )
        badge.set_enabled(False)
        badge.click()
        assert clicks == []
        badge.set_enabled(True)
        badge.click()
        assert clicks == ["DONE"]

    def test_color_slot_swap(self):
        from slappyengine.ui.widgets import (
            InkStampBadge,
            NotebookTheme,
            set_active_theme,
        )

        set_active_theme(
            NotebookTheme(
                palette={
                    "accent": (10, 10, 10, 255),
                    "heart": (255, 30, 60, 255),
                },
            )
        )
        badge = InkStampBadge("DONE", color_slot="accent")
        assert badge.stamp_color == (10, 10, 10, 255)
        badge.set_color_slot("heart")
        assert badge.stamp_color == (255, 30, 60, 255)

    def test_rejects_bad_color_slot(self):
        from slappyengine.ui.widgets import InkStampBadge

        with pytest.raises(ValueError):
            InkStampBadge("DONE", color_slot="bogus")


# ===========================================================================
# Public-surface exports
# ===========================================================================

class TestPublicSurface:
    def test_all_widgets_reachable_from_package(self):
        import slappyengine.ui.widgets as pkg

        for name in (
            "GlitterProgressBar",
            "RibbonTab",
            "PaperClipAttachment",
            "WashiTapeDivider",
            "SketchButton",
            "InkStampBadge",
        ):
            assert name in pkg.__all__, name
            assert hasattr(pkg, name), name

    def test_all_widgets_share_notebook_widget_base(self):
        from slappyengine.ui.widgets import (
            GlitterProgressBar,
            InkStampBadge,
            PaperClipAttachment,
            RibbonTab,
            SketchButton,
            WashiTapeDivider,
        )
        from slappyengine.ui.widgets._dpg_base import _NotebookWidget

        classes = [
            GlitterProgressBar,
            InkStampBadge,
            PaperClipAttachment,
            RibbonTab,
            SketchButton,
            WashiTapeDivider,
        ]
        for cls in classes:
            assert issubclass(cls, _NotebookWidget)
