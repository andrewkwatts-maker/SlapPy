from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .projection import IsoViewpoint, depth_key, world_to_screen


@dataclass
class IsoTileDef:
    """Visual definition for a tile type.

    A tile definition describes the *appearance* of a single tile kind.
    Sprite selection per-viewpoint is handled by ``sprite_paths``; if the
    viewpoint-specific path is absent the fallback ``sprite_path`` is used.

    Attributes:
        name: Human-readable identifier (e.g. ``"floor"``, ``"wall_n"``).
        sprite_path: Default sprite PNG path — used when a viewpoint-specific
            entry is absent from ``sprite_paths``.
        sprite_paths: Optional per-viewpoint sprite overrides.
        z_height: Visual height of the tile in world-Z units (0 for flat
            floor tiles, positive for walls / raised surfaces).
        passable: Whether entities can occupy this tile.
        color: Fallback solid colour used by placeholder/debug renderers.
    """

    name: str
    sprite_path: str
    sprite_paths: dict[IsoViewpoint, str] = field(default_factory=dict)
    z_height: float = 0.0
    passable: bool = True
    color: tuple[int, int, int] = (128, 128, 128)

    def sprite_for(self, vp: IsoViewpoint) -> str:
        """Return the best sprite path for the given viewpoint."""
        return self.sprite_paths.get(vp, self.sprite_path)


@dataclass
class IsoCell:
    """One cell in the 3D isometric grid.

    Attributes:
        gx: Grid X coordinate.
        gy: Grid Y coordinate.
        gz: Grid Z coordinate (height level, 0 = ground floor).
        tile_def: Visual definition attached to this cell, or ``None`` for
            an empty/air cell.
        entity: The :class:`~playslap.iso.iso_entity.IsoEntity` currently
            occupying this cell, or ``None``.
        z_offset: Fine-grained Z offset within the cell.  Added to ``gz``
            when computing screen position.
    """

    gx: int
    gy: int
    gz: int
    tile_def: IsoTileDef | None = None
    entity: Any = None
    z_offset: float = 0.0


