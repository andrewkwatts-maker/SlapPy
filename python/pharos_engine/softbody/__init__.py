"""BeamNG-style soft-body lattice physics — XPBD distance constraints in 2D.

Public surface:

* :class:`SoftBodyWorld` — container for nodes/beams/bodies.
* :class:`Material`, :data:`MATERIALS` — material catalog.
* :func:`make_lattice_body`, :func:`make_layered_creature` — topology builders.
* :func:`step` — advance the world one render frame (default substeps/iters
  pulled from ``config/softbody.yml``).
"""
from __future__ import annotations

from .beam import BeamSoA
from .body_builders import make_lattice_body, make_layered_creature
from .collision import (
    SpatialHash,
    build_contact_pairs,
    project_contact_pairs,
    resolve_contacts,
)
from .material import MATERIALS, Material, load_catalog
from .node import NodeSoA
from .render import SoftBodyRenderConfig, SoftBodyRenderer, render_world_gif
from .solver import step
from .vehicle import (
    VehicleHandle,
    VehicleSpec,
    WheelSpec,
    apply_drivetrain_torque,
    build_vehicle,
)
from .world import BodyMeta, SoftBodyWorld

__all__ = [
    "BeamSoA",
    "BodyMeta",
    "MATERIALS",
    "Material",
    "NodeSoA",
    "SoftBodyRenderConfig",
    "SoftBodyRenderer",
    "SoftBodyWorld",
    "SpatialHash",
    "VehicleHandle",
    "VehicleSpec",
    "WheelSpec",
    "apply_drivetrain_torque",
    "build_contact_pairs",
    "build_vehicle",
    "load_catalog",
    "make_lattice_body",
    "make_layered_creature",
    "project_contact_pairs",
    "render_world_gif",
    "resolve_contacts",
    "step",
]
