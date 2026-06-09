"""Animation curves: Hermite keyframes, cubic Bezier, Catmull-Rom, easing.

All curves are pure Python + ``math`` — no numpy dependency, so they
import cleanly in the no-arithma degraded mode and are cheap to call from
hot animation paths (each ``.sample`` is O(1) once the segment is
located).

Coordinate convention: time ``t`` is a finite real (clamped at the
endpoints by :class:`AnimationCurve` and :class:`Catmull`; un-clamped on
:class:`Bezier` since its parametric domain is exactly ``[0, 1]``).
"""
from __future__ import annotations

import math as _stdmath
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Callable, Sequence

from ._validation import (
    validate_finite_float,
    validate_finite_sequence,
    validate_keyframe_list,
    validate_str,
)


# ---------------------------------------------------------------------------
# Hermite keyframe interpolation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Keyframe:
    """Single Hermite keyframe: time ``t``, value ``v``, in/out tangents."""

    t: float
    value: float
    in_tan: float = 0.0
    out_tan: float = 0.0

    def __post_init__(self) -> None:
        # Frozen dataclass — use object.__setattr__ for validation.
        object.__setattr__(self, "t", validate_finite_float("t", "Keyframe", self.t))
        object.__setattr__(self, "value", validate_finite_float("value", "Keyframe", self.value))
        object.__setattr__(self, "in_tan", validate_finite_float("in_tan", "Keyframe", self.in_tan))
        object.__setattr__(self, "out_tan", validate_finite_float("out_tan", "Keyframe", self.out_tan))


def _hermite(t: float, p0: float, m0: float, p1: float, m1: float) -> float:
    """Standard cubic Hermite basis ``H(t)`` on ``[0, 1]``.

    ``H(t) = h00·p0 + h10·m0 + h01·p1 + h11·m1`` with
    ``h00 = 2t³-3t²+1``, ``h10 = t³-2t²+t``, ``h01 = -2t³+3t²``,
    ``h11 = t³-t²``.
    """
    t2 = t * t
    t3 = t2 * t
    h00 = 2.0 * t3 - 3.0 * t2 + 1.0
    h10 = t3 - 2.0 * t2 + t
    h01 = -2.0 * t3 + 3.0 * t2
    h11 = t3 - t2
    return h00 * p0 + h10 * m0 + h01 * p1 + h11 * m1


@dataclass
class AnimationCurve:
    """Piecewise cubic Hermite curve through *keyframes*.

    Keyframes are sorted by ``t`` at construction time. Sampling outside
    the time range clamps to the endpoint values (no extrapolation —
    that's the contract animation rigs expect).
    """

    keyframes: list[Keyframe]
    _times: tuple[float, ...] = field(default_factory=tuple, init=False, repr=False)

    def __post_init__(self) -> None:
        validate_keyframe_list("keyframes", "AnimationCurve", self.keyframes)
        # Normalise — accept (t, v) / (t, v, in_tan, out_tan) tuples too.
        norm: list[Keyframe] = []
        for i, kf in enumerate(self.keyframes):
            if isinstance(kf, Keyframe):
                norm.append(kf)
                continue
            if isinstance(kf, (tuple, list)) and len(kf) in (2, 4):
                norm.append(Keyframe(*kf))
                continue
            raise TypeError(
                f"AnimationCurve: keyframes[{i}] must be Keyframe or tuple; "
                f"got {type(kf).__name__}"
            )
        norm.sort(key=lambda k: k.t)
        self.keyframes = norm
        self._times = tuple(k.t for k in norm)

    def sample(self, t: float) -> float:
        """Sample the curve at time *t*, clamped to the keyframe range."""
        t = validate_finite_float("t", "AnimationCurve.sample", t)
        kfs = self.keyframes
        if t <= kfs[0].t:
            return kfs[0].value
        if t >= kfs[-1].t:
            return kfs[-1].value
        # Locate the segment ``[i, i+1]`` containing ``t``.
        i = bisect_right(self._times, t) - 1
        a, b = kfs[i], kfs[i + 1]
        dt = b.t - a.t
        if dt <= 0.0:
            return a.value
        u = (t - a.t) / dt
        # Hermite tangents are scaled by the segment length so values
        # compose cleanly across irregular time spacing.
        return _hermite(u, a.value, a.out_tan * dt, b.value, b.in_tan * dt)


# ---------------------------------------------------------------------------
# Cubic Bezier
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Bezier:
    """Cubic Bezier curve through control points ``p0, p1, p2, p3``.

    ``sample(t)`` evaluates the standard Bernstein form at ``t ∈ [0, 1]``;
    inputs outside that range are clamped. Used both as an easing helper
    (``Bezier(0, 0.3, 0.7, 1).sample(t)``) and as a 1-D animation curve.
    """

    p0: float
    p1: float
    p2: float
    p3: float

    def __post_init__(self) -> None:
        for name in ("p0", "p1", "p2", "p3"):
            object.__setattr__(
                self, name,
                validate_finite_float(name, "Bezier", getattr(self, name)),
            )

    def sample(self, t: float) -> float:
        t = validate_finite_float("t", "Bezier.sample", t)
        if t < 0.0:
            t = 0.0
        elif t > 1.0:
            t = 1.0
        u = 1.0 - t
        u2, u3 = u * u, u * u * u
        t2, t3 = t * t, t * t * t
        return (u3 * self.p0
                + 3.0 * u2 * t * self.p1
                + 3.0 * u * t2 * self.p2
                + t3 * self.p3)


