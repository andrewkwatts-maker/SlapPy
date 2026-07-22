"""Negative-path tests for :class:`EventBus` public-boundary validation
(hardening round 4).

EventBus has no dedicated positive-path test file; the round-trip
publish/subscribe contract is exercised end-to-end by other test files.
This file only documents the rejection cases.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "python"))

from pharos_engine.event_bus import EventBus, Observable  # noqa: E402


# ---------------------------------------------------------------------------
# subscribe — event_type / callback
# ---------------------------------------------------------------------------

def test_subscribe_rejects_empty_event_type():
    bus = EventBus()
    with pytest.raises(ValueError, match="event_type must be non-empty"):
        bus.subscribe("", lambda payload: None)


def test_subscribe_rejects_bytes_event_type():
    bus = EventBus()
    with pytest.raises(TypeError, match="event_type must be a str"):
        bus.subscribe(b"entity:spawn", lambda payload: None)


def test_subscribe_rejects_none_event_type():
    bus = EventBus()
    with pytest.raises(TypeError, match="event_type must be a str"):
        bus.subscribe(None, lambda payload: None)


def test_subscribe_rejects_non_callable():
    bus = EventBus()
    with pytest.raises(TypeError, match="callback must be callable"):
        bus.subscribe("entity:spawn", "not_a_function")


def test_subscribe_rejects_int_callback():
    bus = EventBus()
    with pytest.raises(TypeError, match="callback must be callable"):
        bus.subscribe("entity:spawn", 42)


# ---------------------------------------------------------------------------
# publish — event_type
# ---------------------------------------------------------------------------

def test_publish_rejects_empty_event_type():
    # Empty publish() would fan out to subscribers of "" — almost certainly
    # never intended.
    bus = EventBus()
    with pytest.raises(ValueError, match="event_type must be non-empty"):
        bus.publish("", value=1)


def test_publish_rejects_bytes_event_type():
    bus = EventBus()
    with pytest.raises(TypeError, match="event_type must be a str"):
        bus.publish(b"entity:spawn")


def test_publish_rejects_int_event_type():
    bus = EventBus()
    with pytest.raises(TypeError, match="event_type must be a str"):
        bus.publish(42)


# ---------------------------------------------------------------------------
# once / on / unsubscribe — event_type & callback
# ---------------------------------------------------------------------------

def test_once_rejects_empty_event_type():
    bus = EventBus()
    with pytest.raises(ValueError, match="event_type must be non-empty"):
        bus.once("", lambda payload: None)


def test_once_rejects_non_callable():
    bus = EventBus()
    with pytest.raises(TypeError, match="callback must be callable"):
        bus.once("intro:finished", None)


def test_on_decorator_rejects_empty_event_type():
    bus = EventBus()
    with pytest.raises(ValueError, match="event_type must be non-empty"):
        bus.on("")


def test_unsubscribe_rejects_bytes_event_type():
    bus = EventBus()
    with pytest.raises(TypeError, match="event_type must be a str"):
        bus.unsubscribe(b"entity:spawn", lambda payload: None)


# ---------------------------------------------------------------------------
# clear — event_type (round 9 extension)
# ---------------------------------------------------------------------------

def test_clear_rejects_empty_event_type():
    # Empty would map to the sentinel bucket that publish() also refuses
    # — refuse here so the typo surfaces.
    bus = EventBus()
    with pytest.raises(ValueError, match="event_type must be non-empty"):
        bus.clear("")


def test_clear_rejects_int_event_type():
    # Silently no-op'd before via dict.pop(int, None).
    bus = EventBus()
    with pytest.raises(TypeError, match="event_type must be a str"):
        bus.clear(42)


def test_clear_rejects_bytes_event_type():
    bus = EventBus()
    with pytest.raises(TypeError, match="event_type must be a str"):
        bus.clear(b"entity:spawn")


def test_clear_none_still_drops_all_listeners():
    # None remains the sentinel for "clear all".
    bus = EventBus()
    bus.subscribe("a", lambda p: None)
    bus.subscribe("b", lambda p: None)
    bus.clear(None)
    assert bus.listener_count("a") == 0
    assert bus.listener_count("b") == 0


# ---------------------------------------------------------------------------
# listener_count — event_type (round 9 extension)
# ---------------------------------------------------------------------------

def test_listener_count_rejects_empty_event_type():
    bus = EventBus()
    with pytest.raises(ValueError, match="event_type must be non-empty"):
        bus.listener_count("")


def test_listener_count_rejects_int_event_type():
    bus = EventBus()
    with pytest.raises(TypeError, match="event_type must be a str"):
        bus.listener_count(42)


def test_listener_count_rejects_none_event_type():
    bus = EventBus()
    with pytest.raises(TypeError, match="event_type must be a str"):
        bus.listener_count(None)


# ---------------------------------------------------------------------------
# Observable.__init__ — bus / topic (round 9 extension)
# ---------------------------------------------------------------------------

class _FakeBus:
    """Duck-types a publish/subscribe interface but isn't an EventBus."""

    def publish(self, *a, **kw):
        pass

    def subscribe(self, *a, **kw):
        pass


