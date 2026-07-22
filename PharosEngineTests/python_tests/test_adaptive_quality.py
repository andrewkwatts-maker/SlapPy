"""Engine tests for AdaptiveQualityController — headless."""
from __future__ import annotations
import pytest


def _make_controller(num_tiers=3, target_fps=60.0, miss_threshold=3, recovery_threshold=5, callback=None):
    from pharos_engine.gpu.adaptive_quality import AdaptiveQualityController, QualityTier
    tiers = [
        QualityTier("high", particles=1000, fog_res=1.0),
        QualityTier("medium", particles=500, fog_res=0.5),
        QualityTier("low", particles=200, fog_res=0.25),
    ][:num_tiers]
    return AdaptiveQualityController(
        tiers=tiers,
        target_fps=target_fps,
        miss_threshold=miss_threshold,
        recovery_threshold=recovery_threshold,
        on_tier_change=callback,
    )


class TestQualityTier:
    def test_init_stores_label(self):
        from pharos_engine.gpu.adaptive_quality import QualityTier
        qt = QualityTier("ultra", particles=2000)
        assert qt.label == "ultra"

    def test_init_stores_params(self):
        from pharos_engine.gpu.adaptive_quality import QualityTier
        qt = QualityTier("medium", fog_res=0.5, particle_cap=500)
        assert qt.params["fog_res"] == pytest.approx(0.5)
        assert qt.params["particle_cap"] == 500

    def test_repr_contains_label(self):
        from pharos_engine.gpu.adaptive_quality import QualityTier
        qt = QualityTier("low")
        assert "low" in repr(qt)


class TestAdaptiveQualityControllerInit:
    def test_empty_tiers_raises(self):
        from pharos_engine.gpu.adaptive_quality import AdaptiveQualityController
        with pytest.raises(ValueError):
            AdaptiveQualityController(tiers=[])

    def test_starts_at_tier_zero(self):
        ctrl = _make_controller()
        assert ctrl.tier_index == 0

    def test_current_tier_is_first(self):
        ctrl = _make_controller()
        assert ctrl.current_tier.label == "high"

    def test_last_frame_ms_zero_initially(self):
        ctrl = _make_controller()
        assert ctrl.last_frame_ms == pytest.approx(0.0)

    def test_frame_count_zero_initially(self):
        ctrl = _make_controller()
        assert ctrl.frame_count == 0


class TestRecordFrame:
    def test_frame_count_increments(self):
        ctrl = _make_controller()
        ctrl.record_frame(10.0)
        assert ctrl.frame_count == 1
        ctrl.record_frame(10.0)
        assert ctrl.frame_count == 2

    def test_last_frame_ms_updates(self):
        ctrl = _make_controller()
        ctrl.record_frame(25.0)
        assert ctrl.last_frame_ms == pytest.approx(25.0)

    def test_budget_miss_reduces_tier_after_threshold(self):
        ctrl = _make_controller(miss_threshold=3, target_fps=60)
        # 60fps → budget = 16.67ms. Feed 3 over-budget frames.
        for _ in range(3):
            ctrl.record_frame(20.0)
        assert ctrl.tier_index == 1

    def test_only_two_consecutive_misses_does_not_reduce(self):
        ctrl = _make_controller(miss_threshold=3, target_fps=60)
        ctrl.record_frame(20.0)
        ctrl.record_frame(20.0)
        assert ctrl.tier_index == 0  # not yet reached threshold

    def test_recovery_restores_tier(self):
        ctrl = _make_controller(miss_threshold=3, recovery_threshold=5, target_fps=60)
        # Reduce to tier 1
        for _ in range(3):
            ctrl.record_frame(20.0)
        assert ctrl.tier_index == 1
        # Now recover: 5 frames under budget
        for _ in range(5):
            ctrl.record_frame(10.0)
        assert ctrl.tier_index == 0

    def test_miss_count_resets_after_under_budget_frame(self):
        ctrl = _make_controller(miss_threshold=3, target_fps=60)
        ctrl.record_frame(20.0)
        ctrl.record_frame(20.0)
        ctrl.record_frame(10.0)  # under budget — resets miss count
        ctrl.record_frame(20.0)
        ctrl.record_frame(20.0)
        # Only 2 consecutive misses → no reduction
        assert ctrl.tier_index == 0

    def test_tier_does_not_go_below_minimum(self):
        ctrl = _make_controller(num_tiers=2, miss_threshold=1, target_fps=60)
        for _ in range(10):
            ctrl.record_frame(100.0)
        assert ctrl.tier_index == 1  # clamped at last tier

    def test_tier_does_not_go_above_maximum(self):
        ctrl = _make_controller(miss_threshold=1, recovery_threshold=1, target_fps=60)
        ctrl.record_frame(100.0)  # reduce
        ctrl.record_frame(1.0)    # recover
        ctrl.record_frame(1.0)    # should stay at 0, not go negative
        assert ctrl.tier_index == 0

    def test_callback_called_on_tier_change(self):
        changes = []
        ctrl = _make_controller(miss_threshold=3, callback=lambda t: changes.append(t.label))
        for _ in range(3):
            ctrl.record_frame(20.0)
        assert len(changes) == 1
        assert changes[0] == "medium"

    def test_callback_not_called_without_change(self):
        changes = []
        ctrl = _make_controller(miss_threshold=3, callback=lambda t: changes.append(t.label))
        ctrl.record_frame(10.0)  # under budget
        assert changes == []


