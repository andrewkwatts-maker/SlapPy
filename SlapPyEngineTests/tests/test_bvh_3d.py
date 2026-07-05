"""Tests for slappyengine.render.bvh_3d — KK1 Nova3D parity Sprint 6.

Coverage:
* AABB3D union / expand / contains_point / surface_area / overlaps.
* BVH build with N entities → balanced-ish tree (depth ≤ log2(N) + 2).
* Empty BVH is safe.
* query_frustum returns all inside entities, culls outside ones.
* query_ray hits centered cube first from (0,0,-5) direction (0,0,1).
* query_aabb finds overlaps and skips misses.
* update_entity refits leaf → ancestors so queries see the new bounds.
* stats() returns sensible node_count / leaf_count / depth / avg_leaf_size.
* Integration with JJ5's Frustum via Camera3D.
"""
from __future__ import annotations

import math
import random

import numpy as np
import pytest

from slappyengine.render.bvh_3d import AABB3D, BVH3D, BVHNode
from slappyengine.render.camera import Camera3D
from slappyengine.render.scene_walker import Frustum


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _grid_entities(n_side: int = 4, spacing: float = 2.0) -> list[tuple[str, AABB3D]]:
    """Regular n^3 grid of unit cubes centred on the origin."""
    out: list[tuple[str, AABB3D]] = []
    half = (n_side - 1) * spacing * 0.5
    for i in range(n_side):
        for j in range(n_side):
            for k in range(n_side):
                cx = i * spacing - half
                cy = j * spacing - half
                cz = k * spacing - half
                out.append(
                    (
                        f"cube_{i}_{j}_{k}",
                        AABB3D(
                            min=(cx - 0.5, cy - 0.5, cz - 0.5),
                            max=(cx + 0.5, cy + 0.5, cz + 0.5),
                        ),
                    )
                )
    return out


def _random_entities(n: int, seed: int = 0, extent: float = 10.0) -> list[tuple[str, AABB3D]]:
    rng = random.Random(seed)
    out: list[tuple[str, AABB3D]] = []
    for i in range(n):
        cx = rng.uniform(-extent, extent)
        cy = rng.uniform(-extent, extent)
        cz = rng.uniform(-extent, extent)
        r = rng.uniform(0.1, 0.5)
        out.append(
            (
                f"e{i}",
                AABB3D(min=(cx - r, cy - r, cz - r), max=(cx + r, cy + r, cz + r)),
            )
        )
    return out


class _AlwaysHitFrustum:
    """Duck-typed frustum stand-in that lets everything through."""

    def intersects_aabb(self, aabb):
        return True


class _XSliceFrustum:
    """Duck-typed frustum: keeps AABBs whose x-range overlaps [-1, 1]."""

    def intersects_aabb(self, aabb):
        (mnx, _, _), (mxx, _, _) = aabb
        return mxx >= -1.0 and mnx <= 1.0


# ---------------------------------------------------------------------------
# AABB3D
# ---------------------------------------------------------------------------


def test_aabb3d_construction_and_properties():
    a = AABB3D(min=(0.0, 0.0, 0.0), max=(2.0, 4.0, 6.0))
    assert a.center == (1.0, 2.0, 3.0)
    assert a.size == (2.0, 4.0, 6.0)
    # Surface area = 2 * (2*4 + 4*6 + 6*2) = 2 * (8 + 24 + 12) = 88.
    assert a.surface_area() == pytest.approx(88.0)


def test_aabb3d_rejects_inverted_bounds():
    with pytest.raises(ValueError):
        AABB3D(min=(1.0, 0.0, 0.0), max=(0.0, 1.0, 1.0))


def test_aabb3d_rejects_wrong_arity():
    with pytest.raises(TypeError):
        AABB3D(min=(0.0, 0.0), max=(1.0, 1.0, 1.0))  # type: ignore[arg-type]


def test_aabb3d_union_preserves_both_boxes():
    a = AABB3D(min=(0.0, 0.0, 0.0), max=(1.0, 1.0, 1.0))
    b = AABB3D(min=(-1.0, 0.5, 2.0), max=(0.5, 3.0, 3.0))
    u = a.union(b)
    # Every corner of both boxes must be inside the union.
    for box in (a, b):
        for cx in (box.min[0], box.max[0]):
            for cy in (box.min[1], box.max[1]):
                for cz in (box.min[2], box.max[2]):
                    assert u.contains_point((cx, cy, cz))
    # The union must be minimal — its min/max exactly matches the extremes.
    assert u.min == (-1.0, 0.0, 0.0)
    assert u.max == (1.0, 3.0, 3.0)


