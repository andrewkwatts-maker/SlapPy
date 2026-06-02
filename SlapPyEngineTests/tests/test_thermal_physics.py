"""Tests for the standalone thermal scaffold in :mod:`physics.thermal`.

Covers per-particle relaxation, phase-change detection (melt + freeze
+ inert sand), and the per-pixel temperature field's stamp / step /
sample loop.
"""
from __future__ import annotations

import numpy as np
import pytest

from slappyengine.physics.thermal import (
    LAVA_THERMAL,
    SAND_THERMAL,
    SNOW_THERMAL,
    WATER_THERMAL,
    TemperatureField,
    ThermalProfile,
    detect_phase_changes,
    step_temperatures,
)


# ── Per-particle relaxation ─────────────────────────────────────────────────


def test_lava_cools_toward_ambient_over_time():
    """Lava starts at 1200 °C, with decay 0.05; after 100 frames of dt=1 s
    it should be meaningfully cooler — well under 1000 °C — yet still well
    above ambient (it's lava, not a cup of tea)."""
    profiles = [LAVA_THERMAL]
    T = np.array([1200.0], dtype=np.float32)
    ids = np.array([0], dtype=np.int32)

    for _ in range(100):
        step_temperatures(T, ids, profiles, dt=1.0)

    assert T[0] < 1000.0, f"lava failed to cool: T={T[0]}"
    assert T[0] > LAVA_THERMAL.ambient_temperature, (
        f"lava overshot ambient: T={T[0]}"
    )


# ── Phase change detection ──────────────────────────────────────────────────


def test_water_freezes_when_temperature_drops_below_zero():
    """A water particle at -5 °C should flip to ice via detect_phase_changes."""
    profiles = [WATER_THERMAL]
    name_to_id = {"water": 0, "ice": 1}

    T = np.array([-5.0], dtype=np.float32)
    ids = np.array([0], dtype=np.int32)

    new_ids = detect_phase_changes(T, ids, profiles, name_to_id)
    assert new_ids[0] == name_to_id["ice"], (
        f"water did not freeze to ice; got id={new_ids[0]}"
    )


def test_snow_does_not_phase_change_above_freeze_but_below_melt():
    """Snow has melt_at=2.0; at T=1 °C the threshold isn't crossed, so the
    material id stays the same."""
    profiles = [SNOW_THERMAL]
    name_to_id = {"snow": 0, "water": 1}

    T = np.array([1.0], dtype=np.float32)
    ids = np.array([0], dtype=np.int32)

    new_ids = detect_phase_changes(T, ids, profiles, name_to_id)
    assert new_ids[0] == 0, (
        f"snow flipped phase prematurely; got id={new_ids[0]}"
    )


def test_sand_thermal_no_phase_change():
    """Sand is thermally inert — neither freeze_at nor melt_at is set, so
    a particle at any temperature must keep its sand id."""
    profiles = [SAND_THERMAL]
    name_to_id = {"sand": 0, "glass": 1, "ice": 2}

    extreme_temps = np.array([-200.0, -50.0, 25.0, 500.0, 3000.0],
                              dtype=np.float32)
    ids = np.zeros(extreme_temps.shape, dtype=np.int32)

    new_ids = detect_phase_changes(extreme_temps, ids, profiles, name_to_id)
    assert np.all(new_ids == 0), (
        f"sand changed phase at some temperature: {new_ids.tolist()}"
    )


# ── 2-D temperature field ───────────────────────────────────────────────────


def test_temperature_field_stamp_creates_hot_circle():
    """stamp() with radius=5 at (32, 32) and T=500 must register T≈500 at
    the centre pixel."""
    tf = TemperatureField(width=64, height=64, ambient=20.0)
    tf.stamp(32, 32, radius=5, temperature=500.0)

    centre = tf.sample(32, 32)
    assert centre == pytest.approx(500.0, abs=1e-3), (
        f"centre temperature wrong: {centre}"
    )
    # A pixel inside the radius should also be hot.
    assert tf.sample(33, 32) == pytest.approx(500.0, abs=1e-3)
    # A pixel well outside the radius should still be ambient.
    assert tf.sample(50, 50) == pytest.approx(20.0, abs=1e-3)


def test_temperature_field_diffuses_over_time():
    """After many diffusion steps a stamped hot spot's peak must drop —
    that's the entire point of the Laplacian."""
    tf = TemperatureField(
        width=64, height=64, ambient=20.0, diffusivity=0.2,
    )
    tf.stamp(32, 32, radius=4, temperature=500.0)
    initial_peak = float(tf.grid.max())

    for _ in range(200):
        tf.step(dt=1.0)

    final_peak = float(tf.grid.max())
    assert final_peak < initial_peak, (
        f"diffusion did not lower peak: initial={initial_peak} "
        f"final={final_peak}"
    )
    # The peak must remain above ambient — energy doesn't vanish, just
    # spreads.
    assert final_peak > tf.ambient, (
        f"diffusion collapsed below ambient: final={final_peak}"
    )


# ── Extras worth keeping ────────────────────────────────────────────────────


def test_step_temperatures_zero_dt_is_no_op():
    """dt=0 must not change any temperature."""
    profiles = [LAVA_THERMAL]
    T = np.array([1200.0, 800.0, 500.0], dtype=np.float32)
    before = T.copy()
    step_temperatures(T, np.zeros(3, dtype=np.int32), profiles, dt=0.0)
    np.testing.assert_array_equal(T, before)


def test_step_temperatures_relaxes_toward_ambient_directionally():
    """Both hot and cold particles must move *toward* ambient, not past."""
    profile = ThermalProfile(
        initial_temperature=20.0,
        ambient_temperature=20.0,
        decay_per_sec=0.5,
    )
    profiles = [profile]
    T = np.array([100.0, -40.0, 20.0], dtype=np.float32)
    ids = np.zeros(3, dtype=np.int32)

    step_temperatures(T, ids, profiles, dt=0.1)
    # Hot particle cooled.
    assert T[0] < 100.0
    # Cold particle warmed.
    assert T[1] > -40.0
    # Particle already at ambient stays at ambient.
    assert T[2] == pytest.approx(20.0, abs=1e-5)


def test_detect_phase_changes_unknown_target_leaves_id():
    """If a profile names a target material that isn't in the registry,
    the particle should *not* phase-change (silent skip rather than KeyError)."""
    profiles = [WATER_THERMAL]
    # Note: 'ice' deliberately absent.
    name_to_id = {"water": 0}

    T = np.array([-50.0], dtype=np.float32)
    ids = np.array([0], dtype=np.int32)

    new_ids = detect_phase_changes(T, ids, profiles, name_to_id)
    assert new_ids[0] == 0
