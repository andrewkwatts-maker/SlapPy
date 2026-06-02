"""Engine tests for FluidSimConfig and preset factories — headless (no GPU)."""
from __future__ import annotations
import pytest


class TestFluidSimConfig:
    def test_default_values(self):
        from slappyengine.fluid_sim import FluidSimConfig
        cfg = FluidSimConfig()
        assert cfg.viscosity == pytest.approx(0.1)
        assert cfg.diffusion == pytest.approx(0.02)
        assert cfg.buoyancy == pytest.approx(0.0)
        assert cfg.gravity == pytest.approx(0.0)
        assert cfg.density_decay == pytest.approx(0.995)
        assert cfg.velocity_decay == pytest.approx(0.99)

    def test_pad_pixels_default(self):
        from slappyengine.fluid_sim import FluidSimConfig
        cfg = FluidSimConfig()
        assert cfg.pad_pixels == 64

    def test_lod_defaults(self):
        from slappyengine.fluid_sim import FluidSimConfig
        cfg = FluidSimConfig()
        assert cfg.lod_mode == "exp"
        assert cfg.lod_zones == 4

    def test_init_mode_default(self):
        from slappyengine.fluid_sim import FluidSimConfig
        cfg = FluidSimConfig()
        assert cfg.init_mode == "noise"
        assert cfg.noise_type == "fbm"

    def test_god_rays_default_true(self):
        from slappyengine.fluid_sim import FluidSimConfig
        cfg = FluidSimConfig()
        assert cfg.god_rays is True

    def test_caustics_default_false(self):
        from slappyengine.fluid_sim import FluidSimConfig
        cfg = FluidSimConfig()
        assert cfg.caustics is False

    def test_render_tint_default(self):
        from slappyengine.fluid_sim import FluidSimConfig
        cfg = FluidSimConfig()
        assert len(cfg.render_tint) == 3

    def test_custom_values(self):
        from slappyengine.fluid_sim import FluidSimConfig
        cfg = FluidSimConfig(viscosity=0.5, gravity=9.8, density_decay=1.0)
        assert cfg.viscosity == pytest.approx(0.5)
        assert cfg.gravity == pytest.approx(9.8)
        assert cfg.density_decay == pytest.approx(1.0)


class TestFluidPresets:
    def test_fog_config_values(self):
        from slappyengine.fluid_sim import fog_config
        cfg = fog_config()
        assert cfg.viscosity == pytest.approx(0.2)
        assert cfg.diffusion == pytest.approx(0.04)
        assert cfg.buoyancy == pytest.approx(0.05)
        assert cfg.density_decay == pytest.approx(0.998)

    def test_water_config_has_gravity(self):
        from slappyengine.fluid_sim import water_config
        cfg = water_config()
        assert cfg.gravity > 0.0
        assert cfg.buoyancy == pytest.approx(0.0)
        assert cfg.density_decay == pytest.approx(1.0)

    def test_smoke_config_has_buoyancy(self):
        from slappyengine.fluid_sim import smoke_config
        cfg = smoke_config()
        assert cfg.buoyancy > 0.0
        assert cfg.density_decay < 1.0

    def test_water_viscosity_lower_than_fog(self):
        from slappyengine.fluid_sim import fog_config, water_config
        fog = fog_config()
        water = water_config()
        assert water.viscosity < fog.viscosity

    def test_presets_return_distinct_objects(self):
        from slappyengine.fluid_sim import fog_config, smoke_config
        cfg1 = fog_config()
        cfg2 = smoke_config()
        assert cfg1 is not cfg2
        assert cfg1.viscosity != cfg2.viscosity

    def test_fog_render_tint_blueish(self):
        from slappyengine.fluid_sim import fog_config
        cfg = fog_config()
        r, g, b = cfg.render_tint
        # Fog tint is blueish-white: B channel >= R
        assert b >= r

    def test_smoke_render_tint_grey(self):
        from slappyengine.fluid_sim import smoke_config
        cfg = smoke_config()
        r, g, b = cfg.render_tint
        # Smoke is grey: all channels roughly equal and < 0.5
        assert abs(r - g) < 0.1
        assert abs(g - b) < 0.1

    def test_water_render_tint_blueish(self):
        from slappyengine.fluid_sim import water_config
        cfg = water_config()
        r, g, b = cfg.render_tint
        # Water tint: more blue than red
        assert b > r


class TestFluidSimConfigDataclass:
    def test_is_dataclass(self):
        import dataclasses
        from slappyengine.fluid_sim import FluidSimConfig
        assert dataclasses.is_dataclass(FluidSimConfig)

    def test_can_be_replaced(self):
        import dataclasses
        from slappyengine.fluid_sim import FluidSimConfig
        base = FluidSimConfig()
        modified = dataclasses.replace(base, viscosity=0.99)
        assert modified.viscosity == pytest.approx(0.99)
        assert base.viscosity == pytest.approx(0.1)  # original unchanged

    def test_equality(self):
        from slappyengine.fluid_sim import FluidSimConfig
        a = FluidSimConfig(viscosity=0.3)
        b = FluidSimConfig(viscosity=0.3)
        assert a == b

    def test_inequality(self):
        from slappyengine.fluid_sim import FluidSimConfig
        a = FluidSimConfig(viscosity=0.1)
        b = FluidSimConfig(viscosity=0.5)
        assert a != b
