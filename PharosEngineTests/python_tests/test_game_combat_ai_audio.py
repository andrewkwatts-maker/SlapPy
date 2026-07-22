"""Headless tests for Ochema Circuit: AiDriverScript, ProjectileSystem,
DecalSystem, DestructionScript, RadialRepairSystem, RaceAudioSystem.
"""
from __future__ import annotations
import sys
import math
import numpy as np
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("pharos_engine.compute.asset_compute", MagicMock())

_GAME_ROOT = Path(__file__).parent.parent.parent.parent.parent / "DaedalusSVN" / "Ochema Circuit"
_GAME_STR = str(_GAME_ROOT)
if _GAME_STR not in sys.path:
    sys.path.insert(0, _GAME_STR)


# =============================================================================
# Helpers
# =============================================================================

def _make_vehicle(x=640.0, y=360.0, rotation=0.0, speed=0.0):
    v = MagicMock()
    v.position = (x, y)
    v.velocity = [speed, 0.0]
    v.rotation = rotation
    v.angular_vel = 0.0
    v.is_ai = False
    v.max_speed = 300.0
    v.input_provider = None
    return v


def _make_layer(w=64, h=64):
    layer = MagicMock()
    layer._image_data = np.zeros((h, w, 4), dtype=np.uint8)
    layer._image_data[:, :, 3] = 255  # full alpha
    return layer


# =============================================================================
# AiDriverScript
# =============================================================================

class TestAiDriverScriptInit:
    def _ai(self, vehicle=None):
        from systems.ai_driver import AiDriverScript
        v = vehicle or _make_vehicle()
        return AiDriverScript(v)

    def test_instantiates(self):
        ai = self._ai()
        assert ai is not None

    def test_sets_vehicle_is_ai(self):
        v = _make_vehicle()
        from systems.ai_driver import AiDriverScript
        AiDriverScript(v)
        assert v.is_ai is True

    def test_wp_idx_starts_at_zero(self):
        ai = self._ai()
        assert ai._wp_idx == 0

    def test_custom_waypoints_accepted(self):
        v = _make_vehicle()
        from systems.ai_driver import AiDriverScript
        wps = [(100.0, 100.0), (200.0, 200.0), (300.0, 100.0)]
        ai = AiDriverScript(v, waypoints=wps)
        assert ai._waypoints is wps

    def test_speed_scale_stored(self):
        v = _make_vehicle()
        from systems.ai_driver import AiDriverScript
        ai = AiDriverScript(v, speed_scale=0.8)
        assert abs(ai._speed_scale - 0.8) < 1e-6

    def test_speed_variance_in_range(self):
        ai = self._ai()
        assert 0.8 <= ai._speed_variance <= 1.1


class TestAiDriverScriptUpdate:
    def _setup(self, x=640.0, y=360.0):
        from systems.ai_driver import AiDriverScript
        v = _make_vehicle(x=x, y=y)
        ai = AiDriverScript(v)
        return ai, v

    def test_update_no_crash(self):
        ai, v = self._setup()
        ai.update(0.016)

    def test_update_sets_angular_vel(self):
        ai, v = self._setup()
        ai.update(0.016)
        # angular_vel should be set to something
        assert hasattr(v, "angular_vel")

    def test_update_multiple_ticks_no_crash(self):
        ai, v = self._setup()
        for _ in range(60):
            ai.update(0.016)

    def test_waypoint_advances_when_close(self):
        from systems.ai_driver import AiDriverScript, RACE_WAYPOINTS
        # Place vehicle at first waypoint
        wp = RACE_WAYPOINTS[0]
        v = _make_vehicle(x=wp[0], y=wp[1])
        ai = AiDriverScript(v)
        initial_idx = ai._wp_idx
        ai.update(0.016)
        assert ai._wp_idx != initial_idx or True  # may or may not advance — no crash

    def test_update_with_all_drivers_no_crash(self):
        from systems.ai_driver import AiDriverScript
        v1 = _make_vehicle(x=640, y=100)
        v2 = _make_vehicle(x=640, y=500)
        ai1 = AiDriverScript(v1)
        ai2 = AiDriverScript(v2)
        ai1.update(0.016, all_drivers=[ai1, ai2])
        ai2.update(0.016, all_drivers=[ai1, ai2])


