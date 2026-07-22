from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .beam import BeamSoA
from .node import NodeSoA


def _config_path() -> Path | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "softbody.yml"
        if candidate.is_file():
            return candidate
    return None


def _load_world_config() -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "gravity": (0.0, 9.81),
        "default_dt": 1.0 / 60.0,
        "substeps": 8,
        "iters": 4,
        "floor_y": 5.0,
        "velocity_epsilon": 1.0e-9,
        "rest_velocity_threshold": 0.01,
        "floor_friction": 0.4,
        "plasticity_subcycle": False,
    }
    contact_defaults: dict[str, Any] = {
        "enabled": True,
        "default_thickness": 0.04,
        "default_stiffness": 1.0e9,
        "broadphase_cell_factor": 1.5,
    }
    p = _config_path()
    if p is None:
        out = dict(defaults)
        out["contact"] = contact_defaults
        return out
    try:
        with p.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except Exception:
        out = dict(defaults)
        out["contact"] = contact_defaults
        return out
    section = raw.get("world") or {}
    out = dict(defaults)
    if isinstance(section, dict):
        for key in defaults:
            if key in section:
                out[key] = section[key]
    contact_section = raw.get("contact") or {}
    contact_out = dict(contact_defaults)
    if isinstance(contact_section, dict):
        for key in contact_defaults:
            if key in contact_section:
                contact_out[key] = contact_section[key]
    out["contact"] = contact_out
    return out


@dataclass
class BodyMeta:
    body_id: int
    name: str = ""
    node_slice: tuple[int, int] = (0, 0)
    beam_slice: tuple[int, int] = (0, 0)
    # Free-form per-body metadata. Builders may stash topology/material
    # details here (e.g. ``cell_area``, ``material_density``) so downstream
    # systems (buoyancy, etc.) can recover them without re-reading config.
    parameters: dict[str, Any] = field(default_factory=dict)

    # ----- convenience methods (sugar over the SoA arrays) -----

    def anchor(self, world: "SoftBodyWorld") -> "BodyMeta":
        """Pin every node in this body (fixed=True, inv_mass=0). Chainable."""
        ns, ne = self.node_slice
        if ne > ns:
            world.nodes.fixed[ns:ne] = True
            world.nodes.inv_mass[ns:ne] = 0.0
        return self

    def kick(self, world: "SoftBodyWorld",
             vx: float = 0.0, vy: float = 0.0,
             *, twist: float = 0.0) -> "BodyMeta":
        """Set uniform velocity (+ optional twist) on this body. Chainable.

        ``twist`` adds per-node x-velocity proportional to (x - centroid_x),
        producing a spin around the vertical axis — useful so a falling cube
        doesn't impact perfectly flat.
        """
        ns, ne = self.node_slice
        if ne > ns:
            world.nodes.vel[ns:ne, 0] = float(vx)
            world.nodes.vel[ns:ne, 1] = float(vy)
            if twist:
                cx = float(world.nodes.pos[ns:ne, 0].mean())
                world.nodes.vel[ns:ne, 0] += (
                    world.nodes.pos[ns:ne, 0] - cx) * float(twist)
        return self

    def centroid(self, world: "SoftBodyWorld") -> tuple[float, float]:
        """Geometric centroid of this body's nodes."""
        ns, ne = self.node_slice
        if ne <= ns:
            return (0.0, 0.0)
        return (float(world.nodes.pos[ns:ne, 0].mean()),
                float(world.nodes.pos[ns:ne, 1].mean()))

    def translate(self, world: "SoftBodyWorld",
                  dx: float, dy: float) -> "BodyMeta":
        """Shift every node by (dx, dy); also shifts prev_pos so the XPBD
        integrator doesn't see a fictitious velocity from the displacement.
        Chainable.
        """
        ns, ne = self.node_slice
        if ne > ns:
            world.nodes.pos[ns:ne, 0] += float(dx)
            world.nodes.pos[ns:ne, 1] += float(dy)
            world.nodes.prev_pos[ns:ne, 0] += float(dx)
            world.nodes.prev_pos[ns:ne, 1] += float(dy)
        return self

    def node_count(self) -> int:
        return max(0, self.node_slice[1] - self.node_slice[0])

    def beam_count(self) -> int:
        return max(0, self.beam_slice[1] - self.beam_slice[0])


@dataclass
class SoftBodyWorld:
    nodes: NodeSoA = field(default_factory=NodeSoA)
    beams: BeamSoA = field(default_factory=BeamSoA)
    bodies: list[BodyMeta] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=_load_world_config)

    def next_body_id(self) -> int:
        return len(self.bodies)

    def register_body(self, meta: BodyMeta) -> None:
        self.bodies.append(meta)

    def add_body(self, meta: BodyMeta) -> BodyMeta:
        """Alias for :meth:`register_body`; returns the meta for chaining.

        Builders already call ``register_body`` internally. This method exists
        as the canonical "add a prebuilt body" entry point per
        ``docs/softbody_design.md``.
        """
        self.register_body(meta)
        return meta

    @property
    def gravity(self) -> np.ndarray:
        g = self.config["gravity"]
        return np.asarray([float(g[0]), float(g[1])], dtype=np.float32)

    @property
    def floor_y(self) -> float:
        return float(self.config["floor_y"])

    def connected_components(self, body_id: int | None = None) -> list[set[int]]:
        """Union-Find over live (non-broken) beams; returns lists of node-index sets.

        Useful for tests that need to assert "body split into >= 2 pieces".
        If ``body_id`` is given, only that body's nodes/beams are considered.
        """
        if body_id is None:
            node_mask = np.ones(self.nodes.count, dtype=bool)
            beam_mask = ~self.beams.broken
        else:
            node_mask = self.nodes.body_id == body_id
            beam_mask = (~self.beams.broken) & (self.beams.body_id == body_id)
        node_indices = np.nonzero(node_mask)[0]
        parent = {int(i): int(i) for i in node_indices}

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry

        a_arr = self.beams.node_a[beam_mask]
        b_arr = self.beams.node_b[beam_mask]
        for a, b in zip(a_arr.tolist(), b_arr.tolist()):
            if a in parent and b in parent:
                union(a, b)

        groups: dict[int, set[int]] = {}
        for i in node_indices.tolist():
            r = find(int(i))
            groups.setdefault(r, set()).add(int(i))
        return list(groups.values())


__all__ = ["SoftBodyWorld", "BodyMeta"]
