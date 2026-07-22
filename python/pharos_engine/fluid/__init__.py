"""Position-Based Fluids (PBF) — particle-based fluid sim in 2D.

Public surface:

* :class:`FluidWorld` — container for particles + materials + config.
* :class:`FluidMaterial`, :data:`MATERIALS`, :data:`WATER` — material catalog.
* :class:`ParticleSoA` — SoA particle block.
* :func:`pbf_step` — advance the fluid world one render frame.
* :func:`project_fluid_softbody_contacts` — XPBD contact projection between
  fluid particles and softbody beams (reuses the same form).
* :func:`apply_fluid_buoyancy` — per-node Archimedes upthrust for
  softbody lattices submerged in a PBF fluid.
* :class:`FluidRenderer` — small particle renderer (filled disc + halo).
"""
from __future__ import annotations

from .buoyancy import apply_fluid_buoyancy, apply_fluid_buoyancy_iterative
from .contact import project_fluid_softbody_contacts
from .kernels import poly6, poly6_coefficient, spiky_grad, spiky_grad_coefficient
from .material import (
    DUST,
    GRAVEL,
    ICE,
    LAVA,
    MATERIALS,
    SAND,
    STONE,
    WATER,
    FluidMaterial,
    load_catalog,
)
from .particle import ParticleSoA
from .render import FluidRenderConfig, FluidRenderer, render_world_gif
from .solver import pbf_step
from .surface import (
    EDGE_TABLE,
    compute_density_normals,
    extract_isolines,
    sample_density_grid,
    slerp_normals,
)
from .thermal_step import thermal_step
from .world import FluidWorld

__all__ = [
    "DUST",
    "EDGE_TABLE",
    "FluidMaterial",
    "FluidRenderConfig",
    "FluidRenderer",
    "FluidWorld",
    "GRAVEL",
    "ICE",
    "LAVA",
    "MATERIALS",
    "ParticleSoA",
    "SAND",
    "STONE",
    "WATER",
    "apply_fluid_buoyancy",
    "apply_fluid_buoyancy_iterative",
    "compute_density_normals",
    "extract_isolines",
    "load_catalog",
    "pbf_step",
    "poly6",
    "poly6_coefficient",
    "project_fluid_softbody_contacts",
    "render_world_gif",
    "sample_density_grid",
    "slerp_normals",
    "spiky_grad",
    "spiky_grad_coefficient",
    "thermal_step",
]
