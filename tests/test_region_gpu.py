"""Tests for :class:`RegionGridGPU` — the GPU-friendly region grid.

Covers state codes, dirty-flag flips on live-count change, and the
mark_dirty helper that flags blast-impact regions for indirect
dispatch on the GPU.
"""
from __future__ import annotations

import numpy as np
import pytest

from slappyengine.physics.region_gpu import (
    ACTIVE,
    DORMANT,
    STATIC,
    RegionGridGPU,
)


# ── Construction ──────────────────────────────────────────────────────


def test_initial_state_all_dormant() -> None:
    """Fresh grid: every cell DORMANT, zero live, no dirt."""
    g = RegionGridGPU(width=256, height=256, cell_size=64)
    assert g.shape_cells == (4, 4)
    assert g.state.dtype == np.int8
    assert g.live_count.dtype == np.int32
    assert g.dirty.dtype == bool
    assert (g.state == DORMANT).all()
    assert g.live_count.sum() == 0
    assert not g.dirty.any()
    assert g.active_cell_count() == 0
    assert g.static_cell_count() == 0


def test_record_live_flips_to_active() -> None:
    """A particle inside a cell flips that cell's state to ACTIVE."""
    g = RegionGridGPU(width=256, height=256, cell_size=64)
    # One particle at (100, 100) → cell (1, 1).
    positions = np.array([[100.0, 100.0]], dtype=np.float32)
    g.record_live(positions)
    assert g.state[1, 1] == ACTIVE
    assert g.live_count[1, 1] == 1
    # The other 15 cells stay DORMANT.
    others_mask = np.ones_like(g.state, dtype=bool)
    others_mask[1, 1] = False
    assert (g.state[others_mask] == DORMANT).all()


# ── active_cell_indices ───────────────────────────────────────────────


def test_active_cell_indices_returns_flat_indices() -> None:
    """active_cell_indices returns the flat indices of ACTIVE cells."""
    g = RegionGridGPU(width=256, height=256, cell_size=64)
    # Two particles in two distinct cells.
    positions = np.array(
        [[10.0, 10.0],     # cell (0, 0)
         [200.0, 200.0]],  # cell (3, 3)
        dtype=np.float32,
    )
    g.record_live(positions)
    idx = g.active_cell_indices()
    # cols = 4, so (0, 0) → 0 and (3, 3) → 15.
    assert idx.dtype == np.int32
    assert sorted(idx.tolist()) == [0, 15]


# ── mark_dirty ────────────────────────────────────────────────────────


def test_mark_dirty_at_centre_flags_one_cell() -> None:
    """A tiny dirty radius at a cell centre flags only that cell."""
    g = RegionGridGPU(width=256, height=256, cell_size=64)
    # Centre of cell (1, 1) is (96, 96).
    marked = g.mark_dirty(x=96.0, y=96.0, radius=0.0)
    assert marked == 1
    assert g.dirty[1, 1]
    # Everything else stays clean.
    others_mask = np.ones_like(g.dirty)
    others_mask[1, 1] = False
    assert not g.dirty[others_mask].any()


def test_mark_dirty_with_radius_flags_overlapping_cells() -> None:
    """A larger radius spans multiple neighbouring cells."""
    g = RegionGridGPU(width=512, height=512, cell_size=64)
    # Cell centre at (160, 160) — cell (2, 2). Radius 80 should reach
    # into neighbouring cells.
    marked = g.mark_dirty(x=160.0, y=160.0, radius=80.0)
    # At least the centre cell + its 4 orthogonal neighbours.
    assert marked >= 5
    assert g.dirty[2, 2]
    assert g.dirty[1, 2]
    assert g.dirty[3, 2]
    assert g.dirty[2, 1]
    assert g.dirty[2, 3]


# ── clear_dirty ───────────────────────────────────────────────────────


def test_clear_dirty_resets_all() -> None:
    """clear_dirty wipes every flag."""
    g = RegionGridGPU(width=256, height=256, cell_size=64)
    g.mark_dirty(x=128.0, y=128.0, radius=200.0)
    assert g.dirty.any()
    g.clear_dirty()
    assert not g.dirty.any()
    assert g.dirty_count() == 0


# ── record_live → dirty interaction ───────────────────────────────────


def test_record_live_marks_cells_dirty_when_particle_first_enters() -> None:
    """A particle entering a previously-empty cell flips it dirty.

    This is the indirect-dispatch trigger: a cell that gained or lost
    particles this frame needs its compute shader re-run.
    """
    g = RegionGridGPU(width=256, height=256, cell_size=64)
    # Frame 0: no particles. Dirty stays clean.
    g.record_live(np.zeros((0, 2), dtype=np.float32))
    assert not g.dirty.any()
    # Frame 1: a particle enters cell (1, 1) — should flip dirty.
    g.record_live(np.array([[100.0, 100.0]], dtype=np.float32))
    assert g.dirty[1, 1]
    # End of frame.
    g.clear_dirty()
    # Frame 2: same particle, same cell. No change → not dirty.
    g.record_live(np.array([[100.0, 100.0]], dtype=np.float32))
    assert not g.dirty[1, 1]
    # Frame 3: particle leaves → cell becomes dirty again (lost a count).
    g.record_live(np.zeros((0, 2), dtype=np.float32))
    assert g.dirty[1, 1]
