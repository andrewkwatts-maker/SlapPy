from __future__ import annotations

from typing import Any

from .iso_camera import IsoCamera
from .iso_entity import IsoEntity
from .iso_grid import IsoGrid, IsoTileDef
from .projection import IsoViewpoint, depth_key


class IsoScene:
    """An isometric scene that integrates with the Pharos Engine scene system.

    ``IsoScene`` owns an :class:`~Pharos Engine.iso.iso_grid.IsoGrid`,
    an :class:`~Pharos Engine.iso.iso_camera.IsoCamera`, and a list of
    :class:`~Pharos Engine.iso.iso_entity.IsoEntity` objects.  It can be used
    as a drop-in replacement for the engine's ``Scene`` class wherever the
    engine accepts a scene object.

    The grid tiles and entities are rendered together in correct painter's-
    algorithm order by :meth:`sorted_render_list`.

    Usage::

        scene = IsoScene(grid_w=30, grid_h=30, grid_d=6)

        floor = IsoTileDef("floor", "assets/floor.png")
        wall  = IsoTileDef("wall",  "assets/wall.png", z_height=32.0)
        scene.grid.set_tile(0, 0, 0, floor)
        scene.grid.set_tile(0, 0, 1, wall)

        hero = IsoEntity(grid_x=5.0, grid_y=5.0)
        scene.add_iso_entity(hero)

        scene.camera.rotate_cw()

        # Each frame:
        dt = 1 / 60
        scene.update(dt)
        for item in scene.sorted_render_list():
            if item["type"] == "tile":
                renderer.blit(item["data"].tile_def.sprite_for(scene.camera.viewpoint),
                              item["sx"], item["sy"])
            else:
                renderer.blit(item["data"].sprite, item["sx"], item["sy"])

    Args:
        grid_w: Grid width (number of X columns).
        grid_h: Grid height (number of Y rows).
        grid_d: Grid depth (number of Z levels).
        tile_w: Tile width in pixels.
        tile_h: Tile height in pixels.
        z_scale: Pixels per Z unit.
        viewpoint: Initial camera viewpoint.
    """

    def __init__(
        self,
        grid_w: int = 20,
        grid_h: int = 20,
        grid_d: int = 4,
        tile_w: int = 64,
        tile_h: int = 32,
        z_scale: float = 16.0,
        viewpoint: IsoViewpoint = IsoViewpoint.NE,
    ) -> None:
        self.grid = IsoGrid(grid_w, grid_h, grid_d, tile_w, tile_h, z_scale)
        self.camera = IsoCamera(viewpoint, tile_w, tile_h)
        self.iso_entities: list[IsoEntity] = []

        # Engine-compatible attributes so IsoScene works as a Scene stand-in
        self.entities: list[Any] = []
        self.post_process: list[Any] = []
        self.pixel_physics_enabled: bool = False
        self.fluid: Any = None
        self.strata: Any = None
        self.decals: Any = None
        self.landscape: Any = None
        self.region_effects: list[Any] = []
        self._z_layers: list[Any] = []

    # ------------------------------------------------------------------
    # Entity management
    # ------------------------------------------------------------------

    def add_iso_entity(self, entity: IsoEntity) -> None:
        """Register an :class:`IsoEntity` with this scene."""
        if entity not in self.iso_entities:
            self.iso_entities.append(entity)

    def remove_iso_entity(self, entity: IsoEntity) -> None:
        """Remove an :class:`IsoEntity` from this scene."""
        try:
            self.iso_entities.remove(entity)
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Scene lifecycle
    # ------------------------------------------------------------------

    def update(self, dt: float) -> None:
        """Tick the scene.

        Syncs all iso entity rotations to the current camera viewpoint so
        that the engine's ``AngleSpriteMap`` can select the correct sprite.

        Args:
            dt: Elapsed time in seconds since the last frame.
        """
        self.camera.update_entity_viewpoints(self.iso_entities)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def sorted_render_list(
        self,
        screen_w: int = 1280,
        screen_h: int = 720,
    ) -> list[dict[str, Any]]:
        """Return tiles and entities interleaved in painter's-algorithm order.

        Each element in the returned list is a dict with the keys:

        - ``"type"``: ``"tile"`` or ``"entity"``
        - ``"sx"``: Screen X in pixels (viewport origin = top-left).
        - ``"sy"``: Screen Y in pixels.
        - ``"data"``: The :class:`~Pharos Engine.iso.iso_grid.IsoCell` (tiles)
          or :class:`~Pharos Engine.iso.iso_entity.IsoEntity` (entities).
        - ``"dk"`` *(entities only)*: The raw depth key float.

        Tiles already carry an implicit depth key from
        :meth:`~Pharos Engine.iso.iso_grid.IsoGrid.sorted_cells`; entities are
        re-inserted at the correct position by the final sort.

        Args:
            screen_w: Viewport width in pixels.
            screen_h: Viewport height in pixels.

        Returns:
            A list of render-item dicts ordered back-to-front.
        """
        vp = self.camera.viewpoint
        cam_x = self.camera.cam_x
        cam_y = self.camera.cam_y
        cx = screen_w / 2
        cy = screen_h / 2

        items: list[dict[str, Any]] = []

        # Tiles — already culled and sorted inside sorted_cells
        for cell, sx, sy in self.grid.sorted_cells(vp, cam_x, cam_y, screen_w, screen_h):
            dk = depth_key(cell.gx, cell.gy, cell.gz, vp)
            items.append({
                "type": "tile",
                "sx": sx,
                "sy": sy,
                "dk": dk,
                "data": cell,
            })

        # Entities — project and compute depth key
        for ent in self.iso_entities:
            sx, sy = self.grid.world_to_screen(
                ent.grid_x, ent.grid_y, ent.total_z,
                vp, cam_x, cam_y,
            )
            items.append({
                "type": "entity",
                "sx": sx + cx,
                "sy": sy + cy,
                "dk": depth_key(ent.grid_x, ent.grid_y, ent.total_z, vp),
                "data": ent,
            })

        items.sort(key=lambda x: x["dk"])
        return items

    # ------------------------------------------------------------------
    # Z-layer API (engine compatibility shim)
    # ------------------------------------------------------------------

    @property
    def z_layers(self) -> list[Any]:
        return self._z_layers

    def add_z_layer(self, layer: Any) -> None:
        self._z_layers.append(layer)
        self._z_layers.sort(key=lambda l: l.z)

    def remove_z_layer(self, layer: Any) -> None:
        if layer in self._z_layers:
            self._z_layers.remove(layer)
