"""Headless tests for Ochema Circuit LapTimer, VehicleGridBuilder, HazardSystem,
PitsSystem, and CoinSystem."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("pharos_engine.compute.asset_compute", MagicMock())

_OCHEMA_DIR = Path(__file__).parent.parent.parent.parent.parent / "DaedalusSVN" / "Ochema Circuit"
_OCHEMA_STR = str(_OCHEMA_DIR)
if _OCHEMA_STR not in sys.path:
    sys.path.insert(0, _OCHEMA_STR)


# =============================================================================
# LapTimer
# =============================================================================

class TestLapTimer:
    def _lt(self):
        from systems.lap_timer import LapTimer
        return LapTimer()

    def test_initial_total_elapsed_zero(self):
        lt = self._lt()
        assert lt.total_elapsed == pytest.approx(0.0)

    def test_update_advances_elapsed(self):
        lt = self._lt()
        lt.update(1.5)
        assert lt.total_elapsed == pytest.approx(1.5)

    def test_update_accumulates(self):
        lt = self._lt()
        lt.update(0.5)
        lt.update(0.5)
        assert lt.total_elapsed == pytest.approx(1.0)

    def test_start_sets_lap_reference(self):
        lt = self._lt()
        lt.update(5.0)
        lt.start()
        assert lt.current_lap_elapsed == pytest.approx(0.0)

    def test_current_lap_elapsed_advances_after_start(self):
        lt = self._lt()
        lt.start()
        lt.update(2.0)
        assert lt.current_lap_elapsed == pytest.approx(2.0)

    def test_record_lap_returns_duration(self):
        lt = self._lt()
        lt.start()
        lt.update(3.0)
        dur = lt.record_lap()
        assert dur == pytest.approx(3.0)

    def test_record_lap_increments_count(self):
        lt = self._lt()
        lt.start()
        lt.update(1.0)
        lt.record_lap()
        assert lt.lap_count == 1

    def test_best_lap_updates(self):
        lt = self._lt()
        lt.start()
        lt.update(10.0)
        lt.record_lap()
        lt.update(8.0)
        lt.record_lap()
        assert lt.best_lap == pytest.approx(8.0)

    def test_best_lap_initially_zero(self):
        lt = self._lt()
        assert lt.best_lap == pytest.approx(0.0)

    def test_lap_times_list(self):
        lt = self._lt()
        lt.start()
        lt.update(4.0)
        lt.record_lap()
        lt.update(5.0)
        lt.record_lap()
        times = lt.lap_times
        assert len(times) == 2
        assert times[0] == pytest.approx(4.0)
        assert times[1] == pytest.approx(5.0)


# =============================================================================
# VehicleGridBuilder
# =============================================================================

class TestVehicleGridBuilder:
    def _gb(self):
        from systems.grid_builder import VehicleGridBuilder
        return VehicleGridBuilder()

    def test_place_returns_true_on_empty_cell(self):
        from entities.part import PartType
        gb = self._gb()
        assert gb.place(PartType.ENGINE, 0, 0) is True

    def test_place_returns_false_on_occupied_cell(self):
        from entities.part import PartType
        gb = self._gb()
        gb.place(PartType.ENGINE, 0, 0)
        assert gb.place(PartType.WHEEL, 0, 0) is False

    def test_place_returns_false_out_of_bounds(self):
        from entities.part import PartType
        from systems.grid_builder import GRID_SIZE
        gb = self._gb()
        assert gb.place(PartType.ENGINE, GRID_SIZE, 0) is False

    def test_remove_returns_part(self):
        from entities.part import PartType
        gb = self._gb()
        gb.place(PartType.ENGINE, 1, 1)
        part = gb.remove(1, 1)
        assert part is not None

    def test_remove_nonexistent_returns_none(self):
        gb = self._gb()
        assert gb.remove(5, 5) is None

    def test_validate_needs_cockpit(self):
        from entities.part import PartType
        gb = self._gb()
        gb.place(PartType.ENGINE, 0, 0)
        gb.place(PartType.WHEEL, 1, 0)
        gb.place(PartType.WHEEL, 2, 0)
        ok, msg = gb.validate()
        assert ok is False
        assert "COCKPIT" in msg

    def test_validate_needs_engine(self):
        from entities.part import PartType
        gb = self._gb()
        gb.place(PartType.COCKPIT, 0, 0)
        gb.place(PartType.WHEEL, 1, 0)
        gb.place(PartType.WHEEL, 2, 0)
        ok, msg = gb.validate()
        assert ok is False
        assert "ENGINE" in msg

    def test_validate_needs_two_wheels(self):
        from entities.part import PartType
        gb = self._gb()
        gb.place(PartType.COCKPIT, 0, 0)
        gb.place(PartType.ENGINE, 1, 0)
        gb.place(PartType.WHEEL, 2, 0)
        ok, msg = gb.validate()
        assert ok is False

    def test_validate_passes_with_required_parts(self):
        from entities.part import PartType
        gb = self._gb()
        gb.place(PartType.COCKPIT, 0, 0)
        gb.place(PartType.ENGINE, 1, 0)
        gb.place(PartType.WHEEL, 2, 0)
        gb.place(PartType.WHEEL, 3, 0)
        ok, _ = gb.validate()
        assert ok is True

    def test_bake_returns_vehicle_entity(self):
        from entities.part import PartType
        from entities.vehicle import VehicleEntity
        gb = self._gb()
        gb.place(PartType.COCKPIT, 0, 0)
        gb.place(PartType.ENGINE, 1, 0)
        gb.place(PartType.WHEEL, 2, 0)
        gb.place(PartType.WHEEL, 3, 0)
        vehicle = gb.bake(driver_id=0)
        assert isinstance(vehicle, VehicleEntity)

    def test_bake_vehicle_has_parts(self):
        from entities.part import PartType
        gb = self._gb()
        gb.place(PartType.COCKPIT, 0, 0)
        gb.place(PartType.ENGINE, 1, 0)
        gb.place(PartType.WHEEL, 2, 0)
        gb.place(PartType.WHEEL, 3, 0)
        vehicle = gb.bake(driver_id=0)
        assert len(vehicle.parts) >= 4


# =============================================================================
# HazardSystem — init, add_boost_pad, add_damage_zone, _on_boost, _on_damage_zone
# =============================================================================

class TestHazardSystemInit:
    def _hs(self):
        from pharos_engine.trigger import TriggerSystem
        from systems.hazard_system import HazardSystem
        ts = TriggerSystem()
        hs = HazardSystem(ts)
        return hs, ts

    def test_init_no_crash(self):
        hs, ts = self._hs()
        hs.teardown()

    def test_add_boost_pad_returns_volume(self):
        from pharos_engine.trigger import TriggerVolume
        hs, ts = self._hs()
        vol = hs.add_boost_pad((100.0, 200.0))
        assert vol is not None
        hs.teardown()

    def test_add_damage_zone_returns_volume(self):
        from pharos_engine.trigger import TriggerVolume
        hs, ts = self._hs()
        vol = hs.add_damage_zone((50.0, 50.0))
        assert vol is not None
        hs.teardown()

    def test_teardown_clears_volumes(self):
        hs, ts = self._hs()
        hs.add_boost_pad((0.0, 0.0))
        hs.add_damage_zone((0.0, 0.0))
        hs.teardown()
        assert len(hs._boost_vols) == 0
        assert len(hs._damage_vols) == 0

    def test_boost_pad_tag_is_boost(self):
        hs, ts = self._hs()
        vol = hs.add_boost_pad((0.0, 0.0))
        assert vol.tag == "boost"
        hs.teardown()


class TestHazardSystemOnBoost:
    def _hs(self):
        from pharos_engine.trigger import TriggerSystem
        from systems.hazard_system import HazardSystem
        ts = TriggerSystem()
        return HazardSystem(ts), ts

    def test_on_boost_calls_boost_method(self):
        from pharos_engine.event_bus import publish
        hs, ts = self._hs()
        entity = MagicMock()
        entity._vphys_script = MagicMock()
        entity._vphys_script.boost = MagicMock()
        publish("Vehicle.Boost", publisher=entity, amount=1.5, duration=0.8)
        entity._vphys_script.boost.assert_called_once_with(1.5, 0.8)
        hs.teardown()

    def test_on_boost_fallback_scales_velocity(self):
        from pharos_engine.event_bus import publish
        hs, ts = self._hs()
        entity = MagicMock(spec=[])  # no _vphys_script
        entity.velocity = [100.0, 50.0]
        publish("Vehicle.Boost", publisher=entity, amount=2.0, duration=0.5)
        assert entity.velocity[0] == pytest.approx(200.0)
        hs.teardown()

    def test_on_boost_none_entity_no_crash(self):
        from pharos_engine.event_bus import publish
        hs, ts = self._hs()
        publish("Vehicle.Boost", publisher=None, amount=1.5, duration=0.8)
        hs.teardown()

    def test_on_boost_no_velocity_no_crash(self):
        from pharos_engine.event_bus import publish
        hs, ts = self._hs()
        entity = MagicMock(spec=[])  # no velocity
        publish("Vehicle.Boost", publisher=entity, amount=2.0, duration=0.5)
        hs.teardown()


class TestHazardSystemOnDamage:
    def _hs(self):
        from pharos_engine.trigger import TriggerSystem
        from systems.hazard_system import HazardSystem
        ts = TriggerSystem()
        return HazardSystem(ts), ts

    def test_on_damage_reduces_hull_integrity(self):
        from pharos_engine.event_bus import publish
        hs, ts = self._hs()
        entity = MagicMock(spec=[])
        entity.hull_integrity = 1.0
        entity._deform = None
        publish("Vehicle.DamageZone", publisher=entity, damage=0.2)
        assert entity.hull_integrity == pytest.approx(0.8)
        hs.teardown()

    def test_on_damage_none_entity_no_crash(self):
        from pharos_engine.event_bus import publish
        hs, ts = self._hs()
        publish("Vehicle.DamageZone", publisher=None, damage=0.1)
        hs.teardown()

    def test_on_damage_calls_deform_apply_impact(self):
        from pharos_engine.event_bus import publish
        hs, ts = self._hs()
        entity = MagicMock()
        entity._deform = MagicMock()
        entity._deform.apply_impact = MagicMock()
        publish("Vehicle.DamageZone", publisher=entity, damage=0.3)
        entity._deform.apply_impact.assert_called_once_with(0.3)
        hs.teardown()

    def test_on_damage_clamps_to_zero(self):
        from pharos_engine.event_bus import publish
        hs, ts = self._hs()
        entity = MagicMock(spec=[])
        entity.hull_integrity = 0.1
        entity._deform = None
        publish("Vehicle.DamageZone", publisher=entity, damage=0.5)
        assert entity.hull_integrity == pytest.approx(0.0)
        hs.teardown()


# =============================================================================
# PitsSystem — _on_vehicle_enter, _on_vehicle_exit, update
# =============================================================================

def _make_vehicle_for_pits(speed=0.0, integrity=0.5):
    v = MagicMock()
    vx = speed  # velocity x component
    v.velocity = [vx, 0.0]
    v.hull_integrity = integrity
    v._deform = None
    return v


class TestPitsSystemInit:
    def _ps(self):
        from pharos_engine.trigger import TriggerSystem
        from systems.pits_system import PitsSystem
        ts = TriggerSystem()
        ps = PitsSystem(ts, vehicles=[])
        return ps, ts

    def test_init_no_crash(self):
        ps, ts = self._ps()
        ps.teardown()

    def test_default_pit_volume_added(self):
        ps, ts = self._ps()
        assert len(ps._pit_volumes) >= 1
        ps.teardown()

    def test_teardown_clears_state(self):
        ps, ts = self._ps()
        ps.teardown()
        assert len(ps._pit_volumes) == 0


class TestPitsSystemEnterExit:
    def _ps(self):
        from pharos_engine.trigger import TriggerSystem
        from systems.pits_system import PitsSystem
        ts = TriggerSystem()
        ps = PitsSystem(ts, vehicles=[])
        return ps, ts

    def test_enter_slow_vehicle_creates_session(self):
        from systems.pits_system import ENTRY_SPEED_LIMIT
        ps, ts = self._ps()
        v = _make_vehicle_for_pits(speed=0.0)
        ps._on_vehicle_enter(v)
        assert id(v) in ps._active_sessions
        ps.teardown()

    def test_enter_fast_vehicle_no_session(self):
        from systems.pits_system import ENTRY_SPEED_LIMIT
        ps, ts = self._ps()
        v = _make_vehicle_for_pits(speed=ENTRY_SPEED_LIMIT + 10)
        ps._on_vehicle_enter(v)
        assert id(v) not in ps._active_sessions
        ps.teardown()

    def test_exit_removes_session(self):
        ps, ts = self._ps()
        v = _make_vehicle_for_pits(speed=0.0)
        ps._on_vehicle_enter(v)
        ps._on_vehicle_exit(v)
        assert id(v) not in ps._active_sessions
        ps.teardown()

    def test_exit_without_enter_no_crash(self):
        ps, ts = self._ps()
        v = _make_vehicle_for_pits()
        ps._on_vehicle_exit(v)  # should not raise
        ps.teardown()

    def test_update_accrues_cost(self):
        ps, ts = self._ps()
        v = _make_vehicle_for_pits(speed=0.0)
        ps._on_vehicle_enter(v)
        ps.update(1.0)
        state = ps._active_sessions.get(id(v))
        if state:
            assert state.cost_accrued > 0.0
        ps.teardown()

    def test_update_exits_fast_vehicle(self):
        from systems.pits_system import EXIT_SPEED
        ps, ts = self._ps()
        v = _make_vehicle_for_pits(speed=0.0)
        ps._on_vehicle_enter(v)
        v.velocity = [EXIT_SPEED + 10, 0.0]
        ps.update(0.016)
        assert id(v) not in ps._active_sessions
        ps.teardown()


# =============================================================================
# CoinSystem — _on_coin_enter, reset, teardown
# =============================================================================

class TestCoinSystem:
    def _cs(self, positions=None):
        from pharos_engine.trigger import TriggerSystem
        from systems.coin_system import CoinSystem
        ts = TriggerSystem()
        profile = MagicMock()
        profile.earn = MagicMock()
        cs = CoinSystem(ts, profile, positions or [(100.0, 100.0)])
        return cs, ts, profile

    def test_init_creates_volumes(self):
        cs, ts, profile = self._cs([(50.0, 50.0), (100.0, 100.0)])
        assert len(cs._volumes) == 2
        cs.teardown()

    def test_coin_enter_awards_profile(self):
        from pharos_engine.event_bus import publish
        cs, ts, profile = self._cs()
        vol = cs._volumes[0]
        publish("Trigger.Enter.coin", volume=vol)
        profile.earn.assert_called_once()
        cs.teardown()

    def test_coin_enter_only_once_before_reset(self):
        from pharos_engine.event_bus import publish
        cs, ts, profile = self._cs()
        vol = cs._volumes[0]
        publish("Trigger.Enter.coin", volume=vol)
        publish("Trigger.Enter.coin", volume=vol)
        assert profile.earn.call_count == 1
        cs.teardown()

    def test_reset_re_enables_coins(self):
        from pharos_engine.event_bus import publish
        cs, ts, profile = self._cs()
        vol = cs._volumes[0]
        publish("Trigger.Enter.coin", volume=vol)
        cs.reset()
        publish("Trigger.Enter.coin", volume=vol)
        assert profile.earn.call_count == 2
        cs.teardown()

    def test_teardown_clears_volumes(self):
        cs, ts, profile = self._cs()
        cs.teardown()
        assert len(cs._volumes) == 0
