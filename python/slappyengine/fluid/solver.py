from __future__ import annotations

import numpy as np

from .kernels import (
    poly6,
    poly6_coefficient,
    poly6_scalar,
    spiky_grad,
)
from .material import FluidMaterial
from .thermal_step import thermal_step
from .world import FluidWorld

# Detect the Rust-backed PBF kernels once at import time. Falls back to
# the pure-numpy paths if `_core` is absent or the symbols aren't present
# (older _core builds without ``pbf_solver.rs``). Mirror the
# `_HAS_NATIVE_RASTER` pattern in `softbody/render.py`.
try:
    from slappyengine import _core as _native_core  # type: ignore
    _HAS_NATIVE_PBF = (
        hasattr(_native_core, "build_neighbour_table")
        and hasattr(_native_core, "pbf_iter")
    )
    # Tier 10: full-step Rust entry point — moves the substep+iter loop
    # for PBF into native code so per-iter dispatch overhead is amortised.
    _HAS_NATIVE_FULL_STEP = (
        _HAS_NATIVE_PBF and hasattr(_native_core, "pbf_step_full")
    )
except ImportError:  # pragma: no cover - exercised in pure-Python envs
    _native_core = None  # type: ignore
    _HAS_NATIVE_PBF = False
    _HAS_NATIVE_FULL_STEP = False


