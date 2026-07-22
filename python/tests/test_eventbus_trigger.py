"""Engine tests for event_bus.py and trigger.py.
All headless — no GPU required.
"""
from __future__ import annotations
import pytest


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------

class TestEventBusSubscribePublish:
    def setup_method(self):
        from slappyengine.event_bus import EventBus
        self.bus = EventBus()

    def test_subscribe_returns_int_handle(self):
        h = self.bus.subscribe("entity:hit", lambda p: None)
        assert isinstance(h, int)

    def test_publish_fires_callback(self):
        received = []
        self.bus.subscribe("entity:hit", lambda p: received.append(p))
        self.bus.publish("entity:hit", damage=10)
        assert len(received) == 1
        assert received[0]["damage"] == 10

    def test_unsubscribe_by_handle(self):
        received = []
        h = self.bus.subscribe("evt", lambda p: received.append(p))
        self.bus.unsubscribe(h)
        self.bus.publish("evt")
        assert received == []

    def test_publish_no_subscribers_no_crash(self):
        self.bus.publish("unused:event", x=1)

    def test_multiple_subscribers(self):
        results = []
        self.bus.subscribe("e", lambda p: results.append("a"))
        self.bus.subscribe("e", lambda p: results.append("b"))
        self.bus.publish("e")
        assert "a" in results and "b" in results

    def test_handles_monotone(self):
        h1 = self.bus.subscribe("e", lambda p: None)
        h2 = self.bus.subscribe("e", lambda p: None)
        assert h2 > h1

    def test_listener_count(self):
        self.bus.subscribe("e", lambda p: None)
        self.bus.subscribe("e", lambda p: None)
        assert self.bus.listener_count("e") == 2

    def test_listener_count_after_unsubscribe(self):
        h = self.bus.subscribe("e", lambda p: None)
        self.bus.subscribe("e", lambda p: None)
        self.bus.unsubscribe(h)
        assert self.bus.listener_count("e") == 1

    def test_clear_all(self):
        self.bus.subscribe("a", lambda p: None)
        self.bus.subscribe("b", lambda p: None)
        self.bus.clear()
        assert self.bus.listener_count("a") == 0
        assert self.bus.listener_count("b") == 0

    def test_clear_specific_event(self):
        self.bus.subscribe("a", lambda p: None)
        self.bus.subscribe("b", lambda p: None)
        self.bus.clear("a")
        assert self.bus.listener_count("a") == 0
        assert self.bus.listener_count("b") == 1

    def test_once_fires_once(self):
        count = []
        self.bus.once("e", lambda p: count.append(1))
        self.bus.publish("e")
        self.bus.publish("e")
        assert len(count) == 1

    def test_on_decorator(self):
        received = []

        @self.bus.on("click")
        def handler(p):
            received.append(p.get("x"))

        self.bus.publish("click", x=42)
        assert received == [42]

    def test_callback_exception_does_not_block_others(self):
        received = []

        def bad_cb(p):
            raise RuntimeError("boom")

        def good_cb(p):
            received.append(1)

        self.bus.subscribe("e", bad_cb)
        self.bus.subscribe("e", good_cb)
        self.bus.publish("e")
        assert received == [1]

    def test_unsubscribe_by_callback(self):
        received = []

        def cb(p):
            received.append(1)

        self.bus.subscribe("e", cb)
        self.bus.unsubscribe(cb)
        self.bus.publish("e")
        assert received == []

    def test_thread_safe_mode(self):
        from slappyengine.event_bus import EventBus
        bus = EventBus(thread_safe=True)
        results = []
        bus.subscribe("e", lambda p: results.append(1))
        bus.publish("e")
        assert results == [1]


# ---------------------------------------------------------------------------
# Global bus publish/subscribe helpers
# ---------------------------------------------------------------------------

