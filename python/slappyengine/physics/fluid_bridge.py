"""Bridge: route fluid-material particles in ParticleField through the
existing proven PBF solver in slappyengine.fluid.

Existing fluid module is Macklin 2013 PBF with Rust kernels — proper
density-relaxation. ParticleField's _fluid_relax was a naive
substitute. This bridge keeps the unified field architecture while
delegating fluid physics to the canonical solver.

API discovered
==============
``slappyengine.fluid.world.FluidWorld`` is a dataclass holding a
``ParticleSoA`` (positions/velocities/masses/material_id/temperature),
a list of ``FluidMaterial`` entries, and a ``config`` dict.

``pbf_step(world, dt=None, substeps=None, iters=None)`` mutates
``world.particles`` in place. ``substeps`` is the number of
sub-iterations of the prediction step, ``iters`` is the number of
density-projection passes per substep. ``dt`` is the *full* frame dt
— internally divided by ``substeps``.

The solver reads ``kernel_radius`` and ``rest_density`` from the
first / dominant material in ``world.materials``. Per-particle
``mass`` is auto-derived from rest density when using
``add_block_of_particles``; we set it explicitly here from the bridge
config since callers may not want to think in physical units.

Boundary handling
-----------------
``pbf_step`` only knows about the axis-aligned floor / ceiling / walls
in ``world.config``. ParticleField uses an arbitrary
``mask_grid`` (H, W, 4) with alpha as the solid mask. We handle that
*after* ``pbf_step`` by projecting any particle whose pixel sits on
solid out to the nearest empty cell via a short BFS-style ring search.
This is cheap (only fired for the small subset of penetrating
particles) and keeps ``pbf_step`` untouched.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Import the existing fluid solver — these are the canonical entry
# points the rest of the engine already uses.
from slappyengine.fluid.kernels import poly6_coefficient
from slappyengine.fluid.material import FluidMaterial
from slappyengine.fluid.particle import ParticleSoA
from slappyengine.fluid.solver import pbf_step
from slappyengine.fluid.world import FluidWorld


@dataclass(frozen=True)
class FluidBridgeConfig:
    """Per-fluid-material bridge configuration.

    ``rest_distance`` is the desired inter-particle spacing in pixel
    units. The PBF solver works in whatever unit you feed it — we
    derive ``kernel_radius`` and ``rest_density`` from this so the
    canonical solver behaves consistently when driven from
    ParticleField's pixel-space inputs.
    """

    rest_distance: float = 3.0
    iterations: int = 3
    gravity: tuple[float, float] = (0.0, 720.0)
    substeps: int = 1
    # Rest density in particles-per-unit² space. The solver expects a
    # mass-density value; we treat each particle as mass=1.0 and pick
    # a density target that matches ``rest_distance`` (one particle per
    # rest_distance × rest_distance cell).
    viscosity: float = 0.0
    relaxation_eps: float = 600.0
    # Margin inside the mask projection — push particles this many
    # pixels past the solid boundary so they don't immediately reenter
    # next step.
    mask_eject_margin: float = 0.5
    # Velocity clamp in pixel/sec. The canonical fluid YAML defaults
    # this to 20 m/s (a real-world scale). ParticleField uses pixel
    # space where gravity is ~720 px/s² and impact velocities run
    # hundreds of px/s — set the clamp high enough not to interfere.
    max_velocity: float = 4000.0


def _make_bridge_material(cfg: FluidBridgeConfig) -> FluidMaterial:
    """Synthesise a FluidMaterial from the bridge config.

    Kernel radius is ``2 × rest_distance`` (so each particle has
    ~12-16 neighbours in 2D, which is what Macklin's PBF assumes).

    Rest density must be the *SPH-summed* density a fluid achieves at
    its target packing — not the geometric ``1/area`` value. We
    compute it by summing the poly6 kernel over a regular grid of
    neighbours at spacing ``rest_distance`` (plus the self
    contribution). This mirrors what
    ``FluidWorld._mass_for_rest_density`` does in reverse: that method
    picks a mass to hit a target rho0; here we pick rho0 to match
    mass=1 at the desired spacing.
    """
    rest = float(cfg.rest_distance)
    h = 2.0 * rest
    rho0 = _sph_rest_density(h, rest, particle_mass=1.0)
    return FluidMaterial(
        name="_bridge_fluid",
        rest_density=float(rho0),
        kernel_radius=float(h),
        relaxation_eps=float(cfg.relaxation_eps),
        viscosity=float(cfg.viscosity),
        surface_tension=0.0,
        surface_tension_n=4.0,
        particle_mass=1.0,
    )


def _sph_rest_density(h: float, spacing: float, particle_mass: float) -> float:
    """Return the SPH-summed density of a particle in a regular grid
    of neighbours at the given spacing, kernel radius ``h``."""
    sp = float(spacing)
    R = int(np.ceil(h / max(sp, 1e-6))) + 1
    offsets = np.arange(-R, R + 1, dtype=np.float64) * sp
    gx, gy = np.meshgrid(offsets, offsets, indexing="xy")
    r2 = (gx * gx + gy * gy).ravel()
    valid = r2 < h * h
    diff = np.maximum(h * h - r2[valid], 0.0)
    w_sum = float(poly6_coefficient(h) * np.power(diff, 3).sum())
    return float(particle_mass * w_sum)


def _build_world(
    fluid_pos: np.ndarray,
    fluid_vel: np.ndarray,
    cfg: FluidBridgeConfig,
) -> FluidWorld:
    """Construct a fresh FluidWorld populated with the bridge particles.

    The world's boundaries are pushed out to infinity (effectively
    disabled) because ParticleField provides its own ``mask_grid``
    collision — we don't want the canonical axis-aligned floor/ceiling
    fighting that.
    """
    material = _make_bridge_material(cfg)
    soa = ParticleSoA()
    n = int(fluid_pos.shape[0])
    if n > 0:
        soa.append(
            np.ascontiguousarray(fluid_pos, dtype=np.float32),
            mass=float(material.particle_mass),
            material_id=0,
            vel=np.ascontiguousarray(fluid_vel, dtype=np.float32),
            temperature=float(material.ambient_temperature),
        )
    world = FluidWorld(particles=soa, materials=[material])
    # Override config: gravity (pixel-space), substeps, iters, disable
    # the axis-aligned boundaries (we handle collision via mask_grid),
    # disable thermal coupling (no temperature gradient here).
    world.config["gravity"] = (float(cfg.gravity[0]), float(cfg.gravity[1]))
    world.config["substeps"] = int(cfg.substeps)
    world.config["iters"] = int(cfg.iterations)
    # ParticleField operates in pixel-space with much higher absolute
    # velocities than the default m/s clamp (20.0). Bump the clamp so
    # gravity-driven fall and impact velocities aren't artificially
    # capped at low values.
    world.config["max_velocity"] = float(cfg.max_velocity)
    big = 1.0e9
    world.config["floor_y"] = big
    world.config["ceiling_y"] = -big
    world.config["wall_x_min"] = -big
    world.config["wall_x_max"] = big
    # Disable granular + thermal subsystems for the pure-fluid bridge.
    world.config["granular"]["enabled"] = False
    world.config["thermal"]["enabled"] = False
    return world


def _project_out_of_mask(
    pos: np.ndarray,
    vel: np.ndarray,
    mask_grid: np.ndarray,
    margin: float,
) -> None:
    """In-place: push any particle whose pixel is solid (alpha > 0)
    to the nearest non-solid pixel via a small ring search.

    Velocity normal component is zeroed on contact so particles don't
    re-tunnel next step.
    """
    if pos.shape[0] == 0:
        return
    h, w = mask_grid.shape[:2]
    if h == 0 or w == 0:
        return
    solid = mask_grid[..., 3] > 0

    # Index particles whose current pixel is solid.
    ix = np.clip(np.floor(pos[:, 0]).astype(np.int64), 0, w - 1)
    iy = np.clip(np.floor(pos[:, 1]).astype(np.int64), 0, h - 1)
    inside = solid[iy, ix]
    if not np.any(inside):
        return
    bad_idx = np.flatnonzero(inside)

    # For each penetrating particle, walk outward in concentric rings
    # until we find an empty pixel. Cap the radius so a fully solid
    # field doesn't loop forever.
    max_ring = max(4, int(margin * 4) + 4)
    for k in bad_idx:
        px = float(pos[k, 0])
        py = float(pos[k, 1])
        cx = int(np.clip(np.floor(px), 0, w - 1))
        cy = int(np.clip(np.floor(py), 0, h - 1))
        found = False
        for r in range(1, max_ring + 1):
            # Sample 8 cardinal/diagonal directions at radius r.
            for dx, dy in (
                (r, 0), (-r, 0), (0, r), (0, -r),
                (r, r), (-r, -r), (r, -r), (-r, r),
            ):
                nx = cx + dx
                ny = cy + dy
                if 0 <= nx < w and 0 <= ny < h and not solid[ny, nx]:
                    # Move to the centre of the empty cell, offset by
                    # the margin away from the original solid pixel.
                    norm = float(np.hypot(dx, dy)) or 1.0
                    ux = dx / norm
                    uy = dy / norm
                    pos[k, 0] = np.float32(nx + 0.5 + ux * margin)
                    pos[k, 1] = np.float32(ny + 0.5 + uy * margin)
                    # Zero the velocity component pointing into the
                    # solid (i.e. opposite to the eject direction).
                    vn = vel[k, 0] * (-ux) + vel[k, 1] * (-uy)
                    if vn > 0.0:
                        vel[k, 0] -= np.float32(vn * (-ux))
                        vel[k, 1] -= np.float32(vn * (-uy))
                    found = True
                    break
            if found:
                break


def bridge_step(
    fluid_pos: np.ndarray,
    fluid_vel: np.ndarray,
    mask_grid: np.ndarray | None,
    cfg: FluidBridgeConfig,
    dt: float,
) -> tuple[np.ndarray, np.ndarray]:
    """One PBF step on the subset of particles flagged as fluid.

    Builds a temporary :class:`FluidWorld` from the inputs, calls
    :func:`slappyengine.fluid.solver.pbf_step`, extracts the updated
    positions and velocities, and (if a mask is supplied) projects any
    particle that ended up inside a solid pixel out of it.

    Parameters
    ----------
    fluid_pos : (N, 2) float32
        Fluid particle positions in pixel coordinates.
    fluid_vel : (N, 2) float32
        Fluid particle velocities (pixels / sec).
    mask_grid : (H, W, 4) uint8 or None
        Collision mask. Alpha > 0 marks solid pixels. ``None`` skips
        the projection step (open-world fluid).
    cfg : FluidBridgeConfig
        Bridge tuning — controls particle spacing, solver iterations,
        gravity.
    dt : float
        Frame timestep (seconds).

    Returns
    -------
    (new_pos, new_vel) : tuple of (N, 2) float32 arrays
        Updated positions and velocities. Shapes match the inputs.
    """
    pos_in = np.asarray(fluid_pos, dtype=np.float32).reshape(-1, 2)
    vel_in = np.asarray(fluid_vel, dtype=np.float32).reshape(-1, 2)
    if pos_in.shape[0] != vel_in.shape[0]:
        raise ValueError(
            f"fluid_pos and fluid_vel length mismatch: "
            f"{pos_in.shape[0]} vs {vel_in.shape[0]}"
        )
    if pos_in.shape[0] == 0:
        return (
            np.empty((0, 2), dtype=np.float32),
            np.empty((0, 2), dtype=np.float32),
        )

    world = _build_world(pos_in, vel_in, cfg)
    pbf_step(world, dt=float(dt))

    new_pos = np.ascontiguousarray(world.particles.pos, dtype=np.float32)
    new_vel = np.ascontiguousarray(world.particles.vel, dtype=np.float32)

    if mask_grid is not None:
        mask = np.asarray(mask_grid)
        if mask.ndim == 3 and mask.shape[2] >= 4:
            _project_out_of_mask(new_pos, new_vel, mask, float(cfg.mask_eject_margin))

    return new_pos, new_vel


__all__ = ["FluidBridgeConfig", "bridge_step"]
