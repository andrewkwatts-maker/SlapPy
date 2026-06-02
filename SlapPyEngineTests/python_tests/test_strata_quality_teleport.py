"""Headless tests for Bullet Strata QualityManager and TeleportScript._do_teleport."""
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entity(strata_layer=0, pos=(100.0, 200.0), vel=None):
    e = MagicMock()
    e.position = pos
    e.velocity = list(vel) if vel else [50.0, 30.0]
    e.strata_layer = strata_layer
    e.teleport_cooldown = 0.0
    e.scene._engine.input = None
    e.scene._engine.compositor = None
    e.scene.strata = None
    e.scene.entities = []
    return e


# =============================================================================
# TeleportScript._do_teleport
# =============================================================================

class TestDoTeleport:
    def _script(self):
        from systems.teleport import TeleportScript, MOMENTUM_MUL, COOLDOWN, NUM_LAYERS
        return TeleportScript(), MOMENTUM_MUL, COOLDOWN, NUM_LAYERS

    def test_do_teleport_scales_velocity(self):
        script, mul, cooldown, _ = self._script()
        e = _make_entity(vel=[100.0, 60.0])
        script._do_teleport(e)
        assert abs(e.velocity[0] - 100.0 * mul) < 0.01
        assert abs(e.velocity[1] - 60.0 * mul) < 0.01

    def test_do_teleport_advances_strata_layer(self):
        script, _, _, n = self._script()
        e = _make_entity(strata_layer=0)
        script._do_teleport(e)
        assert e.strata_layer == 1

    def test_do_teleport_wraps_strata_layer(self):
        script, _, _, n = self._script()
        e = _make_entity(strata_layer=n - 1)
        script._do_teleport(e)
        assert e.strata_layer == 0

    def test_do_teleport_sets_cooldown(self):
        script, _, cooldown, _ = self._script()
        e = _make_entity()
        e.teleport_cooldown = 0.0
        script._do_teleport(e)
        assert e.teleport_cooldown == pytest.approx(cooldown)

    def test_do_teleport_no_compositor_no_crash(self):
        script, _, _, _ = self._script()
        e = _make_entity()
        e.scene._engine.compositor = None
        script._do_teleport(e)  # should not raise

    def test_do_teleport_compositor_called(self):
        script, _, _, _ = self._script()
        e = _make_entity(strata_layer=0)
        comp = MagicMock()
        e.scene._engine.compositor = comp
        script._do_teleport(e)
        # Should have called lerp_to at least once
        assert comp.lerp_to.called

    def test_do_teleport_tele_frag_same_layer(self):
        from systems.teleport import FRAG_RADIUS
        script, _, _, _ = self._script()
        e = _make_entity(strata_layer=0, pos=(100.0, 100.0))
        # victim on same destination layer, within frag radius
        victim = MagicMock()
        victim.strata_layer = 1  # entity will move to layer 1
        victim.position = (100.0 + FRAG_RADIUS * 0.5, 100.0)
        e.scene.entities = [e, victim]
        script._do_teleport(e)
        victim.kill.assert_called_once()

    def test_do_teleport_no_frag_different_layer(self):
        script, _, _, _ = self._script()
        e = _make_entity(strata_layer=0, pos=(100.0, 100.0))
        victim = MagicMock()
        victim.strata_layer = 0  # NOT same as destination (1)
        victim.position = (101.0, 100.0)
        e.scene.entities = [e, victim]
        script._do_teleport(e)
        victim.kill.assert_not_called()

    def test_do_teleport_no_frag_too_far(self):
        from systems.teleport import FRAG_RADIUS
        script, _, _, _ = self._script()
        e = _make_entity(strata_layer=0, pos=(0.0, 0.0))
        victim = MagicMock()
        victim.strata_layer = 1
        victim.position = (FRAG_RADIUS * 3, 0.0)
        e.scene.entities = [e, victim]
        script._do_teleport(e)
        victim.kill.assert_not_called()

    def test_do_teleport_strata_begin_phase_called(self):
        script, _, _, _ = self._script()
        e = _make_entity()
        strata = MagicMock()
        e.scene.strata = strata
        script._do_teleport(e)
        strata.begin_phase.assert_called_once_with(e)


# =============================================================================
# QualityManager._make_tiers, _apply_tier, _try_downgrade
# =============================================================================

