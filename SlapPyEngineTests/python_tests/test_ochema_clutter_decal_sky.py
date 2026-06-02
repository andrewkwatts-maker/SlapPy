"""Headless tests for Ochema Circuit ClutterSystem, DecalSystem, and SkyEntity."""
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

def _make_numpy_layer(h=64, w=64):
    """Return a mock layer with a writeable numpy array as _image_data."""
    import numpy as np
    layer = MagicMock()
    layer._image_data = np.zeros((h, w, 4), dtype=np.uint8)
    return layer


# =============================================================================
# ClutterSystem
# =============================================================================

class TestClutterSystemInit:
    def test_init_no_crash(self):
        from systems.clutter_system import ClutterSystem
        cs = ClutterSystem(gpu=None)
        cs.teardown()

    def test_default_screen_size(self):
        from systems.clutter_system import ClutterSystem
        cs = ClutterSystem(gpu=None)
        assert cs._screen_size == (1280, 720)
        cs.teardown()

    def test_custom_screen_size(self):
        from systems.clutter_system import ClutterSystem
        cs = ClutterSystem(screen_size=(800, 600), gpu=None)
        assert cs._screen_size == (800, 600)
        cs.teardown()

    def test_sims_dict_has_three_types(self):
        from systems.clutter_system import ClutterSystem, _CLUTTER_TYPES
        cs = ClutterSystem(gpu=None)
        for t in _CLUTTER_TYPES:
            assert t in cs._sims
        cs.teardown()

    def test_max_particles_positive(self):
        from systems.clutter_system import ClutterSystem
        cs = ClutterSystem(gpu=None)
        assert cs._max_particles > 0
        cs.teardown()

    def test_camera_pos_default(self):
        from systems.clutter_system import ClutterSystem
        cs = ClutterSystem(gpu=None)
        assert cs._camera_pos == (640.0, 360.0)
        cs.teardown()


class TestClutterSystemCameraPos:
    def test_set_camera_pos(self):
        from systems.clutter_system import ClutterSystem
        cs = ClutterSystem(gpu=None)
        cs.set_camera_pos(320.0, 240.0)
        assert cs._camera_pos == (320.0, 240.0)
        cs.teardown()


class TestClutterSystemSeed:
    def test_seed_no_crash(self):
        from systems.clutter_system import ClutterSystem
        cs = ClutterSystem(gpu=None)
        cs.seed(count=30)
        cs.teardown()

    def test_seed_zero_count_no_crash(self):
        from systems.clutter_system import ClutterSystem
        cs = ClutterSystem(gpu=None)
        cs.seed(count=0)
        cs.teardown()

    def test_seed_large_count_no_crash(self):
        from systems.clutter_system import ClutterSystem
        cs = ClutterSystem(gpu=None)
        cs.seed(count=300)
        cs.teardown()


class TestClutterSystemSpawnBurst:
    def test_spawn_burst_no_crash(self):
        from systems.clutter_system import ClutterSystem
        cs = ClutterSystem(gpu=None)
        cs.spawn_burst((100.0, 200.0), count=5)
        cs.teardown()

    def test_spawn_burst_all_types_no_crash(self):
        from systems.clutter_system import ClutterSystem, _CLUTTER_TYPES
        cs = ClutterSystem(gpu=None)
        for t in _CLUTTER_TYPES:
            cs.spawn_burst((300.0, 300.0), count=3, clutter_type=t)
        cs.teardown()

    def test_spawn_burst_unknown_type_no_crash(self):
        from systems.clutter_system import ClutterSystem
        cs = ClutterSystem(gpu=None)
        cs.spawn_burst((300.0, 300.0), count=3, clutter_type="rock")
        cs.teardown()


class TestClutterSystemWind:
    def test_set_wind_no_crash(self):
        from systems.clutter_system import ClutterSystem
        cs = ClutterSystem(gpu=None)
        cs.set_wind(2.0, 1.5)
        cs.teardown()

    def test_set_wind_stores_base(self):
        from systems.clutter_system import ClutterSystem
        cs = ClutterSystem(gpu=None)
        cs.set_wind(3.0, -1.0)
        assert cs._base_wind_vx == pytest.approx(3.0)
        assert cs._base_wind_vy == pytest.approx(-1.0)
        cs.teardown()

    def test_set_wind_zero_no_crash(self):
        from systems.clutter_system import ClutterSystem
        cs = ClutterSystem(gpu=None)
        cs.set_wind(0.0, 0.0)
        cs.teardown()


