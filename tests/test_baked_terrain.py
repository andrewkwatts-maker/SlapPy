"""Tests for slappyengine.physics.baked_terrain — bake + region grid."""
from __future__ import annotations

import numpy as np
import pytest

from slappyengine.physics.baked_terrain import (
    RegionGrid,
    RegionState,
    bake_settled_particles,
    unbake_region_to_particles,
)


# ── Bake path ──────────────────────────────────────────────────────────────


def _make_arrays(n: int):
    pos = np.zeros((n, 2), dtype=np.float32)
    radius = np.ones(n, dtype=np.float32)
    colour = np.zeros((n, 3), dtype=np.uint8)
    landed = np.zeros(n, dtype=bool)
    settled = np.zeros(n, dtype=bool)
    bake_flag = np.zeros(n, dtype=bool)
    return pos, radius, colour, landed, settled, bake_flag


def test_bake_writes_settled_pixels_to_terrain() -> None:
    terrain = np.zeros((100, 100, 4), dtype=np.uint8)
    pos, rad, col, landed, settled, baked = _make_arrays(3)
    pos[:] = [(10, 10), (50, 50), (90, 90)]
    col[:] = [(200, 100, 50), (10, 220, 30), (40, 60, 230)]
    rad[:] = 1.0
    landed[:] = True
    settled[:] = True
    n = bake_settled_particles(
        pos=pos, radius=rad, colour=col, landed=landed, settled=settled,
        bake_flag=baked, terrain_rgba=terrain,
    )
    assert n == 3
    assert terrain[10, 10, 3] == 255
    assert tuple(terrain[10, 10, :3]) == (200, 100, 50)
    assert tuple(terrain[50, 50, :3]) == (10, 220, 30)


def test_bake_skips_unsettled() -> None:
    terrain = np.zeros((50, 50, 4), dtype=np.uint8)
    pos, rad, col, landed, settled, baked = _make_arrays(2)
    pos[:] = [(5, 5), (25, 25)]
    col[:] = [(100, 100, 100), (50, 50, 50)]
    landed[:] = True
    settled[0] = True
    settled[1] = False  # still sliding
    n = bake_settled_particles(
        pos=pos, radius=rad, colour=col, landed=landed, settled=settled,
        bake_flag=baked, terrain_rgba=terrain,
    )
    assert n == 1
    assert terrain[5, 5, 3] == 255
    assert terrain[25, 25, 3] == 0  # unsettled — not baked


def test_bake_idempotent_via_bake_flag() -> None:
    terrain = np.zeros((20, 20, 4), dtype=np.uint8)
    pos, rad, col, landed, settled, baked = _make_arrays(1)
    pos[:] = [(10, 10)]
    col[:] = [(123, 45, 67)]
    landed[:] = True
    settled[:] = True
    n1 = bake_settled_particles(
        pos=pos, radius=rad, colour=col, landed=landed, settled=settled,
        bake_flag=baked, terrain_rgba=terrain,
    )
    # Second call must NOT re-bake (bake_flag now True).
    n2 = bake_settled_particles(
        pos=pos, radius=rad, colour=col, landed=landed, settled=settled,
        bake_flag=baked, terrain_rgba=terrain,
    )
    assert n1 == 1
    assert n2 == 0


def test_bake_rejects_wrong_shape() -> None:
    terrain = np.zeros((20, 20, 3), dtype=np.uint8)  # missing alpha
    pos, rad, col, landed, settled, baked = _make_arrays(1)
    settled[:] = True
    landed[:] = True
    with pytest.raises(ValueError, match=r"\(H, W, 4\)"):
        bake_settled_particles(
            pos=pos, radius=rad, colour=col, landed=landed, settled=settled,
            bake_flag=baked, terrain_rgba=terrain,
        )


# ── RegionGrid ─────────────────────────────────────────────────────────────


def test_region_grid_starts_all_dormant() -> None:
    g = RegionGrid(width=640, height=360, cell_size=64)
    assert g.shape_cells == (6, 10)
    assert g.active_cell_count() == 0
    assert g.static_cell_count() == 0


def test_record_live_flips_to_active() -> None:
    g = RegionGrid(width=640, height=360, cell_size=64)
    positions = np.array([(100, 100), (320, 200)], dtype=np.float32)
    g.record_live(positions)
    # Cell (1,1) = (100,100) and cell (3,3) = (320,200) should be ACTIVE.
    assert g.active_cell_count() == 2


def test_mark_static_after_idle_frames() -> None:
    g = RegionGrid(width=64, height=64, cell_size=32)
    g.record_live(np.array([(10, 10)], dtype=np.float32))
    assert g.active_cell_count() == 1
    # Now particles gone — repeat idle for 5 frames at idle_frames=5.
    for _ in range(5):
        g.record_live(np.zeros((0, 2), dtype=np.float32))
        g.mark_static_when_idle(idle_frames=5)
    assert g.static_cell_count() == 1


def test_wake_region_flips_back_to_active() -> None:
    g = RegionGrid(width=64, height=64, cell_size=32)
    g.record_live(np.array([(10, 10)], dtype=np.float32))
    for _ in range(5):
        g.record_live(np.zeros((0, 2), dtype=np.float32))
        g.mark_static_when_idle(idle_frames=5)
    assert g.static_cell_count() == 1
    # Wake the static cell.
    woken = g.wake_region(10, 10, radius=0)
    assert woken == 1
    assert g.active_cell_count() == 1
    assert g.static_cell_count() == 0


def test_unbake_emits_seeds_from_baked_pixels() -> None:
    g = RegionGrid(width=64, height=64, cell_size=32)
    terrain = np.zeros((64, 64, 4), dtype=np.uint8)
    # Plant 3 baked pixels in cell (0, 0).
    terrain[10, 10] = (255, 0, 0, 255)
    terrain[11, 11] = (0, 255, 0, 255)
    terrain[12, 12] = (0, 0, 255, 255)
    seeds_pos: list = []
    seeds_col: list = []
    seeds_rad: list = []
    n = unbake_region_to_particles(
        g, cy=0, cx=0, terrain_rgba=terrain,
        out_pos=seeds_pos, out_colour=seeds_col, out_radius=seeds_rad,
    )
    assert n == 3
    assert len(seeds_pos) == 3
    # Baked pixels were cleared.
    assert terrain[10, 10, 3] == 0
    assert terrain[12, 12, 3] == 0


def test_region_grid_rejects_bad_dims() -> None:
    with pytest.raises(ValueError):
        RegionGrid(width=0, height=10)
    with pytest.raises(ValueError):
        RegionGrid(width=10, height=10, cell_size=0)
