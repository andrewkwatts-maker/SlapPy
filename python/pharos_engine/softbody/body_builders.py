from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np
import yaml

from .material import MATERIALS, Material
from .world import BodyMeta, SoftBodyWorld


def _builder_cfg() -> dict:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "softbody.yml"
        if candidate.is_file():
            try:
                with candidate.open("r", encoding="utf-8") as fh:
                    raw = yaml.safe_load(fh) or {}
                return (raw.get("builders") or {})
            except Exception:
                return {}
    return {}


def _resolve_material(material: str | Material) -> Material:
    if isinstance(material, Material):
        return material
    if material not in MATERIALS:
        raise KeyError(f"unknown material: {material!r}")
    return MATERIALS[material]


def make_lattice_body(
    world: SoftBodyWorld,
    material: str | Material,
    width_cells: int,
    height_cells: int,
    cell_size: float,
    position: tuple[float, float] = (0.0, 0.0),
    name: str = "lattice",
    fixed_nodes: Sequence[int] | None = None,
) -> BodyMeta:
    """Rectangular grid of nodes with N-S, E-W, and diagonal beams.

    ``width_cells`` and ``height_cells`` count the number of cells; the grid
    therefore has ``(width_cells + 1) * (height_cells + 1)`` nodes.
    """
    if width_cells < 1 or height_cells < 1:
        raise ValueError("lattice cell counts must be >= 1")

    mat = _resolve_material(material)
    cfg = _builder_cfg().get("lattice", {})
    diag_scale = float(cfg.get("diagonal_stiffness_scale", 0.7))

    nx = width_cells + 1
    ny = height_cells + 1
    px = position[0]
    py = position[1]
    xs = np.arange(nx, dtype=np.float32) * cell_size + px
    ys = np.arange(ny, dtype=np.float32) * cell_size + py
    grid_x, grid_y = np.meshgrid(xs, ys, indexing="xy")
    pos = np.stack([grid_x.ravel(), grid_y.ravel()], axis=1)

    node_count = nx * ny
    cell_area = cell_size * cell_size
    node_mass = mat.density * cell_area
    mass = np.full(node_count, node_mass, dtype=np.float32)
    damping = np.full(node_count, mat.damping, dtype=np.float32)

    fixed_arr = np.zeros(node_count, dtype=bool)
    if fixed_nodes is not None:
        for idx in fixed_nodes:
            fixed_arr[int(idx)] = True

    body_id = world.next_body_id()
    node_start = world.nodes.append(pos, mass, body_id=body_id, layer=3,
                                    damping=damping, fixed=fixed_arr)
    node_end = node_start + node_count

    def gidx(ix: int, iy: int) -> int:
        return node_start + iy * nx + ix

    horiz_a, horiz_b, horiz_len = [], [], []
    for iy in range(ny):
        for ix in range(nx - 1):
            horiz_a.append(gidx(ix, iy))
            horiz_b.append(gidx(ix + 1, iy))
            horiz_len.append(cell_size)

    vert_a, vert_b, vert_len = [], [], []
    for iy in range(ny - 1):
        for ix in range(nx):
            vert_a.append(gidx(ix, iy))
            vert_b.append(gidx(ix, iy + 1))
            vert_len.append(cell_size)

    diag_a, diag_b, diag_len = [], [], []
    diag = float(cell_size) * np.sqrt(2.0)
    for iy in range(ny - 1):
        for ix in range(nx - 1):
            diag_a.append(gidx(ix, iy))
            diag_b.append(gidx(ix + 1, iy + 1))
            diag_len.append(diag)
            diag_a.append(gidx(ix + 1, iy))
            diag_b.append(gidx(ix, iy + 1))
            diag_len.append(diag)

    axial_a = np.array(horiz_a + vert_a, dtype=np.uint32)
    axial_b = np.array(horiz_b + vert_b, dtype=np.uint32)
    axial_len = np.array(horiz_len + vert_len, dtype=np.float32)
    axial_n = axial_a.shape[0]
    axial_stiff = np.full(axial_n, mat.stiffness, dtype=np.float32)
    axial_damp = np.full(axial_n, mat.damping, dtype=np.float32)
    axial_break = np.full(axial_n, mat.break_strain, dtype=np.float32)
    axial_yield = np.full(axial_n, mat.yield_strain, dtype=np.float32)
    axial_plast = np.full(axial_n, mat.plasticity_rate, dtype=np.float32)

    d_a = np.array(diag_a, dtype=np.uint32)
    d_b = np.array(diag_b, dtype=np.uint32)
    d_len = np.array(diag_len, dtype=np.float32)
    d_n = d_a.shape[0]
    d_stiff = np.full(d_n, mat.stiffness * diag_scale, dtype=np.float32)
    d_damp = np.full(d_n, mat.damping, dtype=np.float32)
    d_break = np.full(d_n, mat.break_strain, dtype=np.float32)
    d_yield = np.full(d_n, mat.yield_strain, dtype=np.float32)
    d_plast = np.full(d_n, mat.plasticity_rate, dtype=np.float32)

    beam_start = world.beams.append(
        np.concatenate([axial_a, d_a]),
        np.concatenate([axial_b, d_b]),
        np.concatenate([axial_len, d_len]),
        np.concatenate([axial_stiff, d_stiff]),
        np.concatenate([axial_damp, d_damp]),
        np.concatenate([axial_break, d_break]),
        body_id=body_id,
        yield_strain=np.concatenate([axial_yield, d_yield]),
        plasticity_rate=np.concatenate([axial_plast, d_plast]),
    )
    beam_end = world.beams.count

    meta = BodyMeta(body_id=body_id, name=name,
                    node_slice=(node_start, node_end),
                    beam_slice=(beam_start, beam_end),
                    parameters={
                        "topology": "lattice",
                        "cell_size": float(cell_size),
                        "cell_area": float(cell_area),
                        "material_density": float(mat.density),
                        "material_name": mat.name,
                        "width_cells": int(width_cells),
                        "height_cells": int(height_cells),
                    })
    world.register_body(meta)
    return meta


