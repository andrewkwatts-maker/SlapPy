from __future__ import annotations
from typing import Callable, Any, Iterator

from slappyengine._event_bus_validation import (
    validate_event_type,
    validate_event_type_or_none,
    validate_callback,
    validate_bus_or_none,
)


class EventPayload(dict):
    """Dual-shape event payload — behaves as BOTH object AND dict.

    Downstream games (Ochema Circuit, Bullet Strata) index event payloads
    through attribute access:

        def _on_speed(self, evt):
            if evt.publisher is not self._vehicle:  # ← attribute access
                return
            self._speed = float(evt.value)          # ← ad-hoc kwarg attr

    Internal engine callers use dict indexing:

        bus.subscribe("topic", lambda p: p.get("v", 0))

    ``EventPayload`` unifies both patterns by subclassing ``dict`` (so
    ``p["k"]``, ``p.get(...)``, ``"k" in p``, ``p.keys()`` all work) while
    also promoting every kwarg to an attribute (so ``p.publisher``,
    ``p.value``, ``p.lap`` etc. resolve).

    Standard shape (set for every published event):

    * ``name`` — event type string (mirrors legacy ``evt.name``)
    * ``label`` — alias for ``name`` (matches YY1 spec)
    * ``publisher`` — kwarg promoted to attribute (``None`` if absent)
    * ``data`` — same as ``payload`` (the raw kwargs dict)
    * ``payload`` — nested dict of the kwargs (Ochema ``evt.payload.get(...)``)
    * ``timestamp`` — float wall-clock seconds when the event fired

    Every additional kwarg passed to :meth:`EventBus.publish` is promoted
    to both a dict key AND an attribute — so ``publish("t", value=7)``
    yields ``evt.value == evt["value"] == 7``.
    """

    __slots__ = ()

    def __init__(
        self,
        name: str = "",
        publisher: Any = None,
        payload: dict | None = None,
        timestamp: float = 0.0,
        **extra: Any,
    ) -> None:
        # Build the underlying dict — start from payload kwargs then overlay
        # the reserved keys so publisher/name/etc. always resolve.
        payload_dict = dict(payload) if payload else {}
        payload_dict.update(extra)
        super().__init__(payload_dict)
        # Reserved keys are set via dict assignment so __getitem__ finds
        # them without needing a fallback in the lookup path.
        self["name"] = name
        self["label"] = name  # YY1-spec alias
        self["publisher"] = publisher
        self["data"] = payload_dict
        self["payload"] = payload_dict
        self["timestamp"] = float(timestamp)

    # ---- attribute access ------------------------------------------------
    def __getattr__(self, key: str) -> Any:
        # Only reached when normal attribute lookup fails — fall back to
        # the dict. Raise AttributeError (not KeyError) to keep ``hasattr``
        # and ``getattr(evt, k, default)`` working.
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key) from None

    def __setattr__(self, key: str, value: Any) -> None:
        # Support ``evt.progress = 0.65`` mutation pattern seen in
        # Ochema's test_q8_garage_polish.py — write to the dict so both
        # attribute and item access observe the update.
        self[key] = value