def test_observable_rejects_fake_bus():
    # A duck-typed fake bus would silently route events into the void.
    with pytest.raises(TypeError, match="bus must be an EventBus or None"):
        Observable(bus=_FakeBus())


def test_observable_rejects_string_bus():
    with pytest.raises(TypeError, match="bus must be an EventBus or None"):
        Observable(bus="not_a_bus")


def test_observable_rejects_int_bus():
    with pytest.raises(TypeError, match="bus must be an EventBus or None"):
        Observable(bus=0)


def test_observable_rejects_empty_topic():
    bus = EventBus()
    with pytest.raises(ValueError, match="topic must be non-empty"):
        Observable(bus=bus, topic="")


def test_observable_rejects_bytes_topic():
    bus = EventBus()
    with pytest.raises(TypeError, match="topic must be a str"):
        Observable(bus=bus, topic=b"changed")


def test_observable_rejects_int_topic():
    bus = EventBus()
    with pytest.raises(TypeError, match="topic must be a str"):
        Observable(bus=bus, topic=42)


def test_observable_default_construction_still_works():
    # None bus + default "changed" topic must round-trip.
    # Payload is now an ``EventPayload`` (dual attr/dict shape — YY1); check
    # via item lookup + attribute lookup rather than strict dict equality
    # so the reserved keys (label/publisher/data/timestamp) don't confuse
    # the assertion.
    obs = Observable()
    captured = []
    obs.subscribe(lambda payload: captured.append(payload))
    obs.notify(value=1)
    assert len(captured) == 1
    assert captured[0]["value"] == 1
    assert captured[0].value == 1
    assert captured[0].publisher is obs  # notify() auto-sets publisher=self


# ---------------------------------------------------------------------------
# Positive sanity — round-trip still works after hardening
# ---------------------------------------------------------------------------

def test_subscribe_publish_round_trip_still_works():
    # Payload is now an ``EventPayload`` (dual attr/dict shape — YY1); check
    # each kwarg individually so the reserved keys don't collide.
    bus = EventBus()
    captured = []
    bus.subscribe("entity:spawn", lambda payload: captured.append(payload))
    bus.publish("entity:spawn", entity_id=7, position=(1, 2))
    assert len(captured) == 1
    assert captured[0]["entity_id"] == 7
    assert captured[0]["position"] == (1, 2)
    assert captured[0].entity_id == 7
    assert captured[0].position == (1, 2)


def test_listener_count_works_after_subscribe():
    bus = EventBus()
    bus.subscribe("scene:loaded", lambda p: None)
    bus.subscribe("scene:loaded", lambda p: None)
    assert bus.listener_count("scene:loaded") == 2
    assert bus.listener_count("scene:unloaded") == 0