def test_aabb3d_expand_grows_to_include_point():
    a = AABB3D(min=(0.0, 0.0, 0.0), max=(1.0, 1.0, 1.0))
    b = a.expand((-2.0, 5.0, 0.5))
    assert b.min == (-2.0, 0.0, 0.0)
    assert b.max == (1.0, 5.0, 1.0)
    # Original untouched (frozen dataclass).
    assert a.min == (0.0, 0.0, 0.0)


def test_aabb3d_contains_point_edges_are_inclusive():
    a = AABB3D(min=(0.0, 0.0, 0.0), max=(1.0, 1.0, 1.0))
    assert a.contains_point((0.0, 0.0, 0.0)) is True
    assert a.contains_point((1.0, 1.0, 1.0)) is True
    assert a.contains_point((0.5, 0.5, 0.5)) is True
    assert a.contains_point((1.5, 0.5, 0.5)) is False
    assert a.contains_point((-0.01, 0.5, 0.5)) is False


def test_aabb3d_surface_area_of_degenerate_point_is_zero():
    a = AABB3D(min=(3.0, 3.0, 3.0), max=(3.0, 3.0, 3.0))
    assert a.surface_area() == 0.0


def test_aabb3d_overlaps_shared_face():
    a = AABB3D(min=(0.0, 0.0, 0.0), max=(1.0, 1.0, 1.0))
    b = AABB3D(min=(1.0, 0.0, 0.0), max=(2.0, 1.0, 1.0))
    c = AABB3D(min=(2.0, 0.0, 0.0), max=(3.0, 1.0, 1.0))
    assert a.overlaps(b) is True   # touching faces at x=1
    assert a.overlaps(c) is False  # x-ranges are disjoint


# ---------------------------------------------------------------------------
# BVHNode
# ---------------------------------------------------------------------------


def test_bvhnode_is_leaf_property():
    leaf = BVHNode(
        bounds=AABB3D((0, 0, 0), (1, 1, 1)),
        entity_ids=["a", "b"],
    )
    inner = BVHNode(
        bounds=AABB3D((0, 0, 0), (1, 1, 1)),
        left=1,
        right=2,
    )
    assert leaf.is_leaf is True
    assert inner.is_leaf is False


# ---------------------------------------------------------------------------
# BVH3D build + stats
# ---------------------------------------------------------------------------


def test_bvh_empty_does_not_crash():
    bvh = BVH3D([])
    assert bvh.root is None
    assert bvh.nodes == []
    stats = bvh.stats()
    assert stats["node_count"] == 0
    assert stats["entity_count"] == 0
    assert stats["depth"] == 0
    assert stats["avg_leaf_size"] == 0.0
    # Queries on an empty tree return empty results, never crash.
    assert bvh.query_frustum(_AlwaysHitFrustum()) == []
    assert bvh.query_aabb(AABB3D((0, 0, 0), (1, 1, 1))) == []
    assert bvh.query_ray((0, 0, 0), (1, 0, 0)) == []


def test_bvh_single_entity_is_single_leaf():
    e = ("only", AABB3D(min=(-1, -1, -1), max=(1, 1, 1)))
    bvh = BVH3D([e])
    assert bvh.root == 0
    assert len(bvh.nodes) == 1
    node = bvh.nodes[0]
    assert node.is_leaf is True
    assert node.entity_ids == ["only"]
    stats = bvh.stats()
    assert stats["node_count"] == 1
    assert stats["leaf_count"] == 1
    assert stats["depth"] == 0
    assert stats["avg_leaf_size"] == 1.0


def test_bvh_rejects_bad_entity_shape():
    with pytest.raises(TypeError):
        BVH3D([("a", "not an aabb")])  # type: ignore[list-item]
    with pytest.raises(TypeError):
        BVH3D([("a",)])  # type: ignore[list-item]


def test_bvh_build_produces_balanced_tree_grid():
    ents = _grid_entities(n_side=4)  # 64 boxes on a regular grid
    bvh = BVH3D(ents)
    stats = bvh.stats()
    n = stats["entity_count"]
    assert n == 64
    # For 64 entities the tree should not exceed log2(64) + 2 = 8 levels.
    assert stats["depth"] <= int(math.log2(n)) + 2
    # Every entity must land in a leaf.
    total_in_leaves = sum(len(node.entity_ids) for node in bvh.nodes if node.is_leaf)
    assert total_in_leaves == n
    # Average leaf size is bounded by the leaf threshold (4).
    assert stats["avg_leaf_size"] <= 4.0
    assert stats["max_leaf_size"] <= 4


