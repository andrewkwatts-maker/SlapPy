"""Input-validation tests for the public ``slappyengine.telemetry`` API.

Engineering policy: validate at system boundaries, refuse bad input loudly
rather than silently coercing it to a default. Each test in this file
exercises one rejection path with a precise substring match so messages
stay useful for callers debugging their authoring code.

Positive paths live in :file:`tests/test_telemetry.py`; this file only
covers the rejection contract.
"""
from __future__ import annotations

import pytest

from slappyengine import telemetry


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
