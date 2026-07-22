"""Tests for TT6 DiagnosticsCollector polish helpers + App widget summary.

Covers three tiny additions layered on top of OO6/QQ4/RR4/SS6:

* ``DiagnosticsCollector.filter_by_message`` — substring + regex, plus
  ValueError on malformed regex.
* ``DiagnosticsCollector.count_by_time_window`` — recency counter with a
  ValueError guard on negative windows.
* ``App.diagnostics_widget_summary`` — small HUD-label dict, with
  empty-defaults when diagnostics are not enabled.
"""
from __future__ import annotations

import time

import pytest

from pharos_engine.diagnostics import DiagnosticEvent, DiagnosticsCollector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    level: str = "WARNING",
    subsystem: str = "render",
    message: str = "msg",
    timestamp: float | None = None,
    exc_info=None,
) -> DiagnosticEvent:
    return DiagnosticEvent(
        level=level,
        subsystem=subsystem,
        message=message,
        timestamp=time.time() if timestamp is None else timestamp,
        exc_info=exc_info,
    )


def _seed(collector: DiagnosticsCollector, events: list[DiagnosticEvent]) -> None:
    """Populate the collector's ring buffer directly, bypassing logging."""
    with collector._lock:
        collector._events.clear()
        collector._events.extend(events)


# ---------------------------------------------------------------------------
# filter_by_message
# ---------------------------------------------------------------------------


def test_filter_by_message_substring_default():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    _seed(
        c,
        [
            _make_event(message="no such asset: foo.png"),
            _make_event(message="loaded texture bar.png"),
            _make_event(message="no such shader: baz.wgsl"),
        ],
    )
    matches = c.filter_by_message("no such")
    assert len(matches) == 2
    assert all("no such" in e.message for e in matches)


def test_filter_by_message_substring_no_match_returns_empty():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    _seed(c, [_make_event(message="ok"), _make_event(message="also ok")])
    assert c.filter_by_message("catastrophe") == []


def test_filter_by_message_regex_prefix_anchor():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    _seed(
        c,
        [
            _make_event(message="SoundBank missing wav id 3"),
            _make_event(message="loaded SoundBank fine"),
            _make_event(message="SoundBank: reload"),
        ],
    )
    matches = c.filter_by_message(r"^SoundBank", regex=True)
    # Only messages that *start with* SoundBank should match.
    assert len(matches) == 2
    assert all(e.message.startswith("SoundBank") for e in matches)


def test_filter_by_message_regex_invalid_raises_value_error():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    _seed(c, [_make_event(message="hi")])
    with pytest.raises(ValueError, match="invalid regex"):
        c.filter_by_message(r"[invalid regex", regex=True)


def test_filter_by_message_substring_does_not_treat_regex_literals():
    # A pattern with regex metachars should be treated as *literal* text
    # when regex=False.
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    _seed(
        c,
        [
            _make_event(message="parse a.b failed"),
            _make_event(message="parse aXb failed"),
        ],
    )
    matches = c.filter_by_message("a.b")
    # Substring: only the literal "a.b" message matches, not "aXb".
    assert len(matches) == 1
    assert matches[0].message == "parse a.b failed"


# ---------------------------------------------------------------------------
# count_by_time_window
# ---------------------------------------------------------------------------


def test_count_by_time_window_zero_when_events_are_old():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    old = time.time() - 3600.0  # one hour ago
    _seed(
        c,
        [
            _make_event(message="old", timestamp=old),
            _make_event(message="also old", timestamp=old + 1.0),
        ],
    )
    # 1 ms window — no chance either old event is inside it.
    assert c.count_by_time_window(0.001) == 0


def test_count_by_time_window_includes_recent():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    now = time.time()
    _seed(
        c,
        [
            _make_event(message="old", timestamp=now - 3600.0),
            _make_event(message="fresh", timestamp=now - 0.1),
            _make_event(message="also fresh", timestamp=now),
        ],
    )
    # 10-second window catches the two recent events, misses the old one.
    assert c.count_by_time_window(10.0) == 2


def test_count_by_time_window_negative_raises():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    with pytest.raises(ValueError, match="seconds"):
        c.count_by_time_window(-1)


def test_count_by_time_window_zero_seconds_only_exact_now():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    _seed(c, [_make_event(message="old", timestamp=time.time() - 10.0)])
    # Zero-second window: nothing older than "now" qualifies.
    assert c.count_by_time_window(0.0) == 0


# ---------------------------------------------------------------------------
# App.diagnostics_widget_summary
# ---------------------------------------------------------------------------


def test_app_widget_summary_returns_empty_defaults_when_disabled():
    from pharos_engine.app import App, AppConfig

    app = App(AppConfig(enable_gpu=False, max_frames=1))
    summary = app.diagnostics_widget_summary()
    assert summary == {
        "total": 0,
        "warnings": 0,
        "errors": 0,
        "top_subsystem": None,
        "last_message": None,
    }


def test_app_widget_summary_reports_totals_and_top_subsystem():
    from pharos_engine.app import App, AppConfig

    app = App(AppConfig(enable_gpu=False, max_frames=1))
    app.enable_diagnostics()
    try:
        base = 1_700_000_000.0
        _seed(
            app._diagnostics,
            [
                _make_event(
                    level="WARNING",
                    subsystem="audio_3d",
                    message="a1",
                    timestamp=base + 1,
                ),
                _make_event(
                    level="WARNING",
                    subsystem="audio_3d",
                    message="a2",
                    timestamp=base + 2,
                ),
                _make_event(
                    level="WARNING",
                    subsystem="audio_3d",
                    message="a3",
                    timestamp=base + 3,
                ),
                _make_event(
                    level="ERROR",
                    subsystem="render",
                    message="last one",
                    timestamp=base + 4,
                ),
            ],
        )
        summary = app.diagnostics_widget_summary()
        assert summary["total"] == 4
        assert summary["warnings"] == 3
        assert summary["errors"] == 1
        # audio_3d has 3 events, render has 1 → audio_3d wins top slot.
        assert summary["top_subsystem"] == "audio_3d"
        # Last buffered event's message is exposed.
        assert summary["last_message"] == "last one"
    finally:
        app.disable_diagnostics()


def test_app_widget_summary_counts_critical_as_error():
    from pharos_engine.app import App, AppConfig

    app = App(AppConfig(enable_gpu=False, max_frames=1))
    app.enable_diagnostics()
    try:
        _seed(
            app._diagnostics,
            [
                _make_event(level="WARNING", subsystem="render", message="w"),
                _make_event(level="ERROR", subsystem="render", message="e"),
                _make_event(level="CRITICAL", subsystem="render", message="c"),
            ],
        )
        summary = app.diagnostics_widget_summary()
        assert summary["warnings"] == 1
        # ERROR + CRITICAL → 2 errors in the widget summary.
        assert summary["errors"] == 2
        assert summary["top_subsystem"] == "render"
        assert summary["last_message"] == "c"
    finally:
        app.disable_diagnostics()


def test_app_widget_summary_empty_collector_returns_none_message():
    from pharos_engine.app import App, AppConfig

    app = App(AppConfig(enable_gpu=False, max_frames=1))
    app.enable_diagnostics()
    try:
        # Diagnostics enabled but no events buffered.
        summary = app.diagnostics_widget_summary()
        assert summary["total"] == 0
        assert summary["warnings"] == 0
        assert summary["errors"] == 0
        assert summary["top_subsystem"] is None
        assert summary["last_message"] is None
    finally:
        app.disable_diagnostics()
