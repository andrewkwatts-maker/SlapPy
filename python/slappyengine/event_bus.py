from __future__ import annotations
from typing import Callable, Any

from slappyengine._event_bus_validation import (
    validate_event_type,
    validate_callback,
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
        validate_event_type("event_type", "EventBus.publish", event_type)
        for cb in list(self._listeners.get(event_type, [])):
            try:
                cb(payload)
            except Exception:
                pass

    def clear(self, event_type: str | None = None) -> None:
        if event_type is None:
            self._listeners.clear()
        else:
            self._listeners.pop(event_type, None)

    def listener_count(self, event_type: str) -> int:
        return len(self._listeners.get(event_type, []))

    def __repr__(self) -> str:
        total = sum(len(v) for v in self._listeners.values())
        return f"EventBus({len(self._listeners)} event types, {total} listeners)"