class TestGlobalBusHelpers:
    def setup_method(self):
        from slappyengine.event_bus import global_bus
        global_bus.clear()

    def teardown_method(self):
        from slappyengine.event_bus import global_bus
        global_bus.clear()

    def test_subscribe_and_publish(self):
        from slappyengine.event_bus import subscribe, publish, unsubscribe
        received = []
        h = subscribe("Test.Event", lambda evt: received.append(evt.name))
        publish("Test.Event")
        unsubscribe(h)
        assert "Test.Event" in received

    def test_hierarchical_fanout(self):
        from slappyengine.event_bus import subscribe, publish, unsubscribe
        received = []
        h1 = subscribe("Race.LapComplete", lambda evt: received.append("lap"))
        h2 = subscribe("Race", lambda evt: received.append("race"))
        publish("Race.LapComplete")
        unsubscribe(h1)
        unsubscribe(h2)
        assert "lap" in received
        assert "race" in received

    def test_value_pipe_fanout(self):
        from slappyengine.event_bus import subscribe, publish, unsubscribe
        received_exact = []
        received_path = []
        h1 = subscribe("Vehicle.speed|120.0", lambda evt: received_exact.append(1))
        h2 = subscribe("Vehicle.speed", lambda evt: received_path.append(1))
        publish("Vehicle.speed|120.0")
        unsubscribe(h1)
        unsubscribe(h2)
        assert received_exact  # exact match fires
        assert received_path   # path match also fires

    def test_event_details_name(self):
        from slappyengine.event_bus import subscribe, publish, unsubscribe
        names = []
        h = subscribe("My.Event", lambda evt: names.append(evt.name))
        publish("My.Event")
        unsubscribe(h)
        assert "My.Event" in names

    def test_event_details_payload_attr(self):
        from slappyengine.event_bus import subscribe, publish, unsubscribe
        vals = []
        h = subscribe("My.Event", lambda evt: vals.append(evt.fuel))
        publish("My.Event", fuel=0.5)
        unsubscribe(h)
        assert vals == [pytest.approx(0.5)]

    def test_event_details_bad_attr_raises(self):
        from slappyengine.event_bus import EventDetails
        ed = EventDetails(name="x", payload={"a": 1})
        with pytest.raises(AttributeError):
            _ = ed.nonexistent

    def test_listener_count_helper(self):
        from slappyengine.event_bus import subscribe, unsubscribe, listener_count
        h = subscribe("X.Y", lambda e: None)
        assert listener_count("X.Y") >= 1
        unsubscribe(h)

    def test_publish_batch(self):
        from slappyengine.event_bus import subscribe, unsubscribe, publish_batch
        received = []
        h = subscribe("Batch", lambda evt: received.append(1))
        publish_batch([("Batch", {}), ("Batch", {})])
        unsubscribe(h)
        assert len(received) == 2

    def test_debug_listeners(self):
        from slappyengine.event_bus import subscribe, unsubscribe, debug_listeners
        h = subscribe("Debug.Test", lambda e: None)
        d = debug_listeners()
        assert isinstance(d, dict)
        unsubscribe(h)


# ---------------------------------------------------------------------------
# EventDetails
# ---------------------------------------------------------------------------

class TestEventDetails:
    def test_instantiates(self):
        from slappyengine.event_bus import EventDetails
        ed = EventDetails(name="x")
        assert ed.name == "x"

    def test_payload_access_as_attr(self):
        from slappyengine.event_bus import EventDetails
        ed = EventDetails(name="x", payload={"speed": 100})
        assert ed.speed == 100

    def test_publisher_stored(self):
        from slappyengine.event_bus import EventDetails
        obj = object()
        ed = EventDetails(name="x", publisher=obj)
        assert ed.publisher is obj

    def test_timestamp_is_float(self):
        from slappyengine.event_bus import EventDetails
        ed = EventDetails(name="x")
        assert isinstance(ed.timestamp, float)

    def test_repr(self):
        from slappyengine.event_bus import EventDetails
        ed = EventDetails(name="x", payload={"a": 1})
        r = repr(ed)
        assert "x" in r


# ---------------------------------------------------------------------------
# Observable
# ---------------------------------------------------------------------------

