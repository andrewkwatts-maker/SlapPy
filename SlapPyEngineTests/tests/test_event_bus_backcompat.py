"""Regression tests for ``slappyengine.event_bus`` backwards-compat surface.

Downstream games (Ochema Circuit, Bullet Strata) rely on:

1. Module symbol ``global_bus`` importable from ``slappyengine.event_bus``.
2. ``EventBus.unsubscribe(topic)`` — single-arg form that removes all
   listeners for the topic.
3. ``EventBus.unsubscribe(topic, listener)`` — modern two-arg form that
   removes only the specific listener.
4. ``global_bus`` is a process-wide singleton (same instance across
   repeated imports).

If any of these regress the games break at import time. Keep this file
green — do not remove without a v1.0 deprecation cycle. (UU2)
"""
from __future__ import annotations


def test_global_bus_importable():
    """Legacy import path must resolve to an ``EventBus`` instance."""
    from slappyengine.event_bus import global_bus, EventBus
    assert isinstance(global_bus, EventBus)


def test_unsubscribe_one_arg_removes_all_listeners_for_topic():
    """Legacy 1-arg form ``bus.unsubscribe("topic")`` drops every listener."""
    from slappyengine.event_bus import EventBus
    bus = EventBus()
    hits: list[str] = []
    bus.subscribe("topic", lambda _p: hits.append("a"))
    bus.subscribe("topic", lambda _p: hits.append("b"))
    assert bus.listener_count("topic") == 2

    bus.unsubscribe("topic")  # legacy 1-arg form

    assert bus.listener_count("topic") == 0
    bus.publish("topic")
    assert hits == []


def test_unsubscribe_two_arg_removes_only_specific_listener():
    """Modern 2-arg form drops exactly one callback, leaves others alone."""
    from slappyengine.event_bus import EventBus
    bus = EventBus()
    hits: list[str] = []

    def _a(_p): hits.append("a")
    def _b(_p): hits.append("b")

    bus.subscribe("topic", _a)
    bus.subscribe("topic", _b)
    assert bus.listener_count("topic") == 2

    bus.unsubscribe("topic", _a)  # modern 2-arg form

    assert bus.listener_count("topic") == 1
    bus.publish("topic")
    assert hits == ["b"]


def test_global_bus_is_process_wide_singleton():
    """Repeated imports must yield the identical bus object."""
    from slappyengine.event_bus import global_bus as gb_first
    from slappyengine.event_bus import global_bus as gb_second
    from slappyengine.event_bus import get_default_bus

    assert gb_first is gb_second
    assert gb_first is get_default_bus()


def test_module_level_unsubscribe_one_arg_form():
    """Module-level ``unsubscribe`` proxy also accepts the legacy 1-arg form."""
    from slappyengine.event_bus import (
        global_bus,
        subscribe,
        unsubscribe,
        publish,
    )
    hits: list[int] = []
    subscribe("_backcompat:test", lambda p: hits.append(p.get("v", 0)))
    subscribe("_backcompat:test", lambda p: hits.append(-p.get("v", 0)))
    assert global_bus.listener_count("_backcompat:test") == 2

    unsubscribe("_backcompat:test")  # legacy 1-arg form via module proxy

    assert global_bus.listener_count("_backcompat:test") == 0
    publish("_backcompat:test", v=7)
    assert hits == []