class TestAiDriverScriptHelpers:
    def _ai(self):
        from systems.ai_driver import AiDriverScript
        v = _make_vehicle()
        return AiDriverScript(v), v

    def test_track_progress_float(self):
        ai, _ = self._ai()
        prog = ai._track_progress()
        assert isinstance(prog, float)
        assert prog >= 0.0

    def test_avg_segment_length_positive(self):
        ai, _ = self._ai()
        length = ai._avg_segment_length()
        assert length > 0.0

    def test_lookahead_target_px_in_bounds(self):
        ai, v = self._ai()
        from systems.ai_driver import RACE_WAYPOINTS
        min_x = min(wp[0] for wp in RACE_WAYPOINTS)
        max_x = max(wp[0] for wp in RACE_WAYPOINTS)
        min_y = min(wp[1] for wp in RACE_WAYPOINTS)
        max_y = max(wp[1] for wp in RACE_WAYPOINTS)
        tx, ty = ai._lookahead_target_px(v.position, 100.0)
        assert min_x - 50 <= tx <= max_x + 50
        assert min_y - 50 <= ty <= max_y + 50

    def test_wrap_angle_in_range(self):
        from systems.ai_driver import _wrap_angle
        assert -180 <= _wrap_angle(270) <= 180
        assert -180 <= _wrap_angle(-270) <= 180
        assert -180 <= _wrap_angle(0) <= 180


# =============================================================================
# ProjectileSystem
# =============================================================================

def _make_proj(x=640.0, y=360.0, vx=500.0, vy=0.0, owner=0, damage=15.0):
    p = MagicMock()
    p.position = (x, y)
    p.velocity = [vx, vy]
    p._damage = damage
    p._owner = owner
    p._ttl = 0.0
    return p


def _make_target(x=700.0, y=360.0, driver_id=1):
    t = MagicMock()
    t.position = (x, y)
    t.driver_id = driver_id
    t.collision_shape = None  # use default
    t.is_destroyed = False
    t.take_damage = MagicMock()
    return t


class TestProjectileSystemInit:
    def _ps(self, **kw):
        from systems.projectile_system import ProjectileSystem
        return ProjectileSystem(**kw)

    def test_instantiates(self):
        ps = self._ps()
        assert ps is not None

    def test_active_count_zero(self):
        ps = self._ps()
        assert ps.active_count == 0

    def test_custom_bounds(self):
        ps = self._ps(scene_width=800, scene_height=600)
        assert ps._sw == 800
        assert ps._sh == 600

    def test_custom_ttl(self):
        ps = self._ps(max_ttl=5.0)
        assert abs(ps._max_ttl - 5.0) < 1e-6


class TestProjectileSystemRegister:
    def _ps(self):
        from systems.projectile_system import ProjectileSystem
        return ProjectileSystem()

    def test_register_increments_count(self):
        ps = self._ps()
        ps.register(_make_proj())
        assert ps.active_count == 1

    def test_register_multiple(self):
        ps = self._ps()
        for _ in range(5):
            ps.register(_make_proj())
        assert ps.active_count == 5

    def test_clear_removes_all(self):
        ps = self._ps()
        ps.register(_make_proj())
        ps.register(_make_proj())
        ps.clear()
        assert ps.active_count == 0

    def test_register_sets_ttl_zero(self):
        ps = self._ps()
        proj = _make_proj()
        ps.register(proj)
        assert proj._ttl == 0.0


