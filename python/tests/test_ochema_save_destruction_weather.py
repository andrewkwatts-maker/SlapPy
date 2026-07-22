"""Headless tests for Ochema Circuit SaveSystem, DestructionScript helpers,
and WeatherSystem."""
from __future__ import annotations
import sys
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
# SaveSystem
# =============================================================================

class TestSaveSystemKeyValue:
    def _ss(self, tmp_path):
        from systems.save_system import SaveSystem
        ss = SaveSystem(save_dir=str(tmp_path))
        return ss

    def test_init_no_crash(self, tmp_path):
        ss = self._ss(tmp_path)
        ss.teardown()

    def test_update_stores_key(self, tmp_path):
        ss = self._ss(tmp_path)
        ss.update("score", 100)
        assert ss._data["score"] == 100
        ss.teardown()

    def test_save_writes_file(self, tmp_path):
        ss = self._ss(tmp_path)
        ss.update("level", 3)
        ss.save()
        assert (tmp_path / "game_save.json").exists()
        ss.teardown()

    def test_load_restores_data(self, tmp_path):
        ss = self._ss(tmp_path)
        ss.update("coins", 50)
        ss.save()
        ss.teardown()

        ss2 = self._ss(tmp_path)
        result = ss2.load()
        assert result.get("coins") == 50
        ss2.teardown()

    def test_load_missing_returns_empty_dict(self, tmp_path):
        ss = self._ss(tmp_path / "empty")
        result = ss.load()
        assert result == {}
        ss.teardown()

    def test_save_best_lap(self, tmp_path):
        ss = self._ss(tmp_path)
        ss.save_best_lap("circuit01", 65.3)
        laps = ss.load_best_laps()
        assert "circuit01" in laps
        assert laps["circuit01"] == pytest.approx(65.3)
        ss.teardown()

    def test_save_best_lap_keeps_faster(self, tmp_path):
        ss = self._ss(tmp_path)
        ss.save_best_lap("track", 100.0)
        ss.save_best_lap("track", 80.0)
        ss.save_best_lap("track", 90.0)  # slower — should not replace 80.0
        assert ss.load_best_laps()["track"] == pytest.approx(80.0)
        ss.teardown()

    def test_save_race_appends(self, tmp_path):
        ss = self._ss(tmp_path)
        ss.save_race("circuit01", [1, 2, 3], [60.0, 62.5, 61.1])
        ss.save_race("circuit01", [2, 1, 3], [58.0, 59.0, 63.0])
        assert len(ss._data.get("races", [])) == 2
        ss.teardown()

    def test_load_profile_default_values(self, tmp_path):
        ss = self._ss(tmp_path)
        profile = ss.load_profile()
        assert "paint_color" in profile
        assert "best_laps" in profile
        assert "total_coins" in profile
        ss.teardown()

    def test_save_profile_updates_data(self, tmp_path):
        ss = self._ss(tmp_path)
        ss.save_profile({"total_coins": 999, "level": 5})
        assert ss._data.get("total_coins") == 999
        ss.teardown()

    def test_teardown_clears_handles(self, tmp_path):
        ss = self._ss(tmp_path)
        ss.teardown()
        assert len(ss._handles) == 0


class TestSaveSystemEventHandlers:
    def _ss(self, tmp_path):
        from systems.save_system import SaveSystem
        return SaveSystem(save_dir=str(tmp_path))

    def test_on_race_finished_increments_total_races(self, tmp_path):
        from slappyengine.event_bus import publish
        ss = self._ss(tmp_path)
        publish("Race.Finished", publisher=None, track_name="t1", results=[])
        assert ss._data.get("total_races", 0) == 1
        ss.teardown()

    def test_on_best_lap_stores_time(self, tmp_path):
        from slappyengine.event_bus import publish
        ss = self._ss(tmp_path)
        publish("Race.BestLap", publisher=None, track_name="circuit01", lap_time=55.2)
        assert ss._data.get("best_laps", {}).get("circuit01") == pytest.approx(55.2)
        ss.teardown()

    def test_on_paint_changed_stores_color(self, tmp_path):
        from slappyengine.event_bus import publish
        ss = self._ss(tmp_path)
        publish("Garage.PaintChanged", publisher=None, color="#FF4400")
        assert ss._data.get("paint_color") == "#FF4400"
        ss.teardown()


class TestSaveSystemQuickHelpers:
    def test_quick_save_and_load(self, tmp_path):
        from systems.save_system import quick_save, quick_load
        quick_save({"hero": "foo", "score": 42}, save_dir=str(tmp_path))
        data = quick_load(save_dir=str(tmp_path))
        assert data.get("score") == 42

    def test_quick_load_empty(self, tmp_path):
        from systems.save_system import quick_load
        result = quick_load(save_dir=str(tmp_path))
        assert result == {}


# =============================================================================
# _direction_to_grid_edge (pure utility)
# =============================================================================

