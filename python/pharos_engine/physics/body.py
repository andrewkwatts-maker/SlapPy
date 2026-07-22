"""PhysicsBody — author-facing handle to a hierarchical-hull entity.

A body wraps one root :class:`HullTree` slot plus optional cell-grid slots
for its T2 leaves.  ``PhysicsWorld.create_body`` is the constructor; callers
do not instantiate ``PhysicsBody`` directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from pharos_engine._compat import CellMaterial
from pharos_engine.physics.cell import CELL_GRID_SIZE, CELL_PIXEL_STRUCT

if TYPE_CHECKING:
    from pharos_engine.physics.world import PhysicsWorld


# Default initial density of a cell whose silhouette alpha >= the mask threshold.
_INITIAL_DENSITY = 1.0


@dataclass
class PhysicsBody:
    """Handle returned by :meth:`PhysicsWorld.create_body`.

    Stores the root hull id and the material lookup so callers can query
    state without reaching into the world's internal arrays.
    """
    world: "PhysicsWorld"
    root_hull_id: int
    material_name: str
    material: CellMaterial
    silhouette_size: tuple[int, int]  # (h, w) of the original silhouette mask
    fixed: bool

    @property
    def position(self) -> tuple[float, float]:
        """Current world position of the root hull."""
        p = self.world.hulls.position[self.root_hull_id]
        return float(p[0]), float(p[1])

    @position.setter
    def position(self, value: tuple[float, float]) -> None:
        self.world.hulls.position[self.root_hull_id, 0] = float(value[0])
        self.world.hulls.position[self.root_hull_id, 1] = float(value[1])
        self.world.hulls.mark_dirty()

    @property
    def velocity(self) -> tuple[float, float]:
        """Current world velocity of the root hull."""
        v = self.world.hulls.velocity[self.root_hull_id]
        return float(v[0]), float(v[1])

    @velocity.setter
    def velocity(self, value: tuple[float, float]) -> None:
        self.world.hulls.velocity[self.root_hull_id, 0] = float(value[0])
        self.world.hulls.velocity[self.root_hull_id, 1] = float(value[1])
        self.world.hulls.mark_dirty()

    @property
    def mass(self) -> float:
        return float(self.world.hulls.mass[self.root_hull_id])

    @property
    def radius(self) -> float:
        return float(self.world.hulls.radius[self.root_hull_id])

    @property
    def cell_grid_id(self) -> int:
        return int(self.world.hulls.cell_grid_id[self.root_hull_id])

    @property
    def cells(self) -> np.ndarray | None:
        """View of this body's (32, 32, 16) cell grid, or None if T0/T1."""
        gid = self.cell_grid_id
        if gid < 0:
            return None
        return self.world.cell_pool.slot_view(gid)


def silhouette_to_cells(
    silhouette: np.ndarray,
    material: CellMaterial,
) -> np.ndarray:
    """Resample a binary/alpha silhouette mask into a 32x32 cell grid.

    The mask is bilinearly downsampled to ``CELL_GRID_SIZE``; cells whose
    sampled alpha exceeds the engine's mask threshold are seeded with
    initial density + initial heat.  Bond strengths default to intact (1.0)
    via the pool acquire path; we don't touch them here.
    """
    h, w = silhouette.shape[:2]
    # Take a single-channel alpha view.
    if silhouette.ndim == 3:
        alpha = silhouette[..., -1].astype(np.float32)
    else:
        alpha = silhouette.astype(np.float32)
    if alpha.max() > 1.5:
        alpha = alpha / 255.0

    # Cheap box-filter downsample to CELL_GRID_SIZE x CELL_GRID_SIZE.
    cells = np.zeros(
        (CELL_GRID_SIZE, CELL_GRID_SIZE, CELL_PIXEL_STRUCT.total_channels),
        dtype=np.float32,
    )
    sy = h / CELL_GRID_SIZE
    sx = w / CELL_GRID_SIZE
    for cy in range(CELL_GRID_SIZE):
        y0 = int(cy * sy)
        y1 = max(y0 + 1, int((cy + 1) * sy))
        for cx in range(CELL_GRID_SIZE):
            x0 = int(cx * sx)
            x1 = max(x0 + 1, int((cx + 1) * sx))
            a = float(alpha[y0:y1, x0:x1].mean())
            if a >= 0.05:
                # density at index 9, heat at index 12 (per CELL_PIXEL_STRUCT)
                cells[cy, cx, 9] = _INITIAL_DENSITY * a
                cells[cy, cx, 12] = material.initial_heat
            # Bond channels: leave at default 0.0 here; pool.acquire() will
            # have seeded them to 1.0 already and we copy *into* that buffer.
    return cells


def make_circle_silhouette(diameter: int) -> np.ndarray:
    """Return a (d, d) float32 alpha mask of an antialiased filled disk."""
    d = diameter
    yy, xx = np.mgrid[0:d, 0:d].astype(np.float32)
    cx = cy = (d - 1) / 2.0
    r = (d - 1) / 2.0
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    # Antialiased edge: full alpha until r-0.5, fade to 0 at r+0.5
    alpha = np.clip(r + 0.5 - dist, 0.0, 1.0)
    return alpha.astype(np.float32)


def make_rect_silhouette(width: int, height: int) -> np.ndarray:
    """Return a (height, width) solid alpha mask."""
    return np.ones((height, width), dtype=np.float32)
