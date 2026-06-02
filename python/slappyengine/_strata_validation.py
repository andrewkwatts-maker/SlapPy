"""Internal input-validation helpers for the :mod:`slappyengine.strata` API.

Generic ``validate_non_empty_str``, ``validate_non_negative_int``,
``validate_finite_float`` and ``validate_unit_float`` live in
:mod:`slappyengine._validation`. Domain-specific ``validate_rgba_tuple``,
``validate_layer_list``, and ``validate_entity_arg`` stay here.
"""
from __future__ import annotations

import math
from typing import Any

from slappyengine._validation import (
    validate_finite_float,
    validate_non_empty_str,
    validate_non_negative_int,
    validate_unit_float,
)


def validate_rgba_tuple(name: str, fn: str, value: Any) -> tuple[float, float, float, float]:
    """Confirm ``value`` is a 4-element sequence of finite real numbers."""
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__"):
        raise TypeError(
            f"{fn}: {name} must be a 4-tuple of floats; "
            f"got {type(value).__name__}"
        )
    if len(value) != 4:
        raise ValueError(
            f"{fn}: {name} must have length 4 (r, g, b, a); "
            f"got length {len(value)}"
        )
    out: list[float] = []
    for i, ch in enumerate(value):
        if isinstance(ch, bool) or not isinstance(ch, (int, float)):
            raise TypeError(
                f"{fn}: {name}[{i}] must be a real number; "
                f"got {type(ch).__name__}"
            )
        fv = float(ch)
        if not math.isfinite(fv):
            raise ValueError(
                f"{fn}: {name}[{i}] must be finite; got {fv!r}"
            )
        out.append(fv)
    return (out[0], out[1], out[2], out[3])


def validate_layer_list(name: str, fn: str, value: Any) -> list:
    """Confirm ``value`` is a non-empty list of :class:`StrataLayer`."""
    from slappyengine.strata import StrataLayer

    if not isinstance(value, (list, tuple)):
        raise TypeError(
            f"{fn}: {name} must be a list of StrataLayer; "
            f"got {type(value).__name__}"
        )
    if len(value) == 0:
        raise ValueError(f"{fn}: {name} must be non-empty")
    for i, item in enumerate(value):
        if not isinstance(item, StrataLayer):
            raise TypeError(
                f"{fn}: {name}[{i}] must be a StrataLayer; "
                f"got {type(item).__name__}"
            )
    return list(value)


def validate_entity_arg(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` is non-``None``."""
    if value is None:
        raise TypeError(f"{fn}: {name} must not be None")
    return value


__all__ = [
    "validate_non_empty_str",
    "validate_non_negative_int",
    "validate_finite_float",
    "validate_unit_float",
    "validate_rgba_tuple",
    "validate_layer_list",
    "validate_entity_arg",
]
