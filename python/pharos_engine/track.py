"""
SplineTrack — renders a textured road along a CatmullRomSpline.

The road is rasterised once (or on demand) into a PIL RGBA image and stored
as a Layer2D.  The engine uploads it to the GPU as a normal textured entity.

Road layers (painter's order, bottom → top)
-------------------------------------------
1. Asphalt fill quads
2. Optional road texture tiled along the road
3. Red/white alternating kerb strips at each edge
4. Dashed centre line
"""
from __future__ import annotations
import math
from typing import TYPE_CHECKING

from pharos_engine.asset import Asset
from pharos_engine.layer import Layer

if TYPE_CHECKING:
    from pharos_engine.spline import CatmullRomSpline


class SplineTrack(Asset):
    """A driveable road surface drawn along a spline.

    Parameters
    ----------
    spline:
        The centreline path.
    width:
        Total road width in pixels (kerb to kerb).
    canvas_size:
        Output texture size — match your window resolution.
    road_color:
        RGBA asphalt fill colour.
    kerb_colors:
        Two alternating RGBA colours for the kerb strips.
    line_color:
        RGBA colour for the centre dashes.
    texture_path:
        Optional PNG road texture.  Tiled along the road longitudinally.
    segments:
        Quad resolution along the spline.  200 is smooth enough for most tracks.
    """

    def __init__(
        self,
        spline: "CatmullRomSpline",
        width: float = 120.0,
        canvas_size: tuple[int, int] = (1280, 720),
        road_color: tuple[int, int, int, int] = (52, 48, 44, 255),
        kerb_colors: tuple[tuple, tuple] = (
            (190, 28, 28, 255),
            (240, 240, 240, 255),
        ),
        line_color: tuple[int, int, int, int] = (230, 215, 55, 255),
        texture_path: str | None = None,
        segments: int = 240,
    ):
        super().__init__(name="SplineTrack", position=(0.0, 0.0))
        self.spline       = spline
        self.road_width   = width
        self.canvas_size  = canvas_size
        self.road_color   = road_color
        self.kerb_colors  = kerb_colors
        self.line_color   = line_color
        self.texture_path = texture_path
        self.segments     = segments
        self.z_height     = 0.0
        self._road_tex    = None

        if texture_path:
            self._load_texture(texture_path)

        self._layer = Layer.blank(canvas_size[0], canvas_size[1], name="road")
        self.add_layer(self._layer)
        self.rebuild()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def rebuild(self) -> None:
        """Re-rasterise the track.  Call after editing spline points."""
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            return

        img  = Image.new("RGBA", self.canvas_size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        self._draw_road(draw, img)

        import numpy as np
        arr = np.asarray(img, dtype=np.uint8)
        self._layer._image_data[:] = arr

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_texture(self, path: str) -> None:
        try:
            from PIL import Image
            self._road_tex = Image.open(path).convert("RGBA")
        except Exception:
            self._road_tex = None

    def _edge_points(self) -> tuple[
        list[tuple[float, float]],
        list[tuple[float, float]],
        list[tuple[float, float]],
        list[tuple[float, float]],
        list[tuple[float, float]],
    ]:
        """Compute edge + kerb edge + centre arrays for all samples."""
        kerb   = self.road_width * 0.5
        inner  = kerb - 10.0          # 10 px kerb strip width

        ts      = self.spline.uniform_ts(self.segments)
        lefts, rights       = [], []
        out_l,  out_r       = [], []
        centers             = []

        for t in ts:
            cx, cy = self.spline.sample(t)
            nx, ny = self.spline.normal(t)
            lefts.append(  (cx + nx * inner, cy + ny * inner))
            rights.append( (cx - nx * inner, cy - ny * inner))
            out_l.append(  (cx + nx * kerb,  cy + ny * kerb ))
            out_r.append(  (cx - nx * kerb,  cy - ny * kerb ))
            centers.append((cx, cy))

        return lefts, rights, out_l, out_r, centers

    def _draw_road(self, draw, img) -> None:
        n = self.segments
        lefts, rights, out_l, out_r, centers = self._edge_points()

        # ---- 1. Asphalt fill -------------------------------------------
        for i in range(n):
            j = (i + 1) % n
            draw.polygon(
                [lefts[i], lefts[j], rights[j], rights[i]],
                fill=self.road_color,
            )

        # ---- 2. Road texture (optional) --------------------------------
        if self._road_tex is not None:
            self._tile_texture(img, lefts, rights, n)

        # ---- 3. Kerb strips --------------------------------------------
        for i in range(n):
            j   = (i + 1) % n
            kc  = self.kerb_colors[(i // 4) % 2]
            draw.polygon([out_l[i], out_l[j], lefts[j],  lefts[i]],  fill=kc)
            draw.polygon([rights[i], rights[j], out_r[j], out_r[i]], fill=kc)

        # ---- 4. Centre dashes ------------------------------------------
        dash_len    = 28.0
        gap_len     = 18.0
        cycle_len   = dash_len + gap_len
        acc         = 0.0
        prev        = centers[0]

        for i in range(1, n + 1):
            curr    = centers[i % n]
            seg_len = math.hypot(curr[0] - prev[0], curr[1] - prev[1])

            # Walk through this segment in tiny steps to track dash phase
            steps   = max(1, int(seg_len))
            for s in range(steps):
                frac = s / steps
                px   = prev[0] + (curr[0] - prev[0]) * frac
                py   = prev[1] + (curr[1] - prev[1]) * frac
                nx   = prev[0] + (curr[0] - prev[0]) * (frac + 1.0 / steps)
                ny   = prev[1] + (curr[1] - prev[1]) * (frac + 1.0 / steps)
                phase = acc % cycle_len
                if phase < dash_len:
                    draw.line([(px, py), (nx, ny)], fill=self.line_color, width=3)
                acc += seg_len / steps

            prev = curr

    def _tile_texture(self, img, lefts, rights, n) -> None:
        """Paste the road texture across the road surface using affine mapping."""
        try:
            from PIL import Image
        except ImportError:
            return
        if self._road_tex is None:
            return

        tw, th = self._road_tex.size
        tile_step = th  # advance one texture-height per tile

        acc_v = 0.0  # longitudinal texture coordinate accumulator
        for i in range(n):
            j       = (i + 1) % n
            # Approximate segment length for UV stepping
            seg_len = math.hypot(
                lefts[j][0] - lefts[i][0],
                lefts[j][1] - lefts[i][1],
            )
            # Road-width in pixels → tile horizontally
            road_w  = math.hypot(
                rights[i][0] - lefts[i][0],
                rights[i][1] - lefts[i][1],
            )
            if road_w < 1:
                continue

            u0 = int(acc_v) % th
            u1 = int(acc_v + seg_len) % th
            if u1 <= u0:
                u1 = u0 + 1

            strip  = self._road_tex.crop((0, u0, tw, u1))
            # Resize strip to match segment dimensions (approx.)
            try:
                strip_r = strip.resize((max(1, int(road_w)), max(1, u1 - u0)),
                                       Image.BILINEAR)
            except Exception:
                acc_v += seg_len
                continue

            # Paste at the left edge of this segment (rough but fast)
            px = int(lefts[i][0])
            py = int(lefts[i][1]) - strip_r.height // 2
            try:
                img.paste(strip_r, (px, py), strip_r)
            except Exception:
                pass

            acc_v += seg_len
