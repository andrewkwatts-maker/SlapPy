"""Headless tests for Bullet Strata: GameModeSystem, WaveSpawner, enemy entities,
Projectile, WeaponPickup, EnemyAiScript.
"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock
import pytest

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("pharos_engine.compute.asset_compute", MagicMock())

_STRATA_ROOT = (
    Path(__file__).parent.parent.parent.parent.parent / "DaedalusSVN" / "Bullet Strata"
)
_STRATA_STR = str(_STRATA_ROOT)

_CONFLICT_PKGS = ("systems", "entities", "scenes")


@pytest.fixture(autouse=True)
def _strata_isolation():
    """Isolate Bullet Strata imports from Ochema Circuit package namespace."""
    # Save and remove any cached conflicting modules before the test
    stale = [k for k in sys.modules
             if k in _CONFLICT_PKGS or any(k.startswith(p + ".") for p in _CONFLICT_PKGS)]
    saved = {k: sys.modules.pop(k) for k in stale}

    # Put strata at the front of sys.path
    if _STRATA_STR in sys.path:
        sys.path.remove(_STRATA_STR)
    sys.path.insert(0, _STRATA_STR)

    yield

    # Clean up strata modules
    strata_keys = [k for k in sys.modules
                   if k in _CONFLICT_PKGS or any(k.startswith(p + ".") for p in _CONFLICT_PKGS)]
    for k in strata_keys:
        del sys.modules[k]

    # Remove strata path
    if _STRATA_STR in sys.path:
        sys.path.remove(_STRATA_STR)

    # Restore previously saved modules
    sys.modules.update(saved)


# =============================================================================
# GameMode / ScoreBoard / GameModeSystem
# =============================================================================

class TestScoreBoard:
    def _sb(self, ids=None):
        from systems.gamemodes import ScoreBoard
        return ScoreBoard(ids or [1, 2, 3])

    def test_instantiates(self):
        assert self._sb() is not None

    def test_kills_initialized_to_zero(self):
        sb = self._sb([1, 2])
        assert sb.kills[1] == 0
        assert sb.kills[2] == 0

    def test_deaths_initialized_to_zero(self):
        sb = self._sb([1, 2])
        assert sb.deaths[1] == 0
        assert sb.deaths[2] == 0

    def test_record_kill_increments_kills(self):
        sb = self._sb([1, 2])
        sb.record_kill(1, 2)
        assert sb.kills[1] == 1

    def test_record_kill_increments_victim_deaths(self):
        sb = self._sb([1, 2])
        sb.record_kill(1, 2)
        assert sb.deaths[2] == 1

    def test_self_kill_no_kill_credit(self):
        sb = self._sb([1, 2])
        sb.record_kill(1, 1)
        assert sb.kills.get(1, 0) == 0  # no credit for self-kill

    def test_self_kill_increments_deaths(self):
        sb = self._sb([1, 2])
        sb.record_kill(1, 1)
        assert sb.deaths[1] == 1

    def test_leader_returns_highest_kills(self):
        sb = self._sb([1, 2, 3])
        sb.record_kill(2, 1)
        sb.record_kill(2, 3)
        sb.record_kill(1, 2)
        assert sb.leader() == 2

    def test_multiple_kills_accumulate(self):
        sb = self._sb([1, 2])
        sb.record_kill(1, 2)
        sb.record_kill(1, 2)
        sb.record_kill(1, 2)
        assert sb.kills[1] == 3

    def test_kill_unknown_id_no_crash(self):
        sb = self._sb([1, 2])
        sb.record_kill(1, 99)  # 99 not in initial list — death tracked dynamically


class TestGameModeSystem:
    def _gms(self, mode=None, score_limit=5):
        from systems.gamemodes import GameModeSystem, GameMode
        return GameModeSystem(mode=mode or GameMode.FFA, score_limit=score_limit)

    def test_instantiates(self):
        assert self._gms() is not None

    def test_board_none_before_setup(self):
        gms = self._gms()
        assert gms.board is None

    def test_setup_creates_board(self):
        gms = self._gms()
        gms.setup([1, 2, 3])
        assert gms.board is not None

    def test_on_player_killed_returns_false_before_limit(self):
        gms = self._gms(score_limit=5)
        gms.setup([1, 2])
        over = gms.on_player_killed(1, 2)
        assert over is False

    def test_on_player_killed_returns_true_at_limit(self):
        gms = self._gms(score_limit=2)
        gms.setup([1, 2])
        gms.on_player_killed(1, 2)
        over = gms.on_player_killed(1, 2)
        assert over is True

    def test_on_player_killed_no_board_returns_false(self):
        gms = self._gms()
        over = gms.on_player_killed(1, 2)
        assert over is False

    def test_all_gamemodes_instantiate(self):
        from systems.gamemodes import GameModeSystem, GameMode
        for mode in GameMode:
            gms = GameModeSystem(mode=mode)
            assert gms.mode == mode

    def test_score_limit_stored(self):
        gms = self._gms(score_limit=15)
        assert gms.score_limit == 15


class TestGameModeEnum:
    def test_ffa_exists(self):
        from systems.gamemodes import GameMode
        assert GameMode.FFA is not None

    def test_tdm_exists(self):
        from systems.gamemodes import GameMode
        assert GameMode.TDM is not None

    def test_ctf_exists(self):
        from systems.gamemodes import GameMode
        assert GameMode.CTF is not None


# =============================================================================
# WaveSpawner
# =============================================================================

class TestWaveSpawnerInit:
    def _ws(self, **kw):
        from systems.wave_spawner import WaveSpawner
        return WaveSpawner(screen_w=800, screen_h=600, **kw)

    def test_instantiates(self):
        assert self._ws() is not None

    def test_wave_num_starts_zero(self):
        ws = self._ws()
        assert ws.wave_num == 0

    def test_not_done_initially(self):
        ws = self._ws()
        assert ws.done is False

    def test_done_after_all_waves(self):
        ws = self._ws(total_waves=3)
        ws.wave_num = 3
        assert ws.done is True

    def test_screen_dimensions_stored(self):
        ws = self._ws()
        assert ws.screen_w == 800
        assert ws.screen_h == 600


class TestWaveSpawnerNextWave:
    def _ws(self, total=10):
        from systems.wave_spawner import WaveSpawner
        return WaveSpawner(screen_w=640, screen_h=480, total_waves=total)

    def test_next_wave_returns_list(self):
        ws = self._ws()
        enemies = ws.next_wave()
        assert isinstance(enemies, list)

    def test_next_wave_increments_wave_num(self):
        ws = self._ws()
        ws.next_wave()
        assert ws.wave_num == 1

    def test_first_wave_has_drones(self):
        ws = self._ws()
        enemies = ws.next_wave()
        from entities.enemy import DroneEnemy
        assert any(isinstance(e, DroneEnemy) for e in enemies)

    def test_first_wave_no_brutes(self):
        ws = self._ws()
        enemies = ws.next_wave()
        from entities.enemy import BruteEnemy
        assert not any(isinstance(e, BruteEnemy) for e in enemies)

    def test_later_wave_has_shades(self):
        ws = self._ws()
        ws.wave_num = 2  # skip to wave 3
        enemies = ws.next_wave()
        from entities.enemy import ShadeEnemy
        assert any(isinstance(e, ShadeEnemy) for e in enemies)

    def test_done_returns_empty_list(self):
        ws = self._ws(total=3)
        ws.wave_num = 3
        enemies = ws.next_wave()
        assert enemies == []

    def test_enemies_have_positions(self):
        ws = self._ws()
        enemies = ws.next_wave()
        for e in enemies:
            assert hasattr(e, "pos")

    def test_edge_spawn_pos_on_screen_edge(self):
        ws = self._ws()
        for _ in range(20):
            x, y = ws._edge_spawn_pos()
            on_left = x == 0.0
            on_right = x == float(ws.screen_w)
            on_top = y == 0.0
            on_bottom = y == float(ws.screen_h)
            assert on_left or on_right or on_top or on_bottom

    def test_wave_count_scales_with_wave_num(self):
        ws = self._ws()
        w1 = ws.next_wave()
        w5 = ws.next_wave()
        w5 = ws.next_wave()
        w5 = ws.next_wave()
        w5 = ws.next_wave()
        # Wave 5 should have more enemies than wave 1
        assert len(w5) >= len(w1)


# =============================================================================
# DroneEnemy
# =============================================================================

class TestDroneEnemy:
    def _d(self):
        from entities.enemy import DroneEnemy
        return DroneEnemy()

    def test_instantiates(self):
        assert self._d() is not None

    def test_hp_positive(self):
        d = self._d()
        assert d.hp > 0

    def test_alive_initially(self):
        assert self._d().alive is True

    def test_pending_shots_empty(self):
        assert self._d().pending_shots == []

    def test_take_damage_reduces_hp(self):
        d = self._d()
        initial = d.hp
        d.take_damage(10)
        assert d.hp < initial

    def test_take_damage_returns_false_when_alive(self):
        d = self._d()
        assert d.take_damage(1) is False

    def test_take_damage_returns_true_when_killed(self):
        d = self._d()
        killed = d.take_damage(d.hp)
        assert killed is True

    def test_alive_false_after_fatal_damage(self):
        d = self._d()
        d.take_damage(d.hp)
        assert d.alive is False

    def test_hp_floors_at_zero(self):
        d = self._d()
        d.take_damage(d.hp * 10)
        assert d.hp == 0

    def test_update_no_players_no_crash(self):
        d = self._d()
        d.pos = (320.0, 240.0)
        d.position = d.pos
        d.update(0.016, players=[])

    def test_update_moves_toward_player(self):
        d = self._d()
        d.pos = (0.0, 0.0)
        d.position = d.pos
        target = MagicMock()
        target.position = (100.0, 0.0)
        target.data = MagicMock()
        target.data.get = MagicMock(return_value="alive")
        d.update(0.016, players=[target])
        assert d.pos[0] > 0.0  # moved right toward target

    def test_update_dead_no_move(self):
        d = self._d()
        d.alive = False
        d.pos = (100.0, 100.0)
        d.position = d.pos
        target = MagicMock()
        target.position = (200.0, 200.0)
        d.update(0.016, players=[target])
        assert d.pos == (100.0, 100.0)  # didn't move

    def test_rect_returns_four_tuple(self):
        d = self._d()
        r = d.rect
        assert len(r) == 4

    def test_has_layers(self):
        d = self._d()
        assert len(d.layers) >= 1


# =============================================================================
# ShadeEnemy
# =============================================================================

class TestShadeEnemy:
    def _s(self):
        from entities.enemy import ShadeEnemy
        return ShadeEnemy()

    def test_instantiates(self):
        assert self._s() is not None

    def test_hp_positive(self):
        assert self._s().hp > 0

    def test_alive_initially(self):
        assert self._s().alive is True

    def test_fallen_initially_false(self):
        assert self._s()._fallen is False

    def test_take_damage_reduces_hp(self):
        s = self._s()
        initial = s.hp
        s.take_damage(15)
        assert s.hp < initial

    def test_take_damage_fatal(self):
        s = self._s()
        killed = s.take_damage(s.hp)
        assert killed is True
        assert s.alive is False

    def test_fallen_after_kill(self):
        s = self._s()
        s.take_damage(s.hp)
        assert s._fallen is True

    def test_update_fallen_ticks_timer(self):
        s = self._s()
        s._fallen = True
        s._persist_timer = 1.0
        s.position = (100.0, 100.0)
        s.pos = (100.0, 100.0)
        s.update(0.5, players=[])
        assert s._persist_timer < 1.0

    def test_update_moves_toward_player(self):
        s = self._s()
        s.pos = (0.0, 0.0)
        s.position = s.pos
        target = MagicMock()
        target.position = (500.0, 0.0)  # far away, beyond orbit radius
        target.data = MagicMock()
        target.data.get = MagicMock(return_value="alive")
        s.update(0.016, players=[target])
        assert s.pos[0] > 0.0


# =============================================================================
# BruteEnemy
# =============================================================================

class TestBruteEnemy:
    def _b(self):
        from entities.enemy import BruteEnemy
        return BruteEnemy()

    def test_instantiates(self):
        assert self._b() is not None

    def test_hp_positive(self):
        assert self._b().hp > 0

    def test_alive_initially(self):
        assert self._b().alive is True

    def test_not_wrecked_initially(self):
        assert self._b()._wrecked is False

    def test_take_damage_reduces_hp(self):
        b = self._b()
        initial = b.hp
        b.take_damage(50)
        assert b.hp < initial

    def test_take_damage_fatal(self):
        b = self._b()
        killed = b.take_damage(b.hp)
        assert killed is True

    def test_wrecked_after_kill(self):
        b = self._b()
        b.take_damage(b.hp)
        assert b._wrecked is True

    def test_pending_shots_always_empty(self):
        b = self._b()
        b.pos = (100.0, 100.0)
        b.position = b.pos
        target = MagicMock()
        target.position = (200.0, 100.0)
        target.data = MagicMock()
        target.data.get = MagicMock(return_value="alive")
        b.update(0.016, players=[target])
        assert b.pending_shots == []  # brute is melee-only


# =============================================================================
# Enemy helper functions
# =============================================================================

class TestEnemyHelpers:
    def test_dist_to(self):
        from entities.enemy import _dist_to
        d = _dist_to((0.0, 0.0), (3.0, 4.0))
        assert abs(d - 5.0) < 1e-6

    def test_dist_to_same_pos(self):
        from entities.enemy import _dist_to
        assert _dist_to((1.0, 1.0), (1.0, 1.0)) == 0.0

    def test_dir_to_unit(self):
        from entities.enemy import _dir_to
        import math
        dx, dy = _dir_to((0.0, 0.0), (3.0, 4.0))
        mag = math.hypot(dx, dy)
        assert abs(mag - 1.0) < 1e-6

    def test_dir_to_coincident_returns_zero(self):
        from entities.enemy import _dir_to
        assert _dir_to((1.0, 1.0), (1.0, 1.0)) == (0.0, 0.0)


# =============================================================================
# EnemyAiScript
# =============================================================================

class TestEnemyAiScript:
    def test_instantiates(self):
        from systems.enemy_ai import EnemyAiScript
        assert EnemyAiScript() is not None

    def test_update_delegates_to_enemy(self):
        from systems.enemy_ai import EnemyAiScript
        script = EnemyAiScript()
        enemy = MagicMock()
        script.update(enemy, 0.016, players=[])
        enemy.update.assert_called_once_with(0.016, [])


# =============================================================================
# Projectile
# =============================================================================

class TestProjectile:
    def _p(self, weapon_type="bullet", vx=300.0, vy=0.0, damage=10.0, strata_layer=0):
        from entities.projectile import Projectile
        return Projectile(owner_id=1, weapon_type=weapon_type,
                          vx=vx, vy=vy, damage=damage, strata_layer=strata_layer)

    def test_instantiates(self):
        assert self._p() is not None

    def test_weapon_type_stored(self):
        p = self._p(weapon_type="laser")
        assert p.weapon_type == "laser"

    def test_velocity_stored(self):
        p = self._p(vx=300.0, vy=100.0)
        assert abs(p.velocity[0] - 300.0) < 1e-6
        assert abs(p.velocity[1] - 100.0) < 1e-6

    def test_damage_stored(self):
        p = self._p(damage=25.0)
        assert abs(p.damage - 25.0) < 1e-6

    def test_strata_layer_stored(self):
        p = self._p(strata_layer=2)
        assert p.strata_layer == 2

    def test_lifetime_positive(self):
        p = self._p()
        assert p.lifetime > 0.0

    def test_tick_advances_position(self):
        p = self._p(vx=300.0, vy=0.0)
        p.position = (0.0, 0.0)
        p.scene = None
        p.tick(0.016)
        assert p.position[0] > 0.0

    def test_tick_decrements_lifetime(self):
        p = self._p()
        initial = p.lifetime
        p.scene = None
        p.tick(0.1)
        assert p.lifetime < initial

    def test_all_weapon_types_instantiate(self):
        from entities.projectile import Projectile
        for wt in ["bullet", "pistol", "laser", "plasma", "rocket", "gravity", "orbital"]:
            proj = Projectile(owner_id=0, weapon_type=wt,
                              vx=100.0, vy=0.0, damage=10.0, strata_layer=0)
            assert proj is not None

    def test_has_layer(self):
        p = self._p()
        assert len(p.layers) >= 1

    def test_temperature_initially_zero(self):
        p = self._p()
        assert p.temperature == 0.0


# =============================================================================
# WeaponPickup
# =============================================================================

class TestWeaponPickup:
    def _wp(self, weapon_type="bullet"):
        from entities.weapon_pickup import WeaponPickup
        return WeaponPickup(weapon_type=weapon_type)

    def test_instantiates(self):
        assert self._wp() is not None

    def test_weapon_type_stored(self):
        wp = self._wp("rocket")
        assert wp.weapon_type == "rocket"

    def test_has_collision_shape(self):
        from pharos_engine.collision import AABBShape
        wp = self._wp()
        assert isinstance(wp.collision_shape, AABBShape)

    def test_collision_shape_size(self):
        wp = self._wp()
        assert wp.collision_shape.width == 32
        assert wp.collision_shape.height == 32

    def test_has_layer(self):
        wp = self._wp()
        assert len(wp.layers) >= 1

    def test_on_spawn_sets_base_y(self):
        wp = self._wp()
        wp.position = (100.0, 200.0)
        wp.on_spawn()
        assert abs(wp._base_y - 200.0) < 1e-6

    def test_tick_bobs_position(self):
        import math
        wp = self._wp()
        wp.position = (100.0, 200.0)
        wp._base_y = 200.0
        wp.tick(0.5)
        expected_y = 200.0 + math.sin(0.5 * 2.5) * 6.0
        assert abs(wp.position[1] - expected_y) < 0.01

    def test_all_weapon_types_instantiate(self):
        from entities.weapon_pickup import WeaponPickup
        for wt in ["bullet", "pistol", "laser", "plasma", "rocket", "gravity", "orbital"]:
            wp = WeaponPickup(weapon_type=wt)
            assert wp is not None
