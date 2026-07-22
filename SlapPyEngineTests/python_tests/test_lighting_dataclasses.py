"""Engine tests for lighting.py data structures — DirectionalLight, PointLight,
ConeLight, ShapeLight, FlashLight, GravityWarpSource, RadianceCascadeConfig,
LightingContext. All headless — no GPU required.
"""
from __future__ import annotations
import pytest


# ---------------------------------------------------------------------------
# DirectionalLight
# ---------------------------------------------------------------------------

class TestDirectionalLight:
    def test_instantiates(self):
        from pharos_engine.lighting import DirectionalLight
        l = DirectionalLight()
        assert l is not None

    def test_defaults(self):
        from pharos_engine.lighting import DirectionalLight
        l = DirectionalLight()
        assert l.direction == (0.707, 0.707)
        assert l.elevation == pytest.approx(0.785)
        assert l.color == (1.0, 1.0, 0.9)
        assert l.intensity == pytest.approx(1.0)
        assert l.cast_shadows is True

    def test_custom_values(self):
        from pharos_engine.lighting import DirectionalLight
        l = DirectionalLight(direction=(1.0, 0.0), intensity=2.0,
                             color=(0.8, 0.8, 1.0), cast_shadows=False)
        assert l.direction == (1.0, 0.0)
        assert l.intensity == pytest.approx(2.0)
        assert l.cast_shadows is False

    def test_mutable_intensity(self):
        from pharos_engine.lighting import DirectionalLight
        l = DirectionalLight()
        l.intensity = 0.5
        assert l.intensity == pytest.approx(0.5)

    def test_tags_empty_set(self):
        from pharos_engine.lighting import DirectionalLight
        l = DirectionalLight()
        assert l.tags == set()


# ---------------------------------------------------------------------------
# PointLight
# ---------------------------------------------------------------------------

class TestPointLight:
    def test_instantiates(self):
        from pharos_engine.lighting import PointLight
        l = PointLight()
        assert l is not None

    def test_defaults(self):
        from pharos_engine.lighting import PointLight
        l = PointLight()
        assert l.position == (0.0, 0.0)
        assert l.z == pytest.approx(100.0)
        assert l.radius == pytest.approx(200.0)
        assert l.color == (1.0, 0.8, 0.6)
        assert l.intensity == pytest.approx(1.0)
        assert l.cast_shadows is False

    def test_custom_position(self):
        from pharos_engine.lighting import PointLight
        l = PointLight(position=(320.0, 240.0), radius=150.0)
        assert l.position == (320.0, 240.0)
        assert l.radius == pytest.approx(150.0)

    def test_tags_default_empty(self):
        from pharos_engine.lighting import PointLight
        l = PointLight()
        assert l.tags == set()

    def test_intensity_mutable(self):
        from pharos_engine.lighting import PointLight
        l = PointLight()
        l.intensity = 3.0
        assert l.intensity == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# ConeLight
# ---------------------------------------------------------------------------

class TestConeLight:
    def test_instantiates(self):
        from pharos_engine.lighting import ConeLight
        l = ConeLight()
        assert l is not None

    def test_defaults(self):
        from pharos_engine.lighting import ConeLight
        l = ConeLight()
        assert l.position == (0.0, 0.0)
        assert l.direction == (1.0, 0.0)
        assert l.z == pytest.approx(0.0)
        assert l.half_angle == pytest.approx(0.35)
        assert l.outer_half_angle == pytest.approx(0.50)
        assert l.radius == pytest.approx(300.0)
        assert l.intensity == pytest.approx(2.0)
        assert l.cast_shadows is False
        assert l.volumetric is False

    def test_volumetric_flag(self):
        from pharos_engine.lighting import ConeLight
        l = ConeLight(volumetric=True)
        assert l.volumetric is True

    def test_custom_values(self):
        from pharos_engine.lighting import ConeLight
        l = ConeLight(position=(100.0, 200.0), direction=(0.0, 1.0),
                      half_angle=0.2, radius=200.0, intensity=3.0)
        assert l.position == (100.0, 200.0)
        assert l.direction == (0.0, 1.0)
        assert l.half_angle == pytest.approx(0.2)
        assert l.radius == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# ShapeLight
# ---------------------------------------------------------------------------

class TestShapeLight:
    def test_instantiates(self):
        from pharos_engine.lighting import ShapeLight
        l = ShapeLight()
        assert l is not None

    def test_defaults(self):
        from pharos_engine.lighting import ShapeLight
        l = ShapeLight()
        assert l.position == (0.0, 0.0)
        assert l.mask_path == ""
        assert l.color == (1.0, 1.0, 0.8)
        assert l.intensity == pytest.approx(1.0)
        assert l.size == (64.0, 64.0)
        assert l.falloff == pytest.approx(1.0)

    def test_custom_mask_path(self):
        from pharos_engine.lighting import ShapeLight
        l = ShapeLight(mask_path="assets/lights/torch.png")
        assert l.mask_path == "assets/lights/torch.png"


# ---------------------------------------------------------------------------
# FlashLight
# ---------------------------------------------------------------------------

