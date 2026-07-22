"""Input-validation tests for the public ``pharos_engine.telemetry`` API.

Engineering policy: validate at system boundaries, refuse bad input loudly
rather than silently coercing it to a default. Each test in this file
exercises one rejection path with a precise substring match so messages
stay useful for callers debugging their authoring code.

Positive paths live in :file:`tests/test_telemetry.py`; this file only
covers the rejection contract.
"""
from __future__ import annotations

import pytest

from pharos_engine import telemetry


@pytest.fixture(autouse=True)
def _reset_telemetry_state():
    """Reset module state between tests so order does not matter."""
    for handle in list(telemetry._subscribers):
        telemetry.unsubscribe(handle)
    telemetry.set_history_capacity(1000)
    telemetry.clear_history()
    yield
    for handle in list(telemetry._subscribers):
        telemetry.unsubscribe(handle)
    telemetry.set_history_capacity(1000)
    telemetry.clear_history()


# ---------------------------------------------------------------------------
# subscribe(name_pattern, callback)
# ---------------------------------------------------------------------------
def test_subscribe_rejects_non_string_pattern():
    with pytest.raises(TypeError, match="name_pattern"):
        telemetry.subscribe(42, lambda ev: None)  # type: ignore[arg-type]


def test_subscribe_rejects_bytes_pattern():
    """Bytes look glob-ish but bypass fnmatchcase semantics — refuse."""
    with pytest.raises(TypeError, match="name_pattern"):
        telemetry.subscribe(b"physics.*", lambda ev: None)  # type: ignore[arg-type]


def test_subscribe_rejects_none_callback():
    with pytest.raises(TypeError, match="callback"):
        telemetry.subscribe("physics.*", None)  # type: ignore[arg-type]


def test_subscribe_rejects_non_callable_callback():
    """A bare dict isn't callable — would crash inside emit's loop later."""
    with pytest.raises(TypeError, match="callback"):
        telemetry.subscribe("physics.*", {"not": "callable"})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# emit(name, **payload)
# ---------------------------------------------------------------------------
def test_emit_rejects_non_string_name():
    with pytest.raises(TypeError, match="name"):
        telemetry.emit(42)  # type: ignore[arg-type]


def test_emit_rejects_empty_name():
    """Empty name silently passes fnmatch — catch at the boundary."""
    with pytest.raises(ValueError, match="non-empty"):
        telemetry.emit("")


def test_emit_rejects_none_name():
    with pytest.raises(TypeError, match="name"):
        telemetry.emit(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# set_history_capacity(capacity)
# ---------------------------------------------------------------------------
def test_set_history_capacity_rejects_negative():
    with pytest.raises(ValueError, match="capacity"):
        telemetry.set_history_capacity(-1)


def test_set_history_capacity_rejects_float():
    """``deque(maxlen=2.5)`` would crash inside the deque; catch at boundary."""
    with pytest.raises(TypeError, match="capacity"):
        telemetry.set_history_capacity(2.5)  # type: ignore[arg-type]


def test_set_history_capacity_rejects_bool():
    """``set_history_capacity(True)`` almost certainly means a bug, not 1."""
    with pytest.raises(TypeError, match="capacity"):
        telemetry.set_history_capacity(True)  # type: ignore[arg-type]


def test_set_history_capacity_rejects_string():
    with pytest.raises(TypeError, match="capacity"):
        telemetry.set_history_capacity("100")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# enable_pattern_index(enabled)
# ---------------------------------------------------------------------------
def test_enable_pattern_index_rejects_non_bool_int():
    """Truthy int is NOT a bool — refuse silent coercion."""
    with pytest.raises(TypeError, match="enabled"):
        telemetry.enable_pattern_index(1)  # type: ignore[arg-type]


def test_enable_pattern_index_rejects_none():
    with pytest.raises(TypeError, match="enabled"):
        telemetry.enable_pattern_index(None)  # type: ignore[arg-type]


def test_enable_pattern_index_rejects_string():
    with pytest.raises(TypeError, match="enabled"):
        telemetry.enable_pattern_index("yes")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Round 13 — get_event_history(name_pattern, max_count)
#
# Silent-acceptance bugs caught here:
#   * ``max_count=-1`` silently returned an empty list (negative slicing in
#     ``filtered[-max_count:]`` would yield ``filtered[1:]`` instead — and
#     in tests, ``filtered[-(-1):]`` => ``filtered[1:]`` clipped the most
#     recent event!). Caller almost certainly wanted "everything".
#   * ``max_count=2.5`` silently passed (slicing accepts float in some
#     paths and crashes deep elsewhere).
#   * ``name_pattern=42`` reached ``fnmatchcase`` and crashed with a
#     confusing ``TypeError: 'int' object has no len()``.
# ---------------------------------------------------------------------------


def test_get_event_history_rejects_negative_max_count():
    """Silent-acceptance bug: -1 silently returned a wrong-sized slice."""
    with pytest.raises(ValueError, match="max_count must be >= 1"):
        telemetry.get_event_history("*", -1)


def test_get_event_history_rejects_zero_max_count():
    """``max_count=0`` is almost always a bug — refuse explicitly."""
    with pytest.raises(ValueError, match="max_count must be >= 1"):
        telemetry.get_event_history("*", 0)


def test_get_event_history_rejects_float_max_count():
    with pytest.raises(TypeError, match="max_count"):
        telemetry.get_event_history("*", 2.5)  # type: ignore[arg-type]


def test_get_event_history_rejects_bool_max_count():
    """``max_count=True`` would mean "return at most 1" — refuse silent coercion."""
    with pytest.raises(TypeError, match="max_count"):
        telemetry.get_event_history("*", True)  # type: ignore[arg-type]


def test_get_event_history_rejects_string_max_count():
    with pytest.raises(TypeError, match="max_count"):
        telemetry.get_event_history("*", "100")  # type: ignore[arg-type]


def test_get_event_history_rejects_int_pattern():
    """Silent-acceptance bug: int reached fnmatchcase and crashed obscurely."""
    with pytest.raises(TypeError, match="name_pattern"):
        telemetry.get_event_history(42, 10)  # type: ignore[arg-type]


def test_get_event_history_rejects_none_pattern():
    with pytest.raises(TypeError, match="name_pattern"):
        telemetry.get_event_history(None, 10)  # type: ignore[arg-type]


def test_get_event_history_rejects_bytes_pattern():
    """Bytes look glob-ish but fnmatchcase wants str."""
    with pytest.raises(TypeError, match="name_pattern"):
        telemetry.get_event_history(b"physics.*", 10)  # type: ignore[arg-type]


def test_get_event_history_rejects_empty_pattern():
    """Empty string never matches any event — refuse at the boundary."""
    with pytest.raises(ValueError, match="non-empty"):
        telemetry.get_event_history("", 10)


def test_get_event_history_accepts_valid_inputs():
    """Positive sanity: tightened validation does not break the happy path."""
    telemetry.subscribe("foo.*", lambda ev: None)
    telemetry.emit("foo.bar", x=1)
    telemetry.emit("foo.baz", y=2)
    out = telemetry.get_event_history("foo.*", 10)
    assert [e.name for e in out] == ["foo.bar", "foo.baz"]


def test_get_event_history_respects_max_count_cap():
    """Positive sanity: max_count slices to the most recent N."""
    telemetry.emit("a")
    telemetry.emit("b")
    telemetry.emit("c")
    out = telemetry.get_event_history("*", 2)
    assert [e.name for e in out] == ["b", "c"]
