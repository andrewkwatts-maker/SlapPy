"""Tests for the notebook-themed widget primitives.

Every widget is exercised in a *headless* DPG context: the test stubs
``dearpygui.dearpygui`` with a no-op shim so the widgets can call into
``build()`` without a real GUI.  The widgets also have to construct
cleanly when DPG is not even importable (the slapping case for plain
CI runners), so the import is deferred to ``build()`` time and every
DPG call is guarded.

Coverage focuses on the four invariants the task spec calls out:

1. Each widget constructs without DPG context errors.
2. Theme application changes the rendered appearance.
3. Callbacks fire correctly.
4. Sticker corners can be added / removed at runtime.

Plus the validator contract — bad inputs raise ``TypeError`` /
``ValueError`` through the shared ``pharos_engine._validation`` helpers.
"""
from __future__ import annotations

import sys
import types
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub — accepts both context-manager calls (``with dpg.group()``)
# and plain method calls.  Every method records its call site so tests can
# assert "did this widget actually attempt a build?".
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
    """Minimal dearpygui surface with call-tracking."""

    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: set[str] = set()

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    # context-manager primitives the widgets use
    def group(self, *args, **kwargs):
        self._track("group", args, kwargs)
        return _StubCM(self.calls, "group")

    def child_window(self, *args, **kwargs):
        self._track("child_window", args, kwargs)
        return _StubCM(self.calls, "child_window")

    def tab(self, *args, **kwargs):
        self._track("tab", args, kwargs)
        return _StubCM(self.calls, "tab")

    # plain widget primitives
    def add_text(self, *args, **kwargs):
        self._track("add_text", args, kwargs)

    def add_button(self, *args, **kwargs):
        self._track("add_button", args, kwargs)

    def add_checkbox(self, *args, **kwargs):
        self._track("add_checkbox", args, kwargs)

    def add_slider_float(self, *args, **kwargs):
        self._track("add_slider_float", args, kwargs)

    def add_separator(self, *args, **kwargs):
        self._track("add_separator", args, kwargs)

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
    # Make any unknown attribute resolve to a recording no-op so the
    # widgets don't crash when they call a method we haven't stubbed.
    def _fallback(name):
        if hasattr(stub, name):
            return getattr(stub, name)
        def _noop(*a, **kw):
            stub.calls.setdefault(name, []).append((a, kw))
        return _noop
    mod.__getattr__ = _fallback
    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    # Patch every relevant attribute the widget code touches.
    for name in (
        "group", "child_window", "tab", "add_text", "add_button",
        "add_checkbox", "add_slider_float", "add_separator",
        "delete_item", "does_item_exist",
    ):
        setattr(mod, name, getattr(stub, name))
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


@pytest.fixture(autouse=True)
def clear_theme():
    """Reset the active theme + sticker registry between tests."""
    from pharos_engine.ui.widgets.notebook_theme import set_active_theme
    from pharos_engine.ui.widgets.sticker_corner import _active_stickers

    set_active_theme(None)
    _active_stickers.clear()
    yield
    set_active_theme(None)
    _active_stickers.clear()


# ===========================================================================
# Theme registry
# ===========================================================================

class TestThemeRegistry:
    def test_no_theme_active_by_default(self):
        from pharos_engine.ui.widgets import get_active_theme

        assert get_active_theme() is None

    def test_set_active_theme_round_trips(self):
        from pharos_engine.ui.widgets import (
            NotebookTheme,
            get_active_theme,
            set_active_theme,
        )

        theme = NotebookTheme(name="teen_girl")
        set_active_theme(theme)
        assert get_active_theme() is theme

    def test_set_active_theme_clears_with_none(self):
        from pharos_engine.ui.widgets import (
            NotebookTheme,
            get_active_theme,
            set_active_theme,
        )

        set_active_theme(NotebookTheme(name="foo"))
        set_active_theme(None)
        assert get_active_theme() is None

    def test_set_active_theme_rejects_non_theme(self):
        from pharos_engine.ui.widgets import set_active_theme

        with pytest.raises(TypeError):
            set_active_theme("not a theme")  # type: ignore[arg-type]

    def test_resolve_theme_returns_fallback_when_no_theme(self):
        from pharos_engine.ui.widgets import resolve_theme

        theme = resolve_theme()
        assert theme is not None
        # Fallback ships an ink palette entry so widgets can read it.
        assert theme.color("ink")[3] == 255


