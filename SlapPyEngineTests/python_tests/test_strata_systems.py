"""Headless tests for Bullet Strata JetpackScript, WeaponScript, QualityManager."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock, call
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

def _make_input(**key_held_map):
    """Return a mock input object with configurable key states."""
    inp = MagicMock()
    inp.key_held = MagicMock(side_effect=lambda k: key_held_map.get(k, False))
    inp.key_just_pressed = MagicMock(return_value=False)
    return inp


def _make_jetpack_entity(energy=1.0, grounded=True, vy=0.0, vx=0.0, inp=None):
    e = MagicMock()
    e.velocity = [vx, vy]
    e.energy = energy
    e.grounded = grounded
    e.position = (200.0, 300.0)
    if inp is None:
        inp = _make_input()
    e.scene._engine.input = inp
    return e


def _make_weapon_entity(weapon="pistol", energy=1.0, cooldown=0.0, inp=None):
    e = MagicMock()
    e.fire_cooldown = cooldown
    e.energy = energy
    e.current_weapon = weapon
    e.player_id = 0
    e.strata_layer = 0
    e.position = (100.0, 300.0)
    if inp is None:
        inp = _make_input()
    e.scene._engine.input = inp
    e.scene._engine.lighting = None  # suppress FlashLight / PointLight creation
    return e


# =============================================================================
# JetpackScript — gravity
# =============================================================================

class TestJetpackGravity:
    def test_gravity_applied_each_tick(self):
        from systems.jetpack import JetpackScript, GRAVITY
        e = _make_jetpack_entity()
        js = JetpackScript()
        js.on_tick(e, 0.1)
        assert e.velocity[1] == pytest.approx(GRAVITY * 0.1)

    def test_gravity_accumulates_over_ticks(self):
        from systems.jetpack import JetpackScript, GRAVITY
        e = _make_jetpack_entity()
        js = JetpackScript()
        js.on_tick(e, 0.1)
        js.on_tick(e, 0.1)
        assert e.velocity[1] == pytest.approx(GRAVITY * 0.2)

    def test_gravity_applied_even_with_no_input(self):
        from systems.jetpack import JetpackScript, GRAVITY
        e = _make_jetpack_entity(inp=None)
        e.scene._engine.input = None
        js = JetpackScript()
        js.on_tick(e, 0.05)
        assert e.velocity[1] > 0  # gravity increases downward velocity

    def test_gravity_applied_when_grounded(self):
        from systems.jetpack import JetpackScript, GRAVITY
        e = _make_jetpack_entity(grounded=True)
        js = JetpackScript()
        js.on_tick(e, 0.016)
        # velocity[1] increases by gravity even while grounded
        assert e.velocity[1] == pytest.approx(GRAVITY * 0.016)


# =============================================================================
# JetpackScript — thrust
# =============================================================================

class TestJetpackThrust:
    def test_thrust_reduces_vertical_velocity(self):
        from systems.jetpack import JetpackScript, THRUST, GRAVITY
        inp = _make_input(space=True)
        e = _make_jetpack_entity(energy=1.0, inp=inp)
        js = JetpackScript()
        js.on_tick(e, 0.1)
        net = (GRAVITY - THRUST) * 0.1
        assert e.velocity[1] == pytest.approx(net)

    def test_no_thrust_when_energy_zero(self):
        from systems.jetpack import JetpackScript, GRAVITY
        inp = _make_input(space=True)
        e = _make_jetpack_entity(energy=0.0, inp=inp)
        js = JetpackScript()
        js.on_tick(e, 0.1)
        # Only gravity applied, no thrust reduction
        assert e.velocity[1] == pytest.approx(GRAVITY * 0.1)

    def test_thrust_drains_energy(self):
        from systems.jetpack import JetpackScript, DRAIN_RATE
        inp = _make_input(space=True)
        e = _make_jetpack_entity(energy=1.0, inp=inp)
        js = JetpackScript()
        js.on_tick(e, 0.1)
        assert e.energy < 1.0

    def test_energy_does_not_go_below_zero_on_thrust(self):
        from systems.jetpack import JetpackScript
        inp = _make_input(space=True)
        e = _make_jetpack_entity(energy=0.001, inp=inp)
        js = JetpackScript()
        js.on_tick(e, 1.0)  # large dt — drains all energy
        assert e.energy >= 0.0


# =============================================================================
# JetpackScript — energy recharge
# =============================================================================

class TestJetpackRecharge:
    def test_energy_recharges_when_grounded(self):
        from systems.jetpack import JetpackScript, MAX_ENERGY
        e = _make_jetpack_entity(energy=0.5, grounded=True)
        js = JetpackScript()
        js.on_tick(e, 0.5)
        assert e.energy > 0.5

    def test_no_recharge_when_space_held(self):
        from systems.jetpack import JetpackScript
        inp = _make_input(space=True)
        e = _make_jetpack_entity(energy=0.5, grounded=True, inp=inp)
        initial_energy = e.energy
        js = JetpackScript()
        js.on_tick(e, 0.016)
        # Space held → thrust branch, not recharge
        assert e.energy <= initial_energy  # drained or unchanged, not recharged

    def test_energy_capped_at_max(self):
        from systems.jetpack import JetpackScript, MAX_ENERGY
        e = _make_jetpack_entity(energy=MAX_ENERGY, grounded=True)
        js = JetpackScript()
        js.on_tick(e, 1.0)
        assert e.energy <= MAX_ENERGY

    def test_no_recharge_when_not_grounded(self):
        from systems.jetpack import JetpackScript
        e = _make_jetpack_entity(energy=0.5, grounded=False)
        js = JetpackScript()
        js.on_tick(e, 0.5)
        # Not grounded, no space → no recharge branch
        # (but gravity applies, so we just check energy unchanged)
        assert e.energy == pytest.approx(0.5)


# =============================================================================
# JetpackScript — horizontal movement
# =============================================================================

class TestJetpackHorizontal:
    def test_left_key_sets_negative_vx(self):
        from systems.jetpack import JetpackScript
        inp = _make_input(a=True)
        e = _make_jetpack_entity(inp=inp)
        js = JetpackScript()
        js.on_tick(e, 0.016)
        assert e.velocity[0] == pytest.approx(-220.0)

    def test_left_arrow_sets_negative_vx(self):
        from systems.jetpack import JetpackScript
        inp = _make_input(left=True)
        e = _make_jetpack_entity(inp=inp)
        js = JetpackScript()
        js.on_tick(e, 0.016)
        assert e.velocity[0] == pytest.approx(-220.0)

    def test_right_key_sets_positive_vx(self):
        from systems.jetpack import JetpackScript
        inp = _make_input(d=True)
        e = _make_jetpack_entity(inp=inp)
        js = JetpackScript()
        js.on_tick(e, 0.016)
        assert e.velocity[0] == pytest.approx(220.0)

    def test_right_arrow_sets_positive_vx(self):
        from systems.jetpack import JetpackScript
        inp = _make_input(right=True)
        e = _make_jetpack_entity(inp=inp)
        js = JetpackScript()
        js.on_tick(e, 0.016)
        assert e.velocity[0] == pytest.approx(220.0)

    def test_no_key_applies_friction(self):
        from systems.jetpack import JetpackScript
        e = _make_jetpack_entity(vx=100.0)
        js = JetpackScript()
        js.on_tick(e, 0.016)
        assert abs(e.velocity[0]) < 100.0  # friction reduced it

    def test_friction_factor_correct(self):
        from systems.jetpack import JetpackScript
        e = _make_jetpack_entity(vx=100.0)
        js = JetpackScript()
        js.on_tick(e, 0.016)
        assert e.velocity[0] == pytest.approx(85.0)

    def test_no_input_applies_friction(self):
        from systems.jetpack import JetpackScript
        e = _make_jetpack_entity(vx=200.0)
        e.scene._engine.input = None
        js = JetpackScript()
        js.on_tick(e, 0.016)
        # No input object — friction branch not reached
        assert e.velocity[0] == pytest.approx(200.0)


# =============================================================================
# JetpackScript — position update
# =============================================================================

class TestJetpackPosition:
    def test_position_updated_by_velocity(self):
        from systems.jetpack import JetpackScript, GRAVITY
        # Use 'd' key so vx is set to 220.0 (no friction branch)
        inp = _make_input(d=True)
        e = _make_jetpack_entity(vx=0.0, vy=0.0, inp=inp)
        js = JetpackScript()
        dt = 0.1
        # 'd' key sets vx=220.0 before position update
        expected_x = 200.0 + 220.0 * dt
        js.on_tick(e, dt)
        assert e.position[0] == pytest.approx(expected_x)

    def test_position_y_moves_with_gravity(self):
        from systems.jetpack import JetpackScript, GRAVITY
        e = _make_jetpack_entity(vy=0.0)
        js = JetpackScript()
        dt = 0.1
        js.on_tick(e, dt)
        # vy after gravity: GRAVITY * dt; position_y += vy * dt
        expected_y = 300.0 + (GRAVITY * dt) * dt
        assert e.position[1] == pytest.approx(expected_y)


# =============================================================================
# WeaponScript — cooldown management
# =============================================================================

class TestWeaponCooldown:
    def test_cooldown_decrements(self):
        from systems.weapons import WeaponScript
        e = _make_weapon_entity(cooldown=0.5)
        ws = WeaponScript()
        ws.on_tick(e, 0.1)
        assert e.fire_cooldown == pytest.approx(0.4)

    def test_cooldown_clamps_to_zero(self):
        from systems.weapons import WeaponScript
        e = _make_weapon_entity(cooldown=0.1)
        ws = WeaponScript()
        ws.on_tick(e, 1.0)
        assert e.fire_cooldown == pytest.approx(0.0)

    def test_cooldown_already_zero_stays_zero(self):
        from systems.weapons import WeaponScript
        e = _make_weapon_entity(cooldown=0.0)
        ws = WeaponScript()
        ws.on_tick(e, 0.016)
        assert e.fire_cooldown == pytest.approx(0.0)

    def test_fire_sets_cooldown(self):
        from systems.weapons import WeaponScript, _WEAPONS
        inp = _make_input()
        inp.key_just_pressed = MagicMock(side_effect=lambda k: k == "f")
        e = _make_weapon_entity(cooldown=0.0, inp=inp)
        ws = WeaponScript()
        ws.on_tick(e, 0.016)
        expected_rate = _WEAPONS["pistol"]["fire_rate"]
        assert e.fire_cooldown == pytest.approx(expected_rate)

    def test_no_fire_when_cooldown_active(self):
        from systems.weapons import WeaponScript
        inp = _make_input()
        inp.key_just_pressed = MagicMock(side_effect=lambda k: k == "f")
        e = _make_weapon_entity(cooldown=0.5, inp=inp)
        ws = WeaponScript()
        ws.on_tick(e, 0.016)
        e.scene.add.assert_not_called()


# =============================================================================
# WeaponScript — weapon cycling
# =============================================================================

class TestWeaponCycling:
    def test_q_cycles_to_next_weapon(self):
        from systems.weapons import WeaponScript, _WEAPONS
        inp = _make_input()
        inp.key_just_pressed = MagicMock(side_effect=lambda k: k == "q")
        e = _make_weapon_entity(weapon="pistol", inp=inp)
        ws = WeaponScript()
        weapons = list(_WEAPONS.keys())
        ws.on_tick(e, 0.016)
        first_idx = weapons.index("pistol")
        expected = weapons[(first_idx + 1) % len(weapons)]
        assert e.current_weapon == expected

    def test_q_cycles_wraps_around(self):
        from systems.weapons import WeaponScript, _WEAPONS
        inp = _make_input()
        inp.key_just_pressed = MagicMock(side_effect=lambda k: k == "q")
        weapons = list(_WEAPONS.keys())
        last_weapon = weapons[-1]
        e = _make_weapon_entity(weapon=last_weapon, inp=inp)
        ws = WeaponScript()
        ws.on_tick(e, 0.016)
        assert e.current_weapon == weapons[0]

    def test_no_q_no_cycle(self):
        from systems.weapons import WeaponScript
        e = _make_weapon_entity(weapon="pistol")
        ws = WeaponScript()
        ws.on_tick(e, 0.016)
        assert e.current_weapon == "pistol"


# =============================================================================
# WeaponScript — _fire
# =============================================================================

class TestWeaponFire:
    def test_fire_adds_projectile_to_scene(self):
        from systems.weapons import WeaponScript
        from entities.projectile import Projectile
        inp = _make_input()
        inp.key_just_pressed = MagicMock(side_effect=lambda k: k == "f")
        e = _make_weapon_entity(cooldown=0.0, energy=1.0, inp=inp)
        ws = WeaponScript()
        ws.on_tick(e, 0.016)
        # At least one call should be a Projectile (spawn_burst may add more)
        added = [call.args[0] for call in e.scene.add.call_args_list]
        assert any(isinstance(a, Projectile) for a in added)

    def test_fire_deducts_energy(self):
        from systems.weapons import WeaponScript, _WEAPONS
        inp = _make_input()
        inp.key_just_pressed = MagicMock(side_effect=lambda k: k == "f")
        e = _make_weapon_entity(cooldown=0.0, energy=1.0, inp=inp)
        ws = WeaponScript()
        ws.on_tick(e, 0.016)
        cost = _WEAPONS["pistol"]["energy_cost"]
        # energy = clamp(1.0 - cost, 0, 1)
        expected = max(0.0, min(1.0, 1.0 - cost))
        assert e.energy == pytest.approx(expected)

    def test_no_fire_insufficient_energy(self):
        from systems.weapons import WeaponScript, _WEAPONS
        inp = _make_input()
        inp.key_just_pressed = MagicMock(side_effect=lambda k: k == "f")
        cost = _WEAPONS["pistol"]["energy_cost"]
        e = _make_weapon_entity(cooldown=0.0, energy=cost * 0.5, inp=inp)
        ws = WeaponScript()
        ws.on_tick(e, 0.016)
        if cost > 0:
            e.scene.add.assert_not_called()

    def _get_projectile(self, e):
        from entities.projectile import Projectile
        for c in e.scene.add.call_args_list:
            obj = c.args[0]
            if isinstance(obj, Projectile):
                return obj
        return None

    def test_fire_projectile_has_correct_owner(self):
        from systems.weapons import WeaponScript
        inp = _make_input()
        inp.key_just_pressed = MagicMock(side_effect=lambda k: k == "f")
        e = _make_weapon_entity(cooldown=0.0, energy=1.0, inp=inp)
        e.player_id = 42
        ws = WeaponScript()
        ws.on_tick(e, 0.016)
        proj = self._get_projectile(e)
        assert proj is not None
        assert proj.owner_id == 42

    def test_fire_projectile_weapon_type_matches(self):
        from systems.weapons import WeaponScript
        inp = _make_input()
        inp.key_just_pressed = MagicMock(side_effect=lambda k: k == "f")
        e = _make_weapon_entity(weapon="pistol", cooldown=0.0, energy=1.0, inp=inp)
        ws = WeaponScript()
        ws.on_tick(e, 0.016)
        proj = self._get_projectile(e)
        assert proj is not None
        assert proj.weapon_type == "pistol"

    def test_plasma_fire_sets_temperature(self):
        from systems.weapons import WeaponScript
        inp = _make_input()
        inp.key_just_pressed = MagicMock(side_effect=lambda k: k == "f")
        e = _make_weapon_entity(weapon="plasma", cooldown=0.0, energy=1.0, inp=inp)
        ws = WeaponScript()
        ws.on_tick(e, 0.016)
        proj = self._get_projectile(e)
        assert proj is not None
        assert proj.temperature > 0.0

    def test_fire_projectile_positioned_near_entity(self):
        from systems.weapons import WeaponScript
        inp = _make_input()
        inp.key_just_pressed = MagicMock(side_effect=lambda k: k == "f")
        e = _make_weapon_entity(cooldown=0.0, energy=1.0, inp=inp)
        e.position = (50.0, 100.0)
        ws = WeaponScript()
        ws.on_tick(e, 0.016)
        proj = self._get_projectile(e)
        assert proj is not None
        assert abs(proj.position[0] - 50.0) < 100


# =============================================================================
# QualityManager — init
# =============================================================================

class TestQualityManagerInit:
    def test_init_no_crash(self):
        from systems.quality_manager import QualityManager
        qm = QualityManager()
        assert qm is not None

    def test_init_with_particle_system(self):
        from systems.quality_manager import QualityManager
        ps = MagicMock()
        qm = QualityManager(particle_system=ps)
        assert qm._particles is ps

    def test_init_with_deform_budget(self):
        from systems.quality_manager import QualityManager
        db = MagicMock()
        qm = QualityManager(deform_budget=db)
        assert qm._deform_budget is db

    def test_initial_tier_index_zero(self):
        from systems.quality_manager import QualityManager
        qm = QualityManager()
        assert qm._tier_idx == 0

    def test_initial_downgrade_streak_zero(self):
        from systems.quality_manager import QualityManager
        qm = QualityManager()
        assert qm._downgrade_streak == 0

    def test_initial_upgrade_streak_zero(self):
        from systems.quality_manager import QualityManager
        qm = QualityManager()
        assert qm._upgrade_streak == 0

    def test_current_tier_label_returns_string(self):
        from systems.quality_manager import QualityManager
        qm = QualityManager()
        label = qm.current_tier_label
        assert isinstance(label, str)

    def test_target_ms_from_fps(self):
        from systems.quality_manager import QualityManager
        qm = QualityManager(target_fps=60.0)
        assert qm._target_ms == pytest.approx(1000.0 / 60.0)

    def test_particle_system_receives_initial_cap(self):
        from systems.quality_manager import QualityManager, _TIERS
        if not _TIERS:
            pytest.skip("AdaptiveQualityController not available")
        ps = MagicMock()
        qm = QualityManager(particle_system=ps)
        ps.set_max_particles.assert_called()


# =============================================================================
# QualityManager — tick behavior
# =============================================================================

class TestQualityManagerTick:
    def test_tick_no_crash(self):
        from systems.quality_manager import QualityManager
        qm = QualityManager()
        qm.tick(0.016)

    def test_tick_without_tiers_no_crash(self):
        from systems.quality_manager import QualityManager
        qm = QualityManager()
        for _ in range(10):
            qm.tick(0.016)

    def test_tick_appends_frame_times(self):
        from systems.quality_manager import QualityManager
        qm = QualityManager()
        qm.tick(0.016)
        assert len(qm._frame_times) == 1

    def test_tick_caps_frame_time(self):
        from systems.quality_manager import QualityManager, _FRAME_TIME_CAP_MS
        qm = QualityManager()
        qm.tick(1.0)  # 1000ms — way over cap
        assert qm._frame_times[-1] <= _FRAME_TIME_CAP_MS

    def test_bad_frames_trigger_downgrade(self):
        from systems.quality_manager import QualityManager, _TIERS, _DOWNGRADE_FRAMES
        if not _TIERS:
            pytest.skip("AdaptiveQualityController not available")
        qm = QualityManager(target_fps=60.0)
        initial_idx = qm._tier_idx
        # 7 very bad frames (50ms each) → rolling avg >> target, triggers downgrade
        for _ in range(7):
            qm.tick(0.050)
        if initial_idx < len(_TIERS) - 1:
            assert qm._tier_idx > initial_idx

    def test_try_upgrade_reduces_tier_idx(self):
        from systems.quality_manager import QualityManager, _TIERS
        if len(_TIERS) < 2:
            pytest.skip("Need at least 2 tiers")
        qm = QualityManager(target_fps=60.0)
        qm._tier_idx = 1  # simulate being at medium quality
        qm._try_upgrade()
        assert qm._tier_idx == 0

    def test_neutral_frames_no_streak_change(self):
        from systems.quality_manager import QualityManager
        qm = QualityManager(target_fps=60.0)
        # Feed 10 frames of neutral dt (neither clearly bad nor clearly good)
        # 16ms is neither > 18.3ms nor < 14.17ms at 60fps
        for _ in range(10):
            qm.tick(0.016)
        # Streaks should remain 0 after neutralizing
        assert qm._downgrade_streak == 0
        assert qm._upgrade_streak == 0

    def test_downgrade_notifies_particle_system(self):
        from systems.quality_manager import QualityManager, _TIERS
        if len(_TIERS) < 2:
            pytest.skip("Need at least 2 tiers")
        ps = MagicMock()
        qm = QualityManager(particle_system=ps, target_fps=60.0)
        ps.reset_mock()
        for _ in range(7):
            qm.tick(0.050)
        if qm._tier_idx > 0:
            ps.set_max_particles.assert_called()

    def test_current_tier_label_after_init(self):
        from systems.quality_manager import QualityManager, _TIERS
        qm = QualityManager()
        if _TIERS:
            # Should be "high" (first tier)
            assert qm.current_tier_label == "high"
        else:
            assert qm.current_tier_label == "unknown"


# =============================================================================
# QualityManager — _apply_tier
# =============================================================================

class TestQualityManagerApplyTier:
    def test_apply_tier_calls_set_max_particles(self):
        from systems.quality_manager import QualityManager, _TIERS
        if not _TIERS:
            pytest.skip("AdaptiveQualityController not available")
        ps = MagicMock()
        qm = QualityManager(particle_system=ps)
        call_count = ps.set_max_particles.call_count
        qm._apply_tier(_TIERS[0])
        assert ps.set_max_particles.call_count > call_count

    def test_apply_tier_calls_deform_budget(self):
        from systems.quality_manager import QualityManager, _TIERS
        if not _TIERS:
            pytest.skip("AdaptiveQualityController not available")
        db = MagicMock()
        qm = QualityManager(deform_budget=db)
        db.reset_mock()
        qm._apply_tier(_TIERS[0])
        db.allocate_budget.assert_called()

    def test_apply_tier_no_particle_system_no_crash(self):
        from systems.quality_manager import QualityManager, _TIERS
        if not _TIERS:
            pytest.skip("AdaptiveQualityController not available")
        qm = QualityManager()
        qm._apply_tier(_TIERS[0])

    def test_try_downgrade_increments_tier_idx(self):
        from systems.quality_manager import QualityManager, _TIERS
        if len(_TIERS) < 2:
            pytest.skip("Need at least 2 tiers")
        qm = QualityManager()
        initial = qm._tier_idx
        qm._try_downgrade()
        assert qm._tier_idx == initial + 1

    def test_try_downgrade_at_lowest_no_crash(self):
        from systems.quality_manager import QualityManager, _TIERS
        if not _TIERS:
            pytest.skip("AdaptiveQualityController not available")
        qm = QualityManager()
        qm._tier_idx = len(_TIERS) - 1
        qm._try_downgrade()  # already at lowest — no change
        assert qm._tier_idx == len(_TIERS) - 1

    def test_try_upgrade_decrements_tier_idx(self):
        from systems.quality_manager import QualityManager, _TIERS
        if len(_TIERS) < 2:
            pytest.skip("Need at least 2 tiers")
        qm = QualityManager()
        qm._tier_idx = 1
        qm._try_upgrade()
        assert qm._tier_idx == 0

    def test_try_upgrade_at_highest_no_crash(self):
        from systems.quality_manager import QualityManager, _TIERS
        if not _TIERS:
            pytest.skip("AdaptiveQualityController not available")
        qm = QualityManager()
        qm._tier_idx = 0
        qm._try_upgrade()  # already at best — no change
        assert qm._tier_idx == 0
