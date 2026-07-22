"""Headless tests for Ochema Circuit destruction system — ScrapEntity, CockpitPodEntity, DestructionScript."""
from __future__ import annotations
import sys
import math
from pathlib import Path
from unittest.mock import MagicMock
import pytest

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("pharos_engine.compute.asset_compute", MagicMock())

_OCHEMA_ROOT = Path(__file__).parent.parent.parent.parent.parent / "DaedalusSVN" / "Ochema Circuit"
_OCHEMA_STR = str(_OCHEMA_ROOT)

if _OCHEMA_STR not in sys.path:
    sys.path.insert(0, _OCHEMA_STR)


# =============================================================================
# Helpers
# =============================================================================

def _make_scrap(vx=50.0, vy=30.0):
    from systems.destruction import ScrapEntity
    part = MagicMock()
    return ScrapEntity(part=part, vx=vx, vy=vy)


def _make_pod(vx=10.0, vy=5.0, driver_id=1):
    from systems.destruction import CockpitPodEntity
    return CockpitPodEntity(vx=vx, vy=vy, driver_id=driver_id)


def _make_entity(armor=None, velocity=None, parts=None, driver_id=0):
    e = MagicMock()
    e.armor_hp = armor if armor is not None else {"FRONT": 80.0, "REAR": 80.0, "LEFT": 80.0, "RIGHT": 80.0}
    e.velocity = list(velocity) if velocity is not None else [0.0, 0.0]
    e.parts = parts if parts is not None else []
    e.driver_id = driver_id
    e.position = (200.0, 300.0)
    return e


# =============================================================================
# ScrapEntity
# =============================================================================

class TestScrapEntityInit:
    def test_init_no_crash(self):
        scrap = _make_scrap()
        assert scrap is not None

    def test_velocity_stored(self):
        scrap = _make_scrap(vx=40.0, vy=20.0)
        assert scrap.velocity == [40.0, 20.0]

    def test_part_stored(self):
        from systems.destruction import ScrapEntity
        part = MagicMock()
        scrap = ScrapEntity(part=part, vx=0.0, vy=0.0)
        assert scrap.part is part

    def test_has_collision_shape(self):
        scrap = _make_scrap()
        assert scrap.collision_shape is not None

    def test_collision_shape_size(self):
        scrap = _make_scrap()
        assert scrap.collision_shape.width == 14
        assert scrap.collision_shape.height == 14


class TestScrapEntityTick:
    def test_tick_advances_position_x(self):
        scrap = _make_scrap(vx=100.0, vy=0.0)
        scrap.position = (0.0, 0.0)
        scrap.tick(0.1)
        assert scrap.position[0] == pytest.approx(100.0 * 0.97 * 0.1)

    def test_tick_advances_position_y(self):
        scrap = _make_scrap(vx=0.0, vy=60.0)
        scrap.position = (0.0, 0.0)
        scrap.tick(0.1)
        assert scrap.position[1] == pytest.approx(60.0 * 0.97 * 0.1)

    def test_tick_decays_vx(self):
        scrap = _make_scrap(vx=100.0, vy=0.0)
        scrap.position = (0.0, 0.0)
        scrap.tick(0.016)
        assert scrap.velocity[0] == pytest.approx(100.0 * 0.97)

    def test_tick_decays_vy(self):
        scrap = _make_scrap(vx=0.0, vy=80.0)
        scrap.position = (0.0, 0.0)
        scrap.tick(0.016)
        assert scrap.velocity[1] == pytest.approx(80.0 * 0.97)

    def test_velocity_decays_over_multiple_ticks(self):
        scrap = _make_scrap(vx=100.0, vy=0.0)
        scrap.position = (0.0, 0.0)
        for _ in range(5):
            scrap.tick(0.016)
        expected_vx = 100.0 * (0.97 ** 5)
        assert scrap.velocity[0] == pytest.approx(expected_vx)

    def test_position_accumulates_correctly(self):
        scrap = _make_scrap(vx=50.0, vy=0.0)
        scrap.position = (100.0, 50.0)
        scrap.tick(0.016)
        assert scrap.position[0] == pytest.approx(100.0 + 50.0 * 0.97 * 0.016)

    def test_tick_with_negative_velocity(self):
        scrap = _make_scrap(vx=-80.0, vy=-40.0)
        scrap.position = (200.0, 150.0)
        scrap.tick(0.1)
        assert scrap.position[0] == pytest.approx(200.0 + (-80.0 * 0.97) * 0.1)
        assert scrap.position[1] == pytest.approx(150.0 + (-40.0 * 0.97) * 0.1)

    def test_zero_velocity_stays_put(self):
        scrap = _make_scrap(vx=0.0, vy=0.0)
        scrap.position = (100.0, 200.0)
        scrap.tick(0.1)
        assert scrap.position == pytest.approx((100.0, 200.0))


