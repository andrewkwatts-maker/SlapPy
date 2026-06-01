from __future__ import annotations
from typing import Callable, Any

from slappyengine._event_bus_validation import (
    validate_event_type,
    validate_event_type_or_none,
    validate_callback,
    validate_bus_or_none,
)


class EventBus:
    """
    Lightweight synchronous pub-sub event bus.

    Usage:
        bus = EventBus()

        # Subscribe:
        bus.subscribe("entity:destroyed", lambda e: cleanup(e["entity"]))

        # Decorator form:
        @bus.on("scene:loaded")
        def handle_load(event):
            print(event["scene_name"])

        # One-shot:
        bus.once("intro:finished", lambda e: start_game())

        # Publish:
        bus.publish("entity:destroyed", entity=self, position=self.position)

        # Unsubscribe:
        bus.unsubscribe("entity:destroyed", my_callback)

        # Clear all listeners for an event (or all events):
        bus.clear("scene:loaded")
        bus.clear()

    Event payload is a plain dict passed as the sole argument to callbacks.
    Convention: event type strings use "namespace:action" (e.g. "entity:spawn",
    "ui:button_pressed", "scene:transition").
    """

    __slots__ = ("_listeners",)

    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable]] = {}

    def subscribe(self, event_type: str, callback: Callable[[dict], None]) -> None:
        """Register ``callback`` to fire on ``event_type``.

        Raises
        ------
        TypeError
            If ``event_type`` is not a ``str`` or ``callback`` is not callable.
        ValueError
            If ``event_type`` is the empty string.
        """
        validate_event_type("event_type", "EventBus.subscribe", event_type)
        validate_callback("callback", "EventBus.subscribe", callback)
        self._listeners.setdefault(event_type, []).append(callback)

    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        """Remove a previously-registered ``callback`` from ``event_type``.

        Raises
        ------
        TypeError
            If ``event_type`` is not a ``str``.
        ValueError
            If ``event_type`` is the empty string.
        """
        validate_event_type("event_type", "EventBus.unsubscribe", event_type)
        lst = self._listeners.get(event_type, [])
        try:
            lst.remove(callback)
        except ValueError:
            pass

    def once(self, event_type: str, callback: Callable[[dict], None]) -> None:
        """Subscribe for exactly one firing, then auto-unsubscribe.

        Raises
        ------
        TypeError
            If ``event_type`` is not a ``str`` or ``callback`` is not callable.
        ValueError
            If ``event_type`` is the empty string.
        """
        validate_event_type("event_type", "EventBus.once", event_type)
        validate_callback("callback", "EventBus.once", callback)

        def _wrapper(payload: dict) -> None:
            callback(payload)
            self.unsubscribe(event_type, _wrapper)
        self.subscribe(event_type, _wrapper)

    def on(self, event_type: str) -> Callable:
        """Decorator: ``@bus.on("event:type")``.

        Raises
        ------
        TypeError
            If ``event_type`` is not a ``str``.
        ValueError
            If ``event_type`` is the empty string.
        """
        validate_event_type("event_type", "EventBus.on", event_type)

        def decorator(fn: Callable) -> Callable:
            self.subscribe(event_type, fn)
            return fn
        return decorator

    def publish(self, event_type: str, **payload: Any) -> None:
        """Fire all subscribers for ``event_type`` with payload as a dict.

        Raises
        ------
        TypeError
            If ``event_type`` is not a ``str``.
        ValueError
            If ``event_type`` is the empty string.
        """
        # Inline the fast-path validation — calling `validate_event_type`
        # via a separate stack frame adds ~50ns to every publish, which
        # is observable in the no-subscriber bench (140 ns → 218 ns).
        # Keep the slow path identical so error messages match.
        if type(event_type) is not str:
            validate_event_type("event_type", "EventBus.publish", event_type)
        elif not event_type:
            validate_event_type("event_type", "EventBus.publish", event_type)
        for cb in list(self._listeners.get(event_type, [])):
            try:
                cb(payload)
            except Exception:
                pass

    def clear(self, event_type: str | None = None) -> None:
        """Drop all listeners for ``event_type`` (or every type when ``None``).

        Raises
        ------
        TypeError
            If ``event_type`` is not ``None`` and not a ``str``.
        ValueError
            If ``event_type`` is the empty string.
        """
        validate_event_type_or_none("event_type", "EventBus.clear", event_type)
        if event_type is None:
            self._listeners.clear()
        else:
            self._listeners.pop(event_type, None)

    def listener_count(self, event_type: str) -> int:
        """Return the number of listeners registered for ``event_type``.

        Raises
        ------
        TypeError
            If ``event_type`` is not a ``str``.
        ValueError
            If ``event_type`` is the empty string.
        """
        validate_event_type("event_type", "EventBus.listener_count", event_type)
        return len(self._listeners.get(event_type, []))

    def __repr__(self) -> str:
        total = sum(len(v) for v in self._listeners.values())
        return f"EventBus({len(self._listeners)} event types, {total} listeners)"


# Module-level default bus + thin function proxies. Legacy game code
# (slappyengine.trigger, slappyengine.deform_zones) imports
# ``from slappyengine.event_bus import publish, subscribe``; we keep that
# shape working by exposing a process-wide ``_DEFAULT_BUS`` singleton.
_DEFAULT_BUS = EventBus()


def publish(event_type: str, **payload) -> None:
    """Publish to the module-level default :class:`EventBus`."""
    _DEFAULT_BUS.publish(event_type, **payload)


def subscribe(event_type: str, listener) -> None:
    """Subscribe on the module-level default :class:`EventBus`."""
    _DEFAULT_BUS.subscribe(event_type, listener)


def unsubscribe(event_type: str, listener) -> None:
    """Unsubscribe from the module-level default :class:`EventBus`."""
    _DEFAULT_BUS.unsubscribe(event_type, listener)


def get_default_bus() -> EventBus:
    """Return the module-level default :class:`EventBus` singleton."""
    return _DEFAULT_BUS


class Observable:
    """Mixin for objects that publish change events through an EventBus.

    Games (Bullet Strata's reactive HUD per project_bullet_strata.md)
    subscribe to ``"changed"`` to rebuild on dirty state. ``notify(**payload)``
    forwards to the bus; ``subscribe(listener)`` is a thin proxy.
    """

    __slots__ = ("_bus", "_observable_topic")

    def __init__(self, bus: "EventBus | None" = None, topic: str = "changed") -> None:
        validate_bus_or_none("bus", "Observable.__init__", bus)
        validate_event_type("topic", "Observable.__init__", topic)
        self._bus = bus if bus is not None else EventBus()
        self._observable_topic = topic

    def notify(self, **payload) -> None:
        """Publish ``self._observable_topic`` on the bus with the given payload."""
        self._bus.publish(self._observable_topic, **payload)

    def subscribe(self, listener) -> None:
        """Subscribe ``listener`` to this observable's topic."""
        self._bus.subscribe(self._observable_topic, listener)

    def unsubscribe(self, listener) -> None:
        """Drop ``listener`` from this observable's topic."""
        self._bus.unsubscribe(self._observable_topic, listener)