# ===========================================================================
# StickerButton
# ===========================================================================

class TestStickerButton:
    def test_constructs_without_dpg(self):
        from pharos_engine.ui.widgets import StickerButton

        sb = StickerButton("Save", "star", lambda *_: None)
        assert sb.label == "Save"
        assert sb.sticker_icon == "star"

    def test_rejects_empty_label(self):
        from pharos_engine.ui.widgets import StickerButton

        with pytest.raises(ValueError):
            StickerButton("", "star", lambda *_: None)

    def test_rejects_non_callable(self):
        from pharos_engine.ui.widgets import StickerButton

        with pytest.raises(TypeError):
            StickerButton("Save", "star", "not callable")  # type: ignore[arg-type]

    def test_theme_application_changes_accent(self):
        from pharos_engine.ui.widgets import (
            NotebookTheme,
            StickerButton,
            set_active_theme,
        )

        theme = NotebookTheme(
            name="hot_pink",
            palette={"accent": (255, 0, 200, 255), "ink": (10, 10, 10, 255)},
        )
        set_active_theme(theme)
        sb = StickerButton("Save", "star", lambda *_: None)
        assert sb.accent_color == (255, 0, 200, 255)

    def test_rotation_clamped(self):
        from pharos_engine.ui.widgets import StickerButton

        sb = StickerButton("Save", "star", lambda *_: None, rotation=99.0)
        assert sb.rotation == 15.0

    def test_build_registers_dpg_root(self, stub_dpg):
        from pharos_engine.ui.widgets import StickerButton

        sb = StickerButton("Save", "star", lambda *_: None)
        sb.build("parent_x")
        assert sb.root_tag is not None
        assert "add_button" in stub_dpg.calls or "group" in stub_dpg.calls

    def test_destroy_clears_built_flag(self, stub_dpg):
        from pharos_engine.ui.widgets import StickerButton

        sb = StickerButton("Save", "star", lambda *_: None)
        sb.build("parent_x")
        assert sb.root_tag is not None
        sb.destroy()
        assert sb.root_tag is None


# ===========================================================================
# WashiPanel
# ===========================================================================

class TestWashiPanel:
    def test_constructs_with_no_children(self):
        from pharos_engine.ui.widgets import WashiPanel

        wp = WashiPanel("Settings")
        assert wp.title == "Settings"
        assert wp.children == []

    def test_rejects_non_callable_child(self):
        from pharos_engine.ui.widgets import WashiPanel

        with pytest.raises(TypeError):
            WashiPanel("Settings", ["not callable"])  # type: ignore[list-item]

    def test_add_child_appends(self):
        from pharos_engine.ui.widgets import WashiPanel

        wp = WashiPanel("Settings")
        wp.add_child(lambda: None)
        wp.add_child(lambda: None)
        assert len(wp.children) == 2

    def test_theme_application_changes_tape_color(self):
        from pharos_engine.ui.widgets import (
            NotebookTheme,
            WashiPanel,
            set_active_theme,
        )

        theme = NotebookTheme(
            name="pastel",
            palette={"washi": (255, 200, 220, 255)},
        )
        set_active_theme(theme)
        wp = WashiPanel("Settings")
        assert wp.tape_color == (255, 200, 220, 255)

    def test_build_runs_children(self, stub_dpg):
        from pharos_engine.ui.widgets import WashiPanel

        ran = []
        wp = WashiPanel("Settings", [lambda: ran.append(1)])
        wp.build("parent_x")
        # Child should have been invoked during build.
        assert ran == [1]


# ===========================================================================
# NotebookTab
# ===========================================================================

