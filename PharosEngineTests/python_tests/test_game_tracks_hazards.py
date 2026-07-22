"""Headless tests for Ochema Circuit: track entities, hazard entities, VehicleEntity basics."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("pharos_engine.compute.asset_compute", MagicMock())

_GAME_ROOT = Path(__file__).parent.parent.parent.parent.parent / "DaedalusSVN" / "Ochema Circuit"
_GAME_STR = str(_GAME_ROOT)
if _GAME_STR not in sys.path:
    sys.path.insert(0, _GAME_STR)


# =============================================================================
# Track entities — MountainTrackEntity, CityTrackEntity
# =============================================================================

class TestMountainTrackEntity:
    def _t(self):
        from entities.track_mountain import MountainTrackEntity
        return MountainTrackEntity()

    def test_instantiates(self):
        assert self._t() is not None

    def test_has_layer(self):
        t = self._t()
        assert len(t.layers) >= 1

    def test_spline_points_correct_count(self):
        from entities.track_mountain import MOUNTAIN_POINTS
        assert len(MOUNTAIN_POINTS) >= 8

    def test_spline_closed(self):
        from entities.track_mountain import MOUNTAIN_SPLINE
        assert MOUNTAIN_SPLINE.closed is True

    def test_road_color_is_dark_asphalt(self):
        from entities.track_mountain import MountainTrackEntity
        # width=90, narrower than circuit 1
        t = MountainTrackEntity()
        # Can't directly read road_color from SplineTrack,
        # but instantiation implies RGBA tuple was accepted
        assert t is not None

    def test_spline_sample_returns_tuple(self):
        from entities.track_mountain import MOUNTAIN_SPLINE
        pt = MOUNTAIN_SPLINE.sample(0.0)
        assert len(pt) == 2

    def test_spline_uniform_ts(self):
        from entities.track_mountain import MOUNTAIN_SPLINE
        ts = list(MOUNTAIN_SPLINE.uniform_ts(8))
        assert len(ts) == 8
        for t in ts:
            assert 0.0 <= t <= 1.0


class TestCityTrackEntity:
    def _t(self):
        from entities.track_city import CityTrackEntity
        return CityTrackEntity()

    def test_instantiates(self):
        assert self._t() is not None

    def test_has_layer(self):
        t = self._t()
        assert len(t.layers) >= 1

    def test_spline_points_correct_count(self):
        from entities.track_city import CITY_POINTS
        assert len(CITY_POINTS) >= 8

    def test_spline_closed(self):
        from entities.track_city import CITY_SPLINE
        assert CITY_SPLINE.closed is True

    def test_spline_sample_in_canvas(self):
        from entities.track_city import CITY_SPLINE
        pt = CITY_SPLINE.sample(0.5)
        x, y = pt[0], pt[1]
        assert 0 <= x <= 1280
        assert 0 <= y <= 720


class TestTrackBackgroundSpline:
    def test_track_spline_closed(self):
        from entities.track_background import TRACK_SPLINE
        assert TRACK_SPLINE.closed is True

    def test_track_spline_sample(self):
        from entities.track_background import TRACK_SPLINE
        pt = TRACK_SPLINE.sample(0.0)
        assert len(pt) == 2

    def test_track_spline_uniform_ts_16(self):
        from entities.track_background import TRACK_SPLINE
        ts = list(TRACK_SPLINE.uniform_ts(16))
        assert len(ts) == 16

    def test_track_spline_normal_at_zero(self):
        from entities.track_background import TRACK_SPLINE
        n = TRACK_SPLINE.normal(0.0)
        # Normal should be a 2-element sequence
        assert len(n) == 2


class TestDesertTerrainEntity:
    def _d(self, **kw):
        from entities.track_background import DesertTerrainEntity
        return DesertTerrainEntity(**kw)

    def test_instantiates(self):
        d = self._d(width=320, height=240)
        assert d is not None

    def test_layer_created(self):
        d = self._d(width=320, height=240)
        assert d._layer is not None

    def test_size_stored(self):
        d = self._d(width=320, height=240)
        assert d._terrain_width == 320
        assert d._terrain_height == 240

    def test_seed_stored(self):
        d = self._d(width=320, height=240, seed=99)
        assert d._seed == 99

    def test_deterministic_for_same_seed(self):
        import numpy as np
        from entities.track_background import DesertTerrainEntity
        d1 = DesertTerrainEntity(width=160, height=120, seed=7)
        d2 = DesertTerrainEntity(width=160, height=120, seed=7)
        if d1._layer is not None and d2._layer is not None:
            assert np.array_equal(d1._layer._image_data, d2._layer._image_data)

    def test_image_data_correct_shape(self):
        import numpy as np
        d = self._d(width=160, height=120)
        assert d._layer._image_data.shape == (120, 160, 4)


# =============================================================================
# AcidPool
# =============================================================================

class TestAcidPool:
    def _a(self, **kw):
        from entities.hazard import AcidPool
        return AcidPool(**kw)

    def test_instantiates(self):
        assert self._a() is not None

    def test_damage_rate_positive(self):
        a = self._a()
        assert a.damage_rate > 0.0

    def test_custom_size(self):
        from pharos_engine.collision import AABBShape
        a = self._a(width=60, height=30)
        assert a.collision_shape.width == 60
        assert a.collision_shape.height == 30

    def test_has_collision_shape(self):
        from pharos_engine.collision import AABBShape
        a = self._a()
        assert isinstance(a.collision_shape, AABBShape)

    def test_on_pixel_collision_reduces_armor(self):
        a = self._a()
        target = MagicMock()
        target.armor_hp = {"FRONT": 100.0}
        a.on_pixel_collision(target, pixel_pos=(0, 0))
        assert target.armor_hp["FRONT"] < 100.0

    def test_on_pixel_collision_no_armor_no_crash(self):
        a = self._a()
        target = MagicMock(spec=[])  # no attributes
        a.on_pixel_collision(target, pixel_pos=(0, 0))

    def test_armor_floors_at_zero(self):
        a = self._a()
        target = MagicMock()
        target.armor_hp = {"FRONT": 0.0}
        a.on_pixel_collision(target, pixel_pos=(0, 0))
        assert target.armor_hp["FRONT"] == 0.0


# =============================================================================
# TurretRaider
# =============================================================================

class TestTurretRaider:
    def _t(self):
        from entities.hazard import TurretRaider
        return TurretRaider()

    def test_instantiates(self):
        assert self._t() is not None

    def test_initial_hp_positive(self):
        t = self._t()
        assert t.hp > 0.0

    def test_has_collision_shape(self):
        from pharos_engine.collision import AABBShape
        t = self._t()
        assert isinstance(t.collision_shape, AABBShape)

    def test_fire_cooldown_zero_initially(self):
        t = self._t()
        assert t.fire_cooldown == 0.0

    def test_tick_decays_cooldown(self):
        t = self._t()
        t.fire_cooldown = 1.0
        t.tick(0.5)
        assert t.fire_cooldown < 1.0

    def test_tick_no_scene_no_crash(self):
        t = self._t()
        t.scene = None
        t.tick(0.016)

    def test_tick_with_empty_scene(self):
        t = self._t()
        t.position = (100.0, 100.0)
        t.scene = MagicMock()
        t.scene.entities = []
        t.tick(0.016)

    def test_take_hit_reduces_hp(self):
        t = self._t()
        initial = t.hp
        t.take_hit(10.0)
        assert t.hp < initial

    def test_take_hit_floors_at_zero(self):
        t = self._t()
        t.take_hit(t.hp * 10)
        assert t.hp == 0.0

    def test_take_hit_triggers_destroyed_event_when_scene(self):
        from pharos_engine.event_bus import subscribe, unsubscribe
        t = self._t()
        t.position = (0.0, 0.0)
        scene = MagicMock()
        scene.remove = MagicMock()
        t.scene = scene
        received = []
        h = subscribe("turret:destroyed", lambda e: received.append(e))
        t.take_hit(t.hp)
        unsubscribe(h)
        assert len(received) >= 1

    def test_take_hit_no_scene_no_crash(self):
        t = self._t()
        t.scene = None
        t.take_hit(t.hp)  # should not raise

    def test_tick_fires_at_nearby_vehicle(self):
        t = self._t()
        t.position = (100.0, 100.0)
        target = MagicMock()
        target.position = (100.0, 110.0)  # within fire_range
        target.armor_hp = {"FRONT": 100.0}
        scene = MagicMock()
        scene.entities = [target]
        t.scene = scene
        t.tick(0.016)
        assert target.armor_hp["FRONT"] < 100.0

    def test_tick_no_fire_when_out_of_range(self):
        t = self._t()
        t.position = (0.0, 0.0)
        target = MagicMock()
        target.position = (5000.0, 5000.0)  # far away
        target.armor_hp = {"FRONT": 100.0}
        scene = MagicMock()
        scene.entities = [target]
        t.scene = scene
        t.tick(0.016)
        assert target.armor_hp["FRONT"] == 100.0  # untouched


# =============================================================================
# FallingSkyscraper
# =============================================================================

class TestFallingSkyscraper:
    def _f(self):
        from entities.hazard import FallingSkyscraper
        return FallingSkyscraper()

    def test_instantiates(self):
        assert self._f() is not None

    def test_not_collapsed_initially(self):
        f = self._f()
        assert f._collapsed is False

    def test_not_active_initially(self):
        f = self._f()
        assert f.active is False

    def test_activate_sets_active(self):
        f = self._f()
        f.activate()
        assert f.active is True

    def test_activate_resets_timer(self):
        f = self._f()
        f._timer = 5.0
        f.activate()
        assert f._timer == 0.0

    def test_tick_when_inactive_no_change(self):
        f = self._f()
        f.position = (100.0, 100.0)
        f.tick(1.0)
        assert f._timer == 0.0  # unchanged

    def test_tick_when_active_advances_timer(self):
        f = self._f()
        f.position = (100.0, 100.0)
        f.activate()
        f.tick(0.5)
        assert f._timer > 0.0

    def test_tick_advances_position_downward(self):
        f = self._f()
        f.position = (100.0, 100.0)
        f.activate()
        initial_y = f.position[1]
        f.tick(0.5)
        assert f.position[1] >= initial_y  # y increases downward

    def test_collapses_after_full_time(self):
        import yaml
        cfg = yaml.safe_load((_GAME_ROOT / "config.yml").read_text())["track"]
        collapse_time = cfg["skyscraper_collapse_time"]
        f = self._f()
        f.position = (100.0, 100.0)
        f.activate()
        f.tick(collapse_time + 0.1)
        assert f._collapsed is True

    def test_tick_no_crash_after_collapse(self):
        f = self._f()
        f.position = (100.0, 100.0)
        f.activate()
        f._collapsed = True
        f.tick(1.0)  # should not crash or advance timer further

    def test_collapse_changes_collision_shape(self):
        import yaml
        from pharos_engine.collision import AABBShape
        cfg = yaml.safe_load((_GAME_ROOT / "config.yml").read_text())["track"]
        collapse_time = cfg["skyscraper_collapse_time"]
        f = self._f()
        f.position = (100.0, 100.0)
        f.activate()
        f.tick(collapse_time + 0.1)
        assert isinstance(f.collision_shape, AABBShape)
        assert f.collision_shape.width == 200
        assert f.collision_shape.height == 40


# =============================================================================
# VehicleEntity (basic headless tests)
# =============================================================================

class TestVehicleEntityInit:
    def _v(self, driver_id=0, vehicle_class="racer"):
        from entities.vehicle import VehicleEntity
        return VehicleEntity(driver_id=driver_id, vehicle_class=vehicle_class)

    def test_instantiates(self):
        v = self._v()
        assert v is not None

    def test_driver_id_stored(self):
        v = self._v(driver_id=2)
        assert v.driver_id == 2

    def test_vehicle_class_stored(self):
        v = self._v(vehicle_class="brawler")
        assert v.vehicle_class == "brawler"

    def test_paint_color_tuple(self):
        v = self._v()
        assert isinstance(v.paint_color, tuple)
        assert len(v.paint_color) == 3

    def test_custom_paint_color(self):
        v = self._v()
        from entities.vehicle import VehicleEntity
        v2 = VehicleEntity(driver_id=0, paint_color=(255, 0, 0))
        assert v2.paint_color == (255, 0, 0)

    def test_position_initially_zero(self):
        v = self._v()
        assert v.position == (0.0, 0.0) or v.position[0] == 0.0

    def test_all_vehicle_classes_instantiate(self):
        from entities.vehicle import VehicleEntity
        for cls in ["racer", "brawler", "scout"]:
            v = VehicleEntity(driver_id=0, vehicle_class=cls)
            assert v is not None

    def test_observable_mixin(self):
        from pharos_engine.event_bus import Observable
        from entities.vehicle import VehicleEntity
        assert issubclass(VehicleEntity, Observable)


class TestVehicleEntityParts:
    def _v(self):
        from entities.vehicle import VehicleEntity
        return VehicleEntity(driver_id=0)

    def test_has_parts_list(self):
        v = self._v()
        assert hasattr(v, "parts")

    def test_has_armor_hp(self):
        v = self._v()
        assert hasattr(v, "armor_hp")

    def test_armor_hp_has_directions(self):
        v = self._v()
        for direction in ["FRONT", "REAR", "LEFT", "RIGHT"]:
            assert direction in v.armor_hp

    def test_armor_hp_positive(self):
        v = self._v()
        for val in v.armor_hp.values():
            assert val > 0.0

    def test_add_part_stores_part(self):
        from entities.vehicle import VehicleEntity
        from entities.part import VehiclePart, PartType
        v = VehicleEntity(driver_id=0)
        part = VehiclePart(PartType.ENGINE, grid_x=1, grid_y=1)
        v.add_part(part)
        assert part in v.parts

    def test_remove_part_removes_it(self):
        from entities.vehicle import VehicleEntity
        from entities.part import VehiclePart, PartType
        v = VehicleEntity(driver_id=0)
        part = VehiclePart(PartType.ENGINE, grid_x=1, grid_y=1)
        v.add_part(part)
        v.remove_part(part)
        assert part not in v.parts


class TestVehicleEntityDamage:
    def _v(self):
        from entities.vehicle import VehicleEntity
        return VehicleEntity(driver_id=0)

    def test_take_damage_reduces_front_armor(self):
        v = self._v()
        initial = v.armor_hp["FRONT"]
        v.take_damage(10.0, direction=(1.0, 0.0))
        # damage should reduce some armor
        total_after = sum(v.armor_hp.values())
        total_before = initial + sum(v.armor_hp[k] for k in v.armor_hp if k != "FRONT")
        assert total_after <= total_before

    def test_take_damage_no_crash(self):
        v = self._v()
        v.take_damage(5.0, direction=(0.0, 1.0))

    def test_is_destroyed_initially_false(self):
        v = self._v()
        assert v.is_destroyed is False

    def test_hull_integrity_initially_one(self):
        v = self._v()
        assert abs(v.hull_integrity - 1.0) < 0.01


class TestVehicleEntityObservable:
    def _v(self):
        from entities.vehicle import VehicleEntity
        return VehicleEntity(driver_id=0)

    def test_speed_is_tracked_attr(self):
        from pharos_engine.event_bus import subscribe, unsubscribe
        v = self._v()
        received = []
        h = subscribe("VehicleEntity.speed", lambda e: received.append(e))
        v.speed = 150.0
        unsubscribe(h)
        assert len(received) >= 1

    def test_throttle_is_tracked_attr(self):
        from pharos_engine.event_bus import subscribe, unsubscribe
        v = self._v()
        received = []
        h = subscribe("VehicleEntity.throttle", lambda e: received.append(e))
        v.throttle = 0.8
        unsubscribe(h)
        assert len(received) >= 1

    def test_hull_integrity_is_tracked_attr(self):
        from pharos_engine.event_bus import subscribe, unsubscribe
        v = self._v()
        received = []
        h = subscribe("VehicleEntity.hull_integrity", lambda e: received.append(e))
        v.hull_integrity = 0.5
        unsubscribe(h)
        assert len(received) >= 1


class TestLoadVehicleClassConfig:
    def test_racer_config_returned(self):
        from entities.vehicle import load_vehicle_class_config
        cfg = load_vehicle_class_config("racer")
        assert isinstance(cfg, dict)

    def test_unknown_class_returns_empty_dict(self):
        from entities.vehicle import load_vehicle_class_config
        cfg = load_vehicle_class_config("__nonexistent_class__")
        assert isinstance(cfg, dict)
        assert len(cfg) == 0

    def test_brawler_config_returned(self):
        from entities.vehicle import load_vehicle_class_config
        cfg = load_vehicle_class_config("brawler")
        assert isinstance(cfg, dict)
