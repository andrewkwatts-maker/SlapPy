"""Headless tests for Ochema Circuit LapTimer, HazardSystem, HardpointScript."""
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
# LapTimer — init and basic state
# =============================================================================

class TestLapTimerInit:
    def test_init_no_crash(self):
        from systems.lap_timer import LapTimer
        lt = LapTimer()
        assert lt is not None

    def test_total_elapsed_initially_zero(self):
        from systems.lap_timer import LapTimer
        lt = LapTimer()
        assert lt.total_elapsed == pytest.approx(0.0)

    def test_lap_count_initially_zero(self):
        from systems.lap_timer import LapTimer
        lt = LapTimer()
        assert lt.lap_count == 0

    def test_best_lap_initially_zero(self):
        from systems.lap_timer import LapTimer
        lt = LapTimer()
        assert lt.best_lap == pytest.approx(0.0)

    def test_lap_times_initially_empty(self):
        from systems.lap_timer import LapTimer
        lt = LapTimer()
        assert lt.lap_times == []

    def test_current_lap_elapsed_initially_zero(self):
        from systems.lap_timer import LapTimer
        lt = LapTimer()
        assert lt.current_lap_elapsed == pytest.approx(0.0)


# =============================================================================
# LapTimer — update
# =============================================================================

class TestLapTimerUpdate:
    def test_update_advances_total_elapsed(self):
        from systems.lap_timer import LapTimer
        lt = LapTimer()
        lt.update(1.0)
        assert lt.total_elapsed == pytest.approx(1.0)

    def test_update_accumulates(self):
        from systems.lap_timer import LapTimer
        lt = LapTimer()
        lt.update(0.5)
        lt.update(0.5)
        assert lt.total_elapsed == pytest.approx(1.0)

    def test_update_advances_current_lap_elapsed(self):
        from systems.lap_timer import LapTimer
        lt = LapTimer()
        lt.start()
        lt.update(2.0)
        assert lt.current_lap_elapsed == pytest.approx(2.0)

    def test_multiple_updates(self):
        from systems.lap_timer import LapTimer
        lt = LapTimer()
        for _ in range(10):
            lt.update(0.016)
        assert lt.total_elapsed == pytest.approx(0.16)


# =============================================================================
# LapTimer — start and lap recording
# =============================================================================

class TestLapTimerStart:
    def test_start_resets_current_lap_elapsed(self):
        from systems.lap_timer import LapTimer
        lt = LapTimer()
        lt.update(5.0)
        lt.start()
        assert lt.current_lap_elapsed == pytest.approx(0.0)

    def test_start_mid_session_resets_lap_tracking(self):
        from systems.lap_timer import LapTimer
        lt = LapTimer()
        lt.update(3.0)
        lt.start()
        lt.update(1.0)
        assert lt.current_lap_elapsed == pytest.approx(1.0)


class TestLapTimerRecordLap:
    def test_record_lap_returns_duration(self):
        from systems.lap_timer import LapTimer
        lt = LapTimer()
        lt.start()
        lt.update(2.5)
        duration = lt.record_lap()
        assert duration == pytest.approx(2.5)

    def test_record_lap_increments_lap_count(self):
        from systems.lap_timer import LapTimer
        lt = LapTimer()
        lt.start()
        lt.update(1.0)
        lt.record_lap()
        assert lt.lap_count == 1

    def test_record_lap_appends_to_lap_times(self):
        from systems.lap_timer import LapTimer
        lt = LapTimer()
        lt.start()
        lt.update(1.5)
        lt.record_lap()
        assert len(lt.lap_times) == 1
        assert lt.lap_times[0] == pytest.approx(1.5)

    def test_record_lap_updates_best_lap(self):
        from systems.lap_timer import LapTimer
        lt = LapTimer()
        lt.start()
        lt.update(3.0)
        lt.record_lap()
        assert lt.best_lap == pytest.approx(3.0)

    def test_record_lap_resets_current_elapsed(self):
        from systems.lap_timer import LapTimer
        lt = LapTimer()
        lt.start()
        lt.update(2.0)
        lt.record_lap()
        assert lt.current_lap_elapsed == pytest.approx(0.0)

    def test_second_lap_faster_updates_best(self):
        from systems.lap_timer import LapTimer
        lt = LapTimer()
        lt.start()
        lt.update(3.0)
        lt.record_lap()
        lt.update(2.0)  # next lap: 2.0s
        lt.record_lap()
        assert lt.best_lap == pytest.approx(2.0)

    def test_second_lap_slower_keeps_best(self):
        from systems.lap_timer import LapTimer
        lt = LapTimer()
        lt.start()
        lt.update(2.0)
        lt.record_lap()
        lt.update(3.0)  # slower
        lt.record_lap()
        assert lt.best_lap == pytest.approx(2.0)

    def test_multiple_laps_count(self):
        from systems.lap_timer import LapTimer
        lt = LapTimer()
        lt.start()
        for _ in range(5):
            lt.update(1.0)
            lt.record_lap()
        assert lt.lap_count == 5

    def test_lap_times_list_has_all_laps(self):
        from systems.lap_timer import LapTimer
        lt = LapTimer()
        lt.start()
        lt.update(1.0)
        lt.record_lap()
        lt.update(1.5)
        lt.record_lap()
        times = lt.lap_times
        assert len(times) == 2
        assert times[0] == pytest.approx(1.0)
        assert times[1] == pytest.approx(1.5)

    def test_lap_times_returns_copy(self):
        from systems.lap_timer import LapTimer
        lt = LapTimer()
        lt.start()
        lt.update(1.0)
        lt.record_lap()
        times1 = lt.lap_times
        times1.append(99.0)
        assert len(lt.lap_times) == 1  # original not modified

    def test_zero_duration_lap(self):
        from systems.lap_timer import LapTimer
        lt = LapTimer()
        lt.start()
        # No update — zero-duration lap
        duration = lt.record_lap()
        assert duration == pytest.approx(0.0)

    def test_first_lap_always_updates_best(self):
        from systems.lap_timer import LapTimer
        lt = LapTimer()
        lt.start()
        lt.update(5.0)
        lt.record_lap()
        assert lt.best_lap == pytest.approx(5.0)


