"""Tests for FlashLight auto-expiry and LightingSystem.tick_flash_lights."""
import pytest


def test_flash_light_tick_not_expired():
    from playslap.lighting import FlashLight

    fl = FlashLight(duration=0.1)
    fl.trigger()
    expired = fl.tick(0.05)
    assert not expired, "tick(0.05) on a duration=0.1 light should not yet be expired"
    assert fl.elapsed == pytest.approx(0.05)


def test_flash_light_tick_expired():
    from playslap.lighting import FlashLight

    fl = FlashLight(duration=0.1)
    fl.trigger()
    fl.tick(0.05)
    expired = fl.tick(0.06)
    assert expired, "tick(0.06) after tick(0.05) on duration=0.1 should be expired"
    assert fl.elapsed == pytest.approx(0.11)


def test_flash_light_elapsed_starts_zero():
    from playslap.lighting import FlashLight

    fl = FlashLight(duration=0.1)
    assert fl.elapsed == 0.0


def test_flash_light_trigger_resets_elapsed():
    from playslap.lighting import FlashLight

    fl = FlashLight(duration=0.1)
    fl.trigger()
    fl.tick(0.05)
    # Re-trigger should reset elapsed
    fl.trigger()
    assert fl.elapsed == 0.0


def test_tick_flash_lights_removes_only_expired():
    """tick_flash_lights removes expired FlashLights and returns the count removed."""
    from playslap.lighting import FlashLight, LightingSystem

    # Build a LightingSystem without a real GPU by bypassing __init__.
    # We only need the _lights list and the tick_flash_lights method.
    ls = object.__new__(LightingSystem)
    ls._lights = []
    ls._gravity_warps = []

    # Active flash light: triggered, not yet expired
    active_fl = FlashLight(duration=0.5)
    active_fl.trigger()

    # Expired flash light: already past its duration via elapsed
    expired_fl = FlashLight(duration=0.1)
    expired_fl.trigger()
    # Advance elapsed past duration without going through LightingSystem
    expired_fl.elapsed = 0.15  # manually set elapsed > duration

    ls._lights.append(active_fl)
    ls._lights.append(expired_fl)

    removed = ls.tick_flash_lights(0.0)  # dt=0 so active_fl stays alive

    assert removed == 1, f"Expected 1 removed, got {removed}"
    assert active_fl in ls._lights, "Active flash light should still be in the list"
    assert expired_fl not in ls._lights, "Expired flash light should have been removed"


def test_tick_flash_lights_returns_zero_when_none_expire():
    from playslap.lighting import FlashLight, LightingSystem

    ls = object.__new__(LightingSystem)
    ls._lights = []
    ls._gravity_warps = []

    fl = FlashLight(duration=1.0)
    fl.trigger()
    ls._lights.append(fl)

    removed = ls.tick_flash_lights(0.01)
    assert removed == 0
    assert fl in ls._lights
