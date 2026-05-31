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

    # ── Crater shape ─────────────────────────────────────────────────
    # Bowl profile: depth(offs) = crater_depth * (1 - (offs/R)^pow).
    # 2.0 = parabolic (default, broad bowl). 1.0 = cone (V-shape).
    # 3.0+ = wide flat floor + steep walls (impact crater).
    crater_curve_pow: float = 2.0
    # Bowl noise — fraction of crater_depth used as random perturbation
    # per column. 0.0 = perfect smooth bowl; 0.25 = naturally rough.
    crater_noise: float = 0.15

    # ── Blast direction ──────────────────────────────────────────────
    # Master vector direction the blast pushes particles in.
    # 0° = straight up (default explosion); 90° = right; -90° = left;
    # 180° = downward (directed bomb hitting floor). The cone spread
    # is taken around this axis, not always vertical.
    blast_direction_deg: float = 0.0
    # Per-axis multiplier — useful for "tall thin column" (>1 up_scale)
    # vs "wide flat splash" (>1 lateral_scale).
    up_velocity_scale: float = 1.0
    lateral_velocity_scale: float = 1.0

    # ── Thermal bump on detonation ───────────────────────────────────
    # Added to every spawned particle's initial temperature. Use
    # this to model the explosion's heat: snow ejecta starts hot →
    # melts to water on the first thermal step → cools in flight →
    # may re-freeze to ice (or back to snow) when temperature drops.
    # 0 = no bump (particles get their material's normal initial T).
    temperature_bump: float = 0.0


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
    curves: DetonateCurves | None = None,
) -> int:
    """Carve a crater and inject the preset's ejecta onto ``field``.

    Returns the number of particles spawned. The bowl is parabolic
    (cosine-of-x²); particles spawn AT the original surface band
    (avoids the "fall from the top of the screen" bug) with velocities
    governed by the preset's cone / blend / boosts.

    Per-particle colours are sampled from the **original mask pixels**
    in the carved region. Per-particle materials are likewise sampled
    from the field's ``material_grid`` at those same pixels, so a blast
    through layered terrain (mud over rock) yields ejecta whose material
    matches each chunk's origin layer. The preset's ``Material`` is
    still registered (and used as a fallback when a sampled pixel has
    no ``material_grid`` value, or the bowl is empty / mid-air) — its
    KE / cohesion / drag knobs drive airborne physics for the mixed
    ejecta independent of the per-particle material.
    """
    if rng is None:
        rng = np.random.default_rng()
    if curves is None:
        curves = DetonateCurves()

    H, W = field.height, field.width
    mid = ensure_preset_material(field, preset)

    # ── 1. Carve bowl + capture source colours ──────────────────────────
    bowl = np.zeros((H, W), dtype=bool)
    xi = int(x)
    yi = int(y)
    r = int(crater_radius)
    d = int(crater_depth)
    noise_amp = max(0.0, curves.crater_noise) * d
    pow_curve = max(0.5, curves.crater_curve_pow)
    for col_off in range(-r, r + 1):
        col = xi + col_off
        if not (0 <= col < W):
            continue
        # Bowl shape governed by curves.crater_curve_pow:
        #   2.0 = parabolic (smooth saucer)
        #   1.0 = cone
        #   3.0+ = wide flat floor + steep walls (impact crater).
        base_depth = d * (1.0 - (abs(col_off) / float(r)) ** pow_curve)
        # Per-column noise breaks the rim from a perfect curve.
        if noise_amp > 0.0:
            base_depth += float(rng.uniform(-noise_amp, noise_amp))
        depth = max(0, int(round(base_depth)))
        y0 = max(0, yi)
        y1 = min(H, yi + depth + 1)
        bowl[y0:y1, col] = True

    solid_in_bowl = bowl & (field.mask[..., 3] > 0)
    sampled_rgb: np.ndarray = field.mask[solid_in_bowl, :3].copy()
    # Sample the per-pixel material id of each solid bowl pixel BEFORE
    # carving — so ejecta inherit the actual material under the impact
    # (mud-over-rock layered terrain yields mud chunks on top, rock
    # chunks below). -1 entries fall back to the preset material id
    # later when assigning per-particle materials.
    sampled_mids: np.ndarray = field.material_grid[solid_in_bowl].copy()
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
    # Then optionally rotate the whole vector field by the blast
    # direction (0° = straight up; 90° = right; 180° = into the floor).
    dir_x = np.sin(final_ang)
    dir_y = -np.cos(final_ang)
    edge_kick = (offs / max(1.0, crater_radius)) * preset.edge_outward_boost
    radial_kick = np.sign(offs) * preset.blast_radial_boost
    vx_raw = dir_x * speeds + edge_kick + radial_kick
    vy_raw = dir_y * speeds - preset.blast_up_boost  # negative = up
    # Per-axis scales — useful for "tall column" (up_scale > 1) vs
    # "wide splash" (lateral_scale > 1).
    vx_raw = vx_raw * curves.lateral_velocity_scale
    vy_raw = vy_raw * curves.up_velocity_scale
    # Rotate the velocity field by blast_direction_deg around the
    # standard "up = +0°" axis (positive = tilt to the right; 180°
    # = blast pushes down).
    if abs(curves.blast_direction_deg) > 1e-3:
        theta = math.radians(curves.blast_direction_deg)
        c, s = math.cos(theta), math.sin(theta)
        vx_rot = vx_raw * c - vy_raw * s
        vy_rot = vx_raw * s + vy_raw * c
        vx_raw, vy_raw = vx_rot, vy_rot
    vel = np.column_stack([vx_raw, vy_raw]).astype(np.float32)

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

    # ── 3. Colour + material sourcing: original pixels first, palette
    #       / preset material as fallback. Colour and material come from
    #       the SAME pick(idx) so a chunk taken from a mud pixel gets
    #       both the mud colour AND the mud material id — that's what
    #       lets layered terrain produce ejecta of the correct kind.
    colours = np.zeros((n, 3), dtype=np.uint8)
    particle_mids = np.full(n, mid, dtype=np.int32)
    if sampled_rgb.shape[0] > 0:
        # Sample with replacement; randomised so chunks/grains get
        # varied hues from the original bowl.
        pick = rng.integers(0, sampled_rgb.shape[0], n)
        colours = sampled_rgb[pick].astype(np.uint8)
        # Per-particle material id from the SAME pick. -1 entries
        # (pixel had no material_grid value set) fall back to the
        # preset's material id — `mid` is already pre-filled.
        picked_mids = sampled_mids[pick].astype(np.int32)
        valid = picked_mids >= 0
        particle_mids[valid] = picked_mids[valid]
    # For any particle without a sampled colour, fall back to the
    # palette (when bowl was empty, e.g. mid-air blast). The preset
    # material id (already in particle_mids) is kept as-is.
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
        material_ids=particle_mids,
        radii=radii,
        colors=colours,
        bake_radii=bake_radii,
    )
    # Apply the explosion's temperature bump to the freshly-spawned
    # particles. The bump models the heat the blast deposits into
    # the ejecta — particles cool toward ambient over subsequent
    # frames via the thermal step.
    if curves.temperature_bump != 0.0:
        n_total = field.pos.shape[0]
        field.temperature[n_total - n:] += np.float32(curves.temperature_bump)
    return n


__all__ = ["detonate", "material_from_preset", "ensure_preset_material"]
