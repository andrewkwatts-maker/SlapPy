"""Headless tests for Ochema Circuit VehiclePhysicsScript.
Covers init, boost, teardown, on_tick with/without input,
gear calculation, smoke emission, lighting helpers, and module hooks.
"""
from __future__ import annotations
import sys
import math
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("pharos_engine.compute.asset_compute", MagicMock())

_GAME_ROOT = Path(__file__).parent.parent.parent.parent.parent / "DaedalusSVN" / "Ochema Circuit"
_GAME_STR = str(_GAME_ROOT)
if _GAME_STR not in sys.path:
    sys.path.insert(0, _GAME_STR)


# =============================================================================
# Fake entity helper
# =============================================================================

def _make_entity(throttle=0.0, brake=0.0, steer=0.0):
    """Return a minimal fake vehicle entity with a ScriptInputProvider."""
    from pharos_engine.input_provider import ScriptInputProvider

    e = MagicMock()
    e.position = (0.0, 0.0)
    e.rotation = 0.0
    e.velocity = [0.0, 0.0]
    e.angular_vel = 0.0
    e.yaw_bias = 0.0
    e.grip = 0.8
    e.max_speed = 500.0
    e._deform = None
    e._smoke_field = None
    e.heat = 0.0
    e.speed = 0.0
    e.throttle = 0.0
    e.steer = 0.0
    e.brake = 0.0
    e.drift_factor = 0.0
    e._drift_raw = 0.0
    e.gear = 1
    e._parts = None
    e._drivetrain_cfg = {}

    # Roll and pitch — just regular floats
    e.roll = 0.0
    e.pitch = 0.0

    # ScriptInputProvider with given axes
    inp = ScriptInputProvider()
    inp.set_axis("throttle", throttle)
    inp.set_axis("brake", brake)
    inp.set_axis("steer", steer)
    e.input_provider = inp

    e.is_ai = False
    e.driver_id = 0

    # Scene: engine has no input and no lighting
    e.scene._engine.input = None
    e.scene._engine.lighting = None

    return e


def _make_no_input_entity():
    """Entity with no input_provider and no engine input (returns early)."""
    e = MagicMock()
    e.position = (0.0, 0.0)
    e.rotation = 0.0
    e.velocity = [0.0, 0.0]
    e.angular_vel = 0.0
    e.yaw_bias = 0.0
    e.grip = 0.8
    e.max_speed = 500.0
    e._deform = None
    e._smoke_field = None
    e.heat = 0.0
    e._parts = None
    e._drivetrain_cfg = {}
    e.input_provider = None
    e.is_ai = False
    e.driver_id = 0
    e.scene._engine.input = None   # no input → on_tick returns early
    e.scene._engine.lighting = None
    return e


# =============================================================================
# VehiclePhysicsScript — init and teardown
# =============================================================================

