"""
ComputeLibrary — unified facade over all engine GPU/CPU compute utilities.
CPU fallbacks allow headless use (tests, tools) without a wgpu context.
"""
from __future__ import annotations

import math
import numpy as np


class ComputeLibrary:
    """Facade exposing GPU/CPU compute utilities with numpy CPU fallbacks.

    All methods are classmethods so no instance is needed.  GPU paths are
    invoked only when a wgpu context has been registered via
    ``ComputeLibrary.set_context()``.
    """

    _gpu_context = None
    _stats_compute = None
    _spatial_compute = None
    # Maps shader name → WGSL source string for shaders registered at runtime.
    _registry: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Context registration
    # ------------------------------------------------------------------

    @classmethod
    def set_context(cls, ctx, stats: "StatsCompute | None" = None,
                    spatial: "SpatialCompute | None" = None) -> None:
        """Register a live GPU context and optional compute helpers."""
        cls._gpu_context = ctx
        cls._stats_compute = stats
        cls._spatial_compute = spatial

    # ------------------------------------------------------------------
    # Shader registry
    # ------------------------------------------------------------------

    @classmethod
    def register(cls, name: str, source: str) -> None:
        """Register a named WGSL compute shader source string.

        Parameters
        ----------
        name:
            Unique identifier for this shader (e.g. ``"fluid_advect"``).
        source:
            WGSL source code.
        """
        cls._registry[name] = source

    @classmethod
    def list_registered(cls) -> list[str]:
        """Return names of all registered compute shaders."""
        return list(cls._registry.keys())

    # ------------------------------------------------------------------
    # reduce
    # ------------------------------------------------------------------

    @classmethod
    def reduce(cls, data: np.ndarray, op: str = "max") -> float:
        """Reduce *data* to a scalar using *op*.

        Parameters
        ----------
        data:
            Flat or multi-dimensional float array.
        op:
            One of ``"min"``, ``"max"``, ``"sum"``, ``"mean"``, ``"std"``.

        Returns
        -------
        float
            Scalar result of the reduction.
        """
        arr = np.asarray(data, dtype=np.float64).ravel()
        if arr.size == 0:
            return 0.0

        ops = {
            "min":  lambda a: float(np.min(a)),
            "max":  lambda a: float(np.max(a)),
            "sum":  lambda a: float(np.sum(a)),
            "mean": lambda a: float(np.mean(a)),
            "std":  lambda a: float(np.std(a)),
        }
        if op not in ops:
            raise ValueError(
                f"Unknown op {op!r}. Valid ops: {list(ops)}"
            )
        return ops[op](arr)

    # ------------------------------------------------------------------
    # convex_hull
    # ------------------------------------------------------------------

    @classmethod
    def convex_hull(cls, points: np.ndarray) -> np.ndarray:
        """Return the CCW convex hull of *points*.

        Parameters
        ----------
        points:
            ``(N, 2)`` float32/float64 array of 2-D points.

        Returns
        -------
        np.ndarray
            ``(M, 2)`` array of CCW hull vertices.
        """
        pts = np.asarray(points, dtype=np.float64)
        if pts.ndim != 2 or pts.shape[1] != 2:
            raise ValueError("points must be shape (N, 2)")
        if len(pts) < 3:
            return pts.copy()

        # Try scipy first (accurate and fast)
        try:
            from scipy.spatial import ConvexHull
            hull = ConvexHull(pts)
            # ConvexHull.vertices are in CCW order for 2-D
            hull_pts = pts[hull.vertices]
            return hull_pts.astype(np.float32)
        except ImportError:
            pass
        except Exception:
            # Degenerate input (collinear points, etc.) — fall through to CPU path
            pass

        # Pure-numpy Andrew's monotone chain (handles degenerate/collinear cases)
        sorted_pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]
        return np.array(_monotone_chain(sorted_pts), dtype=np.float32)

    # ------------------------------------------------------------------
    # concave_hull (alpha-shape)
    # ------------------------------------------------------------------

    @classmethod
    def concave_hull(cls, points: np.ndarray, alpha: float = 0.3) -> np.ndarray:
        """Compute an alpha-shape (concave hull) of *points*.

        Parameters
        ----------
        points:
            ``(N, 2)`` float32/float64 array.
        alpha:
            Shape parameter.  ``0`` ≈ convex hull; ``1`` ≈ very tight shape.
            Internally ``alpha`` is scaled to a circumradius threshold of
            ``1 / max(alpha, 1e-9)``.

        Returns
        -------
        np.ndarray
            ``(M, 2)`` boundary vertices in approximate CCW order.
            Falls back to convex hull when Delaunay fails or alpha is too
            small to remove any triangles.
        """
        pts = np.asarray(points, dtype=np.float64)
        if pts.ndim != 2 or pts.shape[1] != 2:
            raise ValueError("points must be shape (N, 2)")
        if len(pts) < 4:
            return cls.convex_hull(pts)

        try:
            from scipy.spatial import Delaunay
        except ImportError:
            # No scipy — fall back to convex hull
            return cls.convex_hull(pts)

        tri = Delaunay(pts)
        radius_threshold = 1.0 / max(alpha, 1e-9)

        # Collect edges of triangles whose circumradius < threshold
        boundary_edges: dict[tuple, int] = {}
        for simplex in tri.simplices:
            ia, ib, ic = simplex
            pa, pb, pc = pts[ia], pts[ib], pts[ic]
            cr = _circumradius(pa, pb, pc)
            if cr < radius_threshold:
                for edge in ((ia, ib), (ib, ic), (ic, ia)):
                    key = (min(edge), max(edge))
                    boundary_edges[key] = boundary_edges.get(key, 0) + 1

        # Keep only edges shared by exactly one triangle (boundary)
        outer = [e for e, cnt in boundary_edges.items() if cnt == 1]
        if not outer:
            return cls.convex_hull(pts)

        # Chain edges into an ordered polygon
        adj: dict[int, list[int]] = {}
        for a, b in outer:
            adj.setdefault(a, []).append(b)
            adj.setdefault(b, []).append(a)

        start = outer[0][0]
        path = [start]
        visited = {start}
        current = start
        while True:
            neighbours = [n for n in adj.get(current, []) if n not in visited]
            if not neighbours:
                break
            current = neighbours[0]
            path.append(current)
            visited.add(current)

        return pts[path].astype(np.float32)

    # ------------------------------------------------------------------
    # reduce_field
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # reduce_async — ON_SUBSCRIBED ComputePass pattern
    # ------------------------------------------------------------------

    @classmethod
    def reduce_async(cls, data: np.ndarray, op: str = "max",
                     event_name: str = "") -> float:
        """Reduce *data* synchronously and publish the result to *event_name*.

        When *event_name* is set and at least one subscriber is listening, the
        scalar result is published as ``publish(event_name, result=value)``.
        This mirrors the ``RunRule.ON_SUBSCRIBED`` pattern: the computation only
        publishes when something is listening.

        Parameters
        ----------
        data:
            Flat or multi-dimensional float array.
        op:
            Reduction operation — same as :meth:`reduce`.
        event_name:
            Dot-path event to publish the result on (optional).

        Returns
        -------
        float
            Scalar result regardless of subscriber count.
        """
        result = cls.reduce(data, op)
        if event_name:
            from slappyengine.event_bus import global_bus, publish
            if global_bus.listener_count(event_name) > 0:
                publish(event_name, publisher=cls, result=result, op=op)
        return result

    # ------------------------------------------------------------------
    # reduce_field (existing, unchanged)
    # ------------------------------------------------------------------

    @classmethod
    def reduce_field(cls, layer, field: str = "alpha", op: str = "mean") -> float:
        """Reduce a named channel from a Layer2D image or data array.

        Parameters
        ----------
        layer:
            A ``Layer2D`` instance or any object with ``_image_data``
            (``H × W × 4`` uint8 RGBA) or ``_data_array``.
        field:
            Named channel.  For RGBA images: ``"r"``=0, ``"g"``=1,
            ``"b"``=2, ``"alpha"``=3.  For structured arrays the field
            name is used directly.
        op:
            Reduction op — same as :meth:`reduce`.

        Returns
        -------
        float
        """
        # Named channel index map for RGBA images
        _rgba_map = {"r": 0, "g": 1, "b": 2, "alpha": 3, "a": 3}

        # Try _image_data first (H×W×4 uint8 RGBA)
        img = getattr(layer, "_image_data", None)
        if img is not None and isinstance(img, np.ndarray) and img.ndim == 3:
            ch_idx = _rgba_map.get(field.lower())
            if ch_idx is not None and img.shape[2] > ch_idx:
                channel = img[:, :, ch_idx].astype(np.float64)
                return cls.reduce(channel, op)

        # Try _data_array (structured or plain ndarray)
        arr = getattr(layer, "_data_array", None)
        if arr is not None and isinstance(arr, np.ndarray):
            if arr.dtype.names and field in arr.dtype.names:
                return cls.reduce(arr[field].ravel().astype(np.float64), op)
            # Plain ndarray — try _rgba_map index
            ch_idx = _rgba_map.get(field.lower())
            if ch_idx is not None and arr.ndim >= 2 and arr.shape[-1] > ch_idx:
                channel = arr[..., ch_idx].astype(np.float64)
                return cls.reduce(channel, op)

        raise AttributeError(
            f"layer has no usable _image_data or _data_array for field {field!r}"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _monotone_chain(sorted_pts: np.ndarray) -> list:
    """Andrew's monotone chain — returns CCW hull vertices."""
    lower: list = []
    for p in sorted_pts:
        while len(lower) >= 2 and _cross2d(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list = []
    for p in reversed(sorted_pts):
        while len(upper) >= 2 and _cross2d(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    return hull


def _cross2d(o, a, b) -> float:
    return float((a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]))


def _circumradius(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """Circumradius of the triangle formed by three 2-D points."""
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    cx, cy = float(c[0]), float(c[1])
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return math.inf
    ux = ((ax*ax + ay*ay) * (by - cy) + (bx*bx + by*by) * (cy - ay)
          + (cx*cx + cy*cy) * (ay - by)) / d
    uy = ((ax*ax + ay*ay) * (cx - bx) + (bx*bx + by*by) * (ax - cx)
          + (cx*cx + cy*cy) * (bx - ax)) / d
    return math.sqrt((ax - ux)**2 + (ay - uy)**2)