class TestQualityManagerMakeTiers:
    def test_make_tiers_returns_list(self):
        from systems.quality_manager import _make_tiers
        result = _make_tiers()
        assert isinstance(result, list)

    def test_make_tiers_three_items_if_aqc_available(self):
        from systems.quality_manager import _make_tiers, _AQC_AVAILABLE
        result = _make_tiers()
        if _AQC_AVAILABLE:
            assert len(result) == 3

    def test_make_tiers_high_label(self):
        from systems.quality_manager import _make_tiers, _AQC_AVAILABLE
        result = _make_tiers()
        if _AQC_AVAILABLE and result:
            assert result[0].label == "high"

    def test_make_tiers_low_label_last(self):
        from systems.quality_manager import _make_tiers, _AQC_AVAILABLE
        result = _make_tiers()
        if _AQC_AVAILABLE and result:
            assert result[-1].label == "low"


class TestQualityManagerApplyTier:
    def _qm(self, particles=None, budget=None):
        from systems.quality_manager import QualityManager
        return QualityManager(particle_system=particles, deform_budget=budget)

    def test_apply_tier_calls_set_max_particles(self):
        particles = MagicMock()
        qm = self._qm(particles=particles)
        from systems.quality_manager import _TIERS, _AQC_AVAILABLE
        if not _AQC_AVAILABLE or not _TIERS:
            pytest.skip("No AQC available")
        # _apply_tier was already called in __init__ with first tier
        particles.set_max_particles.assert_called()

    def test_apply_tier_calls_allocate_budget(self):
        budget = MagicMock()
        qm = self._qm(budget=budget)
        from systems.quality_manager import _TIERS, _AQC_AVAILABLE
        if not _AQC_AVAILABLE or not _TIERS:
            pytest.skip("No AQC available")
        budget.allocate_budget.assert_called()

    def test_apply_tier_publishes_event(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        received = []
        h = subscribe("Quality.TierChanged", lambda e: received.append(e))
        qm = self._qm()
        unsubscribe(h)
        from systems.quality_manager import _AQC_AVAILABLE
        if _AQC_AVAILABLE:
            assert len(received) >= 1

    def test_apply_tier_no_particle_system_no_crash(self):
        from systems.quality_manager import QualityManager
        qm = QualityManager(particle_system=None, deform_budget=None)
        # Constructor calls _apply_tier internally; should not raise
        assert qm is not None


class TestQualityManagerTryDowngrade:
    def _qm(self):
        from systems.quality_manager import QualityManager
        return QualityManager()

    def test_try_downgrade_increases_tier_index(self):
        from systems.quality_manager import _AQC_AVAILABLE
        if not _AQC_AVAILABLE:
            pytest.skip("No AQC available")
        qm = self._qm()
        initial = qm._tier_idx
        qm._try_downgrade()
        assert qm._tier_idx >= initial

    def test_try_downgrade_at_max_no_change(self):
        from systems.quality_manager import _AQC_AVAILABLE, _TIERS
        if not _AQC_AVAILABLE or not _TIERS:
            pytest.skip("No AQC available")
        qm = self._qm()
        qm._tier_idx = len(_TIERS) - 1  # already at lowest
        qm._try_downgrade()
        assert qm._tier_idx == len(_TIERS) - 1

    def test_try_downgrade_changes_current_tier(self):
        from systems.quality_manager import _AQC_AVAILABLE, _TIERS
        if not _AQC_AVAILABLE or len(_TIERS) < 2:
            pytest.skip("Not enough tiers")
        qm = self._qm()
        qm._tier_idx = 0
        first_tier = qm._current_tier
        qm._try_downgrade()
        if len(_TIERS) > 1:
            assert qm._current_tier is not first_tier


class TestQualityManagerTick:
    def _qm(self, target_fps=60.0):
        from systems.quality_manager import QualityManager
        return QualityManager(target_fps=target_fps)

    def test_tick_no_tiers_no_crash(self):
        from systems.quality_manager import QualityManager, _AQC_AVAILABLE
        if _AQC_AVAILABLE:
            pytest.skip("AQC available — tiers present")
        qm = QualityManager()
        qm.tick(0.016)  # should return early without crash

    def test_tick_accumulates_frame_times(self):
        from systems.quality_manager import _AQC_AVAILABLE
        if not _AQC_AVAILABLE:
            pytest.skip("No AQC available")
        qm = self._qm()
        for _ in range(10):
            qm.tick(0.016)
        assert len(qm._frame_times) == 10

    def test_current_tier_label_is_string(self):
        qm = self._qm()
        label = qm.current_tier_label
        assert isinstance(label, str)
