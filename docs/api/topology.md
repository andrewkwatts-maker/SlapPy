# slappyengine.topology — API Reference

> Hand-authored reference for the `slappyengine.topology` subpackage.
> The auto-generated stub at `scripts/gen_subpackage_api_docs.py` only
> captures signatures + docstrings; this page adds usage, complexity, and
> integration notes that don't fit in the source docstrings.

## Overview

`slappyengine.topology` exposes weighted union-find connected-component
labelling for graphs defined by an edge list plus an optional per-edge
activity mask and per-node liveness mask. It was lifted out of the legacy
`slappyengine.physics.cc_label` module during the Phase B repackage so any
subsystem — softbody beam graphs, brittle-fracture cell grids, particle
field region maps, future destructible-mesh tools — can share one tested
union-find core instead of re-rolling its own. The algorithm is
amortised near-linear (O((N + E)·α(N))) and is intended for fragment
detection on detachable physics bodies where edges flip from "live" to
"broken" between frames and downstream code needs to know "is this body
still one piece, or did it just split into two?" without rebuilding any
adjacency structure.

## Public surface

The full export list is:

```python
from slappyengine.topology import (
    BACKGROUND_LABEL,         # int sentinel = -1
    connected_components,     # generic edge-list form
    connected_components_grid # legacy 2-D bond-field form
)
```

Internal validation helpers live in `slappyengine.topology._validation`
and are intentionally not re-exported.

---

### `connected_components(n_nodes, edges, active=None, node_mask=None) -> (labels, n_components)`

Label the connected components of a graph given as an edge list.

#### Signature

```python
def connected_components(
    n_nodes: int,
    edges: np.ndarray,                # shape (E, 2), integral dtype
    active: np.ndarray | None = None, # shape (E,),  bool
    node_mask: np.ndarray | None = None, # shape (n_nodes,), bool
) -> tuple[np.ndarray, int]
```

#### Parameters

- **`n_nodes`** — Total number of nodes in the graph. Labels are emitted
  in `[0, n_components)` for live nodes and `BACKGROUND_LABEL` for any
  node that was masked out.
- **`edges`** — `(E, 2)` integer numpy array of `(a, b)` endpoint pairs.
  Self-loops (`a == b`) and duplicate edges are both tolerated and have
  no effect on the partition. Edges may appear in any order.
- **`active`** — Optional `(E,)` bool array. When provided, an edge is
  only union'd when its corresponding entry is `True`. This is the
  intended fast path for "break a beam without rebuilding the edge
  list": flip the bool and re-label.
- **`node_mask`** — Optional `(n_nodes,)` bool array. Nodes whose entry
  is `False` are not clustered at all and receive `BACKGROUND_LABEL`. An
  edge touching at least one masked endpoint is silently skipped.

#### Returns

- **`labels`** — `(n_nodes,)` `int32` array. Each live node carries a
  unique cluster id in `[0, n_components)`. Masked nodes carry
  `BACKGROUND_LABEL = -1`. The label numbering is dense (no gaps) and
  deterministic for a given input ordering, but the specific integer
  assigned to a given cluster is an implementation detail — downstream
  code should treat equal labels as "same cluster" and not depend on
  numeric stability across releases.
- **`n_components`** — Number of distinct clusters across the live
  nodes. Masked nodes do not contribute.

#### Raises

- **`TypeError`** — `n_nodes` is not an int; `edges` is not a numpy
  ndarray, or has non-integral dtype; `active` or `node_mask` is not a
  bool ndarray.
- **`ValueError`** — `n_nodes` is negative; `edges` is not 2-D with
  second dimension 2; any edge endpoint is outside `[0, n_nodes)`;
  `active` length differs from `E`; `node_mask` length differs from
  `n_nodes`.

#### Complexity

Amortised O((N + E)·α(N)) where N = `n_nodes`, E = `edges.shape[0]`, and
α is the inverse Ackermann function. For all practical N this is
near-linear. Union-find uses weighted-by-size unions and path
compression, both classical. Memory is two `int64` arrays of length N
plus a small dict mapping roots to compressed labels during the final
relabel sweep.

#### Usage

```python
import numpy as np
from slappyengine.topology import connected_components

# Four nodes, two disjoint pairs: {0,1} and {2,3}
edges  = np.array([[0, 1], [2, 3]], dtype=np.int64)
labels, n = connected_components(4, edges)
assert n == 2
assert labels[0] == labels[1] and labels[2] == labels[3]
assert labels[0] != labels[2]
```

Breaking an edge between frames is a single bool flip:

```python
active = np.ones(len(edges), dtype=bool)
active[0] = False                            # snap edge {0,1}
labels, n = connected_components(4, edges, active=active)
assert n == 3                                # {0}, {1}, {2,3}
```