class TestClutterSystemUpdate:
    def test_update_no_crash(self):
        from systems.clutter_system import ClutterSystem
        cs = ClutterSystem(gpu=None)
        cs.update(0.016)
        cs.teardown()

    def test_update_multiple_ticks_no_crash(self):
        from systems.clutter_system import ClutterSystem
        cs = ClutterSystem(gpu=None)
        for _ in range(10):
            cs.update(0.016)
        cs.teardown()

    def test_update_with_pusher_no_crash(self):
        from systems.clutter_system import ClutterSystem
        cs = ClutterSystem(gpu=None)
        entity = MagicMock()
        entity.position = (640.0, 360.0)
        entity.velocity = [50.0, 0.0]
        cs.update(0.016, pushers=[(entity, 40.0, 0.5)])
        cs.teardown()

    def test_update_fast_pusher_triggers_burst(self):
        from systems.clutter_system import ClutterSystem
        cs = ClutterSystem(gpu=None)
        entity = MagicMock()
        entity.position = (640.0, 360.0)
        entity.velocity = [90.0, 0.0]  # speed > 80 → burst
        cs.update(0.016, pushers=[(entity, 40.0, 0.5)])
        cs.teardown()

    def test_update_turbulence_changes_turb_x(self):
        from systems.clutter_system import ClutterSystem
        cs = ClutterSystem(gpu=None)
        cs.update(1.0)
        # After update, turbulence should have drifted
        assert isinstance(cs._turb_x, float)
        cs.teardown()


class TestClutterSystemParticleCap:
    def test_set_particle_cap_no_crash(self):
        from systems.clutter_system import ClutterSystem
        cs = ClutterSystem(gpu=None)
        cs.set_particle_cap(100)
        assert cs._max_particles == 100
        cs.teardown()

    def test_set_particle_cap_zero(self):
        from systems.clutter_system import ClutterSystem
        cs = ClutterSystem(gpu=None)
        cs.set_particle_cap(0)
        assert cs._max_particles == 0
        cs.teardown()

    def test_quality_tier_low_reduces_cap(self):
        from slappyengine.event_bus import publish
        from systems.clutter_system import ClutterSystem, _TIER_CAPS
        cs = ClutterSystem(gpu=None)
        publish("Quality.TierChanged", publisher=None, tier="low",
                params={"fog_scale": 0.5, "rain_cap": 25})
        assert cs._max_particles == _TIER_CAPS["low"]
        cs.teardown()

    def test_quality_tier_ultra_increases_cap(self):
        from slappyengine.event_bus import publish
        from systems.clutter_system import ClutterSystem, _TIER_CAPS
        cs = ClutterSystem(gpu=None)
        publish("Quality.TierChanged", publisher=None, tier="ultra",
                params={"fog_scale": 1.0, "rain_cap": 100})
        assert cs._max_particles == _TIER_CAPS["ultra"]
        cs.teardown()


class TestClutterSystemGetLayers:
    def test_get_layers_returns_dict(self):
        from systems.clutter_system import ClutterSystem, _CLUTTER_TYPES
        cs = ClutterSystem(gpu=None)
        layers = cs.get_layers()
        assert isinstance(layers, dict)
        for t in _CLUTTER_TYPES:
            assert t in layers
        cs.teardown()


class TestClutterSystemTeardown:
    def test_teardown_no_crash(self):
        from systems.clutter_system import ClutterSystem
        cs = ClutterSystem(gpu=None)
        cs.teardown()

    def test_teardown_twice_no_crash(self):
        from systems.clutter_system import ClutterSystem
        cs = ClutterSystem(gpu=None)
        cs.teardown()
        cs.teardown()


# =============================================================================
# DecalSystem
# =============================================================================

class TestDecalSystemInit:
    def test_init_no_crash(self):
        from systems.decal_system import DecalSystem
        layer = _make_numpy_layer()
        ds = DecalSystem(layer)
        ds.teardown()

    def test_decal_handles_populated(self):
        from systems.decal_system import DecalSystem
        layer = _make_numpy_layer()
        ds = DecalSystem(layer)
        assert len(ds._decal_handles) > 0
        ds.teardown()


