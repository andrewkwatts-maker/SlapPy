"""Headless tests for miscellaneous engine module methods not yet covered.

Covers:
- DataComponent.__contains__, __getattr__, __setattr__, __repr__
- TagRegistry.__contains__, __getitem__
- ZLayer.__hash__
- EventBus.__repr__
- EventDetails.__getattr__, __repr__
- Binding._on_source_changed, __repr__, _attach_source
"""
from __future__ import annotations
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("pharos_engine.compute.asset_compute", MagicMock())

import pytest


# =============================================================================
# DataComponent — __contains__, __getattr__, __setattr__, __repr__
# =============================================================================

class TestDataComponentContains:
    def _dc(self, **kwargs):
        from pharos_engine.data_component import DataComponent
        return DataComponent(**kwargs)

    def test_contains_existing_field(self):
        dc = self._dc(hp=100, speed=5.0)
        assert "hp" in dc

    def test_contains_missing_field(self):
        dc = self._dc(hp=100)
        assert "speed" not in dc

    def test_contains_after_setattr(self):
        dc = self._dc()
        dc.newfield = 42
        assert "newfield" in dc

    def test_not_contains_initially_empty(self):
        dc = self._dc()
        assert "anything" not in dc


class TestDataComponentGetattr:
    def _dc(self, **kwargs):
        from pharos_engine.data_component import DataComponent
        return DataComponent(**kwargs)

    def test_getattr_existing(self):
        dc = self._dc(hp=100)
        assert dc.hp == 100

    def test_getattr_missing_raises(self):
        dc = self._dc(hp=100)
        with pytest.raises(AttributeError):
            _ = dc.speed

    def test_getattr_after_setattr(self):
        dc = self._dc()
        dc.fuel = 0.8
        assert dc.fuel == pytest.approx(0.8)

    def test_getattr_error_message_includes_name(self):
        dc = self._dc()
        with pytest.raises(AttributeError, match="missing_field"):
            _ = dc.missing_field


class TestDataComponentSetattr:
    def _dc(self, **kwargs):
        from pharos_engine.data_component import DataComponent
        return DataComponent(**kwargs)

    def test_setattr_updates_value(self):
        dc = self._dc(hp=100)
        dc.hp = 50
        assert dc.hp == 50

    def test_setattr_fires_watcher(self):
        dc = self._dc(hp=100)
        changes = []
        dc.watch("hp", lambda old, new: changes.append((old, new)))
        dc.hp = 75
        assert changes == [(100, 75)]

    def test_setattr_new_field_no_crash(self):
        dc = self._dc()
        dc.new_field = "hello"
        assert dc.new_field == "hello"

    def test_setattr_watcher_receives_correct_old_new(self):
        dc = self._dc(x=1.0)
        log = []
        dc.watch("x", lambda o, n: log.append((o, n)))
        dc.x = 2.0
        dc.x = 3.0
        assert log == [(1.0, 2.0), (2.0, 3.0)]


