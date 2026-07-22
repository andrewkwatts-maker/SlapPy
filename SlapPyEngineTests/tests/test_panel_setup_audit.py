"""Audit regression tests for :meth:`EditorShell.setup`'s panel layer.

These tests fence the fixes landed alongside the 2026-06-07 audit:

* The notebook status bar must end up wrapped in a movable window
  and its ``build`` must be invoked (so the DPG window is created
  and the inner separator/text/button widgets are emitted).
* The status bar window must sit on the bottom edge of the viewport
  and stay fixed there — no drag, no resize, no title bar.
* Every panel registered via :meth:`register_panel` must be wrapped
  in a :class:`MovablePanelWindow` so it owns its own movable
  dpg.window — instead of being trapped inside the legacy
  ``editor_root`` child window.
* Floating panels (theme switcher, spawn menu, code panel, material
  editor, welcome, project picker) default to ``visible=False`` and
  hand ``show=False`` to ``dpg.window`` so they don't flash on boot.
* :meth:`toggle_panel` shows + focuses the panel when revealing it,
  and hides it when toggling it off the second time.

The fixture stubs the entirety of ``dearpygui.dearpygui`` so the
audit can run headless.
"""
from __future__ import annotations

import sys
import types
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub — tracks ``window`` / ``configure_item`` / ``show_item``
# / ``focus_item`` calls and the set of tags created.
# ---------------------------------------------------------------------------


class _StubCM:
    def __init__(self, recorder, name, kwargs):
        self._recorder = recorder
        self._name = name
        self._kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StubDPG:
    """Recording stand-in for ``dearpygui.dearpygui``."""

    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: dict[str, dict[str, Any]] = {}
        self.shown: set[str] = set()
        self.focused: list[str] = []

    # -- bookkeeping -------------------------------------------------
    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))

    # -- window / container ------------------------------------------
    def window(self, *args, **kwargs):
        self._track("window", args, kwargs)
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items[tag] = dict(kwargs)
            if kwargs.get("show", True):
                self.shown.add(tag)
        return _StubCM(self.calls, "window", kwargs)

    # Generic add_* widgets — silent no-ops that still register the tag.
    def _generic_add(self, kind: str, *args, **kwargs):
        self._track(kind, args, kwargs)
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items[tag] = dict(kwargs)
        return tag

    def __getattr__(self, name: str):
        # Default to a tag-tracking no-op for any other DPG widget call.
        if name.startswith("add_"):
            return lambda *a, **k: self._generic_add(name, *a, **k)
        return lambda *a, **k: None

    # -- explicit overrides ------------------------------------------
    def add_separator(self, *args, **kwargs):
        return self._generic_add("add_separator", *args, **kwargs)

    def add_text(self, *args, **kwargs):
        return self._generic_add("add_text", *args, **kwargs)

    def add_button(self, *args, **kwargs):
        return self._generic_add("add_button", *args, **kwargs)

    def group(self, *args, **kwargs):
        self._track("group", args, kwargs)
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items[tag] = dict(kwargs)
        return _StubCM(self.calls, "group", kwargs)

    def configure_item(self, tag, *args, **kwargs):
        self._track("configure_item", (tag,) + args, kwargs)
        if isinstance(tag, str) and tag in self.items:
            self.items[tag].update(kwargs)
            if "show" in kwargs:
                if kwargs["show"]:
                    self.shown.add(tag)
                else:
                    self.shown.discard(tag)

    def does_item_exist(self, tag, *args, **kwargs):
        return isinstance(tag, str) and tag in self.items

    def show_item(self, tag, *args, **kwargs):
        self._track("show_item", (tag,) + args, kwargs)
        if isinstance(tag, str) and tag in self.items:
            self.shown.add(tag)
            self.items[tag]["show"] = True

    def hide_item(self, tag, *args, **kwargs):
        self._track("hide_item", (tag,) + args, kwargs)
        if isinstance(tag, str) and tag in self.items:
            self.shown.discard(tag)
            self.items[tag]["show"] = False

    def focus_item(self, tag, *args, **kwargs):
        self._track("focus_item", (tag,) + args, kwargs)
        if isinstance(tag, str):
            self.focused.append(tag)

    def bind_item_theme(self, *args, **kwargs):
        self._track("bind_item_theme", args, kwargs)