class TestNotebookTab:
    def test_constructs(self):
        from pharos_engine.ui.widgets import NotebookTab

        tab = NotebookTab("Overview")
        assert tab.label == "Overview"

    def test_rejects_non_callable_children(self):
        from pharos_engine.ui.widgets import NotebookTab

        with pytest.raises(TypeError):
            NotebookTab("Overview", [42])  # type: ignore[list-item]

    def test_theme_application_changes_paper(self):
        from pharos_engine.ui.widgets import (
            NotebookTab,
            NotebookTheme,
            set_active_theme,
        )

        set_active_theme(
            NotebookTheme(
                name="paper",
                palette={"paper": (255, 255, 240, 255)},
            )
        )
        tab = NotebookTab("Overview")
        assert tab.paper_color == (255, 255, 240, 255)


# ===========================================================================
# HighlighterSlider
# ===========================================================================

class TestHighlighterSlider:
    def test_constructs(self):
        from pharos_engine.ui.widgets import HighlighterSlider

        sl = HighlighterSlider("Volume", 0.5, 0.0, 1.0, lambda v: None)
        assert sl.value == 0.5

    def test_clamps_initial_value(self):
        from pharos_engine.ui.widgets import HighlighterSlider

        sl = HighlighterSlider("Volume", 2.0, 0.0, 1.0, lambda v: None)
        assert sl.value == 1.0

    def test_rejects_min_geq_max(self):
        from pharos_engine.ui.widgets import HighlighterSlider

        with pytest.raises(ValueError):
            HighlighterSlider("Volume", 0.5, 1.0, 1.0, lambda v: None)

    def test_callback_fires_on_set_value(self):
        from pharos_engine.ui.widgets import HighlighterSlider

        seen: list[float] = []
        sl = HighlighterSlider("Volume", 0.5, 0.0, 1.0, lambda v: seen.append(v))
        sl.set_value(0.75)
        assert seen == [0.75]

    def test_theme_application_changes_highlight_color(self):
        from pharos_engine.ui.widgets import (
            HighlighterSlider,
            NotebookTheme,
            set_active_theme,
        )

        set_active_theme(
            NotebookTheme(
                name="lemon",
                palette={"highlight": (200, 250, 80, 220)},
            )
        )
        sl = HighlighterSlider("Volume", 0.5, 0.0, 1.0, lambda v: None)
        assert sl.highlight_color == (200, 250, 80, 220)

    def test_build_invokes_dpg(self, stub_dpg):
        from pharos_engine.ui.widgets import HighlighterSlider

        sl = HighlighterSlider("Volume", 0.5, 0.0, 1.0, lambda v: None)
        sl.build("parent")
        assert "add_slider_float" in stub_dpg.calls


# ===========================================================================
# HeartCheckbox
# ===========================================================================

class TestHeartCheckbox:
    def test_constructs(self):
        from pharos_engine.ui.widgets import HeartCheckbox

        hc = HeartCheckbox("Cute mode", False, lambda v: None)
        assert hc.value is False

    def test_rejects_non_bool_value(self):
        from pharos_engine.ui.widgets import HeartCheckbox

        with pytest.raises(TypeError):
            HeartCheckbox("Cute mode", 1, lambda v: None)  # type: ignore[arg-type]

    def test_toggle_fires_callback(self):
        from pharos_engine.ui.widgets import HeartCheckbox

        seen: list[bool] = []
        hc = HeartCheckbox("Cute mode", False, lambda v: seen.append(v))
        hc.toggle()
        assert hc.value is True
        assert seen == [True]

    def test_set_value_fires_callback(self):
        from pharos_engine.ui.widgets import HeartCheckbox

        seen: list[bool] = []
        hc = HeartCheckbox("Cute mode", False, lambda v: seen.append(v))
        hc.set_value(True)
        assert hc.value is True
        assert seen == [True]

    def test_theme_application_changes_heart_color(self):
        from pharos_engine.ui.widgets import (
            HeartCheckbox,
            NotebookTheme,
            set_active_theme,
        )

        set_active_theme(
            NotebookTheme(
                name="cherry",
                palette={"heart": (255, 30, 60, 255)},
            )
        )
        hc = HeartCheckbox("Cute mode", False, lambda v: None)
        assert hc.heart_color == (255, 30, 60, 255)


# ===========================================================================
# DoodleSeparator
# ===========================================================================

