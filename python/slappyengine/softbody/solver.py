from __future__ import annotations

import numpy as np

from .collision import (
    _contact_params,
    build_contact_pairs,
    project_contact_pairs,
)
from .world import SoftBodyWorld

# Detect the Rust-backed solver kernels once at import time. Mirrors the
# `_HAS_NATIVE_RASTER` switch in :mod:`slappyengine.softbody.render`.
# The three native entry points are direct ports of the numpy paths
# below; they fall back transparently if the extension is absent.
try:
    from slappyengine import _core as _native_core  # type: ignore
    _HAS_NATIVE_SOLVER = (
        hasattr(_native_core, "project_distance_constraints")
        and hasattr(_native_core, "apply_plasticity")
        and hasattr(_native_core, "mark_breaks")
    )
    # Tier 10: full-step Rust entry point — moves the substep+iter loop
    # into native code so per-iter PyO3 dispatch overhead is amortised.
    # When present we route ``step()`` through one Rust call per frame.
    _HAS_NATIVE_FULL_STEP = (
        _HAS_NATIVE_SOLVER and hasattr(_native_core, "slappyengine_step")
    )
except ImportError:  # pragma: no cover - exercised in pure-Python envs
    _native_core = None  # type: ignore
    _HAS_NATIVE_SOLVER = False
    _HAS_NATIVE_FULL_STEP = False


def step(world: SoftBodyWorld, dt: float | None = None,
         substeps: int | None = None, iters: int | None = None,
         plasticity_subcycle: bool | None = None) -> None:
    if world.nodes.count == 0:
        return
    cfg = world.config
    if dt is None:
        dt = float(cfg["default_dt"])
    if substeps is None:
        substeps = int(cfg["substeps"])
    if iters is None:
        iters = int(cfg["iters"])
    if plasticity_subcycle is None:
        plasticity_subcycle = bool(cfg.get("plasticity_subcycle", False))

    sub_dt = dt / max(substeps, 1)
    gravity = world.gravity
    eps = float(cfg["velocity_epsilon"])
    floor_y = float(cfg["floor_y"])
    floor_friction = float(cfg["floor_friction"])

    n = world.nodes
    b = world.beams

    contact_params = _contact_params(world)

    # Tier 10 fast-path: run the entire substep+iter loop in Rust. Each
    # call hands the persistent SoA arrays through writable bytearrays so
    # the kernel can mutate them in place; we copy back into n.pos/etc.
    # before returning to keep the Python-side numpy state coherent.
    if _HAS_NATIVE_FULL_STEP:
        _run_native_full_step(
            world, sub_dt, gravity, eps, floor_y, floor_friction,
            int(substeps), int(iters), bool(plasticity_subcycle),
            contact_params,
        )
        return

    free_mask = (~n.fixed)[:, None].astype(np.float32)

    if b.count > 0:
        # Per-node beam degree count — integer scatter into a fresh-zero
        # array. ``np.bincount`` is the optimal C path for this and ~5x
        # faster than two ``np.add.at`` calls; it's safe because this
        # buffer doesn't feed back into a precision-sensitive integrator.
        a64 = b.node_a.astype(np.int64, copy=False)
        b64 = b.node_b.astype(np.int64, copy=False)
        constraint_count = (np.bincount(a64, minlength=n.count)
                             + np.bincount(b64, minlength=n.count))
        node_relax = (1.0 / np.maximum(constraint_count.astype(np.float32), 1.0)).astype(np.float32)
    else:
        node_relax = np.ones(n.count, dtype=np.float32)

    for _ in range(substeps):
        n.prev_pos[:] = n.pos
        n.pos += n.vel * sub_dt * free_mask
        n.pos += 0.5 * gravity * (sub_dt * sub_dt) * free_mask

        pair_node, pair_beam, nn_a, nn_b, _ = build_contact_pairs(world, contact_params)

        if b.count > 0:
            for _it in range(iters):
                if plasticity_subcycle:
                    _apply_plasticity(n, b, sub_dt, eps)
                _project_distance_constraints(n, b, sub_dt, eps, node_relax)
                project_contact_pairs(world, sub_dt, eps,
                                      pair_node, pair_beam, nn_a, nn_b,
                                      contact_params)
                _project_floor(n, floor_y)
            if not plasticity_subcycle:
                _apply_plasticity(n, b, sub_dt, eps)
            _mark_breaks(n, b, eps)
        else:
            project_contact_pairs(world, sub_dt, eps,
                                  pair_node, pair_beam, nn_a, nn_b,
                                  contact_params)
            _project_floor(n, floor_y)

        below = n.pos[:, 1] >= floor_y

        new_vel = (n.pos - n.prev_pos) / sub_dt
        new_vel *= free_mask

        damp_factor = np.clip(1.0 - n.damping * sub_dt, 0.0, 1.0)
        new_vel *= damp_factor[:, None]

        if np.any(below):
            new_vel[below, 1] = np.minimum(new_vel[below, 1], 0.0)
            new_vel[below, 0] *= (1.0 - floor_friction)

        n.vel = new_vel.astype(np.float32, copy=False)


