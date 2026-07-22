"""Tests for the engine-level fluid-buoyancy coupling.

Covers the three canonical Archimedes regimes:

* wood block (density 600 kg/m^3) ends up above the water surface,
* steel block (density 7800) ends up below,
* neutral block (density EXACTLY 1000) hovers near the surface.

The tests use a tiny PBF pool just to source ``surface_y`` and drive
the engine's :func:`apply_fluid_buoyancy` pass — the buoyancy force
itself is what determines where the body ends up.
"""
from __future__ import annotations

import warnings

import numpy as np
import pytest

from pharos_engine.fluid import (
    FluidWorld,
    apply_fluid_buoyancy,
    pbf_step,
)
from pharos_engine.softbody import (
    MATERIALS,
    SoftBodyWorld,
    make_lattice_body,
    step as softbody_step,
)


@pytest.fixture(autouse=True)
def _no_runtime_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error", category=RuntimeWarning)
        yield


def _make_pool() -> tuple[FluidWorld, float]:
    """Drop a small PBF water pool and let it settle. Return surface y."""
    fluid = FluidWorld()
    fluid.config["floor_y"] = 6.0
    fluid.config["wall_x_min"] = -1.8
    fluid.config["wall_x_max"] = 1.8
    fluid.config["contact"]["enabled"] = False
    fluid.add_block_of_particles(
        "water", nx=28, ny=22, spacing=0.06,
        origin=(-0.84, 2.7), jitter=0.04,
    )
    for _ in range(140):
        pbf_step(fluid)
    surface_y = float(fluid.particles.pos[:, 1].min())
    return fluid, surface_y


def _drop_block(material_name: str, surface_y: float) -> tuple[SoftBodyWorld, object]:
    sb = SoftBodyWorld()
    sb.config["floor_y"] = 6.0
    sb.config["contact"]["enabled"] = False
    meta = make_lattice_body(
        sb, material_name,
        width_cells=4, height_cells=2, cell_size=0.10,
        position=(0.0, surface_y - 0.4),
    )
    return sb, meta


def _simulate(fluid: FluidWorld, sb: SoftBodyWorld, meta,
              surface_y: float, frames: int = 200) -> float:
    dt = float(sb.config["default_dt"])
    for _ in range(frames):
        apply_fluid_buoyancy(fluid, sb, dt, body_meta=meta, surface_y=surface_y)
        softbody_step(sb)
        pbf_step(fluid)
    ns, ne = meta.node_slice
    return float(sb.nodes.pos[ns:ne, 1].mean())


def test_buoyancy_records_cell_area_on_body():
    """make_lattice_body must stash cell_area + density on body.parameters."""
    sb = SoftBodyWorld()
    meta = make_lattice_body(
        sb, "wood",
        width_cells=4, height_cells=2, cell_size=0.10,
        position=(0.0, 0.0),
    )
    assert "cell_area" in meta.parameters
    assert "material_density" in meta.parameters
    assert meta.parameters["cell_area"] == pytest.approx(0.01)
    assert meta.parameters["material_density"] == pytest.approx(
        MATERIALS["wood"].density
    )


def test_wood_block_floats_above_surface():
    """rho=600 < 1000 → wood floats with top above the water surface.

    By Archimedes the wood block (density 600, height 0.20m) reaches
    equilibrium with 60% submerged, so the top of the block sits about
    0.08m above the surface and the centroid hovers within one cell-
    height of the surface (not far below it like steel does).
    """
    fluid, surface_y = _make_pool()
    sb, meta = _drop_block("wood", surface_y)

    final_y = _simulate(fluid, sb, meta, surface_y, frames=200)

    ns, ne = meta.node_slice
    top_y = float(sb.nodes.pos[ns:ne, 1].min())  # min y = top of block in screen
    # Top of wood block must be visibly above water surface.
    assert top_y < surface_y - 0.02, (
        f"wood block fully submerged: top y={top_y:.3f} "
        f"vs surface y={surface_y:.3f}"
    )
    # Centroid stays within one cell-height of the surface (it does not sink).
    assert abs(final_y - surface_y) < 0.15, (
        f"wood centroid drifted: |{final_y:.3f} - {surface_y:.3f}| > 0.15"
    )
    assert not np.any(np.isnan(sb.nodes.pos))


def test_steel_block_sinks_below_surface():
    """rho=7800 >> 1000 → steel block centroid ends below water surface."""
    fluid, surface_y = _make_pool()
    sb, meta = _drop_block("steel", surface_y)

    final_y = _simulate(fluid, sb, meta, surface_y, frames=200)

    # Lower y = higher → "below surface" means final_y > surface_y.
    assert final_y > surface_y, (
        f"steel block did not sink: final centroid y={final_y:.3f} "
        f"vs surface y={surface_y:.3f}"
    )
    assert not np.any(np.isnan(sb.nodes.pos))


def test_neutral_density_block_hovers_near_surface():
    """A material with density == water (1000) settles near-neutral.

    We construct a temporary :class:`~pharos_engine.softbody.Material`
    instance with density 1000 (matching water) and verify the lattice
    block's centroid stays within ±0.05 m of the surface after 200
    frames.
    """
    from dataclasses import replace
    neutral = replace(MATERIALS["rubber"], name="neutral_buoyant", density=1000.0)

    fluid, surface_y = _make_pool()

    sb = SoftBodyWorld()
    sb.config["floor_y"] = 6.0
    sb.config["contact"]["enabled"] = False
    meta = make_lattice_body(
        sb, neutral,
        width_cells=4, height_cells=2, cell_size=0.10,
        position=(0.0, surface_y - 0.4),
    )

    final_y = _simulate(fluid, sb, meta, surface_y, frames=200)

    offset = abs(final_y - surface_y)
    assert offset <= 0.05, (
        f"neutral-density block did not hover near surface: "
        f"|final={final_y:.4f} - surface={surface_y:.4f}| = {offset:.4f} > 0.05"
    )
    assert not np.any(np.isnan(sb.nodes.pos))
