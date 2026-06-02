"""Headless tests for DataComponent and StructModule subclasses.

Covers:
- slappyengine.data_component    (DataComponent — full attribute/watch/bind/tick)
- slappyengine.modules.health    (HealthModule)
- slappyengine.modules.physics   (PhysicsModule)
- slappyengine.modules.fluid_params (FluidParamsModule)
- slappyengine.modules.pixel_physics (PixelPhysicsModule if present)
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# data_component.py — DataComponent
# ---------------------------------------------------------------------------

class TestDataComponentInit:
    def test_instantiates(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent(hp=100)
        assert dc is not None

    def test_field_readable(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent(hp=100, speed=5.0)
        assert dc.hp == 100

    def test_float_field(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent(speed=5.0)
        assert abs(dc.speed - 5.0) < 1e-9

    def test_string_field(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent(state="idle")
        assert dc.state == "idle"

    def test_missing_field_raises(self):
        import pytest
        from slappyengine.data_component import DataComponent
        dc = DataComponent(hp=100)
        with pytest.raises(AttributeError):
            _ = dc.nonexistent

    def test_to_dict(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent(hp=100, speed=5.0)
        d = dc.to_dict()
        assert d == {"hp": 100, "speed": 5.0}

    def test_to_dict_is_copy(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent(x=1)
        d = dc.to_dict()
        d["x"] = 999
        assert dc.x == 1  # original unchanged

    def test_repr_contains_fields(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent(hp=100)
        assert "hp" in repr(dc)

    def test_contains_true(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent(hp=100)
        assert "hp" in dc

    def test_contains_false(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent(hp=100)
        assert "mp" not in dc

    def test_get_existing_field(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent(score=42)
        assert dc.get("score") == 42

    def test_get_missing_returns_default(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent()
        assert dc.get("hp", 100) == 100

    def test_get_missing_no_default_returns_none(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent()
        assert dc.get("hp") is None


class TestDataComponentSetAttr:
    def test_set_field_changes_value(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent(hp=100)
        dc.hp = 80
        assert dc.hp == 80

    def test_set_new_field(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent()
        dc.speed = 3.0
        assert dc.speed == 3.0

    def test_set_batch_via_set_method(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent(hp=100, speed=5.0)
        dc.set(hp=80, speed=3.0)
        assert dc.hp == 80
        assert dc.speed == 3.0


class TestDataComponentWatch:
    def test_watch_fires_on_change(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent(hp=100)
        calls = []
        dc.watch("hp", lambda old, new: calls.append((old, new)))
        dc.hp = 80
        assert len(calls) == 1
        assert calls[0] == (100, 80)

    def test_watch_not_fired_for_different_field(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent(hp=100, speed=5.0)
        calls = []
        dc.watch("hp", lambda old, new: calls.append(new))
        dc.speed = 3.0
        assert calls == []

    def test_multiple_watchers_same_field(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent(hp=100)
        calls_a = []
        calls_b = []
        dc.watch("hp", lambda o, n: calls_a.append(n))
        dc.watch("hp", lambda o, n: calls_b.append(n))
        dc.hp = 50
        assert calls_a == [50]
        assert calls_b == [50]

    def test_unwatch_stops_firing(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent(hp=100)
        calls = []
        cb = lambda old, new: calls.append(new)
        dc.watch("hp", cb)
        dc.unwatch("hp", cb)
        dc.hp = 80
        assert calls == []

    def test_unwatch_nonexistent_no_crash(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent(hp=100)
        dc.unwatch("nonexistent", lambda o, n: None)  # should not raise

    def test_watcher_exception_no_crash(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent(hp=100)

        def bad_cb(old, new):
            raise RuntimeError("test")

        dc.watch("hp", bad_cb)
        dc.hp = 50  # should not propagate exception

    def test_set_fires_watcher(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent(hp=100)
        calls = []
        dc.watch("hp", lambda o, n: calls.append(n))
        dc.set(hp=70)
        assert calls == [70]


class TestDataComponentBind:
    def test_bind_fires_on_tick_when_predicate_true(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent(hp=0)
        fired = []
        dc.bind(when=lambda d: d.get("hp", 1) <= 0,
                then=lambda d: fired.append(True))
        dc.tick()
        assert len(fired) == 1

    def test_bind_not_fires_when_predicate_false(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent(hp=100)
        fired = []
        dc.bind(when=lambda d: d.get("hp", 100) <= 0,
                then=lambda d: fired.append(True))
        dc.tick()
        assert fired == []

    def test_bind_once_removed_after_firing(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent(hp=0)
        fired = []
        dc.bind(when=lambda d: True, then=lambda d: fired.append(1), once=True)
        dc.tick()
        dc.tick()
        assert len(fired) == 1  # only fired once

    def test_bind_not_once_fires_repeatedly(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent()
        fired = []
        dc.bind(when=lambda d: True, then=lambda d: fired.append(1), once=False)
        dc.tick()
        dc.tick()
        dc.tick()
        assert len(fired) == 3

    def test_tick_predicate_exception_no_crash(self):
        from slappyengine.data_component import DataComponent
        dc = DataComponent()

        def bad_pred(d):
            raise ValueError("test")

        dc.bind(when=bad_pred, then=lambda d: None)
        dc.tick()  # should not raise


# ---------------------------------------------------------------------------
# modules/health.py — HealthModule
# ---------------------------------------------------------------------------

class TestHealthModule:
    def test_name(self):
        from slappyengine.modules.health import HealthModule
        assert HealthModule.name == "health"

    def test_channels_has_health(self):
        from slappyengine.modules.health import HealthModule
        names = [n for n, _ in HealthModule.channels]
        assert "health" in names

    def test_channels_has_max_health(self):
        from slappyengine.modules.health import HealthModule
        names = [n for n, _ in HealthModule.channels]
        assert "max_health" in names

    def test_channels_has_tag(self):
        from slappyengine.modules.health import HealthModule
        names = [n for n, _ in HealthModule.channels]
        assert "tag" in names

    def test_default_health_one(self):
        from slappyengine.modules.health import HealthModule
        assert HealthModule.default_values["health"] == 1.0

    def test_default_max_health_one(self):
        from slappyengine.modules.health import HealthModule
        assert HealthModule.default_values["max_health"] == 1.0

    def test_compute_passes_has_health_sum(self):
        from slappyengine.modules.health import HealthModule
        assert "health_sum" in HealthModule.compute_passes

    def test_is_struct_module(self):
        from slappyengine.struct_registry import StructModule
        from slappyengine.modules.health import HealthModule
        assert issubclass(HealthModule, StructModule)


# ---------------------------------------------------------------------------
# modules/physics.py — PhysicsModule
# ---------------------------------------------------------------------------

class TestPhysicsModule:
    def test_name(self):
        from slappyengine.modules.physics import PhysicsModule
        assert PhysicsModule.name == "physics"

    def test_has_velocity_channels(self):
        from slappyengine.modules.physics import PhysicsModule
        names = [n for n, _ in PhysicsModule.channels]
        assert "vel_x" in names
        assert "vel_y" in names

    def test_has_strength(self):
        from slappyengine.modules.physics import PhysicsModule
        names = [n for n, _ in PhysicsModule.channels]
        assert "strength" in names

    def test_has_stiffness(self):
        from slappyengine.modules.physics import PhysicsModule
        names = [n for n, _ in PhysicsModule.channels]
        assert "stiffness" in names

    def test_default_vel_zero(self):
        from slappyengine.modules.physics import PhysicsModule
        assert PhysicsModule.default_values["vel_x"] == 0.0
        assert PhysicsModule.default_values["vel_y"] == 0.0

    def test_compute_passes_has_rigid(self):
        from slappyengine.modules.physics import PhysicsModule
        assert "rigid" in PhysicsModule.compute_passes


# ---------------------------------------------------------------------------
# modules/fluid_params.py — FluidParamsModule
# ---------------------------------------------------------------------------

class TestFluidParamsModule:
    def test_name(self):
        from slappyengine.modules.fluid_params import FluidParamsModule
        assert FluidParamsModule.name == "fluid"

    def test_has_viscosity(self):
        from slappyengine.modules.fluid_params import FluidParamsModule
        names = [n for n, _ in FluidParamsModule.channels]
        assert "viscosity" in names

    def test_has_pressure(self):
        from slappyengine.modules.fluid_params import FluidParamsModule
        names = [n for n, _ in FluidParamsModule.channels]
        assert "pressure" in names

    def test_has_fluid_tag(self):
        from slappyengine.modules.fluid_params import FluidParamsModule
        names = [n for n, _ in FluidParamsModule.channels]
        assert "fluid_tag" in names

    def test_default_viscosity(self):
        from slappyengine.modules.fluid_params import FluidParamsModule
        assert FluidParamsModule.default_values["viscosity"] == 0.001

    def test_compute_passes_has_fluid(self):
        from slappyengine.modules.fluid_params import FluidParamsModule
        assert "fluid" in FluidParamsModule.compute_passes

    def test_four_channels(self):
        from slappyengine.modules.fluid_params import FluidParamsModule
        assert len(FluidParamsModule.channels) == 4


# ---------------------------------------------------------------------------
# modules/pixel_physics.py — if it exists
# ---------------------------------------------------------------------------

class TestPixelPhysicsModule:
    def test_importable(self):
        try:
            from slappyengine.modules.pixel_physics import PixelPhysicsModule
            assert PixelPhysicsModule is not None
        except ImportError:
            import pytest
            pytest.skip("pixel_physics module not present")

    def test_is_struct_module(self):
        try:
            from slappyengine.modules.pixel_physics import PixelPhysicsModule
            from slappyengine.struct_registry import StructModule
            assert issubclass(PixelPhysicsModule, StructModule)
        except ImportError:
            import pytest
            pytest.skip("pixel_physics module not present")

    def test_has_channels(self):
        try:
            from slappyengine.modules.pixel_physics import PixelPhysicsModule
            assert len(PixelPhysicsModule.channels) >= 1
        except ImportError:
            import pytest
            pytest.skip("pixel_physics module not present")
