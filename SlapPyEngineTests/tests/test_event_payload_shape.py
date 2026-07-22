"""Regression tests for the dual-shape :class:`EventPayload` return object.

Downstream games (Ochema Circuit, Bullet Strata — see
docs/ui_pattern_audit_2026_06_03.md) access published events as objects:

    def _on_speed(self, evt):
        if evt.publisher is not self._vehicle:
            return
        self._speed = float(evt.value)

Prior to YY1 (Restore EventPayload dual-shape returns) ``EventBus.publish``
handed subscribers a plain ``dict``, so ``evt.publisher`` raised
``AttributeError: 'dict' object has no attribute 'publisher'`` at 84
call-sites across the two games.

These tests lock in:

1. Object-attribute access (``evt.publisher`` / ``evt.label`` / ``evt.data``
   / ``evt.timestamp`` / ad-hoc kwargs promoted to attributes).
2. Dict-item access (``evt["publisher"]``, ``evt.get("missing", default)``,
   ``"key" in evt``, ``evt.keys()``).
3. Subscribers receive :class:`EventPayload` instances (not raw dict).
4. Ochema-style callback ``evt.publisher.name`` doesn't crash when the
   publisher is a namespaced object.
5. ``bus.publish("topic")`` returns a payload even with no kwargs.
6. Backwards-compat with any internal caller that still does dict-style
   lookups (``p.get("v", 0)``).

DO NOT remove without a v1.0 deprecation cycle. (YY1)
"""
from __future__ import annotations

from types import SimpleNamespace

from pharos_engine.event_bus import (
    EventBus,
    EventPayload,
    EventDetails,
    global_bus,
    publish,
    subscribe,
    unsubscribe,
)


# -----------------------------------------------------------------------
# 1. Object-attribute access — the shape games depend on
# -----------------------------------------------------------------------

def test_publish_returns_event_payload_instance():
    """``publish`` must return an :class:`EventPayload`, not a plain dict."""
    bus = EventBus()
    evt = bus.publish("topic", value=7)
    assert isinstance(evt, EventPayload)


def test_object_access_label_and_name():
    """``evt.label`` and ``evt.name`` both resolve to the event type string."""
    bus = EventBus()
    evt = bus.publish("Race.LapComplete", lap=3)
    assert evt.label == "Race.LapComplete"
    assert evt.name == "Race.LapComplete"


def test_object_access_publisher_and_data():
    """``evt.publisher`` and ``evt.data`` mirror the kwargs passed to publish."""
    bus = EventBus()
    car = SimpleNamespace(name="vehicle_1", speed=90.0)
    evt = bus.publish("Vehicle.SpeedChanged", publisher=car, value=90.0)
    assert evt.publisher is car
    # ``data`` is the raw kwargs dict (excluding the special ``publisher`` key).
    assert evt.data == {"value": 90.0}


def test_object_access_timestamp_is_float():
    """``evt.timestamp`` is populated with a real wall-clock float."""
    bus = EventBus()
    evt = bus.publish("t")
    assert isinstance(evt.timestamp, float)
    assert evt.timestamp > 0.0


def test_object_access_promotes_arbitrary_kwargs():
    """Ad-hoc kwargs promote to attributes — Ochema uses ``evt.value``, ``evt.lap``."""
    bus = EventBus()
    evt = bus.publish("Race.LapComplete", lap=4, lap_time=71.2, positions=[1, 2, 3])
    assert evt.lap == 4
    assert evt.lap_time == 71.2
    assert evt.positions == [1, 2, 3]


# -----------------------------------------------------------------------
# 2. Dict-item access — the shape internal engine code still uses
# -----------------------------------------------------------------------

def test_dict_access_publisher():
    """``evt["publisher"]`` works alongside ``evt.publisher``."""
    bus = EventBus()
    src = SimpleNamespace()
    evt = bus.publish("topic", publisher=src, value=1)
    assert evt["publisher"] is src
    assert evt["value"] == 1


def test_dict_get_with_default():
    """``evt.get("missing", default)`` returns the default when the key is absent."""
    bus = EventBus()
    evt = bus.publish("topic", value=7)
    assert evt.get("missing", -1) == -1
    assert evt.get("value", -1) == 7


def test_dict_contains_and_keys():
    """``"k" in evt`` and ``evt.keys()`` reflect both reserved and ad-hoc keys."""
    bus = EventBus()
    evt = bus.publish("topic", extra="hello")
    assert "publisher" in evt
    assert "label" in evt
    assert "extra" in evt
    keys = set(evt.keys())
    assert {"label", "publisher", "data", "timestamp", "name", "extra"} <= keys


