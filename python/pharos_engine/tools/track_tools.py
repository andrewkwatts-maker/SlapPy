"""Track rendering and export tools.

All functions require only Pillow + numpy; no wgpu context needed.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    import PIL.Image


# ---------------------------------------------------------------------------
# bake_track_thumbnail
# ---------------------------------------------------------------------------

def bake_track_thumbnail(
    spline,
    size: tuple = (200, 200),
) -> "PIL.Image.Image":
    """Render a SplineTrack as a small PIL image for menu previews.

    Parameters
    ----------
    spline:
        A ``SplineTrack`` or ``CatmullRomSpline`` instance that exposes
        a ``sample_points(n)`` method returning a list of ``(x, y)`` tuples,
        or a ``control_points`` attribute.
    size:
        ``(width, height)`` of the output thumbnail.

    Returns
    -------
    PIL.Image.Image
        RGBA thumbnail image.
    """
    import numpy as np
    from PIL import Image, ImageDraw

    pts = _sample_spline(spline, n=256)
    if not pts:
        img = Image.new("RGBA", size, (30, 30, 30, 255))
        return img

    arr = np.array(pts, dtype=np.float64)
    min_x, min_y = arr[:, 0].min(), arr[:, 1].min()
    max_x, max_y = arr[:, 0].max(), arr[:, 1].max()

    margin = 10
    tw, th = size[0] - margin * 2, size[1] - margin * 2
    range_x = max(max_x - min_x, 1e-6)
    range_y = max(max_y - min_y, 1e-6)

    def _map(x, y):
        nx = margin + (x - min_x) / range_x * tw
        ny = margin + (y - min_y) / range_y * th
        return nx, ny

    img = Image.new("RGBA", size, (20, 20, 25, 255))
    draw = ImageDraw.Draw(img)

    mapped = [_map(x, y) for x, y in pts]
    if len(mapped) >= 2:
        draw.line(mapped, fill=(180, 180, 200, 255), width=3)

    # Mark start point
    sx, sy = mapped[0]
    draw.ellipse((sx - 4, sy - 4, sx + 4, sy + 4), fill=(0, 220, 80, 255))

    return img


# ---------------------------------------------------------------------------
# export_track_boundary
# ---------------------------------------------------------------------------

def export_track_boundary(
    spline,
    width: float,
    out_png: str,
    canvas_size: tuple = (1280, 720),
) -> str:
    """Write an alpha-channel boundary mask used by collision.

    Pixels beyond the kerb edge (outside the track) have alpha=255;
    pixels on the road surface have alpha=0.

    Parameters
    ----------
    spline:
        SplineTrack or CatmullRomSpline instance.
    width:
        Full track width in world units.
    out_png:
        Output PNG path.
    canvas_size:
        ``(canvas_width, canvas_height)`` in pixels.

    Returns
    -------
    str
        Absolute path to the output file.
    """
    import numpy as np
    from PIL import Image, ImageDraw

    pts = _sample_spline(spline, n=512)
    cw, ch = canvas_size

    # Build the road mask: draw filled polyline of width=width onto a canvas
    mask = np.ones((ch, cw), dtype=np.uint8) * 255  # start all "off-road"

    if pts:
        arr = np.array(pts, dtype=np.float64)
        min_x, min_y = arr[:, 0].min(), arr[:, 1].min()
        max_x, max_y = arr[:, 0].max(), arr[:, 1].max()
        margin = int(width * 2)
        tw = cw - margin * 2
        th = ch - margin * 2
        range_x = max(max_x - min_x, 1e-6)
        range_y = max(max_y - min_y, 1e-6)

        def _map(x, y):
            nx = margin + (x - min_x) / range_x * tw
            ny = margin + (y - min_y) / range_y * th
            return nx, ny

        # Pixel width of road
        scale = min(tw / range_x, th / range_y)
        road_px = max(4, int(width * scale))

        road_img = Image.new("L", canvas_size, 255)
        draw = ImageDraw.Draw(road_img)
        mapped = [_map(x, y) for x, y in pts]
        if len(mapped) >= 2:
            draw.line(mapped, fill=0, width=road_px)
        mask = np.array(road_img, dtype=np.uint8)

    # Build RGBA: RGB=0, A=mask
    rgba = np.zeros((ch, cw, 4), dtype=np.uint8)
    rgba[:, :, 3] = mask

    out_file = Path(out_png)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, "RGBA").save(str(out_file))
    return str(out_file.resolve())


# ---------------------------------------------------------------------------
# generate_track_decal_mask
# ---------------------------------------------------------------------------

def generate_track_decal_mask(
    spline,
    width: float,
    margin: float = 20.0,
) -> "np.ndarray":
    """Return a boolean mask array of the road surface area.

    Parameters
    ----------
    spline:
        SplineTrack or CatmullRomSpline instance.
    width:
        Full track width in world units (plus *margin* on each side).
    margin:
        Extra margin in world units added to each side.

    Returns
    -------
    np.ndarray
        Boolean ``(H, W)`` mask where ``True`` = on road.  The array
        is sized to fit the spline with a small border.
    """
    import numpy as np
    from PIL import Image, ImageDraw

    pts = _sample_spline(spline, n=512)
    if not pts:
        return np.zeros((100, 100), dtype=bool)

    arr = np.array(pts, dtype=np.float64)
    min_x, min_y = arr[:, 0].min(), arr[:, 1].min()
    max_x, max_y = arr[:, 0].max(), arr[:, 1].max()

    border = int(width + margin) * 2
    cw = int(max_x - min_x) + border * 2
    ch = int(max_y - min_y) + border * 2

    def _map(x, y):
        nx = (x - min_x) + border
        ny = (y - min_y) + border
        return nx, ny

    road_img = Image.new("L", (cw, ch), 0)
    draw = ImageDraw.Draw(road_img)
    mapped = [_map(x, y) for x, y in pts]
    road_px = max(4, int(width + margin * 2))
    if len(mapped) >= 2:
        draw.line(mapped, fill=255, width=road_px)

    return np.array(road_img, dtype=np.uint8) > 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sample_spline(spline, n: int = 256) -> list[tuple[float, float]]:
    """Extract sample points from a spline/track object."""
    # Try sample_points(n) method
    if hasattr(spline, "sample_points"):
        pts = spline.sample_points(n)
        return [(float(p[0]), float(p[1])) for p in pts]

    # Try evaluate(t) with t in [0, 1]
    if hasattr(spline, "evaluate"):
        result = []
        for i in range(n):
            t = i / max(n - 1, 1)
            p = spline.evaluate(t)
            result.append((float(p[0]), float(p[1])))
        return result

    # Try control_points attribute
    cp = getattr(spline, "control_points", None)
    if cp is not None:
        return [(float(p[0]), float(p[1])) for p in cp]

    # If spline is already a list of points
    if hasattr(spline, "__iter__"):
        try:
            pts = list(spline)
            if pts and hasattr(pts[0], "__len__") and len(pts[0]) >= 2:
                return [(float(p[0]), float(p[1])) for p in pts]
        except Exception:
            pass

    return []
