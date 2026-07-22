"""Backwards-compat regression tests: Bullet Strata residual sweep (AAA6).

Pins the ``h = subscribe(topic, cb); ... unsubscribe(h)`` handle idiom
that Bullet Strata's ``entities/hud.py::ArenaInfoHUD.teardown`` (per
``project_bullet_strata.md``) relies on to release its Arena.* event
subscriptions on scene tear-down. Prior to AAA6, module-level
``subscribe`` returned ``None`` and ``unsubscribe(None)`` was a no-op —
so ``for h in self._sub_handles: unsubscribe(h)`` silently leaked every
listener, failing Bullet Strata's
``TestArenaInfoHUDReactive.test_teardown_unsubscribes_arena_events``.

DO NOT REMOVE without a v1.0 deprecation cycle — this same pattern is
also used by ``pharos_engine.ui.widgets.Widget.bind_event/unbind_all``
and by Ochema Circuit's Sprint P1 observable tests.
"""
from __future__ import annotations


def test_subscribe_returns_callback_as_handle_module_level():
    """Module-level ``subscribe`` returns the callback so it can be used as a handle."""
    from pharos_engine.event_bus import subscribe, unsubscribe

    def cb(evt):
        pass

    h = subscribe("Test.AAA6.Handle.Module", cb)
    try:
        assert h is cb, "subscribe should return the callback as its opaque handle"
    finally:
        unsubscribe(h)


def test_subscribe_returns_callback_as_handle_bus_method():
    """``EventBus.subscribe`` returns the callback so it can be used as a handle."""
    from pharos_engine.event_bus import EventBus

    bus = EventBus()

    def cb(evt):
        pass

    h = bus.subscribe("Test.AAA6.Handle.Bus", cb)
    assert h is cb, "EventBus.subscribe should return the callback"


def test_unsubscribe_handle_arity_module_level():
    """``unsubscribe(h)`` where h is a callable drops it from every topic."""
    from pharos_engine.event_bus import subscribe, unsubscribe, global_bus

    def cb(evt):
        pass

    h1 = subscribe("Test.AAA6.HandleUnsub.A", cb)
    h2 = subscribe("Test.AAA6.HandleUnsub.B", cb)
    assert h1 is cb and h2 is cb
    assert global_bus.listener_count("Test.AAA6.HandleUnsub.A") == 1
    assert global_bus.listener_count("Test.AAA6.HandleUnsub.B") == 1

    # Handle-arity form — should drop cb from BOTH topics.
    unsubscribe(h1)

    assert global_bus.listener_count("Test.AAA6.HandleUnsub.A") == 0
    assert global_bus.listener_count("Test.AAA6.HandleUnsub.B") == 0


def test_unsubscribe_handle_arity_bus_method():
    """``EventBus.unsubscribe(h)`` where h is a callable drops it from every topic."""
    from pharos_engine.event_bus import EventBus

    bus = EventBus()

    def cb(evt):
        pass

    h = bus.subscribe("Test.AAA6.BusHandle.A", cb)
    bus.subscribe("Test.AAA6.BusHandle.B", cb)
    assert bus.listener_count("Test.AAA6.BusHandle.A") == 1
    assert bus.listener_count("Test.AAA6.BusHandle.B") == 1

    bus.unsubscribe(h)

    assert bus.listener_count("Test.AAA6.BusHandle.A") == 0
    assert bus.listener_count("Test.AAA6.BusHandle.B") == 0


def test_hud_teardown_pattern_end_to_end():
    """Replay the exact Bullet Strata ArenaInfoHUD teardown pattern.

    From ``entities/hud.py``::

        self._sub_handles = [
            subscribe("Arena.Enemy.Killed", self._on_enemy_killed),
            subscribe("Arena.Wave.Started", self._on_wave_started),
            ...
        ]

    Then teardown::

        for h in self._sub_handles:
            unsubscribe(h)
    """
    from pharos_engine.event_bus import subscribe, unsubscribe, global_bus

    def killed(evt):
        pass

    def wave_started(evt):
        pass

    before = global_bus.listener_count("Arena.AAA6.Killed")
    handles = [
        subscribe("Arena.AAA6.Killed", killed),
        subscribe("Arena.AAA6.WaveStarted", wave_started),
    ]
    assert global_bus.listener_count("Arena.AAA6.Killed") == before + 1

    for h in handles:
        unsubscribe(h)

    after = global_bus.listener_count("Arena.AAA6.Killed")
    assert after == before, "teardown() must unsubscribe every stashed handle"


def test_legacy_unsubscribe_shapes_still_work():
    """The AAA6 shim must NOT break the pre-existing unsubscribe forms."""
    from pharos_engine.event_bus import EventBus

    bus = EventBus()

    def a(evt):
        pass

    def b(evt):
        pass

    # Shape 1: unsubscribe(topic, listener) — drops specific listener.
    bus.subscribe("Test.AAA6.Legacy.Topic1", a)
    bus.subscribe("Test.AAA6.Legacy.Topic1", b)
    bus.unsubscribe("Test.AAA6.Legacy.Topic1", a)
    assert bus.listener_count("Test.AAA6.Legacy.Topic1") == 1

    # Shape 2: unsubscribe(topic) — drops ALL listeners for topic.
    bus.subscribe("Test.AAA6.Legacy.Topic2", a)
    bus.subscribe("Test.AAA6.Legacy.Topic2", b)
    bus.unsubscribe("Test.AAA6.Legacy.Topic2")
    assert bus.listener_count("Test.AAA6.Legacy.Topic2") == 0

    # Shape 3: unsubscribe(None, listener) — drops listener across topics.
    bus.subscribe("Test.AAA6.Legacy.Topic3a", a)
    bus.subscribe("Test.AAA6.Legacy.Topic3b", a)
    bus.unsubscribe(None, a)
    assert bus.listener_count("Test.AAA6.Legacy.Topic3a") == 0
    assert bus.listener_count("Test.AAA6.Legacy.Topic3b") == 0

    # Shape 4: unsubscribe() — no-op, no crash.
    bus.unsubscribe()
    bus.unsubscribe(None, None)