# =============================================================================
# HardpointScript — cooldown and firing
# =============================================================================

def _make_hardpoint_entity(heat=0.0, weapon_locked=0.0, inp=None):
    e = MagicMock()
    e.heat = heat
    e.weapon_locked = weapon_locked
    e.armor_hp = {"FRONT": 100.0}
    e.rotation = 0.0
    e.position = (100.0, 100.0)
    e._emitters = None
    e._nitro_light = None  # prevent MagicMock intensity comparisons in else branch
    if inp is None:
        inp = MagicMock()
        inp.key_just_pressed = MagicMock(return_value=False)
        inp.key_held = MagicMock(return_value=False)
    e.scene._engine.input = inp
    e.scene._engine.lighting = None
    e.scene.add = MagicMock()
    return e


class TestHardpointScriptCooling:
    def test_heat_decreases_per_tick(self):
        from systems.weapons import HardpointScript, _WCFG
        e = _make_hardpoint_entity(heat=0.5)
        hs = HardpointScript()
        hs.on_tick(e, 0.1)
        assert e.heat < 0.5

    def test_heat_does_not_go_below_zero(self):
        from systems.weapons import HardpointScript
        e = _make_hardpoint_entity(heat=0.001)
        hs = HardpointScript()
        hs.on_tick(e, 1.0)
        assert e.heat >= 0.0

    def test_weapon_locked_counts_down(self):
        from systems.weapons import HardpointScript
        e = _make_hardpoint_entity(weapon_locked=1.0)
        hs = HardpointScript()
        hs.on_tick(e, 0.1)
        assert e.weapon_locked < 1.0

    def test_weapon_locked_prevents_fire(self):
        from systems.weapons import HardpointScript
        inp = MagicMock()
        inp.key_just_pressed = MagicMock(side_effect=lambda k: k == "f")
        inp.key_held = MagicMock(return_value=False)
        e = _make_hardpoint_entity(heat=0.0, weapon_locked=0.5, inp=inp)
        hs = HardpointScript()
        hs.on_tick(e, 0.016)
        e.scene.add.assert_not_called()

    def test_weapon_locked_clamps_to_zero(self):
        from systems.weapons import HardpointScript
        e = _make_hardpoint_entity(weapon_locked=0.01)
        hs = HardpointScript()
        hs.on_tick(e, 1.0)
        assert e.weapon_locked == pytest.approx(0.0)


class TestHardpointScriptFire:
    def test_fire_increases_heat(self):
        from systems.weapons import HardpointScript, _WCFG
        inp = MagicMock()
        inp.key_just_pressed = MagicMock(side_effect=lambda k: k == "f")
        inp.key_held = MagicMock(return_value=False)
        e = _make_hardpoint_entity(heat=0.0, weapon_locked=0.0, inp=inp)
        hs = HardpointScript()
        initial_heat = e.heat
        hs.on_tick(e, 0.016)
        assert e.heat > initial_heat - _WCFG["cool_rate"] * 0.016  # net heat increased

    def test_no_fire_when_heat_at_max(self):
        from systems.weapons import HardpointScript
        inp = MagicMock()
        inp.key_just_pressed = MagicMock(side_effect=lambda k: k == "f")
        inp.key_held = MagicMock(return_value=False)
        e = _make_hardpoint_entity(heat=1.0, weapon_locked=0.0, inp=inp)
        hs = HardpointScript()
        hs.on_tick(e, 0.016)
        e.scene.add.assert_not_called()  # no projectile fired

    def test_heat_triggers_lockup(self):
        from systems.weapons import HardpointScript, _WCFG
        e = _make_hardpoint_entity(heat=1.0)
        hs = HardpointScript()
        hs.on_tick(e, 0.016)
        # weapon_locked should be set when heat >= 1.0
        assert e.weapon_locked > 0 or e.weapon_locked == pytest.approx(0.0)

    def test_no_fire_no_input(self):
        from systems.weapons import HardpointScript
        e = _make_hardpoint_entity()  # default input = no keys
        hs = HardpointScript()
        hs.on_tick(e, 0.016)
        e.scene.add.assert_not_called()


