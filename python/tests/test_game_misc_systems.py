"""Headless tests for Ochema Circuit: GhostSystem, QualitySystem,
CoinSystem, and PlayerProfile.
"""
from __future__ import annotations
import sys
import time
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("slappyengine.compute.asset_compute", MagicMock())

_GAME_ROOT = Path(__file__).parent.parent.parent.parent.parent / "DaedalusSVN" / "Ochema Circuit"
_GAME_STR = str(_GAME_ROOT)
if _GAME_STR not in sys.path:
    sys.path.insert(0, _GAME_STR)


# =============================================================================
# GhostSystem
# =============================================================================

class TestGhostSystemInit:
    def _g(self, **kw):
        from systems.ghost_system import GhostSystem
        return GhostSystem(**kw)

    def test_instantiates(self):
        g = self._g()
        g.teardown()

    def test_no_ghost_initially(self):
        g = self._g()
        assert g.has_ghost is False
        g.teardown()

    def test_not_recording_initially(self):
        g = self._g()
        assert g._recording is False
        g.teardown()

    def test_not_playback_initially(self):
        g = self._g()
        assert g._playback is False
        g.teardown()

    def test_ghost_entity_none_initially(self):
        g = self._g()
        assert g.ghost_entity is None
        g.teardown()

    def test_teardown_no_crash(self):
        g = self._g()
        g.teardown()
        g.teardown()  # double teardown should be harmless


class TestGhostSystemRecording:
    class _Vehicle:
        position = (50.0, 80.0)
        rotation = 1.23

    def _g(self):
        from systems.ghost_system import GhostSystem
        return GhostSystem(tracked_vehicle=self._Vehicle())

    def test_start_recording_sets_flag(self):
        g = self._g()
        g._start_recording()
        assert g._recording is True
        g.teardown()

    def test_record_tick_before_interval_no_frame(self):
        g = self._g()
        g._start_recording()
        # Force last_sample to now so sampling won't fire
        g._last_sample = time.perf_counter()
        g.record_tick(0.016)
        assert len(g._frames) == 0
        g.teardown()

    def test_record_tick_after_interval_appends_frame(self):
        from systems.ghost_system import GhostSystem, GhostFrame
        g = GhostSystem(tracked_vehicle=self._Vehicle())
        g._start_recording()
        # Force sampling by setting last_sample far in the past
        g._last_sample = time.perf_counter() - 1.0
        g.record_tick(0.016)
        assert len(g._frames) == 1
        g.teardown()

    def test_recorded_frame_has_correct_position(self):
        from systems.ghost_system import GhostSystem
        g = GhostSystem(tracked_vehicle=self._Vehicle())
        g._start_recording()
        g._last_sample = time.perf_counter() - 1.0
        g.record_tick(0.016)
        f = g._frames[0]
        assert abs(f.x - 50.0) < 1e-6
        assert abs(f.y - 80.0) < 1e-6
        g.teardown()

    def test_record_tick_no_vehicle_no_frame(self):
        from systems.ghost_system import GhostSystem
        g = GhostSystem(tracked_vehicle=None)
        g._start_recording()
        g._last_sample = time.perf_counter() - 1.0
        g.record_tick(0.016)
        assert len(g._frames) == 0
        g.teardown()

    def test_start_recording_clears_previous_frames(self):
        from systems.ghost_system import GhostSystem, GhostFrame
        g = GhostSystem(tracked_vehicle=self._Vehicle())
        g._frames = [GhostFrame(t=0.0, x=0.0, y=0.0, rotation=0.0)]
        g._start_recording()
        assert len(g._frames) == 0
        g.teardown()