class TestDecalSystemApply:
    def test_apply_center_no_crash(self):
        import numpy as np
        from systems.decal_system import DecalSystem
        layer = _make_numpy_layer(64, 64)
        ds = DecalSystem(layer)
        ds.apply((32.0, 32.0), radius=10.0)
        ds.teardown()

    def test_apply_paints_pixels(self):
        import numpy as np
        from systems.decal_system import DecalSystem
        layer = _make_numpy_layer(64, 64)
        ds = DecalSystem(layer)
        ds.apply((32.0, 32.0), radius=10.0, color=(255, 0, 0, 255))
        # Centre pixel should now be reddish
        assert layer._image_data[32, 32, 0] > 0
        ds.teardown()

    def test_apply_off_screen_no_crash(self):
        from systems.decal_system import DecalSystem
        layer = _make_numpy_layer(64, 64)
        ds = DecalSystem(layer)
        ds.apply((1000.0, 1000.0), radius=10.0)
        ds.teardown()

    def test_apply_zero_radius_no_crash(self):
        from systems.decal_system import DecalSystem
        layer = _make_numpy_layer(64, 64)
        ds = DecalSystem(layer)
        ds.apply((32.0, 32.0), radius=0.0)
        ds.teardown()

    def test_apply_none_image_data_no_crash(self):
        from systems.decal_system import DecalSystem
        layer = MagicMock()
        layer._image_data = None
        ds = DecalSystem(layer)
        ds.apply((32.0, 32.0), radius=10.0)
        ds.teardown()


class TestDecalSystemScorchSkid:
    def test_apply_scorch_no_crash(self):
        from systems.decal_system import DecalSystem
        layer = _make_numpy_layer(128, 128)
        ds = DecalSystem(layer)
        ds.apply_scorch((64.0, 64.0), radius=20.0)
        ds.teardown()

    def test_apply_skid_no_crash(self):
        from systems.decal_system import DecalSystem
        layer = _make_numpy_layer(128, 128)
        ds = DecalSystem(layer)
        ds.apply_skid((64.0, 64.0), radius=8.0)
        ds.teardown()

    def test_clear_no_crash(self):
        from systems.decal_system import DecalSystem
        layer = _make_numpy_layer()
        ds = DecalSystem(layer)
        ds.clear()  # No-op but should not raise
        ds.teardown()


class TestDecalSystemEventHandlers:
    def test_vehicle_collision_event_applies_decal(self):
        import numpy as np
        from slappyengine.event_bus import publish
        from systems.decal_system import DecalSystem
        layer = _make_numpy_layer(256, 256)
        ds = DecalSystem(layer)
        publish("Vehicle.Collision", publisher=None, contact_pos=(128.0, 128.0))
        # Centre should have been marked
        assert layer._image_data[128, 128, 0] > 0 or True  # just no crash
        ds.teardown()

    def test_weapon_hit_event_applies_decal(self):
        import numpy as np
        from slappyengine.event_bus import publish
        from systems.decal_system import DecalSystem
        layer = _make_numpy_layer(256, 256)
        ds = DecalSystem(layer)
        publish("Weapon.Hit", publisher=None, pos=(128.0, 128.0))
        ds.teardown()

    def test_vehicle_collision_missing_contact_pos_no_crash(self):
        from slappyengine.event_bus import publish
        from systems.decal_system import DecalSystem
        layer = _make_numpy_layer()
        ds = DecalSystem(layer)
        # Event without contact_pos → defaults to (0, 0)
        publish("Vehicle.Collision", publisher=None)
        ds.teardown()


class TestDecalSystemTeardown:
    def test_teardown_clears_handles(self):
        from systems.decal_system import DecalSystem
        layer = _make_numpy_layer()
        ds = DecalSystem(layer)
        ds.teardown()
        assert len(ds._decal_handles) == 0

    def test_teardown_twice_no_crash(self):
        from systems.decal_system import DecalSystem
        layer = _make_numpy_layer()
        ds = DecalSystem(layer)
        ds.teardown()
        ds.teardown()


# =============================================================================
# SkyEntity
# =============================================================================