class TestDataComponentRepr:
    def test_repr_contains_class_name(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent(hp=100)
        assert "DataComponent" in repr(dc)

    def test_repr_contains_field_name(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent(hp=100, speed=5.0)
        assert "hp" in repr(dc)

    def test_repr_is_string(self):
        from pharos_engine.data_component import DataComponent
        dc = DataComponent()
        assert isinstance(repr(dc), str)


# =============================================================================
# TagRegistry — __contains__, __getitem__
# =============================================================================

class TestTagRegistryContains:
    def _reg(self):
        from pharos_engine.tags import TagRegistry
        return TagRegistry()

    def test_defined_tag_in_registry(self):
        reg = self._reg()
        reg.define("enemy")
        assert "enemy" in reg

    def test_undefined_tag_not_in_registry(self):
        reg = self._reg()
        assert "player" not in reg

    def test_multiple_tags_all_contained(self):
        reg = self._reg()
        reg.define("a")
        reg.define("b")
        assert "a" in reg
        assert "b" in reg


class TestTagRegistryGetitem:
    def _reg(self):
        from pharos_engine.tags import TagRegistry
        return TagRegistry()

    def test_getitem_returns_mask(self):
        reg = self._reg()
        reg.define("enemy")
        mask = reg["enemy"]
        assert isinstance(mask, int)
        assert mask > 0

    def test_getitem_matches_define_return(self):
        reg = self._reg()
        m1 = reg.define("ally")
        m2 = reg["ally"]
        assert m1 == m2

    def test_getitem_missing_raises(self):
        reg = self._reg()
        with pytest.raises(KeyError):
            _ = reg["undefined"]

    def test_two_tags_different_masks(self):
        reg = self._reg()
        reg.define("a")
        reg.define("b")
        assert reg["a"] != reg["b"]


# =============================================================================
# ZLayer.__hash__
# =============================================================================

class TestZLayerHash:
    def test_hash_returns_int(self):
        from pharos_engine.z_height import ZLayer
        zl = ZLayer(name="ground", z=0.0)
        assert isinstance(hash(zl), int)

    def test_two_distinct_layers_different_hash(self):
        from pharos_engine.z_height import ZLayer
        z1 = ZLayer(name="ground")
        z2 = ZLayer(name="ground")  # same data, different object
        # hash(obj) = id(obj) → different objects → different ids
        assert hash(z1) != hash(z2)

    def test_same_object_consistent_hash(self):
        from pharos_engine.z_height import ZLayer
        zl = ZLayer(name="sky", z=100.0)
        assert hash(zl) == hash(zl)

    def test_usable_as_dict_key(self):
        from pharos_engine.z_height import ZLayer
        zl = ZLayer(name="mid", z=50.0)
        d = {zl: "mid_layer"}
        assert d[zl] == "mid_layer"

    def test_usable_in_set(self):
        from pharos_engine.z_height import ZLayer
        z1 = ZLayer(name="a")
        z2 = ZLayer(name="b")
        s = {z1, z2}
        assert len(s) == 2


# =============================================================================
# EventBus.__repr__
# =============================================================================

class TestEventBusRepr:
    def test_repr_contains_eventbus(self):
        from pharos_engine.event_bus import EventBus
        bus = EventBus()
        assert "EventBus" in repr(bus)

    def test_repr_is_string(self):
        from pharos_engine.event_bus import EventBus
        bus = EventBus()
        assert isinstance(repr(bus), str)

    def test_repr_shows_listener_count(self):
        from pharos_engine.event_bus import EventBus
        bus = EventBus()
        bus.subscribe("foo", lambda e: None)
        r = repr(bus)
        assert "1" in r  # 1 type with listeners

    def test_repr_empty_bus(self):
        from pharos_engine.event_bus import EventBus
        bus = EventBus()
        r = repr(bus)
        assert "0" in r  # no types


# =============================================================================
# EventDetails.__getattr__, __repr__
# =============================================================================

class TestEventDetailsGetattr:
    def _evt(self, **payload):
        from pharos_engine.event_bus import EventDetails
        return EventDetails(name="Test.Event", payload=payload)

    def test_payload_field_accessible_as_attr(self):
        evt = self._evt(damage=25)
        assert evt.damage == 25

    def test_missing_payload_field_raises(self):
        evt = self._evt(damage=25)
        with pytest.raises(AttributeError):
            _ = evt.missing_field

    def test_error_includes_event_name(self):
        evt = self._evt()
        with pytest.raises(AttributeError, match="Test.Event"):
            _ = evt.nonexistent

    def test_payload_field_various_types(self):
        evt = self._evt(count=3, label="hit", active=True, ratio=0.5)
        assert evt.count == 3
        assert evt.label == "hit"
        assert evt.active is True
        assert evt.ratio == pytest.approx(0.5)


class TestEventDetailsRepr:
    def test_repr_is_string(self):
        from pharos_engine.event_bus import EventDetails
        evt = EventDetails(name="Foo.Bar", payload={"x": 1})
        assert isinstance(repr(evt), str)

    def test_repr_contains_event_name(self):
        from pharos_engine.event_bus import EventDetails
        evt = EventDetails(name="Vehicle.Hit", payload={"damage": 10})
        assert "Vehicle.Hit" in repr(evt)

    def test_repr_shows_payload_keys(self):
        from pharos_engine.event_bus import EventDetails
        evt = EventDetails(name="Test", payload={"damage": 10, "pos": (0, 0)})
        r = repr(evt)
        assert "damage" in r or "pos" in r


# =============================================================================
# Binding — __repr__, _on_source_changed, _attach_source
# =============================================================================

class TestBindingRepr:
    def test_repr_is_string(self):
        from pharos_engine.event_bus import Binding, Observable

        class _Src(Observable):
            speed: float = 0.0

        class _Dst:
            pass

        src = _Src()
        dst = _Dst()
        b = Binding(src, "speed", dst, "speed")
        assert isinstance(repr(b), str)

    def test_repr_contains_source_attr(self):
        from pharos_engine.event_bus import Binding, Observable

        class _Src(Observable):
            throttle: float = 0.0

        class _Dst:
            throttle: float = 0.0

        src = _Src()
        dst = _Dst()
        b = Binding(src, "throttle", dst, "throttle")
        assert "throttle" in repr(b)


class TestBindingOnSourceChanged:
    def test_updates_target_attr(self):
        from pharos_engine.event_bus import Binding, Observable

        class _Src(Observable):
            speed: float = 0.0

        class _Dst:
            speed: float = 0.0

        src = _Src()
        dst = _Dst()
        b = Binding(src, "speed", dst, "speed")
        b._on_source_changed(99.0)
        assert dst.speed == pytest.approx(99.0)

    def test_formatter_applied(self):
        from pharos_engine.event_bus import Binding, Observable

        class _Src(Observable):
            val: float = 0.0

        class _Dst:
            text: str = ""

        src = _Src()
        dst = _Dst()
        b = Binding(src, "val", dst, "text", formatter=lambda v: f"{v:.1f}")
        b._on_source_changed(3.14)
        assert dst.text == "3.1"

    def test_callable_target(self):
        from pharos_engine.event_bus import Binding, Observable

        class _Src(Observable):
            x: float = 0.0

        received = []
        src = _Src()
        b = Binding(src, "x", lambda v: received.append(v), None)
        received.clear()  # discard initial-value fire on attach
        b._on_source_changed(42.0)
        assert 42.0 in received

    def test_not_reentrant(self):
        from pharos_engine.event_bus import Binding, Observable

        class _Src(Observable):
            y: float = 0.0

        calls = []
        src = _Src()
        b = Binding(src, "y", lambda v: calls.append(v), None)
        calls.clear()  # discard initial-value fire on attach
        # Simulate reentrant call by setting _updating manually
        b._updating = True
        b._on_source_changed(5.0)
        assert len(calls) == 0  # blocked by _updating guard


class TestBindingAttachSource:
    def test_attach_source_observable_creates_handle(self):
        from pharos_engine.event_bus import Binding, Observable, unsubscribe

        class _Src(Observable):
            fuel: float = 1.0

        class _Dst:
            fuel: float = 1.0

        src = _Src()
        dst = _Dst()
        b = Binding(src, "fuel", dst, "fuel")
        assert len(b._handles) >= 1
        b.detach()

    def test_source_change_propagates_to_target(self):
        from pharos_engine.event_bus import Binding, Observable

        class _Src(Observable):
            health: float = 100.0

        class _Dst:
            health: float = 100.0

        src = _Src()
        dst = _Dst()
        b = Binding(src, "health", dst, "health")
        src.health = 50.0
        assert dst.health == pytest.approx(50.0)
        b.detach()
