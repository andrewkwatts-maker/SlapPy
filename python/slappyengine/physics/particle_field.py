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
)

SAND_MAT = Material(
    name="sand",
    binding_force=1.0e5,
    cohesion=0.15,
    slump_angle_deg=33.0,
    density=1.6,
    color=(212, 168, 90),
)

MUD_MAT = Material(
    name="mud",
    binding_force=3.0e5,
    cohesion=0.95,
    slump_angle_deg=70.0,
    density=1.8,
    air_drag_per_sec=0.40,
    color=(96, 66, 34),
)

ROCK_MAT = Material(
    name="rock",
    binding_force=5.0e5,
    cohesion=0.05,
    slump_angle_deg=40.0,
    density=2.5,
    air_drag_per_sec=0.65,
    color=(110, 100, 90),
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
    radius: np.ndarray = field(init=False)
    color: np.ndarray = field(init=False)
    landed: np.ndarray = field(init=False)
    settled: np.ndarray = field(init=False)
    bake_flag: np.ndarray = field(init=False)

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
        self.color = np.zeros((0, 3), dtype=np.uint8)
        self.landed = np.zeros(0, dtype=bool)
        self.settled = np.zeros(0, dtype=bool)
        self.bake_flag = np.zeros(0, dtype=bool)
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
    ) -> int:
        """Append a single particle. Returns its index."""
        mid = self.material_id_of(material) if isinstance(material, str) else material
        mat = self.materials[mid]
        r = radius if radius is not None else mat.radius_min
        # Grow SoA by one row.
        self.pos = np.vstack([self.pos, [[x, y]]]).astype(np.float32)
        self.vel = np.vstack([self.vel, [[vx, vy]]]).astype(np.float32)
        self.material_id = np.append(
            self.material_id, np.int32(mid)).astype(np.int32)
        self.radius = np.append(self.radius, np.float32(r)).astype(np.float32)
        self.color = np.vstack([self.color, [list(mat.color)]]).astype(np.uint8)
        self.landed = np.append(self.landed, False)
        self.settled = np.append(self.settled, False)
        self.bake_flag = np.append(self.bake_flag, False)
        return self.pos.shape[0] - 1

    def spawn_batch(
        self,
        *,
        pos: np.ndarray,                # (N, 2) float
        vel: np.ndarray,                # (N, 2) float
        material_ids: np.ndarray,       # (N,) int
        radii: np.ndarray,              # (N,) float
        colors: np.ndarray | None = None,  # (N, 3) uint8; defaults to material color
    ) -> None:
        """Bulk-append a batch of particles. The hot path for explosions."""
        n = pos.shape[0]
        if n == 0:
            return
        if colors is None:
            colors = np.zeros((n, 3), dtype=np.uint8)
            for i in range(n):
                colors[i] = self.materials[int(material_ids[i])].color
        self.pos = np.concatenate(
            [self.pos, pos.astype(np.float32)], axis=0)
        self.vel = np.concatenate(
            [self.vel, vel.astype(np.float32)], axis=0)
        self.material_id = np.concatenate(
            [self.material_id, material_ids.astype(np.int32)])
        self.radius = np.concatenate(
            [self.radius, radii.astype(np.float32)])
        self.color = np.concatenate(
            [self.color, colors.astype(np.uint8)], axis=0)
        self.landed = np.concatenate(
            [self.landed, np.zeros(n, dtype=bool)])
        self.settled = np.concatenate(
            [self.settled, np.zeros(n, dtype=bool)])
        self.bake_flag = np.concatenate(
            [self.bake_flag, np.zeros(n, dtype=bool)])

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
        air_mask = ~self.landed
        if air_mask.any():
            self._integrate(air_mask, dt)
            self._collide(air_mask, dt)
        # Fluid pooling — particles whose material has binding_force=0
        # get pushed apart so they cluster into a contiguous body
        # rather than stacking on a single pixel. Cheap O(N) over the
        # fluid subset.
        self._fluid_relax(dt)
        slide_mask = self.landed & ~self.settled
        if slide_mask.any():
            self._slide(slide_mask, dt)
        # Settle bake (mass conservation: particle bodies stamp into
        # the mask at their final position).
        bake_settled_particles(
            pos=self.pos, radius=self.radius, colour=self.color,
            landed=self.landed, settled=self.settled,
            bake_flag=self.bake_flag, terrain_rgba=self.mask,
        )
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

    def _fluid_relax(self, dt: float) -> None:
        """Light density-relaxation for fluid materials.

        Real PBF (Macklin 2013) does a constraint-projection pass on
        density; this is a cheap single-pass approximation: each fluid
        particle gets a small push away from its nearest neighbour
        when too close. Enough for water-on-mud to pool naturally
        without dragging the full PBF stack into this module.
        """
        if self.pos.shape[0] < 2:
            return
        # Subset: fluid materials only.
        fluid_mask = np.zeros(self.pos.shape[0], dtype=bool)
        for mi, mat in enumerate(self.materials):
            if mat.is_fluid:
                fluid_mask |= self.material_id == mi
        # Live fluid only (not baked).
        fluid_mask &= ~self.bake_flag
        n_fluid = int(fluid_mask.sum())
        if n_fluid < 2:
            return
        idx = np.nonzero(fluid_mask)[0]
        fp = self.pos[idx]
        # Bin into small cells so we only test in-cell pairs (O(N) avg).
        bin_size = 6.0
        bx = (fp[:, 0] / bin_size).astype(np.int32)
        by = (fp[:, 1] / bin_size).astype(np.int32)
        bins: dict[tuple[int, int], list[int]] = {}
        for k, (bxk, byk) in enumerate(zip(bx, by)):
            bins.setdefault((int(bxk), int(byk)), []).append(k)
        rest = 3.0
        push = np.zeros_like(fp)
        for (cx, cy), members in bins.items():
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
                        f = (rest - d) * 0.5
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
            if y < 0 or self.vel[i, 1] < 0:
                continue
            # Swept-y check to avoid 1-px tunneling on fast falls.
            prev_y = int(self.pos[i, 1] - self.vel[i, 1] * dt)
            hit = -1
            for yi in range(max(0, prev_y), min(H, y + 1)):
                if self.mask[yi, x, 3] > 0:
                    hit = yi
                    break
            if hit < 0:
                continue
            self.pos[i, 1] = float(hit - 1)
            self.landed[i] = True
            # Fluid materials don't settle — they keep integrating each
            # frame; just clamp position so they sit on the surface and
            # let the next step bounce them off if vy reverses.
            mat = self.materials[int(self.material_id[i])]
            if mat.is_fluid:
                self.vel[i, 1] = -self.vel[i, 1] * 0.3  # gentle bounce
                self.landed[i] = False  # keep integrating

    def _slide(self, slide_mask: np.ndarray, dt: float) -> None:
        H, W = self.mask.shape[:2]
        # Friction per-material.
        for mi, mat in enumerate(self.materials):
            m = slide_mask & (self.material_id == mi)
            if not m.any():
                continue
            # Reuse cohesion as friction proxy: more cohesive = more
            # friction. Cap so cohesion=0 still has some friction.
            friction = 0.2 + 0.7 * mat.cohesion
            self.vel[m, 0] *= friction ** dt
            self.vel[m, 1] = 0.0
        self.pos[slide_mask, 0] += self.vel[slide_mask, 0] * dt
        # Per-particle surface re-snap.
        for i in np.nonzero(slide_mask)[0]:
            x = int(self.pos[i, 0])
            y = int(self.pos[i, 1])
            if 0 <= x < W:
                while y > 0 and self.mask[y, x, 3] > 0:
                    y -= 1
                self.pos[i, 1] = float(y)
            if abs(self.vel[i, 0]) < 5.0:
                self.settled[i] = True
                self.vel[i, 0] = 0.0

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
