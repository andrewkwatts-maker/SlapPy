"""Regression tests for ZZ2's backwards-compat shim stack.

Follows up on YY3's post-YY1 walk in ``docs/game_compat_2026_07_07.md``
§ 12.4 which identified four residual failure fingerprints after ZZ1's
Observable kwarg-swallow landed. ZZ2 closes the four items on the game-
compat critical path (Observable auto-publish, ``debug_listeners``,
``EventBus.__slots__`` relaxation, and the ``label``-kwarg shadow
regression from YY1). None of these steps on ZZ1's Observable
kwarg-swallow diff — they are orthogonal fixes to distinct call sites.

1. ``EventPayload.label`` preserves caller-supplied ``label=`` kwarg
   instead of unconditionally clobbering it with the topic name.
   Bullet Strata's ``QualityManager._apply_tier`` fires
   ``publish("Quality.TierChanged", label="low", ...)`` and asserts
   ``evt.label == "low"``. YY1's ``self["label"] = name`` line shadowed
   the caller's kwarg. Now only defaults to the topic name when
   ``label`` was not present in the extras dict.

2. ``EventBus.__slots__`` REMOVED — enables downstream setattr on the
   bus, needed by (a) ``ui.debug_overlay._sync_event_sub`` stashing
   ``bus._debug_overlay_orig_pub``, and (b) Ochema's
   ``TestRaceManagerDeltaPublish`` using
   ``mock.patch.object(bus, 'listener_count', ...)`` to simulate the
   "no subscribers" fast-path.

3. ``event_bus.debug_listeners`` module function — snapshot of
   ``{topic: listener_count}`` for teardown leak-detection. Ochema
   Circuit's ``tests/test_p8_integration.py::TestGhostSystem::
   test_teardown_removes_subscriptions`` imports it.

4. ``Observable.__setattr__`` auto-publish on public attribute set —
   downstream games (Bullet Strata's ``PlayerEntity``, Ochema Circuit's
   ``VehicleEntity`` subclasses) declare ``__no_publish__ = frozenset({...})``
   of hot-tick attrs and rely on Observable auto-publishing
   ``{ClassName}.{attr}`` on every other public attribute assignment.
   Bullet Strata test coverage:
     * ``test_strata_layer_change_fires_event``
     * ``test_current_weapon_change_fires_event``
     * ``test_hot_attrs_do_not_fire_events`` (negative — must NOT publish)

If any of these regress, downstream games break. Do NOT remove without
a v1.0 deprecation cycle. (ZZ2)
"""
from __future__ import annotations

from unittest import mock

import pytest

from pharos_engine.event_bus import (
    EventBus,
    EventPayload,
    Observable,
    debug_listeners,
    get_default_bus,
    global_bus,
    publish,
    subscribe,
    unsubscribe,
)


# ---------------------------------------------------------------------------
# 1. EventPayload label shadow fix
# ---------------------------------------------------------------------------


class TestEventPayloadLabel:
    def test_label_defaults_to_name_when_not_supplied(self):
        evt = EventPayload(name="Foo.Bar")
        assert evt.label == "Foo.Bar"
        assert evt["label"] == "Foo.Bar"

    def test_label_kwarg_preserved_when_supplied(self):
        # Bullet Strata's QualityManager publishes with label="low" and
        # asserts evt.label == "low". YY1 clobbered this — ZZ2 restores.
        evt = EventPayload(name="Quality.TierChanged", label="low")
        assert evt.label == "low"
        assert evt["label"] == "low"
        # Name is still preserved separately.
        assert evt.name == "Quality.TierChanged"

    def test_label_kwarg_via_publish(self):
        # End-to-end: publish() should also preserve label.
        received = []
        h = subscribe(
            "ZZ2.LabelTest",
            lambda e: received.append((e.name, e.label, e.get("extra"))),
        )
        try:
            publish("ZZ2.LabelTest", label="custom_label_value", extra=42)
        finally:
            unsubscribe("ZZ2.LabelTest", h)
        assert received == [("ZZ2.LabelTest", "custom_label_value", 42)]


# ---------------------------------------------------------------------------
# 2. EventBus __slots__ relaxation
# ---------------------------------------------------------------------------


class TestEventBusNoSlots:
    def test_setattr_arbitrary_attribute(self):
        bus = EventBus()
        # debug_overlay stashes original publish here.
        bus._debug_overlay_orig_pub = "sentinel_value"
        assert bus._debug_overlay_orig_pub == "sentinel_value"

    def test_mock_patch_object_on_listener_count(self):
        bus = EventBus()
        # Ochema's TestRaceManagerDeltaPublish uses this pattern to
        # simulate the "no subscribers" fast-path branch.
        with mock.patch.object(bus, "listener_count", return_value=0):
            assert bus.listener_count("anything") == 0
        # Restored after context manager exits.
        assert bus.listener_count("anything") == 0  # (no listeners registered)

    def test_bus_dict_present(self):
        # No __slots__ means __dict__ is available (per test contract).
        bus = EventBus()
        assert hasattr(bus, "__dict__")


# ---------------------------------------------------------------------------
# 3. debug_listeners module function
# ---------------------------------------------------------------------------


