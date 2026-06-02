"""Headless pytest tests for fluid_sim.py — pure-Python / no-GPU parts only.

Covers:
  - FluidSimConfig dataclass (defaults and field types)
  - fog_config(), water_config(), smoke_config() factories
  - GlobalFluidSim.__init__ with a MagicMock GPU context
  - GlobalFluidSim.sample_velocity() — None cache and real numpy cache
  - GlobalFluidSim._ping_pong_textures() — both ping states
  - GlobalFluidSim._flip_ping_pong() — toggle behaviour
  - GlobalFluidSim._sim_params_size() — constant 64
  - GlobalFluidSim.dispatch() — early-return when _initialized=False
  - GlobalFluidSim.apply_force() — early-return when _initialized=False
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

# ── Stub out GPU / compute dependencies before any slappyengine import ────────
sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("slappyengine.compute.asset_compute", MagicMock())

import numpy as np
import pytest


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_sim(screen_w: int = 640, screen_h: int = 480, cfg=None):
    """Return a GlobalFluidSim with a MagicMock GPU context."""
    from slappyengine.fluid_sim import GlobalFluidSim
    gpu_ctx = MagicMock()
    gpu_ctx.device = MagicMock()
    return GlobalFluidSim(gpu=gpu_ctx, screen_w=screen_w, screen_h=screen_h, cfg=cfg)


# ─────────────────────────────────────────────────────────────────────────────
#  1. FluidSimConfig — default values
# ─────────────────────────────────────────────────────────────────────────────

class TestFluidSimConfigDefaults:
    """Full coverage of every documented default field value."""

    def test_viscosity_default(self):
        from slappyengine.fluid_sim import FluidSimConfig
        assert FluidSimConfig().viscosity == pytest.approx(0.1)

    def test_diffusion_default(self):
        from slappyengine.fluid_sim import FluidSimConfig
        assert FluidSimConfig().diffusion == pytest.approx(0.02)

    def test_buoyancy_default(self):
        from slappyengine.fluid_sim import FluidSimConfig
        assert FluidSimConfig().buoyancy == pytest.approx(0.0)

    def test_gravity_default(self):
        from slappyengine.fluid_sim import FluidSimConfig
        assert FluidSimConfig().gravity == pytest.approx(0.0)

    def test_density_decay_default(self):
        from slappyengine.fluid_sim import FluidSimConfig
        assert FluidSimConfig().density_decay == pytest.approx(0.995)

    def test_velocity_decay_default(self):
        from slappyengine.fluid_sim import FluidSimConfig
        assert FluidSimConfig().velocity_decay == pytest.approx(0.99)

    def test_pad_pixels_default(self):
        from slappyengine.fluid_sim import FluidSimConfig
        assert FluidSimConfig().pad_pixels == 64

    def test_lod_zones_default(self):
        from slappyengine.fluid_sim import FluidSimConfig
        assert FluidSimConfig().lod_zones == 4

    def test_lod_mode_default(self):
        from slappyengine.fluid_sim import FluidSimConfig
        assert FluidSimConfig().lod_mode == "exp"

    def test_noise_type_default(self):
        from slappyengine.fluid_sim import FluidSimConfig
        assert FluidSimConfig().noise_type == "fbm"

    def test_god_rays_default(self):
        from slappyengine.fluid_sim import FluidSimConfig
        assert FluidSimConfig().god_rays is True

    def test_caustics_default(self):
        from slappyengine.fluid_sim import FluidSimConfig
        assert FluidSimConfig().caustics is False

    def test_render_tint_default_is_3_tuple(self):
        from slappyengine.fluid_sim import FluidSimConfig
        tint = FluidSimConfig().render_tint
        assert len(tint) == 3
        assert all(isinstance(v, float) for v in tint)

    def test_render_tint_default_values(self):
        from slappyengine.fluid_sim import FluidSimConfig
        r, g, b = FluidSimConfig().render_tint
        assert r == pytest.approx(0.8)
        assert g == pytest.approx(0.9)
        assert b == pytest.approx(1.0)

    def test_render_alpha_scale_default(self):
        from slappyengine.fluid_sim import FluidSimConfig
        assert FluidSimConfig().render_alpha_scale == pytest.approx(1.0)

    def test_is_dataclass(self):
        import dataclasses
        from slappyengine.fluid_sim import FluidSimConfig
        assert dataclasses.is_dataclass(FluidSimConfig)

    def test_dataclass_replace(self):
        import dataclasses
        from slappyengine.fluid_sim import FluidSimConfig
        orig = FluidSimConfig()
        updated = dataclasses.replace(orig, viscosity=0.5)
        assert updated.viscosity == pytest.approx(0.5)
        assert orig.viscosity == pytest.approx(0.1)

    def test_equality_same_params(self):
        from slappyengine.fluid_sim import FluidSimConfig
        assert FluidSimConfig() == FluidSimConfig()

    def test_inequality_different_params(self):
        from slappyengine.fluid_sim import FluidSimConfig
        assert FluidSimConfig(viscosity=0.2) != FluidSimConfig(viscosity=0.3)


# ─────────────────────────────────────────────────────────────────────────────
#  2. Factory functions
# ─────────────────────────────────────────────────────────────────────────────

class TestFogConfig:
    def test_returns_fluid_sim_config(self):
        from slappyengine.fluid_sim import fog_config, FluidSimConfig
        assert isinstance(fog_config(), FluidSimConfig)

    def test_viscosity(self):
        from slappyengine.fluid_sim import fog_config
        assert fog_config().viscosity == pytest.approx(0.2)

    def test_diffusion(self):
        from slappyengine.fluid_sim import fog_config
        assert fog_config().diffusion == pytest.approx(0.04)

    def test_density_decay(self):
        from slappyengine.fluid_sim import fog_config
        assert fog_config().density_decay == pytest.approx(0.998)

    def test_returns_new_object_each_call(self):
        from slappyengine.fluid_sim import fog_config
        assert fog_config() is not fog_config()


class TestWaterConfig:
    def test_returns_fluid_sim_config(self):
        from slappyengine.fluid_sim import water_config, FluidSimConfig
        assert isinstance(water_config(), FluidSimConfig)

    def test_gravity(self):
        from slappyengine.fluid_sim import water_config
        assert water_config().gravity == pytest.approx(9.8)

    def test_density_decay_is_one(self):
        from slappyengine.fluid_sim import water_config
        assert water_config().density_decay == pytest.approx(1.0)

    def test_buoyancy_is_zero(self):
        from slappyengine.fluid_sim import water_config
        assert water_config().buoyancy == pytest.approx(0.0)


class TestSmokeConfig:
    def test_returns_fluid_sim_config(self):
        from slappyengine.fluid_sim import smoke_config, FluidSimConfig
        assert isinstance(smoke_config(), FluidSimConfig)

    def test_buoyancy(self):
        from slappyengine.fluid_sim import smoke_config
        assert smoke_config().buoyancy == pytest.approx(0.15)

    def test_density_decay_less_than_one(self):
        from slappyengine.fluid_sim import smoke_config
        assert smoke_config().density_decay < 1.0

    def test_smoke_render_tint_grey(self):
        from slappyengine.fluid_sim import smoke_config
        r, g, b = smoke_config().render_tint
        assert abs(r - g) < 0.05
        assert abs(g - b) < 0.05


# ─────────────────────────────────────────────────────────────────────────────
#  3. GlobalFluidSim.__init__ with MagicMock GPU
# ─────────────────────────────────────────────────────────────────────────────

class TestGlobalFluidSimInit:
    def test_stores_screen_w(self):
        sim = _make_sim(screen_w=800, screen_h=600)
        assert sim._screen_w == 800

    def test_stores_screen_h(self):
        sim = _make_sim(screen_w=800, screen_h=600)
        assert sim._screen_h == 600

    def test_ping_starts_true(self):
        sim = _make_sim()
        assert sim._ping is True

    def test_initialized_starts_false(self):
        sim = _make_sim()
        assert sim._initialized is False

    def test_cfg_set_to_default_when_none_passed(self):
        from slappyengine.fluid_sim import FluidSimConfig
        sim = _make_sim()
        assert isinstance(sim.cfg, FluidSimConfig)
        assert sim.cfg.viscosity == pytest.approx(0.1)

    def test_cfg_uses_passed_config(self):
        from slappyengine.fluid_sim import FluidSimConfig
        custom = FluidSimConfig(viscosity=0.7)
        sim = _make_sim(cfg=custom)
        assert sim.cfg.viscosity == pytest.approx(0.7)

    def test_vel_cache_starts_none(self):
        sim = _make_sim()
        assert sim._vel_cache is None

    def test_sim_w_includes_padding(self):
        sim = _make_sim(screen_w=640, screen_h=480)
        pad = sim.cfg.pad_pixels  # default 64
        assert sim._sim_w == 640 + 2 * pad

    def test_sim_h_includes_padding(self):
        sim = _make_sim(screen_w=640, screen_h=480)
        pad = sim.cfg.pad_pixels
        assert sim._sim_h == 480 + 2 * pad

    def test_gpu_stored(self):
        from slappyengine.fluid_sim import GlobalFluidSim
        gpu_ctx = MagicMock()
        gpu_ctx.device = MagicMock()
        sim = GlobalFluidSim(gpu=gpu_ctx, screen_w=320, screen_h=240)
        assert sim._gpu is gpu_ctx


# ─────────────────────────────────────────────────────────────────────────────
#  4. sample_velocity — _vel_cache is None
# ─────────────────────────────────────────────────────────────────────────────

class TestSampleVelocityNoneCache:
    def test_returns_tuple(self):
        sim = _make_sim()
        result = sim.sample_velocity(0.0, 0.0)
        assert isinstance(result, tuple)

    def test_returns_two_elements(self):
        sim = _make_sim()
        assert len(sim.sample_velocity(0.0, 0.0)) == 2

    def test_returns_zero_vx(self):
        sim = _make_sim()
        vx, _ = sim.sample_velocity(100.0, 200.0)
        assert vx == 0.0

    def test_returns_zero_vy(self):
        sim = _make_sim()
        _, vy = sim.sample_velocity(100.0, 200.0)
        assert vy == 0.0

    def test_does_not_raise(self):
        sim = _make_sim()
        sim.sample_velocity(999.0, 999.0)  # must not raise


# ─────────────────────────────────────────────────────────────────────────────
#  5. sample_velocity — real numpy vel_cache
# ─────────────────────────────────────────────────────────────────────────────

class TestSampleVelocityWithCache:
    def _sim_with_cache(self, vx: float, vy: float):
        """Create a 1×1 sim with a single-pixel vel_cache."""
        from slappyengine.fluid_sim import FluidSimConfig
        cfg = FluidSimConfig(pad_pixels=0)   # pad=0 so pixel 0,0 maps to sim 0,0
        sim = _make_sim(screen_w=1, screen_h=1, cfg=cfg)
        sim._vel_cache = np.array([[[vx, vy]]], dtype=np.float32)
        sim._sim_w = 1
        sim._sim_h = 1
        return sim

    def test_correct_vx(self):
        sim = self._sim_with_cache(1.5, -0.3)
        vx, _ = sim.sample_velocity(0.0, 0.0)
        assert abs(vx - 1.5) < 0.01

    def test_correct_vy(self):
        sim = self._sim_with_cache(1.5, -0.3)
        _, vy = sim.sample_velocity(0.0, 0.0)
        assert abs(vy - (-0.3)) < 0.01

    def test_negative_velocity(self):
        sim = self._sim_with_cache(-2.5, -3.7)
        vx, vy = sim.sample_velocity(0.0, 0.0)
        assert abs(vx - (-2.5)) < 0.01
        assert abs(vy - (-3.7)) < 0.01

    def test_zero_velocity(self):
        sim = self._sim_with_cache(0.0, 0.0)
        vx, vy = sim.sample_velocity(0.0, 0.0)
        assert vx == pytest.approx(0.0)
        assert vy == pytest.approx(0.0)

    def test_out_of_bounds_clamped(self):
        """Coordinates beyond sim bounds should clamp to edge, not raise."""
        sim = self._sim_with_cache(5.0, -1.0)
        # request far outside the 1×1 grid — should clamp and return edge pixel
        vx, vy = sim.sample_velocity(9999.0, 9999.0)
        assert abs(vx - 5.0) < 0.01
        assert abs(vy - (-1.0)) < 0.01

    def test_injected_numpy_cache_canonical(self):
        """Canonical form from the task specification."""
        from slappyengine.fluid_sim import GlobalFluidSim
        gpu_ctx = MagicMock()
        gpu_ctx.device = MagicMock()
        sim = GlobalFluidSim(gpu=gpu_ctx, screen_w=640, screen_h=480)
        sim._vel_cache = np.array([[[1.5, -0.3]]], dtype=np.float32)
        sim._sim_w = 1
        sim._sim_h = 1
        # With default pad_pixels=64, sample_velocity clamps cx/cy to [0, sim_w-1]
        result = sim.sample_velocity(0.0, 0.0)
        assert abs(result[0] - 1.5) < 0.01
        assert abs(result[1] - (-0.3)) < 0.01


# ─────────────────────────────────────────────────────────────────────────────
#  6. _ping_pong_textures()
# ─────────────────────────────────────────────────────────────────────────────

class TestPingPongTextures:
    def _sim_with_textures(self):
        sim = _make_sim()
        # Assign distinguishable sentinel objects for each texture
        sim._vel_tex_a = object()
        sim._vel_tex_b = object()
        sim._den_tex_a = object()
        sim._den_tex_b = object()
        return sim

    def test_ping_true_returns_vel_a_as_read(self):
        sim = self._sim_with_textures()
        sim._ping = True
        vel_read, vel_write, den_read, den_write = sim._ping_pong_textures()
        assert vel_read is sim._vel_tex_a

    def test_ping_true_returns_vel_b_as_write(self):
        sim = self._sim_with_textures()
        sim._ping = True
        vel_read, vel_write, den_read, den_write = sim._ping_pong_textures()
        assert vel_write is sim._vel_tex_b

    def test_ping_true_returns_den_a_as_read(self):
        sim = self._sim_with_textures()
        sim._ping = True
        vel_read, vel_write, den_read, den_write = sim._ping_pong_textures()
        assert den_read is sim._den_tex_a

    def test_ping_true_returns_den_b_as_write(self):
        sim = self._sim_with_textures()
        sim._ping = True
        vel_read, vel_write, den_read, den_write = sim._ping_pong_textures()
        assert den_write is sim._den_tex_b

    def test_ping_false_returns_vel_b_as_read(self):
        sim = self._sim_with_textures()
        sim._ping = False
        vel_read, vel_write, den_read, den_write = sim._ping_pong_textures()
        assert vel_read is sim._vel_tex_b

    def test_ping_false_returns_vel_a_as_write(self):
        sim = self._sim_with_textures()
        sim._ping = False
        vel_read, vel_write, den_read, den_write = sim._ping_pong_textures()
        assert vel_write is sim._vel_tex_a

    def test_ping_false_returns_den_b_as_read(self):
        sim = self._sim_with_textures()
        sim._ping = False
        vel_read, vel_write, den_read, den_write = sim._ping_pong_textures()
        assert den_read is sim._den_tex_b

    def test_ping_false_returns_den_a_as_write(self):
        sim = self._sim_with_textures()
        sim._ping = False
        vel_read, vel_write, den_read, den_write = sim._ping_pong_textures()
        assert den_write is sim._den_tex_a

    def test_returns_four_elements(self):
        sim = self._sim_with_textures()
        result = sim._ping_pong_textures()
        assert len(result) == 4


# ─────────────────────────────────────────────────────────────────────────────
#  7. _flip_ping_pong()
# ─────────────────────────────────────────────────────────────────────────────

class TestFlipPingPong:
    def test_toggles_true_to_false(self):
        sim = _make_sim()
        sim._ping = True
        sim._flip_ping_pong()
        assert sim._ping is False

    def test_toggles_false_to_true(self):
        sim = _make_sim()
        sim._ping = False
        sim._flip_ping_pong()
        assert sim._ping is True

    def test_double_flip_restores_original_true(self):
        sim = _make_sim()
        sim._ping = True
        sim._flip_ping_pong()
        sim._flip_ping_pong()
        assert sim._ping is True

    def test_double_flip_restores_original_false(self):
        sim = _make_sim()
        sim._ping = False
        sim._flip_ping_pong()
        sim._flip_ping_pong()
        assert sim._ping is False

    def test_flip_sequence_alternates(self):
        sim = _make_sim()
        states = [sim._ping]
        for _ in range(4):
            sim._flip_ping_pong()
            states.append(sim._ping)
        assert states == [True, False, True, False, True]


# ─────────────────────────────────────────────────────────────────────────────
#  8. _sim_params_size()
# ─────────────────────────────────────────────────────────────────────────────

class TestSimParamsSize:
    def test_returns_64(self):
        sim = _make_sim()
        assert sim._sim_params_size() == 64

    def test_return_type_is_int(self):
        sim = _make_sim()
        assert isinstance(sim._sim_params_size(), int)

    def test_is_multiple_of_16(self):
        """GPU uniform buffer alignment: size must be a multiple of 16 bytes."""
        sim = _make_sim()
        assert sim._sim_params_size() % 16 == 0


# ─────────────────────────────────────────────────────────────────────────────
#  9. dispatch() — early return when _initialized=False
# ─────────────────────────────────────────────────────────────────────────────

class TestDispatchEarlyReturn:
    def test_dispatch_returns_none_when_not_initialized(self):
        sim = _make_sim()
        assert sim._initialized is False
        result = sim.dispatch(encoder=MagicMock(), dt=0.016, frame_index=0)
        assert result is None

    def test_dispatch_does_not_call_gpu_device(self):
        sim = _make_sim()
        sim.dispatch(encoder=MagicMock(), dt=0.016, frame_index=0)
        # device.create_command_encoder must not have been called
        sim._gpu.device.create_command_encoder.assert_not_called()

    def test_dispatch_does_not_raise(self):
        sim = _make_sim()
        sim.dispatch(encoder=MagicMock(), dt=0.016, frame_index=42)

    def test_dispatch_multiple_calls_no_exception(self):
        sim = _make_sim()
        for frame in range(5):
            sim.dispatch(encoder=MagicMock(), dt=0.016, frame_index=frame)

    def test_dispatch_does_not_change_initialized_flag(self):
        sim = _make_sim()
        sim.dispatch(encoder=MagicMock(), dt=0.016, frame_index=0)
        assert sim._initialized is False


# ─────────────────────────────────────────────────────────────────────────────
#  10. apply_force() — early return when _initialized=False
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyForceEarlyReturn:
    def test_apply_force_returns_none_when_not_initialized(self):
        sim = _make_sim()
        result = sim.apply_force(x=100.0, y=100.0, vx=1.0, vy=0.0)
        assert result is None

    def test_apply_force_does_not_call_gpu_device(self):
        sim = _make_sim()
        sim.apply_force(x=100.0, y=100.0, vx=1.0, vy=0.0)
        sim._gpu.device.queue.write_texture.assert_not_called()

    def test_apply_force_does_not_raise(self):
        sim = _make_sim()
        sim.apply_force(x=320.0, y=240.0, vx=5.0, vy=-2.0, radius=10.0)

    def test_apply_force_with_default_radius_no_raise(self):
        sim = _make_sim()
        sim.apply_force(x=0.0, y=0.0, vx=0.0, vy=0.0)

    def test_apply_force_does_not_change_vel_cache(self):
        sim = _make_sim()
        sim.apply_force(x=100.0, y=100.0, vx=10.0, vy=10.0)
        assert sim._vel_cache is None
