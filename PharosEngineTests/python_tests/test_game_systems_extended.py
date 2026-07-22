"""Headless tests for Ochema Circuit extended systems:
GhostSystem, PlayerProfile, CoinSystem, HazardSystem, PitsSystem, QualitySystem.
"""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("pharos_engine.compute.asset_compute", MagicMock())

_GAME_ROOT = Path(__file__).parent.parent.parent.parent.parent / "DaedalusSVN" / "Ochema Circuit"
_GAME_STR = str(_GAME_ROOT)
if _GAME_STR not in sys.path:
    sys.path.insert(0, _GAME_STR)


# =============================================================================
# GhostSystem
# =============================================================================

class TestGhostSystemInit:
    def _gs(self, vehicle=None, save_dir=None):
        from systems.ghost_system import GhostSystem
        return GhostSystem(tracked_vehicle=vehicle, save_dir=save_dir)

    def test_instantiates(self):
        gs = self._gs()
        gs.teardown()

    def test_not_recording_initially(self):
        gs = self._gs()
        assert gs._recording is False
        gs.teardown()

    def test_frames_empty_initially(self):
        gs = self._gs()
        assert gs._frames == []
        gs.teardown()

    def test_best_frames_empty_initially(self):
        gs = self._gs()
        assert gs._best_frames == []
        gs.teardown()

    def test_has_ghost_false_initially(self):
        gs = self._gs()
        assert gs.has_ghost is False
        gs.teardown()

    def test_ghost_entity_none_initially(self):
        gs = self._gs()
        assert gs.ghost_entity is None
        gs.teardown()

    def test_teardown_twice_no_crash(self):
        gs = self._gs()
        gs.teardown()
        gs.teardown()

    def test_best_lap_time_infinite_initially(self):
        import math
        gs = self._gs()
        assert math.isinf(gs._best_lap_time)
        gs.teardown()


class TestGhostSystemRecording:
    def _vehicle(self):
        v = MagicMock()
        v.position = (100.0, 200.0)
        v.rotation = 45.0
        return v

    def test_race_started_sets_recording(self):
        from systems.ghost_system import GhostSystem
        v = self._vehicle()
        gs = GhostSystem(tracked_vehicle=v)
        gs._on_race_started(MagicMock())
        assert gs._recording is True
        gs.teardown()

    def test_race_started_clears_frames(self):
        from systems.ghost_system import GhostSystem
        from systems.ghost_system import GhostFrame
        v = self._vehicle()
        gs = GhostSystem(tracked_vehicle=v)
        gs._frames = [GhostFrame(t=0.0, x=0.0, y=0.0, rotation=0.0)]
        gs._on_race_started(MagicMock())
        assert gs._frames == []
        gs.teardown()

    def test_record_tick_captures_frame_when_interval_elapsed(self):
        from systems.ghost_system import GhostSystem
        v = self._vehicle()
        gs = GhostSystem(tracked_vehicle=v)
        gs._recording = True
        gs._last_sample = 0.0  # force interval to have elapsed
        gs.record_tick(0.016)
        assert len(gs._frames) >= 1
        gs.teardown()

    def test_record_tick_no_vehicle(self):
        from systems.ghost_system import GhostSystem
        gs = GhostSystem(tracked_vehicle=None)
        gs._recording = True
        gs._last_sample = 0.0
        gs.record_tick(0.016)
        assert len(gs._frames) == 0
        gs.teardown()

    def test_record_tick_not_recording(self):
        from systems.ghost_system import GhostSystem
        v = self._vehicle()
        gs = GhostSystem(tracked_vehicle=v)
        gs._recording = False
        gs._last_sample = 0.0
        gs.record_tick(0.016)
        assert len(gs._frames) == 0
        gs.teardown()

    def test_race_finished_stops_recording(self):
        from systems.ghost_system import GhostSystem
        v = self._vehicle()
        gs = GhostSystem(tracked_vehicle=v)
        gs._recording = True
        gs._on_race_finished(MagicMock())
        assert gs._recording is False
        gs.teardown()

    def test_best_lap_event_updates_best(self):
        from systems.ghost_system import GhostSystem, GhostFrame
        v = self._vehicle()
        gs = GhostSystem(tracked_vehicle=v)
        gs._frames = [GhostFrame(t=0.0, x=10.0, y=20.0, rotation=0.0)]
        evt = MagicMock()
        evt.lap_time = 55.0
        gs._on_best_lap(evt)
        assert abs(gs._best_lap_time - 55.0) < 1e-6
        assert len(gs._best_frames) == 1
        gs.teardown()

    def test_best_lap_not_updated_when_slower(self):
        from systems.ghost_system import GhostSystem, GhostFrame
        v = self._vehicle()
        gs = GhostSystem(tracked_vehicle=v)
        gs._best_lap_time = 50.0
        gs._frames = [GhostFrame(t=0.0, x=10.0, y=20.0, rotation=0.0)]
        evt = MagicMock()
        evt.lap_time = 70.0  # slower
        gs._on_best_lap(evt)
        assert abs(gs._best_lap_time - 50.0) < 1e-6  # unchanged
        gs.teardown()


