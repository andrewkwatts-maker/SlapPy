from __future__ import annotations
from dataclasses import dataclass
from enum import IntEnum


class IsoViewpoint(IntEnum):
    NE = 0
    NW = 1
    SW = 2
    SE = 3


@dataclass(frozen=True)
class ViewpointTransform:
    xx: int
    xy: int
    yx: int
    yy: int
    depth_sign: int  # 1 or -1 to make depth_key always "smaller = further back"


TRANSFORMS: dict[IsoViewpoint, ViewpointTransform] = {
    IsoViewpoint.NE: ViewpointTransform( 1, -1,  1,  1,  1),
    IsoViewpoint.NW: ViewpointTransform(-1, -1,  1, -1,  1),
    IsoViewpoint.SW: ViewpointTransform(-1,  1, -1, -1, -1),
    IsoViewpoint.SE: ViewpointTransform( 1,  1, -1,  1,  1),
}


def world_to_screen(
    gx: float,
    gy: float,
    gz: float,
    vp: IsoViewpoint,
    tile_w: int = 64,
    tile_h: int = 32,
    z_scale: float = 16.0,
    cam_x: float = 0.0,
    cam_y: float = 0.0,
) -> tuple[float, float]:
    """Project a 3D grid coordinate to screen space.

    The returned (sx, sy) is relative to the map origin (screen centre by
    convention).  Subtract ``cam_x`` / ``cam_y`` to apply the camera offset.

    Args:
        gx: Grid X position.
        gy: Grid Y position.
        gz: Grid Z position (height).  Positive values go *up* on screen.
        vp: Active :class:`IsoViewpoint`.
        tile_w: Tile width in pixels (default 64).
        tile_h: Tile height in pixels (default 32).
        z_scale: Pixels per Z unit (default 16).
        cam_x: Camera X offset in pixels.
        cam_y: Camera Y offset in pixels.

    Returns:
        ``(screen_x, screen_y)`` in pixels relative to the map origin.
    """
    t = TRANSFORMS[vp]
    hw, hh = tile_w / 2, tile_h / 2
    sx = (t.xx * gx + t.xy * gy) * hw - cam_x
    sy = (t.yx * gx + t.yy * gy) * hh - gz * z_scale - cam_y
    return sx, sy


def screen_to_world(
    sx: float,
    sy: float,
    vp: IsoViewpoint,
    tile_w: int = 64,
    tile_h: int = 32,
    cam_x: float = 0.0,
    cam_y: float = 0.0,
) -> tuple[int, int]:
    """Pick the ground plane (gz=0) and return the nearest grid (gx, gy).

    Uses Cramer's rule on the 2×2 projection system.  If the determinant of
    the viewpoint matrix is zero (degenerate transform) the function returns
    ``(0, 0)``.

    Args:
        sx: Screen X coordinate in pixels, relative to map origin.
        sy: Screen Y coordinate in pixels, relative to map origin.
        vp: Active :class:`IsoViewpoint`.
        tile_w: Tile width in pixels.
        tile_h: Tile height in pixels.
        cam_x: Camera X offset in pixels.
        cam_y: Camera Y offset in pixels.

    Returns:
        ``(gx, gy)`` as rounded integer grid coordinates.
    """
    t = TRANSFORMS[vp]
    hw, hh = tile_w / 2, tile_h / 2
    # Undo camera offset, then normalise to half-tile units
    rx = (sx + cam_x) / hw
    ry = (sy + cam_y) / hh
    det = t.xx * t.yy - t.xy * t.yx
    if det == 0:
        return 0, 0
    gx = (t.yy * rx - t.xy * ry) / det
    gy = (-t.yx * rx + t.xx * ry) / det
    return round(gx), round(gy)


def depth_key(gx: float, gy: float, gz: float, vp: IsoViewpoint) -> float:
    """Compute a scalar depth key for painter's-algorithm ordering.

    Lower values are further from the camera and must be drawn first.

    The primary component is the isometric "row" of the tile projected through
    the viewpoint matrix, scaled by ``depth_sign`` so that the convention
    (smaller = further back) holds for all four viewpoints.  ``gz`` is added
    as a fractional tie-breaker so that lower floors are drawn before higher
    ones within the same tile column.

    Args:
        gx: Grid X position.
        gy: Grid Y position.
        gz: Grid Z position.
        vp: Active :class:`IsoViewpoint`.

    Returns:
        A float suitable for use as a sort key.
    """
    t = TRANSFORMS[vp]
    base = (t.yx * gx + t.yy * gy) * t.depth_sign
    return base + gz * 0.001  # gz as tie-breaker
