"""
Tests for Pharos Engine.landscape — no GPU required.
"""
import pytest
import numpy as np

try:
    from pharos_engine.landscape import TileCoord, Tile, Landscape
    from pharos_engine.camera import Camera
except ImportError as _landscape_err:
    pytest.skip(
        f"Pharos Engine.landscape not importable: {_landscape_err}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# TileCoord
# ---------------------------------------------------------------------------

def test_tile_coord_hash():
    a = TileCoord(1, 2)
    b = TileCoord(1, 2)
    c = TileCoord(2, 1)
    assert a == b
    assert hash(a) == hash(b)
    assert a != c


# ---------------------------------------------------------------------------
# Tile
# ---------------------------------------------------------------------------

def test_tile_world_position():
    coord = TileCoord(3, 4)
    tile = Tile(coord, tile_size=256)
    assert tile.position == (3 * 256.0, 4 * 256.0)
    assert tile.size == (256, 256)


def test_tile_dirty_flag():
    tile = Tile(TileCoord(0, 0), tile_size=64)
    assert not tile._dirty
    tile.mark_dirty()
    assert tile._dirty
    tile.mark_clean()
    assert not tile._dirty


# ---------------------------------------------------------------------------
# Landscape — construction
# ---------------------------------------------------------------------------

def test_landscape_init(tmp_path):
    ls = Landscape(tile_size=64, tile_dir=tmp_path, cache_size=8)
    assert ls.tile_size == 64
    assert ls.visible_tiles == []


# ---------------------------------------------------------------------------
# Landscape — update loads blank tiles for visible area
# ---------------------------------------------------------------------------

def test_landscape_load_creates_blank_tile(tmp_path):
    ls = Landscape(tile_size=64, tile_dir=tmp_path, cache_size=8)
    cam = Camera()
    cam._viewport_size = (128, 128)
    ls.update(cam)
    tiles = ls.visible_tiles
    assert len(tiles) > 0
    for tile in tiles:
        assert len(tile.layers) == 1
        assert tile.layers[0]._image_data is not None


# ---------------------------------------------------------------------------
# Landscape — paint_tile marks dirty
# ---------------------------------------------------------------------------

def test_landscape_paint_tile(tmp_path):
    ls = Landscape(tile_size=32, tile_dir=tmp_path, cache_size=4)
    data = np.full((32, 32, 4), [255, 0, 0, 255], dtype=np.uint8)
    ls.paint_tile(0, 0, data)
    tile = ls.get_tile(0, 0)
    assert tile is not None
    assert tile._dirty


# ---------------------------------------------------------------------------
# Landscape — flush_all writes PNG to disk
# ---------------------------------------------------------------------------

def test_landscape_flush_saves_png(tmp_path):
    ls = Landscape(tile_size=32, tile_dir=tmp_path, cache_size=4)
    data = np.full((32, 32, 4), [0, 255, 0, 255], dtype=np.uint8)
    ls.paint_tile(2, 3, data)
    ls.flush_all()
    expected_png = tmp_path / "tile_2_3.png"
    assert expected_png.exists()


# ---------------------------------------------------------------------------
# Landscape — get_tile for an unloaded coord returns None
# ---------------------------------------------------------------------------

def test_landscape_get_nonexistent_tile_returns_none(tmp_path):
    ls = Landscape(tile_size=64, tile_dir=tmp_path, cache_size=4)
    assert ls.get_tile(99, 99) is None


# ---------------------------------------------------------------------------
# Landscape — camera determines which tiles are visible
# ---------------------------------------------------------------------------

def test_landscape_visible_coords_from_camera(tmp_path):
    ls = Landscape(tile_size=100, tile_dir=tmp_path, cache_size=16)
    cam = Camera()
    cam._viewport_size = (200, 200)  # 2×2 tiles visible
    ls.update(cam)
    assert len(ls.visible_tiles) >= 4  # at least the 4 corner tiles
