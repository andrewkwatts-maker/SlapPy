"""Internal input-validation helpers for the ``numerics`` public API.

Generic ``validate_positive_int`` / ``validate_positive_float`` live in
:mod:`slappyengine._validation`. Domain-specific ``validate_2d_array``,
``validate_matching_shape``, and ``validate_omega`` stay here.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from slappyengine._validation import (
    validate_positive_float,
    validate_positive_int,
)


def validate_2d_array(name: str, fn: str, arr: Any) -> np.ndarray:
    """Confirm ``arr`` is a 2-D numpy ndarray."""
    if not isinstance(arr, np.ndarray):
        raise TypeError(
            f"{fn}: {name} must be a numpy ndarray; got {type(arr).__name__}"
        )
    if arr.ndim != 2:
        raise ValueError(
            f"{fn}: {name} must be 2-D; got shape {arr.shape}"
        )
    return arr


def validate_matching_shape(
    name: str, fn: str, arr: Any, expected_shape: tuple[int, ...]
) -> np.ndarray:
    """Confirm ``arr`` is a numpy ndarray with shape == ``expected_shape``."""
    if not isinstance(arr, np.ndarray):
        raise TypeError(
            f"{fn}: {name} must be a numpy ndarray; got {type(arr).__name__}"
        )
    if arr.shape != expected_shape:
        raise ValueError(
            f"{fn}: {name} shape {arr.shape} must match {expected_shape}"
        )
    return arr


def validate_omega(fn: str, omega: Any) -> float:
    """Confirm ``omega`` is a finite float strictly in ``(0, 2)``.

    SOR diverges at or outside this interval; refuse loudly.
    """
    if isinstance(omega, bool) or not isinstance(omega, (int, float, np.integer, np.floating)):
        raise TypeError(
            f"{fn}: omega must be a real number; got {type(omega).__name__}"
        )
    v = float(omega)
    if not math.isfinite(v):
        raise ValueError(f"{fn}: omega must be finite; got {v!r}")
    if v <= 0.0 or v >= 2.0:
        raise ValueError(
            f"{fn}: omega must be in (0, 2); got {v}"
        )
    return v


__all__ = [
    "validate_2d_array",
    "validate_matching_shape",
    "validate_positive_int",
    "validate_omega",
    "validate_positive_float",
]
