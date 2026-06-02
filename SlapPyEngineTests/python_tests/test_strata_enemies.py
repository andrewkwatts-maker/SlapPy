"""Headless tests for Bullet Strata DroneEnemy, ShadeEnemy, BruteEnemy."""
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
# Helpers
# =============================================================================

def _make_player(pos=(400.0, 300.0), state="alive"):
    p = MagicMock()
    p.position = pos
    p.data = MagicMock()
    p.data.get = lambda k, default=None: state if k == "state" else default
    return p


def _dead_player(pos=(400.0, 300.0)):
    return _make_player(pos=pos, state="dead")


# =============================================================================
# _dist_to / _dir_to helpers
# =============================================================================

class TestDistDir:
    def test_dist_to_same_point(self):
        from entities.enemy import _dist_to
        assert _dist_to((0.0, 0.0), (0.0, 0.0)) == pytest.approx(0.0)

    def test_dist_to_known_distance(self):
        from entities.enemy import _dist_to
        assert _dist_to((0.0, 0.0), (3.0, 4.0)) == pytest.approx(5.0)

    def test_dir_to_unit_vector(self):
        import math
        from entities.enemy import _dir_to
        dx, dy = _dir_to((0.0, 0.0), (3.0, 4.0))
        assert math.hypot(dx, dy) == pytest.approx(1.0)

    def test_dir_to_coincident_returns_zero(self):
        from entities.enemy import _dir_to
        dx, dy = _dir_to((5.0, 5.0), (5.0, 5.0))
        assert dx == pytest.approx(0.0)
        assert dy == pytest.approx(0.0)

    def test_dir_to_right(self):
        from entities.enemy import _dir_to
        dx, dy = _dir_to((0.0, 0.0), (10.0, 0.0))
        assert dx == pytest.approx(1.0)
        assert dy == pytest.approx(0.0)


# =============================================================================
# DroneEnemy
# =============================================================================

