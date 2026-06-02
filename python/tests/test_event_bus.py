"""Tests for EventBus, Observable, Binding, and global_bus."""
from __future__ import annotations
import pytest
from slappyengine.event_bus import EventBus, Observable, Binding, global_bus


# ── EventBus ─────────────────────────────────────────────────────────────────

class TestEventBus:
    def test_subscribe_and_publish(self):
        bus = EventBus()
        received = []
        bus.subscribe("hit", lambda p: received.append(p["dmg"]))
        bus.publish("hit", dmg=10)
        assert received == [10]

    def test_subscribe_returns_handle(self):
        bus = EventBus()
        h = bus.subscribe("x", lambda p: None)
        assert isinstance(h, int)

    def test_handles_are_unique(self):
        bus = EventBus()
        h1 = bus.subscribe("a", lambda p: None)
        h2 = bus.subscribe("a", lambda p: None)
        assert h1 != h2

    def test_unsubscribe_by_handle(self):
        bus = EventBus()
        fired = []
        h = bus.subscribe("e", lambda p: fired.append(1))
        bus.unsubscribe(h)
        bus.publish("e")
        assert fired == []

    def test_unsubscribe_lambda_by_handle(self):
        """Handle-based unsubscribe works for lambdas (no ref needed)."""
        bus = EventBus()
        fired = []
        h = bus.subscribe("e", lambda p: fired.append(p.get("v")))
        bus.publish("e", v=1)
        bus.unsubscribe(h)
        bus.publish("e", v=2)
        assert fired == [1]

    def test_unsubscribe_by_callback(self):
        bus = EventBus()
        fired = []
        def cb(p): fired.append(p)
        bus.subscribe("e", cb)
        bus.unsubscribe(cb, event_type="e")
        bus.publish("e")
        assert fired == []

    def test_multiple_subscribers_all_fired(self):
        bus = EventBus()
        log = []
        bus.subscribe("e", lambda p: log.append("a"))
        bus.subscribe("e", lambda p: log.append("b"))
        bus.publish("e")
        assert sorted(log) == ["a", "b"]

    def test_publish_no_subscribers_no_crash(self):
        bus = EventBus()
        bus.publish("ghost:event", data=42)  # should not raise

    def test_subscriber_exception_does_not_block_others(self):
        bus = EventBus()
        log = []
        bus.subscribe("e", lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
        bus.subscribe("e", lambda p: log.append("ok"))
        bus.publish("e")
        assert log == ["ok"]

    def test_once_fires_exactly_once(self):
        bus = EventBus()
        count = [0]
        bus.once("e", lambda p: count.__setitem__(0, count[0]+1))
        bus.publish("e")
        bus.publish("e")
        bus.publish("e")
        assert count[0] == 1

    def test_once_returns_handle(self):
        bus = EventBus()
        h = bus.once("e", lambda p: None)
        assert isinstance(h, int)

    def test_on_decorator(self):
        bus = EventBus()
        fired = []
        @bus.on("e")
        def handler(p):
            fired.append(p.get("x"))
        bus.publish("e", x=7)
        assert fired == [7]

    def test_clear_event_type(self):
        bus = EventBus()
        fired = []
        bus.subscribe("e", lambda p: fired.append(1))
        bus.clear("e")
        bus.publish("e")
        assert fired == []

    def test_clear_all(self):
        bus = EventBus()
        fired = []
        bus.subscribe("a", lambda p: fired.append("a"))
        bus.subscribe("b", lambda p: fired.append("b"))
        bus.clear()
        bus.publish("a")
        bus.publish("b")
        assert fired == []

    def test_listener_count(self):
        bus = EventBus()
        assert bus.listener_count("e") == 0
        bus.subscribe("e", lambda p: None)
        bus.subscribe("e", lambda p: None)
        assert bus.listener_count("e") == 2

    def test_listener_count_decreases_on_unsubscribe(self):
        bus = EventBus()
        h = bus.subscribe("e", lambda p: None)
        assert bus.listener_count("e") == 1
        bus.unsubscribe(h)
        assert bus.listener_count("e") == 0

    def test_payload_dict_passed_correctly(self):
        bus = EventBus()
        got = {}
        bus.subscribe("e", lambda p: got.update(p))
        bus.publish("e", a=1, b="hello", c=[1,2])
        assert got == {"a": 1, "b": "hello", "c": [1,2]}

    def test_different_event_types_isolated(self):
        bus = EventBus()
        a_log, b_log = [], []
        bus.subscribe("a", lambda p: a_log.append(1))
        bus.subscribe("b", lambda p: b_log.append(1))
        bus.publish("a")
        assert a_log == [1]
        assert b_log == []


# ── Observable ────────────────────────────────────────────────────────────────

class TestObservable:
    def test_watch_fires_on_set(self):
        class O(Observable): pass
        o = O()
        o.x = 0
        vals = []
        o.watch("x", lambda v: vals.append(v))
        o.x = 42
        assert vals == [42]

    def test_watch_fires_multiple_times(self):
        class O(Observable): pass
        o = O()
        o.x = 0
        vals = []
        o.watch("x", lambda v: vals.append(v))
        o.x = 1
        o.x = 2
        o.x = 3
        assert vals == [1, 2, 3]

    def test_unwatch_stops_notifications(self):
        class O(Observable): pass
        o = O()
        o.x = 0
        vals = []
        h = o.watch("x", lambda v: vals.append(v))
        o.x = 10
        o.unwatch(h)
        o.x = 99
        assert vals == [10]

    def test_multiple_watchers_all_fired(self):
        class O(Observable): pass
        o = O()
        o.x = 0
        a, b = [], []
        o.watch("x", lambda v: a.append(v))
        o.watch("x", lambda v: b.append(v))
        o.x = 5
        assert a == [5] and b == [5]

    def test_unwatch_specific_handle_only(self):
        class O(Observable): pass
        o = O()
        o.x = 0
        a, b = [], []
        h1 = o.watch("x", lambda v: a.append(v))
        h2 = o.watch("x", lambda v: b.append(v))
        o.unwatch(h1)
        o.x = 7
        assert a == [] and b == [7]

    def test_unwatched_attr_no_overhead(self):
        class O(Observable): pass
        o = O()
        o.y = 100   # never watched — should just set normally
        assert o.y == 100

    def test_observable_works_with_inheritance(self):
        class Base(Observable):
            pass
        class Derived(Base):
            pass
        d = Derived()
        d.speed = 0
        vals = []
        d.watch("speed", lambda v: vals.append(v))
        d.speed = 55
        assert vals == [55]

    def test_emit_and_on(self):
        class O(Observable): pass
        o = O()
        received = []
        o.on("item:picked", lambda p: received.append(p["id"]))
        o.emit("item:picked", id=42)
        assert received == [42]

    def test_global_bus_fires_on_watch_attr(self):
        class O(Observable): pass
        o = O()
        o.hp = 100
        o.watch("hp", lambda v: None)  # activate tracking
        hits = []
        h = global_bus.subscribe("prop:changed",
                                 lambda p: hits.append((p.get("attr"), p.get("value"))))
        o.hp = 50
        global_bus.unsubscribe(h)
        assert ("hp", 50) in hits

    def test_watch_returns_int_handle(self):
        class O(Observable): pass
        o = O()
        o.x = 0
        h = o.watch("x", lambda v: None)
        assert isinstance(h, int)


# ── Binding ───────────────────────────────────────────────────────────────────

class TestBinding:
    def test_binding_syncs_on_change(self):
        class Src(Observable): pass
        class Tgt: val = None
        src = Src(); src.x = 0
        tgt = Tgt()
        b = Binding(src, "x", tgt, "val")
        src.x = 99
        assert tgt.val == 99
        b.detach()

    def test_binding_applies_current_value_immediately(self):
        class Src(Observable): pass
        class Tgt: val = None
        src = Src(); src.x = 77
        tgt = Tgt()
        b = Binding(src, "x", tgt, "val")
        assert tgt.val == 77
        b.detach()

    def test_binding_formatter_applied(self):
        class Src(Observable): pass
        class Tgt: text = ""
        src = Src(); src.speed = 0.0
        tgt = Tgt()
        b = Binding(src, "speed", tgt, "text", formatter=lambda v: f"{v:.0f} km/h")
        src.speed = 120.0
        assert tgt.text == "120 km/h"
        b.detach()

    def test_binding_callback_style(self):
        class Src(Observable): pass
        src = Src(); src.x = 0
        received = []
        b = Binding(src, "x", lambda v: received.append(v))
        src.x = 5
        src.x = 10
        assert received == [0, 5, 10]  # initial + two changes
        b.detach()

    def test_binding_detach_stops_updates(self):
        class Src(Observable): pass
        class Tgt: val = None
        src = Src(); src.x = 0
        tgt = Tgt()
        b = Binding(src, "x", tgt, "val")
        b.detach()
        src.x = 42
        assert tgt.val == 0  # initial value, not 42

    def test_bidirectional_binding(self):
        class A(Observable): pass
        class B(Observable): pass
        a = A(); a.x = 0
        b = B(); b.x = 0
        bind = Binding(a, "x", b, "x", bidirectional=True)
        a.x = 10
        assert b.x == 10
        b.x = 20
        assert a.x == 20
        bind.detach()

    def test_binding_no_infinite_loop_bidirectional(self):
        class A(Observable): pass
        class B(Observable): pass
        a = A(); a.x = 0
        b = B(); b.x = 0
        count = [0]
        h = a.watch("x", lambda v: count.__setitem__(0, count[0]+1))
        bind = Binding(a, "x", b, "x", bidirectional=True)
        a.x = 5  # should fire once on a, once on b — but not loop
        assert count[0] <= 2, f"possible infinite loop: count={count[0]}"
        bind.detach()
        a.unwatch(h)

    def test_binding_repr(self):
        class Src(Observable): pass
        class Tgt: val = None
        src = Src(); src.x = 0
        tgt = Tgt()
        b = Binding(src, "x", tgt, "val")
        r = repr(b)
        assert "x" in r
        b.detach()


# ── Global bus ────────────────────────────────────────────────────────────────

class TestGlobalBus:
    def test_global_bus_is_eventbus(self):
        assert isinstance(global_bus, EventBus)

    def test_global_bus_subscribe_publish(self):
        received = []
        h = global_bus.subscribe("_test:global", lambda p: received.append(p.get("v")))
        global_bus.publish("_test:global", v=123)
        global_bus.unsubscribe(h)
        assert received == [123]

    def test_global_bus_import_shorthand(self):
        from slappyengine import global_bus as gb
        assert isinstance(gb, EventBus)

    def test_global_bus_singleton(self):
        from slappyengine.event_bus import global_bus as gb1
        from slappyengine.event_bus import global_bus as gb2
        assert gb1 is gb2