class TestGhostSystemPlayback:
    def _gs_with_frames(self):
        from systems.ghost_system import GhostSystem, GhostFrame
        gs = GhostSystem(tracked_vehicle=None)
        gs._best_frames = [
            GhostFrame(t=0.0,  x=10.0, y=20.0, rotation=0.0),
            GhostFrame(t=0.05, x=15.0, y=20.0, rotation=5.0),
            GhostFrame(t=0.10, x=20.0, y=20.0, rotation=10.0),
        ]
        gs._best_lap_time = 0.10
        return gs

    def test_has_ghost_true_with_frames(self):
        gs = self._gs_with_frames()
        assert gs.has_ghost is True
        gs.teardown()

    def test_playback_tick_returns_none_inactive(self):
        gs = self._gs_with_frames()
        result = gs.playback_tick(0.016)
        assert result is None
        gs.teardown()

    def test_start_playback_activates(self):
        gs = self._gs_with_frames()
        gs._start_playback()
        assert gs._playback is True
        gs.teardown()

    def test_playback_tick_returns_tuple_after_start(self):
        gs = self._gs_with_frames()
        gs._start_playback()
        result = gs.playback_tick(0.016)
        assert result is not None
        x, y, rot = result
        assert isinstance(x, float)
        assert isinstance(y, float)
        assert isinstance(rot, float)
        gs.teardown()

    def test_ghost_entity_created_after_playback_start(self):
        gs = self._gs_with_frames()
        gs._start_playback()
        assert gs.ghost_entity is not None
        gs.teardown()

    def test_race_finished_stops_playback(self):
        gs = self._gs_with_frames()
        gs._start_playback()
        gs._on_race_finished(MagicMock())
        assert gs._playback is False
        gs.teardown()


class TestGhostSystemPersistence:
    def test_save_and_reload(self):
        from systems.ghost_system import GhostSystem, GhostFrame
        d = tempfile.mkdtemp()
        gs1 = GhostSystem(tracked_vehicle=None, save_dir=d)
        gs1._best_frames = [GhostFrame(t=0.0, x=50.0, y=60.0, rotation=90.0)]
        gs1._best_lap_time = 45.5
        gs1._save()
        gs1.teardown()

        gs2 = GhostSystem(tracked_vehicle=None, save_dir=d)
        assert len(gs2._best_frames) == 1
        assert abs(gs2._best_lap_time - 45.5) < 1e-6
        gs2.teardown()

    def test_frame_data_correct_after_reload(self):
        from systems.ghost_system import GhostSystem, GhostFrame
        d = tempfile.mkdtemp()
        gs1 = GhostSystem(tracked_vehicle=None, save_dir=d)
        gs1._best_frames = [
            GhostFrame(t=0.1, x=11.0, y=22.0, rotation=33.0),
        ]
        gs1._best_lap_time = 60.0
        gs1._save()
        gs1.teardown()

        gs2 = GhostSystem(tracked_vehicle=None, save_dir=d)
        f = gs2._best_frames[0]
        assert abs(f.x - 11.0) < 1e-6
        assert abs(f.y - 22.0) < 1e-6
        assert abs(f.rotation - 33.0) < 1e-6
        gs2.teardown()

    def test_missing_save_no_crash(self):
        from systems.ghost_system import GhostSystem
        d = tempfile.mkdtemp()
        gs = GhostSystem(tracked_vehicle=None, save_dir=d)
        assert gs._best_frames == []
        gs.teardown()

    def test_no_save_dir_save_no_crash(self):
        from systems.ghost_system import GhostSystem, GhostFrame
        gs = GhostSystem(tracked_vehicle=None, save_dir=None)
        gs._best_frames = [GhostFrame(t=0.0, x=0.0, y=0.0, rotation=0.0)]
        gs._save()  # should silently skip
        gs.teardown()