class TestObservable:
    def setup_method(self):
        from slappyengine.event_bus import global_bus
        global_bus.clear()

    def teardown_method(self):
        from slappyengine.event_bus import global_bus
        global_bus.clear()

    def test_instantiates(self):
        from slappyengine.event_bus import Observable

        class MyObj(Observable):
            pass

        o = MyObj()
        assert o is not None

    def test_set_attr_no_crash(self):
        from slappyengine.event_bus import Observable

        class MyObj(Observable):
            pass

        o = MyObj()
        o.speed = 100.0
        assert o.speed == pytest.approx(100.0)

    def test_private_attr_not_published(self):
        from slappyengine.event_bus import Observable, subscribe, unsubscribe
        received = []

        class MyObj(Observable):
            pass

        o = MyObj()
        h = subscribe("MyObj._speed", lambda e: received.append(1))
        o._speed = 50.0
        unsubscribe(h)
        assert received == []

    def test_no_publish_attr_not_published(self):
        from slappyengine.event_bus import Observable, subscribe, unsubscribe
        received = []

        class MyObj(Observable):
            __no_publish__ = frozenset({"frame_idx"})

        o = MyObj()
        h = subscribe("MyObj.frame_idx", lambda e: received.append(1))
        o.frame_idx = 5
        unsubscribe(h)
        assert received == []

    def test_public_attr_published_when_listener(self):
        from slappyengine.event_bus import Observable, subscribe, unsubscribe
        received = []

        class MyObj(Observable):
            pass

        o = MyObj()
        h = subscribe("MyObj.speed", lambda e: received.append(e.value))
        o.speed = 120.0
        unsubscribe(h)
        assert 120.0 in received

    def test_watch_fires_on_change(self):
        from slappyengine.event_bus import Observable
        received = []

        class MyObj(Observable):
            pass

        o = MyObj()
        o.watch("fuel", lambda val: received.append(val))
        o.fuel = 0.5
        assert received == [pytest.approx(0.5)]

    def test_unwatch_stops_firing(self):
        from slappyengine.event_bus import Observable
        received = []

        class MyObj(Observable):
            pass

        o = MyObj()
        handle = o.watch("fuel", lambda val: received.append(val))
        o.fuel = 0.5
        o.unwatch(handle)
        o.fuel = 0.2
        assert len(received) == 1  # only first change

    def test_emit_fires_local_bus(self):
        from slappyengine.event_bus import Observable
        received = []

        class MyObj(Observable):
            pass

        o = MyObj()
        o.on("custom:event", lambda p: received.append(p.get("x")))
        o.emit("custom:event", x=99)
        assert received == [99]


# ---------------------------------------------------------------------------
# Binding
# ---------------------------------------------------------------------------

