"""Focused tests for ``physics.particle_spatial.SpatialHash``.

These exercise the CPU implementation; the GPU port (planned) is
expected to satisfy the same contract.
"""

from __future__ import annotations

import numpy as np
import pytest

from slappyengine.physics.particle_spatial import SpatialHash


def test_rebuild_partitions_particles_correctly():
    """Particles in distinct cells must end up in distinct (start, count)
    slots; particles in the same cell must end up contiguous."""
    h = SpatialHash(cell_size=10.0, width=100, height=100)
    # Three particles in cell (0, 0), one in cell (5, 5), two in (2, 3).
    positions = np.array(
        [
            [1.0, 1.0],    # cell (0, 0)
            [2.0, 3.0],    # cell (0, 0)
            [9.0, 9.0],    # cell (0, 0)
            [55.0, 55.0],  # cell (5, 5)
            [25.0, 35.0],  # cell (2, 3)
            [29.0, 31.0],  # cell (2, 3)
        ],
        dtype=np.float32,
    )
    h.rebuild(positions)

    # Total of sorted_ids equals total particle count.
    assert h.sorted_ids.size == 6
    # Total of cell_count equals total particle count.
    assert int(h.cell_count.sum()) == 6

    # Identify the cells we expect to be populated and check counts.
    gx = h._gx
    # Helper: world cell -> flat key (with +1 padding bias).
    def key(cx: int, cy: int) -> int:
        return (cy + 1) * gx + (cx + 1)

    assert int(h.cell_count[key(0, 0)]) == 3
    assert int(h.cell_count[key(5, 5)]) == 1
    assert int(h.cell_count[key(2, 3)]) == 2

    # The three (0, 0) ids must be contiguous in sorted_ids.
    start = int(h.cell_start[key(0, 0)])
    block = set(int(x) for x in h.sorted_ids[start : start + 3])
    assert block == {0, 1, 2}


def test_query_neighbours_finds_only_in_radius():
    """``query_radius`` must return exactly the particles inside the
    disk and exclude particles outside it."""
    h = SpatialHash(cell_size=5.0, width=100, height=100)
    positions = np.array(
        [
            [50.0, 50.0],  # at the query center
            [52.0, 50.0],  # 2 px away  -> inside r=3
            [53.5, 50.0],  # 3.5 px away -> outside r=3
            [50.0, 56.0],  # 6 px away  -> outside r=3
            [49.0, 49.0],  # ~1.41 px   -> inside r=3
            [90.0, 90.0],  # far away
        ],
        dtype=np.float32,
    )
    h.rebuild(positions)

    found = h.query_radius(positions, (50.0, 50.0), radius=3.0)
    found_set = set(int(x) for x in found)
    assert found_set == {0, 1, 4}


def test_rebuild_with_zero_particles_is_safe():
    """Zero particles must produce well-formed empty buffers, not crash
    and not poison subsequent queries."""
    h = SpatialHash(cell_size=4.0, width=64, height=64)
    h.rebuild(np.zeros((0, 2), dtype=np.float32))

    assert h.sorted_ids.size == 0
    # cell_count / cell_start sized to grid, all zero.
    assert h.cell_count.size == h._gx * h._gy
    assert h.cell_start.size == h._gx * h._gy
    assert int(h.cell_count.sum()) == 0

    # Queries against an empty hash return an empty id array.
    result = h.query_neighbours((10.0, 10.0), radius=5.0)
    assert isinstance(result, np.ndarray)
    assert result.size == 0


def test_cell_count_sums_to_total_particles():
    """For any random distribution within bounds, the cell counts must
    sum to the total particle count -- no losses, no double-counting."""
    rng = np.random.default_rng(seed=42)
    n = 500
    positions = rng.uniform(low=0.0, high=200.0, size=(n, 2)).astype(np.float32)

    h = SpatialHash(cell_size=8.0, width=200, height=200)
    h.rebuild(positions)

    assert int(h.cell_count.sum()) == n
    assert h.sorted_ids.size == n
    # Every original particle id must appear exactly once.
    assert sorted(int(x) for x in h.sorted_ids) == list(range(n))


def test_two_close_particles_share_a_cell():
    """Two particles within one cell_size must be in the same cell and
    discoverable as neighbours of one another."""
    h = SpatialHash(cell_size=10.0, width=50, height=50)
    positions = np.array(
        [
            [12.0, 12.0],
            [14.0, 13.0],  # 2.24 px from id 0; both in cell (1, 1)
        ],
        dtype=np.float32,
    )
    h.rebuild(positions)

    cx = int(np.floor(12.0 / 10.0)) + 1  # +1 padding bias
    cy = int(np.floor(12.0 / 10.0)) + 1
    key = cy * h._gx + cx
    assert int(h.cell_count[key]) == 2

    # Each particle should see the other as a neighbour at r > 2.24.
    found = h.query_radius(positions, (12.0, 12.0), radius=5.0)
    found_set = set(int(x) for x in found)
    assert found_set == {0, 1}
