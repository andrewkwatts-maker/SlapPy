"""Internal input-validation helpers for the ``zones`` public API.

Shared by :class:`RectZone`, :class:`ThresholdZone`, and
:class:`ZoneManager`. O(1) checks only.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np


def validate_finite_float(name: str, fn: str, value: Any) -> float:
    """Confirm *value* is a real number and finite, return as ``float``.

    Raises
    ------
    TypeError
        If ``value`` is not a real number (bool / str / sequence rejected).
    ValueError
        If ``value`` is NaN or ±inf.
    """
    if isinstance(value, bool) or not isinstance(
        value, (int, float, np.integer, np.floating)
    ):
        raise TypeError(
            f"{fn}: {name} must be a real number; got {type(value).__name__}"
        )
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{fn}: {name} must be finite; got {v!r}")
    return v


def validate_positive_float(name: str, fn: str, value: Any) -> float:
    """Confirm *value* is a finite real number > 0."""
    v = validate_finite_float(name, fn, value)
    if v <= 0.0:
        raise ValueError(f"{fn}: {name} must be > 0; got {v}")
    return v


def validate_non_negative_float(name: str, fn: str, value: Any) -> float:
    """Confirm *value* is a finite real number ≥ 0."""
    v = validate_finite_float(name, fn, value)
    if v < 0.0:
        raise ValueError(f"{fn}: {name} must be ≥ 0; got {v}")
    return v


__all__ = [
    "validate_finite_float",
    "validate_positive_float",
    "validate_non_negative_float",
]
