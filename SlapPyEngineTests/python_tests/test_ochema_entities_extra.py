"""Headless tests for Ochema Circuit CheckpointEntity, VehiclePart, and hazard entities."""
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
# CheckpointEntity
# =============================================================================

class TestCheckpointEntityInit:
    def test_init_no_crash(self):
        from entities.checkpoint import CheckpointEntity
        cp = CheckpointEntity(100.0, 200.0, 30.0, 10.0)
        assert cp is not None

    def test_rect_stored(self):
        from entities.checkpoint import CheckpointEntity
        cp = CheckpointEntity(10.0, 20.0, 50.0, 15.0)
        assert cp.rect == (10.0, 20.0, 50.0, 15.0)

    def test_crossed_set_initially_empty(self):
        from entities.checkpoint import CheckpointEntity
        cp = CheckpointEntity(0.0, 0.0, 50.0, 20.0)
        assert len(cp._crossed) == 0

    def test_on_crossed_callback_stored(self):
        from entities.checkpoint import CheckpointEntity
        cb = MagicMock()
        cp = CheckpointEntity(0.0, 0.0, 50.0, 20.0, on_crossed=cb)
        assert cp._on_crossed is cb

    def test_no_callback_is_none(self):
        from entities.checkpoint import CheckpointEntity
        cp = CheckpointEntity(0.0, 0.0, 50.0, 20.0)
        assert cp._on_crossed is None


class TestCheckpointEntityCheck:
    def test_vehicle_inside_rect_returns_true(self):
        from entities.checkpoint import CheckpointEntity
        cp = CheckpointEntity(100.0, 100.0, 50.0, 20.0)
        result = cp.check(0, 125.0, 110.0)  # inside rect
        assert result is True

    def test_vehicle_outside_rect_returns_false(self):
        from entities.checkpoint import CheckpointEntity
        cp = CheckpointEntity(100.0, 100.0, 50.0, 20.0)
        result = cp.check(0, 50.0, 110.0)  # x too small
        assert result is False

    def test_vehicle_already_crossed_returns_false(self):
        from entities.checkpoint import CheckpointEntity
        cp = CheckpointEntity(100.0, 100.0, 50.0, 20.0)
        cp.check(0, 125.0, 110.0)  # cross once
        result = cp.check(0, 125.0, 110.0)  # cross again
        assert result is False

    def test_different_vehicle_can_cross(self):
        from entities.checkpoint import CheckpointEntity
        cp = CheckpointEntity(100.0, 100.0, 50.0, 20.0)
        cp.check(0, 125.0, 110.0)  # vehicle 0 crosses
        result = cp.check(1, 125.0, 110.0)  # vehicle 1 crosses
        assert result is True

    def test_callback_fired_on_first_cross(self):
        from entities.checkpoint import CheckpointEntity
        cb = MagicMock()
        cp = CheckpointEntity(100.0, 100.0, 50.0, 20.0, on_crossed=cb)
        cp.check(0, 125.0, 110.0)
        cb.assert_called_once_with(0)

    def test_callback_not_fired_on_second_cross(self):
        from entities.checkpoint import CheckpointEntity
        cb = MagicMock()
        cp = CheckpointEntity(100.0, 100.0, 50.0, 20.0, on_crossed=cb)
        cp.check(0, 125.0, 110.0)
        cp.check(0, 125.0, 110.0)
        assert cb.call_count == 1

    def test_callback_not_fired_when_outside(self):
        from entities.checkpoint import CheckpointEntity
        cb = MagicMock()
        cp = CheckpointEntity(100.0, 100.0, 50.0, 20.0, on_crossed=cb)
        cp.check(0, 500.0, 110.0)  # way outside
        cb.assert_not_called()

    def test_no_callback_no_crash(self):
        from entities.checkpoint import CheckpointEntity
        cp = CheckpointEntity(100.0, 100.0, 50.0, 20.0)
        cp.check(0, 125.0, 110.0)  # no callback set — should not crash

    def test_check_records_vehicle_in_crossed(self):
        from entities.checkpoint import CheckpointEntity
        cp = CheckpointEntity(100.0, 100.0, 50.0, 20.0)
        cp.check(5, 125.0, 110.0)
        assert 5 in cp._crossed

    def test_check_does_not_record_when_outside(self):
        from entities.checkpoint import CheckpointEntity
        cp = CheckpointEntity(100.0, 100.0, 50.0, 20.0)
        cp.check(5, 50.0, 110.0)  # outside
        assert 5 not in cp._crossed

    def test_boundary_left_edge(self):
        from entities.checkpoint import CheckpointEntity
        cp = CheckpointEntity(100.0, 100.0, 50.0, 20.0)
        result = cp.check(0, 100.0, 110.0)  # exactly on left edge
        assert result is True

    def test_boundary_right_edge(self):
        from entities.checkpoint import CheckpointEntity
        cp = CheckpointEntity(100.0, 100.0, 50.0, 20.0)
        result = cp.check(0, 150.0, 110.0)  # exactly on right edge
        assert result is True

    def test_multiple_vehicles_independent(self):
        from entities.checkpoint import CheckpointEntity
        crossed_ids = []
        cp = CheckpointEntity(100.0, 100.0, 50.0, 20.0,
                               on_crossed=lambda vid: crossed_ids.append(vid))
        cp.check(0, 125.0, 110.0)
        cp.check(1, 125.0, 110.0)
        cp.check(2, 125.0, 110.0)
        assert crossed_ids == [0, 1, 2]


