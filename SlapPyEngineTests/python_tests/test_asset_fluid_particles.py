"""Engine tests for asset.py, fluid_sim.py (config + presets), and particles.py
(CPU ParticleEmitter + EmitterShape + TurbulenceConfig).
All headless — no GPU required.
"""
from __future__ import annotations
import pytest
import numpy as np


# ---------------------------------------------------------------------------
# Asset
# ---------------------------------------------------------------------------

class TestAssetDefaults:
    def test_instantiates(self):
        from slappyengine.asset import Asset
        a = Asset()
        assert a is not None

    def test_default_name_empty(self):
        from slappyengine.asset import Asset
        a = Asset()
        assert a.name == ""

    def test_default_size(self):
        from slappyengine.asset import Asset
        a = Asset()
        assert a.size == (64, 64)

    def test_custom_name_and_size(self):
        from slappyengine.asset import Asset
        a = Asset(name="Player", size=(128, 128))
        assert a.name == "Player"
        assert a.size == (128, 128)

    def test_material_map_none(self):
        from slappyengine.asset import Asset
        a = Asset()
        assert a.material_map is None

    def test_pixels_none(self):
        from slappyengine.asset import Asset
        a = Asset()
        assert a.pixels is None

    def test_compute_none(self):
        from slappyengine.asset import Asset
        a = Asset()
        assert a.compute is None

    def test_effects_empty(self):
        from slappyengine.asset import Asset
        a = Asset()
        assert a.effects == []

    def test_is_render_target_subclass(self):
        from slappyengine.asset import Asset
        from slappyengine.render_target import RenderTarget
        a = Asset()
        assert isinstance(a, RenderTarget)

    def test_add_layer(self):
        from slappyengine.asset import Asset
        from slappyengine.layer import Layer2D
        a = Asset()
        l = Layer2D(width=64, height=64)
        result = a.add_layer(l)
        assert result is l
        assert l in a.layers

    def test_evict_no_manager_no_crash(self):
        from slappyengine.asset import Asset
        a = Asset()
        a.evict_to_ram()    # no residency manager — should not raise
        a.evict_to_disk()
        a.prefetch()


# ---------------------------------------------------------------------------
# FluidSimConfig dataclass and preset factories
# ---------------------------------------------------------------------------

class TestFluidSimConfigDefaults:
    def test_instantiates(self):
        from slappyengine.fluid_sim import FluidSimConfig
        c = FluidSimConfig()
        assert c is not None

    def test_pad_pixels(self):
        from slappyengine.fluid_sim import FluidSimConfig
        c = FluidSimConfig()
        assert c.pad_pixels == 64

    def test_lod_mode(self):
        from slappyengine.fluid_sim import FluidSimConfig
        c = FluidSimConfig()
        assert c.lod_mode == "exp"

    def test_lod_zones(self):
        from slappyengine.fluid_sim import FluidSimConfig
        c = FluidSimConfig()
        assert c.lod_zones == 4

    def test_physics_defaults(self):
        from slappyengine.fluid_sim import FluidSimConfig
        c = FluidSimConfig()
        assert c.viscosity == pytest.approx(0.1)
        assert c.diffusion == pytest.approx(0.02)
        assert c.buoyancy == pytest.approx(0.0)
        assert c.gravity == pytest.approx(0.0)
        assert c.density_decay == pytest.approx(0.995)
        assert c.velocity_decay == pytest.approx(0.99)

    def test_init_mode(self):
        from slappyengine.fluid_sim import FluidSimConfig
        c = FluidSimConfig()
        assert c.init_mode == "noise"

    def test_noise_defaults(self):
        from slappyengine.fluid_sim import FluidSimConfig
        c = FluidSimConfig()
        assert c.noise_type == "fbm"
        assert c.noise_seed == 42

    def test_lighting_defaults(self):
        from slappyengine.fluid_sim import FluidSimConfig
        c = FluidSimConfig()
        assert c.god_rays is True
        assert c.caustics is False

    def test_render_tint_tuple(self):
        from slappyengine.fluid_sim import FluidSimConfig
        c = FluidSimConfig()
        assert len(c.render_tint) == 3


class TestFluidSimPresets:
    def test_fog_config(self):
        from slappyengine.fluid_sim import fog_config
        c = fog_config()
        assert c.viscosity == pytest.approx(0.2)
        assert c.density_decay == pytest.approx(0.998)

    def test_water_config(self):
        from slappyengine.fluid_sim import water_config
        c = water_config()
        assert c.gravity == pytest.approx(9.8)
        assert c.density_decay == pytest.approx(1.0)

    def test_smoke_config(self):
        from slappyengine.fluid_sim import smoke_config
        c = smoke_config()
        assert c.buoyancy == pytest.approx(0.15)

    def test_presets_return_fluid_sim_config(self):
        from slappyengine.fluid_sim import fog_config, water_config, smoke_config, FluidSimConfig
        for factory in (fog_config, water_config, smoke_config):
            c = factory()
            assert isinstance(c, FluidSimConfig)