# =============================================================================
# PlayerProfile
# =============================================================================

class TestPlayerProfileInit:
    def _pp(self):
        from systems.player_profile import PlayerProfile
        return PlayerProfile()

    def test_instantiates(self):
        assert self._pp() is not None

    def test_coins_start_at_zero(self):
        assert self._pp().coins == 0

    def test_all_part_tiers_zero(self):
        pp = self._pp()
        for pt in ["cockpit", "engine", "armor", "wheel", "weapon"]:
            assert pp.part_tier(pt) == 0

    def test_is_observable(self):
        from pharos_engine.event_bus import Observable
        from systems.player_profile import PlayerProfile
        assert issubclass(PlayerProfile, Observable)


class TestPlayerProfileCoins:
    def _pp(self):
        from systems.player_profile import PlayerProfile
        return PlayerProfile()

    def test_earn_increases_coins(self):
        pp = self._pp()
        pp.earn(50)
        assert pp.coins == 50

    def test_earn_publishes_event(self):
        from pharos_engine.event_bus import subscribe, unsubscribe
        pp = self._pp()
        received = []
        h = subscribe("PlayerProfile.CoinsEarned", lambda e: received.append(e))
        pp.earn(10)
        unsubscribe(h)
        assert len(received) >= 1

    def test_spend_reduces_coins(self):
        pp = self._pp()
        pp.earn(100)
        pp.spend(30)
        assert pp.coins == 70

    def test_spend_returns_true_on_success(self):
        pp = self._pp()
        pp.earn(100)
        assert pp.spend(50) is True

    def test_spend_returns_false_when_insufficient(self):
        pp = self._pp()
        pp.earn(10)
        assert pp.spend(50) is False

    def test_spend_does_not_go_negative(self):
        pp = self._pp()
        pp.earn(30)
        pp.spend(100)
        assert pp.coins == 30  # unchanged

    def test_earn_multiple_accumulates(self):
        pp = self._pp()
        for _ in range(5):
            pp.earn(20)
        assert pp.coins == 100


class TestPlayerProfileUpgrades:
    def _pp(self):
        from systems.player_profile import PlayerProfile
        return PlayerProfile()

    def test_part_stats_returns_dict(self):
        pp = self._pp()
        stats = pp.part_stats("engine")
        assert isinstance(stats, dict)

    def test_upgrade_cost_returns_int_or_none(self):
        pp = self._pp()
        cost = pp.upgrade_cost("engine")
        assert cost is None or isinstance(cost, int)

    def test_try_upgrade_without_coins_returns_false(self):
        pp = self._pp()
        # No coins — upgrade must fail
        result = pp.try_upgrade("engine")
        assert result is False

    def test_try_upgrade_with_coins_succeeds(self):
        pp = self._pp()
        cost = pp.upgrade_cost("engine")
        if cost is None:
            return  # already at max
        pp.earn(cost)
        result = pp.try_upgrade("engine")
        assert result is True

    def test_try_upgrade_increments_tier(self):
        pp = self._pp()
        cost = pp.upgrade_cost("engine")
        if cost is None:
            return
        pp.earn(cost)
        pp.try_upgrade("engine")
        assert pp.part_tier("engine") == 1

    def test_total_upgrade_spend_zero_initially(self):
        pp = self._pp()
        assert pp.total_upgrade_spend() == 0

    def test_total_upgrade_spend_after_upgrade(self):
        pp = self._pp()
        cost = pp.upgrade_cost("cockpit")
        if cost is None or cost == 0:
            return
        pp.earn(cost)
        pp.try_upgrade("cockpit")
        assert pp.total_upgrade_spend() > 0