# =============================================================================
# CockpitPodEntity
# =============================================================================

class TestCockpitPodEntityInit:
    def test_init_no_crash(self):
        pod = _make_pod()
        assert pod is not None

    def test_driver_id_stored(self):
        pod = _make_pod(driver_id=3)
        assert pod.driver_id == 3

    def test_velocity_kick_applied_to_vy(self):
        # velocity_kick from config is 200.0
        pod = _make_pod(vx=10.0, vy=5.0)
        assert pod.velocity[1] == pytest.approx(5.0 + 200.0)

    def test_vx_stored_unchanged(self):
        pod = _make_pod(vx=25.0, vy=0.0)
        assert pod.velocity[0] == pytest.approx(25.0)

    def test_hp_initially_20(self):
        pod = _make_pod()
        assert pod.hp == pytest.approx(20.0)

    def test_has_collision_shape(self):
        pod = _make_pod()
        assert pod.collision_shape is not None

    def test_collision_shape_size(self):
        pod = _make_pod()
        assert pod.collision_shape.width == 16
        assert pod.collision_shape.height == 16


class TestCockpitPodHijack:
    def test_hijack_transfers_driver_id(self):
        pod = _make_pod(vx=5.0, vy=0.0, driver_id=2)
        pod.velocity = [5.0, 0.0]  # slow enough for hijack (< 60.0)
        pod.scene = MagicMock()

        other = MagicMock()
        other.driver_id = 99
        other.velocity = [0.0, 0.0]
        other.position = (100.0, 100.0)

        pod.on_collision(other, (1.0, 0.0))
        assert other.driver_id == 2

    def test_hijack_spawns_ejected_pod(self):
        pod = _make_pod(vx=5.0, vy=0.0, driver_id=2)
        pod.velocity = [5.0, 0.0]
        pod.scene = MagicMock()

        other = MagicMock()
        other.driver_id = 99
        other.velocity = [10.0, 5.0]
        other.position = (100.0, 100.0)

        pod.on_collision(other, (1.0, 0.0))
        pod.scene.add.assert_called_once()

    def test_hijack_removes_self_from_scene(self):
        pod = _make_pod(vx=5.0, vy=0.0, driver_id=2)
        pod.velocity = [5.0, 0.0]
        pod.scene = MagicMock()

        other = MagicMock()
        other.driver_id = 99
        other.velocity = [0.0, 0.0]
        other.position = (100.0, 100.0)

        pod.on_collision(other, (1.0, 0.0))
        pod.scene.remove.assert_called_once_with(pod)

    def test_no_hijack_when_too_fast(self):
        pod = _make_pod(vx=100.0, vy=100.0, driver_id=2)
        pod.velocity = [100.0, 100.0]  # speed = ~141 > 60 threshold
        pod.scene = MagicMock()

        other = MagicMock()
        other.driver_id = 99
        original_driver = 99

        pod.on_collision(other, (1.0, 0.0))
        # driver_id should not change
        assert other.driver_id == original_driver

    def test_no_hijack_when_other_has_no_driver_id(self):
        pod = _make_pod(vx=5.0, vy=0.0, driver_id=2)
        pod.velocity = [5.0, 0.0]
        pod.scene = MagicMock()

        other = MagicMock(spec=[])  # no driver_id attribute
        pod.on_collision(other, (1.0, 0.0))
        pod.scene.add.assert_not_called()

    def test_no_scene_skips_spawn_and_remove(self):
        # driver_id transfer still happens; scene=None only skips add/remove
        pod = _make_pod(vx=5.0, vy=0.0, driver_id=2)
        pod.velocity = [5.0, 0.0]
        pod.scene = None

        other = MagicMock()
        other.driver_id = 99
        other.velocity = [0.0, 0.0]
        other.position = (100.0, 100.0)

        pod.on_collision(other, (1.0, 0.0))  # no crash
        # driver transferred, but no scene.add/remove calls (scene is None)

    def test_ejected_pod_preserves_original_driver(self):
        pod = _make_pod(vx=5.0, vy=0.0, driver_id=2)
        pod.velocity = [5.0, 0.0]
        pod.scene = MagicMock()
        added = []
        pod.scene.add = lambda x: added.append(x)
        pod.scene.remove = MagicMock()

        other = MagicMock()
        other.driver_id = 77
        other.velocity = [10.0, 5.0]
        other.position = (100.0, 100.0)

        pod.on_collision(other, (1.0, 0.0))
        assert len(added) == 1
        from systems.destruction import CockpitPodEntity
        assert isinstance(added[0], CockpitPodEntity)
        assert added[0].driver_id == 77

    def test_hijack_pod_exactly_at_speed_threshold_no_hijack(self):
        # speed must be strictly less than hijack_max_speed (60.0)
        pod = _make_pod()
        pod.velocity = [60.0, 0.0]  # speed = 60.0, not < 60.0
        pod.scene = MagicMock()

        other = MagicMock()
        other.driver_id = 99

        pod.on_collision(other, (1.0, 0.0))
        assert other.driver_id == 99