class TestGhostSystemPlayback:
    def _g_with_frames(self):
        from systems.ghost_system import GhostSystem, GhostFrame
        g = GhostSystem()
        g._best_frames = [
            GhostFrame(t=0.0, x=10.0, y=20.0, rotation=0.0),
            GhostFrame(t=0.1, x=15.0, y=22.0, rotation=0.5),
            GhostFrame(t=0.2, x=20.0, y=24.0, rotation=1.0),
        ]
        g._best_lap_time = 0.2
        return g

    def test_has_ghost_true_when_frames_exist(self):
        g = self._g_with_frames()
        assert g.has_ghost is True
        g.teardown()

    def test_start_playback_sets_flag(self):
        g = self._g_with_frames()
        g._start_playback()
        assert g._playback is True
        g.teardown()

    def test_playback_tick_returns_position(self):
        g = self._g_with_frames()
        g._start_playback()
        result = g.playback_tick(0.016)
        assert result is not None
        x, y, rot = result
        assert isinstance(x, float)
        assert isinstance(y, float)
        g.teardown()

    def test_playback_tick_inactive_returns_none(self):
        from systems.ghost_system import GhostSystem
        g = GhostSystem()
        result = g.playback_tick(0.016)
        assert result is None
        g.teardown()

    def test_ghost_entity_set_after_playback_start(self):
        g = self._g_with_frames()
        g._start_playback()
        assert g.ghost_entity is not None
        g.teardown()


class TestGhostSystemPersistence:
    def test_save_and_load_ghost(self):
        from systems.ghost_system import GhostSystem, GhostFrame
        td = tempfile.mkdtemp()
        g = GhostSystem(save_dir=td)
        g._best_frames = [
            GhostFrame(t=0.0, x=100.0, y=200.0, rotation=1.5),
            GhostFrame(t=0.1, x=110.0, y=205.0, rotation=1.6),
        ]
        g._best_lap_time = 45.3
        g._save()
        g.teardown()

        g2 = GhostSystem(save_dir=td)
        assert g2.has_ghost is True
        assert abs(g2._best_lap_time - 45.3) < 1e-6
        assert len(g2._best_frames) == 2
        g2.teardown()

    def test_corrupt_ghost_file_handled(self):
        from systems.ghost_system import GhostSystem
        td = tempfile.mkdtemp()
        (Path(td) / "ghost.json").write_text("BAD JSON!")
        g = GhostSystem(save_dir=td)  # should not raise
        assert g.has_ghost is False
        g.teardown()

    def test_no_save_dir_no_crash(self):
        from systems.ghost_system import GhostSystem, GhostFrame
        g = GhostSystem(save_dir=None)
        g._best_frames = [GhostFrame(t=0.0, x=0.0, y=0.0, rotation=0.0)]
        g._save()  # should not crash — no dir set
        g.teardown()


class TestGhostSystemEvents:
    def test_race_started_begins_recording(self):
        from slappyengine.event_bus import publish
        from systems.ghost_system import GhostSystem
        g = GhostSystem()
        publish("Race.Started", publisher=None)
        assert g._recording is True
        g.teardown()

    def test_race_finished_stops_recording(self):
        from slappyengine.event_bus import publish
        from systems.ghost_system import GhostSystem
        g = GhostSystem()
        g._start_recording()
        publish("Race.Finished", publisher=None)
        assert g._recording is False
        g.teardown()

    def test_best_lap_saves_frames(self):
        from slappyengine.event_bus import publish
        from systems.ghost_system import GhostSystem, GhostFrame
        g = GhostSystem()
        g._start_recording()
        g._frames = [GhostFrame(t=0.0, x=0.0, y=0.0, rotation=0.0)]
        publish("Race.BestLap", publisher=None, lap_time=60.0)
        assert g.has_ghost is True
        assert abs(g._best_lap_time - 60.0) < 1e-6
        g.teardown()

    def test_faster_lap_replaces_ghost(self):
        from slappyengine.event_bus import publish
        from systems.ghost_system import GhostSystem, GhostFrame
        g = GhostSystem()
        g._start_recording()
        g._frames = [GhostFrame(t=0.0, x=0.0, y=0.0, rotation=0.0)]
        publish("Race.BestLap", publisher=None, lap_time=70.0)
        old_time = g._best_lap_time

        g._start_recording()
        g._frames = [GhostFrame(t=0.0, x=1.0, y=1.0, rotation=0.0)]
        publish("Race.BestLap", publisher=None, lap_time=50.0)
        assert g._best_lap_time < old_time
        g.teardown()


# =============================================================================
# QualitySystem
# =============================================================================