# =============================================================================
# CoinSystem
# =============================================================================

class TestCoinSystemInit:
    def _cs(self, positions=None):
        from systems.coin_system import CoinSystem
        from pharos_engine.trigger import TriggerSystem
        ts = TriggerSystem()
        profile = MagicMock()
        profile.earn = MagicMock()
        cs = CoinSystem(trigger_system=ts, profile=profile,
                        positions=positions or [(100.0, 100.0), (300.0, 300.0)])
        return cs, ts, profile

    def test_instantiates(self):
        cs, _, _ = self._cs()
        cs.teardown()

    def test_volumes_created(self):
        cs, _, _ = self._cs(positions=[(10.0, 10.0), (20.0, 20.0), (30.0, 30.0)])
        assert len(cs._volumes) == 3
        cs.teardown()

    def test_no_coins_collected_initially(self):
        cs, _, _ = self._cs()
        assert len(cs._collected) == 0
        cs.teardown()

    def test_teardown_no_crash(self):
        cs, _, _ = self._cs()
        cs.teardown()
        cs.teardown()


class TestCoinSystemCollection:
    def _cs(self):
        from systems.coin_system import CoinSystem
        from pharos_engine.trigger import TriggerSystem
        ts = TriggerSystem()
        profile = MagicMock()
        profile.earn = MagicMock()
        cs = CoinSystem(trigger_system=ts, profile=profile,
                        positions=[(100.0, 100.0)], value=15)
        return cs, ts, profile

    def test_coin_enter_awards_profile(self):
        cs, ts, profile = self._cs()
        vol = cs._volumes[0]
        evt = MagicMock()
        evt.volume = vol
        cs._on_coin_enter(evt)
        profile.earn.assert_called_once_with(15)
        cs.teardown()

    def test_coin_enter_marks_collected(self):
        cs, ts, profile = self._cs()
        vol = cs._volumes[0]
        evt = MagicMock()
        evt.volume = vol
        cs._on_coin_enter(evt)
        assert id(vol) in cs._collected
        cs.teardown()

    def test_coin_not_awarded_twice(self):
        cs, ts, profile = self._cs()
        vol = cs._volumes[0]
        evt = MagicMock()
        evt.volume = vol
        cs._on_coin_enter(evt)
        cs._on_coin_enter(evt)
        profile.earn.assert_called_once()
        cs.teardown()

    def test_reset_clears_collected(self):
        cs, ts, profile = self._cs()
        vol = cs._volumes[0]
        evt = MagicMock()
        evt.volume = vol
        cs._on_coin_enter(evt)
        cs.reset()
        assert len(cs._collected) == 0
        cs.teardown()

    def test_coin_enter_publishes_event(self):
        from pharos_engine.event_bus import subscribe, unsubscribe
        cs, ts, profile = self._cs()
        vol = cs._volumes[0]
        received = []
        h = subscribe("Race.CoinCollected", lambda e: received.append(e))
        evt = MagicMock()
        evt.volume = vol
        cs._on_coin_enter(evt)
        unsubscribe(h)
        assert len(received) >= 1
        cs.teardown()

    def test_none_volume_no_crash(self):
        cs, ts, profile = self._cs()
        evt = MagicMock()
        evt.volume = None
        cs._on_coin_enter(evt)  # should not crash
        cs.teardown()


# =============================================================================
# HazardSystem
# =============================================================================