# ---------------------------------------------------------------------------
# Catmull-Rom spline through arbitrary 1-D points (uniform parameterisation)
# ---------------------------------------------------------------------------


@dataclass
class Catmull:
    """Catmull-Rom spline through *points* (uniform parameterisation).

    The spline passes through every interior point. End-tangents are
    mirrored from the first / last interior segment so the curve still
    behaves at the endpoints without requiring phantom control points
    from the caller. ``sample(t)`` accepts ``t`` in ``[0, len(points)-1]``
    and clamps outside that range.
    """

    points: list[float]

    def __post_init__(self) -> None:
        validate_keyframe_list("points", "Catmull", self.points)
        if len(self.points) < 2:
            raise ValueError("Catmull: need at least 2 points")
        self.points = [validate_finite_float(f"points[{i}]", "Catmull", p)
                       for i, p in enumerate(self.points)]

    def sample(self, t: float) -> float:
        t = validate_finite_float("t", "Catmull.sample", t)
        pts = self.points
        n = len(pts)
        if t <= 0.0:
            return pts[0]
        if t >= n - 1:
            return pts[-1]
        i = int(t)
        u = t - i
        # Build the four-point frame ``p_{i-1}, p_i, p_{i+1}, p_{i+2}``
        # with reflected endpoints (Catmull-Rom convention).
        p0 = pts[i - 1] if i - 1 >= 0 else 2.0 * pts[0] - pts[1]
        p1 = pts[i]
        p2 = pts[i + 1]
        p3 = pts[i + 2] if i + 2 < n else 2.0 * pts[-1] - pts[-2]
        # Standard Catmull-Rom matrix form.
        u2 = u * u
        u3 = u2 * u
        return 0.5 * (
            (2.0 * p1)
            + (-p0 + p2) * u
            + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * u2
            + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * u3
        )


# ---------------------------------------------------------------------------
# Easing functions
# ---------------------------------------------------------------------------


def _ease_linear(t: float) -> float:
    return t


def _ease_in_quad(t: float) -> float:
    return t * t


def _ease_out_quad(t: float) -> float:
    return 1.0 - (1.0 - t) * (1.0 - t)


def _ease_in_out_quad(t: float) -> float:
    if t < 0.5:
        return 2.0 * t * t
    return 1.0 - (-2.0 * t + 2.0) ** 2 / 2.0


def _ease_in_cubic(t: float) -> float:
    return t * t * t


def _ease_out_cubic(t: float) -> float:
    return 1.0 - (1.0 - t) ** 3


def _ease_in_out_cubic(t: float) -> float:
    if t < 0.5:
        return 4.0 * t * t * t
    return 1.0 - (-2.0 * t + 2.0) ** 3 / 2.0


def _ease_in_sine(t: float) -> float:
    return 1.0 - _stdmath.cos((t * _stdmath.pi) / 2.0)


def _ease_out_sine(t: float) -> float:
    return _stdmath.sin((t * _stdmath.pi) / 2.0)


def _ease_in_out_sine(t: float) -> float:
    return -(_stdmath.cos(_stdmath.pi * t) - 1.0) / 2.0


_EASE_KINDS: dict[str, Callable[[float], float]] = {
    "linear":            _ease_linear,
    "ease_in_quad":      _ease_in_quad,
    "ease_out_quad":     _ease_out_quad,
    "ease_in_out_quad":  _ease_in_out_quad,
    "ease_in_cubic":     _ease_in_cubic,
    "ease_out_cubic":    _ease_out_cubic,
    "ease_in_out_cubic": _ease_in_out_cubic,
    "ease_in_sine":      _ease_in_sine,
    "ease_out_sine":     _ease_out_sine,
    "ease_in_out_sine":  _ease_in_out_sine,
}


def ease(t: float, kind: str = "ease_in_out_cubic") -> float:
    """Common easing functions on ``[0, 1] → [0, 1]``.

    Inputs outside ``[0, 1]`` are clamped. Unknown ``kind`` raises
    :class:`ValueError` with the legal kinds enumerated.
    """
    t = validate_finite_float("t", "ease", t)
    kind = validate_str("kind", "ease", kind, allow_empty=False)
    if kind not in _EASE_KINDS:
        raise ValueError(
            f"ease: unknown kind {kind!r}; legal kinds: {sorted(_EASE_KINDS)}"
        )
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    return _EASE_KINDS[kind](t)


__all__ = [
    "AnimationCurve",
    "Bezier",
    "Catmull",
    "Keyframe",
    "ease",
]
