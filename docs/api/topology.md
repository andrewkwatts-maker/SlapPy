<!-- handauthored: do not regenerate -->
# pharos_engine.topology — API Reference

> Hand-written reference for the SS7 pass on the Pharos Engine graph
> topology primitives. Owns connected-components / union-find on generic
> edge-list graphs plus a legacy 2-D grid convenience form kept for the
> old bond-solver call sites. Sibling references:
> [`numerics.md`](numerics.md) is the paired numerical-kernel subpackage
> (Poisson multigrid, Red-Black SOR); [`../dynamics_design.md`](../dynamics_design.md)
> is the softbody / rigid-body layer that consumes `connected_components`
> when beams break and the lattice fragments into free-flying islands.

## Overview

`pharos_engine.topology` is one of the small "generic numerical
primitive" subpackages that Phase B extracted out of the old physics
tree so both softbody fragmentation and the legacy 2-D cell-bond grid
share one union-find implementation.

The public surface is intentionally tiny — two entry points and one
constant. The primary form
:func:`connected_components` labels connected components on any
edge-list graph and returns a dense label array together with the
component count. The convenience form
:func:`connected_components_grid` builds the edge list from east / south
bond arrays and returns a 2-D label map — kept for backward compat with
legacy grid code; new call sites should build their own edge list and go
straight through :func:`connected_components`.

Algorithm: weighted union-find with path compression, O((N + E)·α(N)).
Sparse-graph friendly, faster than BFS on the softbody fragmentation
workload (a few thousand beams over a lattice of a few hundred nodes).
Nodes masked out via `node_mask=False` receive the
:data:`BACKGROUND_LABEL` sentinel (`-1`); edges masked out via
`active=False` are ignored without rebuilding the edge list — the
softbody uses this to skip broken beams cheaply.

## Public surface

```python
from pharos_engine.topology import (
    BACKGROUND_LABEL,
    connected_components,
    connected_components_grid,
)
```

## Functions

### `connected_components(n_nodes, edges, active=None, node_mask=None) -> tuple[labels, n_components]`

_defined in `pharos_engine.topology`_

Label connected components on an edge-list graph. Returns a
`(n_nodes,)` `int32` array whose entries are dense labels in
`[0, n_components)` for live nodes and :data:`BACKGROUND_LABEL` for
masked-out nodes, together with `n_components: int`.

| Argument | Type | Notes |
|----------|------|-------|
| `n_nodes` | `int` | Total node count. Labels span `[0, n_components)`. |
| `edges` | `np.ndarray` shape `(E, 2)`, integral dtype | Endpoint pairs. Self-loops and duplicates are tolerated. |
| `active` | `np.ndarray` shape `(E,)`, `bool`, optional | `False` edges are ignored — use this to skip broken beams. |
| `node_mask` | `np.ndarray` shape `(n_nodes,)`, `bool`, optional | `False` nodes are not clustered (label = `BACKGROUND_LABEL`). |

**Raises:**

- `TypeError` — `n_nodes` is not an int, `edges` is not a numpy ndarray
  of integral dtype, or `active` / `node_mask` are not bool ndarrays.
- `ValueError` — `n_nodes` is negative, `edges` is not `(E, 2)`, any
  edge endpoint falls outside `[0, n_nodes)`, or `active` / `node_mask`
  have the wrong length.

### `connected_components_grid(density, bond_e, bond_s, density_threshold=0.1, bond_threshold=0.05) -> tuple[labels_2d, n_components]`

_defined in `pharos_engine.topology`_

Legacy 2-D grid convenience form. Builds an edge list from the east
(`bond_e`) and south (`bond_s`) bond-strength arrays, uses
`density > density_threshold` as `node_mask`, `bond > bond_threshold` as
`active`, and delegates to :func:`connected_components`. Returns an
`(H, W)` label map instead of the flat `(H·W,)` array.

Kept for backward compat with the pre-Phase-B cell-bond solver — new
code should prefer :func:`connected_components` directly.

## Constants

### `BACKGROUND_LABEL`

_int — defined in `pharos_engine.topology`_

Value: `-1`. Sentinel label written into
:func:`connected_components` output for any node whose `node_mask`
entry was `False` (or any grid cell whose density fell below the
threshold in the 2-D convenience form). Distinct from any valid
component label so callers can filter background cells with a single
`labels == BACKGROUND_LABEL` comparison.

## Usage

```python
import numpy as np
from pharos_engine.topology import (
    BACKGROUND_LABEL, connected_components,
)

# Four nodes; two disjoint components 0-1 and 2-3.
edges = np.array([[0, 1], [2, 3]], dtype=np.int64)
labels, n = connected_components(n_nodes=4, edges=edges)
assert n == 2
assert labels[0] == labels[1]
assert labels[2] == labels[3]
assert labels[0] != labels[2]

# Mask out node 2 — its label becomes BACKGROUND_LABEL and the second
# component collapses to a singleton on node 3.
node_mask = np.array([True, True, False, True])
labels, n = connected_components(
    n_nodes=4, edges=edges, node_mask=node_mask,
)
assert labels[2] == BACKGROUND_LABEL
assert n == 2  # {0, 1} and {3}

# Skip a broken edge without rebuilding the edge list.
active = np.array([True, False])  # edge 0-1 live, edge 2-3 broken
labels, n = connected_components(n_nodes=4, edges=edges, active=active)
assert n == 3  # {0, 1}, {2}, {3}
```

## Skip the wrapper

`pharos_engine.topology` is Python-only. Grep of
`pharos_engine._core_facade.RUST_MODULE_MAP` shows **no** `topology`
entry — the inner `_uf_find` / `_uf_union` primitives are scalar
integer ops on a small `parent` / `size` `int64` array, and the outer
loop runs at most `E + N` iterations. For the softbody fragmentation
workload (E ≲ 5000, N ≲ 500) the whole call finishes in tens of
microseconds; rewriting in Rust would move no measurable frame-time
needle.

If a future sprint adds heavier graph algorithms (incremental
connectivity, biconnected components, shortest paths on larger
graphs), promote them to their own module and revisit the
Rust-migration question against
[`../rust_migration_plan.md`](../rust_migration_plan.md) at that point.

## Design notes

The subpackage surface is intentionally small (two entry points plus
one sentinel constant); no separate `topology_design.md` ships. The
union-find weighting, the path-compression `_uf_find`, and the dense
label compression step (root → dense id via `root_to_label` dict) are
documented inline in the source above.

If a future sprint adds incremental connectivity, persistent labelling,
or non-trivial graph algorithms, promote that material to a dedicated
`topology_design.md` and link both ways.

## See also

- [`numerics.md`](numerics.md) — numerical primitives (multigrid
  Poisson, Red-Black SOR) consumed by the same physics stack.
- [`../numerics_design.md`](../numerics_design.md) — sibling
  subpackage's design reference for the multigrid V-cycle.
- [`../dynamics_design.md`](../dynamics_design.md) — softbody /
  rigid-body layer whose beam-break path is the primary
  :func:`connected_components` caller.
- [`../rust_migration_plan.md`](../rust_migration_plan.md) —
  Rust-migration ROI reference; topology is currently below the
  measurable-win threshold.