class TestHazardSystemInit:
    def _hs(self):
        from systems.hazard_system import HazardSystem
        from pharos_engine.trigger import TriggerSystem
        ts = TriggerSystem()
        return HazardSystem(trigger_system=ts), ts

    def test_instantiates(self):
        hs, _ = self._hs()
        hs.teardown()

    def test_no_boost_vols_initially(self):
        hs, _ = self._hs()
        assert len(hs._boost_vols) == 0
        hs.teardown()

    def test_no_damage_vols_initially(self):
        hs, _ = self._hs()
        assert len(hs._damage_vols) == 0
        hs.teardown()

    def test_teardown_no_crash(self):
        hs, _ = self._hs()
        hs.teardown()
        hs.teardown()


class TestHazardSystemBoostPad:
    def _hs(self):
        from systems.hazard_system import HazardSystem
        from pharos_engine.trigger import TriggerSystem
        ts = TriggerSystem()
        return HazardSystem(trigger_system=ts), ts

    def test_add_boost_pad_returns_volume(self):
        from pharos_engine.trigger import TriggerVolume
        hs, _ = self._hs()
        vol = hs.add_boost_pad(position=(200.0, 300.0))
        assert isinstance(vol, TriggerVolume)
        hs.teardown()

    def test_add_boost_pad_registered(self):
        hs, _ = self._hs()
        hs.add_boost_pad(position=(100.0, 100.0))
        assert len(hs._boost_vols) == 1
        hs.teardown()

    def test_multiple_boost_pads(self):
        hs, _ = self._hs()
        for i in range(5):
            hs.add_boost_pad(position=(i * 100.0, 200.0))
        assert len(hs._boost_vols) == 5
        hs.teardown()

    def test_boost_pad_fires_event_on_entry(self):
        from pharos_engine.event_bus import subscribe, unsubscribe
        hs, _ = self._hs()
        vol = hs.add_boost_pad(position=(200.0, 200.0), boost_amount=2.0, duration=1.0)
        received = []
        h = subscribe("Vehicle.Boost", lambda e: received.append(e))
        entity = MagicMock()
        vol.on_enter(entity)
        unsubscribe(h)
        assert len(received) >= 1
        hs.teardown()

    def test_boost_applies_velocity_fallback(self):
        from pharos_engine.event_bus import publish
        hs, _ = self._hs()
        hs.add_boost_pad(position=(200.0, 200.0), boost_amount=2.0, duration=1.0)
        entity = MagicMock()
        entity._vphys_script = None
        entity.velocity = [100.0, 0.0]
        publish("Vehicle.Boost", publisher=entity, amount=2.0, duration=1.0)
        assert entity.velocity[0] == 200.0  # doubled
        hs.teardown()


class TestHazardSystemDamageZone:
    def _hs(self):
        from systems.hazard_system import HazardSystem
        from pharos_engine.trigger import TriggerSystem
        ts = TriggerSystem()
        return HazardSystem(trigger_system=ts), ts

    def test_add_damage_zone_returns_volume(self):
        from pharos_engine.trigger import TriggerVolume
        hs, _ = self._hs()
        vol = hs.add_damage_zone(position=(300.0, 400.0))
        assert isinstance(vol, TriggerVolume)
        hs.teardown()

    def test_add_damage_zone_registered(self):
        hs, _ = self._hs()
        hs.add_damage_zone(position=(100.0, 100.0))
        assert len(hs._damage_vols) == 1
        hs.teardown()

    def test_damage_zone_fires_event_on_entry(self):
        from pharos_engine.event_bus import subscribe, unsubscribe
        hs, _ = self._hs()
        vol = hs.add_damage_zone(position=(200.0, 200.0), damage=0.2)
        received = []
        h = subscribe("Vehicle.DamageZone", lambda e: received.append(e))
        entity = MagicMock()
        vol.on_enter(entity)
        unsubscribe(h)
        assert len(received) >= 1
        hs.teardown()

    def test_damage_reduces_hull_integrity(self):
        from pharos_engine.event_bus import publish
        hs, _ = self._hs()
        hs.add_damage_zone(position=(200.0, 200.0), damage=0.2)
        entity = MagicMock()
        entity._deform = None
        entity.hull_integrity = 1.0
        publish("Vehicle.DamageZone", publisher=entity, damage=0.2)
        assert entity.hull_integrity <= 0.8 + 1e-6
        hs.teardown()

    def test_damage_does_not_go_below_zero(self):
        from pharos_engine.event_bus import publish
        hs, _ = self._hs()
        hs.add_damage_zone(position=(200.0, 200.0), damage=5.0)
        entity = MagicMock()
        entity._deform = None
        entity.hull_integrity = 0.1
        publish("Vehicle.DamageZone", publisher=entity, damage=5.0)
        assert entity.hull_integrity >= 0.0
        hs.teardown()


