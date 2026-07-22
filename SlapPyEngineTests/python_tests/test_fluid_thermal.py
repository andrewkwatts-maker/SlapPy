"""Tests for the PBF thermal pass — diffusion, ambient relaxation, phase change."""
from __future__ import annotations

import warnings

import numpy as np
import pytest

from pharos_engine.fluid import (
    FluidWorld,
    LAVA,
    ICE,
    STONE,
    WATER,
    pbf_step,
    thermal_step,
)


@pytest.fixture(autouse=True)
def _no_runtime_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error", category=RuntimeWarning)
        yield


# ── Material catalog ────────────────────────────────────────────────────────


def test_lava_has_freeze_to_stone():
    assert LAVA.freeze_temperature == 600.0
    assert LAVA.freeze_to == "stone"
    assert LAVA.thermal_conductivity > 0.0


def test_ice_has_melt_to_water():
    assert ICE.melt_temperature == 0.0
    assert ICE.melt_to == "water"
    assert ICE.thermal_conductivity > 0.0


def test_stone_has_melt_to_lava():
    assert STONE.melt_temperature == 1200.0
    assert STONE.melt_to == "lava"


# ── Per-particle temperature plumbing ──────────────────────────────────────


def test_block_inherits_material_ambient_temperature():
    """If `temperature=None`, particles default to their material's
    ambient_temperature (e.g. 20°C for water)."""
    w = FluidWorld()
    w.add_block_of_particles("water", nx=4, ny=4)
    assert w.particles.temperature.shape == (16,)
    # Water's ambient_temperature is 20.0
    assert np.allclose(w.particles.temperature, 20.0)


def test_block_accepts_explicit_temperature():
    w = FluidWorld()
    w.add_block_of_particles("lava", nx=3, ny=3, temperature=1500.0)
    assert np.allclose(w.particles.temperature, 1500.0)


# ── thermal_step in isolation ───────────────────────────────────────────────


def test_thermal_step_no_op_when_no_neighbours():
    """Single particle: no neighbour pairs → diffusion does nothing, but
    ambient relaxation still pulls toward room temp."""
    w = FluidWorld()
    w.add_block_of_particles("water", nx=1, ny=1, temperature=80.0)
    i_idx = np.zeros((0,), dtype=np.int64)
    j_idx = np.zeros((0,), dtype=np.int64)
    thermal_step(w, i_idx, j_idx, sub_dt=0.1, ambient_rate=1.0)
    # Ambient = 20. With rate=1.0, dt=0.1: T_new = (80 + 0.1*20) / 1.1 ≈ 74.5
    assert w.particles.temperature[0] == pytest.approx(74.545, abs=0.1)


def test_thermal_step_diffuses_between_neighbours():
    """Hot particle + cold particle → temperatures move toward each other."""
    w = FluidWorld()
    w.add_block_of_particles("water", nx=1, ny=1,
                              origin=(0.0, 0.0), temperature=80.0)
    w.add_block_of_particles("water", nx=1, ny=1,
                              origin=(0.1, 0.0), temperature=0.0)
    i_idx = np.array([0], dtype=np.int64)
    j_idx = np.array([1], dtype=np.int64)
    t0_a = float(w.particles.temperature[0])
    t0_b = float(w.particles.temperature[1])
    thermal_step(w, i_idx, j_idx, sub_dt=0.05, diffusion_rate=10.0, ambient_rate=0.0)
    t1_a = float(w.particles.temperature[0])
    t1_b = float(w.particles.temperature[1])
    # Hot cools, cold warms.
    assert t1_a < t0_a
    assert t1_b > t0_b
    # Conservation: mean unchanged (mass-weighted; equal masses here).
    assert (t1_a + t1_b) / 2.0 == pytest.approx((t0_a + t0_b) / 2.0, abs=0.1)


def test_thermal_step_returns_phase_change_count():
    """A hot ice particle should melt → flip to water material."""
    w = FluidWorld()
    w.add_block_of_particles("ice", nx=1, ny=1, temperature=50.0)  # well above melt 0°C
    water_id_before = None  # may not exist yet
    i_idx = np.zeros((0,), dtype=np.int64)
    j_idx = np.zeros((0,), dtype=np.int64)
    # Have to ensure WATER is in the world's materials list for the
    # phase-change lookup. Add a water block then remove its particles
    # by resetting count (easier: just register the material via API).
    from pharos_engine.fluid import WATER as _W
    if _W not in w.materials:
        w.materials.append(_W)
    n_changes = thermal_step(w, i_idx, j_idx, sub_dt=0.001,
                              diffusion_rate=0.0, ambient_rate=0.0)
    assert n_changes == 1
    # Material id should now point at water.
    water_id = w.materials.index(_W)
    assert int(w.particles.material_id[0]) == water_id


