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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from slappyengine.event_bus import EventBus  # noqa: E402


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
# Positive sanity — round-trip still works after hardening
# ---------------------------------------------------------------------------

def test_subscribe_publish_round_trip_still_works():
    bus = EventBus()
    captured = []
    bus.subscribe("entity:spawn", lambda payload: captured.append(payload))
    bus.publish("entity:spawn", entity_id=7, position=(1, 2))
    assert captured == [{"entity_id": 7, "position": (1, 2)}]