# =============================================================================
# PitsSystem
# =============================================================================

class TestPitsSystemInit:
    def _ps(self, positions=None):
        from systems.pits_system import PitsSystem
        from pharos_engine.trigger import TriggerSystem
        ts = TriggerSystem()
        vehicles = []
        ps = PitsSystem(trigger_system=ts, vehicles=vehicles,
                        pit_positions=positions or [(200.0, 200.0, 80.0, 40.0, 1.0, 0.0)])
        return ps, ts

    def test_instantiates(self):
        ps, _ = self._ps()
        ps.teardown()

    def test_pit_volumes_created(self):
        ps, _ = self._ps(positions=[(100.0, 100.0, 80.0, 40.0, 1.0, 0.0),
                                     (200.0, 200.0, 80.0, 40.0, 1.0, 0.0)])
        assert len(ps._pit_volumes) == 2
        ps.teardown()

    def test_no_active_sessions_initially(self):
        ps, _ = self._ps()
        assert len(ps._active_sessions) == 0
        ps.teardown()

    def test_teardown_no_crash(self):
        ps, _ = self._ps()
        ps.teardown()
        ps.teardown()


class TestPitsSystemVehicleEntry:
    def _ps(self):
        from systems.pits_system import PitsSystem
        from pharos_engine.trigger import TriggerSystem
        ts = TriggerSystem()
        ps = PitsSystem(trigger_system=ts, vehicles=[],
                        pit_positions=[(200.0, 200.0, 80.0, 40.0, 1.0, 0.0)])
        return ps

    def _slow_vehicle(self):
        v = MagicMock()
        v.velocity = (0.0, 0.0)  # speed = 0 < ENTRY_SPEED_LIMIT
        v.hull_integrity = 0.5
        return v

    def _fast_vehicle(self):
        v = MagicMock()
        v.velocity = (200.0, 0.0)  # speed > ENTRY_SPEED_LIMIT
        v.hull_integrity = 1.0
        return v

    def test_slow_vehicle_enters_pits(self):
        ps = self._ps()
        v = self._slow_vehicle()
        ps._on_vehicle_enter(v)
        assert id(v) in ps._active_sessions
        ps.teardown()

    def test_fast_vehicle_rejected(self):
        from pharos_engine.event_bus import subscribe, unsubscribe
        ps = self._ps()
        v = self._fast_vehicle()
        received = []
        h = subscribe("Pits.Rejected", lambda e: received.append(e))
        ps._on_vehicle_enter(v)
        unsubscribe(h)
        assert id(v) not in ps._active_sessions
        assert len(received) >= 1
        ps.teardown()

    def test_enter_publishes_pits_entered(self):
        from pharos_engine.event_bus import subscribe, unsubscribe
        ps = self._ps()
        v = self._slow_vehicle()
        received = []
        h = subscribe("Pits.Entered", lambda e: received.append(e))
        ps._on_vehicle_enter(v)
        unsubscribe(h)
        assert len(received) >= 1
        ps.teardown()

    def test_exit_publishes_pits_exited(self):
        from pharos_engine.event_bus import subscribe, unsubscribe
        ps = self._ps()
        v = self._slow_vehicle()
        ps._on_vehicle_enter(v)
        received = []
        h = subscribe("Pits.Exited", lambda e: received.append(e))
        ps._on_vehicle_exit(v)
        unsubscribe(h)
        assert len(received) >= 1
        ps.teardown()

    def test_exit_removes_session(self):
        ps = self._ps()
        v = self._slow_vehicle()
        ps._on_vehicle_enter(v)
        ps._on_vehicle_exit(v)
        assert id(v) not in ps._active_sessions
        ps.teardown()

    def test_update_ticks_session(self):
        ps = self._ps()
        v = self._slow_vehicle()
        v.velocity = [0.0, 0.0]
        v._deform = None
        ps._on_vehicle_enter(v)
        ps.update(0.1)
        state = ps._active_sessions.get(id(v))
        if state:
            assert state.time_in_pits > 0.0
        ps.teardown()

    def test_update_no_crash_empty(self):
        ps = self._ps()
        ps.update(0.016)
        ps.teardown()


