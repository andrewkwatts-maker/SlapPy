"""Sprint P1 — Observable and RunRule integration tests."""
import pytest


def test_private_attr_no_publish():
    """Private attrs (starting with _) must not publish events."""
    from slappyengine.event_bus import Observable, global_bus

    class Obj(Observable):
        pass

    events = []
    h = global_bus.subscribe("Obj._internal", lambda e: events.append(e))
    obj = Obj()
    obj._internal = 42
    global_bus.unsubscribe(h)
    assert events == [], "Private attr should not publish"


def test_no_publish_set_skips():
    """Attrs in __no_publish__ must not fire global bus events."""
    from slappyengine.event_bus import Observable, global_bus

    class Obj(Observable):
        __no_publish__ = frozenset({"temp"})

    events = []
    h = global_bus.subscribe("Obj.temp", lambda e: events.append(e))
    obj = Obj()
    obj.temp = 99
    global_bus.unsubscribe(h)
    assert events == [], "Opted-out attr should not publish"


def test_public_attr_publishes():
    """Public attrs on Observable fire 'ClassName.attr' events."""
    from slappyengine.event_bus import Observable, subscribe, unsubscribe

    class Vehicle(Observable):
        pass

    received = []
    h = subscribe("Vehicle.speed", lambda evt: received.append(evt.value))
    v = Vehicle()
    v.speed = 120.0
    unsubscribe(h)
    assert received == [120.0]


def test_no_subscribers_no_publish_overhead():
    """When nobody subscribes to ClassName.attr, setting it must not raise."""
    from slappyengine.event_bus import Observable, global_bus

    class Counter(Observable):
        pass

    assert global_bus.listener_count("Counter.x") == 0
    c = Counter()
    for _ in range(1000):
        c.x = 1  # no subscribers — Rule 3 skips publish


def test_trigger_publishes_event():
    """TriggerVolume crossing publishes Trigger.Enter.<tag> on the global bus."""
    try:
        from slappyengine.trigger import TriggerVolume, TriggerSystem
        from slappyengine.event_bus import subscribe, unsubscribe
    except ImportError:
        pytest.skip("trigger module not available")

    received = []
    h = subscribe("Trigger.Enter.boost", lambda evt: received.append(evt))

    class FakeEntity:
        position = (100, 100)
        size = (20, 20)

    vol = TriggerVolume(position=(90, 90), size=(40, 40), tag="boost")
    system = TriggerSystem()
    system.add(vol)
    system.update([FakeEntity()])

    unsubscribe(h)
    assert len(received) >= 1, "Trigger.Enter.boost should have fired"


def test_runrule_on_subscribed_skips_when_no_listeners():
    """ON_SUBSCRIBED pass must return False when there are no listeners."""
    from slappyengine.compute.pipeline import ComputePass, RunRule
    from slappyengine.event_bus import global_bus

    pass_ = ComputePass.from_source(
        "// dummy",
        run_rule=RunRule.ON_SUBSCRIBED,
        event_name="Test.NoListeners.Result",
    )
    assert global_bus.listener_count("Test.NoListeners.Result") == 0
    assert pass_.should_run() is False


def test_runrule_on_subscribed_runs_with_listener():
    """ON_SUBSCRIBED pass should_run() returns True when there is a subscriber."""
    from slappyengine.compute.pipeline import ComputePass, RunRule
    from slappyengine.event_bus import subscribe, unsubscribe

    pass_ = ComputePass.from_source(
        "// dummy",
        run_rule=RunRule.ON_SUBSCRIBED,
        event_name="Test.HasListener.Result",
    )
    h = subscribe("Test.HasListener.Result", lambda e: None)
    result = pass_.should_run()
    unsubscribe(h)
    assert result is True


def test_runrule_on_demand_oneshot():
    """ON_DEMAND pass runs exactly once after trigger(), then stops."""
    from slappyengine.compute.pipeline import ComputePass, RunRule

    pass_ = ComputePass.from_source("// dummy", run_rule=RunRule.ON_DEMAND)
    assert pass_.should_run() is False
    pass_.trigger()
    assert pass_.should_run() is True
    assert pass_.should_run() is False


def test_hierarchical_fanout():
    """Publishing A.B.C reaches subscribers on A.B.C, A.B, and A."""
    from slappyengine.event_bus import publish, subscribe, unsubscribe

    hits = {"A.B.C": 0, "A.B": 0, "A": 0}
    handles = [
        subscribe("A.B.C", lambda e: hits.__setitem__("A.B.C", hits["A.B.C"] + 1)),
        subscribe("A.B",   lambda e: hits.__setitem__("A.B",   hits["A.B"]   + 1)),
        subscribe("A",     lambda e: hits.__setitem__("A",     hits["A"]     + 1)),
    ]
    publish("A.B.C", x=1)
    for h in handles:
        unsubscribe(h)
    assert hits == {"A.B.C": 1, "A.B": 1, "A": 1}


def test_binding_filter():
    """Binding.filter() only propagates updates when predicate returns True."""
    from slappyengine.event_bus import Observable, Binding

    class Src(Observable):
        pass

    received = []
    src = Src()
    b = Binding(src, "speed", lambda v: received.append(v))
    b.filter(lambda v: v is not None and v > 50)

    src.speed = 30    # filtered out
    src.speed = 80    # passes
    src.speed = 20    # filtered out
    src.speed = 100   # passes
    b.detach()

    assert received == [80, 100]


def test_binding_debounce():
    """Binding.debounce() coalesces rapid updates within the window."""
    import time
    from slappyengine.event_bus import Observable, Binding

    class Src(Observable):
        pass

    received = []
    src = Src()
    b = Binding(src, "value", lambda v: received.append(v))
    b.debounce(0.5)

    src.value = 1   # accepted
    src.value = 2   # debounced (too soon)
    src.value = 3   # debounced (too soon)
    b.detach()

    # Only the first update should have passed within the debounce window
    assert len(received) == 1
    assert received[0] == 1
