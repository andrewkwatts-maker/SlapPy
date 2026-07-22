"""Engine tests for iso subpackage — projection, IsoGrid, IsoTileDef. Headless."""
from __future__ import annotations
import pytest


class TestIsoViewpoint:
    def test_four_viewpoints_exist(self):
        from pharos_engine.iso.projection import IsoViewpoint
        assert len(list(IsoViewpoint)) == 4

    def test_ne_nw_sw_se_values(self):
        from pharos_engine.iso.projection import IsoViewpoint
        assert IsoViewpoint.NE == 0
        assert IsoViewpoint.NW == 1
        assert IsoViewpoint.SW == 2
        assert IsoViewpoint.SE == 3


class TestWorldToScreen:
    def test_origin_maps_to_zero(self):
        from pharos_engine.iso.projection import IsoViewpoint, world_to_screen
        sx, sy = world_to_screen(0, 0, 0, IsoViewpoint.NE)
        assert sx == pytest.approx(0.0)
        assert sy == pytest.approx(0.0)

    def test_height_moves_up(self):
        from pharos_engine.iso.projection import IsoViewpoint, world_to_screen
        _, sy0 = world_to_screen(0, 0, 0, IsoViewpoint.NE)
        _, sy1 = world_to_screen(0, 0, 1, IsoViewpoint.NE)
        assert sy1 < sy0  # higher gz = higher on screen = smaller sy

    def test_camera_offset_shifts_origin(self):
        from pharos_engine.iso.projection import IsoViewpoint, world_to_screen
        sx0, sy0 = world_to_screen(0, 0, 0, IsoViewpoint.NE, cam_x=0, cam_y=0)
        sx1, sy1 = world_to_screen(0, 0, 0, IsoViewpoint.NE, cam_x=100, cam_y=50)
        assert sx1 == pytest.approx(sx0 - 100)
        assert sy1 == pytest.approx(sy0 - 50)

    def test_all_viewpoints_no_crash(self):
        from pharos_engine.iso.projection import IsoViewpoint, world_to_screen
        for vp in IsoViewpoint:
            world_to_screen(5.0, 3.0, 2.0, vp)

    def test_ne_and_sw_are_mirrored(self):
        from pharos_engine.iso.projection import IsoViewpoint, world_to_screen
        sx_ne, sy_ne = world_to_screen(1, 1, 0, IsoViewpoint.NE)
        sx_sw, sy_sw = world_to_screen(1, 1, 0, IsoViewpoint.SW)
        assert sx_ne == pytest.approx(-sx_sw)


class TestScreenToWorld:
    def test_roundtrip_ne_viewpoint(self):
        from pharos_engine.iso.projection import IsoViewpoint, world_to_screen, screen_to_world
        for gx, gy in [(0, 0), (2, 3), (-1, 4), (5, 0)]:
            sx, sy = world_to_screen(gx, gy, 0, IsoViewpoint.NE)
            gx2, gy2 = screen_to_world(sx, sy, IsoViewpoint.NE)
            assert gx2 == gx
            assert gy2 == gy

    def test_roundtrip_nw_viewpoint(self):
        from pharos_engine.iso.projection import IsoViewpoint, world_to_screen, screen_to_world
        for gx, gy in [(0, 0), (3, 2)]:
            sx, sy = world_to_screen(gx, gy, 0, IsoViewpoint.NW)
            gx2, gy2 = screen_to_world(sx, sy, IsoViewpoint.NW)
            assert gx2 == gx
            assert gy2 == gy


class TestDepthKey:
    def test_higher_gz_has_larger_depth_key(self):
        from pharos_engine.iso.projection import IsoViewpoint, depth_key
        d0 = depth_key(2, 2, 0, IsoViewpoint.NE)
        d1 = depth_key(2, 2, 1, IsoViewpoint.NE)
        assert d1 > d0

    def test_depth_key_consistent_for_all_viewpoints(self):
        from pharos_engine.iso.projection import IsoViewpoint, depth_key
        for vp in IsoViewpoint:
            d = depth_key(3, 4, 0, vp)
            assert isinstance(d, float)


class TestIsoTileDef:
    def test_init_defaults(self):
        from pharos_engine.iso.iso_grid import IsoTileDef
        td = IsoTileDef("floor", "floor.png")
        assert td.name == "floor"
        assert td.sprite_path == "floor.png"
        assert td.passable is True
        assert td.z_height == pytest.approx(0.0)

    def test_sprite_for_fallback(self):
        from pharos_engine.iso.iso_grid import IsoTileDef
        from pharos_engine.iso.projection import IsoViewpoint
        td = IsoTileDef("wall", "wall.png")
        assert td.sprite_for(IsoViewpoint.NE) == "wall.png"

    def test_sprite_for_viewpoint_override(self):
        from pharos_engine.iso.iso_grid import IsoTileDef
        from pharos_engine.iso.projection import IsoViewpoint
        td = IsoTileDef("wall", "wall.png",
                        sprite_paths={IsoViewpoint.NW: "wall_nw.png"})
        assert td.sprite_for(IsoViewpoint.NW) == "wall_nw.png"
        assert td.sprite_for(IsoViewpoint.NE) == "wall.png"