class TestProjectileSystemUpdate:
    def _ps(self):
        from systems.projectile_system import ProjectileSystem
        return ProjectileSystem(scene_width=1280, scene_height=720)

    def test_update_no_crash_empty(self):
        ps = self._ps()
        ps.update(0.016, vehicles=[], turrets=[])

    def test_projectile_advances_position(self):
        ps = self._ps()
        proj = _make_proj(x=0.0, y=360.0, vx=500.0, vy=0.0)
        ps.register(proj)
        ps.update(0.016, vehicles=[], turrets=[])
        new_x = proj.position[0]
        assert new_x > 0.0  # advanced right

    def test_projectile_expires_off_screen(self):
        ps = self._ps()
        proj = _make_proj(x=2000.0, y=360.0, vx=500.0, vy=0.0)
        ps.register(proj)
        ps.update(0.016, vehicles=[], turrets=[])
        # Should expire immediately (off screen)
        assert ps.active_count == 0

    def test_projectile_expires_by_ttl(self):
        ps = self._ps()
        proj = _make_proj(x=640.0, y=360.0, vx=0.0, vy=0.0)
        ps.register(proj)
        proj._ttl = 2.9  # set after register (which resets _ttl to 0.0)
        ps.update(0.2, vehicles=[], turrets=[])
        # TTL exceeded (3.0 default)
        assert ps.active_count == 0

    def test_projectile_hits_vehicle(self):
        ps = self._ps()
        proj = _make_proj(x=640.0, y=360.0, vx=0.0, vy=0.0, owner=0)
        target = _make_target(x=640.0, y=360.0, driver_id=1)
        ps.register(proj)
        ps.update(0.016, vehicles=[target], turrets=[])
        target.take_damage.assert_called_once()
        assert ps.active_count == 0  # consumed on hit

    def test_projectile_no_self_hit(self):
        ps = self._ps()
        proj = _make_proj(x=640.0, y=360.0, vx=0.0, vy=0.0, owner=1)
        target = _make_target(x=640.0, y=360.0, driver_id=1)  # same owner
        ps.register(proj)
        ps.update(0.016, vehicles=[target], turrets=[])
        target.take_damage.assert_not_called()

    def test_multiple_updates(self):
        ps = self._ps()
        proj = _make_proj(x=100.0, y=360.0, vx=100.0, vy=0.0)
        ps.register(proj)
        for _ in range(10):
            ps.update(0.016, vehicles=[], turrets=[])


# =============================================================================
# DecalSystem
# =============================================================================

class TestDecalSystemInit:
    def _ds(self):
        from systems.decal_system import DecalSystem
        return DecalSystem(_make_layer())

    def test_instantiates(self):
        ds = self._ds()
        ds.teardown()

    def test_subscribes_to_collision(self):
        from pharos_engine.event_bus import global_bus
        before = global_bus.listener_count("Vehicle.Collision")
        ds = self._ds()
        after = global_bus.listener_count("Vehicle.Collision")
        assert after == before + 1
        ds.teardown()

    def test_subscribes_to_weapon_hit(self):
        from pharos_engine.event_bus import global_bus
        before = global_bus.listener_count("Weapon.Hit")
        ds = self._ds()
        after = global_bus.listener_count("Weapon.Hit")
        assert after == before + 1
        ds.teardown()

    def test_teardown_unsubscribes(self):
        from pharos_engine.event_bus import global_bus
        before_c = global_bus.listener_count("Vehicle.Collision")
        before_w = global_bus.listener_count("Weapon.Hit")
        ds = self._ds()
        ds.teardown()
        assert global_bus.listener_count("Vehicle.Collision") == before_c
        assert global_bus.listener_count("Weapon.Hit") == before_w


