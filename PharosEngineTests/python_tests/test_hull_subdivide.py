"""Tests for HullTree.subdivide / coalesce — hierarchical refinement.

Sprint 2 implementation: a hull splits into 1 centre + 6 hex-ring children
at √2 inner radius; children inherit bulk state; cell-grid sub-sampling
threads through an optional CellGridPool.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from pharos_engine.physics.cell import (
    CELL_GRID_SIZE,
    CELL_PIXEL_STRUCT,
    CellGridPool,
)
from pharos_engine.physics.hull import (
    NO_CELL_GRID,
    HullTree,
    TIER_T2,
)


_ROOT_KW = dict(
    x=10.0,
    y=-5.0,
    cell_size_x=1.0,
    cell_size_y=1.0,
    mass=7.0,           # easy to divide by 7 cleanly
    inertia=14.0,       # easy to divide by 7 cleanly
    material_id=3,
    tier=TIER_T2,
)


def _spawn_default_root(tree: HullTree) -> int:
    """Spawn a root with deterministic state we can reason about in asserts."""
    rid = tree.spawn_root(**_ROOT_KW)
    tree.velocity[rid, 0] = 4.0
    tree.velocity[rid, 1] = -2.0
    tree.omega[rid] = 0.5
    return rid


def test_subdivide_creates_7_children():
    tree = HullTree()
    rid = _spawn_default_root(tree)

    kids = tree.subdivide(rid)
    assert len(kids) == 7
    assert int(tree.child_count[rid]) == 7
    # All children alive and pointing back at the parent.
    for cid in kids:
        assert tree.is_alive(cid)
        assert int(tree.parent_id[cid]) == rid
        assert int(tree.depth[cid]) == int(tree.depth[rid]) + 1
        assert int(tree.root_id[cid]) == int(tree.root_id[rid])

    # Idempotent: calling again returns the same set.
    kids2 = tree.subdivide(rid)
    assert kids2 == kids


def test_subdivide_children_inherit_velocity():
    tree = HullTree()
    rid = _spawn_default_root(tree)
    kids = tree.subdivide(rid)
    for cid in kids:
        assert float(tree.velocity[cid, 0]) == pytest.approx(4.0)
        assert float(tree.velocity[cid, 1]) == pytest.approx(-2.0)
        assert float(tree.omega[cid]) == pytest.approx(0.5)
        assert int(tree.material_id[cid]) == int(tree.material_id[rid])
        assert int(tree.tier[cid]) == int(tree.tier[rid])
        assert bool(tree.fixed[cid]) == bool(tree.fixed[rid])


def test_subdivide_children_centred_correctly():
    """Centre child at the parent; 6 ring children at radius = R/√2 at
    angles 0, π/3, 2π/3, π, 4π/3, 5π/3."""
    tree = HullTree()
    rid = _spawn_default_root(tree)
    px = float(tree.position[rid, 0])
    py = float(tree.position[rid, 1])
    parent_r = float(tree.radius[rid])
    expected_ring = parent_r / math.sqrt(2.0)

    kids = tree.subdivide(rid)
    # First child is the centre child.
    centre = kids[0]
    assert float(tree.position[centre, 0]) == pytest.approx(px, abs=1e-5)
    assert float(tree.position[centre, 1]) == pytest.approx(py, abs=1e-5)
    assert float(tree.centre_local[centre, 0]) == pytest.approx(0.0, abs=1e-5)
    assert float(tree.centre_local[centre, 1]) == pytest.approx(0.0, abs=1e-5)

    # Remaining 6 children form a hex ring.
    for k, cid in enumerate(kids[1:]):
        theta = k * (math.pi / 3.0)
        ex = expected_ring * math.cos(theta)
        ey = expected_ring * math.sin(theta)
        assert float(tree.position[cid, 0]) == pytest.approx(px + ex, abs=1e-4)
        assert float(tree.position[cid, 1]) == pytest.approx(py + ey, abs=1e-4)
        assert float(tree.centre_local[cid, 0]) == pytest.approx(ex, abs=1e-4)
        assert float(tree.centre_local[cid, 1]) == pytest.approx(ey, abs=1e-4)
        # Distance from parent centre = expected_ring.
        d = math.hypot(
            float(tree.position[cid, 0]) - px,
            float(tree.position[cid, 1]) - py,
        )
        assert d == pytest.approx(expected_ring, abs=1e-4)

    # Cell-size shrunk by 1/√2 per axis.
    for cid in kids:
        assert float(tree.cell_size_x[cid]) == pytest.approx(
            float(tree.cell_size_x[rid]) / math.sqrt(2.0), rel=1e-5,
        )
        assert float(tree.cell_size_y[cid]) == pytest.approx(
            float(tree.cell_size_y[rid]) / math.sqrt(2.0), rel=1e-5,
        )


def test_subdivide_then_coalesce_round_trips():
    """After subdivide + coalesce, the parent's bulk velocity is preserved
    (children all inherited the same velocity so the mass-weighted mean
    equals the original) and child slots are freed."""
    tree = HullTree()
    rid = _spawn_default_root(tree)
    v0 = (float(tree.velocity[rid, 0]), float(tree.velocity[rid, 1]))
    om0 = float(tree.omega[rid])
    kids = tree.subdivide(rid)
    # Sanity: 7 extra hulls live now.
    assert tree.count == 8

    tree.coalesce(rid)

    assert int(tree.child_count[rid]) == 0
    # Children freed.
    for cid in kids:
        assert not tree.is_alive(cid)
    # Bulk state preserved.
    assert float(tree.velocity[rid, 0]) == pytest.approx(v0[0], rel=1e-5)
    assert float(tree.velocity[rid, 1]) == pytest.approx(v0[1], rel=1e-5)
    assert float(tree.omega[rid]) == pytest.approx(om0, rel=1e-5)
    # Live-count returns to 1.
    assert tree.count == 1


def test_coalesce_with_no_children_is_noop():
    tree = HullTree()
    rid = _spawn_default_root(tree)
    # No children — coalesce must be a clean no-op.
    pre_count = tree.count
    pre_v = tree.velocity[rid].copy()
    tree.coalesce(rid)
    assert tree.count == pre_count
    assert np.allclose(tree.velocity[rid], pre_v)
    assert int(tree.child_count[rid]) == 0


def test_subdivide_with_cell_pool_seeds_grids():
    """When a cell pool is provided, each child gets its own slot, and
    the parent's cell field is downsampled into each child."""
    pool = CellGridPool(capacity=16)
    tree = HullTree()
    rid = _spawn_default_root(tree)

    # Parent owns a cell grid with a recognisable density pattern.
    parent_slot = pool.acquire()
    tree.cell_grid_id[rid] = parent_slot
    parent_view = pool.slot_view(parent_slot)
    density = CELL_PIXEL_STRUCT.slice_field(parent_view, "density")
    yy, xx = np.mgrid[0:CELL_GRID_SIZE, 0:CELL_GRID_SIZE].astype(np.float32)
    density[...] = xx + yy * 0.01  # unique per cell

    pre_in_use = pool.in_use_count
    kids = tree.subdivide(rid, cell_pool=pool)
    assert pool.in_use_count == pre_in_use + 7

    for cid in kids:
        gid = int(tree.cell_grid_id[cid])
        assert gid != NO_CELL_GRID
        view = pool.slot_view(gid)
        child_density = CELL_PIXEL_STRUCT.slice_field(view, "density")
        # Sampled from the parent's pattern — must be non-zero somewhere.
        assert float(child_density.max()) > 0.0

    # Coalesce should release every child's slot.
    tree.coalesce(rid, cell_pool=pool)
    assert pool.in_use_count == pre_in_use  # only the parent's slot remains


def test_subdivide_mass_sums_to_parent_mass():
    tree = HullTree()
    rid = _spawn_default_root(tree)
    parent_mass = float(tree.mass[rid])
    parent_inertia = float(tree.inertia[rid])

    kids = tree.subdivide(rid)
    total_m = sum(float(tree.mass[c]) for c in kids)
    total_i = sum(float(tree.inertia[c]) for c in kids)
    assert total_m == pytest.approx(parent_mass, rel=1e-6)
    assert total_i == pytest.approx(parent_inertia, rel=1e-6)