@pytest.fixture
def stub_dpg(monkeypatch):
    """Install a fresh recording stub for ``dearpygui.dearpygui``."""
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    for name in (
        "window", "configure_item", "does_item_exist", "show_item",
        "hide_item", "focus_item", "bind_item_theme", "add_separator",
        "add_text", "add_button", "group",
    ):
        setattr(mod, name, getattr(stub, name))
    # Fallback for add_* / other widget calls — pass through to the stub.
    mod.__getattr__ = lambda name: getattr(stub, name)
    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    return stub


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_theme_registry():
    from pharos_engine.ui.theme import _reset_registry_for_tests
    from pharos_engine.ui.widgets import notebook_theme
    from pharos_engine.ui.theme.creatures import (
        _reset_default_scheduler_for_tests,
    )

    # Wipe the listener list directly — `set_active_theme(None)` would
    # otherwise broadcast to widgets registered by an earlier test and
    # crash when those widgets touch the real (uninitialised) DPG.
    def _wipe():
        _reset_registry_for_tests()
        notebook_theme._active_theme = None
        notebook_theme._theme_listeners.clear()
        _reset_default_scheduler_for_tests()

    _wipe()
    yield
    _wipe()


def _make_shell():
    """Build an :class:`EditorShell` against a minimal engine stub."""
    from pharos_engine.ui.editor.shell import EditorShell

    class _StubEngine:
        def __init__(self):
            self.scene = None

    return EditorShell(_StubEngine())


def _wire_default_panels(shell):
    """Run the headless subset of ``setup`` so the layout has every slot."""
    shell.setup_theme_subsystem()
    shell.setup_notebook_panels()
    # Content browser is lazily built by setup() — instantiate one
    # manually so compose_default_panel_layout has a target to wrap.
    from pharos_engine.ui.editor.notebook_content_browser import (
        NotebookContentBrowser,
    )
    shell._content_browser = NotebookContentBrowser(
        on_open_scene=lambda *_: None,
        on_open_script=lambda *_: None,
        on_open_asset=lambda *_: None,
    )
    return shell


# ---------------------------------------------------------------------------
# Synthetic panel classes for the legacy register_panel path.
# ---------------------------------------------------------------------------


class _CustomPanel:
    """Plug-in style panel that doesn't match any named slot."""

    TITLE = "Custom"

    def __init__(self) -> None:
        self.builds: list = []

    def build(self, parent_tag) -> None:
        self.builds.append(parent_tag)


class _SecondPanel:
    TITLE = "Second"

    def __init__(self) -> None:
        self.builds: list = []

    def build(self, parent_tag) -> None:
        self.builds.append(parent_tag)


# ---------------------------------------------------------------------------
# Status bar — build + position + chrome
# ---------------------------------------------------------------------------


class TestStatusBar:
    def test_status_bar_wrapper_present(self):
        shell = _wire_default_panels(_make_shell())
        windows = shell.compose_default_panel_layout()
        assert "status_bar" in windows

    def test_status_bar_position_is_bottom_minus_24(self):
        shell = _wire_default_panels(_make_shell())
        windows = shell.compose_default_panel_layout()
        sb = windows["status_bar"]
        _, y = sb.get_position()
        # ``setup`` pegs the bar to ``viewport_height - 24``.
        assert y == shell._height - 24

    def test_status_bar_no_title_bar(self):
        shell = _wire_default_panels(_make_shell())
        windows = shell.compose_default_panel_layout()
        assert windows["status_bar"].no_title_bar is True

    def test_status_bar_no_move(self):
        shell = _wire_default_panels(_make_shell())
        windows = shell.compose_default_panel_layout()
        assert windows["status_bar"].no_move is True

    def test_status_bar_no_resize(self):
        shell = _wire_default_panels(_make_shell())
        windows = shell.compose_default_panel_layout()
        assert windows["status_bar"].no_resize is True

    def test_status_bar_build_creates_window(self, stub_dpg):
        shell = _wire_default_panels(_make_shell())
        windows = shell.compose_default_panel_layout()
        sb = windows["status_bar"]
        sb.build()
        tag = sb.get_window_tag()
        # Window tag is registered in the stubbed DPG state.
        assert tag in stub_dpg.items
        # Inner status bar widgets emit at least one ``add_text``.
        text_calls = stub_dpg.calls.get("add_text", [])
        assert len(text_calls) >= 1

    def test_status_bar_panel_build_invoked(self, stub_dpg):
        shell = _wire_default_panels(_make_shell())
        windows = shell.compose_default_panel_layout()
        sb = windows["status_bar"]
        sb.build()
        # NotebookStatusBar flips _built when its build runs.
        assert shell._notebook_status_bar._built is True


