from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING
import numpy as np
from slappyengine.render_target import RenderTarget
from slappyengine.layer import Layer

if TYPE_CHECKING:
    from slappyengine.camera import Camera


class TileCoord:
    __slots__ = ("x", "y")

    def __init__(self, x: int, y: int) -> None:
        self.x = x
        self.y = y

    def __hash__(self) -> int:
        return hash((self.x, self.y))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TileCoord):
            return NotImplemented
        return self.x == other.x and self.y == other.y

    def __repr__(self) -> str:
        return f"TileCoord({self.x}, {self.y})"


class Tile(RenderTarget):
    def __init__(self, coord: TileCoord, tile_size: int) -> None:
        super().__init__(
            name=f"tile_{coord.x}_{coord.y}",
            position=(float(coord.x * tile_size), float(coord.y * tile_size)),
            size=(tile_size, tile_size),
        )
        self.coord = coord
        self.tile_size = tile_size
        self._dirty = False

    def mark_dirty(self) -> None:
        self._dirty = True

    def mark_clean(self) -> None:
        self._dirty = False


class Landscape:
    def __init__(
        self,
        tile_size: int = 256,
        tile_dir: str | Path = ".",
        cache_size: int | None = None,
    ) -> None:
        from slappyengine.config import engine_config
        cfg = engine_config()
        self.tile_size = tile_size
        self.tile_dir = Path(tile_dir)
        self.tile_dir.mkdir(parents=True, exist_ok=True)
        _cache_size = cache_size if cache_size is not None else cfg.residency.tile_cache_size

        try:
            from slappyengine import _core
            self._cache = _core.TileCache(_cache_size)
            self._use_rust_cache = True
        except (ImportError, AttributeError):
            self._cache: dict = {}
            self._use_rust_cache = False

        self._loaded_tiles: dict[TileCoord, Tile] = {}
        self._visible_coords: set[TileCoord] = set()

    def _tile_path_png(self, coord: TileCoord) -> Path:
        return self.tile_dir / f"tile_{coord.x}_{coord.y}.png"

    def _tile_path_slap(self, coord: TileCoord) -> Path:
        return self.tile_dir / f"tile_{coord.x}_{coord.y}.slap"

    def _visible_tile_coords(self, camera: Camera) -> set[TileCoord]:
        left, top, right, bottom = camera.visible_rect()
        ts = self.tile_size
        min_tx = int(left // ts)
        max_tx = int(right // ts) + 1
        min_ty = int(top // ts)
        max_ty = int(bottom // ts) + 1
        return {
            TileCoord(x, y)
            for x in range(min_tx, max_tx + 1)
            for y in range(min_ty, max_ty + 1)
        }

    def _load_tile(self, coord: TileCoord) -> Tile:
        tile = Tile(coord, self.tile_size)
        png_path = self._tile_path_png(coord)
        if png_path.exists():
            from PIL import Image
            img = Image.open(png_path).convert("RGBA")
            arr = np.asarray(img, dtype=np.uint8)
            layer = Layer.blank(self.tile_size, self.tile_size, name="terrain")
            layer._image_data = arr
        else:
            layer = Layer.blank(self.tile_size, self.tile_size, name="terrain")
            layer._image_data = np.zeros(
                (self.tile_size, self.tile_size, 4), dtype=np.uint8
            )
        tile.add_layer(layer)
        return tile

    def _unload_tile(self, coord: TileCoord) -> None:
        tile = self._loaded_tiles.pop(coord, None)
        if tile is None:
            return
        if tile._dirty:
            self._flush_tile(tile)

    def _flush_tile(self, tile: Tile) -> None:
        if not tile.layers:
            return
        layer = tile.layers[0]
        if layer._image_data is None:
            return
        from PIL import Image
        img = Image.fromarray(layer._image_data, mode="RGBA")
        img.save(self._tile_path_png(tile.coord))
        tile.mark_clean()

    def update(self, camera: Camera) -> None:
        new_visible = self._visible_tile_coords(camera)

        for coord in new_visible - self._visible_coords:
            if coord not in self._loaded_tiles:
                self._loaded_tiles[coord] = self._load_tile(coord)

        for coord in self._visible_coords - new_visible:
            self._unload_tile(coord)

        self._visible_coords = new_visible

    def flush_all(self) -> None:
        for tile in self._loaded_tiles.values():
            if tile._dirty:
                self._flush_tile(tile)

    @property
    def visible_tiles(self) -> list[Tile]:
        return [self._loaded_tiles[c] for c in self._visible_coords if c in self._loaded_tiles]

    def get_tile(self, tile_x: int, tile_y: int) -> Tile | None:
        return self._loaded_tiles.get(TileCoord(tile_x, tile_y))

    def paint_tile(self, tile_x: int, tile_y: int, image_data: np.ndarray) -> None:
        coord = TileCoord(tile_x, tile_y)
        if coord not in self._loaded_tiles:
            self._loaded_tiles[coord] = self._load_tile(coord)
        tile = self._loaded_tiles[coord]
        if tile.layers:
            tile.layers[0]._image_data = image_data
        tile.mark_dirty()