def _build_neighbour_table(pos: np.ndarray, h: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fully vectorised neighbour gather (no per-particle Python loop)."""
    n = pos.shape[0]
    if n == 0:
        empty_i = np.empty(0, dtype=np.int64)
        empty_f = np.empty((0, 2), dtype=np.float32)
        return empty_i, empty_i, empty_f
    if _HAS_NATIVE_PBF:
        # Rust spatial-hash 9-cell gather. Returns packed int64 bytes for
        # i_idx / j_idx; we reconstitute as numpy views and recompute the
        # delta vector for the (rare) caller that wants it.
        pos_f32 = np.ascontiguousarray(pos, dtype=np.float32)
        i_b, j_b = _native_core.build_neighbour_table(pos_f32.tobytes(), float(h), int(n))
        i_arr = np.frombuffer(i_b, dtype=np.int64)
        j_arr = np.frombuffer(j_b, dtype=np.int64)
        if i_arr.size == 0:
            empty_f = np.empty((0, 2), dtype=np.float32)
            return i_arr.copy(), j_arr.copy(), empty_f
        # Recompute delta on the Python side (cheap, vectorised, and the
        # caller may not even consume this).
        delta = (pos_f32[i_arr] - pos_f32[j_arr]).astype(np.float32, copy=False)
        return i_arr.copy(), j_arr.copy(), delta
    cell = float(h)
    inv_cell = 1.0 / cell
    ix = np.floor(pos[:, 0] * inv_cell).astype(np.int64)
    iy = np.floor(pos[:, 1] * inv_cell).astype(np.int64)

    P1 = np.int64(73856093)
    P2 = np.int64(19349663)
    own_key = (ix * P1) ^ (iy * P2)

    order = np.argsort(own_key, kind="stable")
    key_sorted = own_key[order]

    offsets = np.array([[-1, -1], [-1, 0], [-1, 1],
                        [0, -1],  [0, 0],  [0, 1],
                        [1, -1],  [1, 0],  [1, 1]], dtype=np.int64)
    qx = ix[:, None] + offsets[None, :, 0]
    qy = iy[:, None] + offsets[None, :, 1]
    qkey = (qx * P1) ^ (qy * P2)

    lo = np.searchsorted(key_sorted, qkey, side="left")
    hi = np.searchsorted(key_sorted, qkey, side="right")
    counts = (hi - lo).astype(np.int64)
    total = int(counts.sum())
    if total == 0:
        empty_i = np.empty(0, dtype=np.int64)
        empty_f = np.empty((0, 2), dtype=np.float32)
        return empty_i, empty_i, empty_f
    counts_flat = counts.ravel()
    lo_flat = lo.ravel()

    i_repeat = np.repeat(np.arange(n, dtype=np.int64), counts.sum(axis=1))

    starts = np.cumsum(counts_flat) - counts_flat
    local_idx = np.arange(total, dtype=np.int64) - np.repeat(starts, counts_flat)
    base = np.repeat(lo_flat, counts_flat)
    j_local = base + local_idx
    j_idx = order[j_local]

    keep = i_repeat != j_idx
    i_all = i_repeat[keep]
    j_all = j_idx[keep]
    delta = pos[i_all] - pos[j_all]
    r2 = np.einsum("ij,ij->i", delta, delta)
    within = r2 < (h * h)
    return i_all[within], j_all[within], delta[within].astype(np.float32, copy=False)


def _project_boundaries(pos: np.ndarray, world: FluidWorld) -> None:
    floor_y = world.floor_y
    wx_min = world.wall_x_min
    wx_max = world.wall_x_max
    ceil_y = world.ceiling_y
    np.minimum(pos[:, 1], floor_y, out=pos[:, 1])
    np.maximum(pos[:, 1], ceil_y, out=pos[:, 1])
    np.maximum(pos[:, 0], wx_min, out=pos[:, 0])
    np.minimum(pos[:, 0], wx_max, out=pos[:, 0])


def _resolve_material(world: FluidWorld) -> FluidMaterial:
    if world.particles.count == 0:
        return world.materials[0]
    ids = world.particles.material_id
    counts = np.bincount(ids, minlength=len(world.materials))
    return world.materials[int(np.argmax(counts))]


def _per_particle_material_arrays(world: FluidWorld) -> tuple[np.ndarray, np.ndarray]:
    """Returns (is_granular_per_particle, friction_coef_per_particle)."""
    n_mats = len(world.materials)
    gran = np.zeros(n_mats, dtype=bool)
    mu = np.zeros(n_mats, dtype=np.float32)
    for k, m in enumerate(world.materials):
        gran[k] = bool(m.is_granular)
        mu[k] = float(m.friction_coef)
    ids = world.particles.material_id.astype(np.int64)
    return gran[ids], mu[ids]


def friction_pass(
    world: FluidWorld,
    i_idx: np.ndarray,
    j_idx: np.ndarray,
    prev_pos: np.ndarray,
    sub_dt: float,
) -> None:
    p = world.particles
    if p.count == 0 or i_idx.size == 0:
        return
    g_cfg = world.config.get("granular", {})
    if not bool(g_cfg.get("enabled", True)):
        return

    # Build per-material granular flag + friction-coef lookup tables
    # (one entry per material in the world catalog). The Rust kernel
    # indexes these by `material_id[i]` to match Python's
    # ``is_gran[i_idx] & is_gran[j_idx]`` mask.
    n_mats = len(world.materials)
    gran_table = np.zeros(n_mats, dtype=np.uint8)
    mu_table = np.zeros(n_mats, dtype=np.float32)
    for k, m in enumerate(world.materials):
        gran_table[k] = 1 if bool(m.is_granular) else 0
        mu_table[k] = float(m.friction_coef)
    if not gran_table.any():
        return

    mat = _resolve_material(world)
    h = float(mat.kernel_radius)
    radius_factor = float(g_cfg.get("contact_radius_factor", 0.55))
    contact_radius = radius_factor * h
    dt_scale = float(g_cfg.get("friction_dt_scale", 1.0))
    tan_eps = float(g_cfg.get("tangential_velocity_eps", 1.0e-6))
    normal_proxy_floor_factor = float(g_cfg.get("normal_proxy_floor_factor", 0.5))
    eps = float(world.config["velocity_epsilon"])

    if _HAS_NATIVE_PBF and hasattr(_native_core, "friction_pass_rs"):
        # Fast path: Rust walks pairs once, applying sequential
        # corrections directly into a bytearray-backed view of p.pos.
        n_p = p.count
        pos_buf = bytearray(np.ascontiguousarray(p.pos, dtype=np.float32).tobytes())
        pos_view = np.frombuffer(pos_buf, dtype=np.float32).reshape(n_p, 2)
        prev_bytes = np.ascontiguousarray(prev_pos, dtype=np.float32).tobytes()
        inv_mass_bytes = np.ascontiguousarray(p.inv_mass, dtype=np.float32).tobytes()
        mat_id_bytes = np.ascontiguousarray(p.material_id, dtype=np.uint8).tobytes()
        gran_bytes = gran_table.tobytes()
        mu_bytes = mu_table.tobytes()
        i_bytes = np.ascontiguousarray(i_idx, dtype=np.int64).tobytes()
        j_bytes = np.ascontiguousarray(j_idx, dtype=np.int64).tobytes()
        _native_core.friction_pass_rs(
            pos_buf, prev_bytes, inv_mass_bytes, mat_id_bytes,
            gran_bytes, mu_bytes,
            i_bytes, j_bytes,
            float(contact_radius), float(eps), float(tan_eps),
            float(dt_scale), float(normal_proxy_floor_factor),
        )
        p.pos = np.array(pos_view, dtype=np.float32, copy=True)
        return

    is_gran, mu = _per_particle_material_arrays(world)
    if not np.any(is_gran):
        return

    pair_mask = is_gran[i_idx] & is_gran[j_idx] & (i_idx < j_idx)
    if not np.any(pair_mask):
        return

    ii = i_idx[pair_mask]
    jj = j_idx[pair_mask]

    delta = p.pos[ii] - p.pos[jj]
    r = np.linalg.norm(delta, axis=1)
    overlap_mask = (r < contact_radius) & (r > eps)
    if not np.any(overlap_mask):
        return

    ii = ii[overlap_mask]
    jj = jj[overlap_mask]
    delta = delta[overlap_mask]
    r = r[overlap_mask]

    n_dir = delta / r[:, None]
    rel_dx = (p.pos[ii] - prev_pos[ii]) - (p.pos[jj] - prev_pos[jj])
    rel_dx_n = np.einsum("ij,ij->i", rel_dx, n_dir)
    dx_t = rel_dx - n_dir * rel_dx_n[:, None]
    t_mag = np.linalg.norm(dx_t, axis=1)
    active = t_mag > tan_eps
    if not np.any(active):
        return

    ii = ii[active]
    jj = jj[active]
    n_dir = n_dir[active]
    dx_t = dx_t[active]
    t_mag = t_mag[active]
    r_act = r[active]

    pen = contact_radius - r_act
    mu_pair = 0.5 * (mu[ii] + mu[jj])
    normal_proxy_floor = normal_proxy_floor_factor * contact_radius
    normal_proxy = pen + normal_proxy_floor
    cap = mu_pair * normal_proxy
    s = np.minimum(t_mag, cap) * dt_scale
    t_dir = dx_t / t_mag[:, None]

    w_i = p.inv_mass[ii]
    w_j = p.inv_mass[jj]
    w_sum = w_i + w_j
    inv_w_sum = 1.0 / np.maximum(w_sum, eps)
    corr_i = -t_dir * (s * w_i * inv_w_sum)[:, None]
    corr_j = t_dir * (s * w_j * inv_w_sum)[:, None]

    np.add.at(p.pos, ii, corr_i.astype(np.float32))
    np.add.at(p.pos, jj, corr_j.astype(np.float32))


def _run_native_pbf_full_step(
    world: FluidWorld,
    sub_dt: float,
    substeps: int,
    iters: int,
    gravity: np.ndarray,
    eps: float,
    max_vel: float,
    h: float,
    rho0: float,
    relax: float,
    k_corr: float,
    n_corr: float,
    dq_w: float,
    cohesion_on: bool,
    visc: float,
    xsph_on: bool,
    density_floor: float,
) -> None:
    """Tier-10 native PBF full-step.

    Mirrors the Python loop body 1:1 — substep prediction, neighbour
    build, density-projection iters, friction pass, thermal pass,
    velocity update with XSPH viscosity and clamping. Runs entirely in
    Rust so PyO3 dispatch overhead is paid once per frame.
    """
    p = world.particles
    cfg = world.config
    n_p = int(p.count)

    g_cfg = cfg.get("granular", {})
    granular_enabled = bool(g_cfg.get("enabled", True))
    radius_factor = float(g_cfg.get("contact_radius_factor", 0.55))
    contact_radius = radius_factor * h
    dt_scale_g = float(g_cfg.get("friction_dt_scale", 1.0))
    tan_eps = float(g_cfg.get("tangential_velocity_eps", 1.0e-6))
    normal_proxy_floor_factor = float(
        g_cfg.get("normal_proxy_floor_factor", 0.5)
    )

    thermal_cfg = cfg.get("thermal", {})
    thermal_enabled = bool(thermal_cfg.get("enabled", True))
    diffusion_rate = float(thermal_cfg.get("diffusion_rate", 5.0))
    ambient_rate = float(thermal_cfg.get("ambient_rate", 0.2))

    # Build per-material lookup tables for granular + thermal. These are
    # tiny (n_materials × few bytes) and constant across substeps.
    n_mats = len(world.materials)
    gran_table = np.zeros(n_mats, dtype=np.uint8)
    mu_table = np.zeros(n_mats, dtype=np.float32)
    cond_tab = np.zeros(n_mats, dtype=np.float32)
    amb_tab = np.full(n_mats, 20.0, dtype=np.float32)
    melt_t_tab = np.full(n_mats, 1.0e9, dtype=np.float32)
    freeze_t_tab = np.full(n_mats, -1.0e9, dtype=np.float32)
    melt_to_tab = np.full(n_mats, -1, dtype=np.int32)
    freeze_to_tab = np.full(n_mats, -1, dtype=np.int32)
    name_to_id = {m.name: i for i, m in enumerate(world.materials)}
    for i, m in enumerate(world.materials):
        gran_table[i] = 1 if bool(m.is_granular) else 0
        mu_table[i] = float(m.friction_coef)
        cond_tab[i] = float(getattr(m, "thermal_conductivity", 0.0))
        amb_tab[i] = float(getattr(m, "ambient_temperature", 20.0))
        melt_t_tab[i] = float(getattr(m, "melt_temperature", 1.0e9))
        freeze_t_tab[i] = float(getattr(m, "freeze_temperature", -1.0e9))
        mt = getattr(m, "melt_to", "")
        if mt and mt in name_to_id:
            melt_to_tab[i] = int(name_to_id[mt])
        ft = getattr(m, "freeze_to", "")
        if ft and ft in name_to_id:
            freeze_to_tab[i] = int(name_to_id[ft])

    # Wrap mutable SoA arrays in bytearrays — the Rust kernel mutates
    # them in place, then we copy back into the numpy arrays so any
    # caller that retained a prior reference sees stable values.
    pos_buf = bytearray(np.ascontiguousarray(p.pos, dtype=np.float32).tobytes())
    prev_buf = bytearray(np.ascontiguousarray(p.prev_pos, dtype=np.float32).tobytes())
    vel_buf = bytearray(np.ascontiguousarray(p.vel, dtype=np.float32).tobytes())
    temp_buf = bytearray(np.ascontiguousarray(p.temperature, dtype=np.float32).tobytes())
    mat_buf = bytearray(np.ascontiguousarray(p.material_id, dtype=np.uint8).tobytes())

    mass_bytes = np.ascontiguousarray(p.mass, dtype=np.float32).tobytes()
    inv_mass_bytes = np.ascontiguousarray(p.inv_mass, dtype=np.float32).tobytes()

    floor_y = world.floor_y
    wx_min = world.wall_x_min
    wx_max = world.wall_x_max
    ceil_y = world.ceiling_y

    _native_core.pbf_step_full(
        pos_buf, prev_buf, vel_buf, temp_buf, mat_buf,
        mass_bytes, inv_mass_bytes,
        gran_table.tobytes(), mu_table.tobytes(),
        cond_tab.tobytes(), amb_tab.tobytes(),
        melt_t_tab.tobytes(), freeze_t_tab.tobytes(),
        melt_to_tab.tobytes(), freeze_to_tab.tobytes(),
        int(n_p), int(substeps), int(iters), float(sub_dt),
        float(gravity[0]), float(gravity[1]),
        float(eps), float(max_vel),
        float(floor_y), float(wx_min), float(wx_max), float(ceil_y),
        float(h), float(rho0), float(relax), float(k_corr), float(n_corr),
        float(dq_w), bool(cohesion_on),
        float(visc), bool(xsph_on), float(density_floor),
        bool(granular_enabled), float(contact_radius), float(tan_eps),
        float(dt_scale_g), float(normal_proxy_floor_factor),
        bool(thermal_enabled), float(diffusion_rate), float(ambient_rate),
    )

    p.pos = np.frombuffer(pos_buf, dtype=np.float32).reshape(n_p, 2).copy()
    p.prev_pos = np.frombuffer(prev_buf, dtype=np.float32).reshape(n_p, 2).copy()
    p.vel = np.frombuffer(vel_buf, dtype=np.float32).reshape(n_p, 2).copy()
    p.temperature = np.frombuffer(temp_buf, dtype=np.float32).copy()
    p.material_id = np.frombuffer(mat_buf, dtype=np.uint8).copy()


def pbf_step(
    world: FluidWorld,
    dt: float | None = None,
    substeps: int | None = None,
    iters: int | None = None,
) -> None:
    p = world.particles
    if p.count == 0:
        return
    cfg = world.config
    if dt is None:
        dt = float(cfg["default_dt"])
    if substeps is None:
        substeps = int(cfg["substeps"])
    if iters is None:
        iters = int(cfg["iters"])

    sub_dt = float(dt) / max(int(substeps), 1)
    gravity = world.gravity
    eps = float(cfg["velocity_epsilon"])
    max_vel = float(cfg["max_velocity"])
    solver_cfg = cfg["solver"]
    dq_scale = float(solver_cfg["s_corr_dq_scale"])
    xsph_on = bool(solver_cfg["xsph_enabled"])
    density_floor = float(solver_cfg["density_floor_factor"])

    mat = _resolve_material(world)
    h = float(mat.kernel_radius)
    rho0 = float(mat.rest_density)
    relax = float(mat.relaxation_eps)
    visc = float(mat.viscosity)
    k_corr = float(mat.surface_tension)
    n_corr = float(mat.surface_tension_n)
    cohesion_on = k_corr != 0.0
    inv_rho0 = 1.0 / max(rho0, eps)
    delta_q_w = poly6_scalar((dq_scale * h) ** 2, h) if cohesion_on else 0.0

    self_w0 = poly6_coefficient(h) * (h * h) ** 3

    # Tier-10 fast-path: run the entire PBF step (substep + density
    # projection iters + friction + thermal + velocity clamp) in Rust.
    if _HAS_NATIVE_FULL_STEP:
        _run_native_pbf_full_step(
            world, sub_dt, int(substeps), int(iters),
            gravity, eps, max_vel,
            h, rho0, relax, k_corr, n_corr, delta_q_w, cohesion_on,
            visc, xsph_on, density_floor,
        )
        return

    for _ in range(int(substeps)):
        p.prev_pos[:] = p.pos
        p.vel = p.vel + gravity[None, :] * sub_dt
        p.pos = p.pos + p.vel * sub_dt
        _project_boundaries(p.pos, world)

        i_idx, j_idx, _ = _build_neighbour_table(p.pos, h)
        if i_idx.size == 0:
            new_vel = (p.pos - p.prev_pos) / sub_dt
            speed = np.linalg.norm(new_vel, axis=1)
            scale = np.minimum(1.0, max_vel / np.maximum(speed, eps))
            p.vel = (new_vel * scale[:, None]).astype(np.float32, copy=False)
            continue

        # `np.bincount(idx, weights=w, minlength=N)` is the canonical
        # fast replacement for `np.add.at(out, idx, w)` when ``out`` starts
        # at zero (or a known baseline). Each call below runs in optimised
        # C without per-element Python dispatch — typically 5-10x faster.
        n_p = p.count
        if _HAS_NATIVE_PBF:
            # Fast path: one Rust call per iteration. Position buffer is
            # a bytearray shared with a numpy view so that
            # ``_project_boundaries`` can keep mutating it in place
            # without the round-trip cost.
            pos_buf = bytearray(np.ascontiguousarray(p.pos, dtype=np.float32).tobytes())
            pos_view = np.frombuffer(pos_buf, dtype=np.float32).reshape(n_p, 2)
            mass_bytes = np.ascontiguousarray(p.mass, dtype=np.float32).tobytes()
            i_bytes = np.ascontiguousarray(i_idx, dtype=np.int64).tobytes()
            j_bytes = np.ascontiguousarray(j_idx, dtype=np.int64).tobytes()
            for _it in range(int(iters)):
                _native_core.pbf_iter(
                    pos_buf, mass_bytes, i_bytes, j_bytes,
                    float(h), float(rho0), float(relax), float(eps),
                    float(density_floor), bool(cohesion_on),
                    float(k_corr), float(n_corr), float(delta_q_w),
                )
                _project_boundaries(pos_view, world)
            # Copy bytes back into p.pos. Use a fresh ndarray so any
            # downstream code that retained a reference to the previous
            # p.pos sees stable values.
            p.pos = np.array(pos_view, dtype=np.float32, copy=True)
            delta = p.pos[i_idx] - p.pos[j_idx]
            r2 = np.einsum("ij,ij->i", delta, delta)
        else:
            for _it in range(int(iters)):
                delta = p.pos[i_idx] - p.pos[j_idx]
                r2 = np.einsum("ij,ij->i", delta, delta)
                r = np.sqrt(r2)

                w_ij = poly6(r2, h)
                # density[i] = self_w0*mass[i] + sum over neighbours j of mass[j]*w_ij
                density = (np.full(p.count, self_w0, dtype=np.float64) * p.mass
                           + np.bincount(i_idx, weights=p.mass[j_idx] * w_ij,
                                          minlength=n_p)).astype(np.float32, copy=False)
                p.density[:] = density

                c_i = density * inv_rho0 - 1.0
                c_i = np.maximum(c_i, density_floor)

                grad = spiky_grad(delta, r, h, eps) * inv_rho0
                # sum_grad_self[i] = sum over neighbours of grad_ij (vector — do per axis)
                sgs_x = np.bincount(i_idx, weights=grad[:, 0], minlength=n_p)
                sgs_y = np.bincount(i_idx, weights=grad[:, 1], minlength=n_p)
                sum_grad_sq = sgs_x * sgs_x + sgs_y * sgs_y
                neighbour_sq = np.einsum("ij,ij->i", grad, grad)
                sum_grad_neighbour_sq = np.bincount(i_idx, weights=neighbour_sq,
                                                      minlength=n_p)

                denom = sum_grad_sq + sum_grad_neighbour_sq + relax
                lam = -c_i / np.maximum(denom, eps)
                p.lambda_[:] = lam

                if cohesion_on:
                    denom_w = max(delta_q_w, eps)
                    base_ratio = w_ij / denom_w
                    s_corr_ij = (-k_corr * np.power(np.maximum(base_ratio, 0.0), n_corr)).astype(np.float32)
                    lam_sum = lam[i_idx] + lam[j_idx] + s_corr_ij
                else:
                    lam_sum = lam[i_idx] + lam[j_idx]
                delta_p_terms = grad * lam_sum[:, None]
                delta_p_x = np.bincount(i_idx, weights=delta_p_terms[:, 0],
                                         minlength=n_p)
                delta_p_y = np.bincount(i_idx, weights=delta_p_terms[:, 1],
                                         minlength=n_p)
                delta_p = np.stack([delta_p_x.astype(np.float32, copy=False),
                                     delta_p_y.astype(np.float32, copy=False)],
                                    axis=1)

                p.pos = (p.pos + delta_p).astype(np.float32, copy=False)
                _project_boundaries(p.pos, world)

                delta = p.pos[i_idx] - p.pos[j_idx]
                r2 = np.einsum("ij,ij->i", delta, delta)

        friction_pass(world, i_idx, j_idx, p.prev_pos, sub_dt)
        _project_boundaries(p.pos, world)

        # Thermal pass — diffusion + ambient relaxation + phase change.
        # Cheap when no material has thermal_conductivity > 0 (early-outs).
        thermal_cfg = cfg.get("thermal", {})
        if bool(thermal_cfg.get("enabled", True)):
            thermal_step(
                world,
                i_idx,
                j_idx,
                sub_dt,
                diffusion_rate=float(thermal_cfg.get("diffusion_rate", 5.0)),
                ambient_rate=float(thermal_cfg.get("ambient_rate", 0.2)),
            )

        new_vel = (p.pos - p.prev_pos) / sub_dt

        if xsph_on and visc > 0.0:
            w_vis = poly6(r2, h)
            vol_j = p.mass[j_idx] / max(rho0, eps)
            vel_diff = new_vel[j_idx] - new_vel[i_idx]
            terms = vel_diff * (w_vis * vol_j)[:, None]
            # bincount (per-axis) is ~5x faster than np.add.at for fresh-zero
            # accumulators. ``new_vel`` is recomputed every substep so the
            # tiny order-of-summation difference doesn't cascade.
            accum_x = np.bincount(i_idx, weights=terms[:, 0], minlength=p.count)
            accum_y = np.bincount(i_idx, weights=terms[:, 1], minlength=p.count)
            new_vel = new_vel + visc * np.stack(
                [accum_x.astype(np.float32, copy=False),
                 accum_y.astype(np.float32, copy=False)], axis=1)

        speed = np.linalg.norm(new_vel, axis=1)
        scale = np.minimum(1.0, max_vel / np.maximum(speed, eps))
        new_vel = new_vel * scale[:, None]

        p.vel = new_vel.astype(np.float32, copy=False)


__all__ = ["pbf_step", "friction_pass"]
