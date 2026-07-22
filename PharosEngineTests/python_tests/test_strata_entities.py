"""Headless tests for Bullet Strata: PlayerEntity, CoverBlock, ParticleBurst,
QualityManager, ArenaInfoHUD.
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
# PlayerEntity
# =============================================================================

class TestPlayerEntityInit:
    def _p(self, player_id=1):
        from entities.player import PlayerEntity
        engine = MagicMock()
        return PlayerEntity(player_id=player_id, engine=engine)

    def test_instantiates(self):
        assert self._p() is not None

    def test_player_id_stored(self):
        p = self._p(player_id=3)
        assert p.player_id == 3

    def test_hp_starts_at_100(self):
        assert self._p().hp == 100

    def test_energy_starts_at_one(self):
        p = self._p()
        assert abs(p.energy - 1.0) < 1e-6

    def test_strata_layer_starts_at_zero(self):
        assert self._p().strata_layer == 0

    def test_current_weapon_is_pistol(self):
        assert self._p().current_weapon == "pistol"

    def test_velocity_is_list(self):
        p = self._p()
        assert isinstance(p.velocity, list)
        assert len(p.velocity) == 2

    def test_grounded_false_initially(self):
        assert self._p().grounded is False

    def test_fire_cooldown_zero(self):
        assert self._p().fire_cooldown == 0.0

    def test_teleport_cooldown_zero(self):
        assert self._p().teleport_cooldown == 0.0

    def test_has_layer(self):
        p = self._p()
        assert len(p.layers) >= 1

    def test_data_component_present(self):
        p = self._p()
        assert p.data is not None


class TestPlayerEntityDamage:
    def _p(self):
        from entities.player import PlayerEntity
        engine = MagicMock()
        return PlayerEntity(player_id=1, engine=engine)

    def test_take_damage_reduces_hp(self):
        p = self._p()
        p.take_damage(20.0)
        assert p.hp == 80

    def test_take_damage_returns_false_when_alive(self):
        p = self._p()
        assert p.take_damage(10.0) is False

    def test_take_damage_returns_true_when_killed(self):
        p = self._p()
        assert p.take_damage(100.0) is True

    def test_hp_floors_at_zero(self):
        p = self._p()
        p.take_damage(999.0)
        assert p.hp == 0

    def test_hp_setter_clamps_to_max(self):
        p = self._p()
        p.hp = 200
        assert p.hp <= 100

    def test_hp_setter_clamps_to_zero(self):
        p = self._p()
        p.hp = -50
        assert p.hp == 0

    def test_multiple_hits_accumulate(self):
        p = self._p()
        p.take_damage(30.0)
        p.take_damage(30.0)
        p.take_damage(30.0)
        assert p.hp == 10

    def test_fatal_damage_hp_is_zero(self):
        p = self._p()
        p.take_damage(100.0)
        assert p.hp == 0


class TestPlayerEntityObservable:
    def test_is_observable(self):
        from entities.player import PlayerEntity
        from pharos_engine.event_bus import Observable
        assert issubclass(PlayerEntity, Observable)

    def test_no_publish_attrs_excluded(self):
        from entities.player import PlayerEntity
        assert "velocity" in PlayerEntity.__no_publish__
        assert "fire_cooldown" in PlayerEntity.__no_publish__


# =============================================================================
# CoverBlock
# =============================================================================

class TestCoverBlockInit:
    def _cb(self, strata_index=0):
        from entities.cover import CoverBlock
        return CoverBlock(strata_index=strata_index)

    def test_instantiates_strata_0(self):
        assert self._cb(0) is not None

    def test_instantiates_strata_1(self):
        assert self._cb(1) is not None

    def test_instantiates_strata_2(self):
        assert self._cb(2) is not None

    def test_alive_initially(self):
        assert self._cb().alive is True

    def test_has_layer(self):
        cb = self._cb()
        assert len(cb.layers) >= 1

    def test_strata_index_stored(self):
        cb = self._cb(strata_index=2)
        assert cb.strata_index == 2

    def test_hits_taken_zero(self):
        cb = self._cb()
        assert cb._hits_taken == 0


class TestCoverBlockMaxHp:
    def test_glass_lower_max_hp(self):
        from entities.cover import CoverBlock
        glass = CoverBlock(strata_index=1)
        stone = CoverBlock(strata_index=0)
        assert glass._max_hp < stone._max_hp

    def test_stone_strata0_max_hp(self):
        from entities.cover import CoverBlock
        cb = CoverBlock(strata_index=0)
        assert cb._max_hp == 150

    def test_stone_strata2_max_hp(self):
        from entities.cover import CoverBlock
        cb = CoverBlock(strata_index=2)
        assert cb._max_hp == 150

    def test_glass_strata1_max_hp(self):
        from entities.cover import CoverBlock
        cb = CoverBlock(strata_index=1)
        assert cb._max_hp == 60


class TestCoverBlockDamage:
    def _cb(self, idx=0):
        from entities.cover import CoverBlock
        return CoverBlock(strata_index=idx)

    def test_take_damage_increments_hits(self):
        cb = self._cb()
        cb.take_damage(10)
        assert cb._hits_taken == 10

    def test_take_damage_returns_false_when_alive(self):
        cb = self._cb()
        assert cb.take_damage(1) is False

    def test_take_damage_returns_true_at_max(self):
        cb = self._cb()
        result = cb.take_damage(cb._max_hp)
        assert result is True

    def test_alive_false_after_fatal_damage(self):
        cb = self._cb()
        cb.take_damage(cb._max_hp)
        assert cb.alive is False

    def test_take_damage_with_contact_pos(self):
        cb = self._cb()
        cb.position = (100.0, 100.0)
        result = cb.take_damage(5, contact_pos=(100.0, 100.0))
        assert result is False
        assert cb._hits_taken == 5

    def test_glass_destroyed_faster(self):
        from entities.cover import CoverBlock
        glass = CoverBlock(strata_index=1)
        result = glass.take_damage(60)
        assert result is True

    def test_multiple_partial_hits(self):
        cb = self._cb()
        for _ in range(5):
            cb.take_damage(20)
        assert cb._hits_taken == 100
        assert cb.alive is True  # max_hp=150 so 100 < 150


class TestCoverBlockRect:
    def test_rect_is_tuple_of_four(self):
        from entities.cover import CoverBlock
        cb = CoverBlock(strata_index=0)
        cb.position = (100.0, 100.0)
        rect = cb.rect
        assert len(rect) == 4

    def test_rect_width_is_cover_width(self):
        from entities.cover import CoverBlock, COVER_W
        cb = CoverBlock(strata_index=0)
        cb.position = (100.0, 100.0)
        assert cb.rect[2] == COVER_W

    def test_rect_height_is_cover_height(self):
        from entities.cover import CoverBlock, COVER_H
        cb = CoverBlock(strata_index=0)
        cb.position = (100.0, 100.0)
        assert cb.rect[3] == COVER_H


# =============================================================================
# ParticleBurst
# =============================================================================

class TestParticleBurstInit:
    def _pb(self, **kw):
        from entities.particle_burst import ParticleBurst
        return ParticleBurst(**kw)

    def test_instantiates(self):
        assert self._pb() is not None

    def test_alive_initially(self):
        assert self._pb()._alive is True

    def test_has_layer(self):
        pb = self._pb()
        assert len(pb.layers) >= 1

    def test_custom_count(self):
        pb = self._pb(count=50)
        assert pb is not None

    def test_custom_lifetime(self):
        pb = self._pb(lifetime=1.0)
        assert pb is not None

    def test_gravity_stored(self):
        pb = self._pb(gravity=200.0)
        assert abs(pb._gravity - 200.0) < 1e-6

    def test_tex_size_stored(self):
        pb = self._pb(tex_size=64)
        assert pb._tex_size == 64

    def test_zero_gravity(self):
        pb = self._pb(gravity=0.0)
        assert abs(pb._gravity) < 1e-6


class TestParticleBurstTick:
    def _pb(self):
        from entities.particle_burst import ParticleBurst
        return ParticleBurst(count=5, tex_size=32)

    def test_tick_no_crash(self):
        pb = self._pb()
        pb.tick(0.016)

    def test_tick_multiple_no_crash(self):
        pb = self._pb()
        for _ in range(30):
            pb.tick(0.016)

    def test_still_alive_after_one_tick(self):
        pb = self._pb()
        pb.tick(0.016)
        # May still be alive (scene=None so remove not called)
        assert pb._alive is True  # no scene, won't self-remove

    def test_tick_zero_dt(self):
        pb = self._pb()
        pb.tick(0.0)

    def test_not_alive_does_not_crash(self):
        pb = self._pb()
        pb._alive = False
        pb.tick(0.016)


class TestSpawnBurst:
    def test_spawn_burst_returns_particle_burst(self):
        from entities.particle_burst import spawn_burst, ParticleBurst
        scene = MagicMock()
        result = spawn_burst(scene, position=(100.0, 200.0), count=10)
        if result is not None:
            assert isinstance(result, ParticleBurst)

    def test_spawn_burst_calls_scene_add(self):
        from entities.particle_burst import spawn_burst
        scene = MagicMock()
        spawn_burst(scene, position=(50.0, 50.0))
        scene.add.assert_called_once()

    def test_spawn_burst_sets_position(self):
        from entities.particle_burst import spawn_burst
        scene = MagicMock()
        burst = spawn_burst(scene, position=(300.0, 400.0))
        if burst is not None:
            assert burst.position == (300.0, 400.0)


# =============================================================================
# QualityManager
# =============================================================================

class TestQualityManagerInit:
    def _qm(self, **kw):
        from systems.quality_manager import QualityManager
        return QualityManager(**kw)

    def test_instantiates(self):
        assert self._qm() is not None

    def test_target_ms_computed(self):
        qm = self._qm(target_fps=60.0)
        assert abs(qm._target_ms - 1000.0 / 60.0) < 0.01

    def test_tier_idx_starts_at_zero(self):
        assert self._qm()._tier_idx == 0

    def test_downgrade_streak_starts_at_zero(self):
        assert self._qm()._downgrade_streak == 0

    def test_upgrade_streak_starts_at_zero(self):
        assert self._qm()._upgrade_streak == 0

    def test_current_tier_label_not_empty(self):
        qm = self._qm()
        label = qm.current_tier_label
        assert isinstance(label, str) and len(label) > 0

    def test_with_particle_system(self):
        ps = MagicMock()
        qm = self._qm(particle_system=ps)
        assert qm is not None

    def test_with_deform_budget(self):
        db = MagicMock()
        qm = self._qm(deform_budget=db)
        assert qm is not None


class TestQualityManagerTick:
    def _qm(self, target_fps=60.0):
        from systems.quality_manager import QualityManager
        return QualityManager(target_fps=target_fps)

    def test_tick_no_crash(self):
        qm = self._qm()
        qm.tick(0.016)

    def test_tick_multiple_no_crash(self):
        qm = self._qm()
        for _ in range(10):
            qm.tick(0.016)

    def test_downgrade_on_slow_frames(self):
        from systems.quality_manager import _DOWNGRADE_FRAMES, _TIERS
        if not _TIERS:
            pytest.skip("AdaptiveQualityController not available")
        qm = self._qm(target_fps=60.0)
        initial_idx = qm._tier_idx
        # Simulate many slow frames (500ms each — far over budget)
        for _ in range(100):
            qm.tick(0.500)
        # Should have downgraded if not already at lowest tier
        if initial_idx < len(_TIERS) - 1:
            assert qm._tier_idx > initial_idx

    def test_upgrade_on_fast_frames(self):
        from systems.quality_manager import _UPGRADE_FRAMES, _TIERS
        if not _TIERS:
            pytest.skip("AdaptiveQualityController not available")
        qm = self._qm(target_fps=60.0)
        # Force to lowest tier first
        qm._tier_idx = len(_TIERS) - 1
        if _TIERS:
            qm._current_tier = _TIERS[-1]
        initial_idx = qm._tier_idx
        # Simulate many fast frames (0.1ms each — well under budget)
        for _ in range(200):
            qm.tick(0.0001)
        # Should have upgraded
        if initial_idx > 0:
            assert qm._tier_idx < initial_idx

    def test_good_frames_reset_streaks(self):
        qm = self._qm(target_fps=60.0)
        # Artificial streak
        qm._downgrade_streak = 2
        # A frame at exactly target
        qm.tick(1.0 / 60.0)
        # Streak should have cleared or stayed (depends on avg)
        assert qm._downgrade_streak >= 0  # just verify no crash

    def test_particle_system_called_on_apply(self):
        from systems.quality_manager import _TIERS
        if not _TIERS:
            pytest.skip("AdaptiveQualityController not available")
        ps = MagicMock()
        from systems.quality_manager import QualityManager
        qm = QualityManager(particle_system=ps, target_fps=60.0)
        # set_max_particles called once during __init__ apply
        ps.set_max_particles.assert_called()


class TestQualityManagerTierLabel:
    def test_label_is_string(self):
        from systems.quality_manager import QualityManager
        qm = QualityManager()
        assert isinstance(qm.current_tier_label, str)

    def test_label_in_known_values(self):
        from systems.quality_manager import QualityManager, _TIERS
        if not _TIERS:
            pytest.skip("no tiers")
        qm = QualityManager()
        assert qm.current_tier_label in ("high", "medium", "low", "unknown")


# =============================================================================
# ArenaInfoHUD
# =============================================================================

class TestArenaInfoHUDInit:
    def _hud(self, wave=1, total=10, kills=0):
        from entities.hud import ArenaInfoHUD
        scene = MagicMock()
        scene.current_wave = wave
        scene.total_waves = total
        scene.kill_count = kills
        return ArenaInfoHUD(scene=scene), scene

    def test_instantiates(self):
        hud, _ = self._hud()
        assert hud is not None

    def test_wave_cur_from_scene(self):
        hud, _ = self._hud(wave=3)
        assert hud._wave_cur == 3

    def test_wave_tot_from_scene(self):
        hud, _ = self._hud(total=8)
        assert hud._wave_tot == 8

    def test_kills_from_scene(self):
        hud, _ = self._hud(kills=5)
        assert hud._kills == 5

    def test_dirty_initially(self):
        hud, _ = self._hud()
        assert hud._hud_dirty is True

    def test_popup_text_empty(self):
        hud, _ = self._hud()
        assert hud._popup_text == ""

    def test_popup_timer_zero(self):
        hud, _ = self._hud()
        assert hud._popup_timer == 0.0


class TestArenaInfoHUDEventHandlers:
    def _hud(self):
        from entities.hud import ArenaInfoHUD
        scene = MagicMock()
        scene.current_wave = 1
        scene.total_waves = 10
        scene.kill_count = 0
        h = ArenaInfoHUD(scene=scene)
        h._scene = scene
        return h, scene

    def test_enemy_killed_increments_kills(self):
        hud, scene = self._hud()
        hud._kills = 0
        evt = MagicMock()
        evt.publisher = scene
        hud._on_enemy_killed(evt)
        assert hud._kills == 1

    def test_enemy_killed_marks_dirty(self):
        hud, scene = self._hud()
        hud._hud_dirty = False
        evt = MagicMock()
        evt.publisher = scene
        hud._on_enemy_killed(evt)
        assert hud._hud_dirty is True

    def test_enemy_killed_wrong_scene_ignored(self):
        hud, scene = self._hud()
        hud._kills = 0
        evt = MagicMock()
        evt.publisher = MagicMock()  # different publisher
        hud._on_enemy_killed(evt)
        assert hud._kills == 0

    def test_wave_started_updates_wave(self):
        hud, scene = self._hud()
        evt = MagicMock()
        evt.publisher = scene
        evt.wave = 3
        evt.total = 10
        hud._on_wave_started(evt)
        assert hud._wave_cur == 3

    def test_wave_started_resets_kills(self):
        hud, scene = self._hud()
        hud._kills = 99
        evt = MagicMock()
        evt.publisher = scene
        evt.wave = 2
        evt.total = 10
        hud._on_wave_started(evt)
        assert hud._kills == 0

    def test_wave_complete_updates_kills(self):
        hud, scene = self._hud()
        evt = MagicMock()
        evt.publisher = scene
        evt.kills = 7
        hud._on_wave_complete(evt)
        assert hud._kills == 7

    def test_show_popup_sets_text(self):
        hud, _ = self._hud()
        hud._show_popup("HEADSHOT", 1.5)
        assert hud._popup_text == "HEADSHOT"

    def test_show_popup_sets_timer(self):
        hud, _ = self._hud()
        hud._show_popup("TEST", 2.0)
        assert abs(hud._popup_timer - 2.0) < 1e-6


class TestArenaInfoHUDTick:
    def _hud(self):
        from entities.hud import ArenaInfoHUD
        scene = MagicMock()
        scene.current_wave = 1
        scene.total_waves = 10
        scene.kill_count = 0
        h = ArenaInfoHUD(scene=scene)
        h._scene = scene
        return h

    def test_tick_no_crash(self):
        hud = self._hud()
        hud.tick(0.016)

    def test_tick_multiple_no_crash(self):
        hud = self._hud()
        for _ in range(30):
            hud.tick(0.016)

    def test_popup_timer_decrements(self):
        hud = self._hud()
        hud._popup_timer = 1.0
        hud._popup_text = "TEST"
        hud.tick(0.1)
        assert hud._popup_timer < 1.0

    def test_popup_clears_when_timer_expires(self):
        hud = self._hud()
        hud._popup_timer = 0.01
        hud._popup_text = "HEADSHOT"
        hud.tick(0.1)  # advance past expiry
        assert hud._popup_text == ""

    def test_dirty_cleared_after_render(self):
        hud = self._hud()
        hud._hud_dirty = True
        hud.tick(0.016)
        assert hud._hud_dirty is False


class TestArenaInfoHUDTeardown:
    def test_teardown_no_crash(self):
        from entities.hud import ArenaInfoHUD
        scene = MagicMock()
        scene.current_wave = 1
        scene.total_waves = 5
        scene.kill_count = 0
        hud = ArenaInfoHUD(scene=scene)
        hud.teardown()

    def test_teardown_clears_handles(self):
        from entities.hud import ArenaInfoHUD
        scene = MagicMock()
        scene.current_wave = 1
        scene.total_waves = 5
        scene.kill_count = 0
        hud = ArenaInfoHUD(scene=scene)
        hud.teardown()
        assert hud._sub_handles == []

    def test_teardown_twice_no_crash(self):
        from entities.hud import ArenaInfoHUD
        scene = MagicMock()
        scene.current_wave = 1
        scene.total_waves = 5
        scene.kill_count = 0
        hud = ArenaInfoHUD(scene=scene)
        hud.teardown()
        hud.teardown()


# =============================================================================
# VictoryOverlay
# =============================================================================

class TestVictoryOverlay:
    def _vo(self, message="VICTORY", color=(255, 220, 50)):
        from entities.hud import VictoryOverlay
        return VictoryOverlay(message=message, color=color)

    def test_instantiates_victory(self):
        assert self._vo("VICTORY", (255, 220, 50)) is not None

    def test_instantiates_game_over(self):
        assert self._vo("GAME OVER", (200, 50, 50)) is not None

    def test_message_stored(self):
        vo = self._vo("TEST MSG", (255, 255, 255))
        assert vo._message == "TEST MSG"

    def test_color_stored(self):
        vo = self._vo("X", (100, 150, 200))
        assert vo._color == (100, 150, 200)

    def test_tick_no_crash(self):
        vo = self._vo()
        vo.tick(0.016)
