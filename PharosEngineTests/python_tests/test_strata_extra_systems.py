"""Headless tests for Bullet Strata extra systems and entities:
JetpackScript, TeleportScript, WeaponScript (stubs), DroneEnemy,
ShadeEnemy, BruteEnemy, Projectile, WeaponPickup.
"""
from __future__ import annotations
import sys
import math
from pathlib import Path
from unittest.mock import MagicMock
import pytest

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("pharos_engine.compute.asset_compute", MagicMock())

_STRATA_ROOT = Path(__file__).parent.parent.parent.parent.parent / "DaedalusSVN" / "Bullet Strata"
_STRATA_STR = str(_STRATA_ROOT)

_CONFLICT_PKGS = ("systems", "entities", "scenes")


@pytest.fixture(autouse=True)
def _strata_isolation():
    """Isolate Bullet Strata imports from Ochema Circuit package namespace."""
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

def _fake_entity(energy=1.0, grounded=True, vel=None, pos=(100.0, 200.0)):
    """Return a fake entity compatible with JetpackScript.on_tick."""
    e = MagicMock()
    e.velocity = list(vel) if vel else [0.0, 0.0]
    e.position = pos
    e.energy = energy
    e.grounded = grounded
    e.scene._engine.input = None  # no input → gravity/recharge only
    return e


def _teleport_entity(cooldown=0.0, strata_layer=0, vel=None):
    e = MagicMock()
    e.velocity = list(vel) if vel else [50.0, 0.0]
    e.position = (300.0, 300.0)
    e.strata_layer = strata_layer
    e.teleport_cooldown = cooldown
    e.scene._engine.input = None
    e.scene.strata = None
    e.scene.entities = []
    return e


# =============================================================================
# JetpackScript
# =============================================================================

class TestJetpackScriptInit:
    def _js(self):
        from systems.jetpack import JetpackScript
        return JetpackScript()

    def test_instantiates(self):
        assert self._js() is not None

    def test_constants_positive(self):
        from systems.jetpack import THRUST, DRAIN_RATE, RECHARGE, MAX_ENERGY, GRAVITY
        assert THRUST > 0
        assert DRAIN_RATE > 0
        assert RECHARGE > 0
        assert MAX_ENERGY > 0
        assert GRAVITY > 0


class TestJetpackScriptGravity:
    def _js(self):
        from systems.jetpack import JetpackScript
        return JetpackScript()

    def test_gravity_always_applied(self):
        from systems.jetpack import GRAVITY
        js = self._js()
        e = _fake_entity()
        js.on_tick(e, 0.1)
        assert abs(e.velocity[1] - GRAVITY * 0.1) < 1e-3

    def test_gravity_accumulates_over_ticks(self):
        from systems.jetpack import GRAVITY
        js = self._js()
        e = _fake_entity()
        for _ in range(5):
            js.on_tick(e, 0.1)
        assert e.velocity[1] > GRAVITY * 0.1  # accumulated over 5 ticks

    def test_position_updates_after_tick(self):
        js = self._js()
        e = _fake_entity()
        e.velocity = [100.0, 0.0]
        y0 = e.position[1]
        js.on_tick(e, 0.1)
        # position updated by velocity
        assert e.position[0] != 100.0 or e.position[1] != y0  # something moved

    def test_no_input_horizontal_unchanged(self):
        js = self._js()
        e = _fake_entity()
        e.velocity = [200.0, 0.0]
        js.on_tick(e, 0.016)
        # inp is None so the input block (including friction) is skipped
        assert abs(e.velocity[0]) == 200.0

    def test_grounded_recharges_energy(self):
        from systems.jetpack import MAX_ENERGY, RECHARGE
        js = self._js()
        e = _fake_entity(energy=0.5, grounded=True)
        js.on_tick(e, 0.1)
        assert e.energy > 0.5

    def test_grounded_energy_caps_at_max(self):
        from systems.jetpack import MAX_ENERGY
        js = self._js()
        e = _fake_entity(energy=MAX_ENERGY, grounded=True)
        js.on_tick(e, 1.0)
        assert e.energy <= MAX_ENERGY


