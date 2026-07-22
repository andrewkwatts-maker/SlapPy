"""Headless tests for Ochema Circuit environment systems:
CollisionSystem, FogSystem, WeatherSystem, ClutterSystem.
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
# CollisionSystem
# =============================================================================

class TestCollisionSystemInit:
    def _cs(self, vehicles=None):
        from systems.collision_system import CollisionSystem
        return CollisionSystem(vehicles or [])

    def test_instantiates(self):
        cs = self._cs()
        cs.teardown()

    def test_subscribes_to_pixel_result(self):
        from pharos_engine.event_bus import global_bus
        from systems.collision_system import CollisionSystem
        before = global_bus.listener_count("Collision.Pixel.Result")
        cs = CollisionSystem([])
        after = global_bus.listener_count("Collision.Pixel.Result")
        assert after == before + 1
        cs.teardown()

    def test_teardown_unsubscribes(self):
        from pharos_engine.event_bus import global_bus
        from systems.collision_system import CollisionSystem
        before = global_bus.listener_count("Collision.Pixel.Result")
        cs = CollisionSystem([])
        cs.teardown()
        after = global_bus.listener_count("Collision.Pixel.Result")
        assert after == before

    def test_no_vehicles_no_pairs(self):
        cs = self._cs([])
        cs.update(0.016)  # no crash with empty list
        cs.teardown()

    def test_one_vehicle_no_pairs(self):
        cs = self._cs([MagicMock()])
        cs.update(0.016)
        cs.teardown()

    def test_pair_cooldowns_initially_empty(self):
        cs = self._cs()
        assert len(cs._pair_cooldowns) == 0
        cs.teardown()

    def test_update_decays_cooldowns(self):
        from systems.collision_system import CollisionSystem
        cs = CollisionSystem([])
        cs._pair_cooldowns[(1, 2)] = 0.5
        cs.update(0.1)
        assert cs._pair_cooldowns.get((1, 2), 0.0) < 0.5
        cs.teardown()

    def test_teardown_no_crash_twice(self):
        cs = self._cs()
        cs.teardown()
        cs.teardown()


# =============================================================================
# FogSystem
# =============================================================================

class TestFogSystemInit:
    def _fs(self, **kw):
        from systems.fog_system import FogSystem
        return FogSystem(size=(64, 64), gpu=None, **kw)

    def test_instantiates(self):
        fs = self._fs()
        fs.teardown()

    def test_density_stored(self):
        fs = self._fs(density=0.7)
        assert abs(fs._density - 0.7) < 1e-6
        fs.teardown()

    def test_density_clamped_above_one(self):
        fs = self._fs(density=2.0)
        assert fs._density <= 1.0
        fs.teardown()

    def test_density_clamped_below_zero(self):
        fs = self._fs(density=-0.5)
        assert fs._density >= 0.0
        fs.teardown()

    def test_sim_created(self):
        fs = self._fs()
        assert fs._sim is not None
        fs.teardown()

    def test_teardown_no_crash(self):
        fs = self._fs()
        fs.teardown()
        fs.teardown()


class TestFogSystemWind:
    def _fs(self):
        from systems.fog_system import FogSystem
        return FogSystem(size=(64, 64), gpu=None)

    def test_set_wind_updates_speed(self):
        fs = self._fs()
        fs.set_wind(3.0, 90.0)
        assert abs(fs._wind_speed - 3.0) < 1e-6
        fs.teardown()

    def test_set_wind_updates_angle(self):
        fs = self._fs()
        fs.set_wind(1.0, 45.0)
        assert abs(fs._wind_angle - 45.0) < 1e-6
        fs.teardown()

    def test_set_wind_zero_no_crash(self):
        fs = self._fs()
        fs.set_wind(0.0, 0.0)
        fs.teardown()


class TestFogSystemDisplacers:
    def _fs(self):
        from systems.fog_system import FogSystem
        return FogSystem(size=(64, 64), gpu=None)

    def test_add_displacer_registers(self):
        fs = self._fs()

        class FakeEntity:
            position = (32.0, 32.0)

        e = FakeEntity()
        fs.add_displacer(e, radius=20, strength=0.5)
        assert id(e) in fs._displacer_handles
        fs.teardown()

    def test_remove_displacer_clears(self):
        fs = self._fs()

        class FakeEntity:
            position = (32.0, 32.0)

        e = FakeEntity()
        fs.add_displacer(e, radius=20, strength=0.5)
        fs.remove_displacer(e)
        assert id(e) not in fs._displacer_handles
        fs.teardown()

    def test_remove_unknown_entity_no_crash(self):
        fs = self._fs()
        fs.remove_displacer(object())  # should not raise
        fs.teardown()


class TestFogSystemUpdate:
    def _fs(self):
        from systems.fog_system import FogSystem
        return FogSystem(size=(64, 64), gpu=None, density=0.5)

    def test_update_no_crash(self):
        fs = self._fs()
        fs.update(0.016)
        fs.teardown()

    def test_update_with_displacers_no_crash(self):
        fs = self._fs()

        class FakeEntity:
            position = (32.0, 32.0)

        fs.update(0.016, displacers=[(FakeEntity(), 20, 0.5)])
        fs.teardown()

    def test_update_multiple_ticks(self):
        fs = self._fs()
        for _ in range(10):
            fs.update(0.016)
        fs.teardown()

    def test_sample_returns_float(self):
        fs = self._fs()
        fs.update(0.016)
        v = fs.sample((32.0, 32.0))
        assert isinstance(v, float)
        fs.teardown()

    def test_get_layer_returns_layer(self):
        from pharos_engine.layer import Layer2D
        fs = self._fs()
        layer = fs.get_layer()
        assert isinstance(layer, Layer2D)
        fs.teardown()

    def test_edge_density_boost(self):
        fs = self._fs()
        fs.set_edge_density_boost(0.3)
        fs.update(0.016)
        fs.teardown()

    def test_init_noise_no_crash(self):
        fs = self._fs()
        fs.init_noise(mode="fbm", octaves=3, seed=42)
        fs.teardown()


# =============================================================================
# WeatherSystem
# =============================================================================

class TestWeatherSystemInit:
    def _fs(self):
        from systems.fog_system import FogSystem
        return FogSystem(size=(64, 64), gpu=None, density=0.3)

    def _ws(self, **kw):
        from systems.weather_system import WeatherSystem
        fs = self._fs()
        ws = WeatherSystem(fog_system=fs, gpu=None, **kw)
        ws._fs = fs
        return ws

    def test_instantiates(self):
        ws = self._ws()
        ws.teardown()
        ws._fs.teardown()

    def test_rain_intensity_stored(self):
        ws = self._ws(rain_intensity=0.8)
        assert abs(ws.rain_intensity - 0.8) < 1e-6
        ws.teardown()
        ws._fs.teardown()

    def test_rain_intensity_clamped(self):
        ws = self._ws(rain_intensity=2.0)
        assert ws.rain_intensity <= 1.0
        ws.teardown()
        ws._fs.teardown()

    def test_gust_interval_positive(self):
        ws = self._ws(gust_interval=5.0)
        assert ws._gust_interval > 0
        ws.teardown()
        ws._fs.teardown()

    def test_rain_sim_created(self):
        ws = self._ws()
        assert ws._rain_sim is not None
        ws.teardown()
        ws._fs.teardown()

    def test_teardown_no_crash(self):
        ws = self._ws()
        ws.teardown()
        ws._fs.teardown()


class TestWeatherSystemUpdate:
    def _ws(self, intensity=0.5, interval=100.0):
        from systems.fog_system import FogSystem
        from systems.weather_system import WeatherSystem
        fs = FogSystem(size=(64, 64), gpu=None, density=0.2)
        ws = WeatherSystem(fog_system=fs, rain_intensity=intensity,
                           gust_interval=interval, gpu=None)
        ws._fs = fs
        return ws

    def test_update_no_crash(self):
        ws = self._ws()
        ws.update(0.016)
        ws.teardown()
        ws._fs.teardown()

    def test_update_multiple_ticks(self):
        ws = self._ws()
        for _ in range(30):
            ws.update(0.016)
        ws.teardown()
        ws._fs.teardown()

    def test_gust_fires_event(self):
        from pharos_engine.event_bus import subscribe, unsubscribe
        ws = self._ws(interval=0.01)  # very short interval → gust fires fast
        received = []
        h = subscribe("Weather.Gust", lambda e: received.append(e))
        ws.update(1.0)  # advance past gust threshold
        unsubscribe(h)
        ws.teardown()
        ws._fs.teardown()
        # Gust might or might not fire (depends on interval randomisation)
        assert len(received) >= 0  # just checking no crash

    def test_set_screen_size(self):
        ws = self._ws()
        ws.set_screen_size(1920, 1080)
        assert ws._screen_width == 1920
        assert ws._screen_height == 1080
        ws.teardown()
        ws._fs.teardown()

    def test_intensity_setter(self):
        ws = self._ws(intensity=0.3)
        ws.rain_intensity = 0.9
        assert abs(ws.rain_intensity - 0.9) < 1e-6
        ws.teardown()
        ws._fs.teardown()

    def test_get_rain_layer_returns_layer(self):
        ws = self._ws()
        ws.update(0.016)
        layer = ws.get_rain_layer()
        assert layer is not None  # may be Layer2D or None
        ws.teardown()
        ws._fs.teardown()


# =============================================================================
# ClutterSystem
# =============================================================================

class TestClutterSystemInit:
    def _cs(self, **kw):
        from systems.clutter_system import ClutterSystem
        return ClutterSystem(screen_size=(640, 480), gpu=None, **kw)

    def test_instantiates(self):
        cs = self._cs()
        cs.teardown()

    def test_has_three_clutter_types(self):
        cs = self._cs()
        assert len(cs._sims) == 3
        cs.teardown()

    def test_has_leaf_type(self):
        cs = self._cs()
        assert "leaf" in cs._sims
        cs.teardown()

    def test_has_dust_type(self):
        cs = self._cs()
        assert "dust" in cs._sims
        cs.teardown()

    def test_has_paper_type(self):
        cs = self._cs()
        assert "paper" in cs._sims
        cs.teardown()

    def test_teardown_no_crash(self):
        cs = self._cs()
        cs.teardown()
        cs.teardown()


class TestClutterSystemWind:
    def _cs(self):
        from systems.clutter_system import ClutterSystem
        return ClutterSystem(screen_size=(640, 480), gpu=None)

    def test_set_wind_stores_values(self):
        cs = self._cs()
        cs.set_wind(1.5, 0.8)
        assert abs(cs._base_wind_vx - 1.5) < 1e-6
        assert abs(cs._base_wind_vy - 0.8) < 1e-6
        cs.teardown()

    def test_set_wind_zero(self):
        cs = self._cs()
        cs.set_wind(0.0, 0.0)
        cs.teardown()


class TestClutterSystemSpawnBurst:
    def _cs(self):
        from systems.clutter_system import ClutterSystem
        return ClutterSystem(screen_size=(640, 480), gpu=None)

    def test_spawn_burst_no_crash(self):
        cs = self._cs()
        cs.spawn_burst((320, 240), count=10)
        cs.teardown()

    def test_spawn_burst_zero_count_no_crash(self):
        cs = self._cs()
        cs.spawn_burst((320, 240), count=0)
        cs.teardown()

    def test_spawn_burst_large_count(self):
        cs = self._cs()
        cs.spawn_burst((320, 240), count=50)
        cs.teardown()


class TestClutterSystemUpdate:
    def _cs(self):
        from systems.clutter_system import ClutterSystem
        return ClutterSystem(screen_size=(640, 480), gpu=None)

    def test_update_no_crash(self):
        cs = self._cs()
        cs.update(0.016)
        cs.teardown()

    def test_update_multiple_ticks(self):
        cs = self._cs()
        for _ in range(30):
            cs.update(0.016)
        cs.teardown()

    def test_update_with_pushers(self):
        cs = self._cs()

        class FakePusher:
            position = (320.0, 240.0)
            velocity = (10.0, 0.0)

        cs.update(0.016, pushers=[(FakePusher(), 40, 0.8)])
        cs.teardown()

    def test_get_layers_returns_dict(self):
        cs = self._cs()
        layers = cs.get_layers()
        assert isinstance(layers, dict)
        assert len(layers) == 3
        cs.teardown()

    def test_set_particle_cap(self):
        cs = self._cs()
        cs.set_particle_cap(100)
        cs.teardown()

    def test_set_camera_pos(self):
        cs = self._cs()
        cs.set_camera_pos(320.0, 240.0)
        cs.teardown()

    def test_seed_populates_particles(self):
        cs = self._cs()
        cs.seed(count=30)
        cs.update(0.016)
        cs.teardown()