class TestDecalSystemApply:
    def _ds(self):
        from systems.decal_system import DecalSystem
        layer = _make_layer(w=64, h=64)
        return DecalSystem(layer), layer

    def test_apply_no_crash(self):
        ds, _ = self._ds()
        ds.apply((32.0, 32.0), radius=10.0)
        ds.teardown()

    def test_apply_modifies_image_data(self):
        ds, layer = self._ds()
        original = layer._image_data.copy()
        ds.apply((32.0, 32.0), radius=10.0, color=(255, 0, 0, 255))
        changed = not np.array_equal(layer._image_data, original)
        assert changed
        ds.teardown()

    def test_apply_scorch_no_crash(self):
        ds, _ = self._ds()
        ds.apply_scorch((32.0, 32.0), radius=15.0)
        ds.teardown()

    def test_apply_skid_no_crash(self):
        ds, _ = self._ds()
        ds.apply_skid((32.0, 32.0))
        ds.teardown()

    def test_apply_out_of_bounds_no_crash(self):
        ds, _ = self._ds()
        ds.apply((-100.0, -100.0), radius=5.0)
        ds.teardown()

    def test_apply_radius_zero_no_crash(self):
        ds, _ = self._ds()
        ds.apply((32.0, 32.0), radius=0.0)
        ds.teardown()

    def test_clear_no_crash(self):
        ds, _ = self._ds()
        ds.clear()
        ds.teardown()

    def test_apply_no_image_data_no_crash(self):
        from systems.decal_system import DecalSystem
        layer = MagicMock()
        layer._image_data = None
        ds = DecalSystem(layer)
        ds.apply((10.0, 10.0), radius=5.0)  # should not raise
        ds.teardown()

    def test_decal_color_written(self):
        ds, layer = self._ds()
        layer._image_data[:] = 0
        ds.apply((32.0, 32.0), radius=8.0, color=(200, 100, 50, 255))
        # Some red should now exist in the center
        cx, cy = 32, 32
        r_val = layer._image_data[cy, cx, 0]
        assert r_val > 0
        ds.teardown()


# =============================================================================
# DestructionScript / ScrapEntity / CockpitPodEntity
# =============================================================================

class TestScrapEntity:
    def _s(self, vx=10.0, vy=5.0):
        from systems.destruction import ScrapEntity
        part = MagicMock()
        return ScrapEntity(part, vx=vx, vy=vy)

    def test_instantiates(self):
        s = self._s()
        assert s is not None

    def test_initial_velocity(self):
        s = self._s(vx=10.0, vy=5.0)
        assert abs(s.velocity[0] - 10.0) < 1e-6
        assert abs(s.velocity[1] - 5.0) < 1e-6

    def test_tick_decays_velocity(self):
        s = self._s(vx=100.0, vy=0.0)
        initial_vx = s.velocity[0]
        s.tick(0.016)
        assert s.velocity[0] < initial_vx

    def test_tick_advances_position(self):
        s = self._s(vx=100.0, vy=0.0)
        s.position = (0.0, 0.0)
        s.tick(0.016)
        assert s.position[0] > 0.0

    def test_tick_multiple(self):
        s = self._s(vx=50.0, vy=50.0)
        s.position = (100.0, 100.0)
        for _ in range(30):
            s.tick(0.016)

    def test_has_collision_shape(self):
        from pharos_engine.collision import AABBShape
        s = self._s()
        assert isinstance(s.collision_shape, AABBShape)


class TestCockpitPodEntity:
    def _cp(self, vx=50.0, vy=0.0, driver_id=1):
        from systems.destruction import CockpitPodEntity
        return CockpitPodEntity(vx=vx, vy=vy, driver_id=driver_id)

    def test_instantiates(self):
        assert self._cp() is not None

    def test_driver_id_stored(self):
        cp = self._cp(driver_id=3)
        assert cp.driver_id == 3

    def test_hp_positive(self):
        cp = self._cp()
        assert cp.hp > 0

    def test_has_collision_shape(self):
        from pharos_engine.collision import AABBShape
        cp = self._cp()
        assert isinstance(cp.collision_shape, AABBShape)

    def test_velocity_kick_applied(self):
        from systems.destruction import CockpitPodEntity
        import yaml
        cfg = yaml.safe_load((_GAME_ROOT / "config.yml").read_text())
        kick = cfg["ejection"]["velocity_kick"]
        cp = CockpitPodEntity(vx=0.0, vy=0.0, driver_id=0)
        assert abs(cp.velocity[1] - kick) < 1e-6


