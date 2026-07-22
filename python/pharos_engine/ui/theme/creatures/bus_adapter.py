"""EventBus -> CreatureScheduler adapter.

The adapter is the one and only seam between the engine event-bus and
the woodland-creature scheduler. It is intentionally tolerant:

* The scheduler may be partial — looking up a creature that nobody
  registered is **not** an error; it logs at ``WARNING`` and skips.
* The scheduler module itself may not have landed yet (U3 is shipping
  in a sibling sprint). The adapter accepts any object that exposes a
  ``trigger(creature_id, anim_name)`` callable; missing schedulers
  raise at construction time, not on every event.
* Debounce: the same ``(event, creature_id, anim_name)`` binding will
  not re-fire within ``debounce_ms`` (default 500 ms) — this prevents
  a chatty save loop from making the butterfly spin.

The :data:`EVENT_TO_CREATURE_ANIMS` table is read once at install time;
re-installing rebinds.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Protocol

from pharos_engine._validation import (
    validate_callable,
    validate_non_empty_str,
    validate_positive_float,
)
from pharos_engine._event_bus_validation import validate_bus_or_none
from pharos_engine.event_bus import EventBus

from .event_bindings import EVENT_TO_CREATURE_ANIMS

logger = logging.getLogger(__name__)


class _SchedulerLike(Protocol):
    """Structural protocol for the bits of CreatureScheduler we touch."""

    def trigger(self, creature_id: str, anim_name: str) -> Any: ...


# Default debounce in milliseconds — also the value documented in the
# class docstring. Centralised so the test suite can reference it.
DEFAULT_DEBOUNCE_MS: float = 500.0


class CreatureBusAdapter:
    """Subscribe a :class:`CreatureScheduler` to the engine event bus.

    Parameters
    ----------
    scheduler:
        Any object exposing ``trigger(creature_id, anim_name)``. The
        sibling U3 sprint provides
        :class:`pharos_engine.ui.theme.creatures.scheduler.CreatureScheduler`;
        tests use a tiny stub.
    bus:
        The :class:`EventBus` to subscribe on. ``None`` is rejected to
        keep the failure mode obvious — caller must hand in an explicit
        bus (typically ``pharos_engine.event_bus.get_default_bus()``).
    debounce_ms:
        Minimum milliseconds between *same-binding* refires. The same
        event fired three times in 100 ms triggers the animation once.
        Default :data:`DEFAULT_DEBOUNCE_MS` (500 ms).

    Raises
    ------
    TypeError
        If *scheduler* has no callable ``trigger`` attribute, or *bus*
        is not an :class:`EventBus`.
    ValueError
        If *debounce_ms* is not a positive finite number.
    """

    __slots__ = (
        "_scheduler",
        "_bus",
        "_debounce_s",
        "_subscriptions",
        "_last_fired",
        "_installed",
    )

    def __init__(
        self,
        scheduler: _SchedulerLike,
        bus: EventBus,
        *,
        debounce_ms: float = DEFAULT_DEBOUNCE_MS,
    ) -> None:
        # The scheduler must expose a callable ``trigger`` — validate by
        # duck-typing, not isinstance, so partial fakes work in tests.
        trigger = getattr(scheduler, "trigger", None)
        validate_callable(
            "scheduler.trigger", "CreatureBusAdapter.__init__", trigger
        )
        validate_bus_or_none("bus", "CreatureBusAdapter.__init__", bus)
        if bus is None:
            raise TypeError(
                "CreatureBusAdapter.__init__: bus must not be None"
            )
        debounce_ms_f = validate_positive_float(
            "debounce_ms", "CreatureBusAdapter.__init__", debounce_ms
        )

        self._scheduler = scheduler
        self._bus = bus
        self._debounce_s = debounce_ms_f / 1000.0
        # event_name -> bound handler (so we can unsubscribe the exact
        # callable we registered).
        self._subscriptions: dict[str, Callable[[dict], None]] = {}
        # (event_name, creature_id, anim_name) -> monotonic seconds of
        # the last successful fire. Used for debounce.
        self._last_fired: dict[tuple[str, str, str], float] = {}
        self._installed = False

    # ------------------------------------------------------------------
    # Install / uninstall
    # ------------------------------------------------------------------

    def install(self) -> None:
        """Subscribe to every key in :data:`EVENT_TO_CREATURE_ANIMS`.

        Idempotent: calling twice is a no-op (the second call sees the
        ``_installed`` flag and returns immediately). Use
        :meth:`uninstall` to fully reset, then :meth:`install` to rebind.
        """
        if self._installed:
            return
        for event_name in EVENT_TO_CREATURE_ANIMS:
            handler = self._make_handler(event_name)
            self._bus.subscribe(event_name, handler)
            self._subscriptions[event_name] = handler
        self._installed = True

    def uninstall(self) -> None:
        """Unsubscribe every handler installed by :meth:`install`."""
        for event_name, handler in self._subscriptions.items():
            self._bus.unsubscribe(event_name, handler)
        self._subscriptions.clear()
        self._last_fired.clear()
        self._installed = False

    # ------------------------------------------------------------------
    # Trigger plumbing
    # ------------------------------------------------------------------

    def trigger_for_event(self, event_name: str) -> int:
        """Fire every binding registered for *event_name* once.

        Honours debounce. Returns the number of animations actually
        fired (bindings filtered by debounce are *not* counted).

        Raises
        ------
        TypeError / ValueError
            If *event_name* is not a non-empty ``str``.
        """
        validate_non_empty_str(
            "event_name", "CreatureBusAdapter.trigger_for_event", event_name
        )
        bindings = EVENT_TO_CREATURE_ANIMS.get(event_name)
        if not bindings:
            return 0
        now = time.monotonic()
        fired = 0
        for creature_id, anim_name in bindings:
            key = (event_name, creature_id, anim_name)
            last = self._last_fired.get(key)
            if last is not None and (now - last) < self._debounce_s:
                # Debounced — skip without logging (chatty otherwise).
                continue
            if self._try_trigger(creature_id, anim_name):
                self._last_fired[key] = now
                fired += 1
        return fired

    def _make_handler(self, event_name: str) -> Callable[[dict], None]:
        """Build the subscriber closure for *event_name*."""
        def _handler(_payload: dict) -> None:
            self.trigger_for_event(event_name)
        # Tag the closure so introspection (and tests) can recover the
        # event-name it serves without reading bus internals.
        _handler.__event_name__ = event_name  # type: ignore[attr-defined]
        return _handler

    def _try_trigger(self, creature_id: str, anim_name: str) -> bool:
        """Call ``scheduler.trigger``; swallow missing-creature errors.

        Returns ``True`` on a successful trigger so the debounce table
        only records real fires.
        """
        try:
            self._scheduler.trigger(creature_id, anim_name)
        except KeyError:
            # Missing creature on a partial roster — common during
            # progressive theme rollout. Log once at WARNING per call;
            # the scheduler can dedup downstream.
            logger.warning(
                "CreatureBusAdapter: no creature %r registered for anim %r",
                creature_id,
                anim_name,
            )
            return False
        except LookupError:
            # Some scheduler impls raise LookupError instead of KeyError.
            logger.warning(
                "CreatureBusAdapter: no creature %r registered for anim %r",
                creature_id,
                anim_name,
            )
            return False
        except Exception:  # noqa: BLE001 — never let scheduler bugs
            # break the editor; the bus already swallows handler
            # exceptions, but we log here so the trace is recoverable.
            logger.exception(
                "CreatureBusAdapter: scheduler.trigger(%r, %r) raised",
                creature_id,
                anim_name,
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def installed(self) -> bool:
        """``True`` once :meth:`install` has run and not been undone."""
        return self._installed

    @property
    def subscribed_events(self) -> tuple[str, ...]:
        """Tuple of event names this adapter is currently subscribed to."""
        return tuple(self._subscriptions)


__all__ = ["CreatureBusAdapter", "DEFAULT_DEBOUNCE_MS"]
