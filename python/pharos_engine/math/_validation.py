"""Internal input-validation helpers for the ``math`` public API.

Generic validators live in :mod:`pharos_engine._validation` and are
re-exported. Only the domain-specific keyframe / control-point shape
checks live here.
"""
from __future__ import annotations

from typing import Any, Sequence

from pharos_engine._validation import (
    validate_finite_float,
    validate_non_empty_str,
    validate_non_negative_int,
    validate_positive_int,
    validate_str,
    validate_unit_float,
)


def validate_finite_sequence(name: str, fn: str, value: Any, length: int) -> tuple[float, ...]:
    """Confirm *value* is a length-``length`` sequence of finite reals.

    Refuses ``str`` / ``bytes`` because their ``__len__`` is per-character.
    """
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__"):
        raise TypeError(
            f"{fn}: {name} must be a length-{length} sequence of floats; "
            f"got {type(value).__name__}"
        )
    if len(value) != length:
        raise ValueError(
            f"{fn}: {name} must have length {length}; got length {len(value)}"
        )
    out: list[float] = []
    for i, v in enumerate(value):
        out.append(validate_finite_float(f"{name}[{i}]", fn, v))
    return tuple(out)


def validate_keyframe_list(name: str, fn: str, value: Any) -> Sequence:
    """Confirm *value* is a non-empty sequence (does not type-check entries)."""
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__"):
        raise TypeError(
            f"{fn}: {name} must be a sequence; got {type(value).__name__}"
        )
    if len(value) < 1:
        raise ValueError(f"{fn}: {name} must contain at least one entry")
    return value


__all__ = [
    "validate_finite_float",
    "validate_finite_sequence",
    "validate_keyframe_list",
    "validate_non_empty_str",
    "validate_non_negative_int",
    "validate_positive_int",
    "validate_str",
    "validate_unit_float",
]