def _ensure_contig(arr: np.ndarray, dtype) -> np.ndarray:
    """Return a C-contiguous view of ``arr`` with the requested dtype.

    The Rust kernels read straight from the numpy buffer; the wrappers
    therefore have to guarantee both layout and dtype. When the input
    already matches we hand back the original array (zero copy).
    """
    if arr.dtype == dtype and arr.flags["C_CONTIGUOUS"]:
        return arr
    return np.ascontiguousarray(arr, dtype=dtype)


def _run_native_full_step(world: SoftBodyWorld,
                          sub_dt: float, gravity: np.ndarray,
                          eps: float, floor_y: float, floor_friction: float,
                          substeps: int, iters: int,
                          plasticity_subcycle: bool,
                          contact_params: dict) -> None:
    """Tier-10 native full-step entry point.

    Wraps the persistent SoA state in writable bytearrays, dispatches to
    ``_core.slappyengine_step`` and copies the mutated buffers back into
    the numpy arrays. The Rust kernel runs the entire substep+iter loop
    internally so per-iter PyO3 dispatch overhead is amortised across
    the whole frame (~135 µs × 160 calls → one ~3 ms call on big
    scenes).
    """
    n = world.nodes
    b = world.beams
    n_nodes = int(n.count)
    n_beams = int(b.count)

    # Ensure layout/dtype for the read-only inputs. The numpy arrays
    # are stable across the step; we send their bytes once.
    inv_mass = _ensure_contig(n.inv_mass, np.float32)
    if inv_mass is not n.inv_mass:
        n.inv_mass = inv_mass
    fixed_arr = _ensure_contig(n.fixed, np.bool_)
    if fixed_arr is not n.fixed:
        n.fixed = fixed_arr
    damping = _ensure_contig(n.damping, np.float32)
    if damping is not n.damping:
        n.damping = damping
    node_body_id = _ensure_contig(n.body_id.astype(np.uint32, copy=False),
                                  np.uint32)

    if n_beams > 0:
        node_a = _ensure_contig(b.node_a, np.uint32)
        if node_a is not b.node_a:
            b.node_a = node_a
        node_b = _ensure_contig(b.node_b, np.uint32)
        if node_b is not b.node_b:
            b.node_b = node_b
        stiffness = _ensure_contig(b.stiffness, np.float32)
        if stiffness is not b.stiffness:
            b.stiffness = stiffness
        yield_strain = _ensure_contig(b.yield_strain, np.float32)
        if yield_strain is not b.yield_strain:
            b.yield_strain = yield_strain
        plasticity_rate = _ensure_contig(b.plasticity_rate, np.float32)
        if plasticity_rate is not b.plasticity_rate:
            b.plasticity_rate = plasticity_rate
        break_strain = _ensure_contig(b.break_strain, np.float32)
        if break_strain is not b.break_strain:
            b.break_strain = break_strain
        beam_body_id = _ensure_contig(b.body_id.astype(np.uint32, copy=False),
                                       np.uint32)
        node_a_bytes = node_a.tobytes()
        node_b_bytes = node_b.tobytes()
        stiffness_bytes = stiffness.tobytes()
        yield_strain_bytes = yield_strain.tobytes()
        plasticity_rate_bytes = plasticity_rate.tobytes()
        break_strain_bytes = break_strain.tobytes()
        beam_body_bytes = beam_body_id.tobytes()
    else:
        node_a_bytes = b""
        node_b_bytes = b""
        stiffness_bytes = b""
        yield_strain_bytes = b""
        plasticity_rate_bytes = b""
        break_strain_bytes = b""
        beam_body_bytes = b""

    # Wrap writable SoA arrays in bytearrays — the Rust side mutates
    # them in place via `as_bytes_mut()`. Copy back into the numpy
    # arrays once the call returns.
    pos_buf = bytearray(np.ascontiguousarray(n.pos, dtype=np.float32).tobytes())
    prev_buf = bytearray(np.ascontiguousarray(n.prev_pos, dtype=np.float32).tobytes())
    vel_buf = bytearray(np.ascontiguousarray(n.vel, dtype=np.float32).tobytes())
    if n_beams > 0:
        rest_buf = bytearray(np.ascontiguousarray(b.rest_length, dtype=np.float32).tobytes())
        broken_buf = bytearray(np.ascontiguousarray(b.broken.view(np.uint8),
                                                     dtype=np.uint8).tobytes())
    else:
        rest_buf = bytearray()
        broken_buf = bytearray()

    contact_enabled = bool(contact_params.get("enabled", True))
    contact_thickness = float(contact_params.get("default_thickness", 0.5))
    contact_stiffness = float(contact_params.get("default_stiffness", 1.0e9))
    broadphase_cell_factor = float(contact_params.get("broadphase_cell_factor", 1.5))

    _native_core.slappyengine_step(
        pos_buf, prev_buf, vel_buf, rest_buf, broken_buf,
        inv_mass.tobytes(),
        fixed_arr.view(np.uint8).tobytes(),
        damping.tobytes(),
        node_a_bytes, node_b_bytes,
        stiffness_bytes, yield_strain_bytes, plasticity_rate_bytes, break_strain_bytes,
        node_body_id.tobytes(), beam_body_bytes,
        int(n_nodes), int(n_beams),
        int(substeps), int(iters), float(sub_dt),
        float(gravity[0]), float(gravity[1]),
        float(eps), float(floor_y), float(floor_friction),
        bool(contact_enabled), float(contact_thickness),
        float(contact_stiffness), float(broadphase_cell_factor),
        bool(plasticity_subcycle),
    )

    # Copy mutated buffers back into the numpy SoA arrays. The fresh
    # ndarrays guarantee any downstream callers that retained a
    # reference to the prior n.pos see stable values.
    n.pos = np.frombuffer(pos_buf, dtype=np.float32).reshape(n_nodes, 2).copy()
    n.prev_pos = np.frombuffer(prev_buf, dtype=np.float32).reshape(n_nodes, 2).copy()
    n.vel = np.frombuffer(vel_buf, dtype=np.float32).reshape(n_nodes, 2).copy()
    if n_beams > 0:
        b.rest_length = np.frombuffer(rest_buf, dtype=np.float32).copy()
        b.broken = np.frombuffer(broken_buf, dtype=np.uint8).astype(bool, copy=True)