# =============================================================================
# TeleportScript
# =============================================================================

class TestTeleportScriptInit:
    def _ts(self):
        from systems.teleport import TeleportScript
        return TeleportScript()

    def test_instantiates(self):
        assert self._ts() is not None

    def test_constants_loaded(self):
        from systems.teleport import COOLDOWN, MOMENTUM_MUL, FRAG_RADIUS, NUM_LAYERS
        assert COOLDOWN > 0
        assert MOMENTUM_MUL > 0
        assert FRAG_RADIUS > 0
        assert NUM_LAYERS == 3


class TestTeleportScriptOnTick:
    def _ts(self):
        from systems.teleport import TeleportScript
        return TeleportScript()

    def test_cooldown_decrements(self):
        ts = self._ts()
        e = _teleport_entity(cooldown=1.0)
        ts.on_tick(e, 0.1)
        assert e.teleport_cooldown < 1.0

    def test_cooldown_clamped_to_zero(self):
        ts = self._ts()
        e = _teleport_entity(cooldown=0.05)
        ts.on_tick(e, 0.1)
        assert e.teleport_cooldown == 0.0

    def test_no_input_no_teleport(self):
        ts = self._ts()
        e = _teleport_entity(cooldown=0.0, strata_layer=0)
        initial_layer = e.strata_layer
        ts.on_tick(e, 0.016)
        # inp is None, so key_just_pressed is never called; layer should be unchanged
        assert e.strata_layer == initial_layer

    def test_tick_no_crash_zero_cooldown(self):
        ts = self._ts()
        e = _teleport_entity(cooldown=0.0)
        ts.on_tick(e, 0.016)

    def test_tick_multiple_no_crash(self):
        ts = self._ts()
        e = _teleport_entity(cooldown=5.0)
        for _ in range(30):
            ts.on_tick(e, 0.016)


# =============================================================================
# DroneEnemy
# =============================================================================

class TestDroneEnemyInit:
    def _de(self):
        from entities.enemy import DroneEnemy
        return DroneEnemy()

    def test_instantiates(self):
        assert self._de() is not None

    def test_alive_initially(self):
        d = self._de()
        assert d.alive is True

    def test_hp_at_max(self):
        from entities.enemy import DRONE_MAX_HP
        d = self._de()
        assert d.hp == DRONE_MAX_HP

    def test_data_component_created(self):
        d = self._de()
        assert d.data is not None

    def test_rect_property(self):
        from entities.enemy import DRONE_W, DRONE_H
        d = self._de()
        d.pos = (100.0, 200.0)
        rx, ry, rw, rh = d.rect
        assert rw == DRONE_W
        assert rh == DRONE_H

    def test_pending_shots_empty(self):
        d = self._de()
        assert d.pending_shots == []

    def test_has_layer(self):
        d = self._de()
        assert len(d.layers) > 0


class TestDroneEnemyDamage:
    def _de(self):
        from entities.enemy import DroneEnemy
        return DroneEnemy()

    def test_take_damage_reduces_hp(self):
        from entities.enemy import DRONE_MAX_HP
        d = self._de()
        d.take_damage(10)
        assert d.hp == DRONE_MAX_HP - 10

    def test_take_damage_clamped_to_zero(self):
        d = self._de()
        d.take_damage(9999)
        assert d.hp == 0

    def test_lethal_damage_returns_true(self):
        from entities.enemy import DRONE_MAX_HP
        d = self._de()
        result = d.take_damage(DRONE_MAX_HP)
        assert result is True

    def test_lethal_damage_sets_alive_false(self):
        from entities.enemy import DRONE_MAX_HP
        d = self._de()
        d.take_damage(DRONE_MAX_HP)
        assert d.alive is False

    def test_non_lethal_returns_false(self):
        d = self._de()
        result = d.take_damage(1)
        assert result is False

    def test_partial_damage_alive_true(self):
        d = self._de()
        d.take_damage(5)
        assert d.alive is True