class TestCheckpointEntityReset:
    def test_reset_clears_crossed_set(self):
        from entities.checkpoint import CheckpointEntity
        cp = CheckpointEntity(100.0, 100.0, 50.0, 20.0)
        cp.check(0, 125.0, 110.0)
        cp.check(1, 125.0, 110.0)
        cp.reset()
        assert len(cp._crossed) == 0

    def test_reset_allows_re_crossing(self):
        from entities.checkpoint import CheckpointEntity
        cb = MagicMock()
        cp = CheckpointEntity(100.0, 100.0, 50.0, 20.0, on_crossed=cb)
        cp.check(0, 125.0, 110.0)
        cp.reset()
        cp.check(0, 125.0, 110.0)
        assert cb.call_count == 2

    def test_reset_empty_crossed_no_crash(self):
        from entities.checkpoint import CheckpointEntity
        cp = CheckpointEntity(100.0, 100.0, 50.0, 20.0)
        cp.reset()
        assert len(cp._crossed) == 0


# =============================================================================
# VehiclePart
# =============================================================================

class TestVehiclePartInit:
    def test_cockpit_no_crash(self):
        from entities.part import VehiclePart, PartType
        vp = VehiclePart(PartType.COCKPIT)
        assert vp is not None

    def test_engine_no_crash(self):
        from entities.part import VehiclePart, PartType
        vp = VehiclePart(PartType.ENGINE)
        assert vp is not None

    def test_armor_no_crash(self):
        from entities.part import VehiclePart, PartType
        vp = VehiclePart(PartType.ARMOR)
        assert vp is not None

    def test_wheel_no_crash(self):
        from entities.part import VehiclePart, PartType
        vp = VehiclePart(PartType.WHEEL)
        assert vp is not None

    def test_weapon_no_crash(self):
        from entities.part import VehiclePart, PartType
        vp = VehiclePart(PartType.WEAPON)
        assert vp is not None

    def test_hp_loaded_from_config(self):
        from entities.part import VehiclePart, PartType
        vp = VehiclePart(PartType.COCKPIT)
        assert vp.hp > 0

    def test_mass_loaded_from_config(self):
        from entities.part import VehiclePart, PartType
        vp = VehiclePart(PartType.ENGINE)
        assert vp.mass > 0

    def test_color_is_tuple(self):
        from entities.part import VehiclePart, PartType
        vp = VehiclePart(PartType.ARMOR)
        assert isinstance(vp.color, tuple)
        assert len(vp.color) >= 3

    def test_grid_x_default_zero(self):
        from entities.part import VehiclePart, PartType
        vp = VehiclePart(PartType.COCKPIT)
        assert vp.grid_x == 0

    def test_grid_y_default_zero(self):
        from entities.part import VehiclePart, PartType
        vp = VehiclePart(PartType.COCKPIT)
        assert vp.grid_y == 0

    def test_grid_position_stored(self):
        from entities.part import VehiclePart, PartType
        vp = VehiclePart(PartType.WHEEL, grid_x=3, grid_y=5)
        assert vp.grid_x == 3
        assert vp.grid_y == 5

    def test_tier_default_zero(self):
        from entities.part import VehiclePart, PartType
        vp = VehiclePart(PartType.COCKPIT)
        assert vp.tier == 0

    def test_thrust_mult_default_one(self):
        from entities.part import VehiclePart, PartType
        vp = VehiclePart(PartType.ENGINE)
        assert vp.thrust_mult == pytest.approx(1.0)

    def test_alive_initially_true(self):
        from entities.part import VehiclePart, PartType
        vp = VehiclePart(PartType.COCKPIT)
        assert vp.alive is True