# ---------------------------------------------------------------------------
# Panel registry — every shell panel ends up in _panel_windows.
# ---------------------------------------------------------------------------


class TestPanelRegistry:
    def test_every_named_panel_in_windows(self):
        shell = _wire_default_panels(_make_shell())
        shell.compose_default_panel_layout()
        keys = set(shell._panel_windows.keys())
        # Notebook core surfaces.
        assert "toolbar" in keys
        assert "outliner" in keys
        assert "inspector" in keys
        assert "content_browser" in keys
        assert "status_bar" in keys
        assert "theme_switcher" in keys

    def test_register_panel_appends_to_panels_list(self):
        shell = _wire_default_panels(_make_shell())
        custom = _CustomPanel()
        shell.register_panel(custom)
        assert custom in shell._panels

    def test_register_panel_routes_to_slot_for_known_kind(self):
        """A ``NotebookInspector`` passed to register_panel fills ``_inspector``."""
        from pharos_engine.ui.editor.notebook_inspector import NotebookInspector

        shell = _make_shell()
        shell.setup_theme_subsystem()
        # Don't run setup_notebook_panels — it pre-fills _inspector.
        inspector = NotebookInspector()
        shell.register_panel(inspector)
        assert shell._inspector is inspector

    def test_legacy_panel_wrapped_in_movable_window(self):
        """A custom register_panel entry ends up in ``_panel_windows``."""
        shell = _wire_default_panels(_make_shell())
        custom = _CustomPanel()
        shell.register_panel(custom)
        shell.compose_default_panel_layout()
        # The wrapper key derives from the class name (lowercased).
        wrappers = [
            w for w in shell._panel_windows.values()
            if w.panel is custom
        ]
        assert len(wrappers) == 1

    def test_multiple_legacy_panels_each_get_a_wrapper(self):
        shell = _wire_default_panels(_make_shell())
        a, b = _CustomPanel(), _SecondPanel()
        shell.register_panel(a)
        shell.register_panel(b)
        shell.compose_default_panel_layout()
        wrapped = {id(w.panel) for w in shell._panel_windows.values()}
        assert id(a) in wrapped
        assert id(b) in wrapped


# ---------------------------------------------------------------------------
# Floating-panel default visibility — hidden until summoned.
# ---------------------------------------------------------------------------


class TestFloatingPanelVisibility:
    @pytest.mark.parametrize(
        "key",
        ["theme_switcher", "spawn_menu", "code_panel", "material_editor",
         "welcome", "project_picker"],
    )
    def test_floating_panels_default_to_hidden(self, key, monkeypatch):
        """All floating-by-default panels report ``is_visible() == False``."""
        shell = _wire_default_panels(_make_shell())
        # Wire the optional floating panels — compose_default_panel_layout
        # only emits a wrapper when the underlying panel is non-None.
        from pharos_engine.ui.editor.notebook_welcome import NotebookWelcome
        from pharos_engine.ui.editor.notebook_project_picker import (
            NotebookProjectPicker,
        )
        from pharos_engine.ui.editor.notebook_material_editor import (
            NotebookMaterialEditor,
        )
        from pharos_engine.ui.editor.notebook_code_panel import (
            NotebookCodePanel,
        )

        class _StubSpawn:
            TITLE = "Spawn"

            def build(self, parent_tag):
                pass

        shell._welcome_panel = NotebookWelcome(
            settings=shell._ui_settings,
            on_start_blank=lambda *_: None,
            on_open_demo=lambda *_: None,
            on_dismiss=lambda *_: None,
        )
        shell._project_picker = NotebookProjectPicker()
        shell._material_editor = NotebookMaterialEditor()
        shell._code_mode_panel = NotebookCodePanel()
        shell._spawn_menu_panel = _StubSpawn()
        shell.compose_default_panel_layout()
        wrapper = shell._panel_windows.get(key)
        assert wrapper is not None, f"missing wrapper for {key}"
        assert wrapper.is_visible() is False

    def test_hidden_panel_build_sends_show_false_to_dpg(self, stub_dpg):
        shell = _wire_default_panels(_make_shell())
        shell.compose_default_panel_layout()
        ts = shell._panel_windows["theme_switcher"]
        ts.build()
        tag = ts.get_window_tag()
        # dpg.window was called with show=False (mirroring is_visible=False).
        kwargs = stub_dpg.items[tag]
        assert kwargs["show"] is False


