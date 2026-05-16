from __future__ import annotations
import math

class Camera:
    def __init__(self, position: tuple[float, float] = (0.0, 0.0),
                 zoom: float = 1.0):
        self.position: tuple[float, float] = position
        self.zoom: float = zoom
        self._viewport_size: tuple[int, int] = (800, 600)  # updated by engine

    def world_to_screen(self, world: tuple[float, float]) -> tuple[float, float]:
        cx, cy = self.position
        vw, vh = self._viewport_size
        sx = (world[0] - cx) * self.zoom + vw / 2
        sy = (world[1] - cy) * self.zoom + vh / 2
        return (sx, sy)

    def screen_to_world(self, screen: tuple[float, float]) -> tuple[float, float]:
        cx, cy = self.position
        vw, vh = self._viewport_size
        wx = (screen[0] - vw / 2) / self.zoom + cx
        wy = (screen[1] - vh / 2) / self.zoom + cy
        return (wx, wy)

    def visible_rect(self) -> tuple[float, float, float, float]:
        vw, vh = self._viewport_size
        half_w = (vw / 2) / self.zoom
        half_h = (vh / 2) / self.zoom
        cx, cy = self.position
        return (cx - half_w, cy - half_h, cx + half_w, cy + half_h)

    def follow(
        self,
        entity,
        lerp: float = 0.1,
        screen_w: int | None = None,
        screen_h: int | None = None,
    ) -> None:
        """Smoothly track an entity, keeping it centred on screen.

        Call once per frame in the game update.  The camera ``position``
        represents the world-space point shown at the screen centre, so
        ``target = entity.position - screen_size / 2`` in world coords.

        Args:
            entity: Any object with a ``position`` attribute that is a
                2-element sequence ``(x, y)`` in world-space pixels.
            lerp: Interpolation factor per frame (0 < lerp ≤ 1.0).
                ``1.0`` snaps instantly; ``0.1`` gives smooth lag.
            screen_w: Override viewport width in pixels.  Defaults to the
                value stored in ``_viewport_size``.
            screen_h: Override viewport height in pixels.
        """
        vw, vh = self._viewport_size
        sw = screen_w if screen_w is not None else vw
        sh = screen_h if screen_h is not None else vh

        ex, ey = entity.position[0], entity.position[1]
        # target position: entity centred on screen
        tx = ex - sw / 2
        ty = ey - sh / 2

        cx, cy = self.position
        if lerp >= 1.0:
            self.position = (tx, ty)
        else:
            self.position = (
                cx + (tx - cx) * lerp,
                cy + (ty - cy) * lerp,
            )

    def view_matrix(self) -> list[float]:
        # 3x3 affine matrix (column-major, for shader uniform)
        # Translates world -> NDC via camera offset and zoom
        cx, cy = self.position
        vw, vh = self._viewport_size
        s = self.zoom
        # Row-major 4x4 orthographic projection combined with camera transform
        tx = -2.0 * cx * s / vw
        ty = -2.0 * cy * s / vh
        return [
            2.0 * s / vw, 0.0,          0.0, 0.0,
            0.0,          -2.0 * s / vh, 0.0, 0.0,
            0.0,          0.0,           1.0, 0.0,
            tx,           ty,            0.0, 1.0,
        ]