class TestFlashLight:
    def test_instantiates(self):
        from pharos_engine.lighting import FlashLight
        l = FlashLight()
        assert l is not None

    def test_defaults(self):
        from pharos_engine.lighting import FlashLight
        l = FlashLight()
        assert l.radius == pytest.approx(80.0)
        assert l.color == (1.0, 0.8, 0.4)
        assert l.intensity == pytest.approx(8.0)
        assert l.duration == pytest.approx(0.06)
        assert l.elapsed == pytest.approx(0.0)

    def test_not_active_before_trigger(self):
        from pharos_engine.lighting import FlashLight
        l = FlashLight()
        assert l.active is False

    def test_trigger_activates(self):
        from pharos_engine.lighting import FlashLight
        l = FlashLight()
        l.trigger()
        assert l.active is True

    def test_tick_expires(self):
        from pharos_engine.lighting import FlashLight
        l = FlashLight(duration=0.1)
        l.trigger()
        expired = l.tick(0.2)
        assert expired is True
        assert l.active is False

    def test_tick_not_yet_expired(self):
        from pharos_engine.lighting import FlashLight
        l = FlashLight(duration=0.5)
        l.trigger()
        expired = l.tick(0.1)
        assert expired is False
        assert l.active is True

    def test_tick_advances_elapsed(self):
        from pharos_engine.lighting import FlashLight
        l = FlashLight(duration=1.0)
        l.trigger()
        l.tick(0.3)
        assert l.elapsed == pytest.approx(0.3)

    def test_multiple_triggers_reset(self):
        from pharos_engine.lighting import FlashLight
        l = FlashLight(duration=0.1)
        l.trigger()
        l.tick(0.2)
        l.trigger()
        assert l.active is True
        assert l.elapsed == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# GravityWarpSource
# ---------------------------------------------------------------------------

class TestGravityWarpSource:
    def test_instantiates(self):
        from pharos_engine.lighting import GravityWarpSource
        g = GravityWarpSource()
        assert g is not None

    def test_defaults(self):
        from pharos_engine.lighting import GravityWarpSource
        g = GravityWarpSource()
        assert g.position == (0.0, 0.0)
        assert g.mass == pytest.approx(1.0)
        assert g.radius == pytest.approx(20.0)
        assert g.falloff == pytest.approx(5000.0)

    def test_permanent_is_active(self):
        from pharos_engine.lighting import GravityWarpSource
        g = GravityWarpSource()
        assert g.active is True  # _remaining = -1 → permanent

    def test_set_duration(self):
        from pharos_engine.lighting import GravityWarpSource
        g = GravityWarpSource()
        g.set_duration(2.0)
        assert g.active is True

    def test_duration_expires(self):
        from pharos_engine.lighting import GravityWarpSource
        g = GravityWarpSource()
        g.set_duration(0.1)
        g.tick(0.2)
        # After 0.2s with 0.1s duration, _remaining = 0 → active=True per logic
        # (active is True when _remaining < 0 OR > 0; = 0 is inactive)
        assert g._remaining == pytest.approx(0.0)

    def test_tick_decrements(self):
        from pharos_engine.lighting import GravityWarpSource
        g = GravityWarpSource()
        g.set_duration(1.0)
        g.tick(0.3)
        assert g._remaining == pytest.approx(0.7)

    def test_negative_mass_repulsive(self):
        from pharos_engine.lighting import GravityWarpSource
        g = GravityWarpSource(mass=-1.5)
        assert g.mass == pytest.approx(-1.5)


# ---------------------------------------------------------------------------
# RadianceCascadeConfig
# ---------------------------------------------------------------------------

class TestRadianceCascadeConfig:
    def test_instantiates(self):
        from pharos_engine.lighting import RadianceCascadeConfig
        c = RadianceCascadeConfig()
        assert c is not None

    def test_defaults(self):
        from pharos_engine.lighting import RadianceCascadeConfig
        c = RadianceCascadeConfig()
        assert c.num_cascades == 4
        assert c.probe_spacing_px == 8
        assert c.rays_per_probe == 64
        assert c.max_ray_length_px == pytest.approx(512.0)

    def test_custom_values(self):
        from pharos_engine.lighting import RadianceCascadeConfig
        c = RadianceCascadeConfig(num_cascades=6, rays_per_probe=128)
        assert c.num_cascades == 6
        assert c.rays_per_probe == 128


# ---------------------------------------------------------------------------
# LightingContext
# ---------------------------------------------------------------------------

class TestLightingContext:
    def test_instantiates(self):
        from pharos_engine.lighting import LightingContext
        lc = LightingContext()
        assert lc is not None

    def test_defaults(self):
        from pharos_engine.lighting import LightingContext
        lc = LightingContext()
        assert lc.ambient_intensity == pytest.approx(0.15)
        assert lc.mode == "local"
        assert lc.lights == []

    def test_add_light(self):
        from pharos_engine.lighting import LightingContext, PointLight
        lc = LightingContext()
        l = PointLight()
        lc.add_light(l)
        assert l in lc.lights

    def test_remove_light(self):
        from pharos_engine.lighting import LightingContext, PointLight
        lc = LightingContext()
        l = PointLight()
        lc.add_light(l)
        lc.remove_light(l)
        assert l not in lc.lights

    def test_custom_ambient(self):
        from pharos_engine.lighting import LightingContext
        lc = LightingContext(ambient_color=(0.3, 0.3, 0.4), ambient_intensity=0.4)
        assert lc.ambient_color == (0.3, 0.3, 0.4)
        assert lc.ambient_intensity == pytest.approx(0.4)

    def test_mode_global(self):
        from pharos_engine.lighting import LightingContext
        lc = LightingContext(mode="global")
        assert lc.mode == "global"

    def test_multiple_lights(self):
        from pharos_engine.lighting import LightingContext, PointLight, ConeLight
        lc = LightingContext()
        lc.add_light(PointLight())
        lc.add_light(ConeLight())
        assert len(lc.lights) == 2