# -----------------------------------------------------------------------
# 3. Subscribers receive EventPayload (not raw dict)
# -----------------------------------------------------------------------

def test_subscriber_receives_event_payload():
    """Callbacks fire with an :class:`EventPayload`, not a plain dict."""
    bus = EventBus()
    seen: list = []
    bus.subscribe("topic", lambda evt: seen.append(evt))
    bus.publish("topic", value=42)
    assert len(seen) == 1
    assert isinstance(seen[0], EventPayload)
    # Both shapes work inside the callback.
    assert seen[0].value == 42
    assert seen[0]["value"] == 42


def test_subscriber_backcompat_dict_get():
    """Legacy dict-style ``p.get("v", 0)`` still works inside subscribers."""
    bus = EventBus()
    hits: list[int] = []
    bus.subscribe("topic", lambda p: hits.append(p.get("v", 0)))
    bus.publish("topic", v=13)
    bus.publish("topic")  # no v — default kicks in
    assert hits == [13, 0]


# -----------------------------------------------------------------------
# 4. Ochema-style callback with namespaced publisher
# -----------------------------------------------------------------------

def test_ochema_style_publisher_name_access():
    """``evt.publisher.name`` (nested attr) resolves without AttributeError."""
    bus = EventBus()
    vehicle = SimpleNamespace(name="player_car_01", speed=0.0)
    captured: dict = {}

    def _on_lap(evt):
        # This is the exact pattern used in Ochema's audio_system.py L211.
        captured["publisher_name"] = evt.publisher.name
        captured["lap"] = evt.lap

    bus.subscribe("Race.LapComplete", _on_lap)
    bus.publish("Race.LapComplete", publisher=vehicle, lap=2)
    assert captured == {"publisher_name": "player_car_01", "lap": 2}


def test_ochema_style_nested_payload_dict():
    """``evt.payload.get("amount", default)`` — the pattern in hazard_system.py."""
    bus = EventBus()
    seen: dict = {}
    bus.subscribe(
        "hazard:hit",
        lambda evt: seen.update(
            amount=evt.payload.get("amount", 1.0),
            duration=evt.payload.get("duration", 0.5),
        ),
    )
    bus.publish("hazard:hit", publisher=None, amount=2.5)
    assert seen == {"amount": 2.5, "duration": 0.5}


# -----------------------------------------------------------------------
# 5. Empty publish still returns a payload
# -----------------------------------------------------------------------

def test_publish_with_no_kwargs_returns_payload():
    """``bus.publish("topic")`` returns a valid :class:`EventPayload`."""
    bus = EventBus()
    evt = bus.publish("topic")
    assert isinstance(evt, EventPayload)
    assert evt.label == "topic"
    assert evt.name == "topic"
    assert evt.publisher is None
    assert evt.data == {}
    assert evt.get("missing", "sentinel") == "sentinel"


# -----------------------------------------------------------------------
# 6. Backwards-compat aliases and module-level helpers
# -----------------------------------------------------------------------

def test_event_details_alias_now_dual_shape():
    """``EventDetails`` (legacy alias) resolves to :class:`EventPayload`."""
    assert EventDetails is EventPayload


def test_module_level_publish_returns_payload():
    """The module proxy ``publish(...)`` returns a payload just like the method."""
    hits: list = []
    subscribe("_yy1:test", hits.append)
    try:
        evt = publish("_yy1:test", value=99)
        assert isinstance(evt, EventPayload)
        assert evt.value == 99
        assert hits and isinstance(hits[0], EventPayload)
    finally:
        unsubscribe("_yy1:test")


def test_getattr_missing_raises_attribute_error():
    """Missing attribute lookup raises ``AttributeError`` (not ``KeyError``).

    This keeps ``hasattr(evt, "x")`` and
    ``getattr(evt, "x", default)`` working — a pattern Ochema's
    clutter_system.py uses (``getattr(evt, "tier", "high")``).
    """
    bus = EventBus()
    evt = bus.publish("topic", value=1)
    assert hasattr(evt, "value")
    assert not hasattr(evt, "nonexistent_field")
    assert getattr(evt, "nonexistent_field", "fallback") == "fallback"


def test_setattr_mutation_writes_dict_too():
    """``evt.progress = 0.65`` mutation is visible via both attr and item access.

    Ochema's ``test_q8_garage_polish.py`` mutates the payload after firing:
    ``evt.progress = 0.65``. Both shapes must observe the write.
    """
    bus = EventBus()
    evt = bus.publish("garage:step")
    evt.progress = 0.65
    assert evt.progress == 0.65
    assert evt["progress"] == 0.65
