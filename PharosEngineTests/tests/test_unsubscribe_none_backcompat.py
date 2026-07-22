"""Regression tests for ``EventBus.unsubscribe`` accepting ``None`` event_type.

Downstream games (Ochema Circuit, Bullet Strata) use a teardown pattern:

    bus.unsubscribe(None, listener)   # drop listener from EVERY topic

VV3 game-compat re-verify found 228 sites hitting the strict-str validator
that UU2 introduced. WW1 softens the validator so ``None`` is accepted as
event_type (teardown) while non-str non-None event_type still raises.

Cases covered:

1. ``unsubscribe(None, listener)`` removes listener from all topics.
2. ``unsubscribe()`` is a no-op.
3. ``unsubscribe(None, None)`` is a no-op.
4. ``unsubscribe("topic", listener)`` still works (2-arg form).
5. ``unsubscribe("topic")`` still works (legacy 1-arg form).
6. ``unsubscribe(123, listener)`` still raises TypeError (non-str event_type).

Keep this file green — do not remove without a v1.0 deprecation cycle.
"""
from __future__ import annotations

import pytest


def test_unsubscribe_none_topic_removes_listener_from_all_topics():
    """``unsubscribe(None, listener)`` drops ``listener`` from every topic."""
    from pharos_engine.event_bus import EventBus
    bus = EventBus()
    hits: list[str] = []

    def listener(payload):
        hits.append(payload.get("t", "?"))

    def other(payload):
        hits.append("other")

    bus.subscribe("topic_a", listener)
    bus.subscribe("topic_b", listener)
    bus.subscribe("topic_c", listener)
    bus.subscribe("topic_a", other)  # unrelated listener stays put
    assert bus.listener_count("topic_a") == 2
    assert bus.listener_count("topic_b") == 1
    assert bus.listener_count("topic_c") == 1

    bus.unsubscribe(None, listener)  # teardown pattern

    assert bus.listener_count("topic_a") == 1  # `other` remains
    assert bus.listener_count("topic_b") == 0
    assert bus.listener_count("topic_c") == 0

    bus.publish("topic_a", t="A")
    bus.publish("topic_b", t="B")
    bus.publish("topic_c", t="C")
    assert hits == ["other"]


def test_unsubscribe_no_args_is_noop():
    """Bare ``unsubscribe()`` returns cleanly without touching state."""
    from pharos_engine.event_bus import EventBus
    bus = EventBus()
    bus.subscribe("topic", lambda _p: None)
    assert bus.listener_count("topic") == 1

    result = bus.unsubscribe()  # no args
    assert result is None
    assert bus.listener_count("topic") == 1


def test_unsubscribe_none_none_is_noop():
    """``unsubscribe(None, None)`` is an explicit no-op."""
    from pharos_engine.event_bus import EventBus
    bus = EventBus()
    bus.subscribe("topic", lambda _p: None)
    assert bus.listener_count("topic") == 1

    result = bus.unsubscribe(None, None)
    assert result is None
    assert bus.listener_count("topic") == 1


def test_unsubscribe_two_arg_form_still_works():
    """Modern 2-arg form drops exactly the matching listener."""
    from pharos_engine.event_bus import EventBus
    bus = EventBus()
    hits: list[str] = []

    def _a(_p): hits.append("a")
    def _b(_p): hits.append("b")

    bus.subscribe("topic", _a)
    bus.subscribe("topic", _b)
    assert bus.listener_count("topic") == 2

    bus.unsubscribe("topic", _a)

    assert bus.listener_count("topic") == 1
    bus.publish("topic")
    assert hits == ["b"]


def test_unsubscribe_one_arg_form_still_works():
    """Legacy 1-arg form drops every listener for the topic."""
    from pharos_engine.event_bus import EventBus
    bus = EventBus()
    bus.subscribe("topic", lambda _p: None)
    bus.subscribe("topic", lambda _p: None)
    assert bus.listener_count("topic") == 2

    bus.unsubscribe("topic")

    assert bus.listener_count("topic") == 0


def test_unsubscribe_non_str_non_none_event_type_raises():
    """Integer event_type still raises TypeError — validator remains strict."""
    from pharos_engine.event_bus import EventBus
    bus = EventBus()
    listener = lambda _p: None
    bus.subscribe("topic", listener)

    with pytest.raises(TypeError):
        bus.unsubscribe(123, listener)


def test_module_level_unsubscribe_none_teardown():
    """Module-level proxy also honours the ``unsubscribe(None, listener)`` shape."""
    from pharos_engine.event_bus import (
        global_bus,
        subscribe,
        unsubscribe,
        publish,
    )
    hits: list[str] = []

    def listener(payload):
        hits.append(payload.get("t", "?"))

    subscribe("_ww1:alpha", listener)
    subscribe("_ww1:beta", listener)
    assert global_bus.listener_count("_ww1:alpha") == 1
    assert global_bus.listener_count("_ww1:beta") == 1

    unsubscribe(None, listener)  # teardown pattern via module proxy

    assert global_bus.listener_count("_ww1:alpha") == 0
    assert global_bus.listener_count("_ww1:beta") == 0
    publish("_ww1:alpha", t="A")
    publish("_ww1:beta", t="B")
    assert hits == []
