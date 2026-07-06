"""Tests for :mod:`slappyengine.diagnostics` + HUD widget bridge (OO6).

Covers:

* install/uninstall + idempotence
* rolling buffer respect (max_events)
* min_level filtering
* subsystem tag extraction + prefix filter
* stats() per-level + per-subsystem counts
* HUD widget summary text reflects captured events
"""
from __future__ import annotations

import logging

import pytest

from slappyengine.diagnostics import (
    DiagnosticEvent,
    DiagnosticsCollector,
    _subsystem_from_logger_name,
    get_global_collector,
)


@pytest.fixture
def collector() -> DiagnosticsCollector:
    """Fresh collector per test; uninstalls in teardown."""
    c = DiagnosticsCollector(max_events=500, min_level="WARNING")
    yield c
    c.uninstall()


# ---------------------------------------------------------------------------
# Subsystem tag extraction
# ---------------------------------------------------------------------------


def test_subsystem_extraction_slappy_prefix():
    assert _subsystem_from_logger_name("slappyengine.render.ssao") == "render"
    assert _subsystem_from_logger_name("slappyengine.audio_3d") == "audio_3d"
    assert _subsystem_from_logger_name("slappyengine") == "slappyengine"


def test_subsystem_extraction_other_pkg():
    assert _subsystem_from_logger_name("other.pkg.thing") == "other"
    assert _subsystem_from_logger_name("") == "unknown"


# ---------------------------------------------------------------------------
# Install / capture
# ---------------------------------------------------------------------------


def test_install_captures_warning(collector: DiagnosticsCollector):
    collector.install()
    logging.getLogger("slappyengine.audio_3d").warning("bad channel count")
    events = collector.events()
    assert len(events) == 1
    evt = events[0]
    assert isinstance(evt, DiagnosticEvent)
    assert evt.level == "WARNING"
    assert evt.subsystem == "audio_3d"
    assert "bad channel count" in evt.message


def test_install_is_idempotent(collector: DiagnosticsCollector):
    collector.install()
    collector.install()
    collector.install()
    logging.getLogger("slappyengine.render.ssao").warning("dup handler check")
    # Exactly one event captured — no double-fire from a second handler.
    assert len(collector.events()) == 1
    # And the underlying logger has exactly one handler pointing at us.
    logger = logging.getLogger("slappyengine")
    ours = [h for h in logger.handlers if getattr(h, "collector", None) is collector]
    assert len(ours) == 1


def test_uninstall_stops_capture(collector: DiagnosticsCollector):
    collector.install()
    logging.getLogger("slappyengine.render").warning("first")
    collector.uninstall()
    logging.getLogger("slappyengine.render").warning("second — should not land")
    events = collector.events()
    assert len(events) == 1
    assert "first" in events[0].message


# ---------------------------------------------------------------------------
# Rolling buffer
# ---------------------------------------------------------------------------


def test_rolling_buffer_respects_max_events():
    c = DiagnosticsCollector(max_events=500, min_level="WARNING")
    c.install()
    try:
        log = logging.getLogger("slappyengine.render")
        for i in range(600):
            log.warning("noise %d", i)
        events = c.events()
        assert len(events) == 500
        # Oldest were dropped — the 100th warning should be the first
        # surviving event (indices 100..599 remain).
        assert "noise 100" in events[0].message
        assert "noise 599" in events[-1].message
    finally:
        c.uninstall()


def test_clear_empties_buffer(collector: DiagnosticsCollector):
    collector.install()
    logging.getLogger("slappyengine.render").warning("x")
    logging.getLogger("slappyengine.render").warning("y")
    assert len(collector.events()) == 2
    collector.clear()
    assert collector.events() == []


# ---------------------------------------------------------------------------
# Level filtering
# ---------------------------------------------------------------------------


def test_min_level_error_drops_warnings():
    c = DiagnosticsCollector(max_events=100, min_level="ERROR")
    c.install()
    try:
        log = logging.getLogger("slappyengine.audio_3d")
        log.warning("should be dropped")
        log.error("should land")
        events = c.events()
        assert len(events) == 1
        assert events[0].level == "ERROR"
    finally:
        c.uninstall()


