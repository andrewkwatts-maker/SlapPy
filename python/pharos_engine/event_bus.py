from __future__ import annotations
from typing import Callable, Any, Iterator

from pharos_engine._event_bus_validation import (
    validate_event_type,
    validate_event_type_or_none,
    validate_callback,
    validate_bus_or_none,
)


# Backwards-compat (ZZ2, 2026-07): sentinel for "attribute not previously
# set" in Observable.__setattr__ auto-publish. Distinct from ``None`` because
# ``None`` is a valid attribute value (``player.current_target = None``
# should still publish the "cleared" transition).
_MISSING = object()


def _values_equal(a: Any, b: Any) -> bool:
    """Safe idempotency check for Observable auto-publish.

    ``a == b`` on numpy arrays returns an array, not a bool — coerce to
    ``bool`` via ``bool()`` when possible; when it can't (multi-element
    arrays), treat as "not equal" so we always publish. Also handles the
    common list/tuple mutable-value case (``[50.0, 0.0] == [50.0, 0.0]``
    is True) without special-casing.
    """
    if a is b:
        return True
    try:
        result = a == b
        if isinstance(result, bool):
            return result
        # numpy array — treat any array-valued comparison as "not equal"
        # (games mutate arrays in-place; auto-publish should fire).
        return False
    except Exception:
        return False


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
        # Backwards-compat (ZZ2, 2026-07): ``label`` defaults to ``name``
        # (YY1-spec alias) BUT only when the publisher did not pass an
        # explicit ``label=`` kwarg. Bullet Strata's QualityManager fires
        # ``publish("Quality.TierChanged", label="low", ...)`` and asserts
        # ``evt.label == "low"``. Prior YY1 unconditionally clobbered
        # ``self["label"] = name``, shadowing the caller's kwarg. Preserve
        # the caller-supplied value when present; only fall back to the
        # topic name when ``label`` was not explicitly provided.
        # DO NOT REMOVE without a v1.0 deprecation cycle.
        if "label" not in payload_dict:
            self["label"] = name
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
# ``pharos_engine.event_bus``. Kept as an alias for the new ``EventPayload``
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

    # NOTE: __slots__ intentionally REMOVED (was ("_listeners",)) — Backwards-
    # compat (ZZ2, 2026-07). Two downstream contracts break under __slots__:
    #   1. ``pharos_editor.ui.debug_overlay._sync_event_sub`` stashes the
    #      original ``publish`` callable on the bus as
    #      ``bus._debug_overlay_orig_pub`` before wrapping ``bus.publish``
    #      for the F2 event-stream overlay. Slotted classes reject the
    #      setattr with ``AttributeError: no __dict__``. Ochema Circuit's
    #      test_q5_game_flow.TestDebugOverlayWiring.test_f2_toggles_event_stream
    #      exercises this path.
    #   2. Ochema's TestRaceManagerDeltaPublish uses
    #      ``mock.patch.object(bus, "listener_count", return_value=0)`` to
    #      simulate the "no subscribers" fast-path. mock.patch.object sets
    #      an attribute on the target — slotted classes reject the assignment
    #      with ``AttributeError: read-only``.
    # Restoring slots requires exhaustively enumerating every downstream
    # setattr site — punt to v1.0.
    # DO NOT re-add __slots__ without a v1.0 deprecation cycle.

    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable]] = {}

    def subscribe(self, event_type: str, callback: Callable[[dict], None]) -> Callable:
        """Register ``callback`` to fire on ``event_type``.

        Returns
        -------
        Callable
            The ``callback`` itself, usable as an opaque "handle" for
            :meth:`unsubscribe`. Bullet Strata's ``ArenaInfoHUD`` (per
            ``project_bullet_strata.md``) stashes the return value in
            ``self._sub_handles`` and iterates ``unsubscribe(h)`` during
            teardown. Ochema Circuit's Sprint P1 tests do the same
            (``h = subscribe(...)``; ``unsubscribe(h)``). Returning the
            callback keeps the ``h = subscribe(...); unsubscribe(h)``
            pattern working without callers needing to know that the
            handle IS the callback.
            DO NOT change to ``-> None`` without a v1.0 deprecation cycle.

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
        return callback

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
        * ``unsubscribe(handle)`` where ``handle`` is a callable — treated
          identically to ``unsubscribe(None, handle)``: drop ``handle``
          from EVERY topic. Enables the ``h = subscribe(...)``;
          ``unsubscribe(h)`` handle pattern used by Bullet Strata's
          ``ArenaInfoHUD.teardown`` (see ``project_bullet_strata.md``)
          and Ochema Circuit's Sprint P1 tests. Also matches the
          ``pharos_editor.ui.widgets.Widget.unbind_all`` pattern which
          calls ``unsubscribe(h)`` for every handle in
          ``self._event_handles``.
        * ``unsubscribe()`` or ``unsubscribe(None, None)`` — no-op.

        DO NOT tighten this signature without a v1.0 deprecation cycle.

        Raises
        ------
        TypeError
            If ``event_type`` is neither ``None``, a ``str``, nor callable.
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

        # Case 2b (handle-arity form): unsubscribe(callable) — the caller
        # passed the value returned by ``subscribe`` as a positional
        # "handle". Since ``subscribe`` now returns the callback itself,
        # a callable in the ``event_type`` slot is unambiguously that
        # handle — drop it from every topic. This keeps the
        # ``h = subscribe(...); unsubscribe(h)`` idiom working without
        # requiring callers to remember it's a two-arg call.
        # Guard: str is also callable via ``str()`` — but we already
        # dispatched string topics through the ``validate_event_type``
        # path below, so callable() here can only mean "not a str, not
        # None, but callable" ⇒ handle-arity.
        if callback is None and not isinstance(event_type, str) and callable(event_type):
            handle = event_type
            for topic in list(self._listeners.keys()):
                self._listeners[topic] = [
                    l for l in self._listeners[topic] if l is not handle
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
        # Backwards-compat (AAA1, 2026-07): hierarchical fan-out.
        # Downstream games publish topic-key strings with either a ``|`` or
        # ``.`` delimiter to encode instance / attribute qualifiers:
        #
        #   * ``"Race.CountdownTick|3"``  fires listeners of
        #     ``"Race.CountdownTick"`` too (integer sub-topic — see
        #     Ochema Circuit's TestCountdownTick3 suite).
        #   * ``"Results.RowReady|0"``    fires listeners of
        #     ``"Results.RowReady"`` too (per-rank fan-out).
        #   * ``"VehicleEntity.speed"``   fires listeners of
        #     ``"VehicleEntity"`` too (Observable class-level fan-out — see
        #     Ochema Circuit's test_speed_publish_hierarchical_fanout).
        #
        # Split at BOTH delimiters, in that order (``|`` for enum-like
        # sub-topics, ``.`` for attribute qualifiers). Each parent gets ONE
        # additional dispatch. We stop at the shortest non-empty prefix so
        # the fan-out chain terminates deterministically.
        # DO NOT REMOVE without a v1.0 deprecation cycle.
        for delim in ("|", "."):
            idx = event_type.rfind(delim)
            if idx <= 0:
                continue
            parent = event_type[:idx]
            parent_listeners = self._listeners.get(parent)
            if not parent_listeners:
                continue
            for cb in list(parent_listeners):
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
# (pharos_engine.trigger, pharos_engine.deform_zones) imports
# ``from pharos_engine.event_bus import publish, subscribe``; we keep that
# shape working by exposing a process-wide ``_DEFAULT_BUS`` singleton.
_DEFAULT_BUS = EventBus()


def publish(event_type: str, **payload) -> "EventPayload":
    """Publish to the module-level default :class:`EventBus`.

    Returns the :class:`EventPayload` handed to subscribers so callers
    that assign ``event = publish(...)`` can inspect it (dual attribute
    and dict access — see :class:`EventPayload`).
    """
    return _DEFAULT_BUS.publish(event_type, **payload)


def subscribe(event_type: str, listener) -> Callable:
    """Subscribe on the module-level default :class:`EventBus`.

    Returns the callback so the ``h = subscribe(...); unsubscribe(h)``
    handle idiom works — Bullet Strata's ``ArenaInfoHUD.teardown``
    and Ochema Circuit's Sprint P1 tests rely on this shape.
    """
    return _DEFAULT_BUS.subscribe(event_type, listener)


def unsubscribe(event_type=None, listener=None) -> None:
    """Unsubscribe from the module-level default :class:`EventBus`.

    Backwards-compat: mirrors :meth:`EventBus.unsubscribe` — supports the
    legacy 1-arg ``unsubscribe("topic")`` shape AND the teardown pattern
    ``unsubscribe(None, listener)`` which drops ``listener`` from every
    topic AND the handle-arity form ``unsubscribe(h)`` where ``h`` is a
    callable returned by :func:`subscribe`. ``unsubscribe()`` is a no-op.
    """
    _DEFAULT_BUS.unsubscribe(event_type, listener)


def get_default_bus() -> EventBus:
    """Return the module-level default :class:`EventBus` singleton."""
    return _DEFAULT_BUS


# Backwards-compat (ZZ2, 2026-07): Ochema Circuit's Sprint 8 integration
# suite (tests/test_p8_integration.py::TestGhostSystem::test_teardown_removes_subscriptions)
# imports ``debug_listeners`` from ``pharos_engine.event_bus`` and uses it
# to sum the listener count across every topic on the default bus. It's
# a debug/telemetry helper — returns a snapshot mapping ``{topic: count}``.
# Games use it to write listener-leak sentinels around teardown paths
# (``sum(debug_listeners().values())`` before/after teardown). DO NOT
# REMOVE without a v1.0 deprecation cycle.
def debug_listeners(bus: "EventBus | None" = None) -> dict[str, int]:
    """Return ``{topic: listener_count}`` snapshot for a bus (default: global).

    Designed for teardown leak-detection assertions. Snapshot is a plain
    dict (not a live view) — safe to compare before/after teardown to
    detect listeners that outlive their entity.
    """
    target = bus if bus is not None else _DEFAULT_BUS
    return {topic: len(listeners) for topic, listeners in target._listeners.items()}


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

    Backwards-compat kwarg swallow (ZZ1, 2026-07):
    Downstream games (Ochema Circuit's ``VehicleEntity(Observable, Asset)``,
    Bullet Strata's ``PlayerEntity(Observable, Asset)``) call
    ``super().__init__(name=..., position=..., size=..., spline=..., ...)``
    from subclass ``__init__`` bodies. Prior signature only accepted
    ``bus`` and ``topic``, so ``Observable`` sat in the MRO and rejected
    every game kwarg with ``TypeError: got an unexpected keyword argument
    'name'``. We now accept ``bus``/``topic`` as the two reserved kwargs
    AND forward every other kwarg down the cooperative MRO chain
    (Observable -> Asset -> RenderTarget -> Entity -> object) so downstream
    peers still receive their expected ``name``/``position``/``size``/
    ``spline``/etc. arguments. If the peer chain rejects a kwarg we then
    stash the remaining kwargs as instance attributes so ``self.name`` etc.
    still resolve for downstream getattr users. DO NOT tighten this
    signature without a v1.0 deprecation cycle.
    """

    # NOTE: __slots__ intentionally REMOVED (was ("_bus", "_observable_topic"))
    # so the kwarg-swallow fallback can setattr() arbitrary game-supplied
    # attributes on ``self``. Slots would raise AttributeError for any kwarg
    # not pre-declared, defeating the shim. Restoring slots requires
    # exhaustively enumerating every game kwarg — punt to v1.0.

    def __init__(
        self,
        bus: "EventBus | None" = None,
        topic: str = "changed",
        **kwargs: Any,
    ) -> None:
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
        #
        # Strategy: try to forward every non-Observable kwarg down the MRO
        # first (so Asset gets its name/position/size), and fall back to
        # attribute-stashing if the peer signature rejects them.
        try:
            super().__init__(**kwargs)
        except TypeError:
            # Peer __init__ rejected one or more kwargs (or requires
            # positional args we cannot supply blindly). Try a bare
            # super().__init__() so at least the MRO chain runs, then
            # stash every kwarg on self so downstream attribute access
            # (``self.name``, ``self.id``, ``self.tags``) still resolves.
            try:
                super().__init__()
            except TypeError:
                pass
            for k, v in kwargs.items():
                try:
                    setattr(self, k, v)
                except AttributeError:
                    # A __slots__-restricted subclass may reject a stray
                    # kwarg. Silently ignore — the alternative is breaking
                    # every game construction site.
                    pass

    # Backwards-compat (ZZ2, 2026-07): auto-publish on public attribute set.
    # Downstream games (Bullet Strata's PlayerEntity, Ochema Circuit's
    # VehicleEntity subclasses) declare ``__no_publish__ = frozenset({...})``
    # of hot-tick attrs that must NOT spam the global bus every frame, then
    # rely on Observable to auto-publish ``{ClassName}.{attr}`` on the
    # global bus for every OTHER public attribute assignment. Test coverage:
    #   * Bullet Strata `tests/test_features.py::TestPlayerEntityObservable`
    #     - test_strata_layer_change_fires_event
    #     - test_current_weapon_change_fires_event
    #     - test_hot_attrs_do_not_fire_events (must NOT publish for hot attrs)
    # Rules (must all pass for a publish to fire):
    #   1. Not a dunder or private attr (``name.startswith("_")`` skips).
    #   2. Not in the subclass's ``__no_publish__`` frozenset.
    #   3. Not one of the Observable-reserved names (``_bus``, ``_observable_topic``).
    #   4. Bus must be initialised (``_bus`` on self) — early setattr from
    #      ``__init__`` before ``super().__init__`` runs is silently skipped.
    #   5. The value must have actually changed (avoids re-publish on no-op
    #      writes; matches downstream ``player.strata_layer = 1`` idempotency
    #      expectations across teardown fixtures).
    # Topic name is ``{type(self).__name__}.{attr}`` — matches the string
    # that downstream subscribers pass to ``subscribe("PlayerEntity.strata_layer",
    # ...)``. Event payload carries ``publisher=self``, ``value=new_value``,
    # ``old_value=previous_value``.
    # DO NOT REMOVE without a v1.0 deprecation cycle.
    _OBSERVABLE_RESERVED = frozenset(("_bus", "_observable_topic"))

    def __setattr__(self, key: str, value: Any) -> None:
        # Fast paths: skip publishing for private/dunder attrs, reserved
        # Observable-internal fields, and pre-init state (before _bus exists).
        if key.startswith("_") or key in Observable._OBSERVABLE_RESERVED:
            object.__setattr__(self, key, value)
            return
        no_pub = getattr(type(self), "__no_publish__", frozenset())
        if key in no_pub:
            object.__setattr__(self, key, value)
            return
        # Only publish if bus wiring has finished. During cooperative
        # __init__ chains the peer Asset.__init__ may setattr before
        # Observable.__init__ ran — silently skip those.
        bus = self.__dict__.get("_bus", None)
        if bus is None:
            object.__setattr__(self, key, value)
            return
        old_value = getattr(self, key, _MISSING)
        object.__setattr__(self, key, value)
        # Idempotency: don't republish for no-op writes (fixes teardown
        # fixture double-set patterns and matches downstream expectations).
        if old_value is not _MISSING and _values_equal(old_value, value):
            return
        topic = f"{type(self).__name__}.{key}"
        # Publish to BOTH the observable's private bus (if it differs from
        # the global default) AND the module-level default bus. Downstream
        # games subscribe via the module-level ``subscribe(...)`` helper,
        # which routes to ``_DEFAULT_BUS`` — so the auto-publish MUST reach
        # the global bus to be observable by downstream test suites.
        try:
            if bus is not _DEFAULT_BUS:
                bus.publish(topic, publisher=self, value=value, old_value=old_value if old_value is not _MISSING else None)
            _DEFAULT_BUS.publish(topic, publisher=self, value=value, old_value=old_value if old_value is not _MISSING else None)
        except Exception:
            # Never let a downstream subscriber exception break setattr.
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