class TestDoodleSeparator:
    def test_default_style_is_wavy(self):
        from pharos_engine.ui.widgets import DoodleSeparator

        sep = DoodleSeparator()
        assert sep.style == "wavy"

    @pytest.mark.parametrize("style", ["wavy", "dotted", "star_chain"])
    def test_accepts_each_style(self, style):
        from pharos_engine.ui.widgets import DoodleSeparator

        sep = DoodleSeparator(style)
        assert sep.style == style
        assert sep.glyph  # non-empty

    def test_rejects_invalid_style(self):
        from pharos_engine.ui.widgets import DoodleSeparator

        with pytest.raises(ValueError):
            DoodleSeparator("squiggly")

    def test_build_invokes_dpg(self, stub_dpg):
        from pharos_engine.ui.widgets import DoodleSeparator

        sep = DoodleSeparator("dotted")
        sep.build("parent")
        # Either add_text or add_separator should have been called.
        assert (
            "add_text" in stub_dpg.calls or "add_separator" in stub_dpg.calls
        )


# ===========================================================================
# Sticker corners
# ===========================================================================

class TestStickerCorners:
    def test_add_returns_handle(self):
        from pharos_engine.ui.widgets import add_sticker_corner

        handle = add_sticker_corner("panel_1", "heart", "TR")
        assert isinstance(handle, str)
        assert handle

    def test_remove_returns_true_for_known_handle(self):
        from pharos_engine.ui.widgets import (
            add_sticker_corner,
            remove_sticker_corner,
        )

        h = add_sticker_corner("panel_1", "heart", "TR")
        assert remove_sticker_corner(h) is True
        assert remove_sticker_corner(h) is False  # idempotent

    def test_list_filters_by_parent(self):
        from pharos_engine.ui.widgets import (
            add_sticker_corner,
            list_sticker_corners,
        )

        add_sticker_corner("panel_1", "heart", "TR")
        add_sticker_corner("panel_2", "star", "BL")
        add_sticker_corner("panel_2", "star", "TR")
        assert len(list_sticker_corners("panel_1")) == 1
        assert len(list_sticker_corners("panel_2")) == 2
        assert len(list_sticker_corners()) == 3

    def test_add_rejects_empty_sticker_id(self):
        from pharos_engine.ui.widgets import add_sticker_corner

        with pytest.raises(ValueError):
            add_sticker_corner("panel_1", "", "TR")

    def test_add_rejects_invalid_corner(self):
        from pharos_engine.ui.widgets import add_sticker_corner

        with pytest.raises(ValueError):
            add_sticker_corner("panel_1", "heart", "XY")

    def test_corner_case_insensitive(self):
        from pharos_engine.ui.widgets import add_sticker_corner

        # lowercase should be accepted and round-trip uppercased internally
        h = add_sticker_corner("panel_1", "heart", "tl")
        assert h  # didn't raise

    def test_remove_unknown_handle_raises_on_bad_type(self):
        from pharos_engine.ui.widgets import remove_sticker_corner

        with pytest.raises(TypeError):
            remove_sticker_corner(42)  # type: ignore[arg-type]


# ===========================================================================
# Cross-cutting: theme listener refreshes built widgets
# ===========================================================================

class TestThemeListener:
    def test_listener_invoked_on_set_active_theme(self):
        from pharos_engine.ui.widgets import (
            NotebookTheme,
            register_theme_listener,
            set_active_theme,
            unregister_theme_listener,
        )

        seen: list[Any] = []
        cb = lambda t: seen.append(t)
        register_theme_listener(cb)
        set_active_theme(NotebookTheme(name="x"))
        assert len(seen) == 1
        set_active_theme(None)
        assert len(seen) == 2
        unregister_theme_listener(cb)
        set_active_theme(NotebookTheme(name="y"))
        assert len(seen) == 2  # no further callback after unregister

    def test_widget_refresh_after_theme_change(self):
        from pharos_engine.ui.widgets import (
            NotebookTheme,
            StickerButton,
            set_active_theme,
        )

        sb = StickerButton("Save", "heart", lambda *_: None)
        old = sb.accent_color
        set_active_theme(
            NotebookTheme(
                name="bright",
                palette={"accent": (0, 255, 0, 255)},
            )
        )
        # Live refresh: the listener updated the cached accent.
        assert sb.accent_color == (0, 255, 0, 255)
        assert sb.accent_color != old