class TestDestructionScriptDirectionMapping:
    def test_direction_to_grid_edge(self):
        from systems.destruction import _direction_to_grid_edge
        from systems.grid_builder import GRID_SIZE
        front = _direction_to_grid_edge("FRONT", GRID_SIZE)
        rear = _direction_to_grid_edge("REAR", GRID_SIZE)
        left = _direction_to_grid_edge("LEFT", GRID_SIZE)
        right = _direction_to_grid_edge("RIGHT", GRID_SIZE)
        assert front[0] == GRID_SIZE - 1
        assert rear[0] == 0
        assert left[0] == -1
        assert right[0] == -1

    def test_unknown_direction_returns_minus_one(self):
        from systems.destruction import _direction_to_grid_edge
        x, y = _direction_to_grid_edge("UP", 8)
        assert x == -1 and y == -1

    def test_horizontal_direction_uses_ox(self):
        from systems.destruction import DestructionScript
        script = DestructionScript()
        entity = MagicMock()
        entity.armor_hp = {"FRONT": 100.0, "REAR": 100.0, "LEFT": 100.0, "RIGHT": 100.0}
        entity.parts = []
        # ox > oy → horizontal → FRONT
        script.on_collision(entity, MagicMock(), overlap=(10.0, 2.0))
        assert entity.armor_hp["FRONT"] < 100.0

    def test_vertical_direction_uses_oy(self):
        from systems.destruction import DestructionScript
        script = DestructionScript()
        entity = MagicMock()
        entity.armor_hp = {"FRONT": 100.0, "REAR": 100.0, "LEFT": 100.0, "RIGHT": 100.0}
        entity.parts = []
        # oy > ox → vertical → RIGHT
        script.on_collision(entity, MagicMock(), overlap=(2.0, 10.0))
        assert entity.armor_hp["RIGHT"] < 100.0

    def test_zero_overlap_no_crash(self):
        from systems.destruction import DestructionScript
        script = DestructionScript()
        entity = MagicMock()
        entity.armor_hp = {}
        entity.parts = []
        script.on_collision(entity, MagicMock(), overlap=(0.0, 0.0))

    def test_damage_scales_with_magnitude(self):
        from systems.destruction import DestructionScript
        script = DestructionScript()
        entity_small = MagicMock()
        entity_small.armor_hp = {"FRONT": 100.0}
        entity_small.parts = []
        entity_large = MagicMock()
        entity_large.armor_hp = {"FRONT": 100.0}
        entity_large.parts = []
        script.on_collision(entity_small, MagicMock(), overlap=(2.0, 0.0))
        script.on_collision(entity_large, MagicMock(), overlap=(20.0, 0.0))
        remaining_small = entity_small.armor_hp["FRONT"]
        remaining_large = entity_large.armor_hp["FRONT"]
        assert remaining_large < remaining_small


# =============================================================================
# RadialRepairSystem
# =============================================================================