def _project_distance_constraints(nodes, beams, sub_dt: float, eps: float,
                                  node_relax: np.ndarray) -> None:
    if _HAS_NATIVE_SOLVER and beams.count > 0:
        # Native fast-path. ``nodes.pos`` and ``beams.broken`` are
        # already C-contiguous by construction; the other arrays are
        # too. We pass them straight through the buffer protocol so
        # the Rust kernel writes back into the same numpy memory.
        # NOTE: the kernel walks beams in index order to preserve the
        # float-summation order of ``np.add.at`` — this is what keeps
        # ``test_block_on_block_stacks`` passing.
        pos = _ensure_contig(nodes.pos, np.float32)
        if pos is not nodes.pos:
            nodes.pos = pos
        inv_mass = _ensure_contig(nodes.inv_mass, np.float32)
        if inv_mass is not nodes.inv_mass:
            nodes.inv_mass = inv_mass
        node_a = _ensure_contig(beams.node_a, np.uint32)
        if node_a is not beams.node_a:
            beams.node_a = node_a
        node_b = _ensure_contig(beams.node_b, np.uint32)
        if node_b is not beams.node_b:
            beams.node_b = node_b
        rest = _ensure_contig(beams.rest_length, np.float32)
        if rest is not beams.rest_length:
            beams.rest_length = rest
        stiff = _ensure_contig(beams.stiffness, np.float32)
        if stiff is not beams.stiffness:
            beams.stiffness = stiff
        broken = _ensure_contig(beams.broken, np.bool_)
        if broken is not beams.broken:
            beams.broken = broken
        # numpy bool arrays are 1 byte per element but expose buffer
        # format ``?`` which pyo3 won't reinterpret as ``u8``. ``view``
        # creates a zero-copy aliased uint8 view (read-only here).
        broken_u8 = broken.view(np.uint8)
        relax = _ensure_contig(node_relax, np.float32)
        _native_core.project_distance_constraints(
            pos, inv_mass, node_a, node_b, rest, stiff, broken_u8, relax,
            float(sub_dt), float(eps),
        )
        return

    a = beams.node_a.astype(np.int64, copy=False)
    bb = beams.node_b.astype(np.int64, copy=False)
    pa = nodes.pos[a]
    pb = nodes.pos[bb]
    d = pb - pa
    length = np.sqrt(np.einsum("ij,ij->i", d, d))
    safe_len = np.maximum(length, eps)
    direction = d / safe_len[:, None]

    rest = beams.rest_length
    not_broken = ~beams.broken

    inv_dt2 = 1.0 / (sub_dt * sub_dt)
    alpha = inv_dt2 / np.maximum(beams.stiffness, eps)

    w_a = nodes.inv_mass[a]
    w_b = nodes.inv_mass[bb]
    denom = w_a + w_b + alpha
    denom = np.where(denom < eps, 1.0, denom)

    c = (length - rest) * not_broken.astype(np.float32)
    dlambda = -c / denom

    corr = direction * dlambda[:, None]
    relax_a = node_relax[a][:, None]
    relax_b = node_relax[bb][:, None]
    np.add.at(nodes.pos, a, -corr * (w_a[:, None] * relax_a))
    np.add.at(nodes.pos, bb, corr * (w_b[:, None] * relax_b))