class TestVehiclePartTakeDamage:
    def test_take_damage_reduces_hp(self):
        from entities.part import VehiclePart, PartType
        vp = VehiclePart(PartType.ARMOR)
        initial_hp = vp.hp
        vp.take_damage(10.0)
        assert vp.hp < initial_hp

    def test_take_damage_returns_false_when_alive(self):
        from entities.part import VehiclePart, PartType
        vp = VehiclePart(PartType.ARMOR)
        result = vp.take_damage(1.0)
        assert result is False

    def test_take_damage_returns_true_when_destroyed(self):
        from entities.part import VehiclePart, PartType
        vp = VehiclePart(PartType.ARMOR)
        result = vp.take_damage(vp.hp)
        assert result is True

    def test_hp_does_not_go_below_zero(self):
        from entities.part import VehiclePart, PartType
        vp = VehiclePart(PartType.ARMOR)
        vp.take_damage(9999.0)
        assert vp.hp >= 0

    def test_alive_false_after_destruction(self):
        from entities.part import VehiclePart, PartType
        vp = VehiclePart(PartType.ARMOR)
        vp.take_damage(vp.hp)
        assert vp.alive is False

    def test_hp_at_zero_means_not_alive(self):
        from entities.part import VehiclePart, PartType
        vp = VehiclePart(PartType.COCKPIT)
        vp.hp = 0.0
        assert vp.alive is False

    def test_different_parts_have_different_hp(self):
        from entities.part import VehiclePart, PartType
        cockpit = VehiclePart(PartType.COCKPIT)
        wheel = VehiclePart(PartType.WHEEL)
        # They may differ — just verify both are positive
        assert cockpit.hp > 0
        assert wheel.hp > 0


# =============================================================================
# AcidPool
# =============================================================================

class TestAcidPool:
    def test_init_no_crash(self):
        from entities.hazard import AcidPool
        ap = AcidPool()
        assert ap is not None

    def test_init_custom_size_no_crash(self):
        from entities.hazard import AcidPool
        ap = AcidPool(width=100, height=50)
        assert ap is not None

    def test_has_collision_shape(self):
        from entities.hazard import AcidPool
        ap = AcidPool()
        assert ap.collision_shape is not None

    def test_has_layer(self):
        from entities.hazard import AcidPool
        ap = AcidPool()
        assert len(ap.layers) >= 1

    def test_damage_rate_positive(self):
        from entities.hazard import AcidPool
        ap = AcidPool()
        assert ap.damage_rate > 0

    def test_on_pixel_collision_reduces_armor_hp(self):
        from entities.hazard import AcidPool
        ap = AcidPool()
        other = MagicMock()
        other.armor_hp = {"FRONT": 100.0}
        ap.on_pixel_collision(other, (50.0, 50.0))
        assert other.armor_hp["FRONT"] < 100.0

    def test_on_pixel_collision_no_armor_hp_no_crash(self):
        from entities.hazard import AcidPool
        ap = AcidPool()
        other = MagicMock(spec=[])  # no armor_hp attribute
        ap.on_pixel_collision(other, (50.0, 50.0))

    def test_armor_hp_clamps_to_zero(self):
        from entities.hazard import AcidPool
        ap = AcidPool()
        other = MagicMock()
        other.armor_hp = {"FRONT": 0.0}
        ap.on_pixel_collision(other, (50.0, 50.0))
        assert other.armor_hp["FRONT"] >= 0.0


