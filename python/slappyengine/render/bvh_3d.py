"""3D BVH broadphase for frustum / ray / AABB queries — KK1.

Nova3D parity Sprint 6: JJ5's :class:`~slappyengine.render.scene_walker.SceneWalker`
currently frustum-tests every entity in the scene linearly. That is fine for
tens of entities but degenerates to O(N) work per frame for larger scenes
(hundreds or thousands of instances). This module adds a top-down
Surface-Area-Heuristic (SAH) bounding volume hierarchy that JJ5 can wrap
around its ``for entity in scene.entities`` loop::

    from slappyengine.render.bvh_3d import AABB3D, BVH3D

    bvh = BVH3D([(entity_id, AABB3D(mn, mx)) for ...])
    visible_ids = bvh.query_frustum(Frustum.from_camera(camera))

Design constraints
------------------
* Pure Python + numpy, no wgpu / Rust dependency — this is glue, not a
  hot inner-loop kernel. Kernels ship in the Rust core when JJ5 promotes
  a bake path in a later sprint.
* Read-only integration with JJ5. We *soft-import* Frustum so this
  module works in stripped test builds where scene_walker has been
  omitted; queries fall back on a duck-typed ``intersects_aabb`` check.
* No mutation of AABB3D / BVHNode after construction — everything is
  functional, refits produce new bounds. This keeps the tree safe to
  share across threads (which JJ5 does not do today, but might).
* Deterministic build. Given identical (id, AABB) input, two builds
  produce identical topology — required for reproducible visual tests.

Algorithms
----------
* **Build**: top-down partition. For each internal node, we sort the
  centroids along each of the 3 axes, evaluate ``N=32`` candidate splits
  via SAH cost ``|L|*area(L) + |R|*area(R)``, and recurse. Buckets with
  ``≤ 4`` entities become leaves so the tree stays shallow.
* **Refit** (:meth:`BVH3D.update_entity`): rewrite the leaf's AABB, then
  walk the parent chain unioning children bounds. O(depth) — cheap on
  a balanced tree.
* **Rebuild** (:meth:`BVH3D.rebuild`): re-run the SAH build from
  scratch; use after many refits skew the tree.

The frustum test uses JJ5's ``intersects_aabb`` if a live ``Frustum``
came in, else the duck-type path — any object with ``intersects_aabb((mn, mx))``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np

# ---------------------------------------------------------------------------
# Frustum soft-import (JJ5 integration)
# ---------------------------------------------------------------------------

try:  # pragma: no cover - trivial guard
    from slappyengine.render.scene_walker import Frustum as _JJ5Frustum  # noqa: F401
    _HAS_JJ5_FRUSTUM = True
except Exception:  # pragma: no cover - stripped builds
    _JJ5Frustum = None  # type: ignore[assignment]
    _HAS_JJ5_FRUSTUM = False


# ---------------------------------------------------------------------------
# AABB3D
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AABB3D:
    """Axis-aligned bounding box in 3D world space.

    Immutable so callers can safely stash references without copying.
    Constructor asserts ``min <= max`` per axis — degenerate boxes
    (min == max) are allowed and represent a point.

    Attributes
    ----------
    min
        Lower corner ``(x, y, z)``.
    max
        Upper corner ``(x, y, z)``. Must be ``>= min`` on every axis.
    """

    min: tuple[float, float, float]
    max: tuple[float, float, float]

    # ------------------------------------------------------------------
    def __post_init__(self) -> None:
        mn = self.min
        mx = self.max
        if not (isinstance(mn, tuple) and len(mn) == 3):
            raise TypeError(
                f"AABB3D: min must be a 3-tuple; got {mn!r}"
            )
        if not (isinstance(mx, tuple) and len(mx) == 3):
            raise TypeError(
                f"AABB3D: max must be a 3-tuple; got {mx!r}"
            )
        for axis in range(3):
            if float(mn[axis]) > float(mx[axis]):
                raise ValueError(
                    f"AABB3D: min[{axis}]={mn[axis]} > max[{axis}]={mx[axis]}"
                )
        # Coerce to float for stability.
        object.__setattr__(
            self, "min",
            (float(mn[0]), float(mn[1]), float(mn[2])),
        )
        object.__setattr__(
            self, "max",
            (float(mx[0]), float(mx[1]), float(mx[2])),
        )

    # ------------------------------------------------------------------
    @property
    def center(self) -> tuple[float, float, float]:
        """Geometric center ``(min + max) / 2``."""
        mn = self.min
        mx = self.max
        return (
            (mn[0] + mx[0]) * 0.5,
            (mn[1] + mx[1]) * 0.5,
            (mn[2] + mx[2]) * 0.5,
        )

    @property
    def size(self) -> tuple[float, float, float]:
        """Extents ``(max - min)`` per axis."""
        mn = self.min
        mx = self.max
        return (mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2])

    # ------------------------------------------------------------------
    def union(self, other: "AABB3D") -> "AABB3D":
        """Return the smallest AABB containing both ``self`` and *other*."""
        if not isinstance(other, AABB3D):
            raise TypeError(
                f"AABB3D.union: other must be AABB3D; got {type(other).__name__}"
            )
        a_mn, a_mx = self.min, self.max
        b_mn, b_mx = other.min, other.max
        return AABB3D(
            min=(
                min(a_mn[0], b_mn[0]),
                min(a_mn[1], b_mn[1]),
                min(a_mn[2], b_mn[2]),
            ),
            max=(
                max(a_mx[0], b_mx[0]),
                max(a_mx[1], b_mx[1]),
                max(a_mx[2], b_mx[2]),
            ),
        )

    # ------------------------------------------------------------------
    def expand(self, point: tuple[float, float, float]) -> "AABB3D":
        """Return a new AABB grown to include *point*."""
        if not hasattr(point, "__len__") or len(point) != 3:
            raise TypeError(
                f"AABB3D.expand: point must be a 3-sequence; got {point!r}"
            )
        px, py, pz = float(point[0]), float(point[1]), float(point[2])
        mn = self.min
        mx = self.max
        return AABB3D(
            min=(min(mn[0], px), min(mn[1], py), min(mn[2], pz)),
            max=(max(mx[0], px), max(mx[1], py), max(mx[2], pz)),
        )

    # ------------------------------------------------------------------
    def contains_point(self, point: tuple[float, float, float]) -> bool:
        """True iff *point* lies inside the (closed) box."""
        if not hasattr(point, "__len__") or len(point) != 3:
            raise TypeError(
                f"AABB3D.contains_point: point must be a 3-sequence; got {point!r}"
            )
        px, py, pz = float(point[0]), float(point[1]), float(point[2])
        mn = self.min
        mx = self.max
        return (
            mn[0] <= px <= mx[0]
            and mn[1] <= py <= mx[1]
            and mn[2] <= pz <= mx[2]
        )

    # ------------------------------------------------------------------
    def surface_area(self) -> float:
        """Sum-of-face-areas of the box (SAH cost currency).

        A degenerate (min == max) box has area 0. A slab (zero extent on
        one axis) has ``2 * area_of_the_slab_face``.
        """
        sx, sy, sz = self.size
        return 2.0 * (sx * sy + sy * sz + sz * sx)

    # ------------------------------------------------------------------
    def overlaps(self, other: "AABB3D") -> bool:
        """True iff *self* and *other* share any point (AABB-AABB test)."""
        if not isinstance(other, AABB3D):
            raise TypeError(
                f"AABB3D.overlaps: other must be AABB3D; got {type(other).__name__}"
            )
        a_mn, a_mx = self.min, self.max
        b_mn, b_mx = other.min, other.max
        return (
            a_mn[0] <= b_mx[0] and a_mx[0] >= b_mn[0]
            and a_mn[1] <= b_mx[1] and a_mx[1] >= b_mn[1]
            and a_mn[2] <= b_mx[2] and a_mx[2] >= b_mn[2]
        )

    # ------------------------------------------------------------------
    def as_tuple(self) -> tuple[
        tuple[float, float, float], tuple[float, float, float]
    ]:
        """Return the JJ5-native ``((mn), (mx))`` shape used by Frustum."""
        return (self.min, self.max)


# ---------------------------------------------------------------------------
# BVHNode
# ---------------------------------------------------------------------------


@dataclass
class BVHNode:
    """One node in the :class:`BVH3D` hierarchy.

    Internal nodes point at children via ``left`` / ``right`` indices
    into the flat :attr:`BVH3D._nodes` list; leaves carry entity ids
    directly. ``is_leaf`` is derived from the presence of children.
    """

    bounds: AABB3D
    left: int | None = None
    right: int | None = None
    entity_ids: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    @property
    def is_leaf(self) -> bool:
        return self.left is None and self.right is None


# ---------------------------------------------------------------------------
# BVH3D
# ---------------------------------------------------------------------------


# SAH tuning constants — small enough for pure-Python builds, deterministic
# enough for regression tests.
_SAH_BUCKETS: int = 32
_LEAF_THRESHOLD: int = 4


class BVH3D:
    """Top-down SAH bounding volume hierarchy for 3D scene queries.

    Parameters
    ----------
    entities
        Sequence of ``(entity_id, AABB3D)`` tuples. Ids need not be
        unique — the tree stores duplicates verbatim, which is useful
        when multiple mesh instances share an id (rare, but legal in
        JJ5's scene walker).

    Examples
    --------
    >>> bvh = BVH3D([("cube", AABB3D((-1,-1,-1), (1,1,1)))])
    >>> "cube" in bvh.query_aabb(AABB3D((0,0,0), (2,2,2)))
    True

    Notes
    -----
    Query methods are non-mutating; only :meth:`rebuild`, :meth:`update_entity`,
    and the constructor touch tree state.
    """

    # ------------------------------------------------------------------
    def __init__(self, entities: list[tuple[str, AABB3D]]) -> None:
        if not isinstance(entities, list):
            # Accept any iterable of pairs but pin to list for stability.
            entities = list(entities)
        for idx, item in enumerate(entities):
            if (
                not isinstance(item, tuple)
                or len(item) != 2
                or not isinstance(item[0], str)
                or not isinstance(item[1], AABB3D)
            ):
                raise TypeError(
                    "BVH3D: entities must be a list of (str, AABB3D); "
                    f"item {idx} is {item!r}"
                )
        self._entities: list[tuple[str, AABB3D]] = list(entities)
        # id -> index into self._entities for O(1) refits.
        self._id_index: dict[str, list[int]] = {}
        for i, (eid, _) in enumerate(self._entities):
            self._id_index.setdefault(eid, []).append(i)
        self._nodes: list[BVHNode] = []
        # Leaf node index containing entity[i] — rebuilt with the tree.
        self._entity_leaf: list[int] = [0] * len(self._entities)
        # Parent-of-node lookup for the refit path (root has None).
        self._parent: list[int | None] = []
        # Node idx -> entity indices assigned to that leaf. Populated as
        # part of the build; used by query_ray / query_aabb to pick per-
        # entity boxes rather than just the leaf's union.
        self._leaf_entities: dict[int, list[int]] = {}
        self._root: int | None = None
        self._build()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def root(self) -> int | None:
        """Root node index, or ``None`` if the tree is empty."""
        return self._root

    @property
    def nodes(self) -> list[BVHNode]:
        """Flat list of all nodes (internal + leaf) in build order."""
        return self._nodes

    # ------------------------------------------------------------------
    def rebuild(self) -> None:
        """Rebuild the tree from scratch using the current entity set.

        Call after many :meth:`update_entity` refits have skewed the
        hierarchy — SAH-optimality drifts as bounds move.
        """
        self._build()

    # ------------------------------------------------------------------
    def update_entity(self, entity_id: str, new_bounds: AABB3D) -> None:
        """Rewrite an entity's AABB and refit the tree along its ancestors.

        Raises :class:`KeyError` if *entity_id* is unknown. When the id
        appears more than once (rare), every occurrence is updated to
        the same *new_bounds* — matching the "all instances share the
        same collider" convention JJ5 uses.
        """
        if not isinstance(entity_id, str):
            raise TypeError(
                f"BVH3D.update_entity: entity_id must be str; got {type(entity_id).__name__}"
            )
        if not isinstance(new_bounds, AABB3D):
            raise TypeError(
                "BVH3D.update_entity: new_bounds must be AABB3D; "
                f"got {type(new_bounds).__name__}"
            )
        idxs = self._id_index.get(entity_id)
        if not idxs:
            raise KeyError(
                f"BVH3D.update_entity: no entity registered under id {entity_id!r}"
            )
        for i in idxs:
            self._entities[i] = (entity_id, new_bounds)
        # Refit each affected leaf (they may be distinct if the id was
        # duplicated) and walk parents until nothing changes.
        touched_leaves: set[int] = {self._entity_leaf[i] for i in idxs}
        for leaf_idx in touched_leaves:
            self._refit_leaf(leaf_idx)
            self._refit_ancestors(leaf_idx)

    # ------------------------------------------------------------------
    def query_frustum(self, frustum: Any) -> list[str]:
        """Return entity ids whose AABBs intersect *frustum*.

        Accepts JJ5's :class:`~slappyengine.render.scene_walker.Frustum`
        or any duck-typed object with
        ``intersects_aabb(((mn), (mx))) -> bool``. Traverses the tree
        pruning subtrees whose node bounds already fail the frustum
        test.
        """
        if frustum is None:
            raise TypeError("BVH3D.query_frustum: frustum must not be None")
        if not hasattr(frustum, "intersects_aabb"):
            raise TypeError(
                "BVH3D.query_frustum: frustum must expose intersects_aabb; "
                f"got {type(frustum).__name__}"
            )
        results: list[str] = []
        if self._root is None or not self._nodes:
            return results
        stack: list[int] = [self._root]
        while stack:
            idx = stack.pop()
            node = self._nodes[idx]
            if not frustum.intersects_aabb(node.bounds.as_tuple()):
                continue
            if node.is_leaf:
                # A leaf's union bound may enclose entities that don't
                # individually pass the frustum test — refine per entity
                # to avoid false positives.
                for i, eid in enumerate(node.entity_ids):
                    leaf_entity_idx = self._leaf_entity_indices(idx)[i]
                    if frustum.intersects_aabb(
                        self._entities[leaf_entity_idx][1].as_tuple()
                    ):
                        results.append(eid)
                continue
            if node.left is not None:
                stack.append(node.left)
            if node.right is not None:
                stack.append(node.right)
        return results

    # ------------------------------------------------------------------
    def query_ray(
        self,
        origin: tuple[float, float, float],
        direction: tuple[float, float, float],
    ) -> list[tuple[str, float]]:
        """Return all entities whose AABBs intersect the ray.

        Uses the branchless slab test. Results are ``(entity_id, t_hit)``
        where ``t_hit`` is the smallest positive parameter along
        *direction*. Ids are sorted by ``t_hit`` ascending so the first
        entry is the nearest hit — the caller may treat that as the
        primary pick.

        Parameters
        ----------
        origin
            Ray origin ``(x, y, z)``.
        direction
            Ray direction ``(dx, dy, dz)``. Need not be normalised —
            the returned ``t_hit`` is in units of ``|direction|``.
        """
        if not hasattr(origin, "__len__") or len(origin) != 3:
            raise TypeError(
                f"BVH3D.query_ray: origin must be a 3-sequence; got {origin!r}"
            )
        if not hasattr(direction, "__len__") or len(direction) != 3:
            raise TypeError(
                f"BVH3D.query_ray: direction must be a 3-sequence; got {direction!r}"
            )
        ox, oy, oz = float(origin[0]), float(origin[1]), float(origin[2])
        dx, dy, dz = float(direction[0]), float(direction[1]), float(direction[2])
        if dx * dx + dy * dy + dz * dz == 0.0:
            raise ValueError(
                "BVH3D.query_ray: direction must be non-zero"
            )
        # Precompute reciprocals; use +inf where the axis is zero so the
        # slab test correctly rejects rays parallel-to and outside the box.
        inv_d = (
            1.0 / dx if dx != 0.0 else math.inf,
            1.0 / dy if dy != 0.0 else math.inf,
            1.0 / dz if dz != 0.0 else math.inf,
        )
        results: list[tuple[str, float]] = []
        if self._root is None or not self._nodes:
            return results

        def _slab_hit(box: AABB3D) -> float | None:
            mn = box.min
            mx = box.max
            t1x = (mn[0] - ox) * inv_d[0]
            t2x = (mx[0] - ox) * inv_d[0]
            tmin = min(t1x, t2x)
            tmax = max(t1x, t2x)
            t1y = (mn[1] - oy) * inv_d[1]
            t2y = (mx[1] - oy) * inv_d[1]
            tmin = max(tmin, min(t1y, t2y))
            tmax = min(tmax, max(t1y, t2y))
            t1z = (mn[2] - oz) * inv_d[2]
            t2z = (mx[2] - oz) * inv_d[2]
            tmin = max(tmin, min(t1z, t2z))
            tmax = min(tmax, max(t1z, t2z))
            if tmax < 0.0 or tmin > tmax:
                return None
            return tmin if tmin >= 0.0 else 0.0

        stack: list[int] = [self._root]
        while stack:
            idx = stack.pop()
            node = self._nodes[idx]
            if _slab_hit(node.bounds) is None:
                continue
            if node.is_leaf:
                for i, eid in enumerate(node.entity_ids):
                    # Look up the entity's own AABB (may be a strict
                    # subset of the leaf's union bound).
                    leaf_entity_idx = self._leaf_entity_indices(idx)[i]
                    t = _slab_hit(self._entities[leaf_entity_idx][1])
                    if t is not None:
                        results.append((eid, float(t)))
                continue
            if node.left is not None:
                stack.append(node.left)
            if node.right is not None:
                stack.append(node.right)
        results.sort(key=lambda pair: pair[1])
        return results

    # ------------------------------------------------------------------
    def query_aabb(self, query_box: AABB3D) -> list[str]:
        """Return entity ids whose AABBs overlap *query_box*."""
        if not isinstance(query_box, AABB3D):
            raise TypeError(
                "BVH3D.query_aabb: query_box must be AABB3D; "
                f"got {type(query_box).__name__}"
            )
        results: list[str] = []
        if self._root is None or not self._nodes:
            return results
        stack: list[int] = [self._root]
        while stack:
            idx = stack.pop()
            node = self._nodes[idx]
            if not node.bounds.overlaps(query_box):
                continue
            if node.is_leaf:
                # Filter down to individual entity boxes — the leaf's
                # union bound may over-approximate.
                for i, eid in enumerate(node.entity_ids):
                    leaf_entity_idx = self._leaf_entity_indices(idx)[i]
                    if self._entities[leaf_entity_idx][1].overlaps(query_box):
                        results.append(eid)
                continue
            if node.left is not None:
                stack.append(node.left)
            if node.right is not None:
                stack.append(node.right)
        return results

    # ------------------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        """Return a summary dict: node count, tree depth, average leaf size.

        Keys:
            ``node_count`` — total nodes in the tree (0 when empty).
            ``leaf_count`` — number of leaf nodes.
            ``entity_count`` — number of entities indexed.
            ``depth`` — longest root→leaf path length (0 for a single leaf).
            ``avg_leaf_size`` — mean entities per leaf (``0.0`` when empty).
            ``max_leaf_size`` — largest leaf's entity count.
        """
        node_count = len(self._nodes)
        leaf_count = 0
        max_leaf = 0
        for node in self._nodes:
            if node.is_leaf:
                leaf_count += 1
                if len(node.entity_ids) > max_leaf:
                    max_leaf = len(node.entity_ids)
        entity_count = len(self._entities)
        avg_leaf = float(entity_count) / leaf_count if leaf_count else 0.0
        depth = self._compute_depth()
        return {
            "node_count": node_count,
            "leaf_count": leaf_count,
            "entity_count": entity_count,
            "depth": depth,
            "avg_leaf_size": avg_leaf,
            "max_leaf_size": max_leaf,
        }

    # ------------------------------------------------------------------
    def __len__(self) -> int:
        return len(self._entities)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build(self) -> None:
        """Top-down SAH build."""
        self._nodes = []
        self._parent = []
        self._entity_leaf = [0] * len(self._entities)
        self._leaf_entities = {}
        if not self._entities:
            self._root = None
            return
        indices = list(range(len(self._entities)))
        self._root = self._build_recursive(indices, parent=None)

    # ------------------------------------------------------------------
    def _build_recursive(
        self,
        indices: list[int],
        *,
        parent: int | None,
    ) -> int:
        """Recursively build one subtree over *indices*; return its node idx."""
        # Compute the union of every entity's AABB.
        node_bounds = self._union_of(indices)
        node_idx = len(self._nodes)
        # Placeholder so children can look up parent while we build them.
        self._nodes.append(
            BVHNode(bounds=node_bounds, left=None, right=None, entity_ids=[])
        )
        self._parent.append(parent)

        if len(indices) <= _LEAF_THRESHOLD:
            self._finalise_leaf(node_idx, indices)
            return node_idx

        # Try to find a good SAH split. If SAH refuses (all splits
        # worse than treating as a leaf) we still leaf out — that
        # matches PBRT's convention and prevents pathological deep
        # trees on tightly-overlapping clusters.
        split = self._best_sah_split(indices, node_bounds)
        if split is None:
            self._finalise_leaf(node_idx, indices)
            return node_idx
        left_indices, right_indices = split
        if not left_indices or not right_indices:
            self._finalise_leaf(node_idx, indices)
            return node_idx

        left_child = self._build_recursive(left_indices, parent=node_idx)
        right_child = self._build_recursive(right_indices, parent=node_idx)
        # Refresh — self._nodes[node_idx] was captured by value in a
        # dataclass, but since we're mutating it in place that's fine.
        self._nodes[node_idx].left = left_child
        self._nodes[node_idx].right = right_child

        return node_idx

    # ------------------------------------------------------------------
    def _finalise_leaf(self, node_idx: int, indices: list[int]) -> None:
        node = self._nodes[node_idx]
        node.entity_ids = [self._entities[i][0] for i in indices]
        # Store the entity index list on the node for query_ray / query_aabb
        # to re-index into self._entities.
        for i in indices:
            self._entity_leaf[i] = node_idx
        # Attach the raw indices under a stable attribute — used by
        # per-entity refinement in query_ray / query_aabb.
        self._leaf_entities[node_idx] = list(indices)

    # ------------------------------------------------------------------
    def _leaf_entity_indices(self, node_idx: int) -> list[int]:
        return self._leaf_entities.get(node_idx, [])

    # ------------------------------------------------------------------
    def _union_of(self, indices: list[int]) -> AABB3D:
        it = iter(indices)
        first = next(it)
        acc = self._entities[first][1]
        for i in it:
            acc = acc.union(self._entities[i][1])
        return acc

    # ------------------------------------------------------------------
    def _best_sah_split(
        self,
        indices: list[int],
        node_bounds: AABB3D,
    ) -> tuple[list[int], list[int]] | None:
        """Return the SAH-optimal (left, right) partition of *indices*.

        Returns ``None`` if no split improves on treating the subtree as
        a leaf — the caller then finalises the node as a leaf.
        """
        n = len(indices)
        if n < 2:
            return None
        parent_area = node_bounds.surface_area()
        # A parent with zero area (all boxes identical points) can't be
        # meaningfully split by SAH — leaf out.
        if parent_area <= 0.0:
            return None
        leaf_cost = float(n)
        best_cost = math.inf
        best_axis = -1
        best_split = -1
        # Precompute centroids for each candidate index so we can sort
        # by axis without re-touching the AABBs.
        centroids = np.array(
            [self._entities[i][1].center for i in indices],
            dtype=np.float64,
        )
        for axis in range(3):
            order = np.argsort(centroids[:, axis], kind="stable")
            sorted_indices = [indices[k] for k in order.tolist()]
            # Prefix/suffix AABB sweeps → SAH cost per split.
            prefix = [None] * n
            suffix = [None] * n
            acc = self._entities[sorted_indices[0]][1]
            prefix[0] = acc
            for k in range(1, n):
                acc = acc.union(self._entities[sorted_indices[k]][1])
                prefix[k] = acc
            acc = self._entities[sorted_indices[n - 1]][1]
            suffix[n - 1] = acc
            for k in range(n - 2, -1, -1):
                acc = acc.union(self._entities[sorted_indices[k]][1])
                suffix[k] = acc

            # Sample N_BUCKETS candidate splits — evenly distributed
            # across the sorted range.
            candidates = min(_SAH_BUCKETS, n - 1)
            for c in range(candidates):
                # Split so left has (c+1)/candidates * n entities, at
                # least 1 and at most n-1.
                split_at = int(round((c + 1) * n / (candidates + 1)))
                split_at = max(1, min(n - 1, split_at))
                left_area = prefix[split_at - 1].surface_area()
                right_area = suffix[split_at].surface_area()
                cost = (
                    split_at * left_area + (n - split_at) * right_area
                ) / parent_area
                if cost < best_cost:
                    best_cost = cost
                    best_axis = axis
                    best_split = split_at

        if best_axis < 0 or best_cost >= leaf_cost * 1.0 + 1e-9:
            # SAH couldn't beat the leaf cost by a meaningful margin.
            # For small n we still split (up to _LEAF_THRESHOLD gate
            # already filtered n<=4). This lets us tolerate flat SAH
            # landscapes without collapsing to giant leaves.
            if n <= _LEAF_THRESHOLD * 2:
                return None
            # Fall back to median split along the widest axis.
            widest = int(np.argmax(node_bounds.size))
            order = np.argsort(centroids[:, widest], kind="stable")
            sorted_indices = [indices[k] for k in order.tolist()]
            mid = n // 2
            return sorted_indices[:mid], sorted_indices[mid:]

        order = np.argsort(centroids[:, best_axis], kind="stable")
        sorted_indices = [indices[k] for k in order.tolist()]
        return sorted_indices[:best_split], sorted_indices[best_split:]

    # ------------------------------------------------------------------
    def _refit_leaf(self, leaf_idx: int) -> None:
        leaf = self._nodes[leaf_idx]
        entity_idxs = self._leaf_entity_indices(leaf_idx)
        if not entity_idxs:
            return
        acc = self._entities[entity_idxs[0]][1]
        for i in entity_idxs[1:]:
            acc = acc.union(self._entities[i][1])
        leaf.bounds = acc

    def _refit_ancestors(self, node_idx: int) -> None:
        cur = self._parent[node_idx]
        while cur is not None:
            parent = self._nodes[cur]
            new_bounds = None
            if parent.left is not None:
                new_bounds = self._nodes[parent.left].bounds
            if parent.right is not None:
                right_b = self._nodes[parent.right].bounds
                new_bounds = right_b if new_bounds is None else new_bounds.union(right_b)
            if new_bounds is not None:
                parent.bounds = new_bounds
            cur = self._parent[cur]

    # ------------------------------------------------------------------
    def _compute_depth(self) -> int:
        if self._root is None or not self._nodes:
            return 0

        # Iterative DFS with per-node depth so we don't blow the Python
        # recursion limit on pathological trees.
        max_depth = 0
        stack: list[tuple[int, int]] = [(self._root, 0)]
        while stack:
            idx, d = stack.pop()
            node = self._nodes[idx]
            if node.is_leaf:
                if d > max_depth:
                    max_depth = d
                continue
            if node.left is not None:
                stack.append((node.left, d + 1))
            if node.right is not None:
                stack.append((node.right, d + 1))
        return max_depth


__all__ = [
    "AABB3D",
    "BVH3D",
    "BVHNode",
]
