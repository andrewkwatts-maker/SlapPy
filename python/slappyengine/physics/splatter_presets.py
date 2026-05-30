"""Crater / explosion presets — splattable particle profiles.

Each :class:`SplatterPreset` packs the per-material knobs a Worms-style
particle explosion needs: spread cone, grain/chunk mix, gravity,
friction, splat width, and palette. Game code (Ochema, Bullet Strata)
loads a preset by name and pipes it into the same simulator core.

The same preset object is consumed by:

* ``examples/sand_crater_demo.py`` — standalone PIL renderer
* The pixel/texture asset pipeline — :func:`materialise_texture`
  bakes a preset into a stamp that the per-pixel sim and the
  paint-on-collision deformer can sample from

Builtins:

* ``sand`` — Worms-classic, tan/brown, mid-cone 45°, light friction
* ``mud``  — heavier, brown, narrower cone, sticky landings, big splats
* ``sloppy`` — wet mud, very narrow cone, almost zero air time, huge
              splat radius, fast settle
* ``rock`` — chunky-heavy, mid cone, low friction, sharp splat
* ``snow`` — pale, wide cone, very slow gravity, drift-y settling

Custom presets via :func:`make_preset`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np


_RGB = tuple[int, int, int]


@dataclass(frozen=True)
class SplatterPreset:
    """Knobs for one explosion / splatter material profile."""

    name: str

    # Spread cone (degrees from vertical). 0 = pure-vertical jet,
    # 90 = full hemisphere.
    max_blast_angle_deg: float = 45.0

    # Particle count + mix.
    n_grains: int = 900
    n_chunks: int = 120

    # Speed range (px/sec). Higher = particles fly further before falling.
    grain_speed_min: float = 80.0
    grain_speed_max: float = 480.0
    chunk_speed_min: float = 140.0
    chunk_speed_max: float = 320.0

    # Size in pixels.
    grain_radius_min: int = 1
    grain_radius_max: int = 2
    chunk_radius_min: int = 2
    chunk_radius_max: int = 3

    # Physics knobs.
    gravity: float = 720.0
    air_drag_per_sec: float = 0.55  # per-second retention (1.0 = no drag)
    friction_per_sec: float = 0.05  # horizontal slide friction after landing
    splat_radius_px: int = 5        # column-spread for chunks
    splat_lift_max: int = 3         # peak heightmap lift per chunk landing
    splat_pile_cap_px: int = 30     # pile-slump cap: per-chunk lift
                                    # falls to zero as the column rises
                                    # this many px above the original
                                    # ground. Stops chunk-on-chunk landing
                                    # from growing unbounded towers.
    settle_speed_threshold: float = 10.0  # px/s — settled below this

    # Palettes (grains tan, chunks darker by default).
    grain_palette: tuple[_RGB, ...] = (
        (228, 188, 110),
        (212, 168, 90),
        (192, 148, 76),
        (172, 130, 64),
    )
    chunk_palette: tuple[_RGB, ...] = (
        (148, 110, 50),
        (132, 92, 38),
        (118, 80, 30),
    )

    # Post-blast colour shift (Worms-style "scorched" look). On spawn each
    # particle samples a darken factor uniformly from this range and the
    # palette colour gets multiplied by (1 - factor). 0.0 = same colour,
    # 0.10 = 10 % darker. Set both ends to 0.0 to disable, or widen the
    # range for a more variegated rubble look.
    post_blast_darken_min: float = 0.0
    post_blast_darken_max: float = 0.10

    # Direction blend: 0.0 = every particle goes straight up (Worms-flat,
    # ignores the spawn offset → most horizontal spread), 1.0 = direction
    # is the radial outward vector from the blast centre (current
    # behaviour, more vertical from edges). Values > 1.0 overshoot →
    # the particle's launch direction points slightly *back* toward the
    # blast — useful for snow that wants to drift backward over the rim.
    direction_blend: float = 0.35

    # Self-collision grace period (frames) — for the first N frames after
    # spawn, particles ignore the heightmap landing test so rim-spawned
    # particles can clear the crater edge without immediately piling up.
    # Set to 0 to disable.
    no_collide_frames: int = 4

    # Edge-amplifier: if non-zero, the edge particles get an extra
    # horizontal velocity boost proportional to their distance from the
    # blast centre. Helps "blast out the edges" so they spread further.
    edge_outward_boost: float = 0.0

    # ── Impact dynamics ────────────────────────────────────────────────
    # A landing chunk's kinetic energy is computed as
    # ``ke = 0.5 * radius**2 * (vx**2 + vy**2)``. If that KE exceeds
    # ``impact_binding_ke`` (per-material "cohesion" threshold), the
    # *excess* drives a saturating drill effect: the chunk punches a
    # narrow trail of its own colour DOWN into the ground, and the
    # displaced volume is conserved by being re-ejected as a wider
    # rim splat above the impact. So fast/heavy chunks visibly "spread"
    # outward as they bite into the surface.
    # Set ``impact_binding_ke`` very high to disable drilling entirely.
    impact_binding_ke: float = 1.2e5
    # Maximum drill depth in pixels (the saturating limit). The actual
    # per-chunk drill is ``impact_drill_max_px * (1 - e^(-0.6*ratio))``
    # where ratio = excess_ke / impact_binding_ke.
    impact_drill_max_px: int = 6
    # Drill bit width as a fraction of ``splat_radius_px``. < 1.0 means
    # the drill is narrower than the surface splat (concentrated push).
    impact_drill_width_factor: float = 0.6
    # Material-conservation gain: of the volume drilled out, how much
    # gets re-ejected to the rim splat. 1.0 = fully conserved (mass
    # preserved); < 1.0 = some material "compacted" into the floor;
    # > 1.0 = chunks bring extra ground material outward (Worms-style
    # exaggerated ejecta).
    impact_eject_gain: float = 1.0
    # Crater-floor bonus: when the landing site is below ``GROUND_Y``
    # (already inside the existing crater bowl), excess KE gets this
    # multiplier applied — loose dirt offers less resistance. Set to
    # 1.0 to make crater-bowl impacts behave identically to surface.
    impact_loose_ground_multiplier: float = 2.0

    # ── Asset / texture support ────────────────────────────────────────
    # When this preset is "materialised" onto a sprite or per-pixel sim
    # mask, these knobs control how the splatter writes back into the
    # texture. The pipeline (slappyengine.material.* + the per-pixel
    # sim) reads these to build a stamp.
    texture_stain_color: _RGB = (172, 130, 64)  # paint colour
    texture_stain_alpha: int = 220              # 0..255 alpha at landing
    texture_decay_per_sec: float = 0.0          # 0 = permanent stain

    @property
    def n_particles(self) -> int:
        return self.n_grains + self.n_chunks

    @property
    def max_blast_angle_rad(self) -> float:
        return math.radians(self.max_blast_angle_deg)


# ── Built-in presets ──────────────────────────────────────────────────


SAND = SplatterPreset(
    name="sand",
    # Sand defaults: wide cone, uniform spawn (low blend), strong edge
    # boost. Reproduces the original "flat horizontal spray" look.
    max_blast_angle_deg=55.0,
    direction_blend=0.15,
    edge_outward_boost=140.0,
    no_collide_frames=3,
    # Sand binding tuned so most grains pile, fast chunks dig moderately.
    impact_binding_ke=2.0e5,
    impact_drill_max_px=3.5,
    impact_loose_ground_multiplier=2.0,
)

MUD = SplatterPreset(
    name="mud",
    # Mud — wider cone than before; lower gravity so it actually arcs
    # outward instead of dropping back in the crater. Edge-boost gives
    # rim particles real horizontal spread.
    max_blast_angle_deg=55.0,
    direction_blend=0.20,
    edge_outward_boost=120.0,
    no_collide_frames=4,
    n_grains=600,
    n_chunks=300,
    grain_speed_min=120.0,
    grain_speed_max=380.0,
    chunk_speed_min=100.0,
    chunk_speed_max=280.0,
    chunk_radius_min=3,
    chunk_radius_max=5,
    gravity=620.0,
    air_drag_per_sec=0.55,
    friction_per_sec=0.02,       # mud sticks fast
    splat_radius_px=8,           # wider splat
    splat_lift_max=4,
    # Mud is cohesive — but big chunks landing in the loose bowl still
    # displace. Binding sits well below chunk-median KE so most chunks
    # contribute to the crater, while grains keep piling on the rim.
    impact_binding_ke=1.2e5,
    impact_drill_max_px=4.0,
    impact_loose_ground_multiplier=2.5,
    grain_palette=(
        (110, 78, 42),
        (96, 66, 34),
        (78, 52, 26),
    ),
    chunk_palette=(
        (72, 50, 24),
        (58, 38, 18),
        (44, 28, 12),
    ),
    texture_stain_color=(70, 48, 22),
    texture_stain_alpha=240,
    # Wet mud reflects light unevenly — wider scorch range.
    post_blast_darken_min=0.0,
    post_blast_darken_max=0.20,
)

SLOPPY = SplatterPreset(
    name="sloppy",
    # Sloppy = wet mud. Fewer big chunks, lower per-chunk lift so the
    # accumulated pile stays natural-flat instead of growing into
    # twin mountains. Wider cone + strong edge boost reads as a
    # spread-out splat rather than a fountain.
    max_blast_angle_deg=60.0,
    direction_blend=0.10,
    edge_outward_boost=130.0,
    no_collide_frames=5,
    n_grains=500,
    n_chunks=180,
    grain_speed_min=60.0,
    grain_speed_max=240.0,
    chunk_speed_min=80.0,
    chunk_speed_max=200.0,
    chunk_radius_min=3,
    chunk_radius_max=5,
    gravity=700.0,
    air_drag_per_sec=0.40,
    friction_per_sec=0.0,        # sticks instantly
    splat_radius_px=6,
    splat_lift_max=2,
    # Sloppy = squishy globs; binding sits a bit below median KE so the
    # biggest globs dig and grains pile on the rim.
    impact_binding_ke=1.5e5,
    impact_drill_max_px=4.0,
    impact_loose_ground_multiplier=2.5,
    grain_palette=(
        (84, 58, 30),
        (66, 44, 22),
    ),
    chunk_palette=(
        (58, 38, 18),
        (38, 24, 10),
    ),
    texture_stain_color=(58, 38, 18),
    texture_stain_alpha=255,
)

ROCK = SplatterPreset(
    name="rock",
    max_blast_angle_deg=60.0,
    direction_blend=0.20,
    edge_outward_boost=160.0,    # rocks fly outward hard
    no_collide_frames=3,
    n_grains=300,
    n_chunks=300,
    grain_speed_max=420.0,
    chunk_speed_min=180.0,
    chunk_speed_max=360.0,
    chunk_radius_min=3,
    chunk_radius_max=5,
    gravity=760.0,
    air_drag_per_sec=0.65,
    friction_per_sec=0.15,       # rocks roll a bit
    splat_radius_px=4,
    splat_lift_max=3,
    # Rocks impact hard but only the fastest dig further — middling
    # binding so most pile on the rim and only a fraction punch through.
    impact_binding_ke=4.0e5,
    impact_drill_max_px=4.0,
    impact_loose_ground_multiplier=1.5,
    grain_palette=(
        (140, 130, 120),
        (110, 100, 90),
        (80, 72, 64),
    ),
    chunk_palette=(
        (70, 64, 58),
        (50, 46, 42),
    ),
    texture_stain_color=(60, 54, 48),
    texture_stain_alpha=200,
)

SNOW = SplatterPreset(
    name="snow",
    # Snow — very wide cone, gentle gravity; long no-collide so the drift
    # can carry over the rim and behind. direction_blend close to 0 so
    # particles spray uniformly across the full cone (no rim bias).
    max_blast_angle_deg=85.0,
    direction_blend=0.05,
    edge_outward_boost=80.0,
    no_collide_frames=8,
    n_grains=1400,
    n_chunks=50,
    grain_speed_min=40.0,
    grain_speed_max=240.0,
    chunk_speed_min=80.0,
    chunk_speed_max=180.0,
    grain_radius_min=1,
    grain_radius_max=2,
    chunk_radius_min=2,
    chunk_radius_max=3,
    gravity=420.0,               # slow fall
    air_drag_per_sec=0.30,       # heavy drag, lots of drift
    friction_per_sec=0.30,
    splat_radius_px=3,
    splat_lift_max=2,
    grain_palette=(
        (245, 248, 252),
        (220, 228, 240),
        (200, 212, 230),
    ),
    chunk_palette=(
        (230, 235, 245),
        (210, 220, 235),
    ),
    texture_stain_color=(232, 240, 250),
    texture_stain_alpha=180,
    texture_decay_per_sec=0.02,  # snow melts off textures slowly
    # Snow has very low binding — even soft impacts displace.
    impact_binding_ke=5.0e4,
    impact_drill_max_px=2.5,
    impact_loose_ground_multiplier=1.5,
)


PRESETS: dict[str, SplatterPreset] = {
    "sand": SAND,
    "mud": MUD,
    "sloppy": SLOPPY,
    "rock": ROCK,
    "snow": SNOW,
}


def get(name: str) -> SplatterPreset:
    """Look up a builtin preset by name."""
    if name not in PRESETS:
        raise KeyError(
            f"unknown splatter preset {name!r}; available: {sorted(PRESETS)}"
        )
    return PRESETS[name]


def make_preset(
    name: str,
    base: str | SplatterPreset = "sand",
    **overrides,
) -> SplatterPreset:
    """Derive a custom preset from a base by name + per-knob overrides.

    >>> mud_lite = make_preset("mud_lite", base="mud", n_chunks=100,
    ...                       max_blast_angle_deg=50.0)
    """
    if isinstance(base, str):
        base = get(base)
    from dataclasses import replace
    return replace(base, name=name, **overrides)


def materialise_texture(
    preset: SplatterPreset,
    stamp_size: int = 16,
) -> np.ndarray:
    """Bake a preset into an RGBA stamp the asset pipeline can paint with.

    Returns ``(stamp_size, stamp_size, 4)`` uint8. The stamp is a soft
    radial blob coloured by ``preset.texture_stain_color`` with alpha
    falling off to zero at the edge — game code paints this onto a
    sprite's diffuse map every time the splatter lands a chunk near a
    sprite footprint.
    """
    if stamp_size <= 0:
        raise ValueError(f"stamp_size must be > 0; got {stamp_size!r}")
    out = np.zeros((stamp_size, stamp_size, 4), dtype=np.uint8)
    cx = cy = (stamp_size - 1) / 2
    r_max = stamp_size / 2
    r, g, b = preset.texture_stain_color
    a_peak = float(preset.texture_stain_alpha)
    for y in range(stamp_size):
        for x in range(stamp_size):
            dx = x - cx
            dy = y - cy
            d = math.hypot(dx, dy)
            t = max(0.0, 1.0 - (d / r_max))
            alpha = int(t * t * a_peak)  # quadratic falloff
            out[y, x] = (r, g, b, alpha)
    return out


__all__ = [
    "SplatterPreset",
    "PRESETS",
    "SAND",
    "MUD",
    "SLOPPY",
    "ROCK",
    "SNOW",
    "get",
    "make_preset",
    "materialise_texture",
]