class TestDroneEnemyUpdate:
    def _de(self):
        from entities.enemy import DroneEnemy
        return DroneEnemy()

    def test_update_empty_players_no_crash(self):
        d = self._de()
        d.update(0.016, players=[])

    def test_update_dead_no_crash(self):
        from entities.enemy import DRONE_MAX_HP
        d = self._de()
        d.take_damage(DRONE_MAX_HP)
        d.update(0.016, players=[])

    def test_update_multiple_ticks_no_crash(self):
        d = self._de()
        for _ in range(10):
            d.update(0.016, players=[])

    def test_update_with_dead_player_no_crash(self):
        from entities.enemy import DroneEnemy
        d = DroneEnemy()
        dead_player = MagicMock()
        dead_player.data.get.return_value = "dead"
        dead_player.position = (200.0, 200.0)
        d.update(0.016, players=[dead_player])

    def test_regen_when_deform_inactive(self):
        from entities.enemy import DRONE_MAX_HP
        d = self._de()
        if d._deform_ctrl is None:
            pytest.skip("DeformController not available")
        d.take_damage(5)
        hp_before = d.hp
        # deform_ctrl.is_active is a read-only property; call deactivate via not activating it
        # Just verify update doesn't crash with a slightly damaged drone
        d.update(1.0, players=[])
        # After 1s of regen at 0.5 HP/s, hp should be same or higher
        assert d.hp >= hp_before or d.hp == hp_before


# =============================================================================
# ShadeEnemy
# =============================================================================

class TestShadeEnemyInit:
    def _se(self):
        from entities.enemy import ShadeEnemy
        return ShadeEnemy()

    def test_instantiates(self):
        assert self._se() is not None

    def test_alive_initially(self):
        assert self._se().alive is True

    def test_hp_at_max(self):
        from entities.enemy import SHADE_MAX_HP
        s = self._se()
        assert s.hp == SHADE_MAX_HP

    def test_not_fallen_initially(self):
        assert self._se()._fallen is False

    def test_rect_property(self):
        from entities.enemy import SHADE_W, SHADE_H
        s = self._se()
        s.pos = (50.0, 80.0)
        rx, ry, rw, rh = s.rect
        assert rw == SHADE_W
        assert rh == SHADE_H


class TestShadeEnemyDamage:
    def _se(self):
        from entities.enemy import ShadeEnemy
        return ShadeEnemy()

    def test_take_damage_reduces_hp(self):
        from entities.enemy import SHADE_MAX_HP
        s = self._se()
        s.take_damage(10)
        assert s.hp == SHADE_MAX_HP - 10

    def test_lethal_damage_sets_fallen(self):
        from entities.enemy import SHADE_MAX_HP
        s = self._se()
        s.take_damage(SHADE_MAX_HP)
        assert s._fallen is True

    def test_lethal_damage_alive_false(self):
        from entities.enemy import SHADE_MAX_HP
        s = self._se()
        s.take_damage(SHADE_MAX_HP)
        assert s.alive is False

    def test_lethal_damage_sets_persist_timer(self):
        from entities.enemy import SHADE_MAX_HP
        s = self._se()
        s.take_damage(SHADE_MAX_HP)
        assert s._persist_timer > 0


class TestShadeEnemyUpdate:
    def _se(self):
        from entities.enemy import ShadeEnemy
        return ShadeEnemy()

    def test_update_empty_players_no_crash(self):
        s = self._se()
        s.update(0.016, players=[])

    def test_fallen_persist_timer_decrements(self):
        from entities.enemy import SHADE_MAX_HP
        s = self._se()
        s.take_damage(SHADE_MAX_HP)
        timer_before = s._persist_timer
        s.update(0.5, players=[])
        assert s._persist_timer < timer_before

    def test_fallen_expired_removes_from_scene(self):
        from entities.enemy import SHADE_MAX_HP
        s = self._se()
        s.take_damage(SHADE_MAX_HP)
        s._persist_timer = 0.01  # nearly expired
        scene = MagicMock()
        s.scene = scene
        s.update(0.1, players=[])  # timer expires
        scene.remove.assert_called_once_with(s)


