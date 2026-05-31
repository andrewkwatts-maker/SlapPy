"""Reusable spatial hash for ParticleField particles.

CPU implementation built on numpy. Designed to mirror the layout used by
``shaders/particle_spatial_hash.wgsl`` so a future GPU port can reuse the
same ``cell_start`` / ``cell_count`` / ``sorted_ids`` layout without
changing call sites.

Pipeline (matches the GPU shader's three-pass design):

  1. Quantise every particle position to a flat grid-cell key.
  2. Counting-sort the particle ids by key:
       cell_count   = bincount(keys)
       cell_start   = cumsum(cell_count)
       sorted_ids   = argsort(keys, stable)
  3. Lookup a 3x3 cell neighbourhood and filter by radius.

The grid covers the rectangle ``[0, width) x [0, height)`` plus a small
margin so particles that drift just outside the field still hash to a
valid cell. Particles outside the padded grid are dropped from the hash
(they cannot collide with anything inside the field).

Used by ``_kinetic_relax`` and ``_fluid_relax`` to replace their per-call
``dict``-of-lists binning with a single vectorised pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np


@dataclass
class SpatialHash:
    """Flat 2-D spatial hash backed by a counting-sort layout.

    The arrays use the same names / semantics as the WGSL compute shader
    in ``shaders/particle_spatial_hash.wgsl`` so a future GPU
    implementation can be swapped in transparently.
    """

    cell_size: float
    width: int
    height: int

    # GPU-style flat buffers, lazily (re)allocated on rebuild.
    cell_start: np.ndarray = field(
        default_factory=lambda: np.zeros(0, dtype=np.int32)
    )
    cell_count: np.ndarray = field(
        default_factory=lambda: np.zeros(0, dtype=np.int32)
    )
    sorted_ids: np.ndarray = field(
        default_factory=lambda: np.zeros(0, dtype=np.int32)
    )

    # Cached grid dimensions (number of cells along each axis).
    _gx: int = 0
    _gy: int = 0
    # Cached count of particles that were actually inserted (i.e. fell
    # inside the padded grid). Particles outside are silently dropped.
    _n_inserted: int = 0

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    def _grid_dims(self) -> tuple[int, int]:
        """Number of cells along each axis. A 1-cell pad on each side
        catches particles that drift just outside ``[0, width)`` /
        ``[0, height)``."""
        if self.cell_size <= 0:
            raise ValueError(f"cell_size must be positive (got {self.cell_size})")
        gx = max(1, int(np.ceil(self.width / self.cell_size))) + 2
        gy = max(1, int(np.ceil(self.height / self.cell_size))) + 2
        return gx, gy

    def _world_to_cell(self, positions: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Return integer (cx, cy) coords for each row of ``positions``.

        Coordinates are biased by +1 so that a particle at the very
        bottom-left of the field still has cx >= 0 (matching the +1 grid
        pad in ``_grid_dims``).
        """
        inv = 1.0 / self.cell_size
        cx = np.floor(positions[:, 0] * inv).astype(np.int32) + 1
        cy = np.floor(positions[:, 1] * inv).astype(np.int32) + 1
        return cx, cy

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rebuild(self, positions: np.ndarray) -> None:
        """Rebuild the hash from a 2-D ``positions`` array.

        ``positions`` must have shape ``(n, 2)`` and float dtype. The
        rebuild is O(n + gx*gy) using ``np.bincount`` + stable
        ``np.argsort``; no Python loops over particles.
        """
        gx, gy = self._grid_dims()
        self._gx, self._gy = gx, gy
        n_cells = gx * gy

        if positions.size == 0:
            # Zero-particle case: keep buffers in a consistent shape so
            # downstream queries (which always read ``cell_start`` /
            # ``cell_count``) don't have to special-case empty input.
            self.cell_count = np.zeros(n_cells, dtype=np.int32)
            self.cell_start = np.zeros(n_cells, dtype=np.int32)
            self.sorted_ids = np.zeros(0, dtype=np.int32)
            self._n_inserted = 0
            return

        if positions.ndim != 2 or positions.shape[1] != 2:
            raise ValueError(
                f"positions must have shape (n, 2), got {positions.shape}"
            )

        cx, cy = self._world_to_cell(positions)

        # Mask off particles outside the padded grid. They simply don't
        # participate in this frame's queries.
        in_bounds = (cx >= 0) & (cx < gx) & (cy >= 0) & (cy < gy)
        keys = np.where(in_bounds, cy * gx + cx, -1).astype(np.int64)

        valid = keys >= 0
        valid_keys = keys[valid]
        valid_ids = np.nonzero(valid)[0].astype(np.int32)
        self._n_inserted = int(valid_ids.size)

        # Counts per cell. minlength keeps the array sized to the full
        # grid even when the top cells are empty.
        cell_count = np.bincount(valid_keys, minlength=n_cells).astype(np.int32)

        # Exclusive prefix sum gives the write-offset for each cell.
        cell_start = np.zeros(n_cells, dtype=np.int32)
        if n_cells > 1:
            np.cumsum(cell_count[:-1], out=cell_start[1:])

        # Stable sort by key groups particles within each cell. We sort
        # ``valid_ids`` by ``valid_keys`` to get sorted particle ids.
        if valid_ids.size > 0:
            order = np.argsort(valid_keys, kind="stable")
            sorted_ids = valid_ids[order]
        else:
            sorted_ids = np.zeros(0, dtype=np.int32)

        self.cell_count = cell_count
        self.cell_start = cell_start
        self.sorted_ids = sorted_ids

    def query_neighbours(
        self, position: Sequence[float], radius: float
    ) -> np.ndarray:
        """Return particle ids within ``radius`` of ``position``.

        Walks the (2r/cell_size + 1)^2 block of cells covering the query
        disk, then filters the candidates by squared distance. Suitable
        as a CPU helper for tests and rare-path queries; the hot path
        (kinetic / fluid relax) should iterate directly over neighbour
        cells in vectorised form.
        """
        if self.sorted_ids.size == 0 or self._n_inserted == 0:
            return np.zeros(0, dtype=np.int32)
        if radius < 0:
            raise ValueError(f"radius must be non-negative (got {radius})")

        px = float(position[0])
        py = float(position[1])
        inv = 1.0 / self.cell_size

        # Reach in cells. +1 to cover the partial cell at the edge of
        # the query disk.
        reach = int(np.ceil(radius * inv)) + 1
        center_cx = int(np.floor(px * inv)) + 1
        center_cy = int(np.floor(py * inv)) + 1

        gx, gy = self._gx, self._gy
        cx_lo = max(0, center_cx - reach)
        cx_hi = min(gx - 1, center_cx + reach)
        cy_lo = max(0, center_cy - reach)
        cy_hi = min(gy - 1, center_cy + reach)
        if cx_lo > cx_hi or cy_lo > cy_hi:
            return np.zeros(0, dtype=np.int32)

        # Gather all candidate ids from the cell block.
        chunks: list[np.ndarray] = []
        for cy in range(cy_lo, cy_hi + 1):
            row_base = cy * gx
            for cx in range(cx_lo, cx_hi + 1):
                key = row_base + cx
                count = int(self.cell_count[key])
                if count == 0:
                    continue
                start = int(self.cell_start[key])
                chunks.append(self.sorted_ids[start : start + count])

        if not chunks:
            return np.zeros(0, dtype=np.int32)

        candidates = np.concatenate(chunks)
        return candidates

    def query_radius(
        self,
        positions: np.ndarray,
        position: Sequence[float],
        radius: float,
    ) -> np.ndarray:
        """Like ``query_neighbours`` but additionally filters by exact
        Euclidean distance against the supplied ``positions`` array.

        ``positions`` must be the same array that was passed to the
        most recent ``rebuild`` (or one indexable by the same ids).
        """
        candidates = self.query_neighbours(position, radius)
        if candidates.size == 0:
            return candidates
        px = float(position[0])
        py = float(position[1])
        dx = positions[candidates, 0] - px
        dy = positions[candidates, 1] - py
        d2 = dx * dx + dy * dy
        mask = d2 <= radius * radius
        return candidates[mask]


__all__ = ["SpatialHash"]