class TestBinding:
    def setup_method(self):
        from slappyengine.event_bus import global_bus
        global_bus.clear()

    def teardown_method(self):
        from slappyengine.event_bus import global_bus
        global_bus.clear()

    def test_binding_instantiates(self):
        from slappyengine.event_bus import Observable, Binding

        class Source(Observable):
            pass

        s = Source()
        s.speed = 0.0
        received = []
        b = Binding(s, "speed", lambda val: received.append(val))
        assert b is not None

    def test_binding_initial_value_applied(self):
        from slappyengine.event_bus import Observable, Binding

        class Source(Observable):
            pass

        s = Source()
        s.speed = 50.0
        received = []
        Binding(s, "speed", lambda val: received.append(val))
        assert received == [pytest.approx(50.0)]

    def test_binding_updates_on_change(self):
        from slappyengine.event_bus import Observable, Binding

        class Source(Observable):
            pass

        s = Source()
        s.speed = 0.0
        received = []
        b = Binding(s, "speed", lambda val: received.append(val))
        s.speed = 120.0
        b.detach()
        assert 120.0 in received

    def test_binding_formatter_applied(self):
        from slappyengine.event_bus import Observable, Binding

        class Source(Observable):
            pass

        s = Source()
        s.speed = 0.0
        received = []
        b = Binding(s, "speed", lambda val: received.append(val),
                    formatter=lambda v: v * 2)
        s.speed = 10.0
        b.detach()
        assert 20.0 in received

    def test_binding_target_object(self):
        from slappyengine.event_bus import Observable, Binding

        class Source(Observable):
            pass

        class Target:
            value = 0.0

        s = Source()
        s.x = 0.0
        t = Target()
        b = Binding(s, "x", t, "value")
        s.x = 99.0
        b.detach()
        assert t.value == pytest.approx(99.0)

    def test_binding_filter(self):
        from slappyengine.event_bus import Observable, Binding

        class Source(Observable):
            pass

        s = Source()
        s.fuel = 1.0
        received = []
        b = Binding(s, "fuel", lambda val: received.append(val))
        b.filter(lambda v: v < 0.5)
        s.fuel = 0.8  # filtered out
        s.fuel = 0.3  # passes
        b.detach()
        # 0.3 should be received, 0.8 filtered
        assert 0.3 in received
        assert 0.8 not in received

    def test_binding_detach_stops_updates(self):
        from slappyengine.event_bus import Observable, Binding

        class Source(Observable):
            pass

        s = Source()
        s.speed = 0.0
        received = []
        b = Binding(s, "speed", lambda val: received.append(val))
        b.detach()
        s.speed = 999.0
        # Only the initial value should be in received (from __init__ apply)
        assert 999.0 not in received


# ---------------------------------------------------------------------------
# TriggerVolume + TriggerSystem
# ---------------------------------------------------------------------------

class _Entity:
    """Minimal entity for trigger testing."""
    def __init__(self, x, y, w=8, h=8):
        self.position = (x, y)
        self.size = (w, h)


class TestTriggerVolume:
    def test_instantiates(self):
        from slappyengine.trigger import TriggerVolume
        v = TriggerVolume(position=(100, 100), size=(50, 50))
        assert v is not None

    def test_defaults(self):
        from slappyengine.trigger import TriggerVolume
        v = TriggerVolume(position=(0, 0), size=(10, 10))
        assert v.normal == (0.0, 1.0)
        assert v.on_enter is None
        assert v.on_exit is None
        assert v.on_stay is None
        assert v.tag == ""
        assert v.pixel_precise is False

    def test_custom_values(self):
        from slappyengine.trigger import TriggerVolume
        v = TriggerVolume(position=(50, 50), size=(20, 20), tag="boost",
                          pixel_precise=True)
        assert v.tag == "boost"
        assert v.pixel_precise is True


