"""Tests for :class:`NotebookTelemetryPanel`.

Coverage:

* Construction
    - Constructs without DPG errors / soft-imports succeed.
    - Rejects bad capacity / filter inputs at the boundary.
* Subscriber lifecycle
    - ``subscribe`` registers a single handle (idempotent).
    - ``unsubscribe`` drops the handle (idempotent).
    - Events arrive through the live ``slappyengine.telemetry`` bus.
* Filtering
    - Empty filter passes everything.
    - Substring filter is case-insensitive.
    - fnmatch filter routes through ``fnmatch.fnmatchcase``.
* Pause / Resume / Clear
    - Paused panel drops new events.
    - Resume re-enables capture (does not back-fill).
    - Clear drops every event currently rendered.
* Pin / Unpin
    - Pin appends to the pinned drawer once.
    - Unpin removes (silent on miss).
* Capacity
    - Ring buffer trims oldest events first.
* Theme integration
    - Theme switch invokes ``refresh`` and updates the cached theme.
* Build
    - ``build`` under stub DPG calls the expected widget factories.
"""
from __future__ import annotations

import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub
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

    def collapsing_header(self, *a, **kw):
        self._track("collapsing_header", a, kw)
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

    def add_checkbox(self, *a, **kw):
        self._track("add_checkbox", a, kw)

    def add_separator(self, *a, **kw):
        self._track("add_separator", a, kw)

    def add_slider_float(self, *a, **kw):
        self._track("add_slider_float", a, kw)

    def add_slider_int(self, *a, **kw):
        self._track("add_slider_int", a, kw)

    def does_item_exist(self, tag, *a, **kw):
        return tag in self.items

    def delete_item(self, tag, *a, **kw):
        self._track("delete_item", (tag,), kw)
        if isinstance(tag, str):
            self.items.discard(tag)

    def get_item_children(self, *a, **kw):
        return []

    def set_value(self, tag, value, *a, **kw):
        self._track("set_value", (tag, value), kw)