# ---------------------------------------------------------------------------
# toggle_panel — shows + focuses on reveal, hides on second toggle.
# ---------------------------------------------------------------------------


class TestTogglePanel:
    def test_toggle_panel_shows_then_focuses_on_reveal(self, stub_dpg):
        shell = _wire_default_panels(_make_shell())
        shell.compose_default_panel_layout()
        # Build everything so DPG knows the tags.
        for w in shell._panel_windows.values():
            w.build()
        shell._running = True

        # theme_switcher starts hidden — toggling should reveal it.
        new_visible = shell.toggle_panel("theme_switcher")
        assert new_visible is True

        tag = shell._panel_windows["theme_switcher"].get_window_tag()
        assert tag in stub_dpg.focused

    def test_toggle_panel_hides_on_second_toggle(self, stub_dpg):
        shell = _wire_default_panels(_make_shell())
        shell.compose_default_panel_layout()
        for w in shell._panel_windows.values():
            w.build()
        shell._running = True

        # First toggle — reveal.
        shell.toggle_panel("theme_switcher")
        # Second toggle — hide.
        new_visible = shell.toggle_panel("theme_switcher")
        assert new_visible is False
        wrapper = shell._panel_windows["theme_switcher"]
        assert wrapper.is_visible() is False

    def test_toggle_panel_updates_wrapper_visibility(self):
        """``toggle_panel`` flips the wrapper's tracked ``_visible``."""
        shell = _wire_default_panels(_make_shell())
        shell.compose_default_panel_layout()
        wrapper = shell._panel_windows["theme_switcher"]
        assert wrapper.is_visible() is False
        shell.toggle_panel("theme_switcher")
        assert wrapper.is_visible() is True

    def test_toggle_panel_returns_new_state(self):
        shell = _wire_default_panels(_make_shell())
        shell.compose_default_panel_layout()
        first = shell.toggle_panel("theme_switcher")
        second = shell.toggle_panel("theme_switcher")
        assert first != second


# ---------------------------------------------------------------------------
# MovablePanelWindow.set_size — min-size clamp regression check.
# ---------------------------------------------------------------------------


class TestMinSizeClamp:
    def test_set_size_clamps_to_min(self):
        """Audit fix #4 — set_size enforces min before configure_item."""
        from pharos_engine.ui.editor.movable_panel import MovablePanelWindow

        class _Panel:
            def build(self, parent_tag):
                pass

        win = MovablePanelWindow(_Panel(), min_size=(300, 200))
        win.set_size(100, 50)
        assert win.get_size() == (300, 200)

    def test_min_size_passed_to_dpg_window(self, stub_dpg):
        """``min_size`` flows through to ``dpg.window`` as a 2-list."""
        from pharos_engine.ui.editor.movable_panel import MovablePanelWindow

        class _Panel:
            def build(self, parent_tag):
                pass

        win = MovablePanelWindow(_Panel(), min_size=(420, 280))
        win.build()
        # dpg.window was called with min_size=[420, 280].
        _, kwargs = stub_dpg.calls["window"][0]
        assert kwargs["min_size"] == [420, 280]
