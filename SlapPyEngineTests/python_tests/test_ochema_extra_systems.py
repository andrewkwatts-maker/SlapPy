"""Headless tests for Ochema Circuit extra systems:
ProjectileSystem, RadialRepairSystem, DestructionScript, HardpointScript.
"""
from __future__ import annotations
import sys
import math
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("slappyengine.compute.asset_compute", MagicMock())

_GAME_ROOT = Path(__file__).parent.parent.parent.parent.parent / "DaedalusSVN" / "Ochema Circuit"
_GAME_STR = str(_GAME_ROOT)
if _GAME_STR not in sys.path:
    sys.path.insert(0, _GAME_STR)


# =============================================================================
# Helpers
# =============================================================================

class _FakeProj:
    def __init__(self, x=100.0, y=100.0, vx=10.0, vy=0.0, damage=10.0, owner=-1):
        self.position = (x, y)
        self.velocity = [vx, vy]
        self._damage = damage
        self._owner = owner
        self._ttl = 0.0


class _FakeVehicle:
    def __init__(self, driver_id=99, x=5000.0, y=5000.0):
        self.driver_id = driver_id
        self.position = (x, y)
        self._damage_calls = []

    def take_damage(self, amount, direction=None):
        self._damage_calls.append(amount)

    @property
    def is_destroyed(self):
        return False


class _FakeTurret:
    def __init__(self, x=5000.0, y=5000.0):
        self.position = (x, y)
        self._hits = []

    def take_hit(self, amount):
        self._hits.append(amount)


# =============================================================================
# ProjectileSystem
# =============================================================================

