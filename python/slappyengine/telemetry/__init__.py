"""
slappyengine.telemetry
======================

Instrumentation as a first-class engine API.

Games subscribe to engine events (physics steps, render frames, thermal
phase changes, ...) for debugging, profiling, or save-state diffing.

The pattern was promoted to the engine API after Bullet Strata's reactive
HUD dirty flag proved that every game eventually wants this hook.

Public surface
--------------
- :class:`TelemetryEvent`     — frozen dataclass carrying name/timestamp/payload
- :func:`emit`                — publish an event (hot path; free when idle)
- :func:`subscribe`           — register a glob-pattern callback
- :func:`unsubscribe`         — drop a subscription by handle
- :func:`get_event_history`   — read recent events without subscribing
- :func:`clear_history`       — drop the in-memory ring buffer
- :func:`set_history_capacity` — resize the ring buffer (0 disables history)

Design notes
------------
* ``emit`` is the hot path. When there are zero subscribers AND the ring
  buffer is disabled, it returns immediately without allocating a
  :class:`TelemetryEvent`.
* Subscriber lookup uses :func:`fnmatch.fnmatchcase` for glob semantics —
  patterns like ``"physics.*"`` or ``"thermal.phase_change"`` work as
  expected.
* A single :class:`threading.Lock` guards subscribe/unsubscribe and
  history mutations. ``emit`` snapshots the subscriber list and ring
  buffer under the lock briefly, so concurrent emits do not race.
"""
from __future__ import annotations

import fnmatch
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

__all__ = [
    "TelemetryEvent",
    "emit",
    "subscribe",
    "unsubscribe",
    "get_event_history",
    "clear_history",
    "set_history_capacity",
]


# ---------------------------------------------------------------------------
# Event record
# ---------------------------------------------------------------------------
@dataclass
class TelemetryEvent:
    """A single telemetry event published via :func:`emit`."""

    name: str
    timestamp: float
    payload: Dict[str, Any] = field(default_factory=dict)
    source: Optional[str] = None


# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------
_lock: threading.Lock = threading.Lock()

# {handle: (pattern, callback)} — read concurrently during emit
_subscribers: Dict[int, Tuple[str, Callable[[TelemetryEvent], None]]] = {}
_next_handle: int = 0

_DEFAULT_HISTORY_CAPACITY = 1000
_history_capacity: int = _DEFAULT_HISTORY_CAPACITY
_history: Deque[TelemetryEvent] = deque(maxlen=_DEFAULT_HISTORY_CAPACITY)


# ---------------------------------------------------------------------------
# emit (hot path)
# ---------------------------------------------------------------------------
def emit(name: str, **payload: Any) -> None:
    """Publish a telemetry event.

    No-op (and allocation-free) when there are zero subscribers AND the
    history ring buffer is disabled. Otherwise the event is delivered to
    every subscriber whose glob pattern matches ``name`` and appended to
    the ring buffer.

    Parameters
    ----------
    name : str
        Dotted event name, e.g. ``"physics.step"``.
    **payload : Any
        Arbitrary key/value data. Copied into the event's payload dict.
    """
    # Fast path: nothing to do. Two attribute lookups + a bool — no alloc.
    if not _subscribers and _history_capacity == 0:
        return

    # Build the event exactly once.
    event = TelemetryEvent(
        name=name,
        timestamp=time.perf_counter(),
        payload=dict(payload),
        source=payload.get("source"),
    )

    # Append to history under the lock so the deque stays consistent
    # across concurrent emits.
    if _history_capacity > 0:
        with _lock:
            _history.append(event)

    # Snapshot subscribers so callbacks run without holding the lock.
    # ``list(dict.values())`` is atomic under CPython's GIL but we copy
    # explicitly to remain robust under PEP 703 (no-GIL) builds.
    with _lock:
        snapshot = list(_subscribers.values())

    for pattern, callback in snapshot:
        if fnmatch.fnmatchcase(name, pattern):
            try:
                callback(event)
            except Exception:  # noqa: BLE001
                # Subscriber callbacks must never break the producer.
                # Surface via stdlib logging so the user can see it but
                # do not propagate.
                import logging
                logging.getLogger(__name__).exception(
                    "telemetry subscriber for pattern %r raised", pattern
                )


# ---------------------------------------------------------------------------
# subscribe / unsubscribe
# ---------------------------------------------------------------------------
def subscribe(
    name_pattern: str,
    callback: Callable[[TelemetryEvent], None],
) -> int:
    """Register *callback* for events whose name matches *name_pattern*.

    Pattern matching uses :func:`fnmatch.fnmatchcase` (glob semantics):

    * ``"physics.step"``  — exact match
    * ``"physics.*"``     — any ``physics.something`` event
    * ``"*"``             — every event

    Returns
    -------
    int
        Opaque handle. Pass it to :func:`unsubscribe` to drop the
        subscription.
    """
    global _next_handle
    with _lock:
        handle = _next_handle
        _next_handle += 1
        _subscribers[handle] = (name_pattern, callback)
    return handle


def unsubscribe(handle: int) -> None:
    """Drop a subscription previously returned by :func:`subscribe`.

    Silently ignores unknown handles so double-unsubscribe is safe.
    """
    with _lock:
        _subscribers.pop(handle, None)


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
def get_event_history(
    name_pattern: str = "*",
    max_count: int = 1000,
) -> List[TelemetryEvent]:
    """Return up to *max_count* recent events whose name matches *name_pattern*.

    The returned list is in chronological order (oldest first within the
    ring buffer). When the buffer holds more than *max_count* matching
    events, only the most recent *max_count* are returned.

    Parameters
    ----------
    name_pattern : str
        Glob pattern; defaults to ``"*"`` (everything).
    max_count : int
        Cap on the returned list length. Defaults to 1000.
    """
    with _lock:
        snapshot = list(_history)

    if name_pattern == "*":
        filtered = snapshot
    else:
        filtered = [e for e in snapshot if fnmatch.fnmatchcase(e.name, name_pattern)]

    if len(filtered) > max_count:
        filtered = filtered[-max_count:]
    return filtered


def clear_history() -> None:
    """Drop every event in the ring buffer.

    Useful between scenes so post-mortem queries don't return stale data
    from the previous level.
    """
    with _lock:
        _history.clear()


def set_history_capacity(capacity: int) -> None:
    """Resize the ring buffer.

    Set *capacity* to 0 to disable history entirely — combined with zero
    subscribers, that activates the fully allocation-free fast path in
    :func:`emit`.

    Existing events beyond the new capacity are dropped (oldest first).
    """
    if capacity < 0:
        raise ValueError(f"capacity must be >= 0, got {capacity!r}")

    global _history, _history_capacity
    with _lock:
        _history_capacity = capacity
        if capacity == 0:
            _history = deque(maxlen=0)
        else:
            # deque(maxlen=N) preserves the most recent N entries when
            # constructed from an oversized iterable.
            _history = deque(_history, maxlen=capacity)
