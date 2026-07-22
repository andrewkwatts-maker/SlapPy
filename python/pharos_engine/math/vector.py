"""Small numeric vectors (Vec2 / Vec3 / Vec4).

Hand-written dataclasses (not numpy) — they are deliberately small,
finite-validated, and cheap to import in the no-arithma degraded mode.
Operator overloads (``+ - *``) and the structural helpers (``dot``,
``cross`` on Vec3, ``length``, ``normalized``) cover the surface
animation curves / IK targets / material graph inputs need.

The ``from_arithma`` / ``to_arithma`` round-trip is a best-effort hook
for callers that want to mix symbolic expressions into a vector pipeline.
When ``arithma`` is present and its ``Expression`` wrapper has landed,
``to_arithma`` emits a 2/3/4-tuple of ``Integer`` / ``Expression`` nodes;
otherwise it returns the raw float tuple.
"""
from __future__ import annotations

import math as _stdmath
from dataclasses import dataclass
from typing import Any, Iterable

from ._validation import validate_finite_float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_scalar(name: str, fn: str, value: Any) -> float:
    """Return a finite Python float, refusing bool."""
    return validate_finite_float(name, fn, value)


# ---------------------------------------------------------------------------
# Vec2
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Vec2:
    """Immutable 2-D vector."""

    x: float
    y: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", _coerce_scalar("x", "Vec2", self.x))
        object.__setattr__(self, "y", _coerce_scalar("y", "Vec2", self.y))

    def __add__(self, other: "Vec2") -> "Vec2":
        if not isinstance(other, Vec2):
            return NotImplemented
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Vec2") -> "Vec2":
        if not isinstance(other, Vec2):
            return NotImplemented
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> "Vec2":
        s = _coerce_scalar("scalar", "Vec2.__mul__", scalar)
        return Vec2(self.x * s, self.y * s)

    __rmul__ = __mul__

    def dot(self, other: "Vec2") -> float:
        if not isinstance(other, Vec2):
            raise TypeError(f"Vec2.dot: other must be Vec2; got {type(other).__name__}")
        return self.x * other.x + self.y * other.y

    def length(self) -> float:
        return _stdmath.hypot(self.x, self.y)

    def normalized(self) -> "Vec2":
        L = self.length()
        if L == 0.0:
            raise ValueError("Vec2.normalized: zero-length vector")
        return Vec2(self.x / L, self.y / L)

    def as_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)

    # ---- Arithma round-trip --------------------------------------------------

    @classmethod
    def from_arithma(cls, expr: Iterable[Any]) -> "Vec2":
        """Build from a 2-tuple of arithma scalars (or any iterable of reals)."""
        seq = list(expr)
        if len(seq) != 2:
            raise ValueError(f"Vec2.from_arithma: expected 2 elements; got {len(seq)}")
        return cls(float(seq[0]), float(seq[1]))

    def to_arithma(self) -> tuple[Any, Any]:
        """Convert to arithma scalars when available; else return float tuple."""
        return _to_arithma_tuple((self.x, self.y))


# ---------------------------------------------------------------------------
# Vec3
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Vec3:
    """Immutable 3-D vector."""

    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", _coerce_scalar("x", "Vec3", self.x))
        object.__setattr__(self, "y", _coerce_scalar("y", "Vec3", self.y))
        object.__setattr__(self, "z", _coerce_scalar("z", "Vec3", self.z))

    def __add__(self, other: "Vec3") -> "Vec3":
        if not isinstance(other, Vec3):
            return NotImplemented
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: "Vec3") -> "Vec3":
        if not isinstance(other, Vec3):
            return NotImplemented
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, scalar: float) -> "Vec3":
        s = _coerce_scalar("scalar", "Vec3.__mul__", scalar)
        return Vec3(self.x * s, self.y * s, self.z * s)

    __rmul__ = __mul__

    def dot(self, other: "Vec3") -> float:
        if not isinstance(other, Vec3):
            raise TypeError(f"Vec3.dot: other must be Vec3; got {type(other).__name__}")
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: "Vec3") -> "Vec3":
        if not isinstance(other, Vec3):
            raise TypeError(f"Vec3.cross: other must be Vec3; got {type(other).__name__}")
        return Vec3(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )

    def length(self) -> float:
        return _stdmath.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def normalized(self) -> "Vec3":
        L = self.length()
        if L == 0.0:
            raise ValueError("Vec3.normalized: zero-length vector")
        return Vec3(self.x / L, self.y / L, self.z / L)

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)

    @classmethod
    def from_arithma(cls, expr: Iterable[Any]) -> "Vec3":
        seq = list(expr)
        if len(seq) != 3:
            raise ValueError(f"Vec3.from_arithma: expected 3 elements; got {len(seq)}")
        return cls(float(seq[0]), float(seq[1]), float(seq[2]))

    def to_arithma(self) -> tuple[Any, Any, Any]:
        return _to_arithma_tuple((self.x, self.y, self.z))