class IsoGrid:
    """3D grid of :class:`IsoCell` objects with depth sorting.

    The grid Z axis is positive *upward*.  ``gz=0`` is the ground floor; each
    successive level sits ``z_scale`` pixels higher on screen.

    Cells are stored in a sparse dictionary keyed by ``(gx, gy, gz)`` so
    large, mostly-empty grids remain memory-efficient.

    Example::

        grid = IsoGrid(width=20, height=20, depth=4)
        floor = IsoTileDef("floor", "assets/floor.png")
        wall  = IsoTileDef("wall",  "assets/wall.png", z_height=32.0, passable=False)

        grid.set_tile(5, 3, 0, floor)
        grid.set_tile(5, 3, 1, wall)

        # In the render loop:
        for cell, sx, sy in grid.sorted_cells(viewpoint, cam_x, cam_y):
            renderer.blit(cell.tile_def.sprite_for(viewpoint), sx, sy)

    Args:
        width: Number of columns (X axis).
        height: Number of rows (Y axis).
        depth: Number of height levels (Z axis).
        tile_w: Tile width in pixels.
        tile_h: Tile height in pixels.
        z_scale: Pixels per Z unit.
    """

    def __init__(
        self,
        width: int,
        height: int,
        depth: int = 8,
        tile_w: int = 64,
        tile_h: int = 32,
        z_scale: float = 16.0,
    ) -> None:
        self.width = width
        self.height = height
        self.depth = depth
        self.tile_w = tile_w
        self.tile_h = tile_h
        self.z_scale = z_scale
        self._cells: dict[tuple[int, int, int], IsoCell] = {}

    # ------------------------------------------------------------------
    # Cell management
    # ------------------------------------------------------------------

    def set_tile(self, gx: int, gy: int, gz: int, tile_def: IsoTileDef) -> IsoCell:
        """Place *tile_def* at grid position (gx, gy, gz).

        If a cell already exists at that position its ``tile_def`` is replaced
        in-place; otherwise a new :class:`IsoCell` is created.

        Returns:
            The :class:`IsoCell` at the given position.
        """
        existing = self._cells.get((gx, gy, gz))
        if existing is not None:
            existing.tile_def = tile_def
            return existing
        cell = IsoCell(gx, gy, gz, tile_def)
        self._cells[(gx, gy, gz)] = cell
        return cell

    def get_cell(self, gx: int, gy: int, gz: int) -> IsoCell | None:
        """Return the cell at (gx, gy, gz), or ``None`` if empty."""
        return self._cells.get((gx, gy, gz))

    def remove_tile(self, gx: int, gy: int, gz: int) -> None:
        """Remove the cell at (gx, gy, gz) if it exists."""
        self._cells.pop((gx, gy, gz), None)

    def top_z(self, gx: int, gy: int) -> int:
        """Return the highest occupied gz at column (gx, gy), or 0 if empty."""
        zs = [k[2] for k in self._cells if k[0] == gx and k[1] == gy]
        return max(zs) if zs else 0

    def all_cells(self) -> list[IsoCell]:
        """Return all non-empty cells in arbitrary order."""
        return list(self._cells.values())

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------

    def world_to_screen(
        self,
        gx: float,
        gy: float,
        gz: float,
        vp: IsoViewpoint,
        cam_x: float = 0.0,
        cam_y: float = 0.0,
    ) -> tuple[float, float]:
        """Project grid coordinates to screen space.

        Thin wrapper around :func:`~playslap.iso.projection.world_to_screen`
        that uses this grid's ``tile_w``, ``tile_h``, and ``z_scale``.
        """
        return world_to_screen(
            gx, gy, gz, vp,
            self.tile_w, self.tile_h, self.z_scale,
            cam_x, cam_y,
        )

    # ------------------------------------------------------------------
    # Depth-sorted rendering list
    # ------------------------------------------------------------------

    def sorted_cells(
        self,
        vp: IsoViewpoint,
        cam_x: float = 0.0,
        cam_y: float = 0.0,
        screen_w: int = 1280,
        screen_h: int = 720,
    ) -> list[tuple[IsoCell, float, float]]:
        """Return cells sorted back-to-front for painter's-algorithm rendering.

        Cells whose projected screen position falls entirely outside the
        viewport (with a generous margin equal to ``tile_w * 2`` horizontally
        and ``tile_h * 4`` vertically) are culled and omitted from the result.

        The grid origin maps to the screen centre (``screen_w/2``,
        ``screen_h/2``).  Callers that use a different origin convention
        should subtract the appropriate offset after calling this method.

        Args:
            vp: Current :class:`~playslap.iso.projection.IsoViewpoint`.
            cam_x: Camera X offset in pixels.
            cam_y: Camera Y offset in pixels.
            screen_w: Viewport width in pixels.
            screen_h: Viewport height in pixels.

        Returns:
            A list of ``(cell, screen_x, screen_y)`` tuples ordered
            back-to-front (draw first → last).
        """
        result: list[tuple[IsoCell, float, float, float]] = []
        margin_x = self.tile_w * 2
        margin_y = self.tile_h * 4
        cx = screen_w / 2
        cy = screen_h / 2

        for cell in self._cells.values():
            sx, sy = self.world_to_screen(
                cell.gx, cell.gy,
                cell.gz + cell.z_offset,
                vp, cam_x, cam_y,
            )
            screen_sx = sx + cx
            screen_sy = sy + cy
            # Frustum cull
            if (
                screen_sx < -margin_x
                or screen_sx > screen_w + margin_x
                or screen_sy < -margin_y
                or screen_sy > screen_h + margin_y
            ):
                continue
            dk = depth_key(cell.gx, cell.gy, cell.gz, vp)
            result.append((cell, screen_sx, screen_sy, dk))

        result.sort(key=lambda x: x[3])
        return [(c, sx, sy) for c, sx, sy, _ in result]
