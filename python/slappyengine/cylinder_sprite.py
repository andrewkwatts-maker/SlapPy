"""Cylinder-sprite renderer for tire / wheel visuals.

Game scripts (Ochema Circuit's vehicle.py) consume two symbols:

* :class:`WarpMode` — enum for the warp geometry (currently CIRCLE only).
* :class:`CylinderSpriteRenderer` — wraps a tread-strip texture, scrolls
  it as a function of angular velocity, and warps it to a cylinder shape
  on screen.

The original implementation was a per-frame GPU compute pass. This is a
HEADLESS / SCRIPTING-LAYER shim: it tracks rotation state per-frame so
games run without crashing in test environments where the GPU isn't
active. The actual cylinder-warp visual ships when the real GPU path
is built (or via the rebuild renderer's textured rasterisation).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class WarpMode(Enum):
    """How the tread strip wraps onto the cylinder face."""
    CIRCLE = "circle"      # canonical: strip wraps around circumference
    FLAT = "flat"          # no warp; strip drawn as a flat rectangle
    COMPRESSED = "compressed"  # Y-axis compression for parallax illusion


@dataclass
class CylinderSpriteRenderer:
    """Tire / wheel sprite renderer with rolling-tread scroll.

    Construct with a tread-strip texture (RGBA numpy array). Per frame,
    call :meth:`rotate` with the wheel's angular velocity to advance
    the visible tread offset; the renderer also tracks total rotation
    in radians for serialization / debugging.

    Public attributes used by external code:
        * ``_radius_px`` — read by callers that want to derive
          angular velocity from a linear ground speed.
        * ``angle`` — current rotation in radians (mod 2π).
        * ``scroll`` — current tread strip offset in [0, 1).
    """
    texture: Any
    display_w: int = 16
    display_h: int = 24
    radius_px: float = 7.0
    warp_mode: WarpMode = WarpMode.CIRCLE
    warp_strength: float = 1.0
    angle: float = 0.0
    scroll: float = 0.0
    clip_offset: float = 0.0

    def __post_init__(self) -> None:
        # Public radius alias the engine math reads from; underscore alias
        # for the original Ochema convention.
        self._radius_px = float(self.radius_px)

    def rotate(self, angular_vel: float, dt: float) -> None:
        """Advance the rotation by ``angular_vel * dt`` radians.

        Mirrors `angle` to `clip_offset` as a normalised [0, 1) fraction
        of one revolution — the texture-clipping pipeline reads this to
        offset the tread strip in U.
        """
        import math
        self.angle = (self.angle + float(angular_vel) * float(dt)) % (2.0 * math.pi)
        # tread strip scroll wraps once per full revolution
        self.scroll = (self.angle / (2.0 * math.pi)) % 1.0
        self.clip_offset = self.scroll

    def set_speed(self, linear_speed: float, dt: float) -> None:
        """Derive angular velocity from a linear ground speed."""
        if self._radius_px <= 0.0:
            return
        self.rotate(float(linear_speed) / self._radius_px, dt)

    def render(self, dest: Any, center: tuple[float, float]) -> None:
        """Paint the cylinder sprite into ``dest`` at ``center``.

        No-op stub — the headless shim doesn't draw. Real visual output
        is produced by the rebuild renderer's textured rasterisation
        (see ``slappyengine.softbody.render._draw_texture_deform``).
        """


__all__ = ["WarpMode", "CylinderSpriteRenderer"]