# Backwards-compat: ``EventDetails`` was the legacy alias for the event
# payload dict handed to subscribers. Ochema Circuit's HUD entity type-hints
# every callback with ``evt: EventDetails`` and imports it from
# ``slappyengine.event_bus``. Kept as an alias for the new ``EventPayload``
# class so the import path resolves, type hints remain valid, and the alias
# still behaves as a ``dict`` for any legacy ``isinstance(evt, dict)`` check.
# DO NOT REMOVE without a v1.0 deprecation cycle.
EventDetails = EventPayload  # type alias — dual-shape payload passed to subscribers


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

    def unsubscribe(
        self,
        event_type: str | None = None,
        callback: Callable | None = None,
    ) -> None:
        """Remove a previously-registered ``callback`` from ``event_type``.

        Legacy semantics preserved for downstream games (Ochema Circuit,
        Bullet Strata):

        * ``unsubscribe(topic)`` — remove ALL listeners for ``topic``.
        * ``unsubscribe(topic, listener)`` — remove specific listener from
          ``topic``.
        * ``unsubscribe(None, listener)`` — remove ``listener`` from EVERY
          topic (teardown/cleanup pattern).
        * ``unsubscribe()`` or ``unsubscribe(None, None)`` — no-op.

        DO NOT tighten this signature without a v1.0 deprecation cycle.

        Raises
        ------
        TypeError
            If ``event_type`` is neither ``None`` nor a ``str``.
        ValueError
            If ``event_type`` is the empty string.
        """
        # Case 1: no-op — nothing supplied to remove.
        if event_type is None and callback is None:
            return

        # Case 2: teardown pattern — drop this callback from every topic.
        if event_type is None:
            for topic in list(self._listeners.keys()):
                self._listeners[topic] = [
                    l for l in self._listeners[topic] if l is not callback
                ]
                if not self._listeners[topic]:
                    del self._listeners[topic]
            return

        # Case 3 & 4: topic-scoped. event_type must now be a valid str.
        validate_event_type("event_type", "EventBus.unsubscribe", event_type)
        if callback is None:
            # Legacy 1-arg form: drop every listener bound to this topic.
            self._listeners.pop(event_type, None)
            return
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

    def publish(self, event_type: str, **payload: Any) -> "EventPayload":
        """Fire all subscribers for ``event_type`` with a dual-shape payload.

        Returns
        -------
        EventPayload
            The event object handed to every subscriber. Supports both
            attribute access (``evt.publisher``, ``evt.value``) and dict
            access (``evt["publisher"]``, ``evt.get("value", default)``).
            Downstream games (Ochema Circuit's HUD/audio systems, Bullet
            Strata's reactive HUD) rely on the attribute-access shape.

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
        publisher = payload.pop("publisher", None)
        # Lazy timestamp — only paid when someone actually reads it,
        # but populate eagerly so callbacks that inspect ``evt.timestamp``
        # see a real value rather than 0.0.
        import time as _time
        evt = EventPayload(
            name=event_type,
            publisher=publisher,
            payload=payload,
            timestamp=_time.time(),
        )
        for cb in list(self._listeners.get(event_type, [])):
            try:
                cb(evt)
            except Exception:
                pass
        return evt

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


def publish(event_type: str, **payload) -> "EventPayload":
    """Publish to the module-level default :class:`EventBus`.

    Returns the :class:`EventPayload` handed to subscribers so callers
    that assign ``event = publish(...)`` can inspect it (dual attribute
    and dict access — see :class:`EventPayload`).
    """
    return _DEFAULT_BUS.publish(event_type, **payload)


def subscribe(event_type: str, listener) -> None:
    """Subscribe on the module-level default :class:`EventBus`."""
    _DEFAULT_BUS.subscribe(event_type, listener)


def unsubscribe(event_type: str | None = None, listener=None) -> None:
    """Unsubscribe from the module-level default :class:`EventBus`.

    Backwards-compat: mirrors :meth:`EventBus.unsubscribe` — supports the
    legacy 1-arg ``unsubscribe("topic")`` shape AND the teardown pattern
    ``unsubscribe(None, listener)`` which drops ``listener`` from every
    topic. ``unsubscribe()`` is a no-op.
    """
    _DEFAULT_BUS.unsubscribe(event_type, listener)


def get_default_bus() -> EventBus:
    """Return the module-level default :class:`EventBus` singleton."""
    return _DEFAULT_BUS


# Backwards-compat: legacy ``global_bus`` symbol used by downstream games
# (Ochema Circuit, Bullet Strata) and by internal modules (debug_overlay,
# compute.library, compute.hull). Points at the same singleton as
# ``get_default_bus()`` / ``publish`` / ``subscribe`` module-level helpers.
# DO NOT REMOVE without a v1.0 deprecation cycle.
global_bus = _DEFAULT_BUS


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
        # Cooperative multiple-inheritance chain: without this, mixing Observable
        # into an Entity/Asset subclass (e.g. Ochema's VehicleEntity, Bullet
        # Strata's PlayerEntity) short-circuits the MRO and leaves
        # RenderTarget.__init__ unrun — self.layers never gets initialised, so
        # the first add_layer() call in the subclass __init__ raises
        # AttributeError.
        try:
            super().__init__()
        except TypeError:
            # Peer __init__ requires positional args we cannot supply blindly.
            # Standalone Observable(...) usage (super resolves to object) is
            # unaffected by this except; it only guards the rare case of a
            # mixin peer with a mandatory positional signature.
            pass

    def notify(self, **payload) -> "EventPayload":
        """Publish ``self._observable_topic`` on the bus with the given payload.

        Auto-sets ``publisher=self`` if the caller did not supply one — matches
        the Observable contract that games (Bullet Strata's reactive HUD)
        rely on when they filter events via ``evt.publisher is self._scene``.
        """
        payload.setdefault("publisher", self)
        return self._bus.publish(self._observable_topic, **payload)

    def subscribe(self, listener) -> None:
        """Subscribe ``listener`` to this observable's topic."""
        self._bus.subscribe(self._observable_topic, listener)

    def unsubscribe(self, listener) -> None:
        """Drop ``listener`` from this observable's topic."""
        self._bus.unsubscribe(self._observable_topic, listener)
