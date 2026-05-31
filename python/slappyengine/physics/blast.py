"""Explosion / blast helper — carve a crater and eject particles onto a field.

One entry point, :func:`detonate`, ties :mod:`splatter_presets` to
:class:`~slappyengine.physics.particle_field.ParticleField`. It:

1. Carves a parabolic bowl out of the field's per-pixel mask.
2. Samples the **original pixel colours** from the carved region BEFORE
   clearing them — those colours become the per-particle colour of the
   ejecta, so chunks fly out inheriting the ground's hue instead of a
   detached palette. (User-driven behaviour: "use the original pixels".)
3. Builds a particle batch with up + out trajectories from the cone /
   blend / boost knobs on the preset (``blast_up_boost``,
   ``blast_radial_boost``, ``edge_outward_boost``, ``direction_blend``,
   ``max_blast_angle_deg``).
4. Calls :meth:`ParticleField.spawn_batch` once. From there, the field's
   own ``step()`` handles airborne, landing, sliding, settle-bake, and
   slump — everything is governed by the preset's per-material knobs.

The function also takes care of registering a :class:`Material` derived
from the preset if one with that name isn't already on the field.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from slappyengine.physics.particle_field import Material, ParticleField
from slappyengine.physics.splatter_presets import SplatterPreset


@dataclass(frozen=True)
class DetonateCurves:
    """Tunable shaping curves for :func:`detonate`. Defaults give a
    Worms-style "up and out" feel; pass a custom instance per blast for
    different flavours (nuke, mortar, etc.).

    Each field is a *curve power*: 1.0 is linear; > 1.0 weights the
    distribution toward the low end; < 1.0 weights toward the high end.
    Compose multiple curves for richer shaping without re-specifying
    every per-particle parameter individually.
    """

    # Spawn-depth curve: at offset=R, sample y uniformly from
    # [0, depth_at_offs * (1 - bias**curve_pow)]. Lower curve_pow =
    # particles cluster toward the bowl floor; higher = toward the rim.
    chunk_depth_curve_pow: float = 1.0
    grain_depth_curve_pow: float = 1.0

    # Speed weighting: random in [min, max] raised to this power.
    # > 1.0 = more slow particles (most stay near the blast); < 1.0 =
    # more fast particles (most fly far).
    speed_curve_pow: float = 1.0

    # Rigidify spread: scales the random rigidify_at picker. > 1.0 =
    # more particles rigidify early (rigid look fast); < 1.0 = stay
    # kinetic longer (fluid-flowing look).
    rigidify_curve_pow: float = 1.0

    # Direction-blend curve: scales how strongly rim particles bias
    # toward the radial-outward direction. > 1.0 = stronger edge
    # outward bias; < 1.0 = edge particles look more like centre ones.
    direction_blend_curve_pow: float = 1.0

    # Mass conservation multiplier applied to all ejecta from this
    # blast (overrides Material.mass_conservation for the blast path).
    # 1.0 = exact; > 1.0 = exaggerated debris; < 1.0 = compaction.
    mass_conservation: float = 1.0


def material_from_preset(preset: SplatterPreset) -> Material:
    """Translate a :class:`SplatterPreset` into a :class:`Material`
    suitable for registering with a :class:`ParticleField`. The
    binding force is set from ``impact_binding_ke`` (scaled to the
    field's KE units) and the rest comes straight off the preset.
    """
    return Material(
        name=preset.name,
        binding_force=preset.impact_binding_ke,
        cohesion=preset.cohesion,
        slump_angle_deg=preset.slump_angle_deg,
        density=1.0,
        air_drag_per_sec=preset.air_drag_per_sec,
        gravity_scale=1.0,
        friction_per_sec=preset.friction_per_sec,
        settle_speed_threshold=preset.settle_speed_threshold,
        settle_jitter=preset.settle_jitter,
        color=preset.chunk_palette[0] if preset.chunk_palette else (200, 200, 200),
        radius_min=max(0, preset.grain_radius_min),
        radius_max=max(1, preset.chunk_radius_max),
    )


def ensure_preset_material(field: ParticleField, preset: SplatterPreset) -> int:
    """Return the material id for ``preset`` on ``field``, registering
    a new :class:`Material` derived from the preset if necessary."""
    if preset.name in field._name_to_id:
        return field._name_to_id[preset.name]
    new_mat = material_from_preset(preset)
    field.materials.append(new_mat)
    field._name_to_id[preset.name] = len(field.materials) - 1
    return field._name_to_id[preset.name]


def detonate(
    field: ParticleField,
    preset: SplatterPreset,
    *,
    x: float,
    y: float,
    crater_radius: float,
    crater_depth: float,
    rng: np.random.Generator | None = None,
) -> int:
    """Carve a crater and inject the preset's ejecta onto ``field``.

    Returns the number of particles spawned. The bowl is parabolic
    (cosine-of-x²); particles spawn AT the original surface band
    (avoids the "fall from the top of the screen" bug) with velocities
    governed by the preset's cone / blend / boosts.

    Per-particle colours are sampled from the **original mask pixels**
    in the carved region. If the bowl has no solid pixels (e.g. the
    blast is in mid-air), we fall back to the preset's palettes.
    """
    if rng is None:
        rng = np.random.default_rng()

    H, W = field.height, field.width
    mid = ensure_preset_material(field, preset)

    # ── 1. Carve bowl + capture source colours ──────────────────────────
    bowl = np.zeros((H, W), dtype=bool)
    xi = int(x)
    yi = int(y)
    r = int(crater_radius)
    d = int(crater_depth)
    for col_off in range(-r, r + 1):
        col = xi + col_off
        if not (0 <= col < W):
            continue
        depth = int(d * (1.0 - (col_off / float(r)) ** 2))
        y0 = max(0, yi)
        y1 = min(H, yi + depth + 1)
        bowl[y0:y1, col] = True

    solid_in_bowl = bowl & (field.mask[..., 3] > 0)
    sampled_rgb: np.ndarray = field.mask[solid_in_bowl, :3].copy()
    field.carve(bowl)

    # ── 2. Build particle batch ────────────────────────────────────────
    n_chunks = preset.n_chunks
    n_grains = preset.n_grains
    n = n_chunks + n_grains
    if n == 0:
        return 0
    is_chunk = np.zeros(n, dtype=bool)
    is_chunk[:n_chunks] = True

    cone_rad = preset.max_blast_angle_rad

    # Spawn positions: each particle comes from its ORIGINAL pixel
    # inside the carved bowl. For a particle at offset ``offs``, the
    # bowl extends from y=yi to y=yi+depth(offs); we sample a y
    # uniformly across that depth so the ejecta visibly comes from
    # varied depths (not a single horizontal line at the surface).
    # Chunks favour deeper positions, grains shallower.
    offs = rng.uniform(-crater_radius, crater_radius, n).astype(np.float32)
    depth_at_offs = (crater_depth
                      * (1.0 - (offs / max(1.0, crater_radius)) ** 2))
    # Sample a depth bias per kind: grains in top 60%, chunks anywhere.
    bias = np.where(
        is_chunk,
        rng.uniform(0.0, 1.0, n),
        rng.uniform(0.0, 0.6, n),
    ).astype(np.float32)
    sample_depth = bias * depth_at_offs
    pos = np.column_stack([
        x + offs,
        float(yi) + sample_depth,
    ]).astype(np.float32)

    # Direction: uniform within cone, blended with radial-outward.
    base_ang = rng.uniform(-cone_rad, cone_rad, n).astype(np.float32)
    radial_ang = (offs / max(1.0, crater_radius)) * cone_rad
    blend = preset.direction_blend
    final_ang = base_ang * (1.0 - blend) + radial_ang * blend
    final_ang = np.clip(final_ang, -cone_rad, cone_rad)

    # Speed sampling per kind.
    chunk_speeds = rng.uniform(
        preset.chunk_speed_min, preset.chunk_speed_max, n
    ).astype(np.float32)
    grain_speeds = rng.uniform(
        preset.grain_speed_min, preset.grain_speed_max, n
    ).astype(np.float32)
    speeds = np.where(is_chunk, chunk_speeds, grain_speeds)

    # Velocity: direction * speed + edge boost + flat up/radial bias.
    dir_x = np.sin(final_ang)
    dir_y = -np.cos(final_ang)
    edge_kick = (offs / max(1.0, crater_radius)) * preset.edge_outward_boost
    radial_kick = np.sign(offs) * preset.blast_radial_boost
    vel = np.column_stack([
        dir_x * speeds + edge_kick + radial_kick,
        dir_y * speeds - preset.blast_up_boost,  # negative vy = upward
    ]).astype(np.float32)

    # Airborne disc radii (what the user sees in flight).
    chunk_radii = rng.integers(
        preset.chunk_radius_min, preset.chunk_radius_max + 1, n
    )
    grain_radii = rng.integers(
        preset.grain_radius_min, preset.grain_radius_max + 1, n
    )
    radii = np.where(is_chunk, chunk_radii, grain_radii).astype(np.float32)

    # Bake stamp size derives directly from the particle's own
    # airborne radius — fragment size determines bake amount, as the
    # user asked. Big chunks bake big, small grains bake tiny. No flat
    # "1 particle = X pixels" mapping. Clamp to >= 0 (1-pixel floor).
    bake_radii = np.maximum(0, radii.astype(np.int32) - 1).astype(np.int32)

    # ── 3. Colour sourcing: original pixels first, palette as fallback.
    colours = np.zeros((n, 3), dtype=np.uint8)
    if sampled_rgb.shape[0] > 0:
        # Sample with replacement; randomised so chunks/grains get
        # varied hues from the original bowl.
        pick = rng.integers(0, sampled_rgb.shape[0], n)
        colours = sampled_rgb[pick].astype(np.uint8)
    # For any particle without a sampled colour, fall back to the
    # palette (when bowl was empty, e.g. mid-air blast).
    if sampled_rgb.shape[0] == 0:
        grain_pal = np.asarray(preset.grain_palette, dtype=np.uint8)
        chunk_pal = np.asarray(preset.chunk_palette, dtype=np.uint8)
        gi = rng.integers(0, len(grain_pal), n)
        ci = rng.integers(0, len(chunk_pal), n)
        for k in range(n):
            colours[k] = chunk_pal[ci[k]] if is_chunk[k] else grain_pal[gi[k]]

    # Post-blast darkening (variegated scorched look).
    if preset.post_blast_darken_max > 0.0:
        darken = rng.uniform(
            preset.post_blast_darken_min,
            preset.post_blast_darken_max,
            n,
        ).astype(np.float32)
        scale = np.clip(1.0 - darken, 0.0, 1.0)
        colours = (colours.astype(np.float32) * scale[:, None]).astype(np.uint8)

    field.spawn_batch(
        pos=pos,
        vel=vel,
        material_ids=np.full(n, mid, dtype=np.int32),
        radii=radii,
        colors=colours,
        bake_radii=bake_radii,
    )
    return n


__all__ = ["detonate", "material_from_preset", "ensure_preset_material"]