def test_bvh_build_random_depth_bound():
    ents = _random_entities(200, seed=1)
    bvh = BVH3D(ents)
    stats = bvh.stats()
    # Depth bound accommodates SAH slack — log2(N) + 2.
    assert stats["depth"] <= int(math.log2(len(ents))) + 2
    # Node count in a proper binary tree: leaves + internals ~= 2L - 1 <= 2N.
    assert stats["node_count"] <= 2 * len(ents)


def test_bvh_rebuild_is_idempotent():
    ents = _grid_entities(3)
    bvh = BVH3D(ents)
    stats_before = bvh.stats()
    bvh.rebuild()
    stats_after = bvh.stats()
    assert stats_before == stats_after


# ---------------------------------------------------------------------------
# query_frustum
# ---------------------------------------------------------------------------


def test_query_frustum_returns_all_when_frustum_covers_scene():
    ents = _grid_entities(3)
    bvh = BVH3D(ents)
    hits = set(bvh.query_frustum(_AlwaysHitFrustum()))
    expected = {eid for eid, _ in ents}
    assert hits == expected


def test_query_frustum_culls_outside_entities():
    # Two groups: 3 boxes inside the x-slice [-1, 1], 3 clearly outside.
    inside = [
        ("in0", AABB3D((-0.5, 0, 0), (0.5, 1, 1))),
        ("in1", AABB3D((-0.9, 0, 5), (-0.1, 1, 6))),
        ("in2", AABB3D((0.7, 0, -3), (0.9, 1, -2))),
    ]
    outside = [
        ("out0", AABB3D((10, 0, 0), (11, 1, 1))),
        ("out1", AABB3D((-8, 0, 0), (-7, 1, 1))),
        ("out2", AABB3D((100, 0, 0), (101, 1, 1))),
    ]
    bvh = BVH3D(inside + outside)
    hits = set(bvh.query_frustum(_XSliceFrustum()))
    assert hits == {"in0", "in1", "in2"}
    assert not any(h.startswith("out") for h in hits)


def test_query_frustum_rejects_none():
    bvh = BVH3D([("only", AABB3D((0, 0, 0), (1, 1, 1)))])
    with pytest.raises(TypeError):
        bvh.query_frustum(None)


def test_query_frustum_with_jj5_frustum_camera_default():
    """Integration with JJ5's SceneWalker.Frustum via Camera3D."""
    cam = Camera3D()  # eye (0,0,5), looking at origin
    frustum = Frustum.from_camera(cam)
    # A centred cube must be visible; something 100 units to the side must not.
    in_ent = ("visible", AABB3D((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5)))
    out_ent = ("far_right", AABB3D((100.0, 0.0, 0.0), (101.0, 1.0, 1.0)))
    bvh = BVH3D([in_ent, out_ent])
    hits = set(bvh.query_frustum(frustum))
    assert "visible" in hits
    assert "far_right" not in hits


# ---------------------------------------------------------------------------
# query_ray
# ---------------------------------------------------------------------------


def test_query_ray_hits_centered_cube_first():
    # Two cubes along +z; the closer one at z ∈ [-1, 1] must sort first.
    near = ("near", AABB3D((-1, -1, -1), (1, 1, 1)))
    far = ("far", AABB3D((-1, -1, 10), (1, 1, 12)))
    bvh = BVH3D([near, far])
    hits = bvh.query_ray((0.0, 0.0, -5.0), (0.0, 0.0, 1.0))
    assert len(hits) == 2
    # Nearest hit is (near, t=4.0).
    assert hits[0][0] == "near"
    assert hits[0][1] == pytest.approx(4.0)
    assert hits[1][0] == "far"
    # t for the far cube = 15 (from -5 to +10).
    assert hits[1][1] == pytest.approx(15.0)


def test_query_ray_misses_offset_cube():
    bvh = BVH3D([("cube", AABB3D((5, 5, 5), (6, 6, 6)))])
    hits = bvh.query_ray((0.0, 0.0, -5.0), (0.0, 0.0, 1.0))
    assert hits == []


def test_query_ray_zero_direction_raises():
    bvh = BVH3D([("cube", AABB3D((-1, -1, -1), (1, 1, 1)))])
    with pytest.raises(ValueError):
        bvh.query_ray((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))