def make_layered_creature(
    world: SoftBodyWorld,
    materials_per_layer: Sequence[str | Material],
    ring_counts: Sequence[int],
    radii: Sequence[float],
    position: tuple[float, float] = (0.0, 0.0),
    name: str = "creature",
) -> BodyMeta:
    """Concentric rings: ``materials_per_layer[i]`` for ring ``i``.

    Layer 0 = innermost (bone), layer N-1 = outermost (skin). Each ring is
    a polygon of ``ring_counts[i]`` nodes at radius ``radii[i]``. Tangential
    beams loop around each ring; radial beams connect adjacent rings
    pairwise on the nearest-angle match.
    """
    if not (len(materials_per_layer) == len(ring_counts) == len(radii)):
        raise ValueError("materials_per_layer, ring_counts, and radii must have equal length")
    if len(ring_counts) < 1:
        raise ValueError("need at least one ring")

    cfg = _builder_cfg().get("creature", {})
    cross_scale = float(cfg.get("cross_layer_stiffness_scale", 0.6))

    body_id = world.next_body_id()
    rings_node_ranges: list[tuple[int, int]] = []
    node_start_global = world.nodes.count

    for layer_idx, (mat_in, k, r) in enumerate(zip(materials_per_layer, ring_counts, radii)):
        mat = _resolve_material(mat_in)
        thetas = np.linspace(0.0, 2.0 * np.pi, k, endpoint=False, dtype=np.float32)
        pos = np.stack([
            position[0] + r * np.cos(thetas),
            position[1] + r * np.sin(thetas),
        ], axis=1).astype(np.float32)
        node_mass = mat.density * (r * 2.0 * np.pi / max(k, 1)) ** 2
        mass = np.full(k, max(node_mass, 1e-3), dtype=np.float32)
        damping = np.full(k, mat.damping, dtype=np.float32)
        start = world.nodes.append(pos, mass, body_id=body_id, layer=layer_idx,
                                   damping=damping)
        rings_node_ranges.append((start, start + k))

    for layer_idx, (mat_in, (start, end)) in enumerate(zip(materials_per_layer, rings_node_ranges)):
        mat = _resolve_material(mat_in)
        k = end - start
        if k < 2:
            continue
        idx = np.arange(k, dtype=np.uint32) + start
        nxt = np.roll(idx, -1)
        seg = world.nodes.pos[nxt] - world.nodes.pos[idx]
        rest = np.linalg.norm(seg, axis=1).astype(np.float32)
        world.beams.append(
            idx, nxt, rest,
            np.full(k, mat.stiffness, dtype=np.float32),
            np.full(k, mat.damping, dtype=np.float32),
            np.full(k, mat.break_strain, dtype=np.float32),
            body_id=body_id,
            yield_strain=np.full(k, mat.yield_strain, dtype=np.float32),
            plasticity_rate=np.full(k, mat.plasticity_rate, dtype=np.float32),
        )

    for layer_idx in range(len(rings_node_ranges) - 1):
        inner_start, inner_end = rings_node_ranges[layer_idx]
        outer_start, outer_end = rings_node_ranges[layer_idx + 1]
        inner_pos = world.nodes.pos[inner_start:inner_end]
        outer_pos = world.nodes.pos[outer_start:outer_end]
        if inner_pos.shape[0] == 0 or outer_pos.shape[0] == 0:
            continue
        inner_mat = _resolve_material(materials_per_layer[layer_idx])
        outer_mat = _resolve_material(materials_per_layer[layer_idx + 1])
        cross_stiff = 0.5 * (inner_mat.stiffness + outer_mat.stiffness) * cross_scale
        cross_damp = 0.5 * (inner_mat.damping + outer_mat.damping)
        cross_break = 0.5 * (inner_mat.break_strain + outer_mat.break_strain)
        cross_yield = 0.5 * (inner_mat.yield_strain + outer_mat.yield_strain)
        cross_plast = 0.5 * (inner_mat.plasticity_rate + outer_mat.plasticity_rate)

        d_inner = inner_pos - np.asarray(position, dtype=np.float32)
        d_outer = outer_pos - np.asarray(position, dtype=np.float32)
        theta_in = np.arctan2(d_inner[:, 1], d_inner[:, 0])
        theta_out = np.arctan2(d_outer[:, 1], d_outer[:, 0])

        a_list, b_list, rest_list = [], [], []
        for i, t_in in enumerate(theta_in):
            diff = (theta_out - t_in + np.pi) % (2.0 * np.pi) - np.pi
            j = int(np.argmin(np.abs(diff)))
            a_idx = inner_start + i
            b_idx = outer_start + j
            seg = world.nodes.pos[b_idx] - world.nodes.pos[a_idx]
            a_list.append(a_idx)
            b_list.append(b_idx)
            rest_list.append(float(np.linalg.norm(seg)))

        m = len(a_list)
        world.beams.append(
            np.array(a_list, dtype=np.uint32),
            np.array(b_list, dtype=np.uint32),
            np.array(rest_list, dtype=np.float32),
            np.full(m, cross_stiff, dtype=np.float32),
            np.full(m, cross_damp, dtype=np.float32),
            np.full(m, cross_break, dtype=np.float32),
            body_id=body_id,
            yield_strain=np.full(m, cross_yield, dtype=np.float32),
            plasticity_rate=np.full(m, cross_plast, dtype=np.float32),
        )

    node_end_global = world.nodes.count
    meta = BodyMeta(body_id=body_id, name=name,
                    node_slice=(node_start_global, node_end_global),
                    beam_slice=(0, world.beams.count),
                    parameters={
                        # Stash ring topology so the renderer can recover
                        # the per-layer concentric structure for texture
                        # deformation without re-deriving it from layer ids.
                        "topology": "layered_creature",
                        "ring_counts": [int(k) for k in ring_counts],
                        "ring_radii": [float(r) for r in radii],
                        "rest_center": (float(position[0]), float(position[1])),
                    })
    world.register_body(meta)
    return meta


__all__ = ["make_lattice_body", "make_layered_creature"]
