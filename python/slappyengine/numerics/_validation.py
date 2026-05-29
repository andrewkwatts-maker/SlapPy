"""Internal input-validation helpers for the ``numerics`` public API.

Shared rejection logic for the multigrid V-cycle and its companions
(Red-Black SOR smoother, residual). Validates at the boundary; the inner
solver kernels trust their inputs.

Engineering policy: O(1) shape/range checks only — no whole-array scans.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np


def validate_2d_array(name: str, fn: str, arr: Any) -> np.ndarray:
    """Confirm ``arr`` is a 2-D numpy ndarray.

    Raises
    ------
    TypeError
        If ``arr`` is not a numpy ndarray.
    ValueError
        If ``arr`` is not 2-D.
    """
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
    """Confirm ``arr`` is a numpy ndarray with shape == ``expected_shape``.

    Raises
    ------
    TypeError
        If ``arr`` is not a numpy ndarray.
    ValueError
        If ``arr.shape != expected_shape``.
    """
    if not isinstance(arr, np.ndarray):
        raise TypeError(
            f"{fn}: {name} must be a numpy ndarray; got {type(arr).__name__}"
        )
    if arr.shape != expected_shape:
        raise ValueError(
            f"{fn}: {name} shape {arr.shape} must match {expected_shape}"
        )
    return arr


def validate_positive_int(name: str, fn: str, value: Any) -> int:
    """Coerce *value* to a Python ``int`` ≥ 1, rejecting floats / non-ints.

    Raises
    ------
    TypeError
        If ``value`` is not an int / numpy integer (floats refused).
    ValueError
        If ``value < 1``.
    """
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


def validate_omega(fn: str, omega: Any) -> float:
    """Confirm ``omega`` is a finite float strictly in ``(0, 2)``.

    SOR diverges at or outside this interval; refuse loudly.

    Raises
    ------
    TypeError
        If ``omega`` is not a real number.
    ValueError
        If ``omega`` is NaN, ±inf, or not in ``(0, 2)``.
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


def validate_positive_float(name: str, fn: str, value: Any) -> float:
    """Confirm *value* is a finite float > 0.

    Raises
    ------
    TypeError
        If ``value`` is not a real number.
    ValueError
        If ``value`` is not finite or not strictly positive.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
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
    "validate_2d_array",
    "validate_matching_shape",
    "validate_positive_int",
    "validate_omega",
    "validate_positive_float",
]
