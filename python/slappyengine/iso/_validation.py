"""Internal input-validation helpers for the ``iso`` public API.

Currently shared by the combat module's :class:`Attacker` /
:class:`Defender` resolution helpers and the wave-scheduling primitives.
O(1) checks only.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np


def validate_finite_float(name: str, fn: str, value: Any) -> float:
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
    v = validate_finite_float(name, fn, value)
    if v <= 0.0:
        raise ValueError(f"{fn}: {name} must be > 0; got {v}")
    return v


def validate_non_negative_float(name: str, fn: str, value: Any) -> float:
    v = validate_finite_float(name, fn, value)
    if v < 0.0:
        raise ValueError(f"{fn}: {name} must be ≥ 0; got {v}")
    return v


def validate_positive_int(name: str, fn: str, value: Any) -> int:
    if isinstance(value, bool):
        v = int(value)
    elif isinstance(value, (int, np.integer)):
        v = int(value)
    else:
        raise TypeError(
            f"{fn}: {name} must be an int; got {type(value).__name__}"
        )
    if v < 1:
        raise ValueError(f"{fn}: {name} must be ≥ 1; got {v}")
    return v


def validate_pos2(name: str, fn: str, pos: Any) -> tuple[float, float]:
    """Confirm *pos* is a 2-tuple of finite floats."""
    if isinstance(pos, (str, bytes)) or not hasattr(pos, "__len__"):
        raise TypeError(
            f"{fn}: {name} must be a 2-sequence of floats; "
            f"got {type(pos).__name__}"
        )
    if len(pos) != 2:
        raise ValueError(
            f"{fn}: {name} must have length 2 (x, y); got length {len(pos)}"
        )
    return (
        validate_finite_float(f"{name}[0]", fn, pos[0]),
        validate_finite_float(f"{name}[1]", fn, pos[1]),
    )


__all__ = [
    "validate_finite_float",
    "validate_positive_float",
    "validate_non_negative_float",
    "validate_positive_int",
    "validate_pos2",
]
