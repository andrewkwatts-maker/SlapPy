"""Q1 Sprint — Lighting System Validation Tests.

Tests that validate the LightingSystem, PointLight, ConeLight, DirectionalLight,
and FlashLight objects from pharos_engine.lighting.

GPU dispatch (wgpu) is not available in headless CI, so pixel-render tests are
skipped when wgpu is absent.  All structural, state-management, Observable-event,
and FlashLight lifecycle tests run unconditionally.
"""
from __future__ import annotations

import math
from unittest.mock import MagicMock, patch
import pytest


# ---------------------------------------------------------------------------
# Helper: build a LightingSystem with a mocked GPU context.
# ---------------------------------------------------------------------------

def _make_ls(width: int = 64, height: int = 64):
    from pharos_engine.lighting import LightingSystem
    gpu = MagicMock()
    gpu.device = MagicMock()
    return LightingSystem(gpu, width=width, height=height)


# ---------------------------------------------------------------------------
# 1. PointLight construction and default values
# ---------------------------------------------------------------------------

def test_pointlight_default_construction():
    from pharos_engine.lighting import PointLight
    pl = PointLight()
    assert pl.intensity == 1.0
    assert pl.radius == 200.0
    assert len(pl.color) == 3


def test_pointlight_custom_values():
    from pharos_engine.lighting import PointLight
    pl = PointLight(position=(32.0, 32.0), radius=100.0, intensity=2.0,
                    color=(1.0, 0.0, 0.0))
    assert pl.position == (32.0, 32.0)
    assert pl.radius == pytest.approx(100.0)
    assert pl.intensity == pytest.approx(2.0)
    assert pl.color == (1.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# 2. PointLight is Observable — setting a property fires an event
# ---------------------------------------------------------------------------

def test_pointlight_observable_intensity_event():
    from pharos_engine.lighting import PointLight
    from pharos_engine.event_bus import subscribe, unsubscribe

    received = []
    # Subscribe to the specific attribute path so listener_count check passes
    handle = subscribe("PointLight.intensity", lambda evt: received.append(evt))
    try:
        pl = PointLight()
        pl.intensity = 0.5  # should auto-publish PointLight.intensity|0.5
        assert len(received) >= 1
    finally:
        unsubscribe(handle)


def test_pointlight_observable_color_event():
    from pharos_engine.lighting import PointLight
    from pharos_engine.event_bus import subscribe, unsubscribe

    received = []
    handle = subscribe("PointLight.color", lambda evt: received.append(evt))
    try:
        pl = PointLight()
        pl.color = (0.0, 1.0, 0.0)
        assert len(received) >= 1
    finally:
        unsubscribe(handle)


def test_pointlight_no_publish_tags():
    """tags and cast_shadows must NOT fire events (listed in __no_publish__)."""
    from pharos_engine.lighting import PointLight
    from pharos_engine.event_bus import subscribe, unsubscribe

    received = []
    handle = subscribe("PointLight", lambda evt: received.append(evt))
    try:
        pl = PointLight()
        pl.tags = {"weapon"}        # __no_publish__ → no event
        pl.cast_shadows = True      # __no_publish__ → no event
        assert len(received) == 0
    finally:
        unsubscribe(handle)


# ---------------------------------------------------------------------------
# 3. ConeLight construction
# ---------------------------------------------------------------------------

def test_conelight_default_construction():
    from pharos_engine.lighting import ConeLight
    cl = ConeLight()
    assert cl.intensity == pytest.approx(2.0)
    assert cl.direction == (1.0, 0.0)
    assert cl.half_angle < cl.outer_half_angle


def test_conelight_custom_direction():
    from pharos_engine.lighting import ConeLight
    cl = ConeLight(direction=(0.0, 1.0), half_angle=0.2, outer_half_angle=0.4)
    assert cl.direction == (0.0, 1.0)
    assert cl.half_angle == pytest.approx(0.2)


def test_conelight_is_observable():
    from pharos_engine.lighting import ConeLight
    from pharos_engine.event_bus import subscribe, unsubscribe

    received = []
    handle = subscribe("ConeLight.intensity", lambda evt: received.append(evt))
    try:
        cl = ConeLight()
        cl.intensity = 3.0
        assert len(received) >= 1
    finally:
        unsubscribe(handle)


# ---------------------------------------------------------------------------
# 4. DirectionalLight construction and Observable behaviour
# ---------------------------------------------------------------------------

def test_directionallight_default_construction():
    from pharos_engine.lighting import DirectionalLight
    dl = DirectionalLight()
    assert dl.intensity == pytest.approx(1.0)
    assert len(dl.direction) == 2
    assert dl.elevation > 0.0


def test_directionallight_observable():
    from pharos_engine.lighting import DirectionalLight
    from pharos_engine.event_bus import subscribe, unsubscribe

    received = []
    handle = subscribe("DirectionalLight.intensity", lambda evt: received.append(evt))
    try:
        dl = DirectionalLight()
        dl.intensity = 0.0
        assert len(received) >= 1
    finally:
        unsubscribe(handle)


# ---------------------------------------------------------------------------
# 5. LightingSystem — add / remove lights
# ---------------------------------------------------------------------------

def test_lightingsystem_add_light():
    from pharos_engine.lighting import PointLight
    ls = _make_ls()
    pl = PointLight(position=(10.0, 10.0))
    ls.add_light(pl)
    assert pl in ls.point_lights


def test_lightingsystem_remove_light():
    from pharos_engine.lighting import PointLight
    ls = _make_ls()
    pl = PointLight()
    ls.add_light(pl)
    ls.remove_light(pl)
    assert pl not in ls.point_lights


def test_lightingsystem_remove_nonexistent_no_crash():
    from pharos_engine.lighting import PointLight
    ls = _make_ls()
    pl = PointLight()
    ls.remove_light(pl)  # never added — must not raise


def test_lightingsystem_typed_accessors_directional():
    from pharos_engine.lighting import DirectionalLight, PointLight
    ls = _make_ls()
    dl = DirectionalLight()
    pl = PointLight()
    ls.add_light(dl)
    ls.add_light(pl)
    assert dl in ls.directional_lights
    assert dl not in ls.point_lights
    assert pl in ls.point_lights
    assert pl not in ls.directional_lights


def test_lightingsystem_typed_accessors_cone():
    from pharos_engine.lighting import ConeLight
    ls = _make_ls()
    cl = ConeLight()
    ls.add_light(cl)
    assert cl in ls.cone_lights


def test_lightingsystem_add_50_pointlights_no_crash():
    """Adding 50 PointLights and calling no GPU methods should not raise."""
    from pharos_engine.lighting import PointLight
    ls = _make_ls()
    for i in range(50):
        ls.add_light(PointLight(position=(float(i), 0.0)))
    assert len(ls.point_lights) == 50


# ---------------------------------------------------------------------------
# 6. LightingSystem — ambient configuration
# ---------------------------------------------------------------------------

def test_lightingsystem_set_ambient():
    ls = _make_ls()
    ls.set_ambient((0.5, 0.5, 0.5), intensity=0.5)
    assert ls._ambient_color == (0.5, 0.5, 0.5)
    assert ls._ambient_intensity == pytest.approx(0.5)


def test_lightingsystem_ambient_default():
    ls = _make_ls()
    assert ls._ambient_intensity < 1.0   # sanity: default is not max


# ---------------------------------------------------------------------------
# 7. LightingSystem — profile loading
# ---------------------------------------------------------------------------

def test_lightingsystem_load_profile_night_rally():
    ls = _make_ls()
    ls.load_profile("night_rally")
    assert ls._ambient_intensity < 0.15


def test_lightingsystem_load_profile_day_rally():
    ls = _make_ls()
    ls.load_profile("day_rally")
    assert ls._ambient_intensity > 0.15


def test_lightingsystem_load_profile_garage():
    ls = _make_ls()
    ls.load_profile("garage")
    assert ls._ambient_intensity > 0.2


def test_lightingsystem_load_profile_unknown_no_crash():
    ls = _make_ls()
    ls.load_profile("bogus_profile_xyz")


def test_lightingsystem_load_profile_custom_dict():
    ls = _make_ls()
    custom = {"mytest": {"ambient": (0.3, 0.3, 0.3), "ambient_intensity": 0.7}}
    ls.load_profile("mytest", profiles=custom)
    assert ls._ambient_intensity == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# 8. FlashLight lifecycle
# ---------------------------------------------------------------------------

def test_flashlight_not_active_before_trigger():
    from pharos_engine.lighting import FlashLight
    fl = FlashLight(duration=0.06)
    assert not fl.active


def test_flashlight_active_after_trigger():
    from pharos_engine.lighting import FlashLight
    fl = FlashLight(duration=0.06)
    fl.trigger()
    assert fl.active


def test_flashlight_expires_after_duration():
    from pharos_engine.lighting import FlashLight
    fl = FlashLight(duration=0.1)
    fl.trigger()
    expired = fl.tick(0.2)   # well past duration
    assert expired is True
    assert not fl.active


def test_flashlight_still_active_during_duration():
    from pharos_engine.lighting import FlashLight
    fl = FlashLight(duration=0.5)
    fl.trigger()
    expired = fl.tick(0.1)
    assert expired is False
    assert fl.active


def test_flashlight_tick_accumulates_elapsed():
    from pharos_engine.lighting import FlashLight
    fl = FlashLight(duration=1.0)
    fl.trigger()
    fl.tick(0.4)
    assert fl.elapsed == pytest.approx(0.4, abs=1e-6)


def test_lightingsystem_tick_flash_removes_expired():
    from pharos_engine.lighting import FlashLight
    ls = _make_ls()
    fl = FlashLight(duration=0.01)
    fl.trigger()
    ls.add_light(fl)
    removed = ls.tick_flash_lights(0.1)  # dt >> duration
    assert removed == 1
    assert fl not in ls._lights


def test_lightingsystem_tick_flash_keeps_active():
    from pharos_engine.lighting import FlashLight
    ls = _make_ls()
    fl = FlashLight(duration=1.0)
    fl.trigger()
    ls.add_light(fl)
    removed = ls.tick_flash_lights(0.01)  # dt << duration
    assert removed == 0
    assert fl in ls._lights


# ---------------------------------------------------------------------------
# 9. GravityWarpSource
# ---------------------------------------------------------------------------

def test_gravitywarp_add_and_active():
    ls = _make_ls()
    warp = ls.add_gravity_warp(pos=(10.0, 10.0), mass=2.0, radius=30.0)
    assert warp.active
    assert warp in ls.gravity_warps


def test_gravitywarp_duration_expires():
    ls = _make_ls()
    warp = ls.add_gravity_warp(pos=(0.0, 0.0), mass=1.0, duration=0.05)
    ls.tick(0.1)
    # Expired warps are removed by tick()
    assert warp not in ls.gravity_warps


def test_gravitywarp_permanent_stays_active():
    ls = _make_ls()
    warp = ls.add_gravity_warp(pos=(0.0, 0.0), mass=1.0, duration=-1.0)
    ls.tick(10.0)
    assert warp in ls.gravity_warps


# ---------------------------------------------------------------------------
# 10. RadianceCascadeConfig
# ---------------------------------------------------------------------------

def test_radiance_cascade_config_defaults():
    from pharos_engine.lighting import RadianceCascadeConfig
    cfg = RadianceCascadeConfig()
    assert cfg.num_cascades == 4
    assert cfg.probe_spacing_px == 8
    assert cfg.rays_per_probe == 64


def test_radiance_cascade_config_custom():
    from pharos_engine.lighting import RadianceCascadeConfig
    cfg = RadianceCascadeConfig(num_cascades=2, probe_spacing_px=16, rays_per_probe=32,
                                max_ray_length_px=256.0)
    assert cfg.num_cascades == 2
    assert cfg.max_ray_length_px == pytest.approx(256.0)


def test_lightingsystem_set_radiance_config():
    from pharos_engine.lighting import RadianceCascadeConfig
    ls = _make_ls()
    cfg = RadianceCascadeConfig(num_cascades=3)
    ls.set_radiance_config(cfg)
    assert ls._radiance_config is cfg


# ---------------------------------------------------------------------------
# 11. LightingContext (per-layer lighting)
# ---------------------------------------------------------------------------

def test_lighting_context_add_remove():
    from pharos_engine.lighting import LightingContext, PointLight
    ctx = LightingContext(ambient_intensity=0.3, mode="local")
    pl = PointLight()
    ctx.add_light(pl)
    assert pl in ctx.lights
    ctx.remove_light(pl)
    assert pl not in ctx.lights


def test_lighting_context_clear():
    from pharos_engine.lighting import LightingContext, PointLight
    ctx = LightingContext()
    ctx.add_light(PointLight())
    ctx.add_light(PointLight())
    ctx.clear_lights()
    assert len(ctx.lights) == 0


def test_lighting_context_mode():
    from pharos_engine.lighting import LightingContext
    ctx = LightingContext(mode="cross")
    assert ctx.mode == "cross"


# ---------------------------------------------------------------------------
# 12. ShapeLight and GravityWarpSource construction
# ---------------------------------------------------------------------------

def test_shapelight_construction():
    from pharos_engine.lighting import ShapeLight
    sl = ShapeLight(position=(10.0, 20.0), mask_path="mask.png",
                    color=(1.0, 0.8, 0.6), intensity=1.5)
    assert sl.intensity == pytest.approx(1.5)
    assert sl.mask_path == "mask.png"


def test_gravity_warp_source_direct():
    from pharos_engine.lighting import GravityWarpSource
    g = GravityWarpSource(position=(5.0, 5.0), mass=3.0, radius=10.0)
    assert g.active   # permanent by default (_remaining == -1)
    g.set_duration(0.2)
    g.tick(0.1)
    assert g.active   # still active
    g.tick(0.15)
    assert not g.active  # now expired


# ---------------------------------------------------------------------------
# 13. dispatch() is a no-op when no lights are registered (no GPU crash)
# ---------------------------------------------------------------------------

def test_dispatch_no_lights_is_noop():
    """dispatch() should return immediately when no lights are registered."""
    ls = _make_ls()
    frame_tex = MagicMock()
    # dispatch() checks self._lights and self._gravity_warps first; if both
    # empty it returns without touching GPU.
    ls.dispatch(frame_tex)   # must not raise
    # GPU was never called because the early return fires.
    assert not ls._gpu.device.create_command_encoder.called


def test_set_fluid_density_stores_reference():
    ls = _make_ls()
    fake_tex = MagicMock()
    ls.set_fluid_density(fake_tex)
    assert ls._fluid_density_tex is fake_tex


def test_set_fluid_density_none():
    ls = _make_ls()
    ls.set_fluid_density(None)
    assert ls._fluid_density_tex is None
