"""Engine tests for RenderChannelCompositor (non-GPU methods only) — headless."""
from __future__ import annotations
import pytest


class TestRenderPassDefaults:
    def test_default_blend_mode_lerp(self):
        from pharos_engine.render_channel import RenderPass
        rp = RenderPass("my_pass")
        assert rp.blend_mode == "lerp"

    def test_default_blend_alpha_zero(self):
        from pharos_engine.render_channel import RenderPass
        rp = RenderPass("my_pass")
        assert rp.blend_alpha == pytest.approx(0.0)

    def test_default_gain_one(self):
        from pharos_engine.render_channel import RenderPass
        rp = RenderPass("my_pass")
        assert rp.gain == pytest.approx(1.0)

    def test_default_tint_white(self):
        from pharos_engine.render_channel import RenderPass
        rp = RenderPass("my_pass")
        assert rp.tint == (1.0, 1.0, 1.0)


class TestPrebuiltPasses:
    def test_night_vision_pass_exists(self):
        from pharos_engine.render_channel import NightVisionPass
        assert NightVisionPass.name == "night_vision"

    def test_night_vision_green_tint(self):
        from pharos_engine.render_channel import NightVisionPass
        r, g, b = NightVisionPass.tint
        assert g > r and g > b

    def test_thermal_pass_exists(self):
        from pharos_engine.render_channel import ThermalPass
        assert ThermalPass.name == "thermal"


class TestRenderChannelCompositorNonGpu:
    def _make_compositor(self):
        from pharos_engine.render_channel import RenderChannelCompositor
        return RenderChannelCompositor(gpu=None, width=1280, height=720)

    def test_init_empty_passes(self):
        rc = self._make_compositor()
        assert len(rc._passes) == 0

    def test_add_channel_by_string(self):
        from pharos_engine.render_channel import RenderPass
        rc = self._make_compositor()
        rp = rc.add_channel("custom")
        assert isinstance(rp, RenderPass)
        assert "custom" in rc._passes

    def test_add_channel_by_pass(self):
        from pharos_engine.render_channel import RenderChannelCompositor, NightVisionPass
        rc = self._make_compositor()
        rp = rc.add_channel(NightVisionPass)
        assert rp.name == "night_vision"
        assert "night_vision" in rc._passes

    def test_set_mix_clamps_max(self):
        rc = self._make_compositor()
        rc.add_channel("vision")
        rc.set_mix("vision", 2.0)
        assert rc._passes["vision"].blend_alpha == pytest.approx(1.0)

    def test_set_mix_clamps_min(self):
        rc = self._make_compositor()
        rc.add_channel("vision")
        rc.set_mix("vision", -1.0)
        assert rc._passes["vision"].blend_alpha == pytest.approx(0.0)

    def test_set_mix_valid_range(self):
        rc = self._make_compositor()
        rc.add_channel("vision")
        rc.set_mix("vision", 0.7)
        assert rc._passes["vision"].blend_alpha == pytest.approx(0.7)

    def test_set_mix_unknown_channel_no_crash(self):
        rc = self._make_compositor()
        rc.set_mix("nonexistent", 1.0)  # should not raise

    def test_active_passes_empty_when_all_alpha_zero(self):
        rc = self._make_compositor()
        rc.add_channel("vis")
        assert len(rc.active_passes) == 0

    def test_active_passes_includes_nonzero_alpha(self):
        rc = self._make_compositor()
        rc.add_channel("vis")
        rc.set_mix("vis", 0.5)
        assert len(rc.active_passes) == 1

    def test_lerp_to_creates_transition(self):
        rc = self._make_compositor()
        rc.add_channel("thermal")
        rc.lerp_to("thermal", 1.0, duration=0.5)
        assert "thermal" in rc._transitions

    def test_lerp_to_unknown_channel_no_crash(self):
        rc = self._make_compositor()
        rc.lerp_to("ghost", 1.0)  # should not raise

    def test_tick_advances_transition(self):
        rc = self._make_compositor()
        rc.add_channel("thermal")
        rc.lerp_to("thermal", 1.0, duration=0.5)
        rc.tick(0.1)
        assert rc._passes["thermal"].blend_alpha > 0.0

    def test_tick_completes_transition(self):
        rc = self._make_compositor()
        rc.add_channel("thermal")
        rc.lerp_to("thermal", 1.0, duration=0.1)
        rc.tick(1.0)  # large step — should complete
        assert rc._passes["thermal"].blend_alpha == pytest.approx(1.0)
        assert "thermal" not in rc._transitions

    def test_tick_multiple_transitions(self):
        rc = self._make_compositor()
        rc.add_channel("a")
        rc.add_channel("b")
        rc.lerp_to("a", 1.0, duration=0.5)
        rc.lerp_to("b", 0.5, duration=0.5)
        rc.tick(0.1)
        assert rc._passes["a"].blend_alpha > 0.0
        assert rc._passes["b"].blend_alpha > 0.0