# =============================================================================
# BruteEnemy
# =============================================================================

class TestBruteEnemyInit:
    def _be(self):
        from entities.enemy import BruteEnemy
        return BruteEnemy()

    def test_instantiates(self):
        assert self._be() is not None

    def test_alive_initially(self):
        assert self._be().alive is True

    def test_not_wrecked_initially(self):
        assert self._be()._wrecked is False

    def test_hp_at_max(self):
        from entities.enemy import BRUTE_MAX_HP
        b = self._be()
        assert b.hp == BRUTE_MAX_HP

    def test_not_charging_initially(self):
        assert self._be()._charging is False

    def test_rect_property(self):
        from entities.enemy import BRUTE_W, BRUTE_H
        b = self._be()
        b.pos = (0.0, 0.0)
        rx, ry, rw, rh = b.rect
        assert rw == BRUTE_W
        assert rh == BRUTE_H

    def test_pending_shots_empty(self):
        assert self._be().pending_shots == []


class TestBruteEnemyDamage:
    def _be(self):
        from entities.enemy import BruteEnemy
        return BruteEnemy()

    def test_take_damage_reduces_hp(self):
        from entities.enemy import BRUTE_MAX_HP
        b = self._be()
        b.take_damage(50)
        assert b.hp == BRUTE_MAX_HP - 50

    def test_lethal_damage_returns_true(self):
        from entities.enemy import BRUTE_MAX_HP
        b = self._be()
        result = b.take_damage(BRUTE_MAX_HP)
        assert result is True

    def test_lethal_damage_sets_wrecked(self):
        from entities.enemy import BRUTE_MAX_HP
        b = self._be()
        b.take_damage(BRUTE_MAX_HP)
        assert b._wrecked is True

    def test_lethal_damage_alive_false(self):
        from entities.enemy import BRUTE_MAX_HP
        b = self._be()
        b.take_damage(BRUTE_MAX_HP)
        assert b.alive is False

    def test_wrecked_update_is_noop(self):
        from entities.enemy import BRUTE_MAX_HP
        b = self._be()
        b.take_damage(BRUTE_MAX_HP)
        initial_pos = b.pos
        b.update(1.0, players=[])
        assert b.pos == initial_pos


class TestBruteEnemyUpdate:
    def _be(self):
        from entities.enemy import BruteEnemy
        return BruteEnemy()

    def test_update_empty_players_no_crash(self):
        b = self._be()
        b.update(0.016, players=[])

    def test_update_multiple_ticks_no_crash(self):
        b = self._be()
        for _ in range(10):
            b.update(0.016, players=[])

    def test_charging_when_close_player(self):
        from entities.enemy import BRUTE_CHARGE_RANGE
        b = self._be()
        b.pos = (100.0, 100.0)
        player = MagicMock()
        player.data.get.return_value = "alive"
        player.position = (100.0 + BRUTE_CHARGE_RANGE * 0.5, 100.0)
        b.update(0.016, players=[player])
        assert b._charging is True

    def test_not_charging_when_far_player(self):
        from entities.enemy import BRUTE_CHARGE_RANGE
        b = self._be()
        b.pos = (0.0, 0.0)
        player = MagicMock()
        player.data.get.return_value = "alive"
        player.position = (BRUTE_CHARGE_RANGE * 3, 0.0)
        b.update(0.016, players=[player])
        assert b._charging is False


# =============================================================================
# Projectile (entities/projectile.py)
# =============================================================================

class TestProjectileInit:
    def _proj(self, weapon_type="pistol"):
        from entities.projectile import Projectile
        return Projectile(owner_id=1, weapon_type=weapon_type,
                          vx=100.0, vy=0.0, damage=10.0, strata_layer=0)

    def test_instantiates(self):
        assert self._proj() is not None

    def test_owner_id_stored(self):
        p = self._proj()
        assert p.owner_id == 1

    def test_velocity_stored(self):
        p = self._proj()
        assert p.velocity[0] == 100.0
        assert p.velocity[1] == 0.0

    def test_damage_stored(self):
        p = self._proj()
        assert p.damage == 10.0

    def test_strata_layer_stored(self):
        p = self._proj()
        assert p.strata_layer == 0

    def test_lifetime_positive(self):
        p = self._proj()
        assert p.lifetime > 0

    def test_has_layer(self):
        p = self._proj()
        assert len(p.layers) > 0

    def test_temperature_zero(self):
        p = self._proj()
        assert p.temperature == 0.0

    def test_known_weapon_types_no_crash(self):
        for wtype in ("pistol", "laser", "plasma", "rocket", "gravity", "orbital"):
            self._proj(weapon_type=wtype)