def _project_floor(nodes, floor_y: float) -> None:
    below = nodes.pos[:, 1] > floor_y
    if np.any(below):
        nodes.pos[below, 1] = floor_y


def _apply_plasticity(nodes, beams, sub_dt: float, eps: float) -> None:
    if beams.count == 0:
        return

    if _HAS_NATIVE_SOLVER:
        pos = _ensure_contig(nodes.pos, np.float32)
        if pos is not nodes.pos:
            nodes.pos = pos
        rest = _ensure_contig(beams.rest_length, np.float32)
        if rest is not beams.rest_length:
            beams.rest_length = rest
        node_a = _ensure_contig(beams.node_a, np.uint32)
        if node_a is not beams.node_a:
            beams.node_a = node_a
        node_b = _ensure_contig(beams.node_b, np.uint32)
        if node_b is not beams.node_b:
            beams.node_b = node_b
        ys = _ensure_contig(beams.yield_strain, np.float32)
        if ys is not beams.yield_strain:
            beams.yield_strain = ys
        pr = _ensure_contig(beams.plasticity_rate, np.float32)
        if pr is not beams.plasticity_rate:
            beams.plasticity_rate = pr
        broken = _ensure_contig(beams.broken, np.bool_)
        if broken is not beams.broken:
            beams.broken = broken
        broken_u8 = broken.view(np.uint8)
        _native_core.apply_plasticity(
            pos, rest, node_a, node_b, ys, pr, broken_u8,
            float(sub_dt), float(eps),
        )
        return

    a = beams.node_a.astype(np.int64, copy=False)
    bb = beams.node_b.astype(np.int64, copy=False)
    d = nodes.pos[bb] - nodes.pos[a]
    length = np.sqrt(np.einsum("ij,ij->i", d, d))
    rest = beams.rest_length
    safe_rest = np.maximum(rest, eps)
    strain = (length - rest) / safe_rest
    over = np.abs(strain) - beams.yield_strain
    plastic = (over > 0.0) & (~beams.broken)
    if not np.any(plastic):
        return
    sign_strain = np.sign(strain).astype(np.float32)
    target_rest = length / np.maximum(1.0 + sign_strain * beams.yield_strain, eps)
    blend = (1.0 - np.exp(-beams.plasticity_rate * sub_dt)).astype(np.float32)
    new_rest = np.where(plastic, rest * (1.0 - blend) + target_rest * blend, rest)
    beams.rest_length = new_rest.astype(np.float32, copy=False)


def _mark_breaks(nodes, beams, eps: float) -> None:
    if beams.count == 0:
        return

    if _HAS_NATIVE_SOLVER:
        pos = _ensure_contig(nodes.pos, np.float32)
        if pos is not nodes.pos:
            nodes.pos = pos
        rest = _ensure_contig(beams.rest_length, np.float32)
        if rest is not beams.rest_length:
            beams.rest_length = rest
        node_a = _ensure_contig(beams.node_a, np.uint32)
        if node_a is not beams.node_a:
            beams.node_a = node_a
        node_b = _ensure_contig(beams.node_b, np.uint32)
        if node_b is not beams.node_b:
            beams.node_b = node_b
        bs = _ensure_contig(beams.break_strain, np.float32)
        if bs is not beams.break_strain:
            beams.break_strain = bs
        broken = _ensure_contig(beams.broken, np.bool_)
        if broken is not beams.broken:
            beams.broken = broken
        # Writable u8 view aliasing the bool buffer (zero-copy).
        broken_u8 = broken.view(np.uint8)
        _native_core.mark_breaks(
            pos, rest, node_a, node_b, bs, broken_u8, float(eps),
        )
        return

    not_broken = ~beams.broken
    if not np.any(not_broken):
        return
    a = beams.node_a.astype(np.int64, copy=False)
    bb = beams.node_b.astype(np.int64, copy=False)
    d = nodes.pos[bb] - nodes.pos[a]
    length = np.sqrt(np.einsum("ij,ij->i", d, d))
    rest = beams.rest_length
    deviation = np.abs(length - rest) / np.maximum(rest, eps)
    newly_broken = not_broken & (deviation > beams.break_strain)
    if np.any(newly_broken):
        beams.broken |= newly_broken


__all__ = ["step"]
