"""Generic graph topology primitives.

`connected_components` finds disjoint clusters in a graph defined by an
edge list. Generic over node count and edge representation; works for
the softbody beam graph (fragment detection after beams break), for the
legacy 2D cell-bond grid (legacy compat helper provided), and for any
future graph-structured state.

Algorithm: weighted union-find with path compression — O((N + E)·α(N)),
faster than BFS for sparse graphs typical in softbody fragmentation.
"""
from __future__ import annotations

import numpy as np


BACKGROUND_LABEL = -1


def _uf_find(parent: np.ndarray, x: int) -> int:
    root = x
    while parent[root] != root:
        root = int(parent[root])
    # Path compression
    while parent[x] != root:
        nxt = int(parent[x])
        parent[x] = root
        x = nxt
    return root


def _uf_union(parent: np.ndarray, size: np.ndarray, a: int, b: int) -> None:
    ra = _uf_find(parent, a)
    rb = _uf_find(parent, b)
    if ra == rb:
        return
    if size[ra] < size[rb]:
        ra, rb = rb, ra
    parent[rb] = ra
    size[ra] += size[rb]


def connected_components(
    n_nodes: int,
    edges: np.ndarray,
    active: np.ndarray | None = None,
    node_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, int]:
    """Label connected components on an edge-list graph.

    Parameters
    ----------
    n_nodes
        Number of nodes in the graph. Labels will be in `[0, n_components)`
        for live nodes and :data:`BACKGROUND_LABEL` for masked-out nodes.
    edges
        ``(E, 2)`` int array of edge endpoints. Self-loops and duplicates
        are tolerated.
    active
        Optional ``(E,)`` bool array. ``False`` edges are ignored (use this
        to skip broken beams without rebuilding the edge list).
    node_mask
        Optional ``(n_nodes,)`` bool array. ``False`` nodes are not
        clustered (label = :data:`BACKGROUND_LABEL`).

    Returns
    -------
    labels
        ``(n_nodes,)`` int32 array. Each cluster has a unique label in
        ``[0, n_components)``. Masked nodes are :data:`BACKGROUND_LABEL`.
    n_components
        Number of distinct clusters across the live nodes.
    """
    if n_nodes < 0:
        raise ValueError("n_nodes must be non-negative")
    if edges.ndim != 2 or edges.shape[1] != 2:
        raise ValueError(f"edges must be (E, 2); got {edges.shape}")

    parent = np.arange(n_nodes, dtype=np.int64)
    size = np.ones(n_nodes, dtype=np.int64)

    n_edges = int(edges.shape[0])
    if active is None:
        active_view = None
    else:
        if active.shape != (n_edges,):
            raise ValueError(
                f"active must be (E,) matching edges; got {active.shape}"
            )
        active_view = active

    if node_mask is None:
        is_live = np.ones(n_nodes, dtype=bool)
    else:
        if node_mask.shape != (n_nodes,):
            raise ValueError(
                f"node_mask must be (n_nodes,); got {node_mask.shape}"
            )
        is_live = node_mask.astype(bool, copy=False)

    a_col = edges[:, 0].astype(np.int64, copy=False)
    b_col = edges[:, 1].astype(np.int64, copy=False)

    for k in range(n_edges):
        if active_view is not None and not active_view[k]:
            continue
        a = int(a_col[k])
        b = int(b_col[k])
        if a == b:
            continue
        if not is_live[a] or not is_live[b]:
            continue
        _uf_union(parent, size, a, b)

    # Compress roots into a dense [0, n_components) label range.
    labels = np.full(n_nodes, BACKGROUND_LABEL, dtype=np.int32)
    root_to_label: dict[int, int] = {}
    next_label = 0
    for i in range(n_nodes):
        if not is_live[i]:
            continue
        r = _uf_find(parent, i)
        lbl = root_to_label.get(r)
        if lbl is None:
            lbl = next_label
            root_to_label[r] = lbl
            next_label += 1
        labels[i] = lbl

    return labels, next_label


def connected_components_grid(
    density: np.ndarray,
    bond_e: np.ndarray,
    bond_s: np.ndarray,
    density_threshold: float = 0.1,
    bond_threshold: float = 0.05,
) -> tuple[np.ndarray, int]:
    """Legacy 2-D grid form (kept for backward compat with old physics).

    Builds an edge list from east/south bond arrays and delegates to
    :func:`connected_components`. Returns an ``(H, W)`` label map.
    """
    if density.shape != bond_e.shape or density.shape != bond_s.shape:
        raise ValueError(
            f"shape mismatch: density={density.shape} bond_e={bond_e.shape} "
            f"bond_s={bond_s.shape}"
        )
    if density.ndim != 2:
        raise ValueError(f"expected 2-D fields, got density.ndim={density.ndim}")

    h, w = density.shape
    n_nodes = h * w
    node_mask = (density > density_threshold).reshape(-1)

    # East edges: (i, j) -- (i, j+1). Index = i*w + j -> i*w + j + 1.
    east_i, east_j = np.meshgrid(
        np.arange(h, dtype=np.int64),
        np.arange(w - 1, dtype=np.int64),
        indexing="ij",
    )
    east_a = (east_i * w + east_j).reshape(-1)
    east_b = east_a + 1
    east_active = (bond_e[:, :-1] > bond_threshold).reshape(-1)

    # South edges: (i, j) -- (i+1, j). Index = i*w + j -> (i+1)*w + j.
    south_i, south_j = np.meshgrid(
        np.arange(h - 1, dtype=np.int64),
        np.arange(w, dtype=np.int64),
        indexing="ij",
    )
    south_a = (south_i * w + south_j).reshape(-1)
    south_b = south_a + w
    south_active = (bond_s[:-1, :] > bond_threshold).reshape(-1)

    edges = np.empty((east_a.size + south_a.size, 2), dtype=np.int64)
    edges[: east_a.size, 0] = east_a
    edges[: east_a.size, 1] = east_b
    edges[east_a.size :, 0] = south_a
    edges[east_a.size :, 1] = south_b

    active = np.concatenate([east_active, south_active])

    flat_labels, n_components = connected_components(
        n_nodes=n_nodes,
        edges=edges,
        active=active,
        node_mask=node_mask,
    )
    return flat_labels.reshape(h, w), n_components


__all__ = [
    "BACKGROUND_LABEL",
    "connected_components",
    "connected_components_grid",
]
