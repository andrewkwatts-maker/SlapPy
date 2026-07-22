"""Uniform-grid spatial-hash broadphase for AABB overlap queries.

The previous broadphase iterated every pair of live root hulls
(``O(N^2)``).  At ``N = 50`` that is 1225 AABB tests per frame which
dominated the multi_body_50 benchmark (≈7.8 ms / frame, see
``benchmarks/baseline.json``).

A uniform-grid spatial hash buckets every AABB into the integer cells of
a fixed-pitch grid.  Each pair of hulls that *share* any cell becomes a
candidate; everything else is pruned for free.  The caller still runs
the cheap AABB-overlap + narrowphase tests on the candidate set, which
keeps the broadphase a pure spatial filter — there is no behavioural
change, only fewer pairs to consider.

Cell-size tuning
----------------
We size cells against the *typical* hull diagonal so most bodies live in
1–4 cells.  ``cell_size = 64`` covers the engine's reference 32-pixel
balls comfortably while still subdividing the 768-pixel multi_body_50
arena into a useful grid.  Wide ``fixed`` ground slabs (which span many
cells) cost us at most one duplicate-pair insertion per cell they touch
— but the consumer immediately culls ``fixed-vs-fixed`` pairs, and the
de-duplication step here drops repeats from multi-cell occupancy before
the caller ever sees them.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:  # pragma: no cover - import only for type hints
    from pharos_engine.physics.hull import HullTree


class SpatialHashBroadphase:
    """Uniform-grid spatial hash for AABB overlap queries.

    Cell size is tunable; default = 64 px, which matches the engine's
    typical hull diagonal (32-pixel ball + headroom).  Each AABB is
    inserted into every grid cell it overlaps; :meth:`candidate_pairs`
    returns the deduplicated set of ``(hull_a, hull_b)`` pairs whose
    AABBs share at least one cell.  Callers still run the actual
    AABB-overlap + narrowphase tests on those candidates.
    """

    def __init__(self, cell_size: float = 64.0, expected_bodies: int = 256) -> None:
        if cell_size <= 0.0:
            raise ValueError(f"cell_size must be positive, got {cell_size}")
        self.cell_size: float = float(cell_size)
        self._inv_cell: float = 1.0 / float(cell_size)
        # ``_cells[(cx, cy)]`` -> list of hull ids whose AABB touches that
        # cell.  Built fresh every rebuild; dict avoids the unbounded
        # memory of a dense world-spanning array for sparse scenes.
        self._cells: dict[tuple[int, int], list[int]] = {}
        # Live hull-id list cached from the last rebuild.  Not used by
        # ``candidate_pairs`` but useful for diagnostics / tests.
        self._inserted: list[int] = []
        # Caller may inspect this after rebuild for instrumentation.
        self.expected_bodies: int = int(expected_bodies)

    # -- internal helpers ----------------------------------------------------

    def _aabb_cell_range(self, x0: float, y0: float, x1: float, y1: float
                        ) -> tuple[int, int, int, int]:
        """Convert a world-space AABB to inclusive integer cell bounds.

        We floor each corner separately so the AABB is always covered
        even when it straddles a cell boundary or has zero extent on
        one axis (degenerate but legal).
        """
        inv = self._inv_cell
        cx0 = int(np.floor(x0 * inv))
        cy0 = int(np.floor(y0 * inv))
        cx1 = int(np.floor(x1 * inv))
        cy1 = int(np.floor(y1 * inv))
        return cx0, cy0, cx1, cy1

    # -- public API ----------------------------------------------------------

    def rebuild(self, hulls: "HullTree") -> None:
        """Re-insert every live root hull's AABB into the grid.

        ``hulls`` provides the SoA columns ``_alive``, ``parent_id``, and
        ``aabb`` we need.  Roots only (``parent_id < 0``) — matches the
        scope of :meth:`PhysicsWorld._broadphase`.
        """
        # Reset state.  We allocate fresh dicts/lists instead of clearing
        # in-place: the cell-count is usually tiny compared to the number
        # of bodies, and Python dict-clear is the same allocation pattern.
        self._cells = {}
        self._inserted = []

        alive = hulls._alive
        parent = hulls.parent_id
        # Mask of root, alive hulls — exact same predicate the old
        # broadphase used.
        roots_mask = alive & (parent < 0)
        if not roots_mask.any():
            return
        root_ids = np.nonzero(roots_mask)[0]
        # Snapshot the four AABB columns once — repeated indexing into a
        # 2-D ndarray is ~3x slower than vectorised slicing.
        aabbs = hulls.aabb[root_ids]
        inv = self._inv_cell
        # Pre-compute integer cell ranges for every body, vectorised.
        x0 = aabbs[:, 0]
        y0 = aabbs[:, 1]
        x1 = aabbs[:, 2]
        y1 = aabbs[:, 3]
        cx0 = np.floor(x0 * inv).astype(np.int64)
        cy0 = np.floor(y0 * inv).astype(np.int64)
        cx1 = np.floor(x1 * inv).astype(np.int64)
        cy1 = np.floor(y1 * inv).astype(np.int64)

        cells = self._cells
        inserted = self._inserted
        for k in range(root_ids.shape[0]):
            hid = int(root_ids[k])
            inserted.append(hid)
            ix0 = int(cx0[k]); iy0 = int(cy0[k])
            ix1 = int(cx1[k]); iy1 = int(cy1[k])
            # Most bodies hit 1-4 cells; the inner loop stays Python-flat.
            for cy in range(iy0, iy1 + 1):
                for cx in range(ix0, ix1 + 1):
                    bucket = cells.get((cx, cy))
                    if bucket is None:
                        cells[(cx, cy)] = [hid]
                    else:
                        bucket.append(hid)

    def candidate_pairs(self) -> list[tuple[int, int]]:
        """Return de-duplicated ``(hull_a, hull_b)`` candidate pairs.

        Caller still does the actual AABB-overlap test (fast: 4 float
        compares) and the narrowphase contact computation.  The returned
        list contains each ordered pair (``a < b``) at most once even if
        the two AABBs share multiple cells.
        """
        seen: set[tuple[int, int]] = set()
        pairs: list[tuple[int, int]] = []
        for occupants in self._cells.values():
            n = len(occupants)
            if n < 2:
                continue
            for i in range(n):
                ai = occupants[i]
                for j in range(i + 1, n):
                    bj = occupants[j]
                    if ai < bj:
                        key = (ai, bj)
                    else:
                        key = (bj, ai)
                    if key in seen:
                        continue
                    seen.add(key)
                    pairs.append(key)
        return pairs

    # -- diagnostics ---------------------------------------------------------

    @property
    def cell_count(self) -> int:
        """Number of grid cells currently occupied by at least one hull."""
        return len(self._cells)

    @property
    def inserted_count(self) -> int:
        """Number of hulls re-inserted by the last :meth:`rebuild` call."""
        return len(self._inserted)


__all__ = ["SpatialHashBroadphase"]