class TestDroneEnemyInit:
    def test_init_no_crash(self):
        from entities.enemy import DroneEnemy
        d = DroneEnemy()
        assert d is not None

    def test_alive_initially(self):
        from entities.enemy import DroneEnemy
        d = DroneEnemy()
        assert d.alive is True

    def test_hp_full_initially(self):
        from entities.enemy import DroneEnemy, DRONE_MAX_HP
        d = DroneEnemy()
        assert d.hp == DRONE_MAX_HP

    def test_no_pending_shots_initially(self):
        from entities.enemy import DroneEnemy
        d = DroneEnemy()
        assert d.pending_shots == []

    def test_rect_size(self):
        from entities.enemy import DroneEnemy, DRONE_W, DRONE_H
        d = DroneEnemy()
        d.pos = (0.0, 0.0)
        _, _, w, h = d.rect
        assert w == DRONE_W
        assert h == DRONE_H

    def test_rect_centered_on_pos(self):
        from entities.enemy import DroneEnemy, DRONE_W, DRONE_H
        d = DroneEnemy()
        d.pos = (100.0, 200.0)
        x, y, _, _ = d.rect
        assert x == pytest.approx(100.0 - DRONE_W // 2)
        assert y == pytest.approx(200.0 - DRONE_H // 2)


class TestDroneEnemyTakeDamage:
    def test_take_damage_reduces_hp(self):
        from entities.enemy import DroneEnemy, DRONE_MAX_HP
        d = DroneEnemy()
        d.take_damage(10)
        assert d.hp == DRONE_MAX_HP - 10

    def test_take_damage_returns_false_when_alive(self):
        from entities.enemy import DroneEnemy
        d = DroneEnemy()
        result = d.take_damage(5)
        assert result is False

    def test_take_damage_kills_at_max_hp(self):
        from entities.enemy import DroneEnemy, DRONE_MAX_HP
        d = DroneEnemy()
        result = d.take_damage(DRONE_MAX_HP)
        assert result is True
        assert d.alive is False

    def test_hp_floored_at_zero(self):
        from entities.enemy import DroneEnemy
        d = DroneEnemy()
        d.take_damage(10000)
        assert d.hp == 0

    def test_dead_after_lethal_damage(self):
        from entities.enemy import DroneEnemy, DRONE_MAX_HP
        d = DroneEnemy()
        d.take_damage(DRONE_MAX_HP)
        assert d.alive is False


class TestDroneEnemyUpdate:
    def test_update_no_crash_with_no_players(self):
        from entities.enemy import DroneEnemy
        d = DroneEnemy()
        d.pos = (100.0, 100.0)
        d.update(0.016, players=[])

    def test_update_moves_toward_player(self):
        from entities.enemy import DroneEnemy, DRONE_SPEED
        d = DroneEnemy()
        d.pos = (0.0, 0.0)
        player = _make_player(pos=(100.0, 0.0))
        d.update(0.1, players=[player])
        assert d.pos[0] > 0.0

    def test_update_fires_after_cooldown(self):
        from entities.enemy import DroneEnemy, DRONE_FIRE_RATE
        d = DroneEnemy()
        d.pos = (0.0, 0.0)
        d._fire_timer = 0.0  # ready to fire immediately
        player = _make_player(pos=(100.0, 0.0))
        d.update(0.001, players=[player])
        assert len(d.pending_shots) == 1

    def test_update_queued_shot_has_correct_keys(self):
        from entities.enemy import DroneEnemy
        d = DroneEnemy()
        d.pos = (50.0, 50.0)
        d._fire_timer = 0.0
        player = _make_player(pos=(150.0, 50.0))
        d.update(0.001, players=[player])
        shot = d.pending_shots[0]
        for key in ("ox", "oy", "vx", "vy", "damage", "owner"):
            assert key in shot

    def test_update_dead_player_skipped(self):
        from entities.enemy import DroneEnemy
        d = DroneEnemy()
        d.pos = (0.0, 0.0)
        dead = _dead_player(pos=(50.0, 0.0))
        d.update(0.1, players=[dead])
        # No movement since no live targets
        assert d.pos == (0.0, 0.0)

    def test_update_dead_enemy_does_nothing(self):
        from entities.enemy import DroneEnemy
        d = DroneEnemy()
        d.alive = False
        d.pos = (100.0, 100.0)
        player = _make_player(pos=(200.0, 100.0))
        d.update(0.1, players=[player])
        assert d.pos == (100.0, 100.0)  # did not move

    def test_position_synced_to_asset_position(self):
        from entities.enemy import DroneEnemy
        d = DroneEnemy()
        d.pos = (0.0, 0.0)
        player = _make_player(pos=(100.0, 0.0))
        d.update(0.1, players=[player])
        assert d.position == d.pos


# =============================================================================
# ShadeEnemy
# =============================================================================

class TestShadeEnemyInit:
    def test_init_no_crash(self):
        from entities.enemy import ShadeEnemy
        s = ShadeEnemy()
        assert s is not None

    def test_alive_initially(self):
        from entities.enemy import ShadeEnemy
        s = ShadeEnemy()
        assert s.alive is True

    def test_hp_full_initially(self):
        from entities.enemy import ShadeEnemy, SHADE_MAX_HP
        s = ShadeEnemy()
        assert s.hp == SHADE_MAX_HP

    def test_not_fallen_initially(self):
        from entities.enemy import ShadeEnemy
        s = ShadeEnemy()
        assert s._fallen is False

    def test_no_pending_shots_initially(self):
        from entities.enemy import ShadeEnemy
        s = ShadeEnemy()
        assert s.pending_shots == []

    def test_rect_size(self):
        from entities.enemy import ShadeEnemy, SHADE_W, SHADE_H
        s = ShadeEnemy()
        s.pos = (0.0, 0.0)
        _, _, w, h = s.rect
        assert w == SHADE_W
        assert h == SHADE_H


class TestShadeEnemyTakeDamage:
    def test_damage_reduces_hp(self):
        from entities.enemy import ShadeEnemy, SHADE_MAX_HP
        s = ShadeEnemy()
        s.take_damage(20)
        assert s.hp == SHADE_MAX_HP - 20

    def test_lethal_damage_sets_fallen(self):
        from entities.enemy import ShadeEnemy, SHADE_MAX_HP
        s = ShadeEnemy()
        s.take_damage(SHADE_MAX_HP)
        assert s._fallen is True

    def test_lethal_damage_returns_true(self):
        from entities.enemy import ShadeEnemy, SHADE_MAX_HP
        s = ShadeEnemy()
        result = s.take_damage(SHADE_MAX_HP)
        assert result is True

    def test_lethal_damage_marks_not_alive(self):
        from entities.enemy import ShadeEnemy, SHADE_MAX_HP
        s = ShadeEnemy()
        s.take_damage(SHADE_MAX_HP)
        assert s.alive is False

    def test_persist_timer_set_on_death(self):
        from entities.enemy import ShadeEnemy, SHADE_MAX_HP
        s = ShadeEnemy()
        s.take_damage(SHADE_MAX_HP)
        assert s._persist_timer == pytest.approx(s._PERSIST_DURATION)


class TestShadeEnemyUpdate:
    def test_update_fallen_ticks_timer(self):
        from entities.enemy import ShadeEnemy
        s = ShadeEnemy()
        s._fallen = True
        s._persist_timer = 2.0
        s.update(0.5, players=[])
        assert s._persist_timer == pytest.approx(1.5)

    def test_fallen_timer_expires_removes_from_scene(self):
        from entities.enemy import ShadeEnemy
        s = ShadeEnemy()
        s._fallen = True
        s._persist_timer = 0.1
        scene = MagicMock()
        s.scene = scene
        s.update(0.5, players=[])
        scene.remove.assert_called_once_with(s)

    def test_fallen_timer_expired_no_scene_no_crash(self):
        from entities.enemy import ShadeEnemy
        s = ShadeEnemy()
        s._fallen = True
        s._persist_timer = 0.1
        s.scene = None
        s.update(0.5, players=[])  # no crash

    def test_shade_moves_toward_distant_player(self):
        from entities.enemy import ShadeEnemy, SHADE_ORBIT_R
        s = ShadeEnemy()
        far_pos = (SHADE_ORBIT_R * 3, 0.0)
        s.pos = (0.0, 0.0)
        player = _make_player(pos=far_pos)
        s.update(0.1, players=[player])
        assert s.pos[0] > 0.0

    def test_shade_fires_at_player(self):
        from entities.enemy import ShadeEnemy
        s = ShadeEnemy()
        s.pos = (0.0, 0.0)
        s._fire_timer = 0.0
        player = _make_player(pos=(100.0, 0.0))
        s.update(0.001, players=[player])
        assert len(s.pending_shots) == 1

    def test_dead_shade_does_not_update(self):
        from entities.enemy import ShadeEnemy
        s = ShadeEnemy()
        s.alive = False
        s._fallen = False  # not in fallen state
        s.pos = (0.0, 0.0)
        player = _make_player(pos=(100.0, 0.0))
        s.update(0.1, players=[player])
        assert s.pos == (0.0, 0.0)

    def test_no_targets_no_crash(self):
        from entities.enemy import ShadeEnemy
        s = ShadeEnemy()
        s.pos = (100.0, 100.0)
        s.update(0.016, players=[])


# =============================================================================
# BruteEnemy
# =============================================================================

class TestBruteEnemyInit:
    def test_init_no_crash(self):
        from entities.enemy import BruteEnemy
        b = BruteEnemy()
        assert b is not None

    def test_alive_initially(self):
        from entities.enemy import BruteEnemy
        b = BruteEnemy()
        assert b.alive is True

    def test_hp_full_initially(self):
        from entities.enemy import BruteEnemy, BRUTE_MAX_HP
        b = BruteEnemy()
        assert b.hp == BRUTE_MAX_HP

    def test_not_charging_initially(self):
        from entities.enemy import BruteEnemy
        b = BruteEnemy()
        assert b._charging is False

    def test_not_wrecked_initially(self):
        from entities.enemy import BruteEnemy
        b = BruteEnemy()
        assert b._wrecked is False

    def test_pending_shots_empty(self):
        from entities.enemy import BruteEnemy
        b = BruteEnemy()
        assert b.pending_shots == []

    def test_rect_size(self):
        from entities.enemy import BruteEnemy, BRUTE_W, BRUTE_H
        b = BruteEnemy()
        b.pos = (0.0, 0.0)
        _, _, w, h = b.rect
        assert w == BRUTE_W
        assert h == BRUTE_H


class TestBruteEnemyTakeDamage:
    def test_damage_reduces_hp(self):
        from entities.enemy import BruteEnemy, BRUTE_MAX_HP
        b = BruteEnemy()
        b.take_damage(50)
        assert b.hp == BRUTE_MAX_HP - 50

    def test_lethal_damage_returns_true(self):
        from entities.enemy import BruteEnemy, BRUTE_MAX_HP
        b = BruteEnemy()
        result = b.take_damage(BRUTE_MAX_HP)
        assert result is True

    def test_lethal_damage_marks_wrecked(self):
        from entities.enemy import BruteEnemy, BRUTE_MAX_HP
        b = BruteEnemy()
        b.take_damage(BRUTE_MAX_HP)
        assert b._wrecked is True

    def test_lethal_damage_marks_not_alive(self):
        from entities.enemy import BruteEnemy, BRUTE_MAX_HP
        b = BruteEnemy()
        b.take_damage(BRUTE_MAX_HP)
        assert b.alive is False

    def test_hp_floored_at_zero(self):
        from entities.enemy import BruteEnemy
        b = BruteEnemy()
        b.take_damage(100000)
        assert b.hp == 0


class TestBruteEnemyUpdate:
    def test_wrecked_does_not_move(self):
        from entities.enemy import BruteEnemy
        b = BruteEnemy()
        b._wrecked = True
        b.pos = (100.0, 100.0)
        player = _make_player(pos=(200.0, 100.0))
        b.update(0.1, players=[player])
        assert b.pos == (100.0, 100.0)

    def test_no_targets_no_crash(self):
        from entities.enemy import BruteEnemy
        b = BruteEnemy()
        b.pos = (100.0, 100.0)
        b.update(0.016, players=[])

    def test_brute_moves_toward_distant_player(self):
        from entities.enemy import BruteEnemy, BRUTE_CHARGE_RANGE
        b = BruteEnemy()
        b.pos = (0.0, 0.0)
        far_player = _make_player(pos=(BRUTE_CHARGE_RANGE * 3, 0.0))
        b.update(0.1, players=[far_player])
        assert b.pos[0] > 0.0

    def test_brute_not_charging_far_player(self):
        from entities.enemy import BruteEnemy, BRUTE_CHARGE_RANGE
        b = BruteEnemy()
        b.pos = (0.0, 0.0)
        far_player = _make_player(pos=(BRUTE_CHARGE_RANGE * 3, 0.0))
        b.update(0.016, players=[far_player])
        assert b._charging is False

    def test_brute_charging_close_player(self):
        from entities.enemy import BruteEnemy, BRUTE_CHARGE_RANGE
        b = BruteEnemy()
        b.pos = (0.0, 0.0)
        close_player = _make_player(pos=(BRUTE_CHARGE_RANGE * 0.5, 0.0))
        b.update(0.016, players=[close_player])
        assert b._charging is True

    def test_position_synced(self):
        from entities.enemy import BruteEnemy
        b = BruteEnemy()
        b.pos = (0.0, 0.0)
        player = _make_player(pos=(100.0, 0.0))
        b.update(0.1, players=[player])
        assert b.position == b.pos

    def test_dead_player_skipped(self):
        from entities.enemy import BruteEnemy
        b = BruteEnemy()
        b.pos = (0.0, 0.0)
        dead = _dead_player(pos=(50.0, 0.0))
        b.update(0.1, players=[dead])
        assert b.pos == (0.0, 0.0)

    def test_brute_never_fires_shots(self):
        from entities.enemy import BruteEnemy, BRUTE_CHARGE_RANGE
        b = BruteEnemy()
        b.pos = (0.0, 0.0)
        player = _make_player(pos=(BRUTE_CHARGE_RANGE * 0.5, 0.0))
        b.update(0.1, players=[player])
        assert b.pending_shots == []
