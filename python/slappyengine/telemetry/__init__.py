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
- :func:`enable_pattern_index` — opt-in O(matching) dispatch (default OFF)
- :func:`is_pattern_index_enabled` — query the index toggle

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
* When the pattern index is enabled, subscribers are also grouped into
  buckets keyed by the first dotted segment of their pattern (e.g.
  ``"physics.step"`` -> bucket ``"physics"``, ``"*"`` -> bucket ``"*"``).
  ``emit`` then walks only the bucket matching the event's first segment
  plus the catch-all ``"*"`` bucket — O(matching subscribers) instead of
  O(all subscribers). The index is opt-in via
  :func:`enable_pattern_index`; default is OFF for backward compat.
"""
from __future__ import annotations

import fnmatch
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from ._validation import (
    validate_bool,
    validate_callable,
    validate_non_negative_int,
    validate_str,
)

__all__ = [
    "TelemetryEvent",
    "emit",
    "subscribe",
    "unsubscribe",
    "get_event_history",
    "clear_history",
    "set_history_capacity",
    "enable_pattern_index",
    "is_pattern_index_enabled",
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
# Pattern index (opt-in)
# ---------------------------------------------------------------------------
# When enabled, _bucket_index maps first-segment -> insertion-ordered list of
# (handle, pattern, callback) tuples. Catch-all patterns ("*", or any pattern
# whose first segment contains glob metachars) land in the "*"-bucket so they
# match every event.
#
# Dispatch walks bucket[first_segment(name)] then bucket["*"] in insertion
# order, preserving subscription-time order WITHIN each bucket and matching
# the legacy unindexed dispatch order for the common case (subscribers in
# a single bucket). Cross-bucket order can differ when a "*"-subscriber is
# registered between two "physics.*"-subscribers — same set of deliveries,
# different ordering. Documented in telemetry_design.md.
_pattern_index_enabled: bool = False
_bucket_index: Dict[str, List[Tuple[int, str, Callable[[TelemetryEvent], None]]]] = {}
_CATCHALL_BUCKET = "*"
_GLOB_META = frozenset("*?[")


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

    Raises
    ------
    TypeError
        If ``name`` is not a ``str``.
    ValueError
        If ``name`` is the empty string.
    """
    validate_str("name", "emit", name, allow_empty=False)
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
    if _pattern_index_enabled:
        # O(matching) dispatch: walk the event's first-segment bucket plus
        # the catch-all bucket. Bucket lookups are read-only against the
        # dict; we snapshot each bucket's list under the lock so
        # concurrent subscribe/unsubscribe cannot mutate it mid-iteration.
        seg = _first_segment(name)
        with _lock:
            primary = list(_bucket_index.get(seg, ())) if seg != _CATCHALL_BUCKET else []
            catchall = list(_bucket_index.get(_CATCHALL_BUCKET, ()))
        # Primary bucket: same first segment as the event. fnmatch is still
        # used for fine-grained match (e.g. "physics.step" vs "physics.*"
        # vs "physics.collision"). Catch-all bucket is dispatched
        # unconditionally if its pattern is exactly "*" — otherwise we
        # still fnmatch (e.g. "*.step").
        for _handle, pattern, callback in primary:
            if pattern == name or fnmatch.fnmatchcase(name, pattern):
                try:
                    callback(event)
                except Exception:  # noqa: BLE001
                    import logging
                    logging.getLogger(__name__).exception(
                        "telemetry subscriber for pattern %r raised", pattern
                    )
        for _handle, pattern, callback in catchall:
            if pattern == _CATCHALL_BUCKET or fnmatch.fnmatchcase(name, pattern):
                try:
                    callback(event)
                except Exception:  # noqa: BLE001
                    import logging
                    logging.getLogger(__name__).exception(
                        "telemetry subscriber for pattern %r raised", pattern
                    )
        return

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

    Raises
    ------
    TypeError
        If ``name_pattern`` is not a ``str`` or ``callback`` is not callable.
    """
    validate_str("name_pattern", "subscribe", name_pattern)
    validate_callable("callback", "subscribe", callback)
    global _next_handle
    with _lock:
        handle = _next_handle
        _next_handle += 1
        _subscribers[handle] = (name_pattern, callback)
        if _pattern_index_enabled:
            bucket = _bucket_for_pattern(name_pattern)
            _bucket_index.setdefault(bucket, []).append(
                (handle, name_pattern, callback)
            )
    return handle


def unsubscribe(handle: int) -> None:
    """Drop a subscription previously returned by :func:`subscribe`.

    Silently ignores unknown handles so double-unsubscribe is safe.
    """
    with _lock:
        entry = _subscribers.pop(handle, None)
        if entry is None or not _pattern_index_enabled:
            return
        pattern, _callback = entry
        bucket_key = _bucket_for_pattern(pattern)
        bucket = _bucket_index.get(bucket_key)
        if bucket is None:
            return
        # Remove the entry matching this handle. List order is preserved.
        for i, (h, _p, _c) in enumerate(bucket):
            if h == handle:
                del bucket[i]
                break
        if not bucket:
            _bucket_index.pop(bucket_key, None)


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


# ---------------------------------------------------------------------------
# Pattern index helpers
# ---------------------------------------------------------------------------
def _first_segment(name: str) -> str:
    """Return the first dotted segment of *name*.

    ``"physics.step"`` -> ``"physics"``, ``"tick"`` -> ``"tick"``.
    """
    dot = name.find(".")
    return name if dot < 0 else name[:dot]


def _bucket_for_pattern(pattern: str) -> str:
    """Return the index bucket key for *pattern*.

    The bucket is the pattern's first dotted segment when that segment is a
    literal (no glob metachars). Otherwise the pattern lands in the
    catch-all bucket ``"*"`` so it is checked against every event.

    Examples
    --------
    * ``"physics.step"`` -> ``"physics"``
    * ``"physics.*"``    -> ``"physics"`` (first segment is literal)
    * ``"*"``            -> ``"*"``
    * ``"*.step"``       -> ``"*"`` (first segment has a glob metachar)
    * ``"thermal"``      -> ``"thermal"``
    """
    seg = _first_segment(pattern)
    if any(ch in _GLOB_META for ch in seg):
        return _CATCHALL_BUCKET
    return seg


def _rebuild_bucket_index_locked() -> None:
    """Rebuild ``_bucket_index`` from ``_subscribers``. Caller holds ``_lock``."""
    _bucket_index.clear()
    for handle, (pattern, callback) in _subscribers.items():
        bucket = _bucket_for_pattern(pattern)
        _bucket_index.setdefault(bucket, []).append((handle, pattern, callback))


def enable_pattern_index(enabled: bool = True) -> None:
    """Toggle the opt-in first-segment pattern index for :func:`emit`.

    When enabled, ``emit`` dispatches in O(matching subscribers) by grouping
    subscribers by the first dotted segment of their pattern, rather than
    scanning every subscriber. Default is OFF for backward compatibility:
    the unindexed dispatch path is unchanged when this is never called.

    Toggling does not lose subscriptions — the index is rebuilt from the
    canonical ``_subscribers`` dict.

    Parameters
    ----------
    enabled : bool
        ``True`` to enable indexed dispatch, ``False`` to disable.

    Raises
    ------
    TypeError
        If ``enabled`` is not a ``bool``.
    """
    validate_bool("enabled", "enable_pattern_index", enabled)
    global _pattern_index_enabled
    with _lock:
        _pattern_index_enabled = bool(enabled)
        if _pattern_index_enabled:
            _rebuild_bucket_index_locked()
        else:
            _bucket_index.clear()


def is_pattern_index_enabled() -> bool:
    """Return whether the pattern index is currently enabled."""
    return _pattern_index_enabled


def set_history_capacity(capacity: int) -> None:
    """Resize the ring buffer.

    Set *capacity* to 0 to disable history entirely — combined with zero
    subscribers, that activates the fully allocation-free fast path in
    :func:`emit`.

    Existing events beyond the new capacity are dropped (oldest first).

    Raises
    ------
    TypeError
        If ``capacity`` is not a plain ``int`` (floats/bools refused).
    ValueError
        If ``capacity < 0``.
    """
    validate_non_negative_int("capacity", "set_history_capacity", capacity)

    global _history, _history_capacity
    with _lock:
        _history_capacity = int(capacity)
        if capacity == 0:
            _history = deque(maxlen=0)
        else:
            # deque(maxlen=N) preserves the most recent N entries when
            # constructed from an oversized iterable.
            _history = deque(_history, maxlen=capacity)