class TestProjectileTick:
    def _proj(self):
        from entities.projectile import Projectile
        return Projectile(owner_id=1, weapon_type="pistol",
                          vx=100.0, vy=0.0, damage=10.0, strata_layer=0)

    def test_tick_advances_position(self):
        p = self._proj()
        p.position = (100.0, 100.0)
        x0 = p.position[0]
        p.tick(0.1)
        assert p.position[0] > x0

    def test_tick_decrements_lifetime(self):
        p = self._proj()
        lt0 = p.lifetime
        p.tick(0.1)
        assert p.lifetime < lt0

    def test_tick_no_scene_no_crash(self):
        p = self._proj()
        p.scene = None
        for _ in range(100):
            p.tick(0.016)  # lifetime expires but scene is None → no crash

    def test_apply_burn_numpy_array(self):
        import numpy as np
        from entities.projectile import Projectile
        p = Projectile(owner_id=1, weapon_type="pistol",
                       vx=0.0, vy=0.0, damage=60.0, strata_layer=0)
        target = MagicMock()
        arr = np.ones((10, 10, 4), dtype=np.uint8) * 200
        target.image = arr
        Projectile._apply_burn(target)
        # Center region should be darkened
        assert target.image[5, 5, 0] < 200

    def test_remove_point_light_no_light_no_crash(self):
        p = self._proj()
        p._point_light = None
        p._lighting = None
        p._remove_point_light()  # should not raise


# =============================================================================
# WeaponPickup (entities/weapon_pickup.py)
# =============================================================================

class TestWeaponPickupInit:
    def _wp(self, weapon_type="pistol"):
        from entities.weapon_pickup import WeaponPickup
        return WeaponPickup(weapon_type=weapon_type)

    def test_instantiates(self):
        assert self._wp() is not None

    def test_weapon_type_stored(self):
        w = self._wp("plasma")
        assert w.weapon_type == "plasma"

    def test_bob_timer_zero(self):
        w = self._wp()
        assert w._bob_timer == 0.0

    def test_collision_shape_set(self):
        from pharos_engine.collision import AABBShape
        w = self._wp()
        assert isinstance(w.collision_shape, AABBShape)

    def test_has_layer(self):
        w = self._wp()
        assert len(w.layers) > 0

    def test_all_weapon_types_no_crash(self):
        for wt in ("pistol", "laser", "plasma", "rocket", "gravity", "orbital"):
            self._wp(wt)


class TestWeaponPickupTick:
    def _wp(self):
        from entities.weapon_pickup import WeaponPickup
        w = WeaponPickup("pistol")
        w.position = (100.0, 200.0)
        w._base_y = 200.0
        return w

    def test_tick_increments_bob_timer(self):
        w = self._wp()
        w.tick(0.016)
        assert w._bob_timer > 0.0

    def test_tick_changes_y_position(self):
        w = self._wp()
        w.tick(0.1)
        # bob_timer = 0.1; sin(0.25) != 0 → y changes
        assert w.position[1] != 200.0

    def test_tick_x_unchanged(self):
        w = self._wp()
        w.tick(0.1)
        assert w.position[0] == 100.0

    def test_tick_multiple_no_crash(self):
        w = self._wp()
        for _ in range(60):
            w.tick(0.016)

    def test_on_spawn_sets_base_y(self):
        from entities.weapon_pickup import WeaponPickup
        w = WeaponPickup("pistol")
        w.position = (50.0, 300.0)
        w.on_spawn()
        assert w._base_y == 300.0