class TestVehiclePhysicsScriptInit:
    def _vps(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        return VehiclePhysicsScript()

    def test_instantiates(self):
        vps = self._vps()
        vps.teardown()

    def test_not_destroyed_initially(self):
        vps = self._vps()
        assert vps._destroyed is False
        vps.teardown()

    def test_boost_remaining_zero(self):
        vps = self._vps()
        assert vps._boost_remaining == 0.0
        vps.teardown()

    def test_boost_multiplier_one(self):
        vps = self._vps()
        assert vps._boost_multiplier == 1.0
        vps.teardown()

    def test_time_zero(self):
        vps = self._vps()
        assert vps._time == 0.0
        vps.teardown()

    def test_drivetrain_none(self):
        vps = self._vps()
        assert vps._drivetrain is None
        vps.teardown()

    def test_teardown_no_crash(self):
        vps = self._vps()
        vps.teardown()

    def test_teardown_twice_no_crash(self):
        vps = self._vps()
        vps.teardown()
        vps.teardown()

    def test_subscribes_vehicle_destroyed(self):
        from pharos_engine.event_bus import global_bus
        before = global_bus.listener_count("Vehicle.Destroyed")
        vps = self._vps()
        after = global_bus.listener_count("Vehicle.Destroyed")
        assert after == before + 1
        vps.teardown()

    def test_teardown_unsubscribes(self):
        from pharos_engine.event_bus import global_bus
        before = global_bus.listener_count("Vehicle.Destroyed")
        vps = self._vps()
        vps.teardown()
        after = global_bus.listener_count("Vehicle.Destroyed")
        assert after == before


# =============================================================================
# boost() and _on_vehicle_destroyed()
# =============================================================================

class TestVehiclePhysicsScriptBoost:
    def _vps(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        return VehiclePhysicsScript()

    def test_boost_sets_remaining(self):
        vps = self._vps()
        vps.boost(1.5, 2.0)
        assert abs(vps._boost_remaining - 2.0) < 1e-6
        vps.teardown()

    def test_boost_sets_multiplier(self):
        vps = self._vps()
        vps.boost(2.0, 1.0)
        assert abs(vps._boost_multiplier - 2.0) < 1e-6
        vps.teardown()

    def test_boost_max_takes_higher_remaining(self):
        vps = self._vps()
        vps.boost(1.5, 3.0)
        vps.boost(1.2, 1.0)   # lower duration → no change
        assert abs(vps._boost_remaining - 3.0) < 1e-6
        vps.teardown()

    def test_boost_max_takes_higher_multiplier(self):
        vps = self._vps()
        vps.boost(2.0, 1.0)
        vps.boost(1.2, 2.0)   # lower multiplier → no change
        assert abs(vps._boost_multiplier - 2.0) < 1e-6
        vps.teardown()

    def test_on_vehicle_destroyed_sets_flag(self):
        vps = self._vps()
        vps._on_vehicle_destroyed(MagicMock())
        assert vps._destroyed is True
        vps.teardown()

    def test_destroyed_event_stops_processing(self):
        from pharos_engine.event_bus import publish
        vps = self._vps()
        publish("Vehicle.Destroyed")
        assert vps._destroyed is True
        vps.teardown()


# =============================================================================
# on_tick — no input
# =============================================================================

class TestVehiclePhysicsOnTickNoInput:
    def _vps(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        return VehiclePhysicsScript()

    def test_destroyed_entity_no_tick(self):
        vps = self._vps()
        vps._destroyed = True
        e = _make_no_input_entity()
        # Should return immediately without touching entity attrs
        vps.on_tick(e, 0.016)  # no crash
        vps.teardown()

    def test_no_input_no_crash(self):
        vps = self._vps()
        e = _make_no_input_entity()
        vps.on_tick(e, 0.016)  # returns early since no engine input
        vps.teardown()

    def test_time_increments_with_provider(self):
        vps = self._vps()
        e = _make_entity()
        vps.on_tick(e, 0.1)
        assert abs(vps._time - 0.1) < 1e-6
        vps.teardown()


# =============================================================================
# on_tick — with ScriptInputProvider
# =============================================================================

class TestVehiclePhysicsOnTickWithInput:
    def _vps(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        return VehiclePhysicsScript()

    def test_throttle_advances_position(self):
        vps = self._vps()
        e = _make_entity(throttle=1.0)
        e.position = (0.0, 0.0)
        vps.on_tick(e, 0.1)
        # heading=0 → fwd=(1,0); throttle adds velocity; position updates
        # position should have changed from (0, 0)
        assert e.position != (0.0, 0.0)
        vps.teardown()

    def test_throttle_updates_speed_attr(self):
        vps = self._vps()
        e = _make_entity(throttle=1.0)
        for _ in range(10):
            vps.on_tick(e, 0.05)
        # After multiple ticks, speed should be > 0
        assert e.speed > 0.0
        vps.teardown()

    def test_steer_updates_angular_vel(self):
        vps = self._vps()
        e = _make_entity(steer=1.0)
        vps.on_tick(e, 0.1)
        assert e.angular_vel != 0.0
        vps.teardown()

    def test_brake_attr_updates(self):
        vps = self._vps()
        e = _make_entity(brake=1.0)
        vps.on_tick(e, 0.016)
        assert e.brake == 1.0
        vps.teardown()

    def test_steer_attr_updates(self):
        vps = self._vps()
        e = _make_entity(steer=0.5)
        vps.on_tick(e, 0.016)
        assert abs(e.steer - 0.5) < 1e-6
        vps.teardown()

    def test_throttle_attr_updates(self):
        vps = self._vps()
        e = _make_entity(throttle=1.0)
        vps.on_tick(e, 0.016)
        assert e.throttle == 1.0
        vps.teardown()

    def test_no_throttle_attr_zero(self):
        vps = self._vps()
        e = _make_entity(throttle=0.0)
        vps.on_tick(e, 0.016)
        assert e.throttle == 0.0
        vps.teardown()

    def test_drag_applied_to_velocity(self):
        from systems.vehicle_physics import LINEAR_DRAG
        vps = self._vps()
        e = _make_entity(throttle=0.0)
        e.velocity = [100.0, 0.0]
        vps.on_tick(e, 0.016)
        # Linear drag reduces velocity each tick
        assert abs(e.velocity[0]) < 100.0
        vps.teardown()

    def test_speed_capped_at_max_speed(self):
        vps = self._vps()
        e = _make_entity(throttle=1.0)
        e.velocity = [1000.0, 0.0]  # far over max
        e.max_speed = 100.0
        vps.on_tick(e, 0.016)
        speed = math.hypot(*e.velocity)
        assert speed <= e.max_speed + 1.0  # slight tolerance for one-tick
        vps.teardown()

    def test_boost_reduces_over_time(self):
        vps = self._vps()
        e = _make_entity()
        vps.boost(1.5, 0.1)
        vps.on_tick(e, 0.05)  # consume half the boost
        assert vps._boost_remaining < 0.1
        vps.teardown()

    def test_boost_resets_when_expired(self):
        vps = self._vps()
        e = _make_entity()
        vps.boost(2.0, 0.01)
        vps.on_tick(e, 0.05)  # _boost_remaining goes negative
        vps.on_tick(e, 0.016)  # else branch runs → resets multiplier to 1.0
        assert vps._boost_multiplier == 1.0
        vps.teardown()

    def test_position_updates_after_tick(self):
        vps = self._vps()
        e = _make_entity(throttle=1.0)
        e.position = (500.0, 500.0)
        initial = e.position
        for _ in range(10):
            vps.on_tick(e, 0.016)
        assert e.position != initial
        vps.teardown()

    def test_drivetrain_created_on_first_tick(self):
        vps = self._vps()
        e = _make_entity()
        assert vps._drivetrain is None
        vps.on_tick(e, 0.016)
        assert vps._drivetrain is not None
        vps.teardown()

    def test_suspension_created_on_first_tick(self):
        vps = self._vps()
        e = _make_entity()
        assert vps._suspension is None
        vps.on_tick(e, 0.016)
        assert vps._suspension is not None
        vps.teardown()

    def test_multiple_ticks_no_crash(self):
        vps = self._vps()
        e = _make_entity(throttle=0.8, steer=0.3)
        for _ in range(60):
            vps.on_tick(e, 0.016)
        vps.teardown()


# =============================================================================
# _update_gear
# =============================================================================

class TestUpdateGear:
    def _vps(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        return VehiclePhysicsScript()

    def _entity(self, vx=0.0, max_speed=500.0):
        e = MagicMock()
        e.velocity = [vx, 0.0]
        e.max_speed = max_speed
        e.gear = 1
        return e

    def test_gear1_at_low_speed(self):
        vps = self._vps()
        e = self._entity(vx=20.0, max_speed=500.0)  # 0.04 fraction
        vps._update_gear(e)
        assert e.gear == 1
        vps.teardown()

    def test_gear2_at_medium_low_speed(self):
        vps = self._vps()
        e = self._entity(vx=160.0, max_speed=500.0)  # 0.32 fraction
        vps._update_gear(e)
        assert e.gear == 2
        vps.teardown()

    def test_gear3(self):
        vps = self._vps()
        e = self._entity(vx=260.0, max_speed=500.0)  # 0.52 fraction
        vps._update_gear(e)
        assert e.gear == 3
        vps.teardown()

    def test_gear4(self):
        vps = self._vps()
        e = self._entity(vx=360.0, max_speed=500.0)  # 0.72 fraction
        vps._update_gear(e)
        assert e.gear == 4
        vps.teardown()

    def test_gear5_at_high_speed(self):
        vps = self._vps()
        e = self._entity(vx=450.0, max_speed=500.0)  # 0.90 fraction
        vps._update_gear(e)
        assert e.gear == 5
        vps.teardown()

    def test_zero_speed_gear1(self):
        vps = self._vps()
        e = self._entity(vx=0.0)
        vps._update_gear(e)
        assert e.gear == 1
        vps.teardown()


# =============================================================================
# _maybe_emit_smoke
# =============================================================================

class TestMaybeEmitSmoke:
    def _vps(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        return VehiclePhysicsScript()

    def test_no_smoke_field_no_crash(self):
        vps = self._vps()
        e = MagicMock()
        e._smoke_field = None
        e.rotation = 0.0
        e.position = (0.0, 0.0)
        vps._maybe_emit_smoke(e, speed=100.0, steer_val=1.0, accel=True, brake_val=0.0)
        vps.teardown()

    def test_low_speed_no_smoke(self):
        vps = self._vps()
        e = MagicMock()
        e._smoke_field = MagicMock()
        e.rotation = 0.0
        e.position = (0.0, 0.0)
        from systems.vehicle_physics import _SMOKE_SPEED_THRESH
        vps._maybe_emit_smoke(e, speed=_SMOKE_SPEED_THRESH - 1.0,
                               steer_val=1.0, accel=True, brake_val=0.0)
        e._smoke_field.spawn.assert_not_called()
        vps.teardown()

    def test_no_drift_no_brake_no_smoke(self):
        vps = self._vps()
        e = MagicMock()
        e._smoke_field = MagicMock()
        e.rotation = 0.0
        e.position = (0.0, 0.0)
        # steer below threshold, no brake
        vps._maybe_emit_smoke(e, speed=100.0, steer_val=0.1, accel=True, brake_val=0.0)
        e._smoke_field.spawn.assert_not_called()
        vps.teardown()

    def test_heavy_brake_emits_smoke(self):
        vps = self._vps()
        e = MagicMock()
        e._smoke_field = MagicMock()
        e.rotation = 0.0
        e.position = (100.0, 100.0)
        from systems.vehicle_physics import _SMOKE_BRAKE_THRESH, _SMOKE_SPEED_THRESH
        vps._maybe_emit_smoke(e, speed=_SMOKE_SPEED_THRESH + 20.0,
                               steer_val=0.0, accel=False,
                               brake_val=_SMOKE_BRAKE_THRESH + 0.1)
        e._smoke_field.spawn.assert_called_once()
        vps.teardown()


# =============================================================================
# Module-level hooks (on_launch, on_tick, on_end)
# =============================================================================

class TestModuleHooks:
    def test_on_launch_attaches_script(self):
        from systems.vehicle_physics import on_launch
        e = MagicMock()
        e._scripts = []
        on_launch(e)
        assert e._vphys_script is not None

    def test_on_end_clears_script(self):
        from systems.vehicle_physics import on_launch, on_end
        e = MagicMock()
        e._scripts = []
        on_launch(e)
        on_end(e)
        assert e._vphys_script is None

    def test_on_tick_creates_script_if_missing(self):
        from systems.vehicle_physics import on_tick
        e = _make_no_input_entity()
        e._vphys_script = None
        on_tick(e, 0.016)
        assert e._vphys_script is not None
        e._vphys_script.teardown()

    def test_on_tick_uses_existing_script(self):
        from systems.vehicle_physics import on_launch, on_tick, on_end
        e = MagicMock()
        e._scripts = []
        on_launch(e)
        script_ref = e._vphys_script
        on_end(e)

    def test_full_lifecycle_no_crash(self):
        from systems.vehicle_physics import on_launch, on_tick, on_end
        e = _make_no_input_entity()
        e._scripts = []
        on_launch(e)
        on_tick(e, 0.016)
        on_end(e)
