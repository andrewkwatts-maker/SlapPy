"""Bridge: route fluid-material particles in ParticleField through the
existing proven PBF solver in pharos_engine.fluid.

Existing fluid module is Macklin 2013 PBF with Rust kernels — proper
density-relaxation. ParticleField's _fluid_relax was a naive
substitute. This bridge keeps the unified field architecture while
delegating fluid physics to the canonical solver.

API discovered
==============
``pharos_engine.fluid.world.FluidWorld`` is a dataclass holding a
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
from functools import lru_cache

import numpy as np

# Import the existing fluid solver — these are the canonical entry
# points the rest of the engine already uses.
from pharos_engine.fluid.kernels import poly6_coefficient
from pharos_engine.fluid.material import FluidMaterial
from pharos_engine.fluid.particle import ParticleSoA
from pharos_engine.fluid.solver import pbf_step
from pharos_engine.fluid.world import FluidWorld, _load_world_config


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


@lru_cache(maxsize=1)
def _cached_world_config_template() -> dict:
    """Snapshot of :func:`pharos_engine.fluid.world._load_world_config` with
    the bridge-specific overrides baked in.

    The vanilla ``FluidWorld()`` constructor calls ``_load_world_config``
    in its default factory, which re-parses ``config/fluid.yml`` from
    disk on every invocation. With one bridge step per snow+mud field
    per frame that was costing ~18 ms / call on scenario B (~45% of the
    measured ``_pbf_bridge_step`` time on the 2026-06-01 refresh).
    Caching the parsed config + the bridge overrides lets ``_build_world``
    short-circuit the disk I/O entirely.

    The cached template is the *immutable* baseline; ``_build_world``
    shallow-copies it and patches in the per-call gravity / iters /
    velocity-clamp from ``FluidBridgeConfig``. The nested ``granular`` /
    ``thermal`` dicts are pre-set to ``enabled=False`` here so the
    per-call code path doesn't need to touch them.
    """
    cfg = _load_world_config()
    big = 1.0e9
    cfg["floor_y"] = big
    cfg["ceiling_y"] = -big
    cfg["wall_x_min"] = -big
    cfg["wall_x_max"] = big
    # Granular + thermal are nested dicts; deep-copy them so we don't
    # alias the originals when callers mutate.
    cfg["granular"] = dict(cfg.get("granular", {}))
    cfg["granular"]["enabled"] = False
    cfg["thermal"] = dict(cfg.get("thermal", {}))
    cfg["thermal"]["enabled"] = False
    return cfg


def _fresh_world_config(cfg: "FluidBridgeConfig") -> dict:
    """Return a per-call config dict patched with the bridge overrides.

    Shallow-copies the cached template (cheap), then patches the keys
    that vary per :class:`FluidBridgeConfig` instance. Mirrors the
    overrides previously applied in :func:`_build_world` but skips the
    YAML re-parse entirely.
    """
    base = _cached_world_config_template()
    out = dict(base)
    # The nested sub-dicts in the template are already configured for
    # the bridge use case; shallow-copy them so per-call mutation
    # doesn't leak back into the cache.
    out["solver"] = dict(base["solver"])
    out["contact"] = dict(base["contact"])
    out["granular"] = dict(base["granular"])
    out["thermal"] = dict(base["thermal"])
    out["gravity"] = (float(cfg.gravity[0]), float(cfg.gravity[1]))
    out["substeps"] = int(cfg.substeps)
    out["iters"] = int(cfg.iterations)
    out["max_velocity"] = float(cfg.max_velocity)
    return out


@lru_cache(maxsize=8)
def _cached_bridge_material(
    rest_distance: float,
    relaxation_eps: float,
    viscosity: float,
) -> FluidMaterial:
    """LRU-cached :func:`_make_bridge_material`.

    ``_sph_rest_density`` does a meshgrid + poly6 evaluation over the
    (2 × rest_distance) neighbourhood; tiny but called for every bridge
    step. Caching by the three :class:`FluidBridgeConfig` fields that
    affect the material parameters (rest_distance / relaxation_eps /
    viscosity) shaves another sub-millisecond off the bridge call.
    """
    rest = float(rest_distance)
    h = 2.0 * rest
    rho0 = _sph_rest_density(h, rest, particle_mass=1.0)
    return FluidMaterial(
        name="_bridge_fluid",
        rest_density=float(rho0),
        kernel_radius=float(h),
        relaxation_eps=float(relaxation_eps),
        viscosity=float(viscosity),
        surface_tension=0.0,
        surface_tension_n=4.0,
        particle_mass=1.0,
    )


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

    Delegates to :func:`_cached_bridge_material` so the SPH-density
    meshgrid only runs the first time a given ``(rest_distance,
    relaxation_eps, viscosity)`` triple is seen.
    """
    return _cached_bridge_material(
        rest_distance=float(cfg.rest_distance),
        relaxation_eps=float(cfg.relaxation_eps),
        viscosity=float(cfg.viscosity),
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
    # Build the world with the cached + patched config so the default
    # factory's YAML re-parse never runs. Functionally equivalent to the
    # previous "construct then mutate world.config" sequence below — see
    # ``_fresh_world_config`` for the override list.
    world = FluidWorld(
        particles=soa,
        materials=[material],
        config=_fresh_world_config(cfg),
    )
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
    :func:`pharos_engine.fluid.solver.pbf_step`, extracts the updated
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