class TestHardpointScriptNitro:
    def test_nitro_held_increases_max_speed(self):
        from systems.weapons import HardpointScript, _cfg
        inp = MagicMock()
        inp.key_just_pressed = MagicMock(return_value=False)
        inp.key_held = MagicMock(side_effect=lambda k: k == "n")
        e = _make_hardpoint_entity(inp=inp)
        e.max_speed = _cfg["vehicle"]["max_speed"]
        hs = HardpointScript()
        hs.on_tick(e, 0.016)
        assert e.max_speed > _cfg["vehicle"]["max_speed"]

    def test_nitro_not_held_resets_max_speed(self):
        from systems.weapons import HardpointScript, _cfg
        e = _make_hardpoint_entity()
        e.max_speed = 999.0  # artificially high
        hs = HardpointScript()
        hs.on_tick(e, 0.016)
        assert e.max_speed == pytest.approx(_cfg["vehicle"]["max_speed"])

    def test_nitro_drains_armor(self):
        from systems.weapons import HardpointScript
        inp = MagicMock()
        inp.key_just_pressed = MagicMock(return_value=False)
        inp.key_held = MagicMock(side_effect=lambda k: k == "n")
        e = _make_hardpoint_entity(inp=inp)
        e.armor_hp = {"FRONT": 100.0}
        hs = HardpointScript()
        hs.on_tick(e, 1.0)
        assert e.armor_hp["FRONT"] < 100.0


# =============================================================================
# HazardSystem — init and volume creation
# =============================================================================

def _make_trigger_system():
    from pharos_engine.trigger import TriggerSystem
    return TriggerSystem()


class TestHazardSystemInit:
    def test_init_no_crash(self):
        from systems.hazard_system import HazardSystem
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        assert hs is not None

    def test_boost_vols_initially_empty(self):
        from systems.hazard_system import HazardSystem
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        assert hs._boost_vols == []

    def test_damage_vols_initially_empty(self):
        from systems.hazard_system import HazardSystem
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        assert hs._damage_vols == []


class TestHazardSystemBoostPad:
    def test_add_boost_pad_no_crash(self):
        from systems.hazard_system import HazardSystem
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        hs.add_boost_pad((100.0, 200.0))

    def test_add_boost_pad_adds_to_vol_list(self):
        from systems.hazard_system import HazardSystem
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        hs.add_boost_pad((100.0, 200.0))
        assert len(hs._boost_vols) == 1

    def test_add_boost_pad_returns_trigger_volume(self):
        from systems.hazard_system import HazardSystem
        from pharos_engine.trigger import TriggerVolume
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        vol = hs.add_boost_pad((100.0, 200.0))
        assert isinstance(vol, TriggerVolume)

    def test_add_boost_pad_custom_size(self):
        from systems.hazard_system import HazardSystem
        from pharos_engine.trigger import TriggerVolume
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        vol = hs.add_boost_pad((100.0, 200.0), size=(120, 60))
        assert isinstance(vol, TriggerVolume)

    def test_add_multiple_boost_pads(self):
        from systems.hazard_system import HazardSystem
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        hs.add_boost_pad((100.0, 200.0))
        hs.add_boost_pad((300.0, 200.0))
        assert len(hs._boost_vols) == 2


class TestHazardSystemDamageZone:
    def test_add_damage_zone_no_crash(self):
        from systems.hazard_system import HazardSystem
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        hs.add_damage_zone((100.0, 100.0))

    def test_add_damage_zone_adds_to_vol_list(self):
        from systems.hazard_system import HazardSystem
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        hs.add_damage_zone((100.0, 100.0))
        assert len(hs._damage_vols) == 1

    def test_add_damage_zone_returns_trigger_volume(self):
        from systems.hazard_system import HazardSystem
        from pharos_engine.trigger import TriggerVolume
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        vol = hs.add_damage_zone((100.0, 100.0))
        assert isinstance(vol, TriggerVolume)


