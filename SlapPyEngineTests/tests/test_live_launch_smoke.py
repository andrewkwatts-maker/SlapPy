"""Live-launch smoke test for :meth:`EditorShell.setup`.

A regression tripwire: with ``dearpygui`` mocked end-to-end, calling
``EditorShell.setup`` (the same entry-point ``Engine.run_editor``
funnels through right before the main loop starts) must complete
without raising. The test guards every fix from the 2026-06-07
panel-setup audit at once — if any of the layout, status-bar, or
movable-wrapper paths regress, this fails first.
"""
from __future__ import annotations

import sys
import types
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Fully-no-op DPG stub — every attribute access returns a callable that
# returns ``None`` (or a no-op context manager when entered as ``with``).
# ---------------------------------------------------------------------------


class _NoOpCM:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Anything:
    """Catch-all stand-in for any DPG handle, theme handle, or return value."""

    def __getattr__(self, _name):
        return _Anything()

    def __call__(self, *a, **k):
        return _Anything()


def _no_op_returning_cm(*_a, **_k):
    return _NoOpCM()


class _SmokeDPG:
    """Total stub — every call is silently a no-op."""

    def __init__(self) -> None:
        self._tags: set[str] = set()

    # Context-manager constructors.
    def window(self, *a, **k):
        tag = k.get("tag")
        if isinstance(tag, str):
            self._tags.add(tag)
        return _NoOpCM()

    def viewport_menu_bar(self, *a, **k):
        return _NoOpCM()

    def menu(self, *a, **k):
        return _NoOpCM()

    def group(self, *a, **k):
        tag = k.get("tag")
        if isinstance(tag, str):
            self._tags.add(tag)
        return _NoOpCM()

    def child_window(self, *a, **k):
        return _NoOpCM()

    def tab_bar(self, *a, **k):
        return _NoOpCM()

    def tab(self, *a, **k):
        return _NoOpCM()

    def collapsing_header(self, *a, **k):
        return _NoOpCM()

    def tree_node(self, *a, **k):
        return _NoOpCM()

    def theme(self, *a, **k):
        return _NoOpCM()

    def theme_component(self, *a, **k):
        return _NoOpCM()

    def font_registry(self, *a, **k):
        return _NoOpCM()

    def value_registry(self, *a, **k):
        return _NoOpCM()

    def handler_registry(self, *a, **k):
        return _NoOpCM()

    def item_handler_registry(self, *a, **k):
        return _NoOpCM()

    def stage(self, *a, **k):
        return _NoOpCM()

    def table(self, *a, **k):
        return _NoOpCM()

    def table_row(self, *a, **k):
        return _NoOpCM()

    def drawlist(self, *a, **k):
        return _NoOpCM()

    def viewport_drawlist(self, *a, **k):
        return _NoOpCM()

    def filter_set(self, *a, **k):
        return _NoOpCM()

    # Existence query — keep simple for the smoke run.
    def does_item_exist(self, tag, *a, **k):
        return isinstance(tag, str) and tag in self._tags

    def add_separator(self, *a, **k):
        tag = k.get("tag")
        if isinstance(tag, str):
            self._tags.add(tag)
        return tag

    def add_text(self, *a, **k):
        tag = k.get("tag")
        if isinstance(tag, str):
            self._tags.add(tag)
        return tag

    def add_button(self, *a, **k):
        tag = k.get("tag")
        if isinstance(tag, str):
            self._tags.add(tag)
        return tag

    def __getattr__(self, name: str):
        # Default — track any ``add_*`` tag, otherwise just no-op.
        def _f(*a, **k):
            tag = k.get("tag")
            if isinstance(tag, str):
                self._tags.add(tag)
            return tag if tag else _Anything()
        return _f


@pytest.fixture
def smoke_dpg(monkeypatch):
    stub = _SmokeDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    # Expose every attribute access through ``getattr``.
    for name in dir(stub):
        if name.startswith("__"):
            continue
        setattr(mod, name, getattr(stub, name))
    mod.__getattr__ = lambda name: getattr(stub, name)
    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    return stub


@pytest.fixture(autouse=True)
def reset_theme_registry():
    from slappyengine.ui.theme import _reset_registry_for_tests
    from slappyengine.ui.widgets import notebook_theme
    from slappyengine.ui.theme.creatures import (
        _reset_default_scheduler_for_tests,
    )

    def _wipe():
        _reset_registry_for_tests()
        notebook_theme._active_theme = None
        notebook_theme._theme_listeners.clear()
        _reset_default_scheduler_for_tests()

    _wipe()
    yield
    _wipe()


def test_editor_shell_setup_no_exception(smoke_dpg, monkeypatch):
    """``EditorShell.setup`` runs end-to-end against the mocked DPG."""
    # Force the theme bridge to route through its headless stub even
    # after the shell flips ``mark_dpg_context_ready(True)`` — the real
    # ``dearpygui`` library segfaults on ``add_theme`` without a live
    # context, and the shell legitimately calls into it.
    from slappyengine.ui.theme import dpg_bridge as _bridge

    monkeypatch.setattr(_bridge, "_HAS_DPG", False)
    monkeypatch.setattr(_bridge, "_REAL_DPG", None)

    from slappyengine.ui.editor.shell import EditorShell

    class _StubEngine:
        def __init__(self):
            self.scene = None

    shell = EditorShell(_StubEngine())
    # Suppress the maybe-show-welcome path so we don't depend on
    # ``ui.welcome_shown`` state on disk.
    monkeypatch.setattr(
        shell, "_maybe_show_first_run_welcome", lambda: None,
    )
    # Suppress the layout-presets menu populate — it would otherwise
    # probe the registry singleton on disk.
    monkeypatch.setattr(
        shell, "_populate_layout_presets_menu", lambda: None,
    )
    monkeypatch.setattr(
        shell, "_populate_recent_projects_menu", lambda: None,
    )

    # Should not raise.
    shell.setup()

    # And ``_panel_windows`` must be populated.
    assert isinstance(shell._panel_windows, dict)
    assert "status_bar" in shell._panel_windows
