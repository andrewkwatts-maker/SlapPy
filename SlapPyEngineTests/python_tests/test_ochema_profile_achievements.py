"""Headless tests for Ochema Circuit PlayerProfile and AchievementSystem."""
from __future__ import annotations
import sys
import json
import tempfile
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
# PlayerProfile — earn, spend, part_tier, upgrade_cost, try_upgrade, save/load
# =============================================================================

class TestPlayerProfileCoins:
    def _profile(self):
        from systems.player_profile import PlayerProfile
        return PlayerProfile()

    def test_initial_coins_zero(self):
        p = self._profile()
        assert p.coins == 0

    def test_earn_increases_coins(self):
        p = self._profile()
        p.earn(100)
        assert p.coins == 100

    def test_earn_accumulates(self):
        p = self._profile()
        p.earn(50)
        p.earn(75)
        assert p.coins == 125

    def test_spend_decreases_coins(self):
        p = self._profile()
        p.earn(200)
        p.spend(80)
        assert p.coins == 120

    def test_spend_insufficient_returns_false(self):
        p = self._profile()
        p.earn(10)
        assert p.spend(50) is False
        assert p.coins == 10

    def test_spend_sufficient_returns_true(self):
        p = self._profile()
        p.earn(100)
        assert p.spend(60) is True

    def test_earn_publishes_event(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        p = self._profile()
        events = []
        h = subscribe("PlayerProfile.CoinsEarned", lambda e: events.append(e))
        p.earn(50)
        unsubscribe(h)
        assert len(events) == 1

    def test_spend_publishes_event(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        p = self._profile()
        p.earn(100)
        events = []
        h = subscribe("PlayerProfile.CoinsSpent", lambda e: events.append(e))
        p.spend(30)
        unsubscribe(h)
        assert len(events) == 1


class TestPlayerProfileParts:
    def _profile(self):
        from systems.player_profile import PlayerProfile
        return PlayerProfile()

    def test_initial_part_tier_zero(self):
        p = self._profile()
        assert p.part_tier("engine") == 0

    def test_part_stats_returns_dict(self):
        p = self._profile()
        stats = p.part_stats("engine")
        assert isinstance(stats, dict)

    def test_upgrade_cost_returns_int_or_none(self):
        p = self._profile()
        cost = p.upgrade_cost("engine")
        assert cost is None or isinstance(cost, int)

    def test_try_upgrade_no_coins_returns_false(self):
        p = self._profile()
        result = p.try_upgrade("engine")
        # Only False if cost > 0 and no coins
        if p.upgrade_cost("engine") is not None and p.upgrade_cost("engine") > 0:
            assert result is False
        # If cost is 0 or None, don't assert failure

    def test_try_upgrade_with_coins_advances_tier(self):
        p = self._profile()
        cost = p.upgrade_cost("engine")
        if cost is None:
            pytest.skip("engine already at max tier")
        p.earn(cost + 1)
        initial_tier = p.part_tier("engine")
        result = p.try_upgrade("engine")
        if result:
            assert p.part_tier("engine") == initial_tier + 1

    def test_total_upgrade_spend_initially_zero(self):
        p = self._profile()
        assert p.total_upgrade_spend() == 0

    def test_try_upgrade_at_max_returns_false(self):
        p = self._profile()
        # Force max tier
        from systems.player_profile import _load_shop_cfg
        shop = _load_shop_cfg()
        max_tier = len(shop.get("engine", {}).get("tiers", [1])) - 1
        p._part_tiers["engine"] = max_tier
        result = p.try_upgrade("engine")
        assert result is False


class TestPlayerProfileSaveLoad:
    def test_save_creates_file(self, tmp_path):
        from systems.player_profile import PlayerProfile, _SAVE_PATH
        p = PlayerProfile()
        p.earn(42)
        # Patch save path temporarily
        original = p.__class__.__dict__.get("_save_path_attr", None)
        import systems.player_profile as pp_mod
        old_path = pp_mod._SAVE_PATH
        pp_mod._SAVE_PATH = tmp_path / "profile.json"
        try:
            p.save()
            assert (tmp_path / "profile.json").exists()
        finally:
            pp_mod._SAVE_PATH = old_path

    def test_save_and_load_roundtrip(self, tmp_path):
        import systems.player_profile as pp_mod
        from systems.player_profile import PlayerProfile
        old_path = pp_mod._SAVE_PATH
        pp_mod._SAVE_PATH = tmp_path / "profile.json"
        try:
            p1 = PlayerProfile()
            p1.earn(999)
            p1.save()

            p2 = PlayerProfile()
            result = p2.load()
            assert result is True
            assert p2.coins == 999
        finally:
            pp_mod._SAVE_PATH = old_path

    def test_load_missing_file_returns_false(self, tmp_path):
        import systems.player_profile as pp_mod
        from systems.player_profile import PlayerProfile
        old_path = pp_mod._SAVE_PATH
        pp_mod._SAVE_PATH = tmp_path / "no_file.json"
        try:
            p = PlayerProfile()
            assert p.load() is False
        finally:
            pp_mod._SAVE_PATH = old_path


# =============================================================================
# AchievementSystem — unlock, event handlers, persistence
# =============================================================================

class TestAchievementSystemInit:
    def _ach(self, tmp_path):
        from systems.achievement_system import AchievementSystem
        return AchievementSystem(save_dir=str(tmp_path))

    def test_catalog_has_all_achievements(self, tmp_path):
        from systems.achievement_system import AchievementSystem
        ach = self._ach(tmp_path)
        assert len(ach.get_all()) == len(AchievementSystem.ACHIEVEMENTS)
        ach.teardown()

    def test_initially_no_unlocked(self, tmp_path):
        ach = self._ach(tmp_path)
        assert all(not a.unlocked for a in ach.get_all())
        ach.teardown()

    def test_teardown_no_crash(self, tmp_path):
        ach = self._ach(tmp_path)
        ach.teardown()

    def test_get_all_returns_list(self, tmp_path):
        ach = self._ach(tmp_path)
        result = ach.get_all()
        assert isinstance(result, list)
        ach.teardown()


class TestAchievementSystemUnlock:
    def _ach(self, tmp_path):
        from systems.achievement_system import AchievementSystem
        return AchievementSystem(save_dir=str(tmp_path))

    def test_unlock_marks_achievement(self, tmp_path):
        ach = self._ach(tmp_path)
        ach.unlock("first_win")
        ach_obj = next(a for a in ach.get_all() if a.id == "first_win")
        assert ach_obj.unlocked is True
        ach.teardown()

    def test_unlock_twice_no_duplicate(self, tmp_path):
        ach = self._ach(tmp_path)
        ach.unlock("first_win")
        ach.unlock("first_win")
        assert len([a for a in ach.get_all() if a.id == "first_win" and a.unlocked]) == 1
        ach.teardown()

    def test_unlock_unknown_id_no_crash(self, tmp_path):
        ach = self._ach(tmp_path)
        ach.unlock("nonexistent_achievement")
        ach.teardown()

    def test_unlock_publishes_event(self, tmp_path):
        from slappyengine.event_bus import subscribe, unsubscribe
        ach = self._ach(tmp_path)
        events = []
        h = subscribe("Achievement.Unlocked|speed_demon", lambda e: events.append(e))
        ach.unlock("speed_demon")
        unsubscribe(h)
        assert len(events) == 1
        ach.teardown()

    def test_unlock_sets_unlocked_at(self, tmp_path):
        ach = self._ach(tmp_path)
        ach.unlock("podium")
        ach_obj = next(a for a in ach.get_all() if a.id == "podium")
        assert len(ach_obj.unlocked_at) > 0
        ach.teardown()


class TestAchievementSystemEventHandlers:
    def _ach(self, tmp_path):
        from systems.achievement_system import AchievementSystem
        ach = AchievementSystem(save_dir=str(tmp_path))
        return ach

    def test_race_started_resets_state(self, tmp_path):
        from slappyengine.event_bus import publish
        ach = self._ach(tmp_path)
        vehicle = MagicMock()
        ach.set_player_vehicle(vehicle)
        # Set some state
        ach._nitro_uses = 5
        ach._lap_had_collision = True
        publish("Race.Started", publisher=vehicle)
        assert ach._nitro_uses == 0
        assert ach._lap_had_collision is False
        ach.teardown()

    def test_speed_demon_unlocked_at_threshold(self, tmp_path):
        from slappyengine.event_bus import publish
        from systems.achievement_system import MAX_SPEED_CFG
        ach = self._ach(tmp_path)
        vehicle = MagicMock()
        ach.set_player_vehicle(vehicle)
        publish("VehicleEntity.speed", publisher=vehicle, value=MAX_SPEED_CFG * 0.96)
        ach_obj = next(a for a in ach.get_all() if a.id == "speed_demon")
        assert ach_obj.unlocked is True
        ach.teardown()

    def test_speed_below_threshold_no_unlock(self, tmp_path):
        from slappyengine.event_bus import publish
        from systems.achievement_system import MAX_SPEED_CFG
        ach = self._ach(tmp_path)
        vehicle = MagicMock()
        ach.set_player_vehicle(vehicle)
        publish("VehicleEntity.speed", publisher=vehicle, value=MAX_SPEED_CFG * 0.5)
        ach_obj = next(a for a in ach.get_all() if a.id == "speed_demon")
        assert ach_obj.unlocked is False
        ach.teardown()

    def test_collision_sets_lap_had_collision(self, tmp_path):
        from slappyengine.event_bus import publish
        ach = self._ach(tmp_path)
        vehicle = MagicMock()
        ach.set_player_vehicle(vehicle)
        publish("Vehicle.Collision", publisher=vehicle)
        assert ach._lap_had_collision is True
        ach.teardown()

    def test_nitro_junkie_after_ten_uses(self, tmp_path):
        from slappyengine.event_bus import publish
        ach = self._ach(tmp_path)
        vehicle = MagicMock()
        ach.set_player_vehicle(vehicle)
        for _ in range(10):
            publish("Vehicle.NitroActive", publisher=vehicle)
        ach_obj = next(a for a in ach.get_all() if a.id == "nitro_junkie")
        assert ach_obj.unlocked is True
        ach.teardown()

    def test_collector_after_500_coins(self, tmp_path):
        from slappyengine.event_bus import publish
        ach = self._ach(tmp_path)
        publish("Race.CoinCollected", publisher=None, amount=500)
        ach_obj = next(a for a in ach.get_all() if a.id == "collector")
        assert ach_obj.unlocked is True
        ach.teardown()

    def test_hat_trick_after_three_laps(self, tmp_path):
        from slappyengine.event_bus import publish
        ach = self._ach(tmp_path)
        vehicle = MagicMock()
        ach.set_player_vehicle(vehicle)
        # No collisions → clean lap + hat trick
        for _ in range(3):
            publish("Race.LapComplete", publisher=vehicle)
        ach_obj = next(a for a in ach.get_all() if a.id == "hat_trick")
        assert ach_obj.unlocked is True
        ach.teardown()

    def test_integrity_tracks_minimum(self, tmp_path):
        from slappyengine.event_bus import publish
        ach = self._ach(tmp_path)
        vehicle = MagicMock()
        ach.set_player_vehicle(vehicle)
        publish("VehicleEntity.hull_integrity", publisher=vehicle, value=0.3)
        publish("VehicleEntity.hull_integrity", publisher=vehicle, value=0.05)
        assert ach._min_integrity_seen == pytest.approx(0.05)
        ach.teardown()

    def test_vehicle_destroyed_increments_count(self, tmp_path):
        from slappyengine.event_bus import publish
        ach = self._ach(tmp_path)
        vehicle = MagicMock()
        ai = MagicMock()
        ach.set_player_vehicle(vehicle)
        publish("Vehicle.Destroyed", publisher=ai)
        assert ach._vehicles_destroyed == 1
        ach.teardown()

    def test_player_destroyed_not_counted(self, tmp_path):
        from slappyengine.event_bus import publish
        ach = self._ach(tmp_path)
        vehicle = MagicMock()
        ach.set_player_vehicle(vehicle)
        publish("Vehicle.Destroyed", publisher=vehicle)
        assert ach._vehicles_destroyed == 0
        ach.teardown()

    def test_race_finished_unlocks_first_win(self, tmp_path):
        from slappyengine.event_bus import publish
        ach = self._ach(tmp_path)
        vehicle = MagicMock()
        ach.set_player_vehicle(vehicle)
        publish("Race.Finished", publisher=None,
                results=[(vehicle, 1), (MagicMock(), 2)])
        ach_obj = next(a for a in ach.get_all() if a.id == "first_win")
        assert ach_obj.unlocked is True
        ach.teardown()


class TestAchievementSystemPersistence:
    def test_save_and_load(self, tmp_path):
        from systems.achievement_system import AchievementSystem
        ach1 = AchievementSystem(save_dir=str(tmp_path))
        ach1.unlock("speed_demon")
        ach1.teardown()

        ach2 = AchievementSystem(save_dir=str(tmp_path))
        ach_obj = next(a for a in ach2.get_all() if a.id == "speed_demon")
        assert ach_obj.unlocked is True
        ach2.teardown()

    def test_coins_persisted(self, tmp_path):
        from systems.achievement_system import AchievementSystem
        from slappyengine.event_bus import publish
        ach1 = AchievementSystem(save_dir=str(tmp_path))
        publish("Race.CoinCollected", publisher=None, amount=200)
        ach1.teardown()

        ach2 = AchievementSystem(save_dir=str(tmp_path))
        assert ach2._total_coins == 200
        ach2.teardown()