# ---------------------------------------------------------------------------
# Vec4
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Vec4:
    """Immutable 4-D vector (RGBA, homogeneous coords, quaternion components)."""

    x: float
    y: float
    z: float
    w: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", _coerce_scalar("x", "Vec4", self.x))
        object.__setattr__(self, "y", _coerce_scalar("y", "Vec4", self.y))
        object.__setattr__(self, "z", _coerce_scalar("z", "Vec4", self.z))
        object.__setattr__(self, "w", _coerce_scalar("w", "Vec4", self.w))

    def __add__(self, other: "Vec4") -> "Vec4":
        if not isinstance(other, Vec4):
            return NotImplemented
        return Vec4(self.x + other.x, self.y + other.y, self.z + other.z, self.w + other.w)

    def __sub__(self, other: "Vec4") -> "Vec4":
        if not isinstance(other, Vec4):
            return NotImplemented
        return Vec4(self.x - other.x, self.y - other.y, self.z - other.z, self.w - other.w)

    def __mul__(self, scalar: float) -> "Vec4":
        s = _coerce_scalar("scalar", "Vec4.__mul__", scalar)
        return Vec4(self.x * s, self.y * s, self.z * s, self.w * s)

    __rmul__ = __mul__

    def dot(self, other: "Vec4") -> float:
        if not isinstance(other, Vec4):
            raise TypeError(f"Vec4.dot: other must be Vec4; got {type(other).__name__}")
        return (self.x * other.x + self.y * other.y
                + self.z * other.z + self.w * other.w)

    def length(self) -> float:
        return _stdmath.sqrt(self.x * self.x + self.y * self.y
                             + self.z * self.z + self.w * self.w)

    def normalized(self) -> "Vec4":
        L = self.length()
        if L == 0.0:
            raise ValueError("Vec4.normalized: zero-length vector")
        return Vec4(self.x / L, self.y / L, self.z / L, self.w / L)

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.z, self.w)

    @classmethod
    def from_arithma(cls, expr: Iterable[Any]) -> "Vec4":
        seq = list(expr)
        if len(seq) != 4:
            raise ValueError(f"Vec4.from_arithma: expected 4 elements; got {len(seq)}")
        return cls(float(seq[0]), float(seq[1]), float(seq[2]), float(seq[3]))

    def to_arithma(self) -> tuple[Any, Any, Any, Any]:
        return _to_arithma_tuple((self.x, self.y, self.z, self.w))


# ---------------------------------------------------------------------------
# Arithma bridge helper
# ---------------------------------------------------------------------------


def _to_arithma_tuple(values: tuple[float, ...]) -> tuple[Any, ...]:
    """Wrap each float in ``arithma.Integer`` / ``Expression`` when available.

    Falls back to the raw float tuple when arithma's pyfacade wrappers
    are not yet published — that's the steady state today (Wave-3
    pending), so callers see the float tuple in the wild.
    """
    from . import _HAS_ARITHMA, Expression, Integer  # late binding
    if not _HAS_ARITHMA or (Expression is None and Integer is None):
        return values
    out: list[Any] = []
    for v in values:
        # Prefer ``Integer`` for exact ints, ``Expression`` otherwise.
        if v == int(v) and Integer is not None:
            out.append(Integer(int(v)))
        elif Expression is not None:
            out.append(Expression.parse(repr(v)))  # type: ignore[attr-defined]
        else:
            out.append(v)
    return tuple(out)


__all__ = [
    "Vec2",
    "Vec3",
    "Vec4",
]
