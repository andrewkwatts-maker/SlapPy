"""Synthetic idle-event emitter.

The engine doesn't natively publish ``engine.idle_60s`` /
``engine.idle_120s`` — the editor host calls :meth:`tick` each frame
with the frame delta, and :class:`IdleEventEmitter` publishes the right
event the first time the accumulated idle time crosses each threshold.
Any real user input calls :meth:`reset_activity` and the timer restarts.

Thresholds are configurable so other timeouts (e.g. a hypothetical
``engine.idle_300s`` "deep sleep" pulse) can be wired without changing
the class.
"""
from __future__ import annotations

from typing import Iterable

from slappyengine._validation import (
    validate_non_empty_str,
    validate_non_negative_float,
    validate_positive_float,
)
from slappyengine._event_bus_validation import validate_bus_or_none
from slappyengine.event_bus import EventBus


_DEFAULT_INTERVALS: tuple[tuple[str, float], ...] = (
    ("engine.idle_60s", 60.0),
    ("engine.idle_120s", 120.0),
)


class IdleEventEmitter:
    """Emit idle-pulse events when the user has been inactive long enough.

    Parameters
    ----------
    bus:
        The :class:`EventBus` to publish on.
    intervals:
        Iterable of ``(event_name, threshold_seconds)`` tuples. Each
        event fires the first time accumulated idle time crosses its
        threshold; firing again requires a :meth:`reset_activity` call.
        Defaults to ``(("engine.idle_60s", 60.0), ("engine.idle_120s",
        120.0))`` per the design spec.

    Raises
    ------
    TypeError / ValueError
        On invalid bus, event names, or non-positive thresholds.
    """

    __slots__ = ("_bus", "_intervals", "_idle_s", "_fired")

    def __init__(
        self,
        bus: EventBus,
        intervals: Iterable[tuple[str, float]] | None = None,
    ) -> None:
        validate_bus_or_none("bus", "IdleEventEmitter.__init__", bus)
        if bus is None:
            raise TypeError(
                "IdleEventEmitter.__init__: bus must not be None"
            )
        if intervals is None:
            intervals = _DEFAULT_INTERVALS
        # Materialise once so the iterable can't be exhausted mid-life.
        parsed: list[tuple[str, float]] = []
        for idx, entry in enumerate(intervals):
            if (
                not hasattr(entry, "__len__")
                or len(entry) != 2
            ):
                raise TypeError(
                    "IdleEventEmitter.__init__: intervals[%d] must be a "
                    "(event_name, threshold_seconds) tuple" % idx
                )
            name = validate_non_empty_str(
                f"intervals[{idx}][0]",
                "IdleEventEmitter.__init__",
                entry[0],
            )
            threshold = validate_positive_float(
                f"intervals[{idx}][1]",
                "IdleEventEmitter.__init__",
                entry[1],
            )
            parsed.append((name, threshold))
        # Sort ascending by threshold so the cross-detection loop fires
        # the 60 s event before the 120 s one even if the caller passed
        # them out of order.
        parsed.sort(key=lambda pair: pair[1])

        self._bus = bus
        self._intervals: tuple[tuple[str, float], ...] = tuple(parsed)
        self._idle_s: float = 0.0
        # event_name -> already-fired flag in the current idle window.
        self._fired: dict[str, bool] = {n: False for n, _ in self._intervals}

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    def reset_activity(self) -> None:
        """Mark the user as active *now* — restarts every threshold."""
        self._idle_s = 0.0
        for name in self._fired:
            self._fired[name] = False

    def tick(self, dt: float) -> None:
        """Advance idle time by ``dt`` seconds and publish crossings.

        ``dt`` must be a non-negative finite number — the editor host
        passes the frame delta so 0.0 is legitimate on pause-frames.

        Each threshold publishes exactly once per idle window. Calling
        :meth:`reset_activity` reopens every window.
        """
        dt_f = validate_non_negative_float(
            "dt", "IdleEventEmitter.tick", dt
        )
        if dt_f == 0.0:
            return
        self._idle_s += dt_f
        for name, threshold in self._intervals:
            if not self._fired[name] and self._idle_s >= threshold:
                self._fired[name] = True
                self._bus.publish(name, idle_seconds=self._idle_s)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def idle_seconds(self) -> float:
        """Seconds of idle time accumulated since the last reset."""
        return self._idle_s

    def has_fired(self, event_name: str) -> bool:
        """``True`` if *event_name* has already fired this idle window."""
        validate_non_empty_str(
            "event_name", "IdleEventEmitter.has_fired", event_name
        )
        return self._fired.get(event_name, False)


__all__ = ["IdleEventEmitter"]
