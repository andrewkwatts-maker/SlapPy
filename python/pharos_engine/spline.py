"""
Catmull-Rom spline — smooth curve that passes through every control point.
Used by SplineTrack and any system needing a parametric path.
"""
from __future__ import annotations
import math
from typing import Sequence


class CatmullRomSpline:
    """Closed or open smooth curve through a sequence of 2-D control points.

    Parameters
    ----------
    points:
        Control points the curve passes through.
    closed:
        If True the last segment connects back to the first point.
    tension:
        Catmull-Rom tension parameter (0 = centripetal, 0.5 = standard).
    """

    def __init__(
        self,
        points: Sequence[tuple[float, float]],
        closed: bool = True,
        tension: float = 0.5,
    ):
        self.points  = list(points)
        self.closed  = closed
        self.tension = tension
        self._total_length: float = 0.0
        self._build_length_table()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sample(self, t: float) -> tuple[float, float]:
        """World position at normalised parameter *t* ∈ [0, 1)."""
        n   = len(self.points)
        seg = int(t * n) % n
        u   = (t * n) - int(t * n)
        return self._cr(seg, u)

    def tangent(self, t: float) -> tuple[float, float]:
        """Normalised tangent (forward direction) at *t*."""
        eps = 1e-4
        a   = self.sample((t - eps) % 1.0)
        b   = self.sample((t + eps) % 1.0)
        dx, dy = b[0] - a[0], b[1] - a[1]
        mag = math.hypot(dx, dy) or 1.0
        return dx / mag, dy / mag

    def normal(self, t: float) -> tuple[float, float]:
        """Left-perpendicular (90° CCW from tangent) at *t*."""
        tx, ty = self.tangent(t)
        return -ty, tx

    def length(self) -> float:
        """Approximate total arc length."""
        return self._total_length

    def uniform_samples(self, count: int) -> list[tuple[float, float]]:
        """Return *count* world positions at equal-t intervals."""
        return [self.sample(i / count) for i in range(count)]

    def uniform_ts(self, count: int) -> list[float]:
        """Return *count* t-values approximately equally spaced by arc length."""
        if self._total_length == 0 or count == 0:
            return [i / max(count, 1) for i in range(count)]

        target_step  = self._total_length / count
        ts: list[float] = []
        acc          = 0.0
        next_target  = 0.0
        steps        = max(500, count * 4)
        prev         = self.sample(0.0)

        for i in range(1, steps + 1):
            t    = i / steps
            curr = self.sample(t)
            acc += math.hypot(curr[0] - prev[0], curr[1] - prev[1])
            while acc >= next_target - 1e-9 and len(ts) < count:
                ts.append(t)
                next_target += target_step
            prev = curr

        while len(ts) < count:
            ts.append(1.0)
        return ts[:count]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_length_table(self) -> None:
        steps = max(300, len(self.points) * 50)
        prev  = self.sample(0.0)
        total = 0.0
        for i in range(1, steps + 1):
            curr   = self.sample(i / steps)
            total += math.hypot(curr[0] - prev[0], curr[1] - prev[1])
            prev   = curr
        self._total_length = total

    def _cr(self, seg: int, t: float) -> tuple[float, float]:
        n  = len(self.points)
        p0 = self.points[(seg - 1) % n]
        p1 = self.points[seg % n]
        p2 = self.points[(seg + 1) % n]
        p3 = self.points[(seg + 2) % n]
        a  = self.tension

        def _interp(v0: float, v1: float, v2: float, v3: float) -> float:
            t2, t3 = t * t, t * t * t
            return (
                (-a*v0 + (2 - a)*v1 + (a - 2)*v2 +  a*v3) * t3 +
                (2*a*v0 + (a - 4)*v1 + (4 - 2*a)*v2 - a*v3) * t2 +
                (-a*v0 + a*v2) * t +
                v1
            )

        return _interp(p0[0], p1[0], p2[0], p3[0]), _interp(p0[1], p1[1], p2[1], p3[1])
