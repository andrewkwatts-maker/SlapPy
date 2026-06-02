"""Headless tests for additional Ochema Circuit system methods.

Covers: ai_build_generator, repair_system, collision_system static helpers,
entities/part.__post_init__.
"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("slappyengine.compute.asset_compute", MagicMock())

_OCHEMA_DIR = Path(__file__).parent.parent.parent.parent.parent / "DaedalusSVN" / "Ochema Circuit"
_OCHEMA_STR = str(_OCHEMA_DIR)
if _OCHEMA_STR not in sys.path:
    sys.path.insert(0, _OCHEMA_STR)


# =============================================================================
# AIBuildGenerator — _load_shop, apply_ai_tiers
# =============================================================================

class TestLoadShop:
    def test_returns_dict(self):
        from systems.ai_build_generator import _load_shop
        result = _load_shop()
        assert isinstance(result, dict)

    def test_has_part_type_keys(self):
        from systems.ai_build_generator import _load_shop
        shop = _load_shop()
        # Should have at least one known part type
        known = {"cockpit", "engine", "armor", "wheel", "weapon"}
        assert any(k in shop for k in known)

    def test_each_entry_has_tiers(self):
        from systems.ai_build_generator import _load_shop
        shop = _load_shop()
        for pt_name, pt_data in shop.items():
            assert "tiers" in pt_data, f"{pt_name} missing 'tiers'"

    def test_tiers_is_list(self):
        from systems.ai_build_generator import _load_shop
        shop = _load_shop()
        for pt_name, pt_data in shop.items():
            assert isinstance(pt_data["tiers"], list)


class TestApplyAiTiers:
    def _fake_vehicle(self):
        v = MagicMock()
        # Make a part with .part_type.value = "engine"
        part = MagicMock()
        part.part_type.value = "engine"
        part.hp = 100.0
        part.mass = 50.0
        v.parts = [part]
        return v, part

    def test_apply_ai_tiers_no_crash(self):
        from systems.ai_build_generator import apply_ai_tiers
        v, _ = self._fake_vehicle()
        apply_ai_tiers(v, {"engine": 0})

    def test_apply_ai_tiers_sets_tier(self):
        from systems.ai_build_generator import apply_ai_tiers
        v, part = self._fake_vehicle()
        apply_ai_tiers(v, {"engine": 1})
        assert part.tier == 1

    def test_apply_ai_tiers_empty_parts_no_crash(self):
        from systems.ai_build_generator import apply_ai_tiers
        v = MagicMock()
        v.parts = []
        apply_ai_tiers(v, {"engine": 0})

    def test_apply_ai_tiers_sets_tier_name(self):
        from systems.ai_build_generator import apply_ai_tiers
        v, part = self._fake_vehicle()
        apply_ai_tiers(v, {"engine": 0})
        assert isinstance(part.tier_name, str)

    def test_apply_ai_tiers_updates_thrust_mult(self):
        from systems.ai_build_generator import apply_ai_tiers
        v, part = self._fake_vehicle()
        apply_ai_tiers(v, {"engine": 0})
        assert isinstance(part.thrust_mult, float)

    def test_apply_ai_tiers_unknown_part_type_no_crash(self):
        from systems.ai_build_generator import apply_ai_tiers
        v = MagicMock()
        part = MagicMock()
        part.part_type.value = "completely_unknown_part_type"
        part.hp = 50.0
        part.mass = 10.0
        v.parts = [part]
        apply_ai_tiers(v, {})  # no entry for unknown type


# =============================================================================
# VehiclePart.__post_init__
# =============================================================================

class TestVehiclePartPostInit:
    def test_engine_part_has_hp(self):
        from entities.part import VehiclePart, PartType
        part = VehiclePart(PartType.ENGINE, grid_x=0, grid_y=0)
        assert part.hp > 0.0

    def test_engine_part_has_mass(self):
        from entities.part import VehiclePart, PartType
        part = VehiclePart(PartType.ENGINE, grid_x=0, grid_y=0)
        assert part.mass > 0.0

    def test_engine_part_has_color_tuple(self):
        from entities.part import VehiclePart, PartType
        part = VehiclePart(PartType.ENGINE, grid_x=0, grid_y=0)
        assert isinstance(part.color, tuple)
        assert len(part.color) in (3, 4)

    def test_wheel_part_defaults(self):
        from entities.part import VehiclePart, PartType
        part = VehiclePart(PartType.WHEEL, grid_x=1, grid_y=1)
        assert part.hp > 0.0
        assert part.thrust_mult == 1.0
        assert part.grip_mult == 1.0
        assert part.damage_mult == 1.0
        assert part.tier == 0

    def test_cockpit_part_has_name(self):
        from entities.part import VehiclePart, PartType
        part = VehiclePart(PartType.COCKPIT, grid_x=3, grid_y=3)
        assert isinstance(part.tier_name, str)
        assert len(part.tier_name) > 0

    def test_alive_when_hp_positive(self):
        from entities.part import VehiclePart, PartType
        part = VehiclePart(PartType.ARMOR, grid_x=0, grid_y=0)
        assert part.alive is True

    def test_not_alive_when_hp_zero(self):
        from entities.part import VehiclePart, PartType
        part = VehiclePart(PartType.ARMOR, grid_x=0, grid_y=0)
        part.hp = 0.0
        assert part.alive is False


# =============================================================================
# RadialRepairSystem — _get_repairer, _on_full, _on_radial
# =============================================================================

class TestRadialRepairSystemGetRepairer:
    def _system(self):
        from systems.repair_system import RadialRepairSystem
        return RadialRepairSystem(vehicles=[])

    def test_vehicle_without_deform_returns_none(self):
        sys_ = self._system()
        vehicle = MagicMock(spec=[])  # no _deform attribute
        result = sys_._get_repairer(vehicle)
        assert result is None
        sys_.teardown()

    def test_vehicle_with_deform_no_layer_returns_none(self):
        sys_ = self._system()
        vehicle = MagicMock()
        vehicle._deform = MagicMock()
        vehicle._deform.layer = None
        result = sys_._get_repairer(vehicle)
        assert result is None
        sys_.teardown()

    def test_vehicle_with_valid_deform_returns_repairer(self):
        from slappyengine.deform_repair import DeformRepairer
        sys_ = self._system()
        vehicle = MagicMock()
        vehicle._deform = MagicMock()
        vehicle._deform.layer = MagicMock()
        vehicle._deform._original_alpha = None
        result = sys_._get_repairer(vehicle)
        assert isinstance(result, DeformRepairer)
        sys_.teardown()

    def test_same_vehicle_returns_same_repairer(self):
        sys_ = self._system()
        vehicle = MagicMock()
        vehicle._deform = MagicMock()
        vehicle._deform.layer = MagicMock()
        vehicle._deform._original_alpha = None
        r1 = sys_._get_repairer(vehicle)
        r2 = sys_._get_repairer(vehicle)
        if r1 is not None:
            assert r1 is r2
        sys_.teardown()


class TestRadialRepairSystemOnFull:
    def _system(self):
        from systems.repair_system import RadialRepairSystem
        return RadialRepairSystem(vehicles=[])

    def test_on_full_no_target_no_crash(self):
        sys_ = self._system()
        evt = MagicMock()
        del evt.target  # make sure getattr returns None
        evt.configure_mock(**{"target": None})
        # Actually, just publish the event and check it doesn't crash
        from slappyengine.event_bus import publish
        publish("Repair.Full", target=None, rate=1.0)
        sys_.teardown()

    def test_on_full_with_valid_target_queues_repair(self):
        from slappyengine.event_bus import publish
        from slappyengine.deform_repair import DeformRepairer
        sys_ = self._system()
        vehicle = MagicMock()
        vehicle._deform = MagicMock()
        vehicle._deform.layer = MagicMock()
        vehicle._deform._original_alpha = None
        publish("Repair.Full", target=vehicle, rate=2.0)
        # A repairer should have been created
        assert id(vehicle) in sys_._repairers
        sys_.teardown()


class TestRadialRepairSystemOnRadial:
    def _system(self):
        from systems.repair_system import RadialRepairSystem
        return RadialRepairSystem(vehicles=[])

    def test_on_radial_no_target_no_crash(self):
        from slappyengine.event_bus import publish
        sys_ = self._system()
        publish("Repair.Radial", target=None, center_x=10, center_y=10, radius=20, rate=2.0)
        sys_.teardown()

    def test_on_radial_queues_repair(self):
        from slappyengine.event_bus import publish
        from slappyengine.deform_repair import DeformRepairer
        sys_ = self._system()
        vehicle = MagicMock()
        vehicle._deform = MagicMock()
        vehicle._deform.layer = MagicMock()
        vehicle._deform._original_alpha = None
        publish("Repair.Radial", target=vehicle, center_x=32, center_y=16,
                radius=20, rate=3.0)
        assert id(vehicle) in sys_._repairers
        r = sys_._repairers[id(vehicle)]
        assert len(r._pending) >= 1
        sys_.teardown()


# =============================================================================
# CollisionSystem static helpers — _push_velocity, _apply_damage
# =============================================================================

class TestCollisionSystemPushVelocity:
    def _cs(self):
        from systems.collision_system import CollisionSystem
        cs = CollisionSystem([])
        return cs

    def test_push_velocity_updates_tuple_vel(self):
        from systems.collision_system import CollisionSystem
        entity = MagicMock()
        entity.velocity = (10.0, 0.0)
        CollisionSystem._push_velocity(entity, 1.0, 0.0, 20.0)
        assert entity.velocity[0] == pytest.approx(30.0)
        assert entity.velocity[1] == pytest.approx(0.0)

    def test_push_velocity_no_velocity_attr_no_crash(self):
        from systems.collision_system import CollisionSystem
        entity = object()  # no velocity attribute
        CollisionSystem._push_velocity(entity, 1.0, 0.0, 10.0)

    def test_push_velocity_diagonal_normal(self):
        from systems.collision_system import CollisionSystem
        entity = MagicMock()
        entity.velocity = (0.0, 0.0)
        CollisionSystem._push_velocity(entity, 0.707, 0.707, 10.0)
        assert abs(entity.velocity[0] - 7.07) < 0.1
        assert abs(entity.velocity[1] - 7.07) < 0.1

    def test_push_velocity_zero_impulse_no_change(self):
        from systems.collision_system import CollisionSystem
        entity = MagicMock()
        entity.velocity = (5.0, 5.0)
        CollisionSystem._push_velocity(entity, 1.0, 0.0, 0.0)
        assert entity.velocity == (5.0, 5.0)


class TestCollisionSystemApplyDamage:
    def test_apply_damage_calls_take_damage(self):
        from systems.collision_system import CollisionSystem
        entity = MagicMock()
        CollisionSystem._apply_damage(entity, 20.0, (1.0, 0.0))
        entity.take_damage.assert_called_once()

    def test_apply_damage_zero_no_call(self):
        from systems.collision_system import CollisionSystem
        entity = MagicMock()
        CollisionSystem._apply_damage(entity, 0.0, (1.0, 0.0))
        entity.take_damage.assert_not_called()

    def test_apply_damage_negative_no_call(self):
        from systems.collision_system import CollisionSystem
        entity = MagicMock()
        CollisionSystem._apply_damage(entity, -5.0, (0.0, 1.0))
        entity.take_damage.assert_not_called()

    def test_apply_damage_no_take_damage_attr_no_crash(self):
        from systems.collision_system import CollisionSystem
        entity = object()  # no take_damage method
        CollisionSystem._apply_damage(entity, 15.0, (0.0, 1.0))


# =============================================================================
# CollisionSystem init + teardown
# =============================================================================

class TestCollisionSystemInitTeardown:
    def test_init_with_empty_list(self):
        from systems.collision_system import CollisionSystem
        cs = CollisionSystem([])
        assert cs is not None
        cs.teardown()

    def test_teardown_cleans_up(self):
        from systems.collision_system import CollisionSystem
        cs = CollisionSystem([])
        cs.teardown()
        # After teardown, handles should be gone — no exception

    def test_update_empty_no_crash(self):
        from systems.collision_system import CollisionSystem
        cs = CollisionSystem([])
        cs.update(0.016)
        cs.teardown()