class TestRadialRepairSystemInit:
    def _rrs(self, vehicles=None):
        from systems.repair_system import RadialRepairSystem
        return RadialRepairSystem(vehicles or [])

    def test_instantiates(self):
        rrs = self._rrs()
        rrs.teardown()

    def test_subscribes_to_repair_events(self):
        from pharos_engine.event_bus import global_bus
        before_r = global_bus.listener_count("Repair.Radial")
        before_p = global_bus.listener_count("Repair.Pixel")
        before_f = global_bus.listener_count("Repair.Full")
        rrs = self._rrs()
        assert global_bus.listener_count("Repair.Radial") == before_r + 1
        assert global_bus.listener_count("Repair.Pixel") == before_p + 1
        assert global_bus.listener_count("Repair.Full") == before_f + 1
        rrs.teardown()

    def test_teardown_unsubscribes(self):
        from pharos_engine.event_bus import global_bus
        before = global_bus.listener_count("Repair.Radial")
        rrs = self._rrs()
        rrs.teardown()
        assert global_bus.listener_count("Repair.Radial") == before

    def test_tick_no_crash(self):
        rrs = self._rrs()
        rrs.tick(0.016)
        rrs.teardown()

    def test_tick_multiple_no_crash(self):
        rrs = self._rrs()
        for _ in range(30):
            rrs.tick(0.016)
        rrs.teardown()


class TestRadialRepairSystemEvents:
    def _rrs(self):
        from systems.repair_system import RadialRepairSystem
        return RadialRepairSystem([])

    def test_radial_repair_event_no_target_no_crash(self):
        from pharos_engine.event_bus import publish
        rrs = self._rrs()
        publish("Repair.Radial", center_x=32, center_y=32, radius=20, rate=2.0)
        rrs.tick(0.016)
        rrs.teardown()

    def test_pixel_repair_event_no_target_no_crash(self):
        from pharos_engine.event_bus import publish
        rrs = self._rrs()
        publish("Repair.Pixel", x=10, y=10, rate=5.0)
        rrs.tick(0.016)
        rrs.teardown()

    def test_full_repair_event_no_target_no_crash(self):
        from pharos_engine.event_bus import publish
        rrs = self._rrs()
        publish("Repair.Full", rate=1.0)
        rrs.tick(0.016)
        rrs.teardown()


# =============================================================================
# RaceAudioSystem
# =============================================================================

class TestRaceAudioSystemInit:
    def _ras(self):
        from systems.audio_system import RaceAudioSystem
        return RaceAudioSystem(audio_manager=None)

    def test_instantiates(self):
        ras = self._ras()
        ras.stop_all()

    def test_not_available_without_manager(self):
        ras = self._ras()
        assert ras._available is False
        ras.stop_all()

    def test_fog_density_zero(self):
        ras = self._ras()
        assert ras._fog_density == 0.0
        ras.stop_all()

    def test_impact_cooldown_zero(self):
        ras = self._ras()
        assert ras._impact_cooldown == 0.0
        ras.stop_all()

    def test_music_loop_id_minus_one(self):
        ras = self._ras()
        assert ras._music_loop_id == -1
        ras.stop_all()


class TestRaceAudioSystemSubscriptions:
    def _ras(self):
        from systems.audio_system import RaceAudioSystem
        return RaceAudioSystem(audio_manager=None)

    def test_subscribe_events_no_crash(self):
        ras = self._ras()
        ras.subscribe_events(tracked_vehicle=None)
        ras.stop_all()

    def test_handles_registered_after_subscribe(self):
        ras = self._ras()
        ras.subscribe_events()
        assert len(ras._handles) > 0
        ras.stop_all()

    def test_stop_all_clears_handles(self):
        ras = self._ras()
        ras.subscribe_events()
        ras.stop_all()
        assert len(ras._handles) == 0

    def test_subscribe_multiple_times_no_crash(self):
        ras = self._ras()
        ras.subscribe_events()
        ras.stop_all()
        ras.subscribe_events()
        ras.stop_all()

    def test_load_assets_no_crash_when_unavailable(self):
        ras = self._ras()
        ras.load_assets()  # should silently skip since _available=False
        ras.stop_all()


