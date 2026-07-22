"""Headless tests for Ochema Circuit ProjectileSystem, RadialRepairSystem, PitsSystem."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch
import pytest

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("slappyengine.compute.asset_compute", MagicMock())

_OCHEMA_ROOT = Path(__file__).parent.parent.parent.parent.parent / "DaedalusSVN" / "Ochema Circuit"
_OCHEMA_STR = str(_OCHEMA_ROOT)

if _OCHEMA_STR not in sys.path:
    sys.path.insert(0, _OCHEMA_STR)


# =============================================================================
# Helpers
# =============================================================================

def _make_proj(owner_id=0, vx=200.0, vy=0.0, damage=10.0, pos=(100.0, 100.0)):
    proj = MagicMock()
    proj.position = pos
    proj.velocity = [vx, vy]
    proj._damage = damage
    proj._owner = owner_id
    return proj


def _make_vehicle(driver_id=1, pos=(500.0, 300.0), size=(64, 64)):
    from slappyengine.collision import AABBShape
    v = MagicMock()
    v.driver_id = driver_id
    v.position = pos
    v.collision_shape = AABBShape(width=size[0], height=size[1])
    v.is_destroyed = False
    return v


def _make_turret(pos=(300.0, 300.0)):
    from slappyengine.collision import AABBShape
    t = MagicMock()
    t.position = pos
    t.collision_shape = AABBShape(width=24, height=24)
    return t


# =============================================================================
# ProjectileSystem — init
# =============================================================================

class TestProjectileSystemInit:
    def test_init_no_crash(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem()
        assert ps is not None

    def test_active_count_zero_at_start(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem()
        assert ps.active_count == 0

    def test_register_increments_count(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem()
        proj = _make_proj()
        ps.register(proj)
        assert ps.active_count == 1

    def test_register_sets_ttl(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem()
        proj = _make_proj()
        ps.register(proj)
        assert proj._ttl == pytest.approx(0.0)

    def test_clear_removes_all(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem()
        ps.register(_make_proj())
        ps.register(_make_proj())
        ps.clear()
        assert ps.active_count == 0

    def test_custom_scene_size(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem(scene_width=800, scene_height=600)
        assert ps._sw == 800
        assert ps._sh == 600

    def test_custom_max_ttl(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem(max_ttl=5.0)
        assert ps._max_ttl == pytest.approx(5.0)


# =============================================================================
# ProjectileSystem — movement
# =============================================================================

class TestProjectileSystemMovement:
    def test_update_advances_position(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem()
        proj = _make_proj(vx=100.0, vy=0.0, pos=(0.0, 100.0))
        ps.register(proj)
        ps.update(0.1, vehicles=[], turrets=[])
        assert proj.position[0] == pytest.approx(10.0)

    def test_update_advances_y_position(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem()
        proj = _make_proj(vx=0.0, vy=50.0, pos=(100.0, 0.0))
        ps.register(proj)
        ps.update(0.1, vehicles=[], turrets=[])
        assert proj.position[1] == pytest.approx(5.0)

    def test_update_increments_ttl(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem()
        proj = _make_proj(pos=(100.0, 100.0))
        ps.register(proj)
        ps.update(0.1, vehicles=[], turrets=[])
        assert proj._ttl == pytest.approx(0.1)

    def test_active_projectile_stays_alive(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem()
        proj = _make_proj(pos=(100.0, 100.0))
        ps.register(proj)
        ps.update(0.016, vehicles=[], turrets=[])
        assert ps.active_count == 1


# =============================================================================
# ProjectileSystem — expiry
# =============================================================================

class TestProjectileSystemExpiry:
    def test_expired_by_ttl(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem(max_ttl=1.0)
        proj = _make_proj(pos=(100.0, 100.0))
        ps.register(proj)
        ps.update(1.1, vehicles=[], turrets=[])  # TTL exceeded
        assert ps.active_count == 0

    def test_expired_off_screen_left(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem()
        proj = _make_proj(vx=-2000.0, pos=(10.0, 100.0))
        ps.register(proj)
        ps.update(1.0, vehicles=[], turrets=[])
        assert ps.active_count == 0

    def test_expired_off_screen_right(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem(scene_width=1280)
        proj = _make_proj(vx=2000.0, pos=(1000.0, 100.0))
        ps.register(proj)
        ps.update(1.0, vehicles=[], turrets=[])
        assert ps.active_count == 0

    def test_expired_off_screen_top(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem()
        proj = _make_proj(vx=0.0, vy=-2000.0, pos=(100.0, 10.0))
        ps.register(proj)
        ps.update(1.0, vehicles=[], turrets=[])
        assert ps.active_count == 0

    def test_expired_off_screen_bottom(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem(scene_height=720)
        proj = _make_proj(vx=0.0, vy=2000.0, pos=(100.0, 600.0))
        ps.register(proj)
        ps.update(1.0, vehicles=[], turrets=[])
        assert ps.active_count == 0

    def test_multiple_projectiles_only_expired_removed(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem(max_ttl=1.0, scene_width=1280)
        slow = _make_proj(vx=10.0, pos=(100.0, 100.0))
        fast = _make_proj(vx=5000.0, pos=(1200.0, 100.0))  # 1200+500=1700 > 1280+50
        ps.register(slow)
        ps.register(fast)
        ps.update(0.1, vehicles=[], turrets=[])
        # fast went off-screen, slow stayed
        assert ps.active_count == 1


# =============================================================================
# ProjectileSystem — hit detection
# =============================================================================

class TestProjectileSystemVehicleHit:
    def test_hit_vehicle_removes_projectile(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem()
        proj = _make_proj(owner_id=0, pos=(500.0, 300.0))
        vehicle = _make_vehicle(driver_id=1, pos=(500.0, 300.0))
        ps.register(proj)
        ps.update(0.016, vehicles=[vehicle], turrets=[])
        assert ps.active_count == 0

    def test_hit_calls_take_damage(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem()
        proj = _make_proj(owner_id=0, damage=25.0, pos=(500.0, 300.0))
        vehicle = _make_vehicle(driver_id=1, pos=(500.0, 300.0))
        ps.register(proj)
        ps.update(0.016, vehicles=[vehicle], turrets=[])
        vehicle.take_damage.assert_called_once()
        args = vehicle.take_damage.call_args
        assert args[0][0] == pytest.approx(25.0)

    def test_no_self_hit(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem()
        proj = _make_proj(owner_id=5, pos=(500.0, 300.0))
        vehicle = _make_vehicle(driver_id=5, pos=(500.0, 300.0))  # same owner
        ps.register(proj)
        ps.update(0.016, vehicles=[vehicle], turrets=[])
        vehicle.take_damage.assert_not_called()
        assert ps.active_count == 1

    def test_hit_destroyed_vehicle_publishes_destroyed_event(self):
        from systems.projectile_system import ProjectileSystem
        from slappyengine.event_bus import subscribe, unsubscribe
        ps = ProjectileSystem()
        proj = _make_proj(owner_id=0, pos=(500.0, 300.0))
        vehicle = _make_vehicle(driver_id=1, pos=(500.0, 300.0))
        vehicle.is_destroyed = True

        events = []
        h = subscribe("Vehicle.Destroyed", lambda e: events.append(e))
        try:
            ps.register(proj)
            ps.update(0.016, vehicles=[vehicle], turrets=[])
        finally:
            unsubscribe(h)
        assert len(events) == 1


class TestProjectileSystemTurretHit:
    def test_hit_turret_removes_projectile(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem()
        proj = _make_proj(owner_id=0, pos=(300.0, 300.0))
        turret = _make_turret(pos=(300.0, 300.0))
        ps.register(proj)
        ps.update(0.016, vehicles=[], turrets=[turret])
        assert ps.active_count == 0

    def test_hit_turret_calls_take_hit(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem()
        proj = _make_proj(owner_id=0, damage=15.0, pos=(300.0, 300.0))
        turret = _make_turret(pos=(300.0, 300.0))
        ps.register(proj)
        ps.update(0.016, vehicles=[], turrets=[turret])
        turret.take_hit.assert_called_once_with(15.0)

    def test_vehicle_checked_before_turret(self):
        from systems.projectile_system import ProjectileSystem
        ps = ProjectileSystem()
        proj = _make_proj(owner_id=0, pos=(500.0, 300.0))
        vehicle = _make_vehicle(driver_id=1, pos=(500.0, 300.0))
        turret = _make_turret(pos=(500.0, 300.0))
        ps.register(proj)
        ps.update(0.016, vehicles=[vehicle], turrets=[turret])
        vehicle.take_damage.assert_called_once()
        turret.take_hit.assert_not_called()


# =============================================================================
# _normalise helper
# =============================================================================

class TestNormalise:
    def test_unit_vector_unchanged(self):
        from systems.projectile_system import _normalise
        nx, ny = _normalise(1.0, 0.0)
        assert nx == pytest.approx(1.0)
        assert ny == pytest.approx(0.0)

    def test_arbitrary_vector_normalised(self):
        from systems.projectile_system import _normalise
        import math
        nx, ny = _normalise(3.0, 4.0)
        assert math.hypot(nx, ny) == pytest.approx(1.0)

    def test_zero_vector_returns_default(self):
        from systems.projectile_system import _normalise
        nx, ny = _normalise(0.0, 0.0)
        assert nx == pytest.approx(1.0)
        assert ny == pytest.approx(0.0)


# =============================================================================
# RadialRepairSystem
# =============================================================================

class TestRadialRepairSystemInit:
    def test_init_no_crash(self):
        from systems.repair_system import RadialRepairSystem
        rrs = RadialRepairSystem(vehicles=[])
        assert rrs is not None
        rrs.teardown()

    def test_init_with_vehicles(self):
        from systems.repair_system import RadialRepairSystem
        v1, v2 = MagicMock(), MagicMock()
        rrs = RadialRepairSystem(vehicles=[v1, v2])
        assert rrs._vehicles == [v1, v2]
        rrs.teardown()

    def test_subscribes_on_init(self):
        from systems.repair_system import RadialRepairSystem
        rrs = RadialRepairSystem(vehicles=[])
        assert len(rrs._handles) == 3
        rrs.teardown()

    def test_teardown_clears_handles(self):
        from systems.repair_system import RadialRepairSystem
        rrs = RadialRepairSystem(vehicles=[])
        rrs.teardown()
        assert len(rrs._handles) == 0

    def test_teardown_clears_repairers(self):
        from systems.repair_system import RadialRepairSystem
        rrs = RadialRepairSystem(vehicles=[])
        rrs.teardown()
        assert len(rrs._repairers) == 0


class TestRadialRepairSystemEvents:
    def test_radial_event_with_no_deform_skipped(self):
        from systems.repair_system import RadialRepairSystem
        from slappyengine.event_bus import publish
        vehicle = MagicMock()
        vehicle._deform = None
        rrs = RadialRepairSystem(vehicles=[vehicle])
        # Publish Repair.Radial for vehicle with no deform — should not crash
        publish("Repair.Radial", target=vehicle, center_x=50, center_y=50,
                radius=20, rate=2.0)
        rrs.teardown()

    def test_radial_event_with_no_target_ignored(self):
        from systems.repair_system import RadialRepairSystem
        from slappyengine.event_bus import publish
        rrs = RadialRepairSystem(vehicles=[])
        publish("Repair.Radial", center_x=50, center_y=50)  # no target
        rrs.teardown()

    def test_pixel_event_with_no_target_ignored(self):
        from systems.repair_system import RadialRepairSystem
        from slappyengine.event_bus import publish
        rrs = RadialRepairSystem(vehicles=[])
        publish("Repair.Pixel", x=10, y=10, rate=5.0)
        rrs.teardown()

    def test_full_event_with_no_target_ignored(self):
        from systems.repair_system import RadialRepairSystem
        from slappyengine.event_bus import publish
        rrs = RadialRepairSystem(vehicles=[])
        publish("Repair.Full", rate=1.0)
        rrs.teardown()

    def test_tick_no_crash_with_no_sessions(self):
        from systems.repair_system import RadialRepairSystem
        rrs = RadialRepairSystem(vehicles=[])
        rrs.tick(0.016)
        rrs.teardown()

    def test_get_repairer_caches_by_vehicle_id(self):
        from systems.repair_system import RadialRepairSystem
        vehicle = MagicMock()
        layer = MagicMock()
        layer.numpy.return_value = MagicMock()
        vehicle._deform.layer = layer
        vehicle._deform._original_alpha = None
        rrs = RadialRepairSystem(vehicles=[vehicle])
        r1 = rrs._get_repairer(vehicle)
        r2 = rrs._get_repairer(vehicle)
        assert r1 is r2
        rrs.teardown()

    def test_get_repairer_returns_none_for_no_deform(self):
        from systems.repair_system import RadialRepairSystem
        vehicle = MagicMock()
        vehicle._deform = None
        rrs = RadialRepairSystem(vehicles=[vehicle])
        result = rrs._get_repairer(vehicle)
        assert result is None
        rrs.teardown()


# =============================================================================
# PitsSystem
# =============================================================================

class TestPitsSystemInit:
    def _make_trigger_system(self):
        ts = MagicMock()
        ts.add = MagicMock()
        ts.remove = MagicMock()
        return ts

    def test_init_no_crash(self):
        from systems.pits_system import PitsSystem
        ts = self._make_trigger_system()
        ps = PitsSystem(ts, vehicles=[])
        assert ps is not None
        ps.teardown()

    def test_default_pit_volume_added(self):
        from systems.pits_system import PitsSystem
        ts = self._make_trigger_system()
        ps = PitsSystem(ts, vehicles=[])
        ts.add.assert_called_once()
        ps.teardown()

    def test_custom_pit_positions(self):
        from systems.pits_system import PitsSystem
        ts = self._make_trigger_system()
        pits = [(100.0, 200.0, 80.0, 40.0, 1.0, 0.0),
                (300.0, 200.0, 80.0, 40.0, 1.0, 0.0)]
        ps = PitsSystem(ts, vehicles=[], pit_positions=pits)
        assert ts.add.call_count == 2
        ps.teardown()

    def test_teardown_removes_volumes(self):
        from systems.pits_system import PitsSystem
        ts = self._make_trigger_system()
        ps = PitsSystem(ts, vehicles=[])
        ps.teardown()
        ts.remove.assert_called_once()

    def test_teardown_clears_sessions(self):
        from systems.pits_system import PitsSystem
        ts = self._make_trigger_system()
        ps = PitsSystem(ts, vehicles=[])
        ps.teardown()
        assert len(ps._active_sessions) == 0


class TestPitsSystemVehicleEnter:
    def _make_trigger_system(self):
        ts = MagicMock()
        ts.add = MagicMock()
        ts.remove = MagicMock()
        return ts

    def test_slow_vehicle_enters_pits(self):
        from systems.pits_system import PitsSystem
        from slappyengine.event_bus import subscribe, unsubscribe
        ts = self._make_trigger_system()
        vehicle = MagicMock()
        vehicle.velocity = [10.0, 0.0]  # slow
        vehicle.hull_integrity = 0.5
        ps = PitsSystem(ts, vehicles=[vehicle])

        events = []
        h = subscribe("Pits.Entered", lambda e: events.append(e))
        try:
            ps._on_vehicle_enter(vehicle)
        finally:
            unsubscribe(h)

        assert len(events) == 1
        ps.teardown()

    def test_fast_vehicle_rejected(self):
        from systems.pits_system import PitsSystem
        from slappyengine.event_bus import subscribe, unsubscribe
        ts = self._make_trigger_system()
        vehicle = MagicMock()
        vehicle.velocity = [200.0, 0.0]  # too fast
        ps = PitsSystem(ts, vehicles=[vehicle])

        events = []
        h = subscribe("Pits.Rejected", lambda e: events.append(e))
        try:
            ps._on_vehicle_enter(vehicle)
        finally:
            unsubscribe(h)

        assert len(events) == 1
        ps.teardown()

    def test_double_enter_ignored(self):
        from systems.pits_system import PitsSystem
        ts = self._make_trigger_system()
        vehicle = MagicMock()
        vehicle.velocity = [10.0, 0.0]
        vehicle.hull_integrity = 0.5
        ps = PitsSystem(ts, vehicles=[vehicle])
        ps._on_vehicle_enter(vehicle)
        ps._on_vehicle_enter(vehicle)  # second enter ignored
        assert len(ps._active_sessions) == 1
        ps.teardown()

    def test_vehicle_exit_publishes_event(self):
        from systems.pits_system import PitsSystem
        from slappyengine.event_bus import subscribe, unsubscribe
        ts = self._make_trigger_system()
        vehicle = MagicMock()
        vehicle.velocity = [10.0, 0.0]
        vehicle.hull_integrity = 0.7
        ps = PitsSystem(ts, vehicles=[vehicle])
        ps._on_vehicle_enter(vehicle)

        events = []
        h = subscribe("Pits.Exited", lambda e: events.append(e))
        try:
            ps._on_vehicle_exit(vehicle)
        finally:
            unsubscribe(h)

        assert len(events) == 1
        ps.teardown()

    def test_exit_without_enter_no_crash(self):
        from systems.pits_system import PitsSystem
        ts = self._make_trigger_system()
        vehicle = MagicMock()
        ps = PitsSystem(ts, vehicles=[vehicle])
        ps._on_vehicle_exit(vehicle)  # should not crash
        ps.teardown()


class TestPitsSystemUpdate:
    def _make_trigger_system(self):
        ts = MagicMock()
        ts.add = MagicMock()
        ts.remove = MagicMock()
        return ts

    def test_update_no_sessions_no_crash(self):
        from systems.pits_system import PitsSystem
        ts = self._make_trigger_system()
        ps = PitsSystem(ts, vehicles=[])
        ps.update(0.016)
        ps.teardown()

    def test_update_accrues_cost(self):
        from systems.pits_system import PitsSystem, COST_PER_SECOND
        ts = self._make_trigger_system()
        vehicle = MagicMock()
        vehicle.velocity = [10.0, 0.0]
        vehicle.hull_integrity = 0.5
        vehicle._deform = None
        ps = PitsSystem(ts, vehicles=[vehicle])
        ps._on_vehicle_enter(vehicle)
        ps.update(1.0)
        vid = id(vehicle)
        assert ps._active_sessions[vid].cost_accrued == pytest.approx(COST_PER_SECOND * 1.0)
        ps.teardown()

    def test_update_damped_velocity(self):
        from systems.pits_system import PitsSystem
        ts = self._make_trigger_system()
        vehicle = MagicMock()
        vehicle.velocity = [20.0, 10.0]
        vehicle.hull_integrity = 0.5
        vehicle._deform = None
        ps = PitsSystem(ts, vehicles=[vehicle])
        ps._on_vehicle_enter(vehicle)
        ps.update(0.1)
        # velocity *= max(0, 1 - dt*5) = max(0, 1-0.5) = 0.5
        assert vehicle.velocity[0] == pytest.approx(20.0 * 0.5)
        ps.teardown()

    def test_fast_vehicle_exits_during_update(self):
        from systems.pits_system import PitsSystem
        ts = self._make_trigger_system()
        vehicle = MagicMock()
        vehicle.velocity = [10.0, 0.0]
        vehicle.hull_integrity = 0.5
        vehicle._deform = None
        ps = PitsSystem(ts, vehicles=[vehicle])
        ps._on_vehicle_enter(vehicle)
        # Now vehicle is fast — should auto-exit
        vehicle.velocity = [200.0, 0.0]
        ps.update(0.016)
        assert len(ps._active_sessions) == 0
        ps.teardown()

    def test_update_publishes_repairing_event(self):
        from systems.pits_system import PitsSystem
        from slappyengine.event_bus import subscribe, unsubscribe
        ts = self._make_trigger_system()
        vehicle = MagicMock()
        vehicle.velocity = [10.0, 0.0]
        vehicle.hull_integrity = 0.5
        vehicle._deform = None
        ps = PitsSystem(ts, vehicles=[vehicle])
        ps._on_vehicle_enter(vehicle)

        events = []
        h = subscribe("Pits.Repairing", lambda e: events.append(e))
        try:
            ps.update(0.016)
        finally:
            unsubscribe(h)
        assert len(events) == 1
        ps.teardown()


# =============================================================================
# PitsVehicleState
# =============================================================================

class TestPitsVehicleState:
    def test_init_stores_vehicle(self):
        from systems.pits_system import PitsVehicleState
        v = MagicMock()
        v.hull_integrity = 0.6
        state = PitsVehicleState(v)
        assert state.vehicle is v

    def test_init_active_true(self):
        from systems.pits_system import PitsVehicleState
        v = MagicMock()
        v.hull_integrity = 0.6
        state = PitsVehicleState(v)
        assert state.active is True

    def test_init_time_zero(self):
        from systems.pits_system import PitsVehicleState
        v = MagicMock()
        v.hull_integrity = 0.6
        state = PitsVehicleState(v)
        assert state.time_in_pits == pytest.approx(0.0)

    def test_init_cost_zero(self):
        from systems.pits_system import PitsVehicleState
        v = MagicMock()
        v.hull_integrity = 0.6
        state = PitsVehicleState(v)
        assert state.cost_accrued == pytest.approx(0.0)

    def test_init_integrity_at_entry(self):
        from systems.pits_system import PitsVehicleState
        v = MagicMock()
        v.hull_integrity = 0.45
        state = PitsVehicleState(v)
        assert state.integrity_at_entry == pytest.approx(0.45)

    def test_init_repair_this_visit_zero(self):
        from systems.pits_system import PitsVehicleState
        v = MagicMock()
        v.hull_integrity = 1.0
        state = PitsVehicleState(v)
        assert state.repair_this_visit == pytest.approx(0.0)