# ---------------------------------------------------------------------------
# ParticleEmitter (CPU)
# ---------------------------------------------------------------------------

class TestParticleEmitterDefaults:
    def test_instantiates(self):
        from slappyengine.particles import ParticleEmitter
        pe = ParticleEmitter()
        assert pe is not None

    def test_texture_data_shape(self):
        from slappyengine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=100, texture_size=64)
        assert pe.texture_data.shape == (64, 64, 4)

    def test_texture_data_dtype(self):
        from slappyengine.particles import ParticleEmitter
        pe = ParticleEmitter()
        assert pe.texture_data.dtype == np.uint8

    def test_texture_data_initially_black(self):
        from slappyengine.particles import ParticleEmitter
        pe = ParticleEmitter()
        assert np.all(pe.texture_data == 0)

    def test_custom_texture_size(self):
        from slappyengine.particles import ParticleEmitter
        pe = ParticleEmitter(texture_size=32)
        assert pe.texture_data.shape == (32, 32, 4)


class TestParticleEmitterEmit:
    def test_emit_no_crash(self):
        from slappyengine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=100)
        pe.emit(count=10, position=(32, 32), color=(255, 0, 0), lifetime=1.0)

    def test_tick_no_crash(self):
        from slappyengine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=100)
        pe.emit(count=10, position=(32, 32), color=(255, 0, 0), lifetime=1.0)
        pe.tick(0.016)

    def test_tick_empty_no_crash(self):
        from slappyengine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=100)
        pe.tick(0.016)

    def test_particles_appear_in_texture_after_emit_and_tick(self):
        from slappyengine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=100, texture_size=64)
        pe.emit(count=20, position=(32, 32), color=(255, 100, 50), lifetime=2.0)
        pe.tick(0.016)
        # Some pixels should be non-zero after particles are alive
        assert pe.texture_data[:, :, 3].max() > 0

    def test_particles_fade_over_time(self):
        from slappyengine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=50, texture_size=64)
        pe.emit(count=20, position=(32, 32), color=(255, 255, 255), lifetime=0.1)
        pe.tick(0.2)  # lifetime expired
        # All particles should be dead — texture all zeros
        assert np.all(pe.texture_data == 0)

    def test_emit_respects_max_particles(self):
        from slappyengine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=5, texture_size=64)
        pe.emit(count=100, position=(32, 32), color=(255, 0, 0), lifetime=5.0)
        alive = np.sum(pe._life > 0)
        assert alive <= 5

    def test_gravity_applied(self):
        from slappyengine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=10, texture_size=64)
        pe.emit(count=5, position=(32, 32), speed_range=(0, 0), color=(255, 255, 255),
                lifetime=10.0, spread_angle=0.0)
        initial_vy = pe._vel_y.copy()
        pe.tick(0.5, gravity=100.0)
        # vel_y should have increased by gravity * dt for alive particles
        alive = pe._life > 0
        if alive.any():
            assert pe._vel_y[alive].mean() > initial_vy[alive].mean()

    def test_spread_angle_zero_emits_upward(self):
        from slappyengine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=20, texture_size=64)
        pe.emit(count=10, position=(0.0, 0.0), speed_range=(100, 100),
                color=(255, 255, 255), lifetime=5.0, spread_angle=0.0)
        alive = pe._life > 0
        if alive.any():
            # All velocities should be near-upward (vel_x ≈ 0, vel_y < 0 = upward)
            assert abs(pe._vel_x[alive].mean()) < 5.0
            assert pe._vel_y[alive].mean() < 0


# ---------------------------------------------------------------------------
# EmitterShape enum
# ---------------------------------------------------------------------------

class TestEmitterShape:
    def test_values(self):
        from slappyengine.particles import EmitterShape
        assert EmitterShape.POINT == 0
        assert EmitterShape.SPHERE == 1
        assert EmitterShape.BOX == 2
        assert EmitterShape.CONE == 3

    def test_distinct(self):
        from slappyengine.particles import EmitterShape
        vals = [EmitterShape.POINT, EmitterShape.SPHERE, EmitterShape.BOX, EmitterShape.CONE]
        assert len(set(vals)) == 4


# ---------------------------------------------------------------------------
# TurbulenceConfig
# ---------------------------------------------------------------------------

class TestTurbulenceConfig:
    def test_instantiates(self):
        from slappyengine.particles import TurbulenceConfig
        tc = TurbulenceConfig()
        assert tc is not None

    def test_defaults(self):
        from slappyengine.particles import TurbulenceConfig
        tc = TurbulenceConfig()
        assert tc.strength == pytest.approx(0.0)
        assert tc.speed == pytest.approx(1.0)
        assert tc.scale == pytest.approx(0.003)

    def test_custom_values(self):
        from slappyengine.particles import TurbulenceConfig
        tc = TurbulenceConfig(strength=0.5, speed=2.0, scale=0.01)
        assert tc.strength == pytest.approx(0.5)
        assert tc.speed == pytest.approx(2.0)
        assert tc.scale == pytest.approx(0.01)