class TestSetTierAndReset:
    def test_set_tier_forces_index(self):
        ctrl = _make_controller()
        ctrl.set_tier(2)
        assert ctrl.tier_index == 2

    def test_set_tier_clamped_to_max(self):
        ctrl = _make_controller()
        ctrl.set_tier(99)
        assert ctrl.tier_index == 2

    def test_set_tier_clamped_to_zero(self):
        ctrl = _make_controller()
        ctrl.set_tier(2)
        ctrl.set_tier(-5)
        assert ctrl.tier_index == 0

    def test_set_tier_fires_callback(self):
        changes = []
        ctrl = _make_controller(callback=lambda t: changes.append(t.label))
        ctrl.set_tier(1)
        assert changes == ["medium"]

    def test_reset_returns_to_tier_zero(self):
        ctrl = _make_controller()
        ctrl.set_tier(2)
        ctrl.reset()
        assert ctrl.tier_index == 0

    def test_reset_clears_counters(self):
        ctrl = _make_controller(miss_threshold=3, target_fps=60)
        ctrl.record_frame(20.0)
        ctrl.record_frame(20.0)
        ctrl.reset()
        ctrl.record_frame(20.0)
        ctrl.record_frame(20.0)
        # After reset, only 2 misses since reset — no reduction
        assert ctrl.tier_index == 0


class TestDebugStr:
    def test_debug_str_is_string(self):
        ctrl = _make_controller()
        ctrl.record_frame(16.0)
        s = ctrl.debug_str()
        assert isinstance(s, str)
        assert "high" in s.lower() or "quality" in s.lower()


class TestCubeArray:
    def test_init_defaults(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray(name="test")
        assert ca.name == "test"
        assert ca.frame_count == 1
        assert ca.current_frame == 0
        assert ca.playing is False

    def test_play_sets_playing(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray()
        ca.play()
        assert ca.playing is True

    def test_pause_clears_playing(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray()
        ca.play()
        ca.pause()
        assert ca.playing is False

    def test_seek_clamps_to_frame_count(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 4
        ca.seek(10)  # beyond max
        assert ca.current_frame == 3

    def test_seek_clamps_to_zero(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 4
        ca.seek(-5)
        assert ca.current_frame == 0

    def test_tick_advances_frame_when_playing(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 4
        ca.fps = 10.0
        ca.play()
        ca.tick(0.15)  # 1.5 frames at 10fps → advances 1
        assert ca.current_frame == 1

    def test_tick_does_not_advance_when_paused(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 4
        ca.fps = 10.0
        ca.tick(1.0)  # paused — should not advance
        assert ca.current_frame == 0

    def test_tick_loops_when_loop_true(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 4
        ca.fps = 10.0
        ca.loop = True
        ca.play()
        ca.tick(0.45)  # 4.5 frames → wraps to 0
        assert ca.current_frame == 0

    def test_tick_stops_at_last_frame_when_not_looping(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 3
        ca.fps = 10.0
        ca.loop = False
        ca.play()
        ca.tick(1.0)  # 10 frames elapsed — clamps to last
        assert ca.current_frame == 2
        assert ca.playing is False

    def test_tick_uses_animation_graph(self):
        from pharos_engine.cube_array import CubeArray
        from pharos_engine.animation.graph import AnimationGraph, AnimState
        ca = CubeArray()
        ca.frame_count = 3
        # Add 3 dummy layers so that min(frame_index, len(layers)-1) = frame_index
        class _FL:
            def tick(self, dt): pass
        ca.layers = [_FL(), _FL(), _FL()]
        g = AnimationGraph()
        g.add_state(AnimState(name="idle", clip_indices=[2], fps=10.0))
        g.set_initial("idle")
        ca.animation_graph = g
        ca.tick(0.016)
        # AnimationGraph drives current_frame from clip_indices[0]=2
        assert ca.current_frame == 2