# =============================================================================
# QualitySystem
# =============================================================================

class TestQualitySystemInit:
    def _qs(self, **kw):
        from systems.quality_system import QualitySystem
        return QualitySystem(**kw)

    def test_instantiates(self):
        qs = self._qs()
        assert qs is not None

    def test_target_ms_computed(self):
        qs = self._qs(target_fps=60.0)
        assert abs(qs._target_ms - 1000.0 / 60.0) < 0.01

    def test_current_tier_label_valid(self):
        qs = self._qs()
        label = qs.current_tier_label
        assert label in ("ultra", "high", "medium", "low")

    def test_debug_str_returns_string(self):
        qs = self._qs()
        s = qs.debug_str()
        assert isinstance(s, str)

    def test_with_clutter_system(self):
        clutter = MagicMock()
        qs = self._qs(clutter_system=clutter)
        assert qs is not None

    def test_with_weather_system(self):
        weather = MagicMock()
        qs = self._qs(weather_system=weather)
        assert qs is not None


class TestQualitySystemUpdate:
    def _qs(self, target_fps=60.0):
        from systems.quality_system import QualitySystem
        return QualitySystem(target_fps=target_fps)

    def test_update_no_crash(self):
        qs = self._qs()
        qs.update(16.67)

    def test_update_multiple_frames(self):
        qs = self._qs()
        for _ in range(30):
            qs.update(16.67)

    def test_downgrade_on_slow_frames(self):
        from systems.quality_system import _TIERS, _DOWNGRADE_FRAMES
        qs = self._qs(target_fps=60.0)
        initial_label = qs.current_tier_label
        for _ in range(100):
            qs.update(200.0)  # far over budget
        # Should have downgraded (label changed or already at lowest)
        final_label = qs.current_tier_label
        if initial_label != "low":
            assert final_label != initial_label or final_label == "low"

    def test_frame_time_cap_applied(self):
        qs = self._qs()
        # A very long frame shouldn't crash and gets capped
        qs.update(5000.0)

    def test_quality_tier_changed_event_published(self):
        from pharos_engine.event_bus import subscribe, unsubscribe
        received = []
        h = subscribe("Quality.TierChanged", lambda e: received.append(e))
        from systems.quality_system import QualitySystem
        qs = QualitySystem(target_fps=60.0)
        unsubscribe(h)
        # At least one published during init (apply_tier)
        assert len(received) >= 1

    def test_upgrade_on_fast_frames(self):
        from systems.quality_system import QualitySystem, _TIERS, _UPGRADE_FRAMES
        qs = QualitySystem(target_fps=60.0)
        # Force to lowest tier
        qs._controller.set_tier(len(_TIERS) - 1)
        initial_idx = qs._controller.tier_index
        # Simulate many fast frames
        for _ in range(_UPGRADE_FRAMES + 5):
            qs.update(1.0)  # 1ms — well under 16.67ms budget
        if initial_idx > 0:
            assert qs._controller.tier_index < initial_idx

    def test_clutter_set_particle_cap_called(self):
        from systems.quality_system import QualitySystem
        clutter = MagicMock()
        clutter.set_particle_cap = MagicMock()
        qs = QualitySystem(clutter_system=clutter, target_fps=60.0)
        clutter.set_particle_cap.assert_called()