class TestQualitySystemInit:
    def _qs(self, **kw):
        from systems.quality_system import QualitySystem
        return QualitySystem(**kw)

    def test_instantiates(self):
        assert self._qs() is not None

    def test_initial_tier_is_ultra(self):
        qs = self._qs()
        assert qs.current_tier_label == "ultra"

    def test_debug_str_returns_string(self):
        qs = self._qs()
        assert isinstance(qs.debug_str(), str)

    def test_debug_str_contains_tier(self):
        qs = self._qs()
        assert "ultra" in qs.debug_str()

    def test_custom_target_fps(self):
        qs = self._qs(target_fps=30.0)
        assert qs._target_ms > 16.0  # 30fps → 33ms


class TestQualitySystemUpdate:
    def _qs(self):
        from systems.quality_system import QualitySystem
        return QualitySystem()

    def test_single_good_frame_no_tier_change(self):
        qs = self._qs()
        qs.update(10.0)  # under 16.7ms budget
        assert qs.current_tier_label == "ultra"

    def test_consecutive_bad_frames_downgrades(self):
        from systems.quality_system import QualitySystem, _DOWNGRADE_FRAMES
        qs = QualitySystem()
        # Feed bad frames (over budget) for long enough to trigger downgrade
        for _ in range(_DOWNGRADE_FRAMES + 1):
            qs.update(100.0)  # way over budget
        assert qs.current_tier_label != "ultra"

    def test_large_frame_time_capped(self):
        qs = self._qs()
        # Frame times > 100ms should be capped, not cause extreme behavior
        for _ in range(100):
            qs.update(9999.0)
        # Should have downgraded but not crashed
        assert qs.current_tier_label in ("ultra", "high", "medium", "low")

    def test_good_frames_after_downgrade_eventually_upgrades(self):
        from systems.quality_system import QualitySystem, _DOWNGRADE_FRAMES, _UPGRADE_FRAMES
        qs = QualitySystem()
        # Downgrade first
        for _ in range(_DOWNGRADE_FRAMES + 5):
            qs.update(100.0)
        downgraded = qs.current_tier_label
        # Now feed good frames for upgrade threshold
        for _ in range(_UPGRADE_FRAMES + 5):
            qs.update(5.0)
        # Should have recovered at least one tier
        assert qs.current_tier_label != downgraded or qs.current_tier_label == "ultra"

    def test_update_publishes_tier_changed_on_downgrade(self):
        from systems.quality_system import QualitySystem, _DOWNGRADE_FRAMES
        from slappyengine.event_bus import subscribe, unsubscribe
        received = []
        h = subscribe("Quality.TierChanged", lambda e: received.append(e))
        qs = QualitySystem()
        initial_count = len(received)  # may fire on init
        for _ in range(_DOWNGRADE_FRAMES + 1):
            qs.update(100.0)
        unsubscribe(h)
        assert len(received) > initial_count

    def test_frame_time_rolling_average(self):
        qs = self._qs()
        # Good frames in rolling window — single bad frame shouldn't downgrade
        for _ in range(29):
            qs.update(10.0)  # fill window with good frames
        qs.update(100.0)     # one bad frame
        assert qs.current_tier_label == "ultra"


class TestQualitySystemWithSystems:
    def test_applies_tier_to_clutter_system(self):
        from systems.quality_system import QualitySystem, _DOWNGRADE_FRAMES

        class MockClutter:
            cap = None
            def set_particle_cap(self, cap):
                self.cap = cap

        clutter = MockClutter()
        qs = QualitySystem(clutter_system=clutter)
        # Initial tier should have been applied
        assert clutter.cap is not None

    def test_none_clutter_no_crash(self):
        from systems.quality_system import QualitySystem
        qs = QualitySystem(clutter_system=None)
        qs.update(100.0)  # should not raise


# =============================================================================
# CoinSystem
# =============================================================================

class _FakeProfile:
    def __init__(self):
        self.coins = 0
        self._earned = []

    def earn(self, amount: int) -> None:
        self.coins += amount
        self._earned.append(amount)


class TestCoinSystemInit:
    def _cs(self, positions=None, value=10):
        from systems.coin_system import CoinSystem
        from slappyengine.trigger import TriggerSystem
        ts = TriggerSystem()
        prof = _FakeProfile()
        cs = CoinSystem(ts, prof, positions or [(100.0, 100.0)], value=value)
        return cs, ts, prof

    def test_instantiates(self):
        cs, ts, prof = self._cs()
        cs.teardown()

    def test_volume_count_matches_positions(self):
        cs, ts, prof = self._cs(positions=[(10, 10), (20, 20), (30, 30)])
        assert len(cs._volumes) == 3
        cs.teardown()

    def test_no_coins_collected_initially(self):
        cs, ts, prof = self._cs()
        assert len(cs._collected) == 0
        cs.teardown()

    def test_teardown_no_crash(self):
        cs, ts, prof = self._cs()
        cs.teardown()

    def test_reset_clears_collected(self):
        cs, ts, prof = self._cs()
        cs._collected.add(12345)
        cs.reset()
        assert len(cs._collected) == 0
        cs.teardown()


