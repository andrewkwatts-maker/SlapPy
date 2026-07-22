"""HullCompute — thin facade exposing convex and concave hull computation.

Delegates to :class:`~pharos_engine.compute.library.ComputeLibrary` so both
paths share the same CPU numpy fallback and optional GPU path.

Usage
-----
    from pharos_engine.compute.hull import HullCompute
    import numpy as np

    pts = np.array([[0,0],[1,0],[0,1],[1,1],[0.5,0.5]], dtype=np.float32)
    hull   = HullCompute.convex(pts)          # convex hull vertex indices
    tight  = HullCompute.concave(pts, 0.5)   # tighter alpha-shape
"""
from __future__ import annotations

import numpy as np

from pharos_engine.compute.library import ComputeLibrary


class HullCompute:
    """Façade for convex and concave (alpha-shape) hull computation.

    All methods are static — no instance required.
    """

    @staticmethod
    def convex(points: np.ndarray) -> np.ndarray:
        """Return the convex hull of *points* as an ordered vertex array.

        Parameters
        ----------
        points:
            ``(N, 2)`` float array of 2-D point coordinates.

        Returns
        -------
        np.ndarray
            ``(M, 2)`` ordered hull vertices (counter-clockwise).
        """
        return ComputeLibrary.convex_hull(points)

    @staticmethod
    def concave(points: np.ndarray, alpha: float = 0.3) -> np.ndarray:
        """Return a concave (alpha-shape) hull of *points*.

        Parameters
        ----------
        points:
            ``(N, 2)`` float array of 2-D point coordinates.
        alpha:
            Concavity parameter.  ``0`` → convex hull; ``1`` → very tight
            wrap around the point set.

        Returns
        -------
        np.ndarray
            ``(M, 2)`` ordered hull vertices.
        """
        return ComputeLibrary.concave_hull(points, alpha)

    @staticmethod
    def convex_async(points: np.ndarray, event_name: str = "") -> np.ndarray:
        """Convex hull with optional pub/sub result publication.

        When *event_name* is set and there are active subscribers, publishes
        ``publish(event_name, hull=result)`` after computing.  Mirrors the
        ``RunRule.ON_SUBSCRIBED`` pattern.

        Returns
        -------
        np.ndarray
            Hull vertices, same as :meth:`convex`.
        """
        hull = ComputeLibrary.convex_hull(points)
        if event_name:
            from pharos_engine.event_bus import global_bus, publish
            if global_bus.listener_count(event_name) > 0:
                publish(event_name, publisher=HullCompute, hull=hull)
        return hull

    @staticmethod
    def concave_async(points: np.ndarray, alpha: float = 0.3,
                      event_name: str = "") -> np.ndarray:
        """Concave hull with optional pub/sub result publication.

        Same as :meth:`convex_async` but for alpha-shape.  Published payload
        includes ``hull`` and ``alpha`` fields.
        """
        hull = ComputeLibrary.concave_hull(points, alpha)
        if event_name:
            from pharos_engine.event_bus import global_bus, publish
            if global_bus.listener_count(event_name) > 0:
                publish(event_name, publisher=HullCompute, hull=hull, alpha=alpha)
        return hull