def test_lava_block_cools_over_time():
    """A lava blob isolated in cold air should cool monotonically.
    Emits a GIF of the cooling via the fluid renderer."""
    from python.tests._visual_snapshot import output_dir, save_softbody_sequence
    from pharos_engine.fluid import FluidRenderer, FluidRenderConfig

    w = FluidWorld()
    w.config["gravity"] = [0.0, 0.0]
    # Position the lava block inside the default world bounds; the fluid
    # solver clamps positions to walls/floor at module-default values.
    w.config["floor_y"] = 5.0
    w.config["wall_x_min"] = -1.5
    w.config["wall_x_max"] = 1.5
    w.add_block_of_particles("lava", nx=4, ny=4, spacing=0.08,
                              origin=(-0.16, 2.0), temperature=1500.0)
    initial_mean = float(w.particles.temperature.mean())
    renderer = FluidRenderer(config=FluidRenderConfig.from_yaml(
        {"width": 280, "height": 220}))
    view_box = (-1.6, 1.5, 1.6, 3.5)

    frames = []
    for _ in range(100):
        pbf_step(w)
        frames.append(renderer.render(w, view_box=view_box))
    save_softbody_sequence(frames, output_dir("fluid_thermal") / "lava_cools.gif",
                           fps=20)

    final_mean = float(w.particles.temperature.mean())
    assert final_mean < initial_mean, (
        f"lava did not cool: initial {initial_mean:.1f} final {final_mean:.1f}"
    )


def test_lava_freezes_to_stone_when_cooled_enough():
    """A lava blob with no heat source eventually crosses 600°C and freezes."""
    w = FluidWorld()
    w.config["gravity"] = [0.0, 0.0]
    w.add_block_of_particles("lava", nx=2, ny=2, temperature=700.0)
    # Ensure STONE is registered so the phase-change lookup finds it.
    if STONE not in w.materials:
        w.materials.append(STONE)
    # Run many ticks; ambient is 20°C so all 4 particles will eventually freeze.
    for _ in range(200):
        pbf_step(w)
    stone_id = w.materials.index(STONE)
    n_stone = int(np.sum(w.particles.material_id == stone_id))
    assert n_stone > 0, "no lava particles froze to stone"


def test_ice_melts_to_water_in_warm_environment():
    """Ice in a warm world melts to water particles."""
    w = FluidWorld()
    w.config["gravity"] = [0.0, 0.0]
    w.add_block_of_particles("ice", nx=2, ny=2, temperature=-10.0)
    if WATER not in w.materials:
        w.materials.append(WATER)
    # Ambient warms the ice particles past their 0°C melt point.
    for _ in range(150):
        pbf_step(w)
    water_id = w.materials.index(WATER)
    n_water = int(np.sum(w.particles.material_id == water_id))
    assert n_water > 0, "no ice particles melted to water"


def test_mass_conserved_across_phase_changes():
    """Phase changes flip material_id but never spawn or remove particles."""
    w = FluidWorld()
    w.config["gravity"] = [0.0, 0.0]
    w.add_block_of_particles("lava", nx=3, ny=3, temperature=1500.0)
    if STONE not in w.materials:
        w.materials.append(STONE)
    n_before = w.particles.count
    for _ in range(300):
        pbf_step(w)
    assert w.particles.count == n_before, "particle count changed during phase changes"


def test_thermal_disabled_via_config():
    """Setting thermal.enabled=False bypasses the pass entirely."""
    w = FluidWorld()
    w.config["gravity"] = [0.0, 0.0]
    w.config["thermal"]["enabled"] = False
    w.add_block_of_particles("lava", nx=2, ny=2, temperature=1500.0)
    initial = float(w.particles.temperature.mean())
    for _ in range(20):
        pbf_step(w)
    final = float(w.particles.temperature.mean())
    # No cooling at all.
    assert abs(final - initial) < 1.0, (
        f"thermal pass ran despite disabled: {initial} → {final}"
    )