class TestTriggerSystem:
    def setup_method(self):
        from slappyengine.event_bus import global_bus
        global_bus.clear()

    def teardown_method(self):
        from slappyengine.event_bus import global_bus
        global_bus.clear()

    def test_instantiates(self):
        from slappyengine.trigger import TriggerSystem
        ts = TriggerSystem()
        assert ts is not None

    def test_add_volume(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        ts = TriggerSystem()
        v = TriggerVolume(position=(0, 0), size=(10, 10))
        result = ts.add(v)
        assert result is v
        assert v in ts._volumes

    def test_remove_volume(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        ts = TriggerSystem()
        v = TriggerVolume(position=(0, 0), size=(10, 10))
        ts.add(v)
        ts.remove(v)
        assert v not in ts._volumes

    def test_remove_not_present_no_crash(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        ts = TriggerSystem()
        v = TriggerVolume(position=(0, 0), size=(10, 10))
        ts.remove(v)  # should not raise

    def test_clear(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        ts = TriggerSystem()
        ts.add(TriggerVolume(position=(0, 0), size=(10, 10)))
        ts.add(TriggerVolume(position=(50, 50), size=(10, 10)))
        ts.clear()
        assert ts._volumes == []

    def test_on_enter_fires(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        entered = []
        ts = TriggerSystem()
        v = TriggerVolume(position=(0, 0), size=(20, 20),
                          on_enter=lambda e: entered.append(e))
        ts.add(v)
        e = _Entity(0, 0)
        ts.update([e])
        assert len(entered) == 1

    def test_on_enter_not_fires_outside(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        entered = []
        ts = TriggerSystem()
        v = TriggerVolume(position=(0, 0), size=(10, 10),
                          on_enter=lambda e: entered.append(e))
        ts.add(v)
        e = _Entity(100, 100)  # far away
        ts.update([e])
        assert entered == []

    def test_on_enter_fires_only_once(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        entered = []
        ts = TriggerSystem()
        v = TriggerVolume(position=(0, 0), size=(20, 20),
                          on_enter=lambda e: entered.append(e))
        ts.add(v)
        e = _Entity(0, 0)
        ts.update([e])
        ts.update([e])  # second frame — still inside
        assert len(entered) == 1

    def test_on_stay_fires_while_inside(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        stays = []
        ts = TriggerSystem()
        v = TriggerVolume(position=(0, 0), size=(20, 20),
                          on_stay=lambda e: stays.append(1))
        ts.add(v)
        e = _Entity(0, 0)
        ts.update([e])  # frame 1 — enter
        ts.update([e])  # frame 2 — stay
        ts.update([e])  # frame 3 — stay
        assert len(stays) == 2  # frames 2 and 3

    def test_on_exit_fires(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        exited = []
        ts = TriggerSystem()
        v = TriggerVolume(position=(0, 0), size=(20, 20),
                          on_exit=lambda e: exited.append(e))
        ts.add(v)
        e = _Entity(0, 0)
        ts.update([e])           # enter — e is now inside
        e.position = (100, 100)  # move same entity far away
        ts.update([e])           # exit — e still in list but no longer overlapping
        assert len(exited) == 1

    def test_tagged_volume_publishes_event(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        from slappyengine.event_bus import subscribe, unsubscribe
        received = []
        h = subscribe("Trigger.Enter.boost", lambda evt: received.append(1))
        ts = TriggerSystem()
        v = TriggerVolume(position=(0, 0), size=(20, 20), tag="boost")
        ts.add(v)
        e = _Entity(0, 0)
        ts.update([e])
        unsubscribe(h)
        assert received

    def test_empty_entities_no_crash(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        ts = TriggerSystem()
        ts.add(TriggerVolume(position=(0, 0), size=(10, 10)))
        ts.update([])

    def test_entity_without_size_uses_default(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        entered = []
        ts = TriggerSystem()
        v = TriggerVolume(position=(0, 0), size=(20, 20),
                          on_enter=lambda e: entered.append(e))
        ts.add(v)

        class NoSizeEntity:
            position = (0, 0)

        ts.update([NoSizeEntity()])
        assert entered  # default 8×8 should still overlap at (0,0)


# ---------------------------------------------------------------------------
# ReverbZone
# ---------------------------------------------------------------------------

class TestReverbZone:
    def setup_method(self):
        from slappyengine.event_bus import global_bus
        global_bus.clear()

    def teardown_method(self):
        from slappyengine.event_bus import global_bus
        global_bus.clear()

    def test_instantiates(self):
        from slappyengine.trigger import ReverbZone
        rz = ReverbZone(position=(100, 100), size=(80, 40),
                        tag="tunnel", reverb_amount=0.7, reverb_decay=1.2)
        assert rz is not None

    def test_is_trigger_volume(self):
        from slappyengine.trigger import ReverbZone, TriggerVolume
        rz = ReverbZone(position=(0, 0), size=(10, 10), tag="r")
        assert isinstance(rz, TriggerVolume)

    def test_reverb_fields_stored(self):
        from slappyengine.trigger import ReverbZone
        rz = ReverbZone(position=(0, 0), size=(10, 10), tag="r",
                        reverb_amount=0.5, reverb_decay=2.0)
        assert rz.reverb_amount == pytest.approx(0.5)
        assert rz.reverb_decay == pytest.approx(2.0)