# =============================================================================
# _direction_to_grid_edge
# =============================================================================

class TestDirectionToGridEdge:
    def test_front_returns_last_column(self):
        from systems.destruction import _direction_to_grid_edge
        gx, gy = _direction_to_grid_edge("FRONT", 5)
        assert gx == 4  # size - 1
        assert gy == -1

    def test_rear_returns_first_column(self):
        from systems.destruction import _direction_to_grid_edge
        gx, gy = _direction_to_grid_edge("REAR", 5)
        assert gx == 0
        assert gy == -1

    def test_left_returns_first_row(self):
        from systems.destruction import _direction_to_grid_edge
        gx, gy = _direction_to_grid_edge("LEFT", 5)
        assert gx == -1
        assert gy == 0

    def test_right_returns_last_row(self):
        from systems.destruction import _direction_to_grid_edge
        gx, gy = _direction_to_grid_edge("RIGHT", 5)
        assert gx == -1
        assert gy == 4  # size - 1

    def test_unknown_direction_returns_sentinel(self):
        from systems.destruction import _direction_to_grid_edge
        gx, gy = _direction_to_grid_edge("DIAGONAL", 5)
        assert gx == -1
        assert gy == -1

    def test_grid_size_1(self):
        from systems.destruction import _direction_to_grid_edge
        gx, gy = _direction_to_grid_edge("FRONT", 1)
        assert gx == 0

    def test_grid_size_3(self):
        from systems.destruction import _direction_to_grid_edge
        gx, gy = _direction_to_grid_edge("RIGHT", 3)
        assert gy == 2


# =============================================================================
# DestructionScript
# =============================================================================

class TestDestructionScriptDirectionFront:
    def test_large_ox_positive_is_front(self):
        from systems.destruction import DestructionScript
        ds = DestructionScript()
        e = _make_entity()
        ds.on_collision(e, MagicMock(), overlap=(10.0, 0.0))
        # FRONT armor should be reduced
        assert e.armor_hp["FRONT"] < 80.0

    def test_large_ox_negative_is_rear(self):
        from systems.destruction import DestructionScript
        ds = DestructionScript()
        e = _make_entity()
        ds.on_collision(e, MagicMock(), overlap=(-10.0, 0.0))
        assert e.armor_hp["REAR"] < 80.0

    def test_large_oy_positive_is_right(self):
        from systems.destruction import DestructionScript
        ds = DestructionScript()
        e = _make_entity()
        ds.on_collision(e, MagicMock(), overlap=(0.0, 10.0))
        assert e.armor_hp["RIGHT"] < 80.0

    def test_large_oy_negative_is_left(self):
        from systems.destruction import DestructionScript
        ds = DestructionScript()
        e = _make_entity()
        ds.on_collision(e, MagicMock(), overlap=(0.0, -10.0))
        assert e.armor_hp["LEFT"] < 80.0


