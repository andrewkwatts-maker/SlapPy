"""Unified particle field — fluid, splatter, and solid materials share one sim.

This module is the engine-level base that ``sand_crater_demo``,
``fluid``, and any future Worms-style destructible-terrain game can sit on.
Three problems it solves at once:

1. **One material spec, many materials.** Every particle has a
   :class:`Material` id. Water has ``binding_force=0`` so it stays
   fluid forever; rock has high ``binding_force`` so it freezes into
   the per-pixel mask the instant it settles; mud sits between.
2. **Per-pixel collision mask.** :attr:`ParticleField.mask` is an
   ``(H, W, 4)`` RGBA buffer where ``alpha=255`` means solid. Overhangs,
   caves, irregular terrain all work because we never assume a per-column
   "top".
3. **Region-based scaling.** A :class:`~slappyengine.physics.baked_terrain.RegionGrid`
   tracks which cells have live particles; static regions skip the live
   loop entirely so a 4 K × 4 K map full of debris only pays for the
   active cells.

Rendering supports two modes:

* ``'discs'`` — stamp each particle as a filled disc of its material
  colour. Fast, looks pixel-arty, matches the existing splatter demo.
* ``'marching_squares'`` — sample a density grid and contour at an
  iso-level; fill the band with the colour of the nearest particle.
  Smooth, looks fluid-y. See :func:`render_marching_squares`.

This module does NOT replace the fluid PBF solver; it complements it.
Fluid particles route through the existing
:mod:`slappyengine.fluid.pbf` solver via :meth:`ParticleField.step` when
``material.binding_force == 0`` — splatter routes through the per-pixel
collision path here. That keeps PBF's pressure / surface tension work
isolated, and lets a single :class:`ParticleField` contain both.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from slappyengine.physics.baked_terrain import (
    RegionGrid,
    bake_settled_particles,
)


_RGB = tuple[int, int, int]


# ── Material spec ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class Material:
    """Physical properties of one substance.

    The key knob is ``binding_force``: if 0, the particle is a fluid (no
    settling — keeps integrating each frame); if > 0, the particle
    freezes into the per-pixel mask once its kinetic energy falls below
    ``binding_force``. Mid-range values give mud-like behaviour: flows
    while energetic, sets once disturbed enough has dissipated.
    """

    name: str

    # Cohesion / settling.
    binding_force: float = 0.0    # 0 = always fluid; > 0 = sets when KE < this
    cohesion: float = 0.8         # 1.0 = no slump; 0.0 = full sand-fall
    slump_angle_deg: float = 35.0

    # Physical.
    density: float = 1.0          # kg/L equivalent — drives buoyancy
    buoyancy: float = 1.0         # multiplier on density vs surrounding medium
    gravity_scale: float = 1.0    # 1.0 = standard; < 1 = floaty (snow)
    air_drag_per_sec: float = 0.55
    # Horizontal-slide friction. Low value = particles decay fast (mud
    # stops quickly); high value = particles roll a long way (rock).
    # Matches the friction_per_sec knob on SplatterPreset.
    friction_per_sec: float = 0.05
    settle_speed_threshold: float = 10.0
    settle_jitter: float = 0.35

    # ── High-velocity drilling (bullet holes, fragments) ───────────────
    # When this particle's kinetic energy at impact exceeds
    # ``binding_force``, it can punch through up to ``drill_max_px``
    # mask pixels along its velocity direction. Each drilled pixel
    # multiplies the particle's velocity by ``drill_velocity_loss``,
    # so a high loss (close to 1.0) means almost no slowdown (bullet
    # passes cleanly); a low loss (0.1) means heavy braking after a
    # few pixels. Set drill_max_px=0 to disable (default — only the
    # blast.detonate() path triggers drilling for most materials).
    drill_max_px: int = 0
    drill_velocity_loss: float = 0.7
    # Of the drilled pixel-volume, what fraction is spawned as ejecta
    # particles flying back out of the hole (Worms-style splash). 0.0
    # = no ejecta (clean tunnel); 1.0 = every drilled pixel becomes
    # a small new particle. Sits with ``mass_conservation`` (below) as
    # the system-wide knob for how much material survives the impact.
    drill_eject_gain: float = 0.0

    # General mass-conservation dial. Multiplied into every "create
    # particle" path (drill ejecta, drill drill-trail painting). < 1.0
    # = some material is lost on impact (compaction); 1.0 = exact;
    # > 1.0 = Worms-style exaggerated debris. Composed with the
    # per-path gains so the user can tune both at once.
    mass_conservation: float = 1.0

    # ── Fluid bulk-flow params (only meaningful when is_fluid) ─────────
    # Density-relaxation rest distance (px). Higher = water spreads
    # further before re-pooling; tunes the bulk-flow "wetness" feel.
    fluid_rest_distance: float = 3.0
    # Push factor per overlap unit. 0.5 = gentle, 1.5 = aggressive
    # spreading; high values can blow particles apart.
    fluid_pressure_factor: float = 0.5
    # Density-relax iterations per step. 1 = single pass (cheap, fluid
    # is a bit lumpy); 3-4 = smoother bulk flow, more cost.
    fluid_iterations: int = 1
    # Surface-flow nudge: when a fluid particle is resting on solid,
    # tilt the local horizontal velocity toward whichever side has
    # an open (empty) neighbour pixel. Drives "flow over the rim"
    # behaviour without a full pressure-solver. 0 = off.
    fluid_surface_flow: float = 0.0

    # ── Kinetic-phase fluidity (lerp from fluid → rigid as age grows) ──
    # Solid particles can behave fluid-like during their airborne /
    # sliding phase (sloshing globs of mud, dust clouds, etc.) and
    # then crystallise into rigid stamps once they "dry". The strength
    # controls how aggressively unsettled particles push apart while
    # in flight — kills vertical stacking columns. 0 = off; 0.5 is a
    # gentle "wet" feel; 1.0 is full bulk-flow.
    kinetic_fluidity: float = 0.0
    # Each particle picks a random "rigidify time" (in frames) uniformly
    # from this range at spawn. Below the time it behaves kinetic; above
    # it crystallises into rigid (slump + settle threshold apply fully).
    # Keep defaults TIGHT (5-15 frames) so particles consolidate
    # rapidly instead of flowing endlessly on the surface — that's the
    # "just flowing on the surface like water" failure mode the user
    # called out. Widen the range for organic spread.
    rigidify_frames_min: int = 5
    rigidify_frames_max: int = 12
    # On impact (landing), the remaining kinetic time is multiplied
    # by (1 - impact_stickiness). 0 = no effect; 1 = rigidifies
    # immediately on first contact (rock thunks down and stays).
    # Mud / clay: high stickiness; sand: medium; snow: low. Water
    # ignores this (binding_force=0 makes it permanently fluid).
    impact_stickiness: float = 0.6

    # Rendering.
    color: _RGB = (200, 200, 200)
    radius_min: int = 1
    radius_max: int = 2

    @property
    def is_fluid(self) -> bool:
        return self.binding_force <= 0.0


# Built-in materials — these mirror the splatter presets but are shared
# across fluid / splatter / future destructible work.
WATER = Material(
    name="water",
    binding_force=0.0,
    cohesion=0.0,
    density=1.0,
    color=(80, 140, 220),
    radius_min=1,
    radius_max=2,
    # Water: never rigidifies, no impact-stickiness, plenty of bulk-flow
    # iterations so it pools cleanly. fluid_surface_flow gives it the
    # "flow over the rim" nudge instead of just sitting where it lands.
    rigidify_frames_min=0,
    rigidify_frames_max=0,
    impact_stickiness=0.0,
    fluid_rest_distance=3.5,
    fluid_pressure_factor=0.6,
    fluid_iterations=2,
    fluid_surface_flow=0.3,
)

SAND_MAT = Material(
    name="sand",
    binding_force=1.0e5,
    cohesion=0.15,
    slump_angle_deg=33.0,
    density=1.6,
    color=(212, 168, 90),
    rigidify_frames_min=4,
    rigidify_frames_max=10,
    impact_stickiness=0.6,        # medium grip
    kinetic_fluidity=0.4,
)

MUD_MAT = Material(
    name="mud",
    binding_force=3.0e5,
    cohesion=0.95,
    slump_angle_deg=70.0,
    density=1.8,
    air_drag_per_sec=0.40,
    color=(96, 66, 34),
    rigidify_frames_min=3,
    rigidify_frames_max=8,
    impact_stickiness=0.85,        # mud STICKS hard on impact
    kinetic_fluidity=0.5,         # globs slosh while in flight
)

ROCK_MAT = Material(
    name="rock",
    binding_force=5.0e5,
    cohesion=0.05,
    slump_angle_deg=40.0,
    density=2.5,
    air_drag_per_sec=0.65,
    color=(110, 100, 90),
    rigidify_frames_min=2,
    rigidify_frames_max=5,
    impact_stickiness=0.9,         # rocks thunk and stay
    kinetic_fluidity=0.2,         # minimal in-flight push
)

SNOW_MAT = Material(
    name="snow",
    binding_force=5.0e4,
    cohesion=0.85,
    slump_angle_deg=50.0,
    density=0.4,
    gravity_scale=0.6,
    air_drag_per_sec=0.30,
    color=(232, 240, 250),
    rigidify_frames_min=8,
    rigidify_frames_max=20,
    impact_stickiness=0.4,         # snow drifts before settling
    kinetic_fluidity=0.6,
)


BUILTIN_MATERIALS: tuple[Material, ...] = (
    WATER, SAND_MAT, MUD_MAT, ROCK_MAT, SNOW_MAT,
)


# ── Field ──────────────────────────────────────────────────────────────


@dataclass
class ParticleField:
    """A 2D world of particles + a per-pixel solid mask.

    Allocate the per-pixel ``mask`` lazily as part of construction; the
    caller (or :func:`from_terrain`) is expected to fill it with the
    initial static terrain. Particles get appended via :meth:`spawn`;
    the simulator steps everything via :meth:`step`.
    """

    width: int
    height: int
    gravity: float = 720.0
    materials: list[Material] = field(default_factory=lambda: list(BUILTIN_MATERIALS))
    cell_size: int = 64

    # Particle SoA — initialised empty, grown via spawn().
    pos: np.ndarray = field(init=False)
    vel: np.ndarray = field(init=False)
    material_id: np.ndarray = field(init=False)
    radius: np.ndarray = field(init=False)         # airborne visual radius
    bake_radius: np.ndarray = field(init=False)    # per-particle stamp size on settle
    color: np.ndarray = field(init=False)
    landed: np.ndarray = field(init=False)
    settled: np.ndarray = field(init=False)
    bake_flag: np.ndarray = field(init=False)
    # Per-particle age + rigidify timeout for the fluid→rigid lerp.
    # Each spawn picks a random rigidify_at; kinetic_age increments
    # each step. While age < rigidify_at, particle is "kinetic" and
    # gets a relax push so flying globs spread laterally instead of
    # stacking. After rigidify_at, particle behaves rigidly (settles
    # easily, full slump cohesion).
    kinetic_age: np.ndarray = field(init=False)
    rigidify_at: np.ndarray = field(init=False)

    # Per-pixel solid mask (the world).
    mask: np.ndarray = field(init=False)
    # Per-pixel "loose" flag — True for pixels added by settled
    # particles, False for fixed terrain set via fill_ground(). Only
    # loose pixels participate in the slump pass, so the original
    # crater bowl stays open as chunks pile around it.
    loose: np.ndarray = field(init=False)
    # Companion fixed-mask used to keep slump from touching terrain
    # that was placed by fill_ground / direct mask writes.
    _fixed_mask: np.ndarray = field(init=False)
    _rng: np.random.Generator = field(init=False)
    region_grid: RegionGrid = field(init=False)
    _name_to_id: dict[str, int] = field(init=False)

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError(
                f"width/height must be > 0; got {self.width}x{self.height}"
            )
        self.pos = np.zeros((0, 2), dtype=np.float32)
        self.vel = np.zeros((0, 2), dtype=np.float32)
        self.material_id = np.zeros(0, dtype=np.int32)
        self.radius = np.zeros(0, dtype=np.float32)
        self.bake_radius = np.zeros(0, dtype=np.int32)
        self.color = np.zeros((0, 3), dtype=np.uint8)
        self.landed = np.zeros(0, dtype=bool)
        self.settled = np.zeros(0, dtype=bool)
        self.bake_flag = np.zeros(0, dtype=bool)
        self.kinetic_age = np.zeros(0, dtype=np.int32)
        self.rigidify_at = np.zeros(0, dtype=np.int32)
        self.mask = np.zeros((self.height, self.width, 4), dtype=np.uint8)
        self.loose = np.zeros((self.height, self.width), dtype=bool)
        self._fixed_mask = np.zeros((self.height, self.width), dtype=bool)
        self._rng = np.random.default_rng(2026)
        self.region_grid = RegionGrid(
            width=self.width, height=self.height, cell_size=self.cell_size,
        )
        self._name_to_id = {m.name: i for i, m in enumerate(self.materials)}

    # ── Material lookup ────────────────────────────────────────────────

    def material(self, name_or_id: str | int) -> Material:
        if isinstance(name_or_id, str):
            return self.materials[self._name_to_id[name_or_id]]
        return self.materials[name_or_id]

    def material_id_of(self, name: str) -> int:
        return self._name_to_id[name]

    # ── Spawning ───────────────────────────────────────────────────────

    def spawn(
        self,
        *,
        x: float,
        y: float,
        vx: float = 0.0,
        vy: float = 0.0,
        material: str | int = 0,
        radius: int | None = None,
        bake_radius: int = 0,
    ) -> int:
        """Append a single particle. Returns its index.

        ``radius`` is the airborne disc size (what the user sees in
        flight). ``bake_radius`` is the per-particle stamp size when
        it settles into the mask — 0 = 1 pixel (one unit of mass),
        1 = 3×3 chunk, 2 = 5×5 boulder. Separating these lets chunks
        look chunky on the ground without bloating airborne render.
        """
        mid = self.material_id_of(material) if isinstance(material, str) else material
        mat = self.materials[mid]
        r = radius if radius is not None else mat.radius_min
        # Grow SoA by one row.
        self.pos = np.vstack([self.pos, [[x, y]]]).astype(np.float32)
        self.vel = np.vstack([self.vel, [[vx, vy]]]).astype(np.float32)
        self.material_id = np.append(
            self.material_id, np.int32(mid)).astype(np.int32)
        self.radius = np.append(self.radius, np.float32(r)).astype(np.float32)
        self.bake_radius = np.append(
            self.bake_radius, np.int32(bake_radius)).astype(np.int32)
        self.color = np.vstack([self.color, [list(mat.color)]]).astype(np.uint8)
        self.landed = np.append(self.landed, False)
        self.settled = np.append(self.settled, False)
        self.bake_flag = np.append(self.bake_flag, False)
        # Pick a per-particle rigidify time from the material range.
        rigid_min = max(0, mat.rigidify_frames_min)
        rigid_max = max(rigid_min, mat.rigidify_frames_max)
        rigid_at = (rigid_min if rigid_min == rigid_max
                    else int(self._rng.integers(rigid_min, rigid_max + 1)))
        self.kinetic_age = np.append(self.kinetic_age, np.int32(0))
        self.rigidify_at = np.append(
            self.rigidify_at, np.int32(rigid_at)).astype(np.int32)
        return self.pos.shape[0] - 1

    def spawn_batch(
        self,
        *,
        pos: np.ndarray,                # (N, 2) float
        vel: np.ndarray,                # (N, 2) float
        material_ids: np.ndarray,       # (N,) int
        radii: np.ndarray,              # (N,) float
        colors: np.ndarray | None = None,  # (N, 3) uint8; defaults to material color
        bake_radii: np.ndarray | None = None,  # (N,) int; default 0 (1px each)
        rigidify_at: np.ndarray | None = None,  # (N,) int; per-particle timeout
    ) -> None:
        """Bulk-append a batch of particles. The hot path for explosions."""
        n = pos.shape[0]
        if n == 0:
            return
        if colors is None:
            colors = np.zeros((n, 3), dtype=np.uint8)
            for i in range(n):
                colors[i] = self.materials[int(material_ids[i])].color
        if bake_radii is None:
            bake_radii = np.zeros(n, dtype=np.int32)
        # Per-particle rigidify_at: sample from each material's range
        # if not supplied. Using a per-particle random timeout gives
        # the organic "some settle fast, some stay wet longer" feel.
        if rigidify_at is None:
            rigidify_at = np.zeros(n, dtype=np.int32)
            for k in range(n):
                m = self.materials[int(material_ids[k])]
                lo = max(0, m.rigidify_frames_min)
                hi = max(lo, m.rigidify_frames_max)
                rigidify_at[k] = (lo if lo == hi
                                  else int(self._rng.integers(lo, hi + 1)))
        self.pos = np.concatenate(
            [self.pos, pos.astype(np.float32)], axis=0)
        self.vel = np.concatenate(
            [self.vel, vel.astype(np.float32)], axis=0)
        self.material_id = np.concatenate(
            [self.material_id, material_ids.astype(np.int32)])
        self.radius = np.concatenate(
            [self.radius, radii.astype(np.float32)])
        self.bake_radius = np.concatenate(
            [self.bake_radius, bake_radii.astype(np.int32)])
        self.color = np.concatenate(
            [self.color, colors.astype(np.uint8)], axis=0)
        self.landed = np.concatenate(
            [self.landed, np.zeros(n, dtype=bool)])
        self.settled = np.concatenate(
            [self.settled, np.zeros(n, dtype=bool)])
        self.bake_flag = np.concatenate(
            [self.bake_flag, np.zeros(n, dtype=bool)])
        self.kinetic_age = np.concatenate(
            [self.kinetic_age, np.zeros(n, dtype=np.int32)])
        self.rigidify_at = np.concatenate(
            [self.rigidify_at, rigidify_at.astype(np.int32)])

    # ── Static-terrain helpers ─────────────────────────────────────────

    def fill_ground(self, *, top_y: int, color: _RGB, sub_color: _RGB | None = None) -> None:
        """Paint a flat ground line into the mask. ``top_y`` rows below
        get ``color``; rows below that get ``sub_color`` (or the same).

        Pixels written here are marked FIXED in ``_fixed_mask`` so the
        slump pass skips them — original terrain stays put while
        settled particles around it can still flow.
        """
        if sub_color is None:
            sub_color = color
        self.mask[top_y, :, :3] = color
        self.mask[top_y, :, 3] = 255
        self.mask[top_y + 1: self.height, :, :3] = sub_color
        self.mask[top_y + 1: self.height, :, 3] = 255
        self._fixed_mask[top_y:self.height, :] = True

    def carve(self, mask_bool: np.ndarray) -> None:
        """Clear alpha to 0 wherever ``mask_bool`` (shape ``(H, W)``) is True.

        Carved pixels also lose their fixed flag — if particles re-fill
        them later, the new pixels are loose and can slump.
        """
        if mask_bool.shape != (self.height, self.width):
            raise ValueError(
                f"mask_bool must be ({self.height}, {self.width}); "
                f"got {mask_bool.shape}"
            )
        self.mask[mask_bool, 3] = 0
        self._fixed_mask[mask_bool] = False
        self.loose[mask_bool] = False

    # ── Step ───────────────────────────────────────────────────────────

    def step(self, dt: float) -> None:
        """Advance one frame.

        Airborne particles integrate gravity + drag, then check per-
        pixel collision against ``mask``. Landed particles slide with
        friction. Settled-non-baked particles get baked into ``mask``
        and removed from the live loop. Fluid materials skip the
        binding settle path (always integrate) and get a lightweight
        density-relaxation pass so they pool. Slump pass runs on
        ``loose`` pixels for the most cohesion-deficient material.
        """
        if self.pos.shape[0] == 0:
            return
        # Age increment for all live particles — drives the fluid→rigid
        # lerp via per-particle rigidify_at timeout.
        live = ~self.bake_flag
        self.kinetic_age[live] += 1
        air_mask = ~self.landed
        if air_mask.any():
            self._integrate(air_mask, dt)
            self._collide(air_mask, dt)
        # Fluid pooling — particles whose material has binding_force=0
        # get pushed apart so they cluster into a contiguous body
        # rather than stacking on a single pixel. Cheap O(N) over the
        # fluid subset.
        self._fluid_relax(dt)
        # Kinetic-phase relax — landed-but-not-rigid solid particles
        # also push apart (lateral spread), mimicking a wet glob phase
        # that crystallises as the rigidify timer expires.
        self._kinetic_relax(dt)
        slide_mask = self.landed & ~self.settled
        if slide_mask.any():
            self._slide(slide_mask, dt)
        # Settle bake — use per-particle bake_radius so chunks bake
        # chunky (3×3 or 5×5) while grains stay 1px. Total bake mass
        # is sum of (2*br+1)² across settled particles — predictable
        # and matches the user's visual expectation that chunks look
        # like clumps in the final pile.
        bake_settled_particles(
            pos=self.pos, radius=self.radius, colour=self.color,
            landed=self.landed, settled=self.settled,
            bake_flag=self.bake_flag, terrain_rgba=self.mask,
            per_particle_bake_radius=self.bake_radius,
        )
        # ── Push fluids out of newly-baked solid ────────────────────
        # Without this, mud chunks baking on top of water created a
        # "drilled in, came back up" oscillation. Now we explicitly
        # buoy any fluid particle trapped in solid up to the nearest
        # empty pixel above.
        self._push_fluids_out_of_solid()
        # Mark the newly-baked pixels as LOOSE so the slump pass can
        # rearrange them. The baked function set alpha=255 at every
        # stamped pixel, so we replay the same condition here.
        self._mark_newly_baked_loose()
        # Per-frame slump on loose pixels for the LEAST cohesive
        # baked material currently sitting on the field.
        self._slump_loose(dt)
        # Region tracking — static cells are skipped on subsequent
        # frames, the big perf knob for large maps.
        live = ~self.bake_flag
        if live.any():
            self.region_grid.record_live(self.pos[live])
        else:
            self.region_grid.record_live(np.zeros((0, 2), dtype=np.float32))
        self.region_grid.mark_static_when_idle(idle_frames=30)

    def _mark_newly_baked_loose(self) -> None:
        """Mark every alpha-solid pixel as loose if it isn't already
        flagged fixed. Cheap: just OR the alpha mask into ``loose``.

        Pixels written by ``fill_ground`` were marked loose=False at
        write time (see :meth:`fill_ground`); everything else baked via
        settled particles is loose by default.
        """
        # Only flip loose where alpha is set AND loose is currently
        # False. We don't want to flip fixed-ground pixels just because
        # they're solid.
        # NB: fill_ground records its own pixels into a side-table; if
        # the user writes directly to mask we don't auto-promote.
        new_solid = (self.mask[..., 3] > 0) & ~self._fixed_mask
        self.loose |= new_solid

    def _slump_loose(self, dt: float) -> None:
        """Cellular fall + diagonal slump on loose pixels only.

        Operates on the LEAST-cohesive baked material's settings (one
        global pass per frame keeps it cheap). Fixed terrain is never
        touched, so the original crater bowl stays open.
        """
        # Pick the least-cohesive material currently represented in the
        # loose mask. If no loose pixels, skip.
        if not self.loose.any():
            return
        # Heuristic: use the lowest-cohesion material we've seen in the
        # settled particle set as the slump rate driver.
        if self.settled.any():
            cohs = np.array(
                [self.materials[int(self.material_id[i])].cohesion
                 for i in np.nonzero(self.settled)[0]],
                dtype=np.float32,
            )
            min_coh = float(cohs.min())
            angle = float(self.materials[
                int(self.material_id[np.argmin(cohs)])].slump_angle_deg)
        else:
            return
        if min_coh >= 1.0:
            return
        fall_prob = (1.0 - min_coh) * 0.08
        side_prob = fall_prob * 0.4
        if fall_prob <= 0.0:
            return
        # Cheap CA pass on the loose subset. Iterate bottom-up so a
        # falling pixel isn't re-tested in the same sweep.
        Hh, Ww = self.loose.shape
        solid = self.mask[..., 3] > 0
        rng = self._rng
        for y in range(Hh - 2, 0, -1):
            row_loose = self.loose[y]
            if not row_loose.any():
                continue
            below_empty = ~solid[y + 1]
            fall = row_loose & below_empty
            if fall.any() and fall_prob > 0.0:
                roll = rng.random(Ww) < fall_prob
                fall &= roll
                if fall.any():
                    idx = np.where(fall)[0]
                    self.mask[y + 1, idx] = self.mask[y, idx]
                    self.mask[y, idx, 3] = 0
                    self.loose[y + 1, idx] = True
                    self.loose[y, idx] = False
                    solid[y + 1, idx] = True
                    solid[y, idx] = False
            # Sideways slump into a step-down neighbour.
            if side_prob > 0.0:
                still = row_loose & ~below_empty
                left_lower = np.zeros(Ww, bool)
                left_lower[1:] = (
                    still[1:]
                    & ~solid[y + 1, :-1]
                    & ~solid[y, :-1]
                )
                right_lower = np.zeros(Ww, bool)
                right_lower[:-1] = (
                    still[:-1]
                    & ~solid[y + 1, 1:]
                    & ~solid[y, 1:]
                )
                slump_l = left_lower & (rng.random(Ww) < side_prob)
                slump_r = right_lower & (rng.random(Ww) < side_prob)
                if slump_l.any():
                    idx = np.where(slump_l)[0]
                    self.mask[y, idx - 1] = self.mask[y, idx]
                    self.mask[y, idx, 3] = 0
                    self.loose[y, idx - 1] = True
                    self.loose[y, idx] = False
                    solid[y, idx - 1] = True
                    solid[y, idx] = False
                if slump_r.any():
                    idx = np.where(slump_r)[0]
                    self.mask[y, idx + 1] = self.mask[y, idx]
                    self.mask[y, idx, 3] = 0
                    self.loose[y, idx + 1] = True
                    self.loose[y, idx] = False
                    solid[y, idx + 1] = True
                    solid[y, idx] = False

    def _push_fluids_out_of_solid(self) -> None:
        """Any live fluid particle sitting in a solid pixel gets buoyed
        up to the nearest empty pixel above. Called after settle bake
        so mud chunks falling on top of water can't push the water
        permanently into the mask (which manifested as "water drills
        in and comes back up").
        """
        H, W = self.mask.shape[:2]
        live = ~self.bake_flag
        if not live.any():
            return
        for i in np.nonzero(live)[0]:
            mat = self.materials[int(self.material_id[i])]
            if not mat.is_fluid:
                continue
            x = int(self.pos[i, 0])
            y = int(self.pos[i, 1])
            if not (0 <= x < W and 0 <= y < H):
                continue
            if self.mask[y, x, 3] == 0:
                continue  # already in empty space
            # Walk up until empty.
            new_y = y
            while new_y > 0 and self.mask[new_y, x, 3] > 0:
                new_y -= 1
            self.pos[i, 1] = float(new_y)
            self.vel[i, 1] = 0.0  # buoyancy doesn't impart velocity

    def _kinetic_relax(self, dt: float) -> None:
        """Push non-fluid particles apart so they can't occupy the
        same position. Two regimes:

        - **In-air kinetic phase** (age < rigidify_at): strong push
          scaled by ``kinetic_fluidity`` * (1 - age/rigidify_at).
        - **Landed sliding phase** (age >= rigidify_at but not yet
          settled): a smaller *baseline* push that always runs so
          multiple particles can't stack on one pixel and bake into
          a tall single-column pile. This is the inter-particle
          collision the user asked for.
        """
        if self.pos.shape[0] < 2:
            return
        n = self.pos.shape[0]
        eligible = np.zeros(n, dtype=bool)
        strengths = np.zeros(n, dtype=np.float32)
        for mi, mat in enumerate(self.materials):
            if mat.is_fluid:
                continue
            m = (self.material_id == mi) & (~self.bake_flag) & (~self.settled)
            if not m.any():
                continue
            indices = np.nonzero(m)[0]
            rig = self.rigidify_at[m].astype(np.float32)
            age = self.kinetic_age[m].astype(np.float32)
            lerp = np.clip(1.0 - age / np.maximum(rig, 1.0), 0.0, 1.0)
            # Kinetic strength fades to 0 as particle rigidifies.
            kinetic_s = mat.kinetic_fluidity * lerp
            # Baseline collision strength — always positive so even
            # rigid sliding particles can't overlap. Capped so it
            # doesn't dominate cohesive piles.
            baseline = 0.4
            strengths_m = np.maximum(kinetic_s, baseline)
            eligible[indices] = True
            strengths[indices] = strengths_m
        if not eligible.any():
            return
        idx = np.nonzero(eligible)[0]
        if idx.size < 2:
            return
        # Cell-binned pair check.
        kp = self.pos[idx]
        rest = 2.5  # tighter than fluid so particles don't drift apart
        bin_size = rest * 1.5
        bx = (kp[:, 0] / bin_size).astype(np.int32)
        by = (kp[:, 1] / bin_size).astype(np.int32)
        bins: dict[tuple[int, int], list[int]] = {}
        for k, (bxk, byk) in enumerate(zip(bx, by)):
            bins.setdefault((int(bxk), int(byk)), []).append(k)
        push = np.zeros_like(kp)
        for members in bins.values():
            if len(members) < 2:
                continue
            for a in members:
                for b in members:
                    if a >= b:
                        continue
                    dx = kp[a, 0] - kp[b, 0]
                    dy = kp[a, 1] - kp[b, 1]
                    d2 = dx * dx + dy * dy
                    if d2 < rest * rest and d2 > 0.0:
                        d = math.sqrt(d2)
                        ga = strengths[idx[a]]
                        gb = strengths[idx[b]]
                        f = (rest - d) * 0.4 * 0.5 * (ga + gb)
                        nx = dx / d
                        ny = dy / d
                        push[a, 0] += nx * f
                        push[a, 1] += ny * f
                        push[b, 0] -= nx * f
                        push[b, 1] -= ny * f
        self.pos[idx] += push

    def _fluid_relax(self, dt: float) -> None:
        """Per-material density-relaxation for fluid particles.

        Cheap PBF-style approximation. Each fluid material's
        ``fluid_rest_distance`` sets the spread; ``fluid_pressure_factor``
        the push strength; ``fluid_iterations`` the number of passes
        per step (more = smoother flow at higher cost).
        """
        if self.pos.shape[0] < 2:
            return
        # Per-material loop so each fluid uses its own knobs.
        for mi, mat in enumerate(self.materials):
            if not mat.is_fluid:
                continue
            fluid_mask = (self.material_id == mi) & (~self.bake_flag)
            if int(fluid_mask.sum()) < 2:
                continue
            idx = np.nonzero(fluid_mask)[0]
            rest = float(mat.fluid_rest_distance)
            press = float(mat.fluid_pressure_factor)
            iters = max(1, int(mat.fluid_iterations))
            bin_size = max(1.0, rest * 1.5)
            for _ in range(iters):
                fp = self.pos[idx]
                bx = (fp[:, 0] / bin_size).astype(np.int32)
                by = (fp[:, 1] / bin_size).astype(np.int32)
                bins: dict[tuple[int, int], list[int]] = {}
                for k, (bxk, byk) in enumerate(zip(bx, by)):
                    bins.setdefault((int(bxk), int(byk)), []).append(k)
                push = np.zeros_like(fp)
                for members in bins.values():
                    if len(members) < 2:
                        continue
                    for a in members:
                        for b in members:
                            if a >= b:
                                continue
                            dx = fp[a, 0] - fp[b, 0]
                            dy = fp[a, 1] - fp[b, 1]
                            d2 = dx * dx + dy * dy
                            if d2 < rest * rest and d2 > 0.0:
                                d = math.sqrt(d2)
                                f = (rest - d) * press
                                nx = dx / d
                                ny = dy / d
                                push[a, 0] += nx * f
                                push[a, 1] += ny * f
                                push[b, 0] -= nx * f
                                push[b, 1] -= ny * f
                self.pos[idx] += push

    # ── Internals ──────────────────────────────────────────────────────

    def _integrate(self, air_mask: np.ndarray, dt: float) -> None:
        # Per-material drag and gravity scale.
        for mi, mat in enumerate(self.materials):
            m = air_mask & (self.material_id == mi)
            if not m.any():
                continue
            self.vel[m] *= mat.air_drag_per_sec ** dt
            self.vel[m, 1] += self.gravity * mat.gravity_scale * dt
        self.pos[air_mask] += self.vel[air_mask] * dt

    def _collide(self, air_mask: np.ndarray, dt: float) -> None:
        H, W = self.mask.shape[:2]
        for i in np.nonzero(air_mask)[0]:
            x = int(self.pos[i, 0])
            y = int(self.pos[i, 1])
            if x < 0 or x >= W or y >= H:
                self.landed[i] = True
                self.settled[i] = True
                continue
            if y < 0:
                continue
            mat = self.materials[int(self.material_id[i])]
            # Drilling materials always check collision regardless of
            # direction (bullets going up should still hit ceilings).
            # Settling materials skip when moving upward (no catching
            # on their own launch surface).
            if mat.drill_max_px == 0 and self.vel[i, 1] < 0:
                continue
            # Swept-xy DDA from previous-frame pixel to current pixel —
            # catches both fast falls (vertical) and fast bullets
            # (horizontal). One alpha probe per step along the line.
            prev_x = int(self.pos[i, 0] - self.vel[i, 0] * dt)
            prev_y = int(self.pos[i, 1] - self.vel[i, 1] * dt)
            dx = x - prev_x
            dy = y - prev_y
            steps = max(abs(dx), abs(dy), 1)
            hit_x = -1
            hit_y = -1
            for s in range(steps + 1):
                cx = prev_x + (dx * s) // steps
                cy = prev_y + (dy * s) // steps
                if not (0 <= cx < W and 0 <= cy < H):
                    continue
                if self.mask[cy, cx, 3] > 0:
                    hit_x = cx
                    hit_y = cy
                    break
            if hit_x < 0:
                continue
            # ── High-velocity drilling path ──────────────────────────
            if mat.drill_max_px > 0:
                vsq = float(self.vel[i, 0] ** 2 + self.vel[i, 1] ** 2)
                ke = 0.5 * (max(1.0, self.radius[i]) ** 2) * vsq
                if ke > mat.binding_force:
                    self._drill_through(i, hit_x, hit_y, mat)
                    if not self.landed[i]:
                        continue
                    else:
                        continue
            self.pos[i, 0] = float(hit_x)
            self.pos[i, 1] = float(hit_y - 1)
            self.landed[i] = True
            if mat.is_fluid:
                # Fluid landing: kill the downward velocity but do NOT
                # bounce. Bouncing kept water oscillating at the surface
                # so it never noticed terrain being carved out below.
                # vy=0 lets gravity re-accelerate immediately, so the
                # particle falls into any hole that opens beneath it.
                self.vel[i, 1] = 0.0
                self.landed[i] = False  # keep integrating
            else:
                # Solid impact: collapse the remaining kinetic time by
                # ``impact_stickiness``. impact_stickiness=0 leaves the
                # full kinetic window; impact_stickiness=1 rigidifies
                # the particle on the very next frame (rock thunk).
                remaining = max(0, int(self.rigidify_at[i]
                                       - self.kinetic_age[i]))
                shrink = (1.0 - mat.impact_stickiness)
                self.rigidify_at[i] = (
                    self.kinetic_age[i] + int(remaining * shrink)
                )

    def _drill_through(self, i: int, x: int, hit_y: int, mat: Material) -> None:
        """High-KE particle punches into the mask along its velocity.

        Walks a DDA-style line from the impact point, clearing alpha
        pixels until ``drill_max_px`` is exhausted OR the particle's KE
        drops below ``binding_force``. Optionally spawns ejecta at the
        impact point. Sets ``landed[i] = True`` if the drill stops
        inside the mask; otherwise leaves the particle airborne with
        a reduced velocity past the exit pixel.
        """
        H, W = self.mask.shape[:2]
        vx = float(self.vel[i, 0])
        vy = float(self.vel[i, 1])
        speed = math.hypot(vx, vy)
        if speed <= 0.0:
            self.landed[i] = True
            return
        dx = vx / speed
        dy = vy / speed
        # Start at the hit pixel and step in unit increments along the
        # velocity direction. Clear alpha as we go.
        px = float(x) + 0.5
        py = float(hit_y) + 0.5
        drilled = 0
        gain = mat.drill_eject_gain * mat.mass_conservation
        # Capture some colours along the drill line so any ejecta we
        # spawn carries the terrain's hue.
        line_colours: list[tuple[int, int, int]] = []
        while drilled < mat.drill_max_px:
            xi = int(px)
            yi = int(py)
            if not (0 <= xi < W and 0 <= yi < H):
                break
            if self.mask[yi, xi, 3] == 0:
                break  # exited the wall
            line_colours.append((
                int(self.mask[yi, xi, 0]),
                int(self.mask[yi, xi, 1]),
                int(self.mask[yi, xi, 2]),
            ))
            self.mask[yi, xi, 3] = 0
            self.loose[yi, xi] = False
            drilled += 1
            # Velocity drops per pixel drilled. Then re-check KE.
            self.vel[i, 0] *= mat.drill_velocity_loss
            self.vel[i, 1] *= mat.drill_velocity_loss
            vsq = (self.vel[i, 0] ** 2 + self.vel[i, 1] ** 2)
            ke = 0.5 * (max(1.0, self.radius[i]) ** 2) * vsq
            if ke < mat.binding_force * 0.5:
                # Out of steam — stop inside the wall.
                self.pos[i, 0] = float(xi)
                self.pos[i, 1] = float(yi)
                self.landed[i] = True
                break
            px += dx
            py += dy
        else:
            # Loop completed without break — exited cleanly.
            self.pos[i, 0] = px
            self.pos[i, 1] = py
            self.landed[i] = False
        # Spawn ejecta proportional to drilled pixels.
        n_eject = int(round(drilled * gain))
        if n_eject > 0 and line_colours:
            ej_pos = np.tile([float(x), float(hit_y)], (n_eject, 1)).astype(np.float32)
            angles = self._rng.uniform(-math.pi / 2, math.pi / 2, n_eject)
            speeds = self._rng.uniform(80.0, 220.0, n_eject)
            ej_vel = np.column_stack([
                np.sin(angles) * speeds,
                -np.cos(angles) * speeds,
            ]).astype(np.float32)
            ej_mids = np.full(n_eject, int(self.material_id[i]), dtype=np.int32)
            ej_radii = np.zeros(n_eject, dtype=np.float32)
            # Sample a colour from the drilled line per ejecta.
            ej_colours = np.zeros((n_eject, 3), dtype=np.uint8)
            pick = self._rng.integers(0, len(line_colours), n_eject)
            for k in range(n_eject):
                ej_colours[k] = line_colours[int(pick[k])]
            self.spawn_batch(
                pos=ej_pos, vel=ej_vel,
                material_ids=ej_mids, radii=ej_radii,
                colors=ej_colours,
            )

    def _slide(self, slide_mask: np.ndarray, dt: float) -> None:
        H, W = self.mask.shape[:2]
        for mi, mat in enumerate(self.materials):
            m = slide_mask & (self.material_id == mi)
            if not m.any():
                continue
            # Lower friction_per_sec = harder braking. Mud (0.02)
            # decays vel by 98%^(1/30) ≈ 5.7%/frame; sand (0.05) by
            # ~9.5%/frame; rock (0.15) by ~6%/frame.
            self.vel[m, 0] *= mat.friction_per_sec ** dt
            self.vel[m, 1] = 0.0
        self.pos[slide_mask, 0] += self.vel[slide_mask, 0] * dt
        # Per-particle surface re-snap + roll-downhill redirect +
        # per-material settle threshold.
        for i in np.nonzero(slide_mask)[0]:
            x = int(self.pos[i, 0])
            y = int(self.pos[i, 1])
            if 0 <= x < W:
                while y > 0 and self.mask[y, x, 3] > 0:
                    y -= 1
                # Roll-downhill: if the particle would perch on top of
                # a column that's significantly taller than its lateral
                # neighbours, redirect it toward the lower side. This
                # is what stops 7 chunks stacking on one column and
                # baking into a vertical pile — the user's complaint.
                my_top = y
                left_top = self._column_top(max(0, x - 1))
                right_top = self._column_top(min(W - 1, x + 1))
                # Higher y = lower in image. So neighbour "lower"
                # means neighbour's top > my_top.
                slump_step = 2  # px difference required to redirect
                left_drop = left_top - my_top
                right_drop = right_top - my_top
                if left_drop >= slump_step and right_drop >= slump_step:
                    direction = 1 if self._rng.random() > 0.5 else -1
                elif left_drop >= slump_step:
                    direction = -1
                elif right_drop >= slump_step:
                    direction = 1
                else:
                    direction = 0
                if direction != 0:
                    new_x = max(0, min(W - 1, x + direction))
                    new_y = self._column_top(new_x) - 1
                    self.pos[i, 0] = float(new_x)
                    self.pos[i, 1] = float(max(0, new_y))
                    # Small velocity kick along the slope so the
                    # particle keeps moving (more rolling, less stalling).
                    self.vel[i, 0] += direction * 6.0
                else:
                    self.pos[i, 1] = float(y)
            mat = self.materials[int(self.material_id[i])]
            jitter = mat.settle_jitter
            base = mat.settle_speed_threshold
            threshold = base * (1.0 + float(self._rng.uniform(-jitter, jitter))) \
                if jitter > 0 else base
            if abs(self.vel[i, 0]) < threshold:
                self.settled[i] = True
                self.vel[i, 0] = 0.0

    def _column_top(self, x: int) -> int:
        """Return the y of the topmost solid pixel in column x.
        If the column is empty, returns the bottom of the field.
        """
        if x < 0 or x >= self.width:
            return self.height
        col = self.mask[:, x, 3]
        nz = np.flatnonzero(col)
        if nz.size == 0:
            return self.height
        return int(nz[0])

    # ── Rendering ──────────────────────────────────────────────────────

    def render(self, *, mode: str = "discs") -> np.ndarray:
        """Composite the static mask + live particles to RGB.

        Returns ``(H, W, 3)`` uint8.
        """
        H, W = self.mask.shape[:2]
        arr = np.zeros((H, W, 3), dtype=np.uint8)
        m = self.mask[..., 3] > 0
        if m.any():
            arr[m] = self.mask[m, :3]
        if mode == "discs":
            for i in range(self.pos.shape[0]):
                if self.bake_flag[i]:
                    continue
                x = int(self.pos[i, 0])
                y = int(self.pos[i, 1])
                r = int(self.radius[i])
                if not (0 <= x < W and 0 <= y < H):
                    continue
                y0 = max(0, y - r); y1 = min(H, y + r + 1)
                x0 = max(0, x - r); x1 = min(W, x + r + 1)
                arr[y0:y1, x0:x1] = self.color[i]
        elif mode == "marching_squares":
            arr = _render_marching_squares(self, arr)
        else:
            raise ValueError(f"unknown render mode: {mode!r}")
        return arr


# ── Marching-squares renderer ──────────────────────────────────────────


def _render_marching_squares(field: ParticleField, base: np.ndarray) -> np.ndarray:
    """Sample a density grid from live particles and paint a smoothed
    iso-surface using the nearest particle's colour. The contour is at
    iso=0.5 of the per-cell density; cells above iso get filled.
    """
    H, W = field.mask.shape[:2]
    cell = 4  # grid resolution; coarser = smoother + faster
    gh, gw = H // cell, W // cell
    density = np.zeros((gh, gw), dtype=np.float32)
    color_grid = np.zeros((gh, gw, 3), dtype=np.uint8)
    live = ~field.bake_flag
    if not live.any():
        return base
    idx = np.nonzero(live)[0]
    gx = np.clip((field.pos[idx, 0] / cell).astype(np.int32), 0, gw - 1)
    gy = np.clip((field.pos[idx, 1] / cell).astype(np.int32), 0, gh - 1)
    # Accumulate density (count) and choose a representative colour
    # per cell (last-write-wins is cheap; good enough at small cell).
    for k, i in enumerate(idx):
        density[gy[k], gx[k]] += 1.0
        color_grid[gy[k], gx[k]] = field.color[i]
    # Smooth density with a 1-step blur.
    pad = np.pad(density, 1, mode="edge")
    smoothed = (
        pad[1:-1, 1:-1]
        + 0.5 * (pad[:-2, 1:-1] + pad[2:, 1:-1] + pad[1:-1, :-2] + pad[1:-1, 2:])
    ) / 3.0
    iso = 0.5
    fill = smoothed >= iso
    # Upsample fill+colour to pixel resolution and composite.
    fill_up = np.repeat(np.repeat(fill, cell, axis=0), cell, axis=1)
    color_up = np.repeat(np.repeat(color_grid, cell, axis=0), cell, axis=1)
    fill_up = fill_up[:H, :W]
    color_up = color_up[:H, :W]
    base[fill_up] = color_up[fill_up]
    return base


__all__ = [
    "Material",
    "ParticleField",
    "BUILTIN_MATERIALS",
    "WATER",
    "SAND_MAT",
    "MUD_MAT",
    "ROCK_MAT",
    "SNOW_MAT",
]
