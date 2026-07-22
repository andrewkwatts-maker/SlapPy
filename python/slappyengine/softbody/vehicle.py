"""BeamNG-style 2D vehicle builder for :class:`SoftBodyWorld`.

A vehicle is a single body composed of three sub-structures glued
together with ordinary :class:`~slappyengine.softbody.beam.Beam`
primitives — no new constraint type:

* **Chassis** — rectangular lattice (steel-like material) that crumples
  plastically on impact.
* **Wheels** — a hub node plus ``rim_count`` rim nodes evenly spaced
  around the hub, joined by tread (circumferential), spoke (radial), and
  optional cross-spoke (torsional) beams of ``tire_rubber``.
* **Suspension** — two beams per wheel connecting the hub to the chassis:
  a vertical "spring" beam (medium stiffness, very high damping) and a
  diagonal "control-arm" beam that resists lateral motion.

All numeric defaults live in ``config/softbody.yml`` under ``vehicle:``;
material parameters live in ``material.py``.

Drivetrain torque
-----------------

Driving torque is applied per frame to the rim nodes of each drive
wheel. For a rim node at world position ``p_i`` with hub position
``p_h`` and spoke vector ``r = p_i - p_h``:

.. code-block:: text

   tangent = perpendicular(r) normalised CCW
   dv      = (torque / (|r| * m_i)) * dt
   v_i    += tangent * dv

The result is a tangential velocity kick around the hub each step,
matching ``F = T/r`` and ``dv = F/m * dt`` on each rim node, fully
vectorised across all rim nodes of all drive wheels.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import yaml

from .material import MATERIALS, Material
from .world import BodyMeta, SoftBodyWorld


def _vehicle_cfg() -> dict[str, Any]:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "softbody.yml"
        if candidate.is_file():
            try:
                with candidate.open("r", encoding="utf-8") as fh:
                    raw = yaml.safe_load(fh) or {}
                section = raw.get("vehicle") or {}
                return dict(section) if isinstance(section, dict) else {}
            except Exception:
                return {}
    return {}


def _resolve_material(material: str | Material) -> Material:
    if isinstance(material, Material):
        return material
    if material not in MATERIALS:
        raise KeyError(f"unknown material: {material!r}")
    return MATERIALS[material]


@dataclass
class WheelSpec:
    """Wheel-attachment description for a vehicle chassis.

    All fields default sensibly so a ``WheelSpec()`` is constructible.
    ``None`` for ``radius``/``rim_count``/``tire_material`` means
    "resolve from ``config/softbody.yml`` ``vehicle:`` defaults at
    build time."
    """

    x_offset: float = 0.0
    radius: float | None = None
    rim_count: int | None = None
    tire_material: str | None = None
    suspension_anchor_offset: float = 0.0


@dataclass
class VehicleSpec:
    chassis_width: int | None = None
    chassis_height: int | None = None
    chassis_cell_size: float | None = None
    chassis_material: str | None = None
    wheels: Sequence[WheelSpec] = field(default_factory=list)
    suspension_material: str | None = None
    drivetrain_mode: str | None = None


@dataclass
class VehicleHandle:
    body_id: int
    chassis_node_ids: np.ndarray
    chassis_beam_slice: tuple[int, int]
    wheel_hubs: list[int]
    wheel_rims: list[np.ndarray]
    suspension_beams: list[np.ndarray]
    drive_wheel_indices: list[int]
    max_torque: float

    def chassis_velocity(self, world: SoftBodyWorld) -> np.ndarray:
        ids = self.chassis_node_ids
        if ids.size == 0:
            return np.zeros(2, dtype=np.float32)
        return world.nodes.vel[ids].mean(axis=0).astype(np.float32)

    def chassis_position(self, world: SoftBodyWorld) -> np.ndarray:
        ids = self.chassis_node_ids
        if ids.size == 0:
            return np.zeros(2, dtype=np.float32)
        return world.nodes.pos[ids].mean(axis=0).astype(np.float32)

    def chassis_up_vector(self, world: SoftBodyWorld) -> np.ndarray:
        ids = self.chassis_node_ids
        if ids.size == 0:
            return np.array([0.0, -1.0], dtype=np.float32)
        pos = world.nodes.pos[ids]
        c = pos.mean(axis=0)
        top_mask = pos[:, 1] < c[1]
        bot_mask = ~top_mask
        if not (top_mask.any() and bot_mask.any()):
            return np.array([0.0, -1.0], dtype=np.float32)
        top_c = pos[top_mask].mean(axis=0)
        bot_c = pos[bot_mask].mean(axis=0)
        v = top_c - bot_c
        n = float(np.linalg.norm(v))
        if n < 1e-6:
            return np.array([0.0, -1.0], dtype=np.float32)
        return (v / n).astype(np.float32)

    def is_inverted(self, world: SoftBodyWorld) -> bool:
        up = self.chassis_up_vector(world)
        return bool(up[1] > 0.0)

    def apply_throttle(self, world: SoftBodyWorld, throttle: float, dt: float) -> None:
        if not self.drive_wheel_indices:
            return
        t = float(np.clip(throttle, -1.0, 1.0)) * float(self.max_torque)
        if t == 0.0:
            return
        eps = float(world.config.get("velocity_epsilon", 1.0e-9))
        for wi in self.drive_wheel_indices:
            hub = self.wheel_hubs[wi]
            rim_ids = self.wheel_rims[wi]
            if rim_ids.size == 0:
                continue
            hub_pos = world.nodes.pos[hub]
            r = world.nodes.pos[rim_ids] - hub_pos
            rlen = np.linalg.norm(r, axis=1)
            safe = np.maximum(rlen, eps)
            tangent = np.stack([-r[:, 1], r[:, 0]], axis=1) / safe[:, None]
            mass = world.nodes.mass[rim_ids]
            dv_mag = (t / (safe * np.maximum(mass, eps))) * float(dt)
            world.nodes.vel[rim_ids] += (tangent * dv_mag[:, None]).astype(np.float32)


def _resolve_spec(spec: VehicleSpec, cfg: dict[str, Any]) -> tuple[
    int, int, float, Material, Material, Sequence[WheelSpec], str
]:
    cw = int(spec.chassis_width if spec.chassis_width is not None else cfg.get("chassis_width", 6))
    ch = int(spec.chassis_height if spec.chassis_height is not None else cfg.get("chassis_height", 3))
    cs = float(spec.chassis_cell_size if spec.chassis_cell_size is not None else cfg.get("chassis_cell_size", 0.40))
    chassis_mat = _resolve_material(spec.chassis_material or cfg.get("chassis_material", "steel"))
    susp_mat = _resolve_material(spec.suspension_material or cfg.get("suspension_material", "suspension"))
    mode = (spec.drivetrain_mode or cfg.get("drivetrain_mode", "rwd")).lower()
    wheels = list(spec.wheels)
    if not wheels:
        default_r = float(cfg.get("wheel_radius", 0.35))
        front_x = cs * 1.0
        rear_x = cs * (cw - 1.0)
        wheels = [
            WheelSpec(x_offset=front_x, radius=default_r),
            WheelSpec(x_offset=rear_x, radius=default_r),
        ]
    return cw, ch, cs, chassis_mat, susp_mat, wheels, mode


def _build_chassis(
    world: SoftBodyWorld,
    body_id: int,
    mat: Material,
    width_cells: int,
    height_cells: int,
    cell_size: float,
    position: tuple[float, float],
    density_scale: float = 1.0,
) -> tuple[int, int, int]:
    nx = width_cells + 1
    ny = height_cells + 1
    xs = np.arange(nx, dtype=np.float32) * cell_size + float(position[0])
    ys = np.arange(ny, dtype=np.float32) * cell_size + float(position[1])
    gx, gy = np.meshgrid(xs, ys, indexing="xy")
    pos = np.stack([gx.ravel(), gy.ravel()], axis=1)

    n = nx * ny
    area = cell_size * cell_size
    node_mass = mat.density * area * float(density_scale)
    mass = np.full(n, node_mass, dtype=np.float32)
    damping = np.full(n, mat.damping, dtype=np.float32)
    node_start = world.nodes.append(pos, mass, body_id=body_id, layer=3, damping=damping)

    def g(ix: int, iy: int) -> int:
        return node_start + iy * nx + ix

    cfg = _vehicle_cfg()
    diag_scale = 0.7
    try:
        builders_cfg_path = Path(__file__).resolve()
        for parent in builders_cfg_path.parents:
            candidate = parent / "config" / "softbody.yml"
            if candidate.is_file():
                with candidate.open("r", encoding="utf-8") as fh:
                    raw = yaml.safe_load(fh) or {}
                diag_scale = float(((raw.get("builders") or {}).get("lattice") or {}).get(
                    "diagonal_stiffness_scale", 0.7))
                break
    except Exception:
        pass

    horiz_a, horiz_b, horiz_len = [], [], []
    for iy in range(ny):
        for ix in range(nx - 1):
            horiz_a.append(g(ix, iy))
            horiz_b.append(g(ix + 1, iy))
            horiz_len.append(cell_size)

    vert_a, vert_b, vert_len = [], [], []
    for iy in range(ny - 1):
        for ix in range(nx):
            vert_a.append(g(ix, iy))
            vert_b.append(g(ix, iy + 1))
            vert_len.append(cell_size)

    diag = float(cell_size) * np.sqrt(2.0)
    diag_a, diag_b, diag_len = [], [], []
    for iy in range(ny - 1):
        for ix in range(nx - 1):
            diag_a.append(g(ix, iy))
            diag_b.append(g(ix + 1, iy + 1))
            diag_len.append(diag)
            diag_a.append(g(ix + 1, iy))
            diag_b.append(g(ix, iy + 1))
            diag_len.append(diag)

    axial_a = np.array(horiz_a + vert_a, dtype=np.uint32)
    axial_b = np.array(horiz_b + vert_b, dtype=np.uint32)
    axial_len = np.array(horiz_len + vert_len, dtype=np.float32)
    axial_n = axial_a.shape[0]

    d_a = np.array(diag_a, dtype=np.uint32)
    d_b = np.array(diag_b, dtype=np.uint32)
    d_len = np.array(diag_len, dtype=np.float32)
    d_n = d_a.shape[0]

    beam_start = world.beams.append(
        np.concatenate([axial_a, d_a]),
        np.concatenate([axial_b, d_b]),
        np.concatenate([axial_len, d_len]),
        np.concatenate([
            np.full(axial_n, mat.stiffness, dtype=np.float32),
            np.full(d_n, mat.stiffness * diag_scale, dtype=np.float32),
        ]),
        np.concatenate([
            np.full(axial_n, mat.damping, dtype=np.float32),
            np.full(d_n, mat.damping, dtype=np.float32),
        ]),
        np.concatenate([
            np.full(axial_n, mat.break_strain, dtype=np.float32),
            np.full(d_n, mat.break_strain, dtype=np.float32),
        ]),
        body_id=body_id,
        yield_strain=np.concatenate([
            np.full(axial_n, mat.yield_strain, dtype=np.float32),
            np.full(d_n, mat.yield_strain, dtype=np.float32),
        ]),
        plasticity_rate=np.concatenate([
            np.full(axial_n, mat.plasticity_rate, dtype=np.float32),
            np.full(d_n, mat.plasticity_rate, dtype=np.float32),
        ]),
    )

    # Full corner-to-corner cross-braces — global structural rigidity
    # beyond the per-cell diagonals (which only locally triangulate). Without
    # these the chassis folds under wheel torque even at iters=4 because
    # bending modes accumulate over the whole lattice.
    corner_scale = float(cfg.get("chassis_corner_brace_scale", 1.5))
    if corner_scale > 0.0 and nx > 2 and ny > 1:
        tl = g(0, 0)
        tr = g(nx - 1, 0)
        bl = g(0, ny - 1)
        br = g(nx - 1, ny - 1)
        diag_full_a = np.array([tl, tr, tl, bl], dtype=np.uint32)
        diag_full_b = np.array([br, bl, bl + (nx - 1), br - (nx - 1)], dtype=np.uint32)
        # Compute actual rest lengths from world positions
        pa = world.nodes.pos[diag_full_a]
        pb = world.nodes.pos[diag_full_b]
        rl = np.linalg.norm(pb - pa, axis=1).astype(np.float32)
        cn = diag_full_a.shape[0]
        # Corner braces are structural reinforcement — they must NOT
        # plastically deform under sustained wheel torque. They inherit
        # steel's huge plasticity_rate by default which lets the brace
        # rest_length migrate, causing the chassis to bend permanently
        # after a few seconds of driving. Lock them rigid.
        world.beams.append(
            diag_full_a, diag_full_b, rl,
            np.full(cn, mat.stiffness * corner_scale, dtype=np.float32),
            np.full(cn, mat.damping, dtype=np.float32),
            np.full(cn, mat.break_strain * 3.0, dtype=np.float32),
            body_id=body_id,
            yield_strain=np.full(cn, mat.break_strain * 2.5, dtype=np.float32),
            plasticity_rate=np.full(cn, 0.0, dtype=np.float32),
        )

    beam_end = world.beams.count
    return node_start, n, beam_end - beam_start


def _build_wheel(
    world: SoftBodyWorld,
    body_id: int,
    tire_mat: Material,
    centre: tuple[float, float],
    radius: float,
    rim_count: int,
    cfg: dict[str, Any],
) -> tuple[int, np.ndarray]:
    hub_mass_scale = float(cfg.get("hub_mass_scale", 4.0))
    rim_mass_scale = float(cfg.get("rim_mass_scale", 1.0))
    use_cross = bool(cfg.get("use_cross_spokes", True))
    cross_scale = float(cfg.get("cross_spoke_stiffness_scale", 0.5))
    radial_scale = float(cfg.get("rim_radial_stiffness_scale", 1.0))
    circ_scale = float(cfg.get("rim_circumferential_stiffness_scale", 1.0))

    hub_area = (radius / max(rim_count, 1)) ** 2 * (2.0 * np.pi) ** 2
    hub_mass = max(tire_mat.density * hub_area * hub_mass_scale, 1e-3)
    rim_arc = 2.0 * np.pi * radius / max(rim_count, 1)
    rim_mass = max(tire_mat.density * (rim_arc ** 2) * rim_mass_scale, 1e-3)

    hub_pos = np.asarray([[centre[0], centre[1]]], dtype=np.float32)
    hub_id = world.nodes.append(
        hub_pos,
        np.array([hub_mass], dtype=np.float32),
        body_id=body_id, layer=3,
        damping=np.array([tire_mat.damping], dtype=np.float32),
    )

    thetas = np.linspace(0.0, 2.0 * np.pi, rim_count, endpoint=False, dtype=np.float32)
    rim_xy = np.stack([
        centre[0] + radius * np.cos(thetas),
        centre[1] + radius * np.sin(thetas),
    ], axis=1).astype(np.float32)
    rim_start = world.nodes.append(
        rim_xy,
        np.full(rim_count, rim_mass, dtype=np.float32),
        body_id=body_id, layer=3,
        damping=np.full(rim_count, tire_mat.damping, dtype=np.float32),
    )
    rim_ids = np.arange(rim_start, rim_start + rim_count, dtype=np.uint32)

    nxt = np.roll(rim_ids, -1)
    seg = world.nodes.pos[nxt.astype(np.int64)] - world.nodes.pos[rim_ids.astype(np.int64)]
    tread_rest = np.linalg.norm(seg, axis=1).astype(np.float32)
    world.beams.append(
        rim_ids, nxt, tread_rest,
        np.full(rim_count, tire_mat.stiffness * circ_scale, dtype=np.float32),
        np.full(rim_count, tire_mat.damping, dtype=np.float32),
        np.full(rim_count, tire_mat.break_strain, dtype=np.float32),
        body_id=body_id,
        yield_strain=np.full(rim_count, tire_mat.yield_strain, dtype=np.float32),
        plasticity_rate=np.full(rim_count, tire_mat.plasticity_rate, dtype=np.float32),
    )

    hub_arr = np.full(rim_count, hub_id, dtype=np.uint32)
    spoke_rest = np.linalg.norm(
        world.nodes.pos[rim_ids.astype(np.int64)] - world.nodes.pos[hub_id], axis=1
    ).astype(np.float32)
    world.beams.append(
        hub_arr, rim_ids, spoke_rest,
        np.full(rim_count, tire_mat.stiffness * radial_scale, dtype=np.float32),
        np.full(rim_count, tire_mat.damping, dtype=np.float32),
        np.full(rim_count, tire_mat.break_strain, dtype=np.float32),
        body_id=body_id,
        yield_strain=np.full(rim_count, tire_mat.yield_strain, dtype=np.float32),
        plasticity_rate=np.full(rim_count, tire_mat.plasticity_rate, dtype=np.float32),
    )

    if use_cross and rim_count >= 4:
        opp = rim_count // 2
        a = rim_ids
        b = np.roll(rim_ids, -opp)
        keep = np.arange(rim_count) < opp
        cross_a = a[keep]
        cross_b = b[keep]
        if cross_a.size > 0:
            cross_rest = np.linalg.norm(
                world.nodes.pos[cross_b.astype(np.int64)]
                - world.nodes.pos[cross_a.astype(np.int64)],
                axis=1,
            ).astype(np.float32)
            m = cross_a.shape[0]
            world.beams.append(
                cross_a, cross_b, cross_rest,
                np.full(m, tire_mat.stiffness * cross_scale, dtype=np.float32),
                np.full(m, tire_mat.damping, dtype=np.float32),
                np.full(m, tire_mat.break_strain, dtype=np.float32),
                body_id=body_id,
                yield_strain=np.full(m, tire_mat.yield_strain, dtype=np.float32),
                plasticity_rate=np.full(m, tire_mat.plasticity_rate, dtype=np.float32),
            )

    return int(hub_id), rim_ids


def _build_suspension(
    world: SoftBodyWorld,
    body_id: int,
    mat: Material,
    hub_id: int,
    chassis_node_start: int,
    chassis_width_nodes: int,
    chassis_height_nodes: int,
    chassis_cell_size: float,
    chassis_position: tuple[float, float],
    wheel_x: float,
    cfg: dict[str, Any],
) -> np.ndarray:
    """Triangulated 4-beam A-arm suspension that pins lateral hub motion.

    Beam layout per wheel:

    * ``spring_main`` — lower-chassis node at ``ix_main`` (the column above
      the wheel). Compresses vertically.
    * ``spring_diag`` — lower-chassis node at ``ix_diag`` (adjacent column).
      Diagonal bracing in the X-Y plane.
    * ``arm_top_main`` — upper-chassis node at ``ix_main``. Triangulates
      the hub with the chassis top edge so lateral X motion is locked.
    * ``arm_top_diag`` — upper-chassis node at ``ix_diag``. Second leg of
      the A-arm; with ``arm_top_main`` it forms a rigid lateral cage.

    The two top arms are deliberately *much* stiffer (``arm_stiffness_scale``
    defaults to ~8x material stiffness) so the wheel only moves along the
    near-vertical spring axis; longitudinal/lateral compliance comes
    entirely from the chassis flex, not the suspension.
    """
    spring_scale = float(cfg.get("spring_stiffness_scale", 1.0))
    arm_scale = float(cfg.get("arm_stiffness_scale", 8.0))
    damp_boost = float(cfg.get("suspension_damping_boost", 1.0))

    bottom_xs = np.array([
        chassis_position[0] + ix * chassis_cell_size
        for ix in range(chassis_width_nodes)
    ], dtype=np.float32)
    ix_main = int(np.clip(np.argmin(np.abs(bottom_xs - wheel_x)), 0, chassis_width_nodes - 1))
    if bottom_xs[ix_main] < wheel_x:
        ix_diag = min(ix_main + 1, chassis_width_nodes - 1)
    else:
        ix_diag = max(ix_main - 1, 0)
    if ix_diag == ix_main:
        ix_diag = min(ix_main + 1, chassis_width_nodes - 1) if ix_main == 0 \
            else max(ix_main - 1, 0)

    bottom_iy = 0
    top_iy = max(chassis_height_nodes - 1, 0)
    spring_anchor = chassis_node_start + bottom_iy * chassis_width_nodes + ix_main
    spring_diag_anchor = chassis_node_start + bottom_iy * chassis_width_nodes + ix_diag
    top_main_anchor = chassis_node_start + top_iy * chassis_width_nodes + ix_main
    top_diag_anchor = chassis_node_start + top_iy * chassis_width_nodes + ix_diag

    hub_pos = world.nodes.pos[hub_id]
    spring_rest = float(np.linalg.norm(world.nodes.pos[spring_anchor] - hub_pos))
    spring_diag_rest = float(np.linalg.norm(world.nodes.pos[spring_diag_anchor] - hub_pos))
    top_main_rest = float(np.linalg.norm(world.nodes.pos[top_main_anchor] - hub_pos))
    top_diag_rest = float(np.linalg.norm(world.nodes.pos[top_diag_anchor] - hub_pos))

    a = np.array([spring_anchor, spring_diag_anchor,
                  top_main_anchor, top_diag_anchor], dtype=np.uint32)
    b = np.array([hub_id, hub_id, hub_id, hub_id], dtype=np.uint32)
    rest = np.array(
        [spring_rest, spring_diag_rest, top_main_rest, top_diag_rest],
        dtype=np.float32,
    )
    stiff = np.array([
        mat.stiffness * spring_scale,          # main spring
        mat.stiffness * spring_scale * 0.5,    # lower diag — half-strength side brace
        mat.stiffness * arm_scale,             # upper main — laterally rigid
        mat.stiffness * arm_scale,             # upper diag — second A-arm leg
    ], dtype=np.float32)
    damp = np.array([min(mat.damping + damp_boost * 0.0, 0.99)] * 4, dtype=np.float32)
    bk = np.array([mat.break_strain] * 4, dtype=np.float32)
    ys = np.array([mat.yield_strain] * 4, dtype=np.float32)
    pr = np.array([mat.plasticity_rate] * 4, dtype=np.float32)

    beam_start = world.beams.append(
        a, b, rest, stiff, damp, bk,
        body_id=body_id, yield_strain=ys, plasticity_rate=pr,
    )
    return np.array([beam_start + i for i in range(4)], dtype=np.int64)


def _drive_wheel_indices(mode: str, n_wheels: int) -> list[int]:
    mode = mode.lower()
    if n_wheels == 0:
        return []
    if mode == "fwd":
        return [0]
    if mode == "awd" or mode == "4wd":
        return list(range(n_wheels))
    return [n_wheels - 1]


def build_vehicle(
    world: SoftBodyWorld,
    spec: VehicleSpec | None = None,
    position: tuple[float, float] = (0.0, 0.0),
    initial_velocity: tuple[float, float] = (0.0, 0.0),
    name: str = "vehicle",
) -> VehicleHandle:
    """Construct a vehicle (chassis + wheels + suspension) as one body.

    ``position`` is the top-left of the chassis lattice. Wheels are
    placed below the chassis bottom edge at ``spec.wheels[i].x_offset``
    (relative to the chassis left edge).
    """
    if spec is None:
        spec = VehicleSpec()

    cfg = _vehicle_cfg()
    cw, ch, cs, chassis_mat, susp_mat, wheel_specs, mode = _resolve_spec(spec, cfg)
    rim_count_default = int(cfg.get("rim_count", 12))
    radius_default = float(cfg.get("wheel_radius", 0.35))
    tire_mat_default = cfg.get("tire_material", "tire_rubber")

    body_id = world.next_body_id()

    node_start = world.nodes.count
    beam_start = world.beams.count

    density_scale = float(cfg.get("chassis_density_scale", 1.0))
    chassis_node_start, chassis_node_count, _ = _build_chassis(
        world, body_id, chassis_mat, cw, ch, cs, position,
        density_scale=density_scale,
    )
    chassis_width_nodes = cw + 1
    chassis_bottom_y = float(position[1]) + ch * cs

    wheel_hubs: list[int] = []
    wheel_rims: list[np.ndarray] = []
    suspension_beam_ids: list[np.ndarray] = []
    for wspec in wheel_specs:
        r = float(wspec.radius if wspec.radius is not None else radius_default)
        rc = int(wspec.rim_count if wspec.rim_count is not None else rim_count_default)
        tire_mat = _resolve_material(wspec.tire_material or tire_mat_default)
        wheel_cx = float(position[0]) + float(wspec.x_offset)
        wheel_cy = chassis_bottom_y + r + cs * 0.10
        hub_id, rim_ids = _build_wheel(
            world, body_id, tire_mat,
            (wheel_cx, wheel_cy), r, rc, cfg,
        )
        susp_ids = _build_suspension(
            world, body_id, susp_mat, hub_id,
            chassis_node_start, chassis_width_nodes, ch + 1, cs, position,
            wheel_cx, cfg,
        )
        wheel_hubs.append(hub_id)
        wheel_rims.append(rim_ids.astype(np.int64))
        suspension_beam_ids.append(susp_ids)

    node_end = world.nodes.count
    beam_end = world.beams.count

    if initial_velocity[0] != 0.0 or initial_velocity[1] != 0.0:
        world.nodes.vel[node_start:node_end] = np.asarray(
            initial_velocity, dtype=np.float32
        )

    meta = BodyMeta(
        body_id=body_id, name=name,
        node_slice=(node_start, node_end),
        beam_slice=(beam_start, beam_end),
    )
    world.register_body(meta)

    chassis_ids = np.arange(
        chassis_node_start, chassis_node_start + chassis_node_count, dtype=np.int64
    )
    drive_indices = _drive_wheel_indices(mode, len(wheel_hubs))
    max_torque = float(cfg.get("drivetrain_max_torque", 480.0))

    return VehicleHandle(
        body_id=body_id,
        chassis_node_ids=chassis_ids,
        chassis_beam_slice=(beam_start, beam_start),
        wheel_hubs=wheel_hubs,
        wheel_rims=wheel_rims,
        suspension_beams=suspension_beam_ids,
        drive_wheel_indices=drive_indices,
        max_torque=max_torque,
    )


def apply_drivetrain_torque(
    world: SoftBodyWorld,
    hub_node_id: int,
    rim_node_ids: np.ndarray,
    torque: float,
    dt: float,
) -> None:
    """Vectorised tangential velocity kick on a single wheel's rim nodes."""
    rim_ids = np.asarray(rim_node_ids, dtype=np.int64).reshape(-1)
    if rim_ids.size == 0 or torque == 0.0:
        return
    eps = float(world.config.get("velocity_epsilon", 1.0e-9))
    hub_pos = world.nodes.pos[int(hub_node_id)]
    r = world.nodes.pos[rim_ids] - hub_pos
    rlen = np.linalg.norm(r, axis=1)
    safe = np.maximum(rlen, eps)
    tangent = np.stack([-r[:, 1], r[:, 0]], axis=1) / safe[:, None]
    mass = world.nodes.mass[rim_ids]
    dv_mag = (float(torque) / (safe * np.maximum(mass, eps))) * float(dt)
    world.nodes.vel[rim_ids] += (tangent * dv_mag[:, None]).astype(np.float32)


__all__ = [
    "VehicleSpec",
    "WheelSpec",
    "VehicleHandle",
    "build_vehicle",
    "apply_drivetrain_torque",
]