@pytest.fixture(autouse=True)
def stub_dpg(monkeypatch):
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    for name in (
        "group", "child_window", "collapsing_header", "window",
        "add_text", "add_button", "add_input_text", "add_checkbox",
        "add_separator", "add_slider_float", "add_slider_int",
        "does_item_exist", "delete_item", "get_item_children",
        "set_value",
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
def clear_state():
    from slappyengine import telemetry as t
    from slappyengine.ui.widgets import notebook_theme
    from slappyengine.ui.widgets.notebook_theme import set_active_theme

    set_active_theme(None)
    notebook_theme._theme_listeners.clear()
    t.clear_history()
    yield
    set_active_theme(None)
    notebook_theme._theme_listeners.clear()
    t.clear_history()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_panel(**kwargs):
    from slappyengine.ui.editor.notebook_telemetry_panel import (
        NotebookTelemetryPanel,
    )
    return NotebookTelemetryPanel(**kwargs)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_constructs_without_dpg_errors(self):
        panel = _make_panel()
        assert panel.TITLE == "Telemetry"
        assert panel.events == []
        assert panel.paused is False

    def test_rejects_bad_capacity(self):
        with pytest.raises((TypeError, ValueError)):
            _make_panel(capacity=-1)

    def test_rejects_bad_filter(self):
        with pytest.raises(TypeError):
            _make_panel(initial_filter=123)

    def test_initial_filter_round_trips(self):
        panel = _make_panel(initial_filter="physics.*")
        assert panel.filter == "physics.*"


# ---------------------------------------------------------------------------
# Subscriber lifecycle
# ---------------------------------------------------------------------------


class TestSubscription:
    def test_subscribe_idempotent(self):
        panel = _make_panel()
        panel.subscribe()
        first = panel._subscription_handle
        panel.subscribe()
        assert panel._subscription_handle == first

    def test_unsubscribe_idempotent(self):
        panel = _make_panel()
        panel.subscribe()
        panel.unsubscribe()
        panel.unsubscribe()
        assert panel._subscription_handle is None

    def test_receives_live_event(self):
        from slappyengine import telemetry

        panel = _make_panel()
        panel.subscribe()
        try:
            telemetry.emit("physics.step", frame=42)
            assert any(
                e.name == "physics.step" for e in panel.events
            )
        finally:
            panel.unsubscribe()

    def test_build_auto_subscribes(self):
        from slappyengine import telemetry

        panel = _make_panel()
        panel.build(parent_tag="root")
        try:
            telemetry.emit("render.frame", n=1)
            assert any(e.name == "render.frame" for e in panel.events)
        finally:
            panel.destroy()


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


class TestFiltering:
    def test_empty_filter_matches_all(self):
        from slappyengine.ui.editor.notebook_telemetry_panel import (
            matches_filter,
        )
        assert matches_filter("physics.step", "")
        assert matches_filter("render.frame", "  ")

    def test_substring_case_insensitive(self):
        from slappyengine.ui.editor.notebook_telemetry_panel import (
            matches_filter,
        )
        assert matches_filter("Physics.Step", "physics")
        assert not matches_filter("render.frame", "physics")

    def test_fnmatch_glob(self):
        from slappyengine.ui.editor.notebook_telemetry_panel import (
            matches_filter,
        )
        assert matches_filter("physics.step", "physics.*")
        assert matches_filter("physics.collision", "physics.*")
        assert not matches_filter("render.frame", "physics.*")

    def test_set_filter_updates_events_view(self):
        from slappyengine import telemetry

        panel = _make_panel()
        panel.subscribe()
        try:
            telemetry.emit("physics.step")
            telemetry.emit("render.frame")
            panel.set_filter("physics")
            names = [e.name for e in panel.events]
            assert names == ["physics.step"]
        finally:
            panel.unsubscribe()


# ---------------------------------------------------------------------------
# Pause / Resume / Clear
# ---------------------------------------------------------------------------


class TestTransport:
    def test_pause_drops_new_events(self):
        from slappyengine import telemetry

        panel = _make_panel()
        panel.subscribe()
        try:
            panel.pause()
            telemetry.emit("physics.step")
            assert panel.events == []
        finally:
            panel.unsubscribe()

    def test_resume_re_enables_capture(self):
        from slappyengine import telemetry

        panel = _make_panel()
        panel.subscribe()
        try:
            panel.pause()
            telemetry.emit("dropped")
            panel.resume()
            telemetry.emit("kept")
            names = [e.name for e in panel.events]
            assert names == ["kept"]
        finally:
            panel.unsubscribe()

    def test_clear_drops_events(self):
        from slappyengine import telemetry

        panel = _make_panel()
        panel.subscribe()
        try:
            telemetry.emit("a")
            telemetry.emit("b")
            assert len(panel.events) == 2
            panel.clear()
            assert panel.events == []
        finally:
            panel.unsubscribe()


# ---------------------------------------------------------------------------
# Pin / Unpin
# ---------------------------------------------------------------------------


class TestPinning:
    def test_pin_appends_once(self):
        from slappyengine import telemetry

        panel = _make_panel()
        panel.subscribe()
        try:
            telemetry.emit("save")
            event = panel.events[0]
            panel.pin(event)
            panel.pin(event)
            assert panel.pinned == [event]
        finally:
            panel.unsubscribe()

    def test_unpin_removes(self):
        from slappyengine import telemetry

        panel = _make_panel()
        panel.subscribe()
        try:
            telemetry.emit("save")
            event = panel.events[0]
            panel.pin(event)
            panel.unpin(event)
            assert panel.pinned == []
        finally:
            panel.unsubscribe()

    def test_unpin_missing_is_silent(self):
        from slappyengine.telemetry import TelemetryEvent

        panel = _make_panel()
        fake = TelemetryEvent(name="ghost", timestamp=0.0)
        # Should not raise
        panel.unpin(fake)


# ---------------------------------------------------------------------------
# Capacity
# ---------------------------------------------------------------------------


class TestCapacity:
    def test_ring_trims_oldest(self):
        from slappyengine import telemetry

        panel = _make_panel(capacity=2)
        panel.subscribe()
        try:
            telemetry.emit("first")
            telemetry.emit("second")
            telemetry.emit("third")
            names = [e.name for e in panel.events]
            # Newest first, capacity = 2 → "third", "second".
            assert names == ["third", "second"]
        finally:
            panel.unsubscribe()

    def test_set_capacity_trims_immediately(self):
        from slappyengine import telemetry

        panel = _make_panel(capacity=10)
        panel.subscribe()
        try:
            for i in range(5):
                telemetry.emit(f"e{i}")
            panel.set_capacity(2)
            assert len(panel.events) == 2
        finally:
            panel.unsubscribe()


# ---------------------------------------------------------------------------
# Theme integration
# ---------------------------------------------------------------------------


class TestThemeIntegration:
    def test_theme_switch_logs(self):
        from slappyengine.ui.widgets.notebook_theme import (
            NotebookTheme,
            set_active_theme,
        )

        panel = _make_panel()
        theme = NotebookTheme(name="alt")
        set_active_theme(theme)
        assert any(call[0] == "theme_changed" for call in panel.call_log)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


class TestBuild:
    def test_build_creates_root_widgets(self, stub_dpg):
        panel = _make_panel()
        panel.build(parent_tag="root")
        # Title text should be added.
        assert "add_text" in stub_dpg.calls
        panel.destroy()