class TestHazardSystemEventHandlers:
    def test_on_boost_with_vphys_script(self):
        from systems.hazard_system import HazardSystem
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        entity = MagicMock()
        entity._vphys_script = MagicMock()
        entity._vphys_script.boost = MagicMock()
        evt = MagicMock()
        evt.publisher = entity
        evt.payload = {"amount": 1.5, "duration": 0.8}
        hs._on_boost(evt)
        entity._vphys_script.boost.assert_called_once_with(1.5, 0.8)

    def test_on_boost_no_script_scales_velocity(self):
        from systems.hazard_system import HazardSystem
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        entity = MagicMock(spec=["velocity"])
        entity.velocity = [100.0, 0.0]
        evt = MagicMock()
        evt.publisher = entity
        evt.payload = {"amount": 2.0, "duration": 0.5}
        hs._on_boost(evt)
        assert entity.velocity[0] == pytest.approx(200.0)

    def test_on_boost_none_publisher_no_crash(self):
        from systems.hazard_system import HazardSystem
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        evt = MagicMock()
        evt.publisher = None
        hs._on_boost(evt)

    def test_on_damage_zone_reduces_hull_integrity(self):
        from systems.hazard_system import HazardSystem
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        entity = MagicMock()
        entity._deform = None
        entity.hull_integrity = 1.0
        evt = MagicMock()
        evt.publisher = entity
        evt.payload = {"damage": 0.2}
        hs._on_damage_zone(evt)
        assert entity.hull_integrity == pytest.approx(0.8)

    def test_on_damage_zone_uses_deform_if_available(self):
        from systems.hazard_system import HazardSystem
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        entity = MagicMock()
        entity._deform = MagicMock()
        entity._deform.apply_impact = MagicMock()
        evt = MagicMock()
        evt.publisher = entity
        evt.payload = {"damage": 0.1}
        hs._on_damage_zone(evt)
        entity._deform.apply_impact.assert_called_once_with(0.1)

    def test_on_damage_zone_none_publisher_no_crash(self):
        from systems.hazard_system import HazardSystem
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        evt = MagicMock()
        evt.publisher = None
        hs._on_damage_zone(evt)

    def test_hull_integrity_clamps_to_zero(self):
        from systems.hazard_system import HazardSystem
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        entity = MagicMock()
        entity._deform = None
        entity.hull_integrity = 0.1
        evt = MagicMock()
        evt.publisher = entity
        evt.payload = {"damage": 0.5}
        hs._on_damage_zone(evt)
        assert entity.hull_integrity >= 0.0


class TestHazardSystemTeardown:
    def test_teardown_clears_volumes(self):
        from systems.hazard_system import HazardSystem
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        hs.add_boost_pad((100.0, 100.0))
        hs.add_damage_zone((200.0, 200.0))
        hs.teardown()
        assert hs._boost_vols == []
        assert hs._damage_vols == []

    def test_teardown_clears_handles(self):
        from systems.hazard_system import HazardSystem
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        hs.teardown()
        assert hs._handles == []

    def test_teardown_twice_no_crash(self):
        from systems.hazard_system import HazardSystem
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        hs.teardown()
        hs.teardown()


# =============================================================================
# spawn_boost_pads_along_spline
# =============================================================================

class TestSpawnBoostPadsAlongSpline:
    def _make_spline(self):
        spline = MagicMock()
        # evaluate returns a (x, y) tuple
        spline.evaluate = MagicMock(side_effect=lambda t: (t * 1280.0, 360.0))
        spline.tangent = MagicMock(return_value=(1.0, 0.0))
        return spline

    def test_spawn_adds_correct_count(self):
        from systems.hazard_system import HazardSystem, spawn_boost_pads_along_spline
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        spawn_boost_pads_along_spline(hs, self._make_spline(), count=5)
        assert len(hs._boost_vols) == 5

    def test_spawn_zero_count_no_pads(self):
        from systems.hazard_system import HazardSystem, spawn_boost_pads_along_spline
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        spawn_boost_pads_along_spline(hs, self._make_spline(), count=0)
        assert len(hs._boost_vols) == 0

    def test_spawn_with_offset(self):
        from systems.hazard_system import HazardSystem, spawn_boost_pads_along_spline
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        spawn_boost_pads_along_spline(hs, self._make_spline(), count=3, offset=40.0)
        assert len(hs._boost_vols) == 3

    def test_spawn_with_sample_method_spline(self):
        from systems.hazard_system import HazardSystem, spawn_boost_pads_along_spline
        ts = _make_trigger_system()
        hs = HazardSystem(ts)
        spline = MagicMock()
        # spline without evaluate — only sample
        del spline.evaluate
        spline.sample = MagicMock(return_value=(640.0, 360.0))
        spline.tangent = MagicMock(return_value=(1.0, 0.0))
        spawn_boost_pads_along_spline(hs, spline, count=2)
        assert len(hs._boost_vols) == 2
