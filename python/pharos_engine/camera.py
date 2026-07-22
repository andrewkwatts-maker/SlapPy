from __future__ import annotations
import math

from pharos_engine._camera_validation import (
    validate_finite_2tuple,
    validate_follow_target,
    validate_lerp,
    validate_positive_finite_float,
    validate_positive_finite_or_none,
)


class Camera:
    def __init__(self, position: tuple[float, float] = (0.0, 0.0),
                 zoom: float = 1.0):
        """Construct a camera.

        Raises
        ------
        TypeError
            If ``position`` is not a 2-element sequence of real numbers, or
            ``zoom`` is not a real number.
        ValueError
            If ``position`` elements are NaN/inf, the sequence has wrong
            length, or ``zoom <= 0`` / NaN / inf.
        """
        # Bypass the property setters so we run validation once with the
        # constructor-frame fn-name in error messages.
        self._position: tuple[float, float] = validate_finite_2tuple(
            "position", "Camera", position,
        )
        self._zoom: float = validate_positive_finite_float(
            "zoom", "Camera", zoom,
        )
        self._viewport_size: tuple[int, int] = (800, 600)  # updated by engine

    @property
    def position(self) -> tuple[float, float]:
        return self._position

    @position.setter
    def position(self, value: tuple[float, float]) -> None:
        """Set the camera centre (world-space pixels).

        Raises
        ------
        TypeError
            If ``value`` is not a 2-element sequence of real numbers.
        ValueError
            If ``value`` has wrong length or contains NaN/inf.
        """
        self._position = validate_finite_2tuple(
            "position", "Camera.position", value,
        )

    @property
    def zoom(self) -> float:
        return self._zoom

    @zoom.setter
    def zoom(self, value: float) -> None:
        """Set the camera zoom factor (>0; >1 zooms in, <1 zooms out).

        Raises
        ------
        TypeError
            If ``value`` is not a real number.
        ValueError
            If ``value <= 0``, NaN, or inf.
        """
        self._zoom = validate_positive_finite_float(
            "zoom", "Camera.zoom", value,
        )

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

        Raises:
            TypeError: if ``entity`` lacks ``.position``, or ``lerp`` /
                ``screen_w`` / ``screen_h`` are not real numbers.
            ValueError: if ``lerp`` is not in ``(0, 1]``, ``screen_w`` /
                ``screen_h`` are NaN/inf/≤0, or ``entity.position`` contains
                NaN/inf.
        """
        validate_follow_target("entity", "Camera.follow", entity)
        lerp = validate_lerp("lerp", "Camera.follow", lerp)
        sw_v = validate_positive_finite_or_none(
            "screen_w", "Camera.follow", screen_w,
        )
        sh_v = validate_positive_finite_or_none(
            "screen_h", "Camera.follow", screen_h,
        )
        vw, vh = self._viewport_size
        sw = sw_v if sw_v is not None else vw
        sh = sh_v if sh_v is not None else vh

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