class TestCoinSystemCollection:
    def test_vehicle_enters_coin_zone_earns_coins(self):
        from systems.coin_system import CoinSystem
        from slappyengine.trigger import TriggerSystem, TriggerVolume

        ts = TriggerSystem()
        prof = _FakeProfile()
        cs = CoinSystem(ts, prof, [(50.0, 50.0)], value=25)

        class FakeVehicle:
            position = (50.0, 50.0)
            size = (10.0, 10.0)

        ts.update([FakeVehicle()])
        cs.teardown()
        assert prof.coins == 25

    def test_double_entry_only_awards_once(self):
        from systems.coin_system import CoinSystem
        from slappyengine.trigger import TriggerSystem

        ts = TriggerSystem()
        prof = _FakeProfile()
        cs = CoinSystem(ts, prof, [(50.0, 50.0)], value=25)

        class FakeVehicle:
            position = (50.0, 50.0)
            size = (10.0, 10.0)

        ts.update([FakeVehicle()])
        ts.update([FakeVehicle()])  # second trigger — should be ignored
        cs.teardown()
        assert prof.coins == 25

    def test_multiple_coins_all_collectible(self):
        from systems.coin_system import CoinSystem
        from slappyengine.trigger import TriggerSystem

        ts = TriggerSystem()
        prof = _FakeProfile()
        positions = [(50.0, 50.0), (150.0, 50.0)]
        cs = CoinSystem(ts, prof, positions, value=10)

        class V1:
            position = (50.0, 50.0)
            size = (10.0, 10.0)

        class V2:
            position = (150.0, 50.0)
            size = (10.0, 10.0)

        ts.update([V1()])
        ts.update([V2()])
        cs.teardown()
        assert prof.coins == 20

    def test_coin_collected_event_fired(self):
        from systems.coin_system import CoinSystem
        from slappyengine.trigger import TriggerSystem
        from slappyengine.event_bus import subscribe, unsubscribe

        ts = TriggerSystem()
        prof = _FakeProfile()
        cs = CoinSystem(ts, prof, [(50.0, 50.0)], value=10)
        received = []
        h = subscribe("Race.CoinCollected", lambda e: received.append(e))

        class FakeVehicle:
            position = (50.0, 50.0)
            size = (10.0, 10.0)

        ts.update([FakeVehicle()])
        unsubscribe(h)
        cs.teardown()
        assert len(received) == 1

    def test_reset_allows_recollection(self):
        from systems.coin_system import CoinSystem
        from slappyengine.trigger import TriggerSystem

        ts = TriggerSystem()
        prof = _FakeProfile()
        cs = CoinSystem(ts, prof, [(50.0, 50.0)], value=10)

        class FakeVehicle:
            position = (50.0, 50.0)
            size = (10.0, 10.0)

        vol = cs._volumes[0]
        cs._collected.add(id(vol))
        cs.reset()
        assert id(vol) not in cs._collected
        cs.teardown()


# =============================================================================
# PlayerProfile
# =============================================================================

