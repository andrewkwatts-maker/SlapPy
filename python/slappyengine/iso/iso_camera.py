from __future__ import annotations

from .projection import IsoViewpoint, screen_to_world


class IsoCamera:
    """Camera for isometric scenes.

    Tracks a world-space pixel offset (``cam_x``, ``cam_y``) and the active
    :class:`~SlapPyEngine.iso.projection.IsoViewpoint`.  The viewpoint can be
    rotated through the four cardinal directions with :meth:`rotate_cw` and
    :meth:`rotate_ccw`.

    Mouse picking is handled by :meth:`screen_to_grid`, which converts a
    viewport pixel coordinate to the nearest ground-plane grid position.

    Entity viewpoint sync
    ~~~~~~~~~~~~~~~~~~~~~
    When the active viewpoint changes, call :meth:`update_entity_viewpoints`
    to push the new ``rotation`` value to every
    :class:`~SlapPyEngine.iso.iso_entity.IsoEntity` in the scene.  This causes
    the engine's existing ``AngleSpriteMap`` system to select the correct
    per-viewpoint sprite automatically — no changes to the sprite system are
    required.

    Args:
        viewpoint: Initial viewpoint (default :attr:`IsoViewpoint.NE`).
        tile_w: Tile width in pixels.
        tile_h: Tile height in pixels.
    """

    # Maps each viewpoint to the camera *look-direction* angle in degrees.
    # AngleSpriteMap keys are matched against entity.rotation, which is set to
    # (entity._facing_angle + viewpoint_angle) % 360.
    VIEWPOINT_ANGLES: dict[IsoViewpoint, float] = {
        IsoViewpoint.NE:  45.0,
        IsoViewpoint.NW: 135.0,
        IsoViewpoint.SW: 225.0,
        IsoViewpoint.SE: 315.0,
    }

    # Clockwise rotation order
    _CW_ORDER: list[IsoViewpoint] = [
        IsoViewpoint.NE,
        IsoViewpoint.SE,
        IsoViewpoint.SW,
        IsoViewpoint.NW,
    ]

    def __init__(
        self,
        viewpoint: IsoViewpoint = IsoViewpoint.NE,
        tile_w: int = 64,
        tile_h: int = 32,
    ) -> None:
        self.viewpoint: IsoViewpoint = viewpoint
        self.tile_w: int = tile_w
        self.tile_h: int = tile_h
        # Camera offset in pixels.  Positive cam_x pans the view right
        # (world scrolls left); positive cam_y pans it down.
        self.cam_x: float = 0.0
        self.cam_y: float = 0.0

    # ------------------------------------------------------------------
    # Camera movement
    # ------------------------------------------------------------------

    def pan(self, dx: float, dy: float) -> None:
        """Shift the camera by (dx, dy) pixels."""
        self.cam_x += dx
        self.cam_y += dy

    def reset_pan(self) -> None:
        """Return the camera to the grid origin."""
        self.cam_x = 0.0
        self.cam_y = 0.0

    # ------------------------------------------------------------------
    # Viewpoint rotation
    # ------------------------------------------------------------------

    def rotate_cw(self) -> IsoViewpoint:
        """Rotate the viewpoint 90° clockwise and return the new viewpoint."""
        idx = self._CW_ORDER.index(self.viewpoint)
        self.viewpoint = self._CW_ORDER[(idx + 1) % 4]
        return self.viewpoint

    def rotate_ccw(self) -> IsoViewpoint:
        """Rotate the viewpoint 90° counter-clockwise and return the new viewpoint."""
        idx = self._CW_ORDER.index(self.viewpoint)
        self.viewpoint = self._CW_ORDER[(idx - 1) % 4]
        return self.viewpoint

    def set_viewpoint(self, vp: IsoViewpoint) -> None:
        """Directly set the active viewpoint."""
        self.viewpoint = vp

    # ------------------------------------------------------------------
    # Coordinate conversion
    # ------------------------------------------------------------------

    def screen_to_grid(
        self,
        sx: float,
        sy: float,
        screen_w: int = 1280,
        screen_h: int = 720,
    ) -> tuple[int, int]:
        """Convert a mouse/screen pixel position to grid (gx, gy) at gz=0.

        The grid origin is assumed to sit at the screen centre
        (``screen_w/2``, ``screen_h/2``).

        Args:
            sx: Mouse X in viewport pixels (0 = left edge).
            sy: Mouse Y in viewport pixels (0 = top edge).
            screen_w: Viewport width in pixels.
            screen_h: Viewport height in pixels.

        Returns:
            ``(gx, gy)`` as rounded integer grid coordinates.
        """
        # Translate from viewport origin to map-relative origin
        rx = sx - screen_w / 2
        ry = sy - screen_h / 2
        return screen_to_world(
            rx, ry, self.viewpoint,
            self.tile_w, self.tile_h,
            self.cam_x, self.cam_y,
        )

    # ------------------------------------------------------------------
    # AngleSpriteMap integration
    # ------------------------------------------------------------------

    @property
    def angle_deg(self) -> float:
        """Camera look-direction angle in degrees for the active viewpoint."""
        return self.VIEWPOINT_ANGLES[self.viewpoint]

    def update_entity_viewpoints(self, entities: list) -> None:
        """Sync all entity rotations to the current camera viewpoint.

        Sets ``entity.rotation`` on each object in *entities* so that the
        engine's ``AngleSpriteMap`` automatically selects the correct sprite
        for the current view direction.

        For entities that expose a ``_facing_angle`` attribute (their
        intrinsic world-facing direction), the effective rotation is:

        .. code-block:: text

            rotation = (_facing_angle + viewpoint_angle) % 360

        Entities without ``_facing_angle`` are treated as if they face north
        (0°), so ``rotation = viewpoint_angle``.

        Args:
            entities: Iterable of entity objects.  Any object with a
                ``rotation`` attribute is accepted.
        """
        vp_angle = self.angle_deg
        for entity in entities:
            facing = getattr(entity, '_facing_angle', 0.0)
            entity.rotation = (facing + vp_angle) % 360
