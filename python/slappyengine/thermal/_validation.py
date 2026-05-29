"""Internal input-validation helpers for the ``thermal`` public API.

Shared by :class:`HeatField` and the pairwise exchange helpers. O(1)
checks only — no whole-array temperature scans.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np


def validate_finite_float(name: str, fn: str, value: Any) -> float:
    """Confirm *value* is a real number and finite, return as ``float``."""
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


def validate_diffusivity(fn: str, value: Any) -> float:
    """Confirm *value* is a real number in ``(0, 1]``.

    Outside that range the explicit pairwise scheme either does nothing
    (≤ 0) or trivially overshoots (> 1 per axis pair → oscillation).
    """
    v = validate_finite_float("diffusivity", fn, value)
    if v <= 0.0 or v > 1.0:
        raise ValueError(
            f"{fn}: diffusivity must be in (0, 1]; got {v}"
        )
    return v


def validate_positive_int(name: str, fn: str, value: Any) -> int:
    """Confirm *value* is an integer ≥ 1."""
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


def validate_grid_2d_float(name: str, fn: str, arr: Any) -> np.ndarray:
    """Confirm ``arr`` is a 2-D float numpy ndarray.

    Raises
    ------
    TypeError
        If ``arr`` is not an ndarray, or its dtype is not floating.
    ValueError
        If ``arr.ndim != 2``.
    """
    if not isinstance(arr, np.ndarray):
        raise TypeError(
            f"{fn}: {name} must be a numpy ndarray; got {type(arr).__name__}"
        )
    if arr.dtype.kind != "f":
        raise TypeError(
            f"{fn}: {name} must have float dtype; got {arr.dtype}"
        )
    if arr.ndim != 2:
        raise ValueError(
            f"{fn}: {name} must be 2-D; got shape {arr.shape}"
        )
    return arr


__all__ = [
    "validate_finite_float",
    "validate_positive_float",
    "validate_non_negative_float",
    "validate_diffusivity",
    "validate_positive_int",
    "validate_grid_2d_float",
]