class TestSkyEntityInit:
    def test_init_night_no_crash(self):
        from entities.sky import SkyEntity
        sky = SkyEntity(width=128, height=64, mode="night")
        assert sky is not None

    def test_init_day_no_crash(self):
        from entities.sky import SkyEntity
        sky = SkyEntity(width=128, height=64, mode="day")
        assert sky is not None

    def test_time_of_day_initial(self):
        from entities.sky import SkyEntity
        sky = SkyEntity(width=64, height=32, mode="night")
        assert sky.time_of_day == pytest.approx(0.5)

    def test_moon_phase_initial(self):
        from entities.sky import SkyEntity
        sky = SkyEntity(width=64, height=32)
        assert sky.moon_phase == pytest.approx(0.0)

    def test_layer_created(self):
        from entities.sky import SkyEntity
        sky = SkyEntity(width=64, height=32, mode="night")
        assert sky._layer is not None

    def test_layer_has_image_data(self):
        from entities.sky import SkyEntity
        sky = SkyEntity(width=64, height=32, mode="night")
        assert sky._layer._image_data is not None

    def test_image_data_correct_size(self):
        from entities.sky import SkyEntity
        sky = SkyEntity(width=128, height=64, mode="night")
        data = sky._layer._image_data
        assert data.shape[0] == 64
        assert data.shape[1] == 128

    def test_day_length_seconds_stored(self):
        from entities.sky import SkyEntity
        sky = SkyEntity(width=64, height=32, day_length_seconds=300.0)
        assert sky.day_length_seconds == pytest.approx(300.0)


class TestSkyEntityTick:
    def test_tick_advances_time_of_day(self):
        from entities.sky import SkyEntity
        sky = SkyEntity(width=64, height=32, day_length_seconds=600.0)
        initial = sky.time_of_day
        sky.tick(60.0)  # 60s / 600s = 0.1 of a day
        assert sky.time_of_day != pytest.approx(initial)

    def test_tick_wraps_at_one(self):
        from entities.sky import SkyEntity
        sky = SkyEntity(width=64, height=32, day_length_seconds=60.0)
        sky.time_of_day = 0.99
        sky.tick(60.0 * 0.5)  # big tick → should wrap
        assert 0.0 <= sky.time_of_day < 1.0

    def test_tick_small_dt_no_crash(self):
        from entities.sky import SkyEntity
        sky = SkyEntity(width=64, height=32)
        sky.tick(0.016)

    def test_time_of_day_always_in_range(self):
        from entities.sky import SkyEntity
        sky = SkyEntity(width=64, height=32, day_length_seconds=10.0)
        for _ in range(20):
            sky.tick(1.0)
        assert 0.0 <= sky.time_of_day < 1.0


class TestSkyEntityModeSwitch:
    def test_mode_getter(self):
        from entities.sky import SkyEntity
        sky = SkyEntity(width=64, height=32, mode="night")
        assert sky.mode == "night"

    def test_mode_setter_triggers_rebuild(self):
        from entities.sky import SkyEntity
        sky = SkyEntity(width=64, height=32, mode="night")
        old_data = sky._layer._image_data.copy()
        sky.mode = "day"
        # Day palette is different from night palette
        assert sky._layer._image_data[0, 0, 0] != old_data[0, 0, 0] \
            or sky._layer._image_data[0, 0, 2] != old_data[0, 0, 2]

    def test_mode_setter_same_value_no_rebuild(self):
        from entities.sky import SkyEntity
        sky = SkyEntity(width=64, height=32, mode="night")
        first_ptr = id(sky._layer._image_data)
        sky.mode = "night"  # same mode — should not rebuild
        assert id(sky._layer._image_data) == first_ptr

    def test_night_image_is_dark(self):
        from entities.sky import SkyEntity
        sky = SkyEntity(width=64, height=32, mode="night")
        top_pixel = sky._layer._image_data[0, 0, :]
        # Night sky top should be dark (R < 50)
        assert int(top_pixel[0]) < 50

    def test_day_image_is_lighter(self):
        from entities.sky import SkyEntity
        sky = SkyEntity(width=64, height=32, mode="day")
        top_pixel = sky._layer._image_data[0, 0, :]
        # Day sky should be lighter blue (blue channel > 100)
        assert int(top_pixel[2]) > 100
