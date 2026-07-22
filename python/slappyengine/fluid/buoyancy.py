"""Archimedes buoyancy coupling between PBF fluids and XPBD softbodies.

The fluid<->softbody contact projection in :mod:`fluid.contact` resolves
thickness-based penetration but cannot sustain Archimedes upthrust at
scale: fluid particles flow *around* a heavy displacing body faster than
density-coupling pressure can rebuild beneath it, so the buoyant force
the body should feel never integrates.

This module provides :func:`apply_fluid_buoyancy` — a direct per-node
upthrust pass that reads density off softbody metadata and pushes nodes
upward by ``F = rho_water * g * cell_area * frac`` where ``frac`` is the
ramp from "just touching surface" to "fully submerged one cell deep".

Wood (density 600 kg/m^3) floats; steel (7800) sinks; neutral-density
bodies hover. The pass is vectorised numpy and skips fixed nodes.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .world import FluidWorld


def _resolve_cell_area(softbody, body_meta) -> float | None:
    """Look up ``cell_area`` from a body's parameters dict.

    Returns None if the body wasn't built by a lattice builder that
    populated ``parameters['cell_area']``. Callers must then supply
    ``cell_area`` explicitly.
    """
    params: dict[str, Any] | None = getattr(body_meta, "parameters", None)
    if not isinstance(params, dict):
        return None
    val = params.get("cell_area")
    if val is None:
        return None
    return float(val)


def apply_fluid_buoyancy(
    fluid: FluidWorld,
    softbody,
    dt: float,
    *,
    body_meta=None,
    water_density: float | None = None,
    surface_y: float | None = None,
    cell_area: float | None = None,
    gravity: float | None = None,
    drag: float = 2.0,
) -> None:
    """Apply per-node Archimedes upthrust to softbody nodes.

    Parameters
    ----------
    fluid
        Source of ``water_density`` (when not overridden) and of the
        auto-detected water surface y-coordinate.
    softbody
        :class:`SoftBodyWorld`. When ``body_meta`` is None the buoyancy
        force is applied to every node in the world.
    dt
        Time-step (s) for the velocity impulse.
    body_meta
        Optional :class:`BodyMeta` returned by a builder. If provided the
        upthrust is restricted to the nodes in ``body_meta.node_slice``,
        and ``cell_area`` may be auto-detected from
        ``body_meta.parameters['cell_area']``.
    water_density
        Override (kg/m^3). Defaults to ``fluid.config['world']['water_density']``,
        falling back to 1000.0 if missing.
    surface_y
        Override the water surface y-coordinate. Defaults to the minimum
        y across all fluid particles (top surface — recall lower y is
        higher in screen space). Required when the fluid has zero
        particles and no explicit value is supplied.
    cell_area
        Per-node displaced area in m^2. Auto-detected from
        ``body_meta.parameters['cell_area']`` when ``body_meta`` is
        supplied by a lattice builder. Required otherwise.
    gravity
        Override gravity magnitude (m/s^2). Defaults to the y component
        of ``fluid.config['gravity']``.
    drag
        Linear viscous drag coefficient applied to submerged nodes
        (units: 1/s). Multiplies ``frac`` so dry nodes feel nothing.
        Default 2.0 → critical damping for the typical cell-size spring
        formed by partial-submersion buoyancy, so neutral-density bodies
        settle near the surface instead of oscillating.
    """
    if softbody is None:
        return
    if softbody.nodes.count == 0:
        return

    # --- resolve water density ----------------------------------------
    if water_density is None:
        # FluidWorld stores world-section keys at top level of config dict;
        # 'water_density' was added under world: in fluid.yml.
        water_density = float(fluid.config.get("water_density", 1000.0))
    water_density = float(water_density)

    # --- resolve surface y --------------------------------------------
    if surface_y is None:
        if fluid.particles.count == 0:
            raise ValueError(
                "apply_fluid_buoyancy: surface_y is None and the fluid has "
                "no particles to auto-detect from. Pass surface_y explicitly."
            )
        surface_y = float(fluid.particles.pos[:, 1].min())
    surface_y = float(surface_y)

    # --- resolve cell area --------------------------------------------
    if cell_area is None:
        if body_meta is not None:
            cell_area = _resolve_cell_area(softbody, body_meta)
        if cell_area is None:
            raise ValueError(
                "apply_fluid_buoyancy: cell_area is None and could not be "
                "inferred from body_meta.parameters. Either pass cell_area "
                "explicitly, or build the body with make_lattice_body "
                "which stores cell_area in the body's parameters dict."
            )
    cell_area = float(cell_area)
    if cell_area <= 0.0:
        return
    cell_size = float(np.sqrt(cell_area))

    # --- resolve gravity ----------------------------------------------
    if gravity is None:
        g_vec = fluid.config.get("gravity", (0.0, 9.81))
        gravity = float(g_vec[1])
    gravity = float(gravity)
    if gravity == 0.0:
        return

    # --- resolve node slice -------------------------------------------
    if body_meta is not None:
        ns, ne = body_meta.node_slice
    else:
        ns, ne = 0, softbody.nodes.count
    if ne <= ns:
        return

    pos = softbody.nodes.pos[ns:ne]
    mass = softbody.nodes.mass[ns:ne]
    fixed = softbody.nodes.fixed[ns:ne]
    vel = softbody.nodes.vel[ns:ne]

    # In our convention, larger y = lower (deeper). A node is "submerged"
    # when its y exceeds the surface y.
    submerged_depth = np.maximum(pos[:, 1] - surface_y, 0.0)
    frac = np.clip(submerged_depth / cell_size, 0.0, 1.0)
    buoy_force = water_density * cell_area * gravity * frac
    # Upward = negative y in screen-space convention.
    dv = -(buoy_force / np.maximum(mass, 1e-6)) * dt

    # Linear viscous drag — physically motivated (boundary-layer skin
    # friction scales with submerged area). Without it neutral-density
    # bodies oscillate forever around the surface; with it they settle.
    if drag > 0.0:
        # Semi-implicit Euler: v_new = v / (1 + drag * frac * dt)
        # equivalent to exponential decay per submerged fraction.
        damp_factor = 1.0 / (1.0 + float(drag) * frac * float(dt))
        scaled = vel * damp_factor[:, None] - vel
        scaled = np.where(fixed[:, None], 0.0, scaled).astype(np.float32, copy=False)
        softbody.nodes.vel[ns:ne] += scaled

    # Don't push fixed nodes (their inv_mass is 0 anyway, but skipping
    # the velocity write also keeps energy bookkeeping clean).
    dv = np.where(fixed, 0.0, dv).astype(np.float32, copy=False)
    softbody.nodes.vel[ns:ne, 1] += dv


def apply_fluid_buoyancy_iterative(
    fluid: FluidWorld,
    softbody,
    dt: float,
    *,
    body_meta=None,
    water_density: float | None = None,
    cell_area: float | None = None,
    gravity: float | None = None,
    drag: float = 2.0,
    iterations: int = 3,
    splash_threshold: float = 1.5,
    splash_strength: float = 0.5,
    fluid_response: bool = True,
) -> dict:
    """Iterative Archimedes pass with per-region surface sampling +
    optional fluid back-reaction + splash spawning.

    Fixes two visible artefacts in the per-impulse :func:`apply_fluid_buoyancy`:

    1. **Wood floating above the waterline** — the single-pass impulse
       lets a buoyant body overshoot equilibrium between frames. With
       ``iterations=3`` the body re-equilibrates within one step.
    2. **No splash on a sinking body** — when a body enters the fluid
       at relative speed above ``splash_threshold``, this pass marks
       the nearest fluid particles for a vertical kick so the shader's
       splash compositor sees a real event.

    Per-region surface sampling: instead of a single global
    ``surface_y = min(fluid.particles.pos[:, 1])``, this pass samples
    the LOCAL surface under each softbody node via nearest-fluid-y
    binning (16-cell horizontal histogram). A body sinking on the
    right gets the right-side surface depression captured correctly.

    Returns a dict with frame metrics (``splashes_spawned``,
    ``mean_submerged_frac``, ``max_impulse``) for telemetry.
    """
    if softbody is None or softbody.nodes.count == 0:
        return {"splashes_spawned": 0, "mean_submerged_frac": 0.0, "max_impulse": 0.0}
    if fluid.particles.count == 0:
        return {"splashes_spawned": 0, "mean_submerged_frac": 0.0, "max_impulse": 0.0}

    if water_density is None:
        water_density = float(fluid.config.get("water_density", 1000.0))
    water_density = float(water_density)

    if cell_area is None:
        if body_meta is not None:
            cell_area = _resolve_cell_area(softbody, body_meta)
        if cell_area is None:
            raise ValueError(
                "apply_fluid_buoyancy_iterative: cell_area is None and could "
                "not be inferred from body_meta.parameters."
            )
    cell_area = float(cell_area)
    if cell_area <= 0.0:
        return {"splashes_spawned": 0, "mean_submerged_frac": 0.0, "max_impulse": 0.0}
    cell_size = float(np.sqrt(cell_area))

    if gravity is None:
        g_vec = fluid.config.get("gravity", (0.0, 9.81))
        gravity = float(g_vec[1])
    gravity = float(gravity)
    if gravity == 0.0:
        return {"splashes_spawned": 0, "mean_submerged_frac": 0.0, "max_impulse": 0.0}

    if body_meta is not None:
        ns, ne = body_meta.node_slice
    else:
        ns, ne = 0, softbody.nodes.count
    if ne <= ns:
        return {"splashes_spawned": 0, "mean_submerged_frac": 0.0, "max_impulse": 0.0}

    iterations = max(1, int(iterations))
    sub_dt = float(dt) / iterations

    # Pre-bin fluid particle surface heights into 16 horizontal columns
    # so we can sample the LOCAL surface under each node — fixes "wood
    # floats above THE waterline" when the global min is far from a
    # local depression.
    fluid_pos = fluid.particles.pos
    fluid_vel = fluid.particles.vel
    if fluid_pos.shape[0] > 0:
        x_min = float(fluid_pos[:, 0].min())
        x_max = float(fluid_pos[:, 0].max())
        x_range = max(x_max - x_min, 1e-6)
        n_bins = 16
        # surface_per_bin[b] = min y among particles in column b (top surface).
        bin_idx = np.clip(
            ((fluid_pos[:, 0] - x_min) / x_range * n_bins).astype(np.int32),
            0, n_bins - 1,
        )
        surface_per_bin = np.full(n_bins, np.inf, dtype=np.float32)
        for b in range(n_bins):
            mask = bin_idx == b
            if mask.any():
                surface_per_bin[b] = float(fluid_pos[mask, 1].min())
        # Fill any empty bins with the global surface.
        global_surf = float(fluid_pos[:, 1].min())
        surface_per_bin[~np.isfinite(surface_per_bin)] = global_surf
    else:
        surface_per_bin = np.array([0.0], dtype=np.float32)
        x_min = 0.0
        x_range = 1.0
        n_bins = 1

    splashes = 0
    max_impulse = 0.0
    last_frac_mean = 0.0

    for _ in range(iterations):
        pos = softbody.nodes.pos[ns:ne]
        mass = softbody.nodes.mass[ns:ne]
        fixed = softbody.nodes.fixed[ns:ne]
        vel = softbody.nodes.vel[ns:ne]

        # Per-node local surface lookup.
        node_bin = np.clip(
            ((pos[:, 0] - x_min) / x_range * n_bins).astype(np.int32),
            0, n_bins - 1,
        )
        local_surface = surface_per_bin[node_bin]
        submerged_depth = np.maximum(pos[:, 1] - local_surface, 0.0)
        frac = np.clip(submerged_depth / cell_size, 0.0, 1.0)
        last_frac_mean = float(frac.mean())

        buoy_force = water_density * cell_area * gravity * frac
        dv = -(buoy_force / np.maximum(mass, 1e-6)) * sub_dt

        if drag > 0.0:
            damp_factor = 1.0 / (1.0 + float(drag) * frac * sub_dt)
            scaled = vel * damp_factor[:, None] - vel
            scaled = np.where(fixed[:, None], 0.0, scaled).astype(np.float32, copy=False)
            softbody.nodes.vel[ns:ne] += scaled

        dv = np.where(fixed, 0.0, dv).astype(np.float32, copy=False)
        softbody.nodes.vel[ns:ne, 1] += dv
        max_impulse = max(max_impulse, float(np.abs(dv).max()))

        # Splash detection: nodes that JUST entered the fluid (frac transitioned
        # from 0 to > 0 within this sub-step) with downward speed above threshold
        # mark nearby particles for a kick — the renderer composites them as
        # splash droplets.
        if fluid_response and fluid_pos.shape[0] > 0:
            entering = (frac > 0.0) & (vel[:, 1] > splash_threshold)
            if entering.any():
                e_pos = pos[entering]
                for px, py in e_pos[:, :2]:
                    # Find particles within cell_size of the impact point.
                    dx = fluid_pos[:, 0] - float(px)
                    dy = fluid_pos[:, 1] - float(py)
                    near = (dx * dx + dy * dy) < (cell_size * cell_size)
                    if near.any():
                        # Newton 3rd: body pushes fluid down + outward.
                        fluid_vel[near, 1] += splash_strength * 5.0
                        fluid_vel[near, 0] += np.sign(dx[near]) * splash_strength * 2.0
                        splashes += int(near.sum())

    return {
        "splashes_spawned": splashes,
        "mean_submerged_frac": last_frac_mean,
        "max_impulse": max_impulse,
        "iterations": iterations,
    }


__all__ = ["apply_fluid_buoyancy", "apply_fluid_buoyancy_iterative"]
