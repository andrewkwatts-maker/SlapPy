"""Internal input-validation helpers for the :class:`Camera` public API.

Shared rejection logic for the :class:`Camera` constructor and its
``position`` / ``zoom`` property setters. Internal matrix maths trusts
its inputs.

Engineering policy: O(1) checks only. Don't silently coerce — a NaN
position would corrupt the view matrix every frame after, so refuse at
the assignment site.
"""
from __future__ import annotations

import math
from typing import Any


def validate_finite_2tuple(name: str, fn: str, value: Any) -> tuple[float, float]:
    """Confirm ``value`` is a 2-element sequence of finite real numbers.

    Raises
    ------
    TypeError
        If ``value`` is not a 2-element sequence or members aren't numeric
        (bool refused).
    ValueError
        If the length isn't 2 or any element is NaN/inf.
    """
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__"):
        raise TypeError(
            f"{fn}: {name} must be a 2-tuple of floats; "
            f"got {type(value).__name__}"
        )
    if len(value) != 2:
        raise ValueError(
            f"{fn}: {name} must have length 2 (x, y); got length {len(value)}"
        )
    x, y = value[0], value[1]
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise TypeError(
            f"{fn}: {name}[0] must be a real number; got {type(x).__name__}"
        )
    if isinstance(y, bool) or not isinstance(y, (int, float)):
        raise TypeError(
            f"{fn}: {name}[1] must be a real number; got {type(y).__name__}"
        )
    fx, fy = float(x), float(y)
    if not math.isfinite(fx):
        raise ValueError(f"{fn}: {name}[0] must be finite; got {fx!r}")
    if not math.isfinite(fy):
        raise ValueError(f"{fn}: {name}[1] must be finite; got {fy!r}")
    return (fx, fy)


def validate_positive_finite_float(name: str, fn: str, value: Any) -> float:
    """Confirm ``value`` is a finite real number > 0.

    Raises
    ------
    TypeError
        If ``value`` is not a real number (bool refused).
    ValueError
        If ``value`` is NaN/inf or ≤ 0.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{fn}: {name} must be a real number; got {type(value).__name__}"
        )
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{fn}: {name} must be finite; got {v!r}")
    if v <= 0.0:
        raise ValueError(f"{fn}: {name} must be > 0; got {v}")
    return v


__all__ = [
    "validate_finite_2tuple",
    "validate_positive_finite_float",
]