class TestDestructionScriptDamage:
    def test_damage_is_mag_times_0_25(self):
        from systems.destruction import DestructionScript
        ds = DestructionScript()
        e = _make_entity(armor={"FRONT": 100.0})
        ds.on_collision(e, MagicMock(), overlap=(8.0, 0.0))
        expected = 100.0 - 8.0 * 0.25
        assert e.armor_hp["FRONT"] == pytest.approx(expected)

    def test_armor_clamped_to_zero(self):
        from systems.destruction import DestructionScript
        ds = DestructionScript()
        e = _make_entity(armor={"FRONT": 1.0})
        ds.on_collision(e, MagicMock(), overlap=(100.0, 0.0))
        assert e.armor_hp["FRONT"] == pytest.approx(0.0)

    def test_zero_overlap_returns_early(self):
        from systems.destruction import DestructionScript
        ds = DestructionScript()
        e = _make_entity(armor={"FRONT": 80.0})
        ds.on_collision(e, MagicMock(), overlap=(0.0, 0.0))
        assert e.armor_hp["FRONT"] == pytest.approx(80.0)

    def test_tiny_overlap_near_zero_returns_early(self):
        from systems.destruction import DestructionScript
        ds = DestructionScript()
        e = _make_entity(armor={"FRONT": 80.0})
        ds.on_collision(e, MagicMock(), overlap=(1e-8, 0.0))
        # mag < 1e-6, early return
        assert e.armor_hp["FRONT"] == pytest.approx(80.0)

    def test_diagonal_overlap_uses_larger_axis(self):
        from systems.destruction import DestructionScript
        ds = DestructionScript()
        e = _make_entity()
        # ox=6, oy=4 → abs(ox) >= abs(oy) → FRONT (ox > 0)
        ds.on_collision(e, MagicMock(), overlap=(6.0, 4.0))
        assert e.armor_hp["FRONT"] < 80.0
        assert e.armor_hp["RIGHT"] == pytest.approx(80.0)

    def test_diagonal_overlap_uses_larger_oy(self):
        from systems.destruction import DestructionScript
        ds = DestructionScript()
        e = _make_entity()
        # ox=3, oy=7 → abs(oy) > abs(ox) → RIGHT (oy > 0)
        ds.on_collision(e, MagicMock(), overlap=(3.0, 7.0))
        assert e.armor_hp["RIGHT"] < 80.0
        assert e.armor_hp["FRONT"] == pytest.approx(80.0)

    def test_equal_ox_oy_uses_ox_branch(self):
        from systems.destruction import DestructionScript
        ds = DestructionScript()
        e = _make_entity()
        # abs(ox) == abs(oy) → uses ox branch (FRONT when ox > 0)
        ds.on_collision(e, MagicMock(), overlap=(5.0, 5.0))
        assert e.armor_hp["FRONT"] < 80.0


class TestDestructionScriptPartCheck:
    def test_no_crash_with_empty_parts(self):
        from systems.destruction import DestructionScript
        ds = DestructionScript()
        e = _make_entity(parts=[])
        ds.on_collision(e, MagicMock(), overlap=(10.0, 0.0))

    def test_dead_part_skipped(self):
        from systems.destruction import DestructionScript
        ds = DestructionScript()
        part = MagicMock()
        part.alive = False
        part.grid_x = 3
        part.grid_y = 0
        e = _make_entity(parts=[part])
        ds.on_collision(e, MagicMock(), overlap=(10.0, 0.0))
        part.take_damage.assert_not_called()

    def test_alive_part_at_edge_takes_damage(self):
        from systems.destruction import DestructionScript
        from systems.grid_builder import GRID_SIZE
        ds = DestructionScript()
        part = MagicMock()
        part.alive = True
        part.grid_x = GRID_SIZE - 1  # FRONT edge
        part.grid_y = -1  # no y match
        part.take_damage.return_value = False
        e = _make_entity(parts=[part], armor={"FRONT": 80.0})
        ds.on_collision(e, MagicMock(), overlap=(10.0, 0.0))
        part.take_damage.assert_called_once()