---

### `connected_components_grid(density, bond_e, bond_s, density_threshold=0.1, bond_threshold=0.05) -> (labels, n_components)`

Legacy 2-D form retained for the Phase D physics shim. Builds an edge
list from the east/south bond fields and delegates to
`connected_components`.

#### Signature

```python
def connected_components_grid(
    density: np.ndarray,       # shape (H, W), float
    bond_e: np.ndarray,        # shape (H, W), float — east bond strengths
    bond_s: np.ndarray,        # shape (H, W), float — south bond strengths
    density_threshold: float = 0.1,
    bond_threshold: float = 0.05,
) -> tuple[np.ndarray, int]
```

#### Parameters

- **`density`** — `(H, W)` float array. Cells with `density > density_threshold` are treated as live nodes; everything else is background.
- **`bond_e`** — `(H, W)` float array of east-neighbour bond strengths. Entry `[i, j]` is the bond between cell `(i, j)` and `(i, j+1)`. The rightmost column is ignored.
- **`bond_s`** — `(H, W)` float array of south-neighbour bond strengths. Entry `[i, j]` is the bond between cell `(i, j)` and `(i+1, j)`. The bottom row is ignored.
- **`density_threshold`** — Cells whose density falls at or below this value are masked out and receive `BACKGROUND_LABEL`.
- **`bond_threshold`** — Edges whose bond strength falls at or below this value are inactive (treated as broken).

#### Returns

- **`labels`** — `(H, W)` `int32` label map.
- **`n_components`** — Number of distinct clusters among the live cells.

#### Raises

- **`ValueError`** — `density`, `bond_e`, and `bond_s` do not all share
  the same shape, or any of them is not 2-D.

#### Complexity

Identical to `connected_components`: O((H·W + 2·H·W)·α(H·W)).
The east/south edge tables are constructed with vectorised
`np.meshgrid` calls — there is no per-cell Python loop in the wrapper.

#### Usage

```python
import numpy as np
from slappyengine.topology import connected_components_grid

density = np.full((1, 4), 0.5, dtype=np.float32)
bond_e  = np.full((1, 4), 0.5, dtype=np.float32)
bond_s  = np.zeros((1, 4), dtype=np.float32)
bond_e[0, 1] = 0.0                  # sever the middle east bond
labels, n = connected_components_grid(density, bond_e, bond_s)
assert n == 2
assert labels[0, 0] == labels[0, 1]
assert labels[0, 2] == labels[0, 3]
```

---

### `BACKGROUND_LABEL`

`int` sentinel set to `-1`. Returned in the `labels` array wherever a
node was excluded via `node_mask` (edge-list form) or sub-threshold
density (grid form). Downstream code should compare against this
constant rather than hard-coding `-1`, both for readability and to
remain robust if the sentinel is ever widened.

---

## Real-world use cases

### Layered-creature limb fragmentation

The softbody humanoid / creature builders construct a beam graph
between flesh nodes. When `world.step()` flags one or more beams as
broken (strain exceeds `flesh_break_strain`), the world toggles the
matching entries in the per-edge `active` array. A single call to
`connected_components` with that array tells the gameplay layer
"the left arm is now a separate body" without any rebuild — the
returned label map can be sliced against bone indices to decide which
fragment carries which body id.

### Brittle fracture component labelling

`slappyengine.physics.hull.HullSystem.split_fragments` is the canonical
example: when a hull cracks, the cell density and east/south bond fields
are passed straight into `connected_components_grid`. The largest
cluster keeps the parent hull id; smaller clusters spawn new root hulls
seeded with each cell's velocity. The cell grid never reallocates — the
density-zero cells already act as their own mask via
`density_threshold`.

### Region grid in `slappyengine.physics.particle_field`

The Phase B particle-field code uses `connected_components` to bucket
particles into spatial regions for collision broad-phase and material
queries. The mapping from cell index to region id is recomputed each
time the field's adjacency changes (e.g. when a fluid pocket merges
with a neighbour). The full integration is internal to the particle
field implementation and not covered here; see
`python/slappyengine/physics/particle_field.py` for the call site.

---

## Notes on guarantees

- Labels are dense in `[0, n_components)` for live nodes — there are no
  gaps. This makes `np.bincount(labels[labels != BACKGROUND_LABEL])`
  always a valid cluster-size histogram.
- The two label arrays returned by two calls with the same inputs
  compare equal element-wise (the algorithm is deterministic), but
  callers that compare across releases should compare *partitions*, not
  raw label ids. The helper `_partition_from_labels` in
  `python/tests/test_topology_components.py` shows the canonical
  permutation-invariant comparison.
- `RuntimeWarning` is never raised by this module on valid input; the
  test suite runs with `simplefilter("error", RuntimeWarning)`.