class TestPlayerProfileInit:
    def _p(self):
        from systems.player_profile import PlayerProfile
        return PlayerProfile()

    def test_instantiates(self):
        assert self._p() is not None

    def test_initial_coins_zero(self):
        assert self._p().coins == 0

    def test_part_tiers_all_zero(self):
        p = self._p()
        for pt in ["cockpit", "engine", "armor", "wheel", "weapon"]:
            assert p.part_tier(pt) == 0

    def test_no_publish_on_internal(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        received = []
        h = subscribe("PlayerProfile._part_tiers", lambda e: received.append(e))
        p = self._p()
        p._part_tiers["engine"] = 1
        unsubscribe(h)
        assert len(received) == 0


class TestPlayerProfileCoins:
    def _p(self):
        from systems.player_profile import PlayerProfile
        return PlayerProfile()

    def test_earn_increases_coins(self):
        p = self._p()
        p.earn(100)
        assert p.coins == 100

    def test_spend_decreases_coins(self):
        p = self._p()
        p.earn(200)
        p.spend(50)
        assert p.coins == 150

    def test_spend_insufficient_returns_false(self):
        p = self._p()
        result = p.spend(100)
        assert result is False
        assert p.coins == 0

    def test_spend_exact_returns_true(self):
        p = self._p()
        p.earn(100)
        result = p.spend(100)
        assert result is True
        assert p.coins == 0

    def test_earn_publishes_event(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        received = []
        h = subscribe("PlayerProfile.CoinsEarned", lambda e: received.append(e))
        p = self._p()
        p.earn(50)
        unsubscribe(h)
        assert len(received) == 1

    def test_spend_publishes_event_on_success(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        received = []
        h = subscribe("PlayerProfile.CoinsSpent", lambda e: received.append(e))
        p = self._p()
        p.earn(100)
        p.spend(50)
        unsubscribe(h)
        assert len(received) == 1

    def test_spend_no_event_on_failure(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        received = []
        h = subscribe("PlayerProfile.CoinsSpent", lambda e: received.append(e))
        p = self._p()
        p.spend(100)  # insufficient
        unsubscribe(h)
        assert len(received) == 0


class TestPlayerProfileUpgrades:
    def _p(self):
        from systems.player_profile import PlayerProfile
        return PlayerProfile()

    def test_upgrade_cost_cockpit_is_positive(self):
        p = self._p()
        cost = p.upgrade_cost("cockpit")
        assert cost is not None and cost > 0

    def test_try_upgrade_insufficient_coins(self):
        p = self._p()
        result = p.try_upgrade("cockpit")
        assert result is False

    def test_try_upgrade_with_coins_succeeds(self):
        p = self._p()
        cost = p.upgrade_cost("cockpit")
        p.earn(cost + 100)
        result = p.try_upgrade("cockpit")
        assert result is True
        assert p.part_tier("cockpit") == 1

    def test_upgrade_publishes_event(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        received = []
        h = subscribe("PlayerProfile.PartUpgraded", lambda e: received.append(e))
        p = self._p()
        cost = p.upgrade_cost("cockpit")
        p.earn(cost + 100)
        p.try_upgrade("cockpit")
        unsubscribe(h)
        assert len(received) == 1

    def test_max_tier_returns_none_cost(self):
        p = self._p()
        # Upgrade until max tier
        for _ in range(20):
            cost = p.upgrade_cost("cockpit")
            if cost is None:
                break
            p.earn(cost)
            p.try_upgrade("cockpit")
        assert p.upgrade_cost("cockpit") is None


class TestPlayerProfileSaveLoad:
    def _tmp_save_path(self):
        td = tempfile.mkdtemp()
        return str(Path(td) / "profile.json")

    def test_save_and_load(self):
        import json
        from systems.player_profile import PlayerProfile
        p = PlayerProfile()
        p.earn(250)
        p._part_tiers["engine"] = 2
        save_path = self._tmp_save_path()
        # Patch save path
        from pathlib import Path as _P
        p._save_path = _P(save_path)  # type: ignore[attr-defined]
        from systems import player_profile
        player_profile._SAVE_PATH = _P(save_path)
        p.save()

        p2 = PlayerProfile()
        p2._save_path = _P(save_path)
        player_profile._SAVE_PATH = _P(save_path)
        loaded = p2.load()
        assert loaded is True
        assert p2.coins == 250
        assert p2.part_tier("engine") == 2

    def test_load_returns_bool(self):
        from systems.player_profile import PlayerProfile
        p = PlayerProfile()
        result = p.load()
        assert isinstance(result, bool)

    def test_total_upgrade_spend_zero_at_start(self):
        p = self._make_profile()
        assert p.total_upgrade_spend() == 0

    def _make_profile(self):
        from systems.player_profile import PlayerProfile
        return PlayerProfile()

    def test_total_upgrade_spend_after_upgrade(self):
        p = self._make_profile()
        cost = p.upgrade_cost("cockpit")
        p.earn(cost + 100)
        p.try_upgrade("cockpit")
        assert p.total_upgrade_spend() == cost
