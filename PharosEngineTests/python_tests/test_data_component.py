"""Engine tests for DataComponent — reactive key-value store."""
from __future__ import annotations
import pytest


class TestDataComponentBasics:
    def test_init_stores_fields(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent(hp=100, speed=5.0)
        assert dc.hp == 100
        assert dc.speed == pytest.approx(5.0)

    def test_attribute_error_for_missing_field(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent(hp=100)
        with pytest.raises(AttributeError):
            _ = dc.missing_field

    def test_setattr_updates_field(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent(hp=100)
        dc.hp = 80
        assert dc.hp == 80

    def test_get_returns_default_for_missing(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent()
        assert dc.get("missing", 42) == 42

    def test_get_returns_value_for_existing(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent(x=10)
        assert dc.get("x") == 10

    def test_contains_true_for_existing_field(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent(state="idle")
        assert "state" in dc

    def test_contains_false_for_missing_field(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent()
        assert "nope" not in dc

    def test_to_dict_returns_all_fields(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent(a=1, b=2)
        d = dc.to_dict()
        assert d == {"a": 1, "b": 2}

    def test_set_batch_updates_fields(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent(hp=100, energy=50)
        dc.set(hp=80, energy=30)
        assert dc.hp == 80
        assert dc.energy == 30

    def test_repr_contains_fields(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent(x=1)
        assert "x" in repr(dc)


class TestDataComponentWatchers:
    def test_watch_fires_on_change(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent(hp=100)
        fired = []
        dc.watch("hp", lambda old, new: fired.append((old, new)))
        dc.hp = 80
        assert len(fired) == 1
        assert fired[0] == (100, 80)

    def test_watch_receives_old_and_new(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent(x=0)
        pairs = []
        dc.watch("x", lambda o, n: pairs.append((o, n)))
        dc.x = 5
        assert pairs[0] == (0, 5)

    def test_watch_not_fired_for_other_field(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent(a=1, b=2)
        fired = []
        dc.watch("a", lambda o, n: fired.append((o, n)))
        dc.b = 99
        assert len(fired) == 0

    def test_multiple_watchers_on_same_field(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent(v=0)
        results = []
        dc.watch("v", lambda o, n: results.append("first"))
        dc.watch("v", lambda o, n: results.append("second"))
        dc.v = 1
        assert "first" in results
        assert "second" in results

    def test_unwatch_removes_callback(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent(x=0)
        fired = []
        cb = lambda o, n: fired.append(n)
        dc.watch("x", cb)
        dc.unwatch("x", cb)
        dc.x = 10
        assert len(fired) == 0

    def test_unwatch_missing_callback_no_crash(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent(x=0)
        dc.unwatch("x", lambda o, n: None)  # never registered

    def test_watcher_exception_does_not_crash(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent(x=0)
        dc.watch("x", lambda o, n: (_ for _ in ()).throw(ValueError("boom")))
        dc.x = 1  # should not raise despite bad watcher

    def test_set_fires_watchers_per_field(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent(a=0, b=0)
        events = []
        dc.watch("a", lambda o, n: events.append(("a", n)))
        dc.watch("b", lambda o, n: events.append(("b", n)))
        dc.set(a=1, b=2)
        assert ("a", 1) in events
        assert ("b", 2) in events


class TestDataComponentBindings:
    def test_bind_fires_when_condition_true(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent(hp=0)
        fired = []
        dc.bind(when=lambda d: d.hp <= 0, then=lambda d: fired.append(True))
        dc.tick()
        assert len(fired) == 1

    def test_bind_does_not_fire_when_condition_false(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent(hp=100)
        fired = []
        dc.bind(when=lambda d: d.hp <= 0, then=lambda d: fired.append(True))
        dc.tick()
        assert len(fired) == 0

    def test_bind_once_fires_only_once(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent(hp=0)
        count = [0]
        dc.bind(when=lambda d: d.hp <= 0, then=lambda d: count.__setitem__(0, count[0] + 1), once=True)
        dc.tick()
        dc.tick()
        assert count[0] == 1

    def test_bind_once_false_fires_repeatedly(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent(flag=True)
        count = [0]
        dc.bind(when=lambda d: d.flag, then=lambda d: count.__setitem__(0, count[0] + 1), once=False)
        dc.tick()
        dc.tick()
        dc.tick()
        assert count[0] == 3

    def test_bind_removed_after_once(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent(v=1)
        dc.bind(when=lambda d: True, then=lambda d: None, once=True)
        dc.tick()
        bindings = object.__getattribute__(dc, "_bindings")
        assert len(bindings) == 0

    def test_bind_condition_exception_does_not_crash(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent()
        dc.bind(when=lambda d: 1 / 0, then=lambda d: None)
        dc.tick()  # should not raise