class TestDebugListeners:
    def test_debug_listeners_is_importable(self):
        # The failing import site was:
        #   from pharos_engine.event_bus import debug_listeners
        from pharos_engine.event_bus import debug_listeners as dl
        assert callable(dl)

    def test_debug_listeners_returns_dict(self):
        bus = EventBus()
        bus.subscribe("a", lambda e: None)
        bus.subscribe("a", lambda e: None)
        bus.subscribe("b", lambda e: None)
        snap = debug_listeners(bus)
        assert isinstance(snap, dict)
        assert snap.get("a") == 2
        assert snap.get("b") == 1

    def test_debug_listeners_default_bus(self):
        # Called without args, returns snapshot of the module default bus.
        h1 = subscribe("zz2_dl_topic", lambda e: None)
        try:
            snap = debug_listeners()
            assert "zz2_dl_topic" in snap
            assert snap["zz2_dl_topic"] >= 1
        finally:
            unsubscribe("zz2_dl_topic", h1)

    def test_debug_listeners_snapshot_not_live(self):
        bus = EventBus()
        bus.subscribe("live", lambda e: None)
        snap = debug_listeners(bus)
        # Add another subscriber AFTER snapshot — snapshot should be stale.
        bus.subscribe("live", lambda e: None)
        assert snap["live"] == 1  # not 2


# ---------------------------------------------------------------------------
# 4. Observable __setattr__ auto-publish
# ---------------------------------------------------------------------------


class _AutoPubEntity(Observable):
    """Fixture: Observable subclass with a __no_publish__ list."""
    __no_publish__ = frozenset({"velocity", "fire_cooldown"})


class TestObservableAutoPublish:
    def test_public_attr_publishes(self):
        e = _AutoPubEntity()
        received = []
        h = subscribe("_AutoPubEntity.strata_layer", lambda evt: received.append(evt))
        try:
            e.strata_layer = 1
            assert len(received) == 1
            assert received[0].value == 1
            assert received[0].publisher is e
        finally:
            unsubscribe("_AutoPubEntity.strata_layer", h)

    def test_no_publish_attr_skipped(self):
        e = _AutoPubEntity()
        fired = []
        h1 = subscribe("_AutoPubEntity.velocity", lambda evt: fired.append(evt))
        h2 = subscribe("_AutoPubEntity.fire_cooldown", lambda evt: fired.append(evt))
        try:
            e.velocity = [50.0, 0.0]
            e.fire_cooldown = 0.2
            assert fired == []
        finally:
            unsubscribe("_AutoPubEntity.velocity", h1)
            unsubscribe("_AutoPubEntity.fire_cooldown", h2)

    def test_private_attr_skipped(self):
        e = _AutoPubEntity()
        received = []
        h = subscribe("_AutoPubEntity._internal", lambda evt: received.append(evt))
        try:
            e._internal = 42
            assert received == []
        finally:
            unsubscribe("_AutoPubEntity._internal", h)

    def test_idempotent_set_skipped(self):
        # Setting the same value twice should only publish once.
        e = _AutoPubEntity()
        received = []
        h = subscribe("_AutoPubEntity.weapon", lambda evt: received.append(evt))
        try:
            e.weapon = "pistol"
            e.weapon = "pistol"  # idempotent — no republish
            assert len(received) == 1
            e.weapon = "plasma"  # different — republish
            assert len(received) == 2
        finally:
            unsubscribe("_AutoPubEntity.weapon", h)

    def test_setattr_reserved_names_skipped(self):
        # _bus / _observable_topic assignment must NOT trigger publish
        # (they are Observable-internal wiring).
        e = _AutoPubEntity()
        received = []
        h = subscribe("_AutoPubEntity._bus", lambda evt: received.append(evt))
        try:
            e._bus = EventBus()  # bypass Observable's private
            assert received == []
        finally:
            unsubscribe("_AutoPubEntity._bus", h)

    def test_early_setattr_before_bus_init_silent(self):
        # If setattr fires from inside cooperative __init__ before _bus
        # is wired, must not raise. Simulated by using object.__new__.
        e = _AutoPubEntity.__new__(_AutoPubEntity)  # bypass __init__
        received = []
        h = subscribe("_AutoPubEntity.no_bus_yet", lambda evt: received.append(evt))
        try:
            # No _bus attribute yet.
            e.no_bus_yet = 42
            # Should NOT crash; should also NOT publish (no bus).
            assert received == []
            assert e.no_bus_yet == 42
        finally:
            unsubscribe("_AutoPubEntity.no_bus_yet", h)

    def test_publish_carries_old_value(self):
        e = _AutoPubEntity()
        received = []
        h = subscribe(
            "_AutoPubEntity.weapon",
            lambda evt: received.append((evt.old_value, evt.value)),
        )
        try:
            e.weapon = "pistol"
            e.weapon = "plasma"
            assert received == [(None, "pistol"), ("pistol", "plasma")]
        finally:
            unsubscribe("_AutoPubEntity.weapon", h)


# ---------------------------------------------------------------------------
# 5. Anti-regression: ZZ1's Observable kwarg-swallow still works
# ---------------------------------------------------------------------------


class TestZZ1KwargSwallowStillWorks:
    def test_observable_accepts_name_kwarg(self):
        # ZZ1's fix — Observable subclass with peer Asset receives name.
        # Ensure ZZ2's __setattr__ addition doesn't break the kwarg-stash
        # fallback path.
        class Peer:
            def __init__(self, name="unset", **_):
                self.name = name

        class Combo(Observable, Peer):
            pass

        c = Combo(name="hello")
        assert c.name == "hello"

    def test_observable_stashes_unknown_kwargs(self):
        # No peer __init__ — ZZ1 stashes kwargs as attributes.
        # Note: ZZ2's __setattr__ MAY publish these, so we set up before
        # subscribing to avoid interference.
        obs = Observable(custom_field="value_x")
        assert obs.custom_field == "value_x"