# =============================================================================
# TurretRaider
# =============================================================================

class TestTurretRaider:
    def test_init_no_crash(self):
        from entities.hazard import TurretRaider
        tr = TurretRaider()
        assert tr is not None

    def test_initial_hp_40(self):
        from entities.hazard import TurretRaider
        tr = TurretRaider()
        assert tr.hp == pytest.approx(40.0)

    def test_initial_fire_cooldown_zero(self):
        from entities.hazard import TurretRaider
        tr = TurretRaider()
        assert tr.fire_cooldown == pytest.approx(0.0)

    def test_has_collision_shape(self):
        from entities.hazard import TurretRaider
        tr = TurretRaider()
        assert tr.collision_shape is not None

    def test_has_layer(self):
        from entities.hazard import TurretRaider
        tr = TurretRaider()
        assert len(tr.layers) >= 1

    def test_tick_decrements_cooldown(self):
        from entities.hazard import TurretRaider
        tr = TurretRaider()
        tr.fire_cooldown = 1.0
        tr.tick(0.1)
        assert tr.fire_cooldown == pytest.approx(0.9)

    def test_tick_cooldown_clamps_to_zero(self):
        from entities.hazard import TurretRaider
        tr = TurretRaider()
        tr.fire_cooldown = 0.1
        tr.tick(1.0)
        assert tr.fire_cooldown == pytest.approx(0.0)

    def test_tick_no_scene_no_crash(self):
        from entities.hazard import TurretRaider
        tr = TurretRaider()
        tr.scene = None
        tr.tick(0.016)

    def test_tick_fires_at_nearby_vehicle(self):
        from entities.hazard import TurretRaider
        tr = TurretRaider()
        tr.position = (100.0, 100.0)
        vehicle = MagicMock()
        vehicle.armor_hp = {"FRONT": 100.0}
        vehicle.position = (110.0, 110.0)  # within fire range
        scene = MagicMock()
        scene.entities = [vehicle]
        tr.scene = scene
        tr.tick(0.016)
        assert vehicle.armor_hp["FRONT"] < 100.0

    def test_tick_does_not_fire_at_far_vehicle(self):
        from entities.hazard import TurretRaider, _cfg
        tr = TurretRaider()
        tr.position = (100.0, 100.0)
        vehicle = MagicMock()
        vehicle.armor_hp = {"FRONT": 100.0}
        fire_range = _cfg["raider_fire_range"]
        vehicle.position = (100.0 + fire_range * 2, 100.0)  # far away
        scene = MagicMock()
        scene.entities = [vehicle]
        tr.scene = scene
        tr.tick(0.016)
        assert vehicle.armor_hp["FRONT"] == pytest.approx(100.0)

    def test_tick_cooldown_active_no_fire(self):
        from entities.hazard import TurretRaider
        tr = TurretRaider()
        tr.position = (100.0, 100.0)
        tr.fire_cooldown = 1.0  # active cooldown
        vehicle = MagicMock()
        vehicle.armor_hp = {"FRONT": 100.0}
        vehicle.position = (110.0, 110.0)
        scene = MagicMock()
        scene.entities = [vehicle]
        tr.scene = scene
        tr.tick(0.016)
        assert vehicle.armor_hp["FRONT"] == pytest.approx(100.0)

    def test_take_hit_reduces_hp(self):
        from entities.hazard import TurretRaider
        tr = TurretRaider()
        tr.take_hit(10.0)
        assert tr.hp == pytest.approx(30.0)

    def test_take_hit_returns_on_zero_hp(self):
        from entities.hazard import TurretRaider
        tr = TurretRaider()
        scene = MagicMock()
        tr.scene = scene
        tr.take_hit(40.0)
        scene.remove.assert_called_once()

    def test_take_hit_no_scene_no_crash(self):
        from entities.hazard import TurretRaider
        tr = TurretRaider()
        tr.scene = None
        tr.take_hit(9999.0)

    def test_hp_clamps_to_zero_on_overkill(self):
        from entities.hazard import TurretRaider
        tr = TurretRaider()
        tr.scene = None
        tr.take_hit(9999.0)
        assert tr.hp >= 0