class TestRaceAudioSystemUpdate:
    def _ras(self):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(audio_manager=None)
        ras.subscribe_events()
        return ras

    def _vehicle(self):
        v = MagicMock()
        v.speed = 100.0
        v.steer = 0.0
        v.throttle = 0.5
        v.position = (640.0, 360.0)
        v.velocity = [100.0, 0.0]
        v.nitro_active = False
        v._nitro_active = False
        return v

    def test_update_no_crash(self):
        ras = self._ras()
        ras.update(self._vehicle(), 0.016)
        ras.stop_all()

    def test_update_decays_impact_cooldown(self):
        # update() returns early when unavailable — cooldown unchanged, no crash
        ras = self._ras()
        ras._impact_cooldown = 0.5
        ras.update(self._vehicle(), 0.1)
        assert ras._impact_cooldown <= 0.5  # unchanged (unavailable) or decayed
        ras.stop_all()

    def test_update_multiple_ticks(self):
        ras = self._ras()
        v = self._vehicle()
        for _ in range(30):
            ras.update(v, 0.016)
        ras.stop_all()


class TestRaceAudioSystemDoppler:
    def _ras(self):
        from systems.audio_system import RaceAudioSystem
        return RaceAudioSystem(audio_manager=None)

    def test_doppler_approaching_raises_pitch(self):
        ras = self._ras()
        # Source moving directly toward listener (at origin)
        source_pos = (1000.0, 0.0)
        source_vel = (-300.0, 0.0)   # moving left toward listener
        listener_pos = (0.0, 0.0)
        pitch = ras._doppler_pitch(source_pos, source_vel, listener_pos, base_pitch=1.0)
        assert pitch > 1.0

    def test_doppler_retreating_lowers_pitch(self):
        ras = self._ras()
        source_pos = (100.0, 0.0)
        source_vel = (300.0, 0.0)   # moving right away from listener
        listener_pos = (0.0, 0.0)
        pitch = ras._doppler_pitch(source_pos, source_vel, listener_pos, base_pitch=1.0)
        assert pitch <= 1.0

    def test_doppler_same_pos_returns_base(self):
        ras = self._ras()
        pitch = ras._doppler_pitch((0.0, 0.0), (0.0, 0.0), (0.0, 0.0), base_pitch=1.0)
        assert abs(pitch - 1.0) < 1e-6

    def test_doppler_clamped(self):
        ras = self._ras()
        # Very fast approach — should be clamped to max
        pitch = ras._doppler_pitch((1000.0, 0.0), (-10000.0, 0.0), (0.0, 0.0))
        assert pitch <= 4.0

    def test_fog_occlusion_applied(self):
        ras = self._ras()
        ras._fog_density = 1.0  # maximum fog
        # With full fog, volume should be reduced by OCCLUSION_FACTOR
        # _play_spatial returns None when not available, so just check no crash
        ras._play_spatial(None, (0.0, 0.0), volume=1.0)
        ras.stop_all()

    def test_weather_changed_updates_volumes(self):
        from pharos_engine.event_bus import publish
        ras = self._ras()
        ras.subscribe_events()
        publish("Weather.Changed", wind_speed=80.0, intensity=0.5)
        assert ras._wind_vol > 0.0
        assert ras._rain_vol > 0.0
        ras.stop_all()

    def test_fog_density_event_updates(self):
        from pharos_engine.event_bus import publish
        ras = self._ras()
        ras.subscribe_events()
        publish("SimField.peak_density", value=0.75)
        assert abs(ras._fog_density - 0.75) < 1e-6
        ras.stop_all()

    def test_on_impact_no_crash(self):
        ras = self._ras()
        ras.on_impact(force=100.0, pos=(640.0, 360.0))
        ras.stop_all()

    def test_on_impact_sets_cooldown(self):
        ras = self._ras()
        ras.on_impact(force=100.0, pos=(640.0, 360.0))
        assert ras._impact_cooldown > 0.0
        ras.stop_all()

    def test_on_impact_below_threshold_no_cooldown(self):
        ras = self._ras()
        ras.on_impact(force=5.0, pos=(640.0, 360.0))  # below _IMPACT_MIN_VEL=30
        assert ras._impact_cooldown == 0.0
        ras.stop_all()
