"""Connected-components labeller on cell-bond fields (CPU).

Used by :func:`HullTree.spawn_fragment` to detect when the cells inside a
single body have split into disjoint clusters via bond-severing.  Two cells
are considered connected iff both are "solid" (density above a small
threshold) AND the shared neighbour-bond is "alive" (bond strength above a
small threshold).  Bonds are stored half-edge-style on each cell:

- ``bond_e[i, j]`` is the bond between ``(i, j)`` and its east neighbour
  ``(i, j+1)`` — i.e. the edge crossing the vertical line between columns
  ``j`` and ``j+1`` on row ``i``.
- ``bond_s[i, j]`` is the bond between ``(i, j)`` and its south neighbour
  ``(i+1, j)``.

A simple BFS flood-fill (two-pass alternative would also work) is used
here.  Numpy bookkeeping is fine — Sprint 1 doesn't need a GPU labeller.
"""
from __future__ import annotations

from collections import deque

import numpy as np


DEFAULT_DENSITY_THRESHOLD = 0.1
DEFAULT_BOND_THRESHOLD = 0.05

# Sentinel label for background (non-solid) cells.
BACKGROUND_LABEL = -1


def connected_components(
    density: np.ndarray,
    bond_e: np.ndarray,
    bond_s: np.ndarray,
    density_threshold: float = DEFAULT_DENSITY_THRESHOLD,
    bond_threshold: float = DEFAULT_BOND_THRESHOLD,
) -> tuple[np.ndarray, int]:
    """Label connected components on a cell grid.

    Two cells ``a`` and ``b`` are connected iff:

    * Both have ``density > density_threshold``, AND
    * The shared bond between them (``bond_e`` from the western cell or
      ``bond_s`` from the northern cell) is ``> bond_threshold``.

    Parameters
    ----------
    density:
        ``(H, W)`` float array of per-cell density (channel 9 of the cell
        struct).  Usually ``H == W == 32``.
    bond_e:
        ``(H, W)`` float array.  ``bond_e[i, j]`` is the bond between
        ``(i, j)`` and ``(i, j+1)``.  Last column is ignored.
    bond_s:
        ``(H, W)`` float array.  ``bond_s[i, j]`` is the bond between
        ``(i, j)`` and ``(i+1, j)``.  Last row is ignored.
    density_threshold:
        Min density for a cell to be considered solid.  Default 0.1.
    bond_threshold:
        Min bond strength for a shared edge to count as connecting.
        Default 0.05.

    Returns
    -------
    label_map:
        ``(H, W)`` int32 array.  Each connected cluster has a unique
        non-negative label starting at 0.  Background (non-solid) cells
        are set to :data:`BACKGROUND_LABEL` (``-1``).
    n_labels:
        Number of distinct non-background clusters.
    """
    if density.shape != bond_e.shape or density.shape != bond_s.shape:
        raise ValueError(
            f"shape mismatch: density={density.shape} bond_e={bond_e.shape} "
            f"bond_s={bond_s.shape}"
        )
    if density.ndim != 2:
        raise ValueError(f"expected 2-D fields, got density.ndim={density.ndim}")

    h, w = density.shape
    solid = density > density_threshold
    labels = np.full((h, w), BACKGROUND_LABEL, dtype=np.int32)

    if not solid.any():
        return labels, 0

    # Convert bond arrays to bool once.
    be_ok = bond_e > bond_threshold
    bs_ok = bond_s > bond_threshold

    next_label = 0
    # Iterate in row-major order; whenever we hit an unlabeled solid cell
    # start a BFS that floods every reachable solid cell across alive bonds.
    for i in range(h):
        for j in range(w):
            if not solid[i, j] or labels[i, j] != BACKGROUND_LABEL:
                continue
            # New cluster.
            stack: deque[tuple[int, int]] = deque()
            stack.append((i, j))
            labels[i, j] = next_label
            while stack:
                ci, cj = stack.pop()
                # East neighbour: shared bond = bond_e[ci, cj].
                if cj + 1 < w and solid[ci, cj + 1] and be_ok[ci, cj] \
                        and labels[ci, cj + 1] == BACKGROUND_LABEL:
                    labels[ci, cj + 1] = next_label
                    stack.append((ci, cj + 1))
                # West neighbour: shared bond = bond_e[ci, cj-1].
                if cj - 1 >= 0 and solid[ci, cj - 1] and be_ok[ci, cj - 1] \
                        and labels[ci, cj - 1] == BACKGROUND_LABEL:
                    labels[ci, cj - 1] = next_label
                    stack.append((ci, cj - 1))
                # South neighbour: shared bond = bond_s[ci, cj].
                if ci + 1 < h and solid[ci + 1, cj] and bs_ok[ci, cj] \
                        and labels[ci + 1, cj] == BACKGROUND_LABEL:
                    labels[ci + 1, cj] = next_label
                    stack.append((ci + 1, cj))
                # North neighbour: shared bond = bond_s[ci-1, cj].
                if ci - 1 >= 0 and solid[ci - 1, cj] and bs_ok[ci - 1, cj] \
                        and labels[ci - 1, cj] == BACKGROUND_LABEL:
                    labels[ci - 1, cj] = next_label
                    stack.append((ci - 1, cj))
            next_label += 1

    return labels, next_label


__all__ = [
    "connected_components",
    "BACKGROUND_LABEL",
    "DEFAULT_DENSITY_THRESHOLD",
    "DEFAULT_BOND_THRESHOLD",
]
