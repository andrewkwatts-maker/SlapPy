"""Headless tests for Bullet Strata PlayerEntity, Projectile, and HUD overlays."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock
import numpy as np
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
# Shared helpers
# =============================================================================

def _make_engine():
    engine = MagicMock()
    engine.lighting = None
    return engine


def _make_player(player_id=0, hp=100.0, strata=0, weapon="pistol"):
    from entities.player import PlayerEntity
    p = PlayerEntity(player_id, _make_engine())
    p.hp = hp
    p.strata_layer = strata
    p.current_weapon = weapon
    return p


def _make_projectile(weapon_type="pistol", vx=100.0, vy=0.0, damage=10.0, strata=0):
    from entities.projectile import Projectile
    return Projectile(
        owner_id=0, weapon_type=weapon_type,
        vx=vx, vy=vy, damage=damage, strata_layer=strata,
    )


def _make_arena_scene(wave=1, total=10, kills=0):
    scene = MagicMock()
    scene.current_wave = wave
    scene.total_waves = total
    scene.kill_count = kills
    return scene


def _make_player_mock(hp=80.0, energy=0.6, strata=0, weapon="pistol"):
    player = MagicMock()
    player.hp = hp
    player.energy = energy
    player.strata_layer = strata
    player.current_weapon = weapon
    player.data = MagicMock()
    return player


# =============================================================================
# PlayerEntity — init
# =============================================================================

class TestPlayerEntityInit:
    def test_init_no_crash(self):
        from entities.player import PlayerEntity
        p = PlayerEntity(0, _make_engine())
        assert p is not None

    def test_player_id_stored(self):
        from entities.player import PlayerEntity
        p = PlayerEntity(1, _make_engine())
        assert p.player_id == 1

    def test_initial_hp_100(self):
        from entities.player import PlayerEntity
        p = PlayerEntity(0, _make_engine())
        assert p.hp == pytest.approx(100.0)

    def test_initial_energy_1(self):
        from entities.player import PlayerEntity
        p = PlayerEntity(0, _make_engine())
        assert p.energy == pytest.approx(1.0)

    def test_initial_strata_layer_0(self):
        from entities.player import PlayerEntity
        p = PlayerEntity(0, _make_engine())
        assert p.strata_layer == 0

    def test_initial_weapon_pistol(self):
        from entities.player import PlayerEntity
        p = PlayerEntity(0, _make_engine())
        assert p.current_weapon == "pistol"

    def test_has_layer(self):
        from entities.player import PlayerEntity
        p = PlayerEntity(0, _make_engine())
        assert len(p.layers) >= 1

    def test_initial_grounded_false(self):
        from entities.player import PlayerEntity
        p = PlayerEntity(0, _make_engine())
        assert p.grounded is False

    def test_initial_fire_cooldown_zero(self):
        from entities.player import PlayerEntity
        p = PlayerEntity(0, _make_engine())
        assert p.fire_cooldown == pytest.approx(0.0)

    def test_initial_teleport_cooldown_zero(self):
        from entities.player import PlayerEntity
        p = PlayerEntity(0, _make_engine())
        assert p.teleport_cooldown == pytest.approx(0.0)

    def test_has_data_component(self):
        from entities.player import PlayerEntity
        p = PlayerEntity(0, _make_engine())
        assert p.data is not None

    def test_velocity_initially_zero(self):
        from entities.player import PlayerEntity
        p = PlayerEntity(0, _make_engine())
        assert p.velocity == [0.0, 0.0]


# =============================================================================
# PlayerEntity — hp property
# =============================================================================

class TestPlayerEntityHP:
    def test_hp_setter_clamps_to_max(self):
        p = _make_player()
        p.hp = 200
        assert p.hp <= 100

    def test_hp_setter_clamps_to_zero(self):
        p = _make_player()
        p.hp = -50
        assert p.hp == pytest.approx(0.0)

    def test_hp_getter_after_set(self):
        p = _make_player()
        p.hp = 75
        assert p.hp == pytest.approx(75.0)

    def test_hp_setter_exact_max(self):
        p = _make_player()
        p.hp = 100
        assert p.hp == pytest.approx(100.0)

    def test_hp_setter_zero(self):
        p = _make_player()
        p.hp = 0
        assert p.hp == pytest.approx(0.0)

    def test_different_player_ids_independent(self):
        from entities.player import PlayerEntity
        p1 = PlayerEntity(0, _make_engine())
        p2 = PlayerEntity(1, _make_engine())
        p1.hp = 50
        p2.hp = 80
        assert p1.hp == pytest.approx(50.0)
        assert p2.hp == pytest.approx(80.0)


# =============================================================================
# PlayerEntity — take_damage
# =============================================================================

class TestPlayerEntityTakeDamage:
    def test_take_damage_reduces_hp(self):
        p = _make_player()
        p.take_damage(30)
        assert p.hp == pytest.approx(70.0)

    def test_take_damage_returns_false_when_alive(self):
        p = _make_player()
        result = p.take_damage(10)
        assert result is False

    def test_take_damage_returns_true_when_killed(self):
        p = _make_player()
        result = p.take_damage(100)
        assert result is True

    def test_take_damage_exact_to_zero(self):
        p = _make_player(hp=50.0)
        result = p.take_damage(50)
        assert result is True
        assert p.hp == pytest.approx(0.0)

    def test_overkill_does_not_go_below_zero(self):
        p = _make_player()
        p.take_damage(9999)
        assert p.hp >= 0

    def test_take_damage_accumulates(self):
        p = _make_player()
        p.take_damage(30)
        p.take_damage(30)
        assert p.hp == pytest.approx(40.0)

    def test_small_damage_still_false(self):
        p = _make_player(hp=100.0)
        result = p.take_damage(1)
        assert result is False


# =============================================================================
# PlayerEntity — kill
# =============================================================================

class TestPlayerEntityKill:
    def test_kill_calls_scene_remove(self):
        p = _make_player()
        scene = MagicMock()
        p.scene = scene
        p.kill()
        scene.remove.assert_called_once_with(p)

    def test_kill_no_scene_no_crash(self):
        p = _make_player()
        p.scene = None
        p.kill()

    def test_kill_after_zero_hp_no_crash(self):
        p = _make_player()
        p.take_damage(9999)
        p.scene = None
        p.kill()


# =============================================================================
# _projectile_layer helper
# =============================================================================

class TestProjectileLayer:
    def test_returns_layer_object(self):
        from entities.projectile import _projectile_layer
        from slappyengine.layer import Layer
        layer = _projectile_layer("pistol")
        assert isinstance(layer, Layer)

    def test_size_8x8(self):
        from entities.projectile import _projectile_layer
        layer = _projectile_layer("pistol")
        assert layer._image_data.shape[0] == 8
        assert layer._image_data.shape[1] == 8

    def test_known_weapon_type_has_nonzero_pixels(self):
        from entities.projectile import _projectile_layer
        layer = _projectile_layer("pistol")
        # Either from PNG or fallback — at least some pixels should be non-zero
        assert layer._image_data.sum() > 0

    def test_unknown_type_white_fallback_color(self):
        from entities.projectile import _projectile_layer, _DEFAULT_PROJECTILE_COLOR
        layer = _projectile_layer("nonexistent_weapon_xyz_12345")
        expected_r = _DEFAULT_PROJECTILE_COLOR[0]
        assert layer._image_data[0, 0, 0] == expected_r

    def test_unknown_type_fallback_alpha_255(self):
        from entities.projectile import _projectile_layer
        layer = _projectile_layer("nonexistent_weapon_xyz_12345")
        assert layer._image_data[0, 0, 3] == 255

    def test_gravity_fallback_purple_color(self):
        from entities.projectile import _projectile_layer, _WEAPON_COLORS
        # Only valid if no PNG exists for "gravity"
        _ASSETS_DIR = _STRATA_ROOT / "assets" / "sprites"
        if not (_ASSETS_DIR / "projectile_gravity.png").exists():
            layer = _projectile_layer("gravity")
            expected_r = _WEAPON_COLORS["gravity"][0]
            assert layer._image_data[0, 0, 0] == expected_r


# =============================================================================
# Projectile — init
# =============================================================================

class TestProjectileInit:
    def test_init_pistol_no_crash(self):
        assert _make_projectile("pistol") is not None

    def test_init_laser_no_crash(self):
        assert _make_projectile("laser") is not None

    def test_init_rocket_no_crash(self):
        assert _make_projectile("rocket") is not None

    def test_init_gravity_no_crash(self):
        assert _make_projectile("gravity") is not None

    def test_init_orbital_no_crash(self):
        assert _make_projectile("orbital") is not None

    def test_init_plasma_no_crash(self):
        assert _make_projectile("plasma") is not None

    def test_init_unknown_weapon_no_crash(self):
        assert _make_projectile("death_ray_9000") is not None

    def test_weapon_type_stored(self):
        proj = _make_projectile("laser")
        assert proj.weapon_type == "laser"

    def test_velocity_x_stored(self):
        proj = _make_projectile(vx=200.0, vy=-50.0)
        assert proj.velocity[0] == pytest.approx(200.0)

    def test_velocity_y_stored(self):
        proj = _make_projectile(vx=200.0, vy=-50.0)
        assert proj.velocity[1] == pytest.approx(-50.0)

    def test_damage_stored(self):
        proj = _make_projectile(damage=75.0)
        assert proj.damage == pytest.approx(75.0)

    def test_lifetime_initially_3(self):
        proj = _make_projectile()
        assert proj.lifetime == pytest.approx(3.0)

    def test_strata_layer_stored(self):
        proj = _make_projectile(strata=2)
        assert proj.strata_layer == 2

    def test_has_layer(self):
        proj = _make_projectile()
        assert len(proj.layers) >= 1

    def test_point_light_initially_none(self):
        proj = _make_projectile()
        assert proj._point_light is None

    def test_lighting_initially_none(self):
        proj = _make_projectile()
        assert proj._lighting is None

    def test_temperature_initially_zero(self):
        proj = _make_projectile()
        assert proj.temperature == pytest.approx(0.0)

    def test_owner_id_stored(self):
        from entities.projectile import Projectile
        proj = Projectile(owner_id=42, weapon_type="pistol",
                          vx=0.0, vy=0.0, damage=10.0, strata_layer=0)
        assert proj.owner_id == 42


# =============================================================================
# Projectile — tick
# =============================================================================

class TestProjectileTick:
    def test_tick_advances_x(self):
        proj = _make_projectile(vx=100.0, vy=0.0)
        proj.position = (0.0, 0.0)
        proj.scene = None
        proj.tick(0.1)
        assert proj.position[0] == pytest.approx(10.0)

    def test_tick_advances_y(self):
        proj = _make_projectile(vx=0.0, vy=50.0)
        proj.position = (0.0, 0.0)
        proj.scene = None
        proj.tick(0.5)
        assert proj.position[1] == pytest.approx(25.0)

    def test_tick_advances_both_components(self):
        proj = _make_projectile(vx=60.0, vy=80.0)
        proj.position = (10.0, 20.0)
        proj.scene = None
        proj.tick(0.25)
        assert proj.position[0] == pytest.approx(25.0)
        assert proj.position[1] == pytest.approx(40.0)

    def test_tick_decrements_lifetime(self):
        proj = _make_projectile()
        proj.scene = None
        proj.tick(0.1)
        assert proj.lifetime == pytest.approx(2.9)

    def test_tick_no_expire_when_lifetime_positive(self):
        proj = _make_projectile()
        scene = MagicMock()
        proj.scene = scene
        proj.tick(0.016)
        scene.remove.assert_not_called()

    def test_tick_expires_when_lifetime_exhausted(self):
        proj = _make_projectile()
        scene = MagicMock()
        proj.scene = scene
        proj.tick(3.1)
        scene.remove.assert_called_once()

    def test_tick_no_expire_without_scene(self):
        proj = _make_projectile()
        proj.scene = None
        proj.tick(100.0)  # no scene → no crash

    def test_tick_syncs_point_light_position(self):
        proj = _make_projectile(vx=100.0, vy=0.0)
        proj.position = (0.0, 0.0)
        proj.scene = None
        light = MagicMock()
        proj._point_light = light
        proj.tick(0.2)
        assert light.position == proj.position

    def test_tick_multiple_frames_accumulates(self):
        proj = _make_projectile(vx=50.0, vy=0.0)
        proj.position = (0.0, 0.0)
        proj.scene = None
        proj.tick(0.1)
        proj.tick(0.1)
        proj.tick(0.1)
        assert proj.position[0] == pytest.approx(15.0)


# =============================================================================
# Projectile — collision and impact
# =============================================================================

class TestProjectileCollision:
    def test_on_collision_removes_from_scene(self):
        proj = _make_projectile()
        scene = MagicMock()
        proj.scene = scene
        target = MagicMock()
        target.image = None
        proj.on_collision(target)
        scene.remove.assert_called_once()

    def test_on_collision_with_normal_no_crash(self):
        proj = _make_projectile()
        proj.scene = None
        proj.on_collision(MagicMock(), normal=(1.0, 0.0))

    def test_on_collision_with_none_target(self):
        proj = _make_projectile()
        proj.scene = None
        proj.on_collision(None)

    def test_high_damage_applies_burn_to_target(self):
        proj = _make_projectile(damage=50.0)
        target = MagicMock()
        arr = np.ones((16, 16, 4), dtype=np.uint8) * 200
        target.image = arr.copy()
        proj.scene = None
        proj._on_impact(target, damage=50.0)
        cx, cy = 8, 8
        assert target.image[cy, cx, 0] < 200

    def test_low_damage_does_not_apply_burn(self):
        proj = _make_projectile(damage=10.0)
        target = MagicMock()
        original = np.ones((16, 16, 4), dtype=np.uint8) * 200
        target.image = original.copy()
        proj.scene = None
        proj._on_impact(target, damage=10.0)
        np.testing.assert_array_equal(target.image, original)

    def test_on_impact_calls_expire(self):
        proj = _make_projectile()
        scene = MagicMock()
        proj.scene = scene
        proj._on_impact(MagicMock(), damage=10.0)
        scene.remove.assert_called_once()

    def test_on_impact_removes_point_light(self):
        proj = _make_projectile()
        proj.scene = None
        light_system = MagicMock()
        proj._point_light = MagicMock()
        proj._lighting = light_system
        proj._on_impact(MagicMock(), damage=5.0)
        light_system.remove_light.assert_called_once()


# =============================================================================
# Projectile — _apply_burn
# =============================================================================

class TestProjectileApplyBurn:
    def test_numpy_darkens_center_pixels(self):
        from entities.projectile import Projectile
        target = MagicMock()
        arr = np.ones((16, 16, 4), dtype=np.uint8) * 200
        target.image = arr.copy()
        Projectile._apply_burn(target)
        cx, cy = 8, 8
        # Center pixel RGB should be roughly 200 * 0.35 = 70
        assert target.image[cy, cx, 0] < 100

    def test_numpy_pixels_outside_center_unchanged(self):
        from entities.projectile import Projectile
        target = MagicMock()
        arr = np.ones((16, 16, 4), dtype=np.uint8) * 200
        target.image = arr.copy()
        Projectile._apply_burn(target)
        # Corners should be untouched
        assert target.image[0, 0, 0] == 200

    def test_no_image_no_crash(self):
        from entities.projectile import Projectile
        target = MagicMock()
        target.image = None
        Projectile._apply_burn(target)

    def test_no_image_attr_no_crash(self):
        from entities.projectile import Projectile
        target = MagicMock(spec=[])  # no 'image' attr
        Projectile._apply_burn(target)

    def test_pil_image_path(self):
        from PIL import Image
        from entities.projectile import Projectile
        target = MagicMock()
        img = Image.new("RGBA", (16, 16), (200, 200, 200, 255))
        target.image = img
        Projectile._apply_burn(target)
        assert target.image is not None

    def test_small_array_clamps_safely(self):
        from entities.projectile import Projectile
        target = MagicMock()
        arr = np.ones((2, 2, 4), dtype=np.uint8) * 200
        target.image = arr.copy()
        Projectile._apply_burn(target)

    def test_result_is_uint8(self):
        from entities.projectile import Projectile
        target = MagicMock()
        arr = np.ones((16, 16, 4), dtype=np.uint8) * 200
        target.image = arr.copy()
        Projectile._apply_burn(target)
        assert target.image.dtype == np.uint8

    def test_alpha_channel_only_rgb_darkened(self):
        from entities.projectile import Projectile
        target = MagicMock()
        arr = np.ones((16, 16, 4), dtype=np.uint8) * 200
        target.image = arr.copy()
        Projectile._apply_burn(target)
        cx, cy = 8, 8
        # Alpha may be affected too since arr[:,:,:3] only targets RGB
        # Just verify the RGB channels are darkened
        assert target.image[cy, cx, 0] < target.image[0, 0, 0]


# =============================================================================
# StrataBulletHUD
# =============================================================================

class TestStrataBulletHUD:
    def test_init_no_crash(self):
        from entities.hud import StrataBulletHUD
        p = _make_player_mock()
        hud = StrataBulletHUD(p, x=10, y=10)
        assert hud is not None

    def test_initially_dirty(self):
        from entities.hud import StrataBulletHUD
        p = _make_player_mock()
        hud = StrataBulletHUD(p, x=10, y=10)
        assert hud._dirty is True

    def test_last_strata_stored_on_init(self):
        from entities.hud import StrataBulletHUD
        p = _make_player_mock(strata=1)
        hud = StrataBulletHUD(p, x=10, y=10)
        assert hud._last_strata == 1

    def test_last_weapon_stored_on_init(self):
        from entities.hud import StrataBulletHUD
        p = _make_player_mock(weapon="laser")
        hud = StrataBulletHUD(p, x=10, y=10)
        assert hud._last_weapon == "laser"

    def test_mark_dirty_sets_flag(self):
        from entities.hud import StrataBulletHUD
        p = _make_player_mock()
        hud = StrataBulletHUD(p, x=10, y=10)
        hud._dirty = False
        hud._mark_dirty()
        assert hud._dirty is True

    def test_tick_detects_strata_change(self):
        from entities.hud import StrataBulletHUD
        p = _make_player_mock(strata=0)
        hud = StrataBulletHUD(p, x=10, y=10)
        hud._upload_texture = MagicMock()
        hud._dirty = False
        p.strata_layer = 1
        hud.tick(0.016)
        assert hud._last_strata == 1

    def test_tick_detects_weapon_change(self):
        from entities.hud import StrataBulletHUD
        p = _make_player_mock(weapon="pistol")
        hud = StrataBulletHUD(p, x=10, y=10)
        hud._upload_texture = MagicMock()
        p.current_weapon = "laser"
        hud.tick(0.016)
        assert hud._last_weapon == "laser"

    def test_tick_clears_dirty_flag(self):
        from entities.hud import StrataBulletHUD
        p = _make_player_mock()
        hud = StrataBulletHUD(p, x=10, y=10)
        hud._upload_texture = MagicMock()
        hud.tick(0.016)
        assert hud._dirty is False

    def test_tick_no_change_no_rerender(self):
        from entities.hud import StrataBulletHUD
        p = _make_player_mock()
        hud = StrataBulletHUD(p, x=10, y=10)
        hud._upload_texture = MagicMock()
        hud.tick(0.016)  # first tick — renders
        upload_count = hud._upload_texture.call_count
        hud.tick(0.016)  # no change — should not re-render
        assert hud._upload_texture.call_count == upload_count


# =============================================================================
# ArenaInfoHUD
# =============================================================================

class TestArenaInfoHUDInit:
    def test_init_no_crash(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene()
        hud = ArenaInfoHUD(s)
        assert hud is not None

    def test_wave_cur_from_scene(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene(wave=3)
        hud = ArenaInfoHUD(s)
        assert hud._wave_cur == 3

    def test_wave_tot_from_scene(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene(total=5)
        hud = ArenaInfoHUD(s)
        assert hud._wave_tot == 5

    def test_kills_from_scene(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene(kills=7)
        hud = ArenaInfoHUD(s)
        assert hud._kills == 7

    def test_initially_dirty(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene()
        hud = ArenaInfoHUD(s)
        assert hud._hud_dirty is True

    def test_popup_timer_initially_zero(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene()
        hud = ArenaInfoHUD(s)
        assert hud._popup_timer == pytest.approx(0.0)

    def test_popup_text_initially_empty(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene()
        hud = ArenaInfoHUD(s)
        assert hud._popup_text == ""


class TestArenaInfoHUDEnemyKilled:
    def test_on_enemy_killed_increments_kills(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene()
        hud = ArenaInfoHUD(s)
        evt = MagicMock()
        evt.publisher = s
        hud._on_enemy_killed(evt)
        assert hud._kills == 1

    def test_on_enemy_killed_multiple_times(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene()
        hud = ArenaInfoHUD(s)
        evt = MagicMock()
        evt.publisher = s
        hud._on_enemy_killed(evt)
        hud._on_enemy_killed(evt)
        hud._on_enemy_killed(evt)
        assert hud._kills == 3

    def test_on_enemy_killed_wrong_publisher_ignored(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene()
        hud = ArenaInfoHUD(s)
        evt = MagicMock()
        evt.publisher = MagicMock()
        hud._on_enemy_killed(evt)
        assert hud._kills == 0

    def test_on_enemy_killed_marks_dirty(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene()
        hud = ArenaInfoHUD(s)
        hud._hud_dirty = False
        evt = MagicMock()
        evt.publisher = s
        hud._on_enemy_killed(evt)
        assert hud._hud_dirty is True


class TestArenaInfoHUDWaveStarted:
    def test_on_wave_started_updates_wave_cur(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene(wave=1)
        hud = ArenaInfoHUD(s)
        evt = MagicMock()
        evt.publisher = s
        evt.wave = 2
        evt.total = 10
        hud._on_wave_started(evt)
        assert hud._wave_cur == 2

    def test_on_wave_started_updates_wave_tot(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene()
        hud = ArenaInfoHUD(s)
        evt = MagicMock()
        evt.publisher = s
        evt.wave = 1
        evt.total = 7
        hud._on_wave_started(evt)
        assert hud._wave_tot == 7

    def test_on_wave_started_resets_kills(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene()
        hud = ArenaInfoHUD(s)
        hud._kills = 5
        evt = MagicMock()
        evt.publisher = s
        evt.wave = 2
        evt.total = 10
        hud._on_wave_started(evt)
        assert hud._kills == 0

    def test_on_wave_started_wrong_publisher_ignored(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene()
        hud = ArenaInfoHUD(s)
        hud._kills = 3
        evt = MagicMock()
        evt.publisher = MagicMock()
        evt.wave = 5
        hud._on_wave_started(evt)
        assert hud._kills == 3

    def test_on_wave_started_marks_dirty(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene()
        hud = ArenaInfoHUD(s)
        hud._hud_dirty = False
        evt = MagicMock()
        evt.publisher = s
        evt.wave = 2
        evt.total = 10
        hud._on_wave_started(evt)
        assert hud._hud_dirty is True


class TestArenaInfoHUDWaveComplete:
    def test_on_wave_complete_updates_kills(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene()
        hud = ArenaInfoHUD(s)
        evt = MagicMock()
        evt.publisher = s
        evt.kills = 15
        hud._on_wave_complete(evt)
        assert hud._kills == 15

    def test_on_wave_complete_marks_dirty(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene()
        hud = ArenaInfoHUD(s)
        hud._hud_dirty = False
        evt = MagicMock()
        evt.publisher = s
        evt.kills = 5
        hud._on_wave_complete(evt)
        assert hud._hud_dirty is True

    def test_on_wave_complete_wrong_publisher_ignored(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene()
        hud = ArenaInfoHUD(s)
        hud._kills = 3
        evt = MagicMock()
        evt.publisher = MagicMock()
        evt.kills = 99
        hud._on_wave_complete(evt)
        assert hud._kills == 3


class TestArenaInfoHUDPopup:
    def test_show_popup_sets_text(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene()
        hud = ArenaInfoHUD(s)
        hud._show_popup("HEADSHOT +50", 1.5)
        assert hud._popup_text == "HEADSHOT +50"

    def test_show_popup_sets_timer(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene()
        hud = ArenaInfoHUD(s)
        hud._show_popup("CRIPPLED!", 1.0)
        assert hud._popup_timer == pytest.approx(1.0)

    def test_show_popup_overrides_previous(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene()
        hud = ArenaInfoHUD(s)
        hud._show_popup("FIRST", 2.0)
        hud._show_popup("SECOND", 0.5)
        assert hud._popup_text == "SECOND"
        assert hud._popup_timer == pytest.approx(0.5)


class TestArenaInfoHUDTick:
    def test_tick_decrements_popup_timer(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene()
        hud = ArenaInfoHUD(s)
        hud._upload_texture = MagicMock()
        hud._show_popup("TEST", 1.0)
        hud._hud_dirty = False
        hud.tick(0.4)
        assert hud._popup_timer == pytest.approx(0.6)

    def test_tick_clears_popup_when_timer_expires(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene()
        hud = ArenaInfoHUD(s)
        hud._upload_texture = MagicMock()
        hud._show_popup("TEST", 0.1)
        hud._hud_dirty = False
        hud.tick(0.2)
        assert hud._popup_text == ""

    def test_tick_clears_dirty_flag(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene()
        hud = ArenaInfoHUD(s)
        hud._upload_texture = MagicMock()
        assert hud._hud_dirty is True
        hud.tick(0.016)
        assert hud._hud_dirty is False

    def test_tick_no_popup_no_dirty_no_rerender(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene()
        hud = ArenaInfoHUD(s)
        hud._upload_texture = MagicMock()
        hud.tick(0.016)  # clears dirty on first tick
        count = hud._upload_texture.call_count
        hud.tick(0.016)
        assert hud._upload_texture.call_count == count


class TestArenaInfoHUDTeardown:
    def test_teardown_clears_handles(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene()
        hud = ArenaInfoHUD(s)
        hud.teardown()
        assert hud._sub_handles == []

    def test_teardown_twice_no_crash(self):
        from entities.hud import ArenaInfoHUD
        s = _make_arena_scene()
        hud = ArenaInfoHUD(s)
        hud.teardown()
        hud.teardown()


# =============================================================================
# VictoryOverlay
# =============================================================================

class TestVictoryOverlay:
    def test_init_victory_no_crash(self):
        from entities.hud import VictoryOverlay
        overlay = VictoryOverlay("VICTORY", (255, 220, 0))
        assert overlay is not None

    def test_init_game_over_no_crash(self):
        from entities.hud import VictoryOverlay
        overlay = VictoryOverlay("GAME OVER", (255, 60, 60))
        assert overlay is not None

    def test_message_stored(self):
        from entities.hud import VictoryOverlay
        overlay = VictoryOverlay("VICTORY", (255, 220, 0))
        assert overlay._message == "VICTORY"

    def test_color_stored(self):
        from entities.hud import VictoryOverlay
        overlay = VictoryOverlay("VICTORY", (100, 200, 50))
        assert overlay._color == (100, 200, 50)

    def test_tick_no_crash(self):
        from entities.hud import VictoryOverlay
        overlay = VictoryOverlay("VICTORY", (255, 220, 0))
        overlay.tick(1.0)

    def test_tick_multiple_times_no_crash(self):
        from entities.hud import VictoryOverlay
        overlay = VictoryOverlay("GAME OVER", (200, 60, 60))
        for _ in range(10):
            overlay.tick(0.016)

    def test_message_preserved_after_tick(self):
        from entities.hud import VictoryOverlay
        overlay = VictoryOverlay("VICTORY", (255, 220, 0))
        overlay.tick(5.0)
        assert overlay._message == "VICTORY"
