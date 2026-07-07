"""Tests for SS6 DiagnosticsCollector.render_markdown_report + save_report.

Covers:

* Empty collector renders a "0 events" report.
* 5 warnings across 2 subsystems produce a summary + top-subsystems table.
* ``group_by="time"`` returns events in descending timestamp order.
* ``group_by="level"`` orders ERROR / CRITICAL before WARNING.
* ``group_by="bogus"`` raises ValueError.
* ``max_events=3`` truncates a 10-event log to 3 rows.
* ``save_report(tmp_path/"r.md")`` writes to disk with valid markdown.
* ``App.diagnostics_report()`` delegates correctly.
"""
from __future__ import annotations

import time

import pytest

from slappyengine.diagnostics import DiagnosticEvent, DiagnosticsCollector


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


def _count_table_rows(md: str, header_marker: str) -> int:
    """Count body rows in the Markdown table under *header_marker*."""
    lines = md.splitlines()
    try:
        idx = next(i for i, ln in enumerate(lines) if ln.startswith(header_marker))
    except StopIteration:
        return 0
    # skip header + separator
    count = 0
    for ln in lines[idx + 2 :]:
        if not ln.startswith("|"):
            break
        count += 1
    return count


# ---------------------------------------------------------------------------
# Empty collector
# ---------------------------------------------------------------------------


def test_empty_collector_report_has_zero_events():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    md = c.render_markdown_report()
    assert "# Diagnostics Report" in md
    assert "## Summary" in md
    assert "**Total events:** 0" in md
    assert "**Warnings:** 0, **Errors:** 0" in md
    assert "**Subsystems affected:** 0" in md
    assert "0 events" in md


# ---------------------------------------------------------------------------
# Summary + top-subsystems
# ---------------------------------------------------------------------------


def test_five_warnings_two_subsystems_summary_and_top():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    base = 1_700_000_000.0
    _seed(
        c,
        [
            _make_event(level="WARNING", subsystem="audio_3d", message="a1", timestamp=base + 1),
            _make_event(level="WARNING", subsystem="audio_3d", message="a2", timestamp=base + 2),
            _make_event(level="WARNING", subsystem="audio_3d", message="a3", timestamp=base + 3),
            _make_event(level="WARNING", subsystem="render", message="r1", timestamp=base + 4),
            _make_event(level="WARNING", subsystem="render", message="r2", timestamp=base + 5),
        ],
    )
    md = c.render_markdown_report()
    assert "**Total events:** 5" in md
    assert "**Warnings:** 5, **Errors:** 0" in md
    assert "**Subsystems affected:** 2" in md
    assert "| Subsystem | Events |" in md
    # audio_3d has 3, render has 2 → both present in top-subsystems table
    assert "| audio_3d | 3 |" in md
    assert "| render | 2 |" in md


def test_report_counts_errors_and_criticals_as_errors():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    _seed(
        c,
        [
            _make_event(level="WARNING", subsystem="render", message="w1"),
            _make_event(level="ERROR", subsystem="render", message="e1"),
            _make_event(level="CRITICAL", subsystem="audio_3d", message="c1"),
        ],
    )
    md = c.render_markdown_report()
    # 1 warning, 1 error + 1 critical = 2 errors reported
    assert "**Warnings:** 1, **Errors:** 2" in md


# ---------------------------------------------------------------------------
# group_by ordering
# ---------------------------------------------------------------------------


def _extract_recent_msgs(md: str) -> list[str]:
    """Pull the ``Message`` column from the Recent events table rows."""
    lines = md.splitlines()
    try:
        idx = next(
            i for i, ln in enumerate(lines) if ln.startswith("## Recent events")
        )
    except StopIteration:
        return []
    msgs: list[str] = []
    for ln in lines[idx + 3 :]:  # skip section header + table header + separator
        if not ln.startswith("|"):
            break
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) >= 4:
            msgs.append(cells[3])
    return msgs


def test_group_by_time_descending_timestamps():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    base = 1_700_000_000.0
    _seed(
        c,
        [
            _make_event(subsystem="render", message="oldest", timestamp=base + 1),
            _make_event(subsystem="audio_3d", message="middle", timestamp=base + 2),
            _make_event(subsystem="render", message="newest", timestamp=base + 3),
        ],
    )
    md = c.render_markdown_report(group_by="time")
    msgs = _extract_recent_msgs(md)
    assert msgs == ["newest", "middle", "oldest"]


