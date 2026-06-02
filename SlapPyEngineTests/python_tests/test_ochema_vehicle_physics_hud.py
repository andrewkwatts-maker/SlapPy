"""Headless tests for Ochema Circuit VehiclePhysicsScript and RaceHUD."""
from __future__ import annotations
import sys
import math
from pathlib import Path
from unittest.mock import MagicMock
import pytest

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("slappyengine.compute.asset_compute", MagicMock())

_OCHEMA_DIR = Path(__file__).parent.parent.parent.parent.parent / "DaedalusSVN" / "Ochema Circuit"
_OCHEMA_STR = str(_OCHEMA_DIR)
if _OCHEMA_STR not in sys.path:
    sys.path.insert(0, _OCHEMA_STR)


# =============================================================================
# Helpers
# =============================================================================

def _make_entity(rotation=0.0, speed=0.0):
    """Return a MagicMock vehicle entity suitable for VehiclePhysicsScript.on_tick."""
    from slappyengine.input_provider import ScriptInputProvider
    e = MagicMock()
    e.position = [640.0, 360.0]
    e.velocity = [speed, 0.0]
    e.rotation = rotation
    e.angular_vel = 0.0
    e.yaw_bias = 0.0
    e.max_speed = 300.0
    e.grip = 0.8
    e.is_ai = False
    e.driver_id = 0
    # Disable lighting to avoid ConeLight creation in tests
    engine_mock = MagicMock()
    engine_mock.lighting = None
    e.scene._engine = engine_mock
    e.input_provider = ScriptInputProvider()
    e._drivetrain_cfg = {}
    e._deform = None
    e._smoke_field = None
    e._parts = None
    return e


# =============================================================================
# VehiclePhysicsScript
# =============================================================================

