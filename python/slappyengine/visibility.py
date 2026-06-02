"""
VisibilityField — general spatial visibility / fog-of-war.
Game-specific: CheckpointSystem, stealth detection, etc. wrap this.
No game concepts (no "players", "enemies", "fog") in this file.
"""
from __future__ import annotations
import math
import numpy as np
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class VisibilityObserver:
    """An entity that contributes to the visibility field."""
    entity: object                  # any object with .position
    range: float = 200.0            # max sight distance in world pixels
    mode: str = "circle"            # "circle" | "convex_hull" | "concave_hull" | "cone"
    cone_angle: float = 360.0       # degrees; < 360 = directional (uses entity.heading or .rotation)
    hull_alpha: float = 0.3         # concave hull tightness (0=convex, 1=very tight)
    occluders: list = field(default_factory=list)  # Layer2D objects blocking LOS
    # (occluders: alpha channel used as solid wall mask)


class VisibilityField:
    """
    A 2D float32 field (0..1 per pixel) representing how visible each point is.
    Updated each tick from observer hulls.

    Sampling:
        vis_field.sample((x, y)) → 0.0 (hidden) to 1.0 (fully visible)

    As a Layer (for post-process / NodeGraph):
        vis_field.get_layer() → Layer2D (alpha = visibility)

    Parameters:
        size: (width, height) of the visibility texture in pixels
        blend_radius: soft edge feather — 0=hard cutoff, 50=very gradual fade
        overlap_mode: "max" = any observer sees it (union);
                      "add" = brightness proportional to observer count;
                      "intersect" = all must see it
        decay_rate: 0.0 = permanent reveal; 0.5 = fast fade back to hidden
    """

    def __init__(self, size: tuple[int, int],
                 blend_radius: float = 20.0,
                 overlap_mode: str = "max",
                 decay_rate: float = 0.0):
        self._w, self._h = size
        self.blend_radius = blend_radius
        self.overlap_mode = overlap_mode
        self.decay_rate = decay_rate

        self._field = np.zeros((self._h, self._w), dtype=np.float32)
        self._observers: dict[int, VisibilityObserver] = {}
        self._obs_counter = 0
        self._layer_cache = None   # cached Layer2D

    def add_observer(self, obs: VisibilityObserver) -> int:
        """Add a visibility observer. Returns handle for removal."""
        self._obs_counter += 1
        self._observers[self._obs_counter] = obs
        return self._obs_counter

    def remove_observer(self, handle: int) -> None:
        self._observers.pop(handle, None)

    def update(self) -> None:
        """
        Recompute visibility field from all observers.
        Called once per frame.
        """
        if self.overlap_mode == "intersect":
            accumulated = np.ones((self._h, self._w), dtype=np.float32)
        else:
            accumulated = np.zeros((self._h, self._w), dtype=np.float32)

        for obs in self._observers.values():
            obs_vis = self._compute_observer_mask(obs)
            if self.overlap_mode == "max":
                accumulated = np.maximum(accumulated, obs_vis)
            elif self.overlap_mode == "add":
                accumulated = np.clip(accumulated + obs_vis, 0.0, 1.0)
            elif self.overlap_mode == "intersect":
                accumulated = np.minimum(accumulated, obs_vis)

        # Decay: previous revealed areas fade back
        if self.decay_rate > 0.0:
            self._field = np.maximum(
                accumulated,
                self._field * (1.0 - self.decay_rate)
            )
        else:
            # decay_rate=0 → permanent reveal: field only grows, never shrinks
            self._field = np.maximum(accumulated, self._field)

        self._layer_cache = None  # invalidate cache

    def sample(self, world_pos: tuple[float, float]) -> float:
        """Sample visibility at a world position. Returns 0..1."""
        x = int(world_pos[0]) % self._w
        y = int(world_pos[1]) % self._h
        return float(self._field[y, x])

    def get_layer(self):
        """Return a Layer2D where alpha channel = visibility (0..255)."""
        if self._layer_cache is not None:
            return self._layer_cache
        try:
            from slappyengine.layer import Layer2D
            layer = Layer2D.blank(self._w, self._h, name="visibility")
            alpha = (self._field * 255).clip(0, 255).astype(np.uint8)
            layer._image_data[:, :, 3] = alpha
            # White tint for visible, black for hidden
            layer._image_data[:, :, 0] = alpha
            layer._image_data[:, :, 1] = alpha
            layer._image_data[:, :, 2] = alpha
            self._layer_cache = layer
        except Exception:
            self._layer_cache = None
        return self._layer_cache

    def _compute_observer_mask(self, obs: VisibilityObserver) -> np.ndarray:
        """Compute a (H, W) float32 visibility mask for one observer."""
        mask = np.zeros((self._h, self._w), dtype=np.float32)
        pos = getattr(obs.entity, "position", (0.0, 0.0))
        cx, cy = float(pos[0]), float(pos[1])
        r = obs.range

        if obs.mode == "circle":
            self._draw_circle_mask(mask, cx, cy, r, obs)

        elif obs.mode in ("convex_hull", "concave_hull"):
            # Generate points around the observer in a circle
            pts = self._sample_los_points(obs, cx, cy, r)
            if len(pts) >= 3:
                try:
                    from slappyengine.compute.library import ComputeLibrary
                    if obs.mode == "convex_hull":
                        hull_pts = ComputeLibrary.convex_hull(
                            np.array(pts, dtype=np.float32))
                    else:
                        hull_pts = ComputeLibrary.concave_hull(
                            np.array(pts, dtype=np.float32), obs.hull_alpha)
                    self._rasterise_hull(mask, hull_pts, cx, cy, r)
                except Exception:
                    # Fallback to circle
                    self._draw_circle_mask(mask, cx, cy, r, obs)
            else:
                self._draw_circle_mask(mask, cx, cy, r, obs)

        elif obs.mode == "cone":
            heading = getattr(obs.entity, "rotation",
                              getattr(obs.entity, "heading", 0.0))
            self._draw_cone_mask(mask, cx, cy, r, heading, obs.cone_angle, obs)

        # Apply soft edge (Gaussian blur approximation via distance feather)
        if self.blend_radius > 0:
            mask = self._feather(mask, cx, cy, r)

        return mask

    def _draw_circle_mask(self, mask: np.ndarray,
                           cx: float, cy: float, r: float,
                           obs: VisibilityObserver) -> None:
        """Fill circle of radius r centred at (cx,cy) with distance-based falloff."""
        r_sq = r * r
        x0 = max(0, int(cx - r))
        x1 = min(self._w, int(cx + r) + 1)
        y0 = max(0, int(cy - r))
        y1 = min(self._h, int(cy + r) + 1)
        xs = np.arange(x0, x1, dtype=np.float32)
        ys = np.arange(y0, y1, dtype=np.float32)
        xx, yy = np.meshgrid(xs, ys)
        dist_sq = (xx - cx) ** 2 + (yy - cy) ** 2
        inside = dist_sq <= r_sq
        if np.any(inside):
            falloff = np.where(inside,
                               np.clip(1.0 - (dist_sq ** 0.5) / r, 0.0, 1.0), 0.0)
            mask[y0:y1, x0:x1] = np.maximum(mask[y0:y1, x0:x1], falloff)

    def _draw_cone_mask(self, mask: np.ndarray,
                         cx: float, cy: float, r: float,
                         heading_deg: float, cone_angle_deg: float,
                         obs: VisibilityObserver) -> None:
        half = math.radians(cone_angle_deg / 2.0)
        fwd = math.radians(heading_deg)
        x0 = max(0, int(cx - r))
        x1 = min(self._w, int(cx + r) + 1)
        y0 = max(0, int(cy - r))
        y1 = min(self._h, int(cy + r) + 1)
        xs = np.arange(x0, x1, dtype=np.float32)
        ys = np.arange(y0, y1, dtype=np.float32)
        xx, yy = np.meshgrid(xs, ys)
        dx, dy = xx - cx, yy - cy
        dist = np.hypot(dx, dy)
        angle = np.arctan2(dy, dx)
        diff = np.abs(np.arctan2(np.sin(angle - fwd), np.cos(angle - fwd)))
        in_cone = (dist <= r) & (diff <= half)
        falloff = np.where(in_cone, np.clip(1.0 - dist / r, 0.0, 1.0), 0.0)
        mask[y0:y1, x0:x1] = np.maximum(mask[y0:y1, x0:x1], falloff)

    def _sample_los_points(self, obs: VisibilityObserver,
                            cx: float, cy: float, r: float,
                            num_rays: int = 32) -> list[list[float]]:
        """Cast rays and collect hit points (for hull computation)."""
        pts = []
        for i in range(num_rays):
            angle = 2.0 * math.pi * i / num_rays
            # Cone check
            if obs.mode == "cone" and obs.cone_angle < 360.0:
                heading = math.radians(getattr(obs.entity, "rotation",
                                               getattr(obs.entity, "heading", 0.0)))
                half = math.radians(obs.cone_angle / 2.0)
                diff = abs(math.atan2(math.sin(angle - heading),
                                      math.cos(angle - heading)))
                if diff > half:
                    continue
            hit_x = cx + r * math.cos(angle)
            hit_y = cy + r * math.sin(angle)
            # Occluder check (simplified: check midpoint alpha)
            if obs.occluders:
                hit_x, hit_y = self._ray_cast_occluders(
                    cx, cy, hit_x, hit_y, obs.occluders, r)
            pts.append([hit_x, hit_y])
        return pts

    def _ray_cast_occluders(self, sx, sy, ex, ey, occluders, max_r):
        """Simple ray march to find first solid occluder pixel. Returns hit point."""
        steps = int(max_r / 4)
        for s in range(1, steps + 1):
            t = s / steps
            px = int(sx + (ex - sx) * t) % self._w
            py = int(sy + (ey - sy) * t) % self._h
            for occ in occluders:
                try:
                    if occ._image_data is not None:
                        alpha = occ._image_data[py % occ._image_data.shape[0],
                                                 px % occ._image_data.shape[1], 3]
                        if alpha > 200:
                            return sx + (ex - sx) * (s - 1) / steps, \
                                   sy + (ey - sy) * (s - 1) / steps
                except Exception:
                    pass
        return ex, ey

    def _rasterise_hull(self, mask: np.ndarray,
                          hull_pts: np.ndarray, cx: float, cy: float,
                          obs_range: float = 200.0) -> None:
        """Fill the polygon defined by hull_pts into mask."""
        if len(hull_pts) < 3:
            return
        # Scan-line fill using numpy
        hull_pts = np.array(hull_pts, dtype=np.float32)
        xs = hull_pts[:, 0]
        ys = hull_pts[:, 1]
        x0, x1 = max(0, int(xs.min())), min(self._w, int(xs.max()) + 1)
        y0, y1 = max(0, int(ys.min())), min(self._h, int(ys.max()) + 1)
        for py in range(y0, y1):
            crossings = []
            n = len(hull_pts)
            for i in range(n):
                p1 = hull_pts[i]
                p2 = hull_pts[(i + 1) % n]
                if (p1[1] <= py < p2[1]) or (p2[1] <= py < p1[1]):
                    t = (py - p1[1]) / (p2[1] - p1[1] + 1e-9)
                    ix = p1[0] + t * (p2[0] - p1[0])
                    crossings.append(ix)
            crossings.sort()
            for k in range(0, len(crossings) - 1, 2):
                lx = max(x0, int(crossings[k]))
                rx = min(x1, int(crossings[k + 1]) + 1)
                if lx < rx:
                    # Distance falloff from centre
                    pxs = np.arange(lx, rx, dtype=np.float32)
                    dist = np.hypot(pxs - cx,
                                    np.full_like(pxs, py - cy, dtype=np.float32))
                    falloff = np.clip(1.0 - dist / max(obs_range, 1.0), 0.0, 1.0)
                    mask[py, lx:rx] = np.maximum(mask[py, lx:rx], falloff)

    def _feather(self, mask: np.ndarray,
                  cx: float, cy: float, r: float) -> np.ndarray:
        """Apply distance-based soft edge: pixels within blend_radius of boundary fade."""
        # Simple approach: scale down mask near boundary using distance from centre
        if self.blend_radius <= 0:
            return mask
        h, w = mask.shape
        xs = np.arange(w, dtype=np.float32)
        ys = np.arange(h, dtype=np.float32)
        xx, yy = np.meshgrid(xs, ys)
        dist = np.hypot(xx - cx, yy - cy)
        # Feather zone: r-blend_radius to r
        feather_start = r - self.blend_radius
        feather = np.where(dist < feather_start, 1.0,
                   np.where(dist < r,
                            (r - dist) / (self.blend_radius + 1e-9),
                            0.0))
        return mask * feather.astype(np.float32)