def test_group_by_level_orders_error_before_warning():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    base = 1_700_000_000.0
    _seed(
        c,
        [
            _make_event(level="WARNING", subsystem="render", message="w1", timestamp=base + 1),
            _make_event(level="ERROR", subsystem="render", message="e1", timestamp=base + 2),
            _make_event(level="WARNING", subsystem="render", message="w2", timestamp=base + 3),
            _make_event(level="CRITICAL", subsystem="render", message="crit", timestamp=base + 4),
        ],
    )
    md = c.render_markdown_report(group_by="level")
    msgs = _extract_recent_msgs(md)
    # CRITICAL > ERROR > WARNING; within same level, newest-first.
    assert msgs[0] == "crit"
    assert msgs[1] == "e1"
    # w2 is newer than w1 → w2 first among warnings
    assert msgs[2] == "w2"
    assert msgs[3] == "w1"


def test_group_by_subsystem_groups_by_tag():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    base = 1_700_000_000.0
    _seed(
        c,
        [
            _make_event(subsystem="render", message="r1", timestamp=base + 3),
            _make_event(subsystem="audio_3d", message="a1", timestamp=base + 1),
            _make_event(subsystem="render", message="r2", timestamp=base + 4),
            _make_event(subsystem="audio_3d", message="a2", timestamp=base + 2),
        ],
    )
    md = c.render_markdown_report(group_by="subsystem")
    msgs = _extract_recent_msgs(md)
    # audio_3d group first (alphabetical) with oldest-first inside, then render
    assert msgs == ["a1", "a2", "r1", "r2"]


def test_group_by_bogus_raises():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    with pytest.raises(ValueError, match="group_by"):
        c.render_markdown_report(group_by="bogus")


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


def test_max_events_truncates_recent_events_table():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    base = 1_700_000_000.0
    events = [
        _make_event(subsystem="render", message=f"m{i}", timestamp=base + i)
        for i in range(10)
    ]
    _seed(c, events)
    md = c.render_markdown_report(max_events=3, group_by="time")
    body_rows = _count_table_rows(md, "| Time | Level | Subsystem | Message |")
    assert body_rows == 3
    assert "(last 3)" in md
    # Summary still reflects the full buffer.
    assert "**Total events:** 10" in md


# ---------------------------------------------------------------------------
# Pipe escaping — messages with '|' must not break the table
# ---------------------------------------------------------------------------


def test_pipe_in_message_is_escaped():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    _seed(
        c,
        [
            _make_event(
                subsystem="render",
                message="parse a|b|c failed",
            ),
        ],
    )
    md = c.render_markdown_report()
    # The escaped form appears; a raw unescaped `a|b|c` would split cells.
    assert r"a\|b\|c" in md
    body_rows = _count_table_rows(md, "| Time | Level | Subsystem | Message |")
    assert body_rows == 1


# ---------------------------------------------------------------------------
# save_report
# ---------------------------------------------------------------------------


def test_save_report_writes_markdown_to_disk(tmp_path):
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    _seed(
        c,
        [
            _make_event(subsystem="render", message="on-disk"),
        ],
    )
    out = tmp_path / "r.md"
    result = c.save_report(out)
    assert result == out
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert content.startswith("# Diagnostics Report")
    assert "## Summary" in content
    assert "## Top subsystems" in content
    assert "## Recent events" in content
    assert "on-disk" in content


def test_save_report_forwards_kwargs(tmp_path):
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    base = 1_700_000_000.0
    events = [
        _make_event(subsystem="render", message=f"m{i}", timestamp=base + i)
        for i in range(5)
    ]
    _seed(c, events)
    out = tmp_path / "r.md"
    c.save_report(out, max_events=2, group_by="time")
    content = out.read_text(encoding="utf-8")
    assert "(last 2)" in content


# ---------------------------------------------------------------------------
# App shim
# ---------------------------------------------------------------------------


def test_app_diagnostics_report_returns_empty_when_disabled():
    from slappyengine.app import App, AppConfig

    app = App(AppConfig(enable_gpu=False, max_frames=1))
    # Diagnostics not enabled yet.
    assert app.diagnostics_report() == ""


def test_app_diagnostics_report_delegates_to_collector():
    from slappyengine.app import App, AppConfig

    app = App(AppConfig(enable_gpu=False, max_frames=1))
    app.enable_diagnostics()
    try:
        _seed(
            app._diagnostics,
            [
                _make_event(subsystem="render", message="from-app"),
            ],
        )
        md = app.diagnostics_report()
        assert "# Diagnostics Report" in md
        assert "from-app" in md
        assert "**Total events:** 1" in md
    finally:
        app.disable_diagnostics()


def test_app_diagnostics_report_forwards_group_by():
    from slappyengine.app import App, AppConfig

    app = App(AppConfig(enable_gpu=False, max_frames=1))
    app.enable_diagnostics()
    try:
        with pytest.raises(ValueError):
            app.diagnostics_report(group_by="bogus")
    finally:
        app.disable_diagnostics()