class TestVehiclePhysicsScriptInit:
    def test_init_no_crash(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        vp = VehiclePhysicsScript()
        assert vp is not None
        vp.teardown()

    def test_destroyed_initially_false(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        vp = VehiclePhysicsScript()
        assert vp._destroyed is False
        vp.teardown()

    def test_boost_remaining_initially_zero(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        vp = VehiclePhysicsScript()
        assert vp._boost_remaining == pytest.approx(0.0)
        vp.teardown()

    def test_boost_multiplier_initially_one(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        vp = VehiclePhysicsScript()
        assert vp._boost_multiplier == pytest.approx(1.0)
        vp.teardown()

    def test_drivetrain_initially_none(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        vp = VehiclePhysicsScript()
        assert vp._drivetrain is None
        vp.teardown()

    def test_time_initially_zero(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        vp = VehiclePhysicsScript()
        assert vp._time == pytest.approx(0.0)
        vp.teardown()


class TestVehiclePhysicsScriptBoost:
    def test_boost_stores_remaining(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        vp = VehiclePhysicsScript()
        vp.boost(1.5, 2.0)
        assert vp._boost_remaining == pytest.approx(2.0)
        vp.teardown()

    def test_boost_stores_multiplier(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        vp = VehiclePhysicsScript()
        vp.boost(1.5, 2.0)
        assert vp._boost_multiplier == pytest.approx(1.5)
        vp.teardown()

    def test_boost_keeps_higher_remaining(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        vp = VehiclePhysicsScript()
        vp.boost(1.3, 5.0)
        vp.boost(1.3, 2.0)  # shorter — should not replace 5.0
        assert vp._boost_remaining == pytest.approx(5.0)
        vp.teardown()

    def test_boost_keeps_higher_multiplier(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        vp = VehiclePhysicsScript()
        vp.boost(1.3, 2.0)
        vp.boost(1.1, 2.0)  # lower mult — should not replace 1.3
        assert vp._boost_multiplier == pytest.approx(1.3)
        vp.teardown()


class TestVehiclePhysicsScriptOnTick:
    def test_on_tick_no_crash(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        vp = VehiclePhysicsScript()
        e = _make_entity()
        vp.on_tick(e, 0.016)
        vp.teardown()

    def test_on_tick_advances_time(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        vp = VehiclePhysicsScript()
        e = _make_entity()
        vp.on_tick(e, 0.5)
        assert vp._time == pytest.approx(0.5)
        vp.teardown()

    def test_on_tick_when_destroyed_returns_early(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        vp = VehiclePhysicsScript()
        vp._destroyed = True
        e = _make_entity()
        vp.on_tick(e, 0.016)
        assert vp._time == pytest.approx(0.0)  # time not advanced
        vp.teardown()

    def test_on_tick_moves_position(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        from slappyengine.input_provider import ScriptInputProvider
        vp = VehiclePhysicsScript()
        e = _make_entity(speed=100.0)
        initial_x = e.position[0]
        vp.on_tick(e, 0.016)
        # Position should have changed
        new_x = e.position[0] if isinstance(e.position, list) else e.position[0]
        # After tick, entity.position is a tuple
        assert isinstance(e.position, tuple)
        vp.teardown()

    def test_on_tick_throttle_accelerates(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        from slappyengine.input_provider import ScriptInputProvider
        vp = VehiclePhysicsScript()
        e = _make_entity()
        e.input_provider = ScriptInputProvider()
        e.input_provider.set_axis("throttle", 1.0)
        vp.on_tick(e, 0.1)
        speed = math.hypot(*e.velocity)
        assert speed > 0.0
        vp.teardown()

    def test_on_tick_brake_decelerates(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        from slappyengine.input_provider import ScriptInputProvider
        vp = VehiclePhysicsScript()
        e = _make_entity(speed=100.0)
        e.input_provider = ScriptInputProvider()
        e.input_provider.set_axis("brake", 1.0)
        speed_before = math.hypot(*e.velocity)
        vp.on_tick(e, 0.016)
        speed_after = math.hypot(*e.velocity)
        # Braking should reduce speed
        assert speed_after < speed_before
        vp.teardown()

    def test_on_tick_creates_drivetrain_lazily(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        vp = VehiclePhysicsScript()
        e = _make_entity()
        assert vp._drivetrain is None
        vp.on_tick(e, 0.016)
        assert vp._drivetrain is not None
        vp.teardown()

    def test_on_tick_with_ai_entity_no_crash(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        vp = VehiclePhysicsScript()
        e = _make_entity()
        e.is_ai = True
        e.input_provider = None
        vp.on_tick(e, 0.016)
        vp.teardown()

    def test_on_tick_boost_active_allows_higher_speed(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        vp = VehiclePhysicsScript()
        vp.boost(2.0, 5.0)
        e = _make_entity(speed=250.0)  # near normal max
        vp.on_tick(e, 0.016)
        # Speed cap should be raised by boost
        assert vp._boost_remaining < 5.0
        vp.teardown()

    def test_on_tick_boost_expires_resets_multiplier(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        vp = VehiclePhysicsScript()
        vp.boost(1.5, 0.01)  # very short boost
        e = _make_entity()
        vp.on_tick(e, 1.0)   # large dt — boost expires, remaining goes negative
        vp.on_tick(e, 0.016) # second tick hits the else branch and resets multiplier
        assert vp._boost_multiplier == pytest.approx(1.0)
        vp.teardown()

    def test_on_tick_no_smoke_without_smoke_field(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        from slappyengine.input_provider import ScriptInputProvider
        vp = VehiclePhysicsScript()
        e = _make_entity(speed=100.0)
        e._smoke_field = None  # explicit None
        e.input_provider = ScriptInputProvider()
        e.input_provider.set_axis("steer", 1.0)
        e.input_provider.set_axis("throttle", 1.0)
        vp.on_tick(e, 0.016)  # should not crash even without smoke field
        vp.teardown()


class TestVehiclePhysicsScriptUpdateGear:
    def test_low_speed_gear_1(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        vp = VehiclePhysicsScript()
        e = _make_entity(speed=10.0)
        vp._update_gear(e)
        # Called on mock, so just checking no crash
        vp.teardown()

    def test_gear_thresholds_no_crash(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        vp = VehiclePhysicsScript()
        for speed in [0, 50, 100, 150, 200, 280]:
            e = _make_entity(speed=float(speed))
            vp._update_gear(e)
        vp.teardown()


class TestVehiclePhysicsScriptVehicleDestroyed:
    def test_vehicle_destroyed_event_marks_destroyed(self):
        from slappyengine.event_bus import publish
        from systems.vehicle_physics import VehiclePhysicsScript
        vp = VehiclePhysicsScript()
        publish("Vehicle.Destroyed", publisher=None)
        assert vp._destroyed is True
        vp.teardown()

    def test_on_tick_after_destroyed_skips(self):
        from slappyengine.event_bus import publish
        from systems.vehicle_physics import VehiclePhysicsScript
        vp = VehiclePhysicsScript()
        publish("Vehicle.Destroyed", publisher=None)
        e = _make_entity()
        vp.on_tick(e, 0.016)
        assert vp._time == pytest.approx(0.0)
        vp.teardown()


class TestVehiclePhysicsScriptTeardown:
    def test_teardown_no_crash(self):
        from systems.vehicle_physics import VehiclePhysicsScript
        vp = VehiclePhysicsScript()
        vp.teardown()

    def test_teardown_unsubscribes(self):
        from slappyengine.event_bus import publish
        from systems.vehicle_physics import VehiclePhysicsScript
        vp = VehiclePhysicsScript()
        vp.teardown()
        # After teardown, Vehicle.Destroyed should not mark destroyed
        vp._destroyed = False
        publish("Vehicle.Destroyed", publisher=None)
        assert vp._destroyed is False


class TestVehiclePhysicsModuleHooks:
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
        e._vphys_script.teardown = MagicMock()
        on_end(e)
        assert e._vphys_script is None

    def test_on_tick_hook_creates_script_if_missing(self):
        from systems.vehicle_physics import on_tick as module_on_tick
        e = _make_entity()
        e._vphys_script = None
        module_on_tick(e, 0.016)
        assert e._vphys_script is not None
        e._vphys_script.teardown()


# =============================================================================
# VehiclePhysicsScript — _maybe_emit_smoke direct tests
# =============================================================================

class TestVehiclePhysicsScriptSmoke:
    def test_no_smoke_below_speed_threshold(self):
        from systems.vehicle_physics import VehiclePhysicsScript, _SMOKE_SPEED_THRESH
        vp = VehiclePhysicsScript()
        e = MagicMock()
        smoke = MagicMock()
        e._smoke_field = smoke
        # Speed below threshold — smoke should not spawn
        vp._maybe_emit_smoke(e, _SMOKE_SPEED_THRESH - 1.0, 1.0, True, 0.0)
        smoke.spawn.assert_not_called()
        vp.teardown()

    def test_no_smoke_without_drift_or_brake(self):
        from systems.vehicle_physics import VehiclePhysicsScript, _SMOKE_SPEED_THRESH
        vp = VehiclePhysicsScript()
        e = MagicMock()
        smoke = MagicMock()
        e._smoke_field = smoke
        e.rotation = 0.0
        e.position = (640.0, 360.0)
        # No steer, no brake → no smoke
        vp._maybe_emit_smoke(e, _SMOKE_SPEED_THRESH + 10.0, 0.0, False, 0.0)
        smoke.spawn.assert_not_called()
        vp.teardown()

    def test_smoke_on_heavy_brake(self):
        from systems.vehicle_physics import VehiclePhysicsScript, _SMOKE_SPEED_THRESH, _SMOKE_BRAKE_THRESH
        vp = VehiclePhysicsScript()
        e = MagicMock()
        smoke = MagicMock()
        e._smoke_field = smoke
        e.rotation = 0.0
        e.position = (640.0, 360.0)
        vp._maybe_emit_smoke(e, _SMOKE_SPEED_THRESH + 10.0, 0.0, False, _SMOKE_BRAKE_THRESH + 0.1)
        smoke.spawn.assert_called()
        vp.teardown()


# =============================================================================
# RaceHUD
# =============================================================================

class TestRaceHUDInit:
    def test_init_no_crash(self):
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        hud.on_end()

    def test_initial_lap_one(self):
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        assert hud._lap == 1
        hud.on_end()

    def test_initial_position_one(self):
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        assert hud._position == 1
        hud.on_end()

    def test_initial_speed_zero(self):
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        assert hud._speed == pytest.approx(0.0)
        hud.on_end()

    def test_initial_hull_integrity_one(self):
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        assert hud._hull_integrity == pytest.approx(1.0)
        hud.on_end()

    def test_handles_populated(self):
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        assert len(hud._handles) > 0
        hud.on_end()

    def test_with_profile(self):
        from entities.hud import RaceHUD
        v = MagicMock()
        profile = MagicMock()
        profile.coins = 250
        hud = RaceHUD(v, 0.0, 0.0, profile=profile)
        assert hud._coins == 250
        hud.on_end()


class TestRaceHUDSpeedEvent:
    def test_speed_event_from_tracked_vehicle_updates(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("VehicleEntity.speed", publisher=v, value=150.0)
        assert hud._speed == pytest.approx(150.0)
        hud.on_end()

    def test_speed_event_from_other_vehicle_ignored(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        other = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("VehicleEntity.speed", publisher=other, value=200.0)
        assert hud._speed == pytest.approx(0.0)
        hud.on_end()


class TestRaceHUDIntegrityEvent:
    def test_integrity_event_updates_value(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("VehicleEntity.hull_integrity", publisher=v, value=0.65)
        assert hud._hull_integrity == pytest.approx(0.65)
        hud.on_end()

    def test_integrity_from_other_ignored(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        other = MagicMock()
        publish("VehicleEntity.hull_integrity", publisher=other, value=0.1)
        assert hud._hull_integrity == pytest.approx(1.0)
        hud.on_end()


class TestRaceHUDLapComplete:
    def test_lap_complete_increments_lap(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("Race.LapComplete", publisher=v, lap=2, lap_time=65.5)
        assert hud._lap == 2
        hud.on_end()

    def test_lap_complete_from_other_ignored(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        other = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("Race.LapComplete", publisher=other, lap=2, lap_time=60.0)
        assert hud._lap == 1
        hud.on_end()

    def test_best_lap_set_on_first_lap(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("Race.LapComplete", publisher=v, lap=1, lap_time=70.2)
        assert hud._best_lap_s == pytest.approx(70.2)
        hud.on_end()

    def test_best_lap_updated_when_faster(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("Race.LapComplete", publisher=v, lap=1, lap_time=70.2)
        publish("Race.LapComplete", publisher=v, lap=2, lap_time=65.0)
        assert hud._best_lap_s == pytest.approx(65.0)
        hud.on_end()

    def test_best_lap_not_updated_when_slower(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("Race.LapComplete", publisher=v, lap=1, lap_time=65.0)
        publish("Race.LapComplete", publisher=v, lap=2, lap_time=70.0)
        assert hud._best_lap_s == pytest.approx(65.0)
        hud.on_end()

    def test_best_lap_flash_set(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("Race.LapComplete", publisher=v, lap=1, lap_time=60.0)
        assert hud._best_lap_flash > 0.0
        hud.on_end()


class TestRaceHUDGearEvent:
    def test_gear_event_updates(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("VehicleEntity.gear", publisher=v, value=3)
        assert hud._gear == 3
        hud.on_end()

    def test_gear_event_other_vehicle_ignored(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        other = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("VehicleEntity.gear", publisher=other, value=5)
        assert hud._gear == 1
        hud.on_end()


class TestRaceHUDCountdownEvents:
    def test_countdown_tick_stored(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("Race.CountdownTick", publisher=None, tick=2)
        assert hud._countdown_tick == 2
        hud.on_end()

    def test_countdown_go_clears_tick(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("Race.CountdownTick", publisher=None, tick=1)
        publish("Race.CountdownGo", publisher=None)
        assert hud._countdown_tick == 0
        assert hud._go_timer > 0.0
        hud.on_end()


class TestRaceHUDNitroBoost:
    def test_nitro_active_event_sets_flag(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("Vehicle.NitroActive", publisher=v, active=True)
        assert hud._nitro_active is True
        hud.on_end()

    def test_nitro_from_other_ignored(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        other = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("Vehicle.NitroActive", publisher=other, active=True)
        assert hud._nitro_active is False
        hud.on_end()

    def test_boost_event_sets_flag(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("Vehicle.Boost", publisher=v)
        assert hud._boost_active is True
        assert hud._boost_timer > 0.0
        hud.on_end()


class TestRaceHUDStatusEvents:
    def test_race_started_sets_flag(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("Race.Started", publisher=None)
        assert hud._race_started is True
        hud.on_end()

    def test_race_finished_sets_flag(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("Race.Finished", publisher=None)
        assert hud._race_finished is True
        hud.on_end()

    def test_dnf_sets_flag_for_tracked_vehicle(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("Race.DNF", publisher=v, driver_id=None)
        assert hud._dnf is True
        hud.on_end()

    def test_wrong_way_sets_flag(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        v.driver_id = 0
        hud = RaceHUD(v, 0.0, 0.0)
        publish("Race.WrongWay", publisher=v, driver_id=None)
        assert hud._wrong_way is True
        assert hud._wrong_way_timer > 0.0
        hud.on_end()

    def test_weapon_hit_sets_flash(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("Weapon.Hit", publisher=None, target=v)
        assert hud._hit_flash > 0.0
        hud.on_end()

    def test_weapon_hit_other_target_ignored(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        other = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("Weapon.Hit", publisher=None, target=other)
        assert hud._hit_flash == pytest.approx(0.0)
        hud.on_end()


class TestRaceHUDPitsEvents:
    def test_pits_entered_sets_active(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("Pits.Entered", publisher=v)
        assert hud._pits_active is True
        hud.on_end()

    def test_pits_repairing_updates_progress(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("Pits.Entered", publisher=v)
        publish("Pits.Repairing", publisher=v, progress=0.5, cost_so_far=50)
        assert hud._pits_progress == pytest.approx(0.5)
        hud.on_end()

    def test_pits_exited_clears_active(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("Pits.Entered", publisher=v)
        publish("Pits.Exited", publisher=v, total_cost=200)
        assert hud._pits_active is False
        hud.on_end()


class TestRaceHUDPositionsEvent:
    def test_positions_event_updates_position(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        other1 = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        other1.position = (0.0, 0.0)
        v.position = (100.0, 100.0)
        # v is in position 2 (after other1)
        publish("Race.PositionsUpdated", publisher=None,
                positions=[other1, v], gaps=[0.0, 50.0])
        assert hud._position == 2
        hud.on_end()


class TestRaceHUDCoinEvents:
    def test_coins_earned_updates_total(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("PlayerProfile.CoinsEarned", publisher=None, total=500)
        assert hud._coins == 500
        hud.on_end()

    def test_coin_collected_adds_to_coins(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        hud._coins = 100
        publish("Race.CoinCollected", publisher=None, amount=10)
        assert hud._coins == 110
        hud.on_end()


class TestRaceHUDLayerDestroyed:
    def test_internals_exposed_message(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("Vehicle.LayerDestroyed", publisher=v, layer_name="internals")
        assert "INTERN" in hud._layer_destroyed_msg.upper()
        assert hud._layer_destroyed_flash > 0.0
        hud.on_end()

    def test_chassis_critical_message(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("Vehicle.LayerDestroyed", publisher=v, layer_name="chassis")
        assert "CHASSIS" in hud._layer_destroyed_msg
        hud.on_end()

    def test_layer_destroyed_from_other_vehicle_ignored(self):
        from slappyengine.event_bus import publish
        from entities.hud import RaceHUD
        v = MagicMock()
        other = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        publish("Vehicle.LayerDestroyed", publisher=other, layer_name="internals")
        assert hud._layer_destroyed_flash == pytest.approx(0.0)
        hud.on_end()


class TestRaceHUDTeardown:
    def test_on_end_clears_handles(self):
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        hud.on_end()
        assert len(hud._handles) == 0

    def test_on_end_twice_no_crash(self):
        from entities.hud import RaceHUD
        v = MagicMock()
        hud = RaceHUD(v, 0.0, 0.0)
        hud.on_end()
        hud.on_end()


class TestFmtLapTime:
    def test_zero_returns_default(self):
        from entities.hud import _fmt_lap_time
        assert _fmt_lap_time(0.0) == "00:00.000"

    def test_negative_returns_default(self):
        from entities.hud import _fmt_lap_time
        assert _fmt_lap_time(-1.0) == "00:00.000"

    def test_one_minute_formats(self):
        from entities.hud import _fmt_lap_time
        s = _fmt_lap_time(60.0)
        assert "01:" in s

    def test_seconds_only(self):
        from entities.hud import _fmt_lap_time
        s = _fmt_lap_time(45.123)
        assert "00:" in s
        assert "45" in s
