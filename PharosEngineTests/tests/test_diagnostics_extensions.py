"""Tests for RR4 DiagnosticsCollector extensions.

Covers the six new APIs added on top of the OO6 baseline:

* ``filter_by_level`` — case-insensitive exact-level filter + ValueError
* ``top_subsystems``  — top-N aggregation
* ``to_json`` / ``from_json`` — round-trip serialisation + error cases
* ``clear_by_subsystem`` — targeted removal
* ``since`` — timestamp filter
"""
from __future__ import annotations

import json
import time

import pytest

from pharos_engine.diagnostics import (
    DiagnosticEvent,
    DiagnosticsCollector,
)


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
# filter_by_level
# ---------------------------------------------------------------------------


def test_filter_by_level_returns_only_warnings():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    _seed(
        c,
        [
            _make_event(level="WARNING", subsystem="audio_3d", message="w1"),
            _make_event(level="ERROR", subsystem="render", message="e1"),
            _make_event(level="WARNING", subsystem="render", message="w2"),
            _make_event(level="CRITICAL", subsystem="capture", message="crit"),
        ],
    )
    hits = c.filter_by_level("WARNING")
    assert len(hits) == 2
    assert {e.message for e in hits} == {"w1", "w2"}


def test_filter_by_level_is_case_insensitive():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    _seed(
        c,
        [
            _make_event(level="ERROR", subsystem="render", message="e1"),
            _make_event(level="WARNING", subsystem="render", message="w1"),
        ],
    )
    assert len(c.filter_by_level("error")) == 1
    assert len(c.filter_by_level("Error")) == 1
    assert len(c.filter_by_level("ERROR")) == 1


def test_filter_by_level_raises_for_unknown_level():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    with pytest.raises(ValueError):
        c.filter_by_level("BOGUS")


def test_filter_by_level_raises_for_non_string():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    with pytest.raises(ValueError):
        c.filter_by_level(42)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# top_subsystems
# ---------------------------------------------------------------------------


def test_top_subsystems_returns_top_n_desc():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    _seed(
        c,
        [
            _make_event(subsystem="render", message=f"r{i}") for i in range(5)
        ]
        + [_make_event(subsystem="audio_3d", message=f"a{i}") for i in range(3)]
        + [_make_event(subsystem="capture", message=f"c{i}") for i in range(2)]
        + [_make_event(subsystem="text", message="t1")],
    )
    top = c.top_subsystems(3)
    assert top == [("render", 5), ("audio_3d", 3), ("capture", 2)]


def test_top_subsystems_n_le_zero_returns_empty():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    _seed(c, [_make_event(subsystem="render", message="x")])
    assert c.top_subsystems(0) == []
    assert c.top_subsystems(-1) == []


def test_top_subsystems_n_larger_than_distinct_returns_all():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    _seed(
        c,
        [
            _make_event(subsystem="render", message="r1"),
            _make_event(subsystem="audio_3d", message="a1"),
        ],
    )
    top = c.top_subsystems(10)
    assert len(top) == 2
    assert {name for name, _ in top} == {"render", "audio_3d"}


# ---------------------------------------------------------------------------
# to_json / from_json round-trip
# ---------------------------------------------------------------------------


def test_to_json_from_json_round_trip_preserves_events():
    c = DiagnosticsCollector(max_events=250, min_level="WARNING")
    _seed(
        c,
        [
            _make_event(
                level="WARNING",
                subsystem="audio_3d",
                message="channel wobble",
                timestamp=1000.5,
            ),
            _make_event(
                level="ERROR",
                subsystem="render",
                message="missing shader",
                timestamp=1001.25,
                exc_info="Traceback: boom",
            ),
        ],
    )
    dumped = c.to_json()
    restored = DiagnosticsCollector.from_json(dumped)

    original = c.events()
    round_tripped = restored.events()
    assert len(round_tripped) == len(original) == 2
    for a, b in zip(original, round_tripped):
        assert a == b

    # Stats survive.
    assert restored.stats() == c.stats()
    # Meta configuration survives.
    assert restored._max_events == 250
    # A restored collector is not installed.
    assert restored.is_installed() is False


def test_to_json_indent_is_forwarded():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    _seed(c, [_make_event(subsystem="render", message="x")])
    compact = c.to_json()
    pretty = c.to_json(indent=2)
    assert "\n" not in compact
    assert "\n" in pretty
    # Meta contains the required keys.
    parsed = json.loads(pretty)
    assert set(parsed.keys()) == {"events", "stats", "meta"}
    assert set(parsed["meta"].keys()) == {"max_events", "min_level", "captured_at"}


def test_from_json_rejects_malformed_json():
    with pytest.raises(ValueError):
        DiagnosticsCollector.from_json("{not valid json")


def test_from_json_rejects_missing_events_key():
    payload = json.dumps({"meta": {"max_events": 100, "min_level": "WARNING"}})
    with pytest.raises(ValueError):
        DiagnosticsCollector.from_json(payload)


def test_from_json_rejects_missing_meta_key():
    payload = json.dumps({"events": []})
    with pytest.raises(ValueError):
        DiagnosticsCollector.from_json(payload)


def test_from_json_rejects_bad_event_shape():
    payload = json.dumps(
        {
            "events": [{"level": "WARNING", "subsystem": "render"}],
            "meta": {"max_events": 100, "min_level": "WARNING"},
        }
    )
    with pytest.raises(ValueError):
        DiagnosticsCollector.from_json(payload)


def test_from_json_rejects_non_object_top_level():
    with pytest.raises(ValueError):
        DiagnosticsCollector.from_json(json.dumps([1, 2, 3]))


# ---------------------------------------------------------------------------
# clear_by_subsystem
# ---------------------------------------------------------------------------


def test_clear_by_subsystem_removes_only_matching():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    _seed(
        c,
        [
            _make_event(subsystem="audio_3d", message="a1"),
            _make_event(subsystem="audio_3d", message="a2"),
            _make_event(subsystem="render", message="r1"),
            _make_event(subsystem="capture", message="c1"),
        ],
    )
    removed = c.clear_by_subsystem("audio")
    assert removed == 2
    remaining = c.events()
    assert len(remaining) == 2
    assert {e.subsystem for e in remaining} == {"render", "capture"}
    # A second call finds nothing.
    assert c.clear_by_subsystem("audio") == 0


def test_clear_by_subsystem_no_match_returns_zero():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    _seed(c, [_make_event(subsystem="render", message="r1")])
    assert c.clear_by_subsystem("nothing") == 0
    assert len(c.events()) == 1


# ---------------------------------------------------------------------------
# since
# ---------------------------------------------------------------------------


def test_since_filters_across_time_boundary():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    _seed(
        c,
        [
            _make_event(subsystem="render", message="old1", timestamp=100.0),
            _make_event(subsystem="render", message="old2", timestamp=150.0),
            _make_event(subsystem="render", message="new1", timestamp=200.0),
            _make_event(subsystem="render", message="new2", timestamp=250.0),
        ],
    )
    fresh = c.since(200.0)
    assert len(fresh) == 2
    assert {e.message for e in fresh} == {"new1", "new2"}


def test_since_inclusive_of_exact_timestamp():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    _seed(
        c,
        [
            _make_event(message="exact", timestamp=500.0),
            _make_event(message="later", timestamp=500.5),
        ],
    )
    assert len(c.since(500.0)) == 2


def test_since_future_returns_empty():
    c = DiagnosticsCollector(max_events=100, min_level="DEBUG")
    _seed(c, [_make_event(message="past", timestamp=100.0)])
    assert c.since(999_999.0) == []