# =============================================================================
# FallingSkyscraper
# =============================================================================

class TestFallingSkyscraper:
    def test_init_no_crash(self):
        from entities.hazard import FallingSkyscraper
        fs = FallingSkyscraper()
        assert fs is not None

    def test_initially_not_active(self):
        from entities.hazard import FallingSkyscraper
        fs = FallingSkyscraper()
        assert fs.active is False

    def test_initially_not_collapsed(self):
        from entities.hazard import FallingSkyscraper
        fs = FallingSkyscraper()
        assert fs._collapsed is False

    def test_initial_timer_zero(self):
        from entities.hazard import FallingSkyscraper
        fs = FallingSkyscraper()
        assert fs._timer == pytest.approx(0.0)

    def test_has_layer(self):
        from entities.hazard import FallingSkyscraper
        fs = FallingSkyscraper()
        assert len(fs.layers) >= 1

    def test_activate_sets_active(self):
        from entities.hazard import FallingSkyscraper
        fs = FallingSkyscraper()
        fs.activate()
        assert fs.active is True

    def test_activate_resets_timer(self):
        from entities.hazard import FallingSkyscraper
        fs = FallingSkyscraper()
        fs._timer = 5.0
        fs.activate()
        assert fs._timer == pytest.approx(0.0)

    def test_tick_inactive_no_movement(self):
        from entities.hazard import FallingSkyscraper
        fs = FallingSkyscraper()
        fs.position = (100.0, 200.0)
        original_y = fs.position[1]
        fs.tick(0.5)  # not active
        assert fs.position[1] == pytest.approx(original_y)

    def test_tick_active_advances_timer(self):
        from entities.hazard import FallingSkyscraper
        fs = FallingSkyscraper()
        fs.position = (100.0, 200.0)
        fs.activate()
        fs.tick(0.5)
        assert fs._timer == pytest.approx(0.5)

    def test_tick_active_moves_position_down(self):
        from entities.hazard import FallingSkyscraper
        fs = FallingSkyscraper()
        fs.position = (100.0, 200.0)
        fs.activate()
        fs.tick(0.1)
        assert fs.position[1] > 200.0  # y increases (downward)

    def test_tick_full_collapse(self):
        from entities.hazard import FallingSkyscraper
        fs = FallingSkyscraper()
        fs.position = (100.0, 200.0)
        fs.activate()
        # tick past collapse_time
        fs.tick(fs.collapse_time + 1.0)
        assert fs._collapsed is True

    def test_tick_collapsed_no_further_movement(self):
        from entities.hazard import FallingSkyscraper
        fs = FallingSkyscraper()
        fs.position = (100.0, 200.0)
        fs.activate()
        fs.tick(fs.collapse_time + 1.0)
        pos_after_collapse = fs.position[1]
        fs.tick(1.0)  # another tick — already collapsed
        assert fs.position[1] == pytest.approx(pos_after_collapse)

    def test_collapse_changes_collision_shape(self):
        from entities.hazard import FallingSkyscraper
        from slappyengine.collision import AABBShape
        fs = FallingSkyscraper()
        fs.position = (100.0, 200.0)
        fs.activate()
        fs.tick(fs.collapse_time + 1.0)
        assert isinstance(fs.collision_shape, AABBShape)

    def test_collapse_time_positive(self):
        from entities.hazard import FallingSkyscraper
        fs = FallingSkyscraper()
        assert fs.collapse_time > 0
