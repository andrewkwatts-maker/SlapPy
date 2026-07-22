"""Internal input-validation helpers for the ``thermal`` public API.

Generic validators live in :mod:`pharos_engine._validation`. Domain-specific
``validate_diffusivity`` (``(0, 1]`` range) and ``validate_grid_2d_float``
stay here.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from pharos_engine._validation import (
    validate_finite_float,
    validate_non_negative_float,
    validate_positive_float,
    validate_positive_int,
)


def validate_diffusivity(fn: str, value: Any) -> float:
    """Confirm *value* is a real number in ``(0, 1]``."""
    v = validate_finite_float("diffusivity", fn, value)
    if v <= 0.0 or v > 1.0:
        raise ValueError(
            f"{fn}: diffusivity must be in (0, 1]; got {v}"
        )
    return v


def validate_grid_2d_float(name: str, fn: str, arr: Any) -> np.ndarray:
    """Confirm ``arr`` is a 2-D float numpy ndarray."""
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
