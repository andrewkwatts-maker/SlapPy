"""Headless tests for Bullet Strata CoverBlock, ParticleBurst, and WeaponPickup."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock
import pytest

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("slappyengine.compute.asset_compute", MagicMock())

_STRATA_ROOT = Path(__file__).parent.parent.parent.parent.parent / "DaedalusSVN" / "Bullet Strata"
_STRATA_STR = str(_STRATA_ROOT)

_CONFLICT_PKGS = ("systems", "entities", "scenes")


@pytest.fixture(autouse=True)
def _strata_isolation():
    stale = [k for k in sys.modules
             if k in _CONFLICT_PKGS or any(k.startswith(p + ".") for p in _CONFLICT_PKGS)]
    saved = {k: sys.modules.pop(k) for k in stale}
    if _STRATA_STR in sys.path:
        sys.path.remove(_STRATA_STR)
    sys.path.insert(0, _STRATA_STR)
    yield
    strata_keys = [k for k in sys.modules
                   if k in _CONFLICT_PKGS or any(k.startswith(p + ".") for p in _CONFLICT_PKGS)]
    for k in strata_keys:
        del sys.modules[k]
    if _STRATA_STR in sys.path:
        sys.path.remove(_STRATA_STR)
    sys.modules.update(saved)


# =============================================================================
# CoverBlock
# =============================================================================

class TestCoverBlockInit:
    def test_init_strata_0_no_crash(self):
        from entities.cover import CoverBlock
        cb = CoverBlock(strata_index=0)
        assert cb is not None

    def test_init_strata_1_no_crash(self):
        from entities.cover import CoverBlock
        cb = CoverBlock(strata_index=1)
        assert cb is not None

    def test_init_strata_2_no_crash(self):
        from entities.cover import CoverBlock
        cb = CoverBlock(strata_index=2)
        assert cb is not None

    def test_alive_initially(self):
        from entities.cover import CoverBlock
        cb = CoverBlock()
        assert cb.alive is True

    def test_has_layer(self):
        from entities.cover import CoverBlock
        cb = CoverBlock()
        assert len(cb.layers) >= 1

    def test_strata_0_high_hp(self):
        from entities.cover import CoverBlock
        cb = CoverBlock(strata_index=0)
        assert cb._max_hp == 150

    def test_strata_1_lower_hp(self):
        from entities.cover import CoverBlock
        cb = CoverBlock(strata_index=1)
        assert cb._max_hp == 60

    def test_strata_index_stored(self):
        from entities.cover import CoverBlock
        cb = CoverBlock(strata_index=2)
        assert cb.strata_index == 2

    def test_hits_taken_initially_zero(self):
        from entities.cover import CoverBlock
        cb = CoverBlock()
        assert cb._hits_taken == 0


class TestCoverBlockRect:
    def test_rect_returns_four_values(self):
        from entities.cover import CoverBlock
        cb = CoverBlock()
        rect = cb.rect
        assert isinstance(rect, tuple)
        assert len(rect) == 4

    def test_rect_size_matches_constants(self):
        from entities.cover import CoverBlock, COVER_W, COVER_H
        cb = CoverBlock()
        cb.position = (0.0, 0.0)
        x, y, w, h = cb.rect
        assert w == COVER_W
        assert h == COVER_H

    def test_rect_offset_from_position(self):
        from entities.cover import CoverBlock, COVER_W, COVER_H
        cb = CoverBlock()
        cb.position = (100.0, 100.0)
        x, y, w, h = cb.rect
        assert x == pytest.approx(100.0 - COVER_W / 2)
        assert y == pytest.approx(100.0 - COVER_H / 2)


class TestCoverBlockTakeDamage:
    def test_take_damage_returns_false_when_alive(self):
        from entities.cover import CoverBlock
        cb = CoverBlock(strata_index=0)
        result = cb.take_damage(1)
        assert result is False

    def test_take_damage_accumulates_hits(self):
        from entities.cover import CoverBlock
        cb = CoverBlock()
        cb.take_damage(50)
        assert cb._hits_taken == 50

    def test_take_damage_reaches_max_returns_true(self):
        from entities.cover import CoverBlock
        cb = CoverBlock(strata_index=0)
        result = cb.take_damage(cb._max_hp)
        assert result is True

    def test_take_damage_marks_not_alive_at_max(self):
        from entities.cover import CoverBlock
        cb = CoverBlock(strata_index=1)
        cb.take_damage(cb._max_hp)
        assert cb.alive is False

    def test_take_damage_with_contact_pos_no_crash(self):
        from entities.cover import CoverBlock
        cb = CoverBlock(strata_index=0)
        cb.position = (50.0, 50.0)
        result = cb.take_damage(10, contact_pos=(50.0, 50.0))
        assert isinstance(result, bool)

    def test_glass_destroyed_faster(self):
        from entities.cover import CoverBlock
        glass = CoverBlock(strata_index=1)  # glass, max_hp=60
        stone = CoverBlock(strata_index=0)  # stone, max_hp=150
        assert glass._max_hp < stone._max_hp


# =============================================================================
# ParticleBurst
# =============================================================================

class TestParticleBurst:
    def test_init_no_crash(self):
        from entities.particle_burst import ParticleBurst
        pb = ParticleBurst(count=5)
        assert pb is not None

    def test_alive_initially(self):
        from entities.particle_burst import ParticleBurst
        pb = ParticleBurst(count=5)
        assert pb._alive is True

    def test_has_layer(self):
        from entities.particle_burst import ParticleBurst
        pb = ParticleBurst(count=5)
        assert len(pb.layers) >= 1

    def test_tick_no_crash_when_not_alive(self):
        from entities.particle_burst import ParticleBurst
        pb = ParticleBurst(count=5)
        pb._alive = False
        pb.tick(0.016)

    def test_tick_no_crash_normally(self):
        from entities.particle_burst import ParticleBurst
        pb = ParticleBurst(count=5)
        pb.tick(0.016)

    def test_spawn_burst_with_mock_scene(self):
        from entities.particle_burst import spawn_burst
        scene = MagicMock()
        scene.add = MagicMock()
        result = spawn_burst(scene, position=(100.0, 200.0), count=3)
        scene.add.assert_called_once()

    def test_spawn_burst_sets_position(self):
        from entities.particle_burst import spawn_burst, ParticleBurst
        scene = MagicMock()
        added = []
        scene.add = lambda x: added.append(x)
        spawn_burst(scene, position=(42.0, 77.0), count=3)
        assert len(added) == 1
        assert added[0].position == (42.0, 77.0)

    def test_custom_color_stored(self):
        from entities.particle_burst import ParticleBurst
        pb = ParticleBurst(count=5, color=(200, 50, 100))
        assert pb is not None  # just no crash

    def test_layer_size_matches_tex_size(self):
        from entities.particle_burst import ParticleBurst
        pb = ParticleBurst(count=5, tex_size=64)
        layer = pb.layers[0]
        assert layer._image_data.shape[0] == 64
        assert layer._image_data.shape[1] == 64


# =============================================================================
# WeaponPickup
# =============================================================================

class TestWeaponPickup:
    def test_init_no_crash(self):
        from entities.weapon_pickup import WeaponPickup
        wp = WeaponPickup("pistol")
        assert wp is not None

    def test_weapon_type_stored(self):
        from entities.weapon_pickup import WeaponPickup
        wp = WeaponPickup("laser")
        assert wp.weapon_type == "laser"

    def test_has_collision_shape(self):
        from entities.weapon_pickup import WeaponPickup
        wp = WeaponPickup("pistol")
        assert wp.collision_shape is not None

    def test_has_layer(self):
        from entities.weapon_pickup import WeaponPickup
        wp = WeaponPickup("rocket")
        assert len(wp.layers) >= 1

    def test_bob_timer_initially_zero(self):
        from entities.weapon_pickup import WeaponPickup
        wp = WeaponPickup("pistol")
        assert wp._bob_timer == pytest.approx(0.0)

    def test_on_spawn_saves_base_y(self):
        from entities.weapon_pickup import WeaponPickup
        wp = WeaponPickup("pistol")
        wp.position = (100.0, 250.0)
        wp.on_spawn()
        assert wp._base_y == pytest.approx(250.0)

    def test_tick_advances_bob_timer(self):
        from entities.weapon_pickup import WeaponPickup
        wp = WeaponPickup("pistol")
        wp.position = (0.0, 100.0)
        wp.on_spawn()
        wp.tick(0.1)
        assert wp._bob_timer == pytest.approx(0.1)

    def test_tick_oscillates_y_position(self):
        import math
        from entities.weapon_pickup import WeaponPickup
        wp = WeaponPickup("pistol")
        wp.position = (50.0, 100.0)
        wp.on_spawn()
        wp.tick(0.5)
        expected_y = 100.0 + math.sin(0.5 * 2.5) * 6.0
        assert wp.position[1] == pytest.approx(expected_y)

    def test_tick_preserves_x_position(self):
        from entities.weapon_pickup import WeaponPickup
        wp = WeaponPickup("pistol")
        wp.position = (50.0, 100.0)
        wp.on_spawn()
        wp.tick(0.1)
        assert wp.position[0] == pytest.approx(50.0)

    def test_unknown_weapon_type_no_crash(self):
        from entities.weapon_pickup import WeaponPickup
        wp = WeaponPickup("orbital_death_ray")
        assert wp is not None