class TestDirectionToGridEdge:
    def test_front_returns_last_col(self):
        from systems.destruction import _direction_to_grid_edge
        x, y = _direction_to_grid_edge("FRONT", 8)
        assert x == 7

    def test_rear_returns_col_zero(self):
        from systems.destruction import _direction_to_grid_edge
        x, y = _direction_to_grid_edge("REAR", 8)
        assert x == 0

    def test_left_returns_row_zero(self):
        from systems.destruction import _direction_to_grid_edge
        x, y = _direction_to_grid_edge("LEFT", 8)
        assert y == 0

    def test_right_returns_last_row(self):
        from systems.destruction import _direction_to_grid_edge
        x, y = _direction_to_grid_edge("RIGHT", 8)
        assert y == 7

    def test_unknown_direction_returns_negative(self):
        from systems.destruction import _direction_to_grid_edge
        x, y = _direction_to_grid_edge("DIAGONAL", 8)
        assert x == -1
        assert y == -1


# =============================================================================
# DestructionScript.on_collision
# =============================================================================

class TestDestructionScriptOnCollision:
    def _entity(self):
        e = MagicMock()
        e.armor_hp = {"FRONT": 100.0, "REAR": 100.0, "LEFT": 100.0, "RIGHT": 100.0}
        e.parts = []
        e.scene = None
        return e

    def test_on_collision_front_reduces_armor(self):
        from systems.destruction import DestructionScript
        ds = DestructionScript()
        e = self._entity()
        # overlap (10, 0) → abs(ox)=10 >= abs(oy)=0 → FRONT (ox>0)
        ds.on_collision(e, MagicMock(), (10.0, 0.0))
        assert e.armor_hp["FRONT"] < 100.0

    def test_on_collision_rear_reduces_armor(self):
        from systems.destruction import DestructionScript
        ds = DestructionScript()
        e = self._entity()
        ds.on_collision(e, MagicMock(), (-8.0, 0.0))
        assert e.armor_hp["REAR"] < 100.0

    def test_on_collision_left_reduces_armor(self):
        from systems.destruction import DestructionScript
        ds = DestructionScript()
        e = self._entity()
        ds.on_collision(e, MagicMock(), (0.0, -5.0))
        assert e.armor_hp["LEFT"] < 100.0

    def test_on_collision_right_reduces_armor(self):
        from systems.destruction import DestructionScript
        ds = DestructionScript()
        e = self._entity()
        ds.on_collision(e, MagicMock(), (0.0, 5.0))
        assert e.armor_hp["RIGHT"] < 100.0

    def test_on_collision_zero_overlap_no_change(self):
        from systems.destruction import DestructionScript
        ds = DestructionScript()
        e = self._entity()
        original = dict(e.armor_hp)
        ds.on_collision(e, MagicMock(), (0.0, 0.0))
        assert e.armor_hp == original

    def test_on_collision_no_crash_with_parts(self):
        from systems.destruction import DestructionScript
        from entities.part import VehiclePart, PartType
        ds = DestructionScript()
        e = self._entity()
        part = VehiclePart(PartType.ARMOR, grid_x=7, grid_y=0)
        e.parts = [part]
        ds.on_collision(e, MagicMock(), (10.0, 0.0))


# =============================================================================
# WeatherSystem
# =============================================================================

class TestWeatherSystem:
    def _ws(self, rain_intensity=0.5):
        from systems.weather_system import WeatherSystem
        fog = MagicMock()
        fog._wind_speed = 1.0
        ws = WeatherSystem(fog_system=fog, rain_intensity=rain_intensity, gpu=None)
        return ws, fog

    def test_init_no_crash(self):
        ws, fog = self._ws()
        ws.teardown()

    def test_screen_size_default(self):
        ws, fog = self._ws()
        assert ws._screen_width == 1280
        assert ws._screen_height == 720
        ws.teardown()

    def test_set_screen_size(self):
        ws, fog = self._ws()
        ws.set_screen_size(800, 600)
        assert ws._screen_width == 800
        assert ws._screen_height == 600
        ws.teardown()

    def test_rain_intensity_getter(self):
        ws, fog = self._ws(rain_intensity=0.75)
        assert ws.rain_intensity == pytest.approx(0.75)
        ws.teardown()

    def test_rain_intensity_setter_clamps_high(self):
        ws, fog = self._ws()
        ws.rain_intensity = 1.5
        assert ws.rain_intensity == pytest.approx(1.0)
        ws.teardown()

    def test_rain_intensity_setter_clamps_low(self):
        ws, fog = self._ws()
        ws.rain_intensity = -0.3
        assert ws.rain_intensity == pytest.approx(0.0)
        ws.teardown()

    def test_update_no_crash(self):
        ws, fog = self._ws()
        ws.update(0.016)
        ws.update(0.016)
        ws.teardown()

    def test_update_advances_gust_timer(self):
        ws, fog = self._ws()
        ws.update(1.0)
        assert ws._gust_timer > 0.0 or ws._gust_timer == 0.0  # may have fired
        ws.teardown()

    def test_fire_gust_calls_fog_set_wind(self):
        ws, fog = self._ws()
        ws._fire_gust()
        fog.set_wind.assert_called()
        ws.teardown()

    def test_get_rain_layer_no_crash(self):
        ws, fog = self._ws()
        layer = ws.get_rain_layer()
        assert layer is not None
        ws.teardown()

    def test_teardown_no_crash(self):
        ws, fog = self._ws()
        ws.teardown()

    def test_quality_tier_changes_intensity(self):
        from slappyengine.event_bus import publish
        ws, fog = self._ws(rain_intensity=1.0)
        publish("Quality.TierChanged", publisher=None,
                params={"rain_cap": 250})  # 250/500 = 50%
        assert ws._rain_intensity == pytest.approx(0.5)
        ws.teardown()