class TestDestructionScriptDetach:
    def test_destroyed_part_added_as_scrap(self):
        from systems.destruction import DestructionScript, ScrapEntity
        from systems.grid_builder import GRID_SIZE
        ds = DestructionScript()
        part = MagicMock()
        part.alive = True
        part.grid_x = GRID_SIZE - 1
        part.grid_y = -1
        part.take_damage.return_value = True  # destroyed!
        part.part_type = MagicMock()  # not COCKPIT
        from entities.part import PartType
        part.part_type = PartType.ENGINE  # not cockpit, no ejection
        e = _make_entity(parts=[part], velocity=[20.0, 10.0])
        e.scene = MagicMock()

        ds.on_collision(e, MagicMock(), overlap=(10.0, 0.0))
        added_objects = [c.args[0] for c in e.scene.add.call_args_list]
        assert any(isinstance(o, ScrapEntity) for o in added_objects)

    def test_scrap_velocity_is_half_entity_velocity(self):
        from systems.destruction import DestructionScript, ScrapEntity
        from systems.grid_builder import GRID_SIZE
        from entities.part import PartType
        ds = DestructionScript()
        part = MagicMock()
        part.alive = True
        part.grid_x = GRID_SIZE - 1
        part.grid_y = -1
        part.take_damage.return_value = True
        part.part_type = PartType.ENGINE
        e = _make_entity(parts=[part], velocity=[40.0, 20.0])
        e.scene = MagicMock()
        added = []
        e.scene.add = lambda x: added.append(x)
        e.remove_part = MagicMock()

        ds.on_collision(e, MagicMock(), overlap=(10.0, 0.0))
        scrap_list = [o for o in added if isinstance(o, ScrapEntity)]
        assert len(scrap_list) == 1
        assert scrap_list[0].velocity[0] == pytest.approx(20.0)
        assert scrap_list[0].velocity[1] == pytest.approx(10.0)

    def test_cockpit_destruction_triggers_eject(self):
        from systems.destruction import DestructionScript, CockpitPodEntity
        from systems.grid_builder import GRID_SIZE
        from entities.part import PartType
        ds = DestructionScript()
        part = MagicMock()
        part.alive = True
        part.grid_x = GRID_SIZE - 1
        part.grid_y = -1
        part.take_damage.return_value = True
        part.part_type = PartType.COCKPIT  # triggers ejection!
        e = _make_entity(parts=[part], velocity=[10.0, 5.0], driver_id=7)
        e.scene = MagicMock()
        added = []
        e.scene.add = lambda x: added.append(x)
        e.scene.remove = MagicMock()
        e.remove_part = MagicMock()

        ds.on_collision(e, MagicMock(), overlap=(10.0, 0.0))
        pods = [o for o in added if isinstance(o, CockpitPodEntity)]
        assert len(pods) >= 1
        assert pods[0].driver_id == 7

    def test_detach_no_scene_does_not_crash(self):
        from systems.destruction import DestructionScript
        from systems.grid_builder import GRID_SIZE
        from entities.part import PartType
        ds = DestructionScript()
        part = MagicMock()
        part.alive = True
        part.grid_x = GRID_SIZE - 1
        part.grid_y = -1
        part.take_damage.return_value = True
        part.part_type = PartType.ENGINE
        e = _make_entity(parts=[part], velocity=[10.0, 0.0])
        e.scene = None  # no scene
        e.remove_part = MagicMock()

        # Should not crash
        ds.on_collision(e, MagicMock(), overlap=(10.0, 0.0))