def test_query_ray_parallel_axis_zero_component():
    # Direction has a zero component — slab test should still work.
    bvh = BVH3D([("cube", AABB3D((-1, -1, -1), (1, 1, 1)))])
    # Ray straight along +x through the origin.
    hits = bvh.query_ray((-5.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    assert hits and hits[0][0] == "cube"
    assert hits[0][1] == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# query_aabb
# ---------------------------------------------------------------------------


def test_query_aabb_finds_overlapping_entities():
    ents = _grid_entities(n_side=4)  # boxes at spacing 2.0
    bvh = BVH3D(ents)
    # Query box covers the central 2x2x2 grid slot only.
    q = AABB3D(min=(-0.6, -0.6, -0.6), max=(0.6, 0.6, 0.6))
    hits = set(bvh.query_aabb(q))
    # Grid centres near origin land in a leaf near the middle of the tree
    # — but only the specific unit boxes whose bounds intersect the query
    # should return.
    expected: set[str] = set()
    for eid, box in ents:
        if box.overlaps(q):
            expected.add(eid)
    assert hits == expected


def test_query_aabb_empty_result_when_disjoint():
    bvh = BVH3D([("cube", AABB3D((0, 0, 0), (1, 1, 1)))])
    q = AABB3D(min=(10, 10, 10), max=(11, 11, 11))
    assert bvh.query_aabb(q) == []


def test_query_aabb_type_check():
    bvh = BVH3D([("cube", AABB3D((0, 0, 0), (1, 1, 1)))])
    with pytest.raises(TypeError):
        bvh.query_aabb(((0, 0, 0), (1, 1, 1)))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# update_entity
# ---------------------------------------------------------------------------


def test_update_entity_reflects_in_aabb_query():
    ents = [
        ("mover", AABB3D((0, 0, 0), (1, 1, 1))),
        ("static", AABB3D((5, 5, 5), (6, 6, 6))),
    ]
    bvh = BVH3D(ents)
    # Move 'mover' next to 'static' — a query over that region should now
    # find both entities.
    bvh.update_entity("mover", AABB3D((4.5, 4.5, 4.5), (5.5, 5.5, 5.5)))
    hits = set(bvh.query_aabb(AABB3D((4, 4, 4), (6, 6, 6))))
    assert hits == {"mover", "static"}
    # And the old location (0..1) no longer returns 'mover'.
    old_hits = set(bvh.query_aabb(AABB3D((0, 0, 0), (0.5, 0.5, 0.5))))
    assert "mover" not in old_hits


def test_update_entity_refits_root_bounds():
    ents = _grid_entities(2)  # 8 small boxes near the origin
    bvh = BVH3D(ents)
    # Grow one entity to a very large box — root should encompass it.
    huge = AABB3D((-50, -50, -50), (50, 50, 50))
    bvh.update_entity("cube_0_0_0", huge)
    root = bvh.nodes[bvh.root]
    assert root.bounds.min[0] <= -50.0
    assert root.bounds.max[0] >= 50.0


def test_update_entity_unknown_id_raises():
    bvh = BVH3D([("only", AABB3D((0, 0, 0), (1, 1, 1)))])
    with pytest.raises(KeyError):
        bvh.update_entity("ghost", AABB3D((0, 0, 0), (1, 1, 1)))


def test_update_entity_type_checks():
    bvh = BVH3D([("only", AABB3D((0, 0, 0), (1, 1, 1)))])
    with pytest.raises(TypeError):
        bvh.update_entity(42, AABB3D((0, 0, 0), (1, 1, 1)))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        bvh.update_entity("only", ((0, 0, 0), (1, 1, 1)))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# SAH stats sanity
# ---------------------------------------------------------------------------


def test_sah_stats_reasonable_for_128_entities():
    ents = _random_entities(128, seed=42)
    bvh = BVH3D(ents)
    stats = bvh.stats()
    # depth ≤ log2(N) + 2.
    assert stats["depth"] <= int(math.log2(len(ents))) + 2
    # Average leaf size no larger than the threshold (4).
    assert stats["avg_leaf_size"] <= 4.0
    # Every entity accounted for in some leaf.
    assert stats["entity_count"] == len(ents)


def test_bvh_len_equals_entity_count():
    ents = _random_entities(37, seed=3)
    bvh = BVH3D(ents)
    assert len(bvh) == 37


def test_bvh_frustum_query_matches_linear_scan():
    """The BVH prune must not lose entities the linear scan would find."""
    ents = _random_entities(64, seed=5)
    bvh = BVH3D(ents)
    frustum = _XSliceFrustum()
    bvh_hits = set(bvh.query_frustum(frustum))
    linear_hits = {eid for eid, box in ents if frustum.intersects_aabb(box.as_tuple())}
    assert bvh_hits == linear_hits