# ---------------------------------------------------------------------------
# Subsystem filter + stats
# ---------------------------------------------------------------------------


def test_filter_by_subsystem_returns_only_matching(collector: DiagnosticsCollector):
    collector.install()
    logging.getLogger("slappyengine.audio_3d").warning("a1")
    logging.getLogger("slappyengine.audio_3d").warning("a2")
    logging.getLogger("slappyengine.render.ssao").warning("r1")
    logging.getLogger("slappyengine.capture").warning("c1")

    audio_events = collector.filter_by_subsystem("audio")
    assert len(audio_events) == 2
    assert all(e.subsystem == "audio_3d" for e in audio_events)
    assert {e.message for e in audio_events} == {"a1", "a2"}

    render_events = collector.filter_by_subsystem("render")
    assert len(render_events) == 1
    assert render_events[0].message == "r1"


def test_stats_reports_level_and_subsystem_counts(collector: DiagnosticsCollector):
    collector.install()
    logging.getLogger("slappyengine.audio_3d").warning("a1")
    logging.getLogger("slappyengine.audio_3d").warning("a2")
    logging.getLogger("slappyengine.render.ssao").error("r_err")
    logging.getLogger("slappyengine.capture").warning("c1")

    stats = collector.stats()
    assert stats["total"] == 4
    assert stats["level:WARNING"] == 3
    assert stats["level:ERROR"] == 1
    assert stats["subsystem:audio_3d"] == 2
    assert stats["subsystem:render"] == 1
    assert stats["subsystem:capture"] == 1


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------


def test_global_collector_is_singleton():
    a = get_global_collector()
    b = get_global_collector()
    assert a is b
    # Do not leave the global installed — other tests must stay clean.
    a.uninstall()
    a.clear()


# ---------------------------------------------------------------------------
# HUD widget
# ---------------------------------------------------------------------------


class _FakeUI:
    """Minimal ImmediateUI stand-in that records label calls."""

    def __init__(self) -> None:
        self.labels: list[tuple[str, str, tuple, tuple]] = []

    def label(self, widget_id, text, position, color) -> None:
        self.labels.append((widget_id, text, tuple(position), tuple(color)))


def test_hud_widget_shows_level_counts(collector: DiagnosticsCollector):
    from slappyengine.hud_bridge import _DiagnosticsHUDWidget

    collector.install()
    logging.getLogger("slappyengine.audio_3d").warning("bad channel")
    logging.getLogger("slappyengine.render.ssao").error("shader missing")

    widget = _DiagnosticsHUDWidget(collector, position=(10.0, 100.0))
    ui = _FakeUI()
    widget.build(ui)

    # First label is the summary.
    assert ui.labels[0][0] == "hud_diagnostics_summary"
    assert ui.labels[0][1] == "ERROR: 1 | WARN: 1"
    # Recent events follow.
    joined = " ".join(row[1] for row in ui.labels[1:])
    assert "bad channel" in joined
    assert "shader missing" in joined
    # Subsystem tags appear inline.
    assert "[audio_3d]" in joined
    assert "[render]" in joined


def test_hud_widget_summary_zero_when_empty(collector: DiagnosticsCollector):
    from slappyengine.hud_bridge import _DiagnosticsHUDWidget

    widget = _DiagnosticsHUDWidget(collector)
    assert widget.summary_text() == "ERROR: 0 | WARN: 0"


def test_add_diagnostics_widget_uses_global_when_none(monkeypatch):
    """`add_diagnostics_widget(app, None)` falls back to the singleton."""
    from slappyengine.hud_bridge import add_diagnostics_widget

    class _FakeOverlay:
        def __init__(self):
            self.attached = []

        def attach(self, w):
            self.attached.append(w)

    class _FakeApp:
        pass

    app = _FakeApp()
    app._hud_overlay = _FakeOverlay()

    widget = add_diagnostics_widget(app, collector=None)
    assert widget.collector is get_global_collector()
    assert app._hud_overlay.attached == [widget]
