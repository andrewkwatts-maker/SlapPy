"""Bake settled particles back to a static texture + BSP-style region
state for large scenes.

Once a Worms-style explosion has settled, every frame still pays the
per-particle cost to draw it. This module solves the perf problem by:

1. **Baking** — when a particle has been ``settled`` for one frame,
   :func:`bake_settled_particles` writes its colour into a static
   ``terrain_rgba`` numpy buffer and removes it from the live list.
2. **Region partition** — :class:`RegionGrid` divides the world into
   axis-aligned cells (BSP-light). Each cell carries a state
   (``ACTIVE`` / ``STATIC`` / ``DORMANT``) and a count of live
   particles inside it.
3. **Wake-on-disturbance** — when an event (impact, new explosion,
   player movement) touches a ``STATIC`` cell, :func:`wake_region`
   flips it back to ``ACTIVE`` and respawns the baked pixels as live
   particles so the dynamics can resume.

The split is conservative: at minimum, baking is correct (particles
move from live arrays to a static texture). The region partition is
the optional perf knob.

Designed for scenes where the active particle count must stay bounded
(e.g. a 1024×1024 map full of debris should not pay 1M-particle cost
per frame).
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np


# ── Baking ─────────────────────────────────────────────────────────────────


def bake_settled_particles(
    *,
    pos: np.ndarray,
    radius: np.ndarray,
    colour: np.ndarray,
    landed: np.ndarray,
    settled: np.ndarray,
    bake_flag: np.ndarray,
    terrain_rgba: np.ndarray,
) -> int:
    """Write every settled-but-not-yet-baked particle into ``terrain_rgba``.

    Parameters
    ----------
    pos, radius, colour
        Per-particle arrays (float32 N×2, float32 N, uint8 N×3).
    landed, settled
        Per-particle bool flags.
    bake_flag
        Per-particle bool — set to ``True`` for each newly baked
        particle. Callers use this to skip baked particles in the live
        loop (do NOT re-bake every frame; the bake-flag prevents that).
    terrain_rgba
        Static RGBA terrain buffer the colours get stamped into. Shape
        (H, W, 4) uint8.

    Returns
    -------
    int
        Count of newly baked particles this call.
    """
    if terrain_rgba.ndim != 3 or terrain_rgba.shape[2] != 4:
        raise ValueError(
            f"terrain_rgba must be (H, W, 4) uint8; got shape {terrain_rgba.shape}"
        )
    H, W = terrain_rgba.shape[:2]
    to_bake = settled & landed & ~bake_flag
    n_baked = 0
    for i in np.nonzero(to_bake)[0]:
        x = int(pos[i, 0])
        y = int(pos[i, 1])
        r = int(radius[i])
        if r < 1:
            r = 1
        rgb = colour[i]
        # Stamp a soft (2r+1)² square with full alpha at centre.
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                nx, ny = x + dx, y + dy
                if 0 <= nx < W and 0 <= ny < H:
                    terrain_rgba[ny, nx, 0] = rgb[0]
                    terrain_rgba[ny, nx, 1] = rgb[1]
                    terrain_rgba[ny, nx, 2] = rgb[2]
                    terrain_rgba[ny, nx, 3] = 255
        bake_flag[i] = True
        n_baked += 1
    return n_baked


# ── Region grid (BSP-light) ────────────────────────────────────────────────


class RegionState(enum.Enum):
    ACTIVE = "active"     # particles live + simulating
    STATIC = "static"     # baked into terrain; no live particles
    DORMANT = "dormant"   # never had particles; cheapest


@dataclass
class RegionGrid:
    """Uniform-grid spatial partition with per-cell activation state.

    Cells are axis-aligned. Each cell tracks an :class:`RegionState`
    and a live-particle count. Use :meth:`mark_static_when_idle` to
    transition ``ACTIVE`` cells to ``STATIC`` after they've had zero
    live particles for ``idle_frames`` consecutive frames.
    """

    width: int
    height: int
    cell_size: int = 64

    state: np.ndarray = field(init=False)
    live_count: np.ndarray = field(init=False)
    idle_frames_remaining: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        if self.cell_size <= 0:
            raise ValueError(f"cell_size must be > 0; got {self.cell_size}")
        if self.width <= 0 or self.height <= 0:
            raise ValueError(
                f"width/height must be > 0; got {self.width}x{self.height}"
            )
        cols = (self.width + self.cell_size - 1) // self.cell_size
        rows = (self.height + self.cell_size - 1) // self.cell_size
        self.state = np.full((rows, cols), RegionState.DORMANT.value,
                             dtype=object)
        self.live_count = np.zeros((rows, cols), dtype=np.int32)
        self.idle_frames_remaining = np.zeros((rows, cols), dtype=np.int32)

    @property
    def shape_cells(self) -> tuple[int, int]:
        return self.state.shape

    def _cell(self, x: float, y: float) -> tuple[int, int]:
        cx = int(np.clip(x // self.cell_size, 0, self.state.shape[1] - 1))
        cy = int(np.clip(y // self.cell_size, 0, self.state.shape[0] - 1))
        return cy, cx

    def record_live(self, positions: np.ndarray) -> None:
        """Recount live-particle occupancy from current positions.

        Pass the airborne+sliding particle ``pos`` array each frame.
        Cells with at least one particle become ``ACTIVE``; cells with
        zero start their idle countdown.
        """
        self.live_count.fill(0)
        for p in positions:
            cy, cx = self._cell(float(p[0]), float(p[1]))
            self.live_count[cy, cx] += 1
        # Anywhere we have particles → ACTIVE, reset countdown.
        active = self.live_count > 0
        self.state[active] = RegionState.ACTIVE.value
        self.idle_frames_remaining[active] = 0

    def mark_static_when_idle(self, idle_frames: int = 30) -> int:
        """Transition ``ACTIVE`` cells with zero particles for at least
        ``idle_frames`` frames to ``STATIC``.

        Returns the count of cells that transitioned this call.
        """
        rows, cols = self.state.shape
        transitioned = 0
        for cy in range(rows):
            for cx in range(cols):
                s = self.state[cy, cx]
                if s != RegionState.ACTIVE.value:
                    continue
                if self.live_count[cy, cx] > 0:
                    continue
                self.idle_frames_remaining[cy, cx] += 1
                if self.idle_frames_remaining[cy, cx] >= idle_frames:
                    self.state[cy, cx] = RegionState.STATIC.value
                    transitioned += 1
        return transitioned

    def wake_region(self, x: float, y: float, radius: int = 1) -> int:
        """Flip cells within ``radius`` cell-units of (x, y) to ``ACTIVE``.

        Returns the count of cells woken (already-ACTIVE cells don't
        count). Use this when a new explosion / collision impacts a
        previously-static region; the caller is responsible for
        respawning live particles from the baked texture (see
        :func:`unbake_region_to_particles`).
        """
        cy0, cx0 = self._cell(x, y)
        rows, cols = self.state.shape
        woken = 0
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                cy, cx = cy0 + dy, cx0 + dx
                if 0 <= cy < rows and 0 <= cx < cols:
                    if self.state[cy, cx] == RegionState.STATIC.value:
                        self.state[cy, cx] = RegionState.ACTIVE.value
                        self.idle_frames_remaining[cy, cx] = 0
                        woken += 1
        return woken

    def static_cell_count(self) -> int:
        return int((self.state == RegionState.STATIC.value).sum())

    def active_cell_count(self) -> int:
        return int((self.state == RegionState.ACTIVE.value).sum())


def unbake_region_to_particles(
    grid: RegionGrid,
    cy: int,
    cx: int,
    terrain_rgba: np.ndarray,
    *,
    out_pos: list,
    out_colour: list,
    out_radius: list,
) -> int:
    """Scan one cell's pixels in ``terrain_rgba`` and emit live-particle
    seeds for every non-transparent pixel. Used after :meth:`wake_region`
    to bring the static pixels back to life.

    Caller appends to ``out_pos`` / ``out_colour`` / ``out_radius`` and
    re-attaches the cell to the simulator.
    """
    y0 = cy * grid.cell_size
    x0 = cx * grid.cell_size
    y1 = min(y0 + grid.cell_size, terrain_rgba.shape[0])
    x1 = min(x0 + grid.cell_size, terrain_rgba.shape[1])
    n = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            if terrain_rgba[y, x, 3] == 0:
                continue
            out_pos.append((float(x), float(y)))
            out_colour.append(tuple(int(c) for c in terrain_rgba[y, x, :3]))
            out_radius.append(1.0)
            # Clear the baked pixel — it's now a live particle.
            terrain_rgba[y, x, 3] = 0
            n += 1
    return n


__all__ = [
    "RegionState",
    "RegionGrid",
    "bake_settled_particles",
    "unbake_region_to_particles",
]
