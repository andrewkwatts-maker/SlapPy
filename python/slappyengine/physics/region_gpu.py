"""GPU-friendly region grid for ParticleField regional dispatch.

This module is the GPU-side companion to :class:`RegionGrid` in
:mod:`slappyengine.physics.baked_terrain`. It stores the same
``ACTIVE`` / ``STATIC`` / ``DORMANT`` per-cell semantics but as
``int8`` codes that map 1:1 to a WGSL ``i32`` / ``u32`` buffer, so the
grid can be uploaded straight to a storage buffer without per-frame
conversion.

The new piece is the **dirty bitmask**: any frame a cell's particle
membership changes (or a blast touches it), the corresponding bit is
set. Once per-pixel kernels (slump, detach, settle) are ported to
compute shaders, the dispatcher can:

1. Read the dirty bitmask each frame.
2. Build an indirect dispatch list of (workgroup_x, workgroup_y, 1)
   for only the dirty + ACTIVE cells.
3. Skip the ~95% of regions that haven't changed.

For a 4K × 4K map with cell_size=64 the grid is 64×64 = 4096 cells.
Per-cell cost is ~6 bytes (int8 state + int32 count + bool dirty),
so the whole grid fits in ~24 KB — one GPU upload per frame is free.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


# State codes match RegionState in baked_terrain, but as int8 so they
# can be uploaded to a GPU storage buffer of i32/u32 directly.
DORMANT: int = 0
ACTIVE: int = 1
STATIC: int = 2


@dataclass
class RegionGridGPU:
    """GPU-friendly region state.

    Same semantics as :class:`RegionGrid` but stores
    ``ACTIVE`` / ``STATIC`` / ``DORMANT`` per cell as ``int8`` instead
    of an enum, for direct GPU upload.

    Adds a ``dirty`` bool array (one bit per cell, exposed as bool for
    ergonomics; pack to ``uint32`` bitmask via :meth:`dirty_bitmask`)
    that gets flipped any frame a cell's particle membership changes.
    Used by indirect dispatch to skip unchanged regions on the GPU.
    """

    width: int
    height: int
    cell_size: int = 64

    state: np.ndarray = field(init=False)        # (rows, cols) int8
    live_count: np.ndarray = field(init=False)   # (rows, cols) int32
    dirty: np.ndarray = field(init=False)        # (rows, cols) bool

    def __post_init__(self) -> None:
        if self.cell_size <= 0:
            raise ValueError(f"cell_size must be > 0; got {self.cell_size}")
        if self.width <= 0 or self.height <= 0:
            raise ValueError(
                f"width/height must be > 0; got {self.width}x{self.height}"
            )
        cols = (self.width + self.cell_size - 1) // self.cell_size
        rows = (self.height + self.cell_size - 1) // self.cell_size
        self.state = np.full((rows, cols), DORMANT, dtype=np.int8)
        self.live_count = np.zeros((rows, cols), dtype=np.int32)
        self.dirty = np.zeros((rows, cols), dtype=bool)

    # ── shape helpers ──────────────────────────────────────────────────

    @property
    def shape_cells(self) -> tuple[int, int]:
        return self.state.shape

    @property
    def n_cells(self) -> int:
        return int(self.state.size)

    def _cell(self, x: float, y: float) -> tuple[int, int]:
        cx = int(np.clip(x // self.cell_size, 0, self.state.shape[1] - 1))
        cy = int(np.clip(y // self.cell_size, 0, self.state.shape[0] - 1))
        return cy, cx

    # ── per-frame updates ──────────────────────────────────────────────

    def record_live(self, positions: np.ndarray) -> None:
        """Recount live-particle occupancy from current positions.

        Pass the airborne+sliding particle ``pos`` array each frame.
        Cells with at least one particle become ``ACTIVE``. Cells whose
        live count differs from last frame (gained or lost particles)
        are flagged ``dirty`` for indirect dispatch.
        """
        prev_count = self.live_count.copy()
        self.live_count.fill(0)
        if positions is not None and len(positions) > 0:
            pos = np.asarray(positions, dtype=np.float32)
            cx = np.clip(
                (pos[:, 0] // self.cell_size).astype(np.int64),
                0, self.state.shape[1] - 1,
            )
            cy = np.clip(
                (pos[:, 1] // self.cell_size).astype(np.int64),
                0, self.state.shape[0] - 1,
            )
            flat = cy * self.state.shape[1] + cx
            counts = np.bincount(flat, minlength=self.n_cells)
            self.live_count = counts.reshape(self.state.shape).astype(np.int32)
        # Cells with live particles → ACTIVE.
        has_live = self.live_count > 0
        self.state[has_live] = ACTIVE
        # Any cell whose live count changed this frame → dirty.
        changed = self.live_count != prev_count
        if changed.any():
            self.dirty |= changed

    def active_cell_indices(self) -> np.ndarray:
        """Return flat indices of cells in ``ACTIVE`` state.

        Useful as the dispatch indirect list — each entry maps to a
        compute-shader workgroup that processes one cell's particles.
        """
        return np.flatnonzero(self.state == ACTIVE).astype(np.int32)

    def dirty_cell_indices(self) -> np.ndarray:
        """Return flat indices of dirty cells. Subset of active+changed."""
        return np.flatnonzero(self.dirty).astype(np.int32)

    def dirty_bitmask(self) -> np.ndarray:
        """Pack the dirty bool grid into a ``uint32`` bitmask.

        Returns a 1-D ``uint32`` array of length ``ceil(n_cells / 32)``,
        bit ``i`` set iff cell flat index ``i`` is dirty. This is the
        format compute shaders read when deciding whether to skip a
        workgroup.
        """
        flat = self.dirty.reshape(-1)
        n_words = (flat.size + 31) // 32
        out = np.zeros(n_words, dtype=np.uint32)
        idx = np.flatnonzero(flat)
        if idx.size:
            word = idx // 32
            bit = idx % 32
            # OR each bit into its word.
            np.bitwise_or.at(out, word, (np.uint32(1) << bit.astype(np.uint32)))
        return out

    def mark_dirty(self, x: float, y: float, radius: float) -> int:
        """Flag any cell within ``radius`` *world units* of (x, y) as dirty.

        Used by :func:`blast.detonate` to flag an impact region so the
        slump / detach compute shaders re-process those cells next
        frame even if their live-particle count hasn't shifted yet.

        Returns the number of cells newly flagged dirty this call.
        """
        if radius < 0:
            raise ValueError(f"radius must be >= 0; got {radius}")
        rows, cols = self.state.shape
        # Convert world radius → cell-space half-extent (ceiling).
        r_cells = int(np.ceil(radius / self.cell_size))
        cy0, cx0 = self._cell(x, y)
        y_lo = max(0, cy0 - r_cells)
        y_hi = min(rows - 1, cy0 + r_cells)
        x_lo = max(0, cx0 - r_cells)
        x_hi = min(cols - 1, cx0 + r_cells)
        # Within the bounding box, take cells whose centres lie within
        # `radius` world units of (x, y). Cells outside the bounding box
        # are guaranteed too far.
        marked = 0
        for cy in range(y_lo, y_hi + 1):
            cyc = (cy + 0.5) * self.cell_size
            for cx in range(x_lo, x_hi + 1):
                cxc = (cx + 0.5) * self.cell_size
                dx = cxc - x
                dy = cyc - y
                if dx * dx + dy * dy <= (radius + 0.5 * self.cell_size) ** 2:
                    if not self.dirty[cy, cx]:
                        marked += 1
                    self.dirty[cy, cx] = True
        return marked

    def clear_dirty(self) -> None:
        """End-of-frame reset of the dirty flag."""
        self.dirty.fill(False)

    # ── introspection ──────────────────────────────────────────────────

    def active_cell_count(self) -> int:
        return int((self.state == ACTIVE).sum())

    def static_cell_count(self) -> int:
        return int((self.state == STATIC).sum())

    def dormant_cell_count(self) -> int:
        return int((self.state == DORMANT).sum())

    def dirty_count(self) -> int:
        return int(self.dirty.sum())


__all__ = [
    "RegionGridGPU",
    "ACTIVE",
    "STATIC",
    "DORMANT",
]
