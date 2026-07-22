"""Internal input-validation helpers for the ``post_process`` public API.

Generic validators live in :mod:`pharos_engine._validation`. Domain-specific
``validate_mat4_tuple`` (16-element finite-float sequence for shader
matrix uniforms) stays here.
"""
from __future__ import annotations

import math
from typing import Any

from pharos_engine._validation import (
    validate_bool,
    validate_non_negative_float,
    validate_positive_float,
    validate_positive_int,
    validate_unit_interval,
)


def validate_mat4_tuple(name: str, fn: str, value: Any) -> tuple:
    """Confirm ``value`` is a 16-element sequence of finite floats."""
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__"):
        raise TypeError(
            f"{fn}: {name} must be a 16-tuple of floats; "
            f"got {type(value).__name__}"
        )
    if len(value) != 16:
        raise ValueError(
            f"{fn}: {name} must have length 16 (4x4 row-major); "
            f"got length {len(value)}"
        )
    out: list[float] = []
    for i, v in enumerate(value):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise TypeError(
                f"{fn}: {name}[{i}] must be a real number; "
                f"got {type(v).__name__}"
            )
        fv = float(v)
        if not math.isfinite(fv):
            raise ValueError(
                f"{fn}: {name}[{i}] must be finite; got {fv!r}"
            )
        out.append(fv)
    return tuple(out)


__all__ = [
    "validate_non_negative_float",
    "validate_positive_float",
    "validate_positive_int",
    "validate_unit_interval",
    "validate_bool",
    "validate_mat4_tuple",
]