class TestIsoGrid:
    def _make_grid(self):
        from pharos_engine.iso.iso_grid import IsoGrid
        return IsoGrid(width=10, height=10, depth=4)

    def _floor_def(self):
        from pharos_engine.iso.iso_grid import IsoTileDef
        return IsoTileDef("floor", "floor.png")

    def test_init_empty(self):
        g = self._make_grid()
        assert len(g.all_cells()) == 0

    def test_set_tile_returns_cell(self):
        from pharos_engine.iso.iso_grid import IsoCell
        g = self._make_grid()
        cell = g.set_tile(0, 0, 0, self._floor_def())
        assert isinstance(cell, IsoCell)

    def test_get_cell_returns_placed_tile(self):
        g = self._make_grid()
        floor = self._floor_def()
        g.set_tile(3, 4, 0, floor)
        cell = g.get_cell(3, 4, 0)
        assert cell is not None
        assert cell.tile_def is floor

    def test_get_cell_empty_returns_none(self):
        g = self._make_grid()
        assert g.get_cell(0, 0, 0) is None

    def test_set_tile_replaces_existing(self):
        from pharos_engine.iso.iso_grid import IsoTileDef
        g = self._make_grid()
        floor = self._floor_def()
        wall = IsoTileDef("wall", "wall.png")
        g.set_tile(1, 1, 0, floor)
        g.set_tile(1, 1, 0, wall)
        assert g.get_cell(1, 1, 0).tile_def is wall

    def test_remove_tile_clears_cell(self):
        g = self._make_grid()
        g.set_tile(2, 2, 0, self._floor_def())
        g.remove_tile(2, 2, 0)
        assert g.get_cell(2, 2, 0) is None

    def test_remove_nonexistent_no_crash(self):
        g = self._make_grid()
        g.remove_tile(99, 99, 0)

    def test_all_cells_count(self):
        g = self._make_grid()
        for i in range(5):
            g.set_tile(i, 0, 0, self._floor_def())
        assert len(g.all_cells()) == 5

    def test_top_z_empty_column_returns_0(self):
        g = self._make_grid()
        assert g.top_z(0, 0) == 0

    def test_top_z_stacked_tiles(self):
        g = self._make_grid()
        floor = self._floor_def()
        g.set_tile(0, 0, 0, floor)
        g.set_tile(0, 0, 1, floor)
        g.set_tile(0, 0, 2, floor)
        assert g.top_z(0, 0) == 2


class TestIsoGridSortedCells:
    def _populate(self, grid, n=4):
        from pharos_engine.iso.iso_grid import IsoTileDef
        floor = IsoTileDef("floor", "floor.png")
        for i in range(n):
            grid.set_tile(i, i, 0, floor)

    def test_sorted_cells_returns_list(self):
        from pharos_engine.iso.iso_grid import IsoGrid
        from pharos_engine.iso.projection import IsoViewpoint
        g = IsoGrid(10, 10)
        self._populate(g)
        result = g.sorted_cells(IsoViewpoint.NE)
        assert isinstance(result, list)

    def test_sorted_cells_has_three_tuple(self):
        from pharos_engine.iso.iso_grid import IsoGrid
        from pharos_engine.iso.projection import IsoViewpoint
        g = IsoGrid(10, 10)
        self._populate(g, 1)
        result = g.sorted_cells(IsoViewpoint.NE)
        assert len(result) == 1
        cell, sx, sy = result[0]
        assert isinstance(sx, float)
        assert isinstance(sy, float)

    def test_sorted_cells_frustum_cull_far_tiles(self):
        from pharos_engine.iso.iso_grid import IsoGrid, IsoTileDef
        from pharos_engine.iso.projection import IsoViewpoint
        g = IsoGrid(100, 100)
        floor = IsoTileDef("floor", "floor.png")
        # Place a tile far off screen
        g.set_tile(99, 99, 0, floor)
        # Small screen, no cam offset — the far tile should be culled
        result = g.sorted_cells(IsoViewpoint.NE, screen_w=100, screen_h=100)
        assert len(result) == 0

    def test_sorted_cells_depth_ordered(self):
        from pharos_engine.iso.iso_grid import IsoGrid, IsoTileDef
        from pharos_engine.iso.projection import IsoViewpoint, depth_key
        g = IsoGrid(10, 10, tile_w=64, tile_h=32)
        floor = IsoTileDef("floor", "floor.png")
        for i in range(5):
            g.set_tile(i, i, 0, floor)
        result = g.sorted_cells(IsoViewpoint.NE, screen_w=2000, screen_h=2000)
        if len(result) >= 2:
            # Verify the depth ordering is non-decreasing
            cells = [r[0] for r in result]
            keys = [depth_key(c.gx, c.gy, c.gz, IsoViewpoint.NE) for c in cells]
            assert keys == sorted(keys)

    def test_sorted_cells_all_viewpoints_no_crash(self):
        from pharos_engine.iso.iso_grid import IsoGrid, IsoTileDef
        from pharos_engine.iso.projection import IsoViewpoint
        g = IsoGrid(5, 5)
        floor = IsoTileDef("floor", "f.png")
        for i in range(3):
            g.set_tile(i, i, 0, floor)
        for vp in IsoViewpoint:
            g.sorted_cells(vp, screen_w=2000, screen_h=2000)
