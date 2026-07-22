"""Internal input-validation helpers for the :class:`Camera` public API.

Generic ``validate_finite_2tuple`` and ``validate_positive_finite_or_none``
live in :mod:`pharos_engine._validation`; ``validate_positive_finite_float``
is aliased from the shared ``validate_positive_float``. Domain-specific
``validate_lerp`` (``(0, 1]`` follow range) and ``validate_follow_target``
(duck-typed ``.position`` check) stay here.
"""
from __future__ import annotations

import math
from typing import Any

from pharos_engine._validation import (
    validate_finite_2tuple,
    validate_positive_finite_or_none,
    validate_positive_float as validate_positive_finite_float,
)


def validate_lerp(name: str, fn: str, value: Any) -> float:
    """Confirm ``value`` is a finite real number in ``(0, 1]`` for ``follow``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{fn}: {name} must be a real number; got {type(value).__name__}"
        )
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{fn}: {name} must be finite; got {v!r}")
    if v <= 0.0:
        raise ValueError(f"{fn}: {name} must be in (0, 1]; got {v}")
    if v > 1.0:
        raise ValueError(f"{fn}: {name} must be in (0, 1]; got {v}")
    return v


def validate_follow_target(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` exposes a ``position`` attribute usable by ``follow``."""
    if value is None or not hasattr(value, "position"):
        raise TypeError(
            f"{fn}: {name} must be an object with a `.position` attribute; "
            f"got {type(value).__name__}"
        )
    pos = value.position
    if isinstance(pos, (str, bytes)) or not hasattr(pos, "__len__"):
        raise TypeError(
            f"{fn}: {name}.position must be a 2-element sequence; "
            f"got {type(pos).__name__}"
        )
    if len(pos) < 2:
        raise ValueError(
            f"{fn}: {name}.position must have length >= 2; got length {len(pos)}"
        )
    x, y = pos[0], pos[1]
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise TypeError(
            f"{fn}: {name}.position[0] must be a real number; "
            f"got {type(x).__name__}"
        )
    if isinstance(y, bool) or not isinstance(y, (int, float)):
        raise TypeError(
            f"{fn}: {name}.position[1] must be a real number; "
            f"got {type(y).__name__}"
        )
    if not math.isfinite(float(x)):
        raise ValueError(
            f"{fn}: {name}.position[0] must be finite; got {x!r}"
        )
    if not math.isfinite(float(y)):
        raise ValueError(
            f"{fn}: {name}.position[1] must be finite; got {y!r}"
        )
    return value


__all__ = [
    "validate_finite_2tuple",
    "validate_positive_finite_float",
    "validate_lerp",
    "validate_positive_finite_or_none",
    "validate_follow_target",
]