class TestProjectileSystemInit:
    def _ps(self):
        from systems.projectile_system import ProjectileSystem
        return ProjectileSystem()

    def test_instantiates(self):
        assert self._ps() is not None

    def test_active_count_zero(self):
        ps = self._ps()
        assert ps.active_count == 0

    def test_custom_scene_size(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem(scene_width=800, scene_height=600)
        assert ps._sw == 800
        assert ps._sh == 600

    def test_custom_max_ttl(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem(max_ttl=5.0)
        assert ps._max_ttl == 5.0


class TestProjectileSystemRegister:
    def _ps(self):
        from systems.projectile_system import ProjectileSystem
        return ProjectileSystem()

    def test_register_increases_count(self):
        ps = self._ps()
        ps.register(_FakeProj())
        assert ps.active_count == 1

    def test_register_multiple(self):
        ps = self._ps()
        for _ in range(5):
            ps.register(_FakeProj())
        assert ps.active_count == 5

    def test_clear_empties_list(self):
        ps = self._ps()
        ps.register(_FakeProj())
        ps.register(_FakeProj())
        ps.clear()
        assert ps.active_count == 0

    def test_register_sets_ttl_zero(self):
        ps = self._ps()
        proj = _FakeProj()
        proj._ttl = 99.0
        ps.register(proj)
        assert proj._ttl == 0.0


class TestProjectileSystemUpdate:
    def _ps(self, w=1280, h=720, ttl=3.0):
        from systems.projectile_system import ProjectileSystem
        return ProjectileSystem(scene_width=w, scene_height=h, max_ttl=ttl)

    def test_update_no_crash_empty(self):
        ps = self._ps()
        ps.update(0.016, vehicles=[], turrets=[])

    def test_update_moves_projectile(self):
        ps = self._ps()
        proj = _FakeProj(x=100.0, y=100.0, vx=100.0, vy=0.0)
        ps.register(proj)
        ps.update(0.1, vehicles=[], turrets=[])
        # If still alive, x advanced; if expired, active_count == 0
        if ps.active_count == 1:
            assert proj.position[0] > 100.0

    def test_offscreen_right_expires(self):
        ps = self._ps(w=1280)
        proj = _FakeProj(x=1400.0, y=100.0)  # beyond 1280+50 margin
        ps.register(proj)
        ps.update(0.016, vehicles=[], turrets=[])
        assert ps.active_count == 0

    def test_offscreen_left_expires(self):
        ps = self._ps()
        proj = _FakeProj(x=-100.0, y=100.0)  # beyond -50 margin
        ps.register(proj)
        ps.update(0.016, vehicles=[], turrets=[])
        assert ps.active_count == 0

    def test_offscreen_top_expires(self):
        ps = self._ps(h=720)
        proj = _FakeProj(x=100.0, y=-100.0)
        ps.register(proj)
        ps.update(0.016, vehicles=[], turrets=[])
        assert ps.active_count == 0

    def test_offscreen_bottom_expires(self):
        ps = self._ps(h=720)
        proj = _FakeProj(x=100.0, y=850.0)  # beyond 720+50
        ps.register(proj)
        ps.update(0.016, vehicles=[], turrets=[])
        assert ps.active_count == 0

    def test_ttl_expire(self):
        ps = self._ps(ttl=3.0)
        proj = _FakeProj(x=100.0, y=100.0)
        ps.register(proj)
        proj._ttl = 2.95  # after +0.1 → 3.05 > 3.0
        ps.update(0.1, vehicles=[], turrets=[])
        assert ps.active_count == 0

    def test_alive_projectile_stays(self):
        ps = self._ps()
        proj = _FakeProj(x=100.0, y=100.0, vx=0.0, vy=0.0)
        ps.register(proj)
        ps.update(0.016, vehicles=[], turrets=[])
        assert ps.active_count == 1

    def test_far_vehicle_no_hit(self):
        ps = self._ps()
        proj = _FakeProj(x=100.0, y=100.0, vx=0.0, vy=0.0)
        ps.register(proj)
        vehicle = _FakeVehicle(driver_id=42, x=5000.0, y=5000.0)
        ps.update(0.016, vehicles=[vehicle], turrets=[])
        assert len(vehicle._damage_calls) == 0

    def test_far_turret_no_hit(self):
        ps = self._ps()
        proj = _FakeProj(x=100.0, y=100.0)
        ps.register(proj)
        turret = _FakeTurret(x=5000.0, y=5000.0)
        ps.update(0.016, vehicles=[], turrets=[turret])
        assert len(turret._hits) == 0

    def test_self_owner_skipped(self):
        ps = self._ps()
        proj = _FakeProj(x=100.0, y=100.0, owner=42)
        ps.register(proj)
        vehicle = _FakeVehicle(driver_id=42, x=100.0, y=100.0)  # same position
        ps.update(0.016, vehicles=[vehicle], turrets=[])
        # Skipped because driver_id == proj._owner; but projectile might expire off-screen
        assert len(vehicle._damage_calls) == 0

    def test_expire_event_published(self):
        from slappyengine.event_bus import global_bus
        received = []
        h = global_bus.subscribe("projectile:expired", lambda e: received.append(e))
        ps = self._ps()
        proj = _FakeProj(x=1400.0, y=100.0)  # off-screen
        ps.register(proj)
        ps.update(0.016, vehicles=[], turrets=[])
        global_bus.unsubscribe(h)
        assert len(received) == 1

    def test_multiple_projectiles_update_independently(self):
        ps = self._ps()
        in_bounds = _FakeProj(x=100.0, y=100.0, vx=0.0, vy=0.0)
        off_screen = _FakeProj(x=1400.0, y=100.0)
        ps.register(in_bounds)
        ps.register(off_screen)
        ps.update(0.016, vehicles=[], turrets=[])
        assert ps.active_count == 1


# =============================================================================
# RadialRepairSystem
# =============================================================================

class TestRadialRepairSystemInit:
    def _rs(self, vehicles=None):
        from systems.repair_system import RadialRepairSystem
        return RadialRepairSystem(vehicles or [])

    def test_instantiates(self):
        rs = self._rs()
        rs.teardown()

    def test_subscribes_repair_events(self):
        from slappyengine.event_bus import global_bus
        before = (
            global_bus.listener_count("Repair.Radial"),
            global_bus.listener_count("Repair.Pixel"),
            global_bus.listener_count("Repair.Full"),
        )
        rs = self._rs()
        after = (
            global_bus.listener_count("Repair.Radial"),
            global_bus.listener_count("Repair.Pixel"),
            global_bus.listener_count("Repair.Full"),
        )
        assert after[0] == before[0] + 1
        assert after[1] == before[1] + 1
        assert after[2] == before[2] + 1
        rs.teardown()

    def test_teardown_unsubscribes(self):
        from slappyengine.event_bus import global_bus
        before = global_bus.listener_count("Repair.Radial")
        rs = self._rs()
        rs.teardown()
        after = global_bus.listener_count("Repair.Radial")
        assert after == before

    def test_teardown_twice_no_crash(self):
        rs = self._rs()
        rs.teardown()
        rs.teardown()

    def test_tick_empty_no_crash(self):
        rs = self._rs()
        rs.tick(0.016)
        rs.teardown()


class TestRadialRepairSystemHandlers:
    def _rs(self, vehicles=None):
        from systems.repair_system import RadialRepairSystem
        return RadialRepairSystem(vehicles or [])

    def test_radial_no_target_no_crash(self):
        from slappyengine.event_bus import publish
        rs = self._rs()
        publish("Repair.Radial", center_x=50, center_y=50, radius=20, rate=2.0)
        rs.tick(0.016)
        rs.teardown()

    def test_pixel_no_target_no_crash(self):
        from slappyengine.event_bus import publish
        rs = self._rs()
        publish("Repair.Pixel", x=10, y=10, rate=5.0)
        rs.tick(0.016)
        rs.teardown()

    def test_full_no_target_no_crash(self):
        from slappyengine.event_bus import publish
        rs = self._rs()
        publish("Repair.Full", rate=1.0)
        rs.tick(0.016)
        rs.teardown()

    def test_radial_missing_deform_no_crash(self):
        from slappyengine.event_bus import publish
        target = MagicMock()
        target._deform = None
        rs = self._rs()
        publish("Repair.Radial", target=target, center_x=50, center_y=50, radius=20, rate=2.0)
        rs.tick(0.016)
        rs.teardown()


# =============================================================================
# DestructionScript / ScrapEntity / CockpitPodEntity
# =============================================================================

class TestScrapEntity:
    def _se(self, vx=50.0, vy=20.0):
        from systems.destruction import ScrapEntity
        part = MagicMock()
        return ScrapEntity(part=part, vx=vx, vy=vy)

    def test_instantiates(self):
        assert self._se() is not None

    def test_velocity_stored(self):
        se = self._se(vx=30.0, vy=10.0)
        assert abs(se.velocity[0] - 30.0) < 1e-6
        assert abs(se.velocity[1] - 10.0) < 1e-6

    def test_tick_decays_velocity(self):
        se = self._se(vx=100.0, vy=100.0)
        se.tick(0.016)
        assert abs(se.velocity[0]) < 100.0
        assert abs(se.velocity[1]) < 100.0

    def test_tick_advances_position(self):
        se = self._se(vx=100.0, vy=0.0)
        x0 = se.position[0]
        se.tick(0.1)
        assert se.position[0] > x0

    def test_tick_multiple_no_crash(self):
        se = self._se()
        for _ in range(30):
            se.tick(0.016)

    def test_collision_shape_set(self):
        from slappyengine.collision import AABBShape
        se = self._se()
        assert isinstance(se.collision_shape, AABBShape)


class TestCockpitPodEntity:
    def _pod(self, vx=50.0, vy=-20.0, driver_id=1):
        from systems.destruction import CockpitPodEntity
        return CockpitPodEntity(vx=vx, vy=vy, driver_id=driver_id)

    def test_instantiates(self):
        assert self._pod() is not None

    def test_driver_id_stored(self):
        pod = self._pod(driver_id=7)
        assert pod.driver_id == 7

    def test_velocity_includes_kick(self):
        pod = self._pod(vx=0.0, vy=0.0)
        from systems.destruction import _EJECT
        # vy = vy_arg + velocity_kick
        assert pod.velocity[1] == _EJECT["velocity_kick"]

    def test_collision_shape_set(self):
        from slappyengine.collision import AABBShape
        pod = self._pod()
        assert isinstance(pod.collision_shape, AABBShape)

    def test_on_collision_no_scene_no_crash(self):
        pod = self._pod()
        pod.scene = None
        other = MagicMock()
        other.driver_id = 2
        pod.on_collision(other, overlap=(10, 10))  # no crash


class TestDestructionScript:
    def _ds(self):
        from systems.destruction import DestructionScript
        return DestructionScript()

    def _entity(self, direction_hp=50.0):
        e = MagicMock()
        e.armor_hp = {"FRONT": direction_hp, "REAR": direction_hp,
                      "LEFT": direction_hp, "RIGHT": direction_hp}
        e.parts = []
        e.scene = None
        e.velocity = [0.0, 0.0]
        return e

    def test_zero_overlap_no_crash(self):
        ds = self._ds()
        e = self._entity()
        ds.on_collision(e, MagicMock(), overlap=(0, 0))

    def test_small_overlap_no_crash(self):
        ds = self._ds()
        e = self._entity()
        ds.on_collision(e, MagicMock(), overlap=(1e-9, 0))

    def test_front_overlap_reduces_front_hp(self):
        ds = self._ds()
        e = self._entity(direction_hp=100.0)
        before = e.armor_hp["FRONT"]
        ds.on_collision(e, MagicMock(), overlap=(50, 0))  # abs(ox)=50 > abs(oy)=0, ox>0 → FRONT
        assert e.armor_hp["FRONT"] < before

    def test_rear_overlap_reduces_rear_hp(self):
        ds = self._ds()
        e = self._entity(direction_hp=100.0)
        before = e.armor_hp["REAR"]
        ds.on_collision(e, MagicMock(), overlap=(-50, 0))  # ox<0 → REAR
        assert e.armor_hp["REAR"] < before

    def test_right_overlap_reduces_right_hp(self):
        ds = self._ds()
        e = self._entity(direction_hp=100.0)
        before = e.armor_hp["RIGHT"]
        ds.on_collision(e, MagicMock(), overlap=(0, 50))  # abs(oy)>abs(ox), oy>0 → RIGHT
        assert e.armor_hp["RIGHT"] < before

    def test_left_overlap_reduces_left_hp(self):
        ds = self._ds()
        e = self._entity(direction_hp=100.0)
        before = e.armor_hp["LEFT"]
        ds.on_collision(e, MagicMock(), overlap=(0, -50))  # oy<0 → LEFT
        assert e.armor_hp["LEFT"] < before

    def test_armor_hp_never_negative(self):
        ds = self._ds()
        e = self._entity(direction_hp=1.0)
        ds.on_collision(e, MagicMock(), overlap=(1000, 0))  # very large damage
        assert e.armor_hp["FRONT"] >= 0.0


class TestDirectionToGridEdge:
    def test_front_returns_grid_size_minus1(self):
        from systems.destruction import _direction_to_grid_edge
        from systems.grid_builder import GRID_SIZE
        result = _direction_to_grid_edge("FRONT", GRID_SIZE)
        assert result[0] == GRID_SIZE - 1

    def test_rear_returns_zero(self):
        from systems.destruction import _direction_to_grid_edge
        from systems.grid_builder import GRID_SIZE
        result = _direction_to_grid_edge("REAR", GRID_SIZE)
        assert result[0] == 0

    def test_unknown_returns_negative(self):
        from systems.destruction import _direction_to_grid_edge
        result = _direction_to_grid_edge("UNKNOWN", 4)
        assert result == (-1, -1)


# =============================================================================
# HardpointScript (systems/weapons.py)
# =============================================================================

class TestHardpointScript:
    def _hs(self):
        from systems.weapons import HardpointScript
        return HardpointScript()

    def _entity(self, heat=0.0, locked=0.0):
        e = MagicMock()
        e.heat = heat
        e.weapon_locked = locked
        e.armor_hp = {"FRONT": 100.0}
        e.max_speed = 500.0
        e._nitro_light = None  # explicit None so the nitro-off branch skips
        engine = MagicMock()
        engine.input = None  # no input
        e.scene._engine = engine
        return e

    def test_on_tick_no_input_cools_heat(self):
        hs = self._hs()
        e = self._entity(heat=0.5, locked=0.0)
        hs.on_tick(e, 0.1)
        # With no input and heat < 1.0, heat should decrease
        assert e.heat <= 0.5

    def test_on_tick_locked_decrements_lock(self):
        hs = self._hs()
        e = self._entity(heat=0.9, locked=1.0)
        before = e.weapon_locked
        hs.on_tick(e, 0.1)
        assert e.weapon_locked < before

    def test_on_tick_heat_zero_no_crash(self):
        hs = self._hs()
        e = self._entity(heat=0.0)
        hs.on_tick(e, 0.016)

    def test_on_tick_no_emitters_no_crash(self):
        hs = self._hs()
        e = self._entity(heat=0.95)
        del e._emitters  # remove _emitters attr so getattr returns None
        e._emitters = None
        hs.on_tick(e, 0.016)

    def test_on_launch_attaches_script(self):
        from systems.weapons import on_launch
        e = MagicMock()
        e._scripts = []
        on_launch(e)
        assert hasattr(e, '_hardpoint_script')
        assert e._hardpoint_script is not None

    def test_on_end_clears_script(self):
        from systems.weapons import on_launch, on_end
        e = MagicMock()
        e._scripts = []
        on_launch(e)
        on_end(e)
        assert e._hardpoint_script is None

    def test_module_on_tick_no_crash(self):
        from systems.weapons import on_tick
        e = self._entity()
        e._hardpoint_script = None  # will be created by on_tick
        on_tick(e, 0.016)
