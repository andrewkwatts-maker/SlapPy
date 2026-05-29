"""Internal input-validation helpers for the ``post_process`` public API.

Shared rejection logic for :class:`BloomPass`, :class:`VignettePass`,
:class:`GTAOPass`, :class:`TAAPass`. Constructor kwargs are validated at
the boundary; ``make_pass``/``apply_cpu`` trust their inputs.

Engineering policy: O(1) checks only. Don't silently coerce — refuse
loudly so the authoring error surfaces at the pass-construction site
instead of as a shader artefact two frames later.
"""
from __future__ import annotations

import math
from typing import Any


def validate_non_negative_float(name: str, fn: str, value: Any) -> float:
    """Confirm ``value`` is a finite real ≥ 0.

    Raises
    ------
    TypeError
        If ``value`` is not a real number (bool refused).
    ValueError
        If ``value`` is NaN/inf or negative.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{fn}: {name} must be a real number; got {type(value).__name__}"
        )
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{fn}: {name} must be finite; got {v!r}")
    if v < 0.0:
        raise ValueError(f"{fn}: {name} must be >= 0; got {v}")
    return v


def validate_positive_float(name: str, fn: str, value: Any) -> float:
    """Confirm ``value`` is a finite real > 0.

    Raises
    ------
    TypeError
        If ``value`` is not a real number (bool refused).
    ValueError
        If ``value`` is NaN/inf or ≤ 0.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{fn}: {name} must be a real number; got {type(value).__name__}"
        )
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{fn}: {name} must be finite; got {v!r}")
    if v <= 0.0:
        raise ValueError(f"{fn}: {name} must be > 0; got {v}")
    return v


def validate_positive_int(name: str, fn: str, value: Any) -> int:
    """Confirm ``value`` is an integer ≥ 1 (no floats, no bools).

    Raises
    ------
    TypeError
        If ``value`` is not a plain ``int``.
    ValueError
        If ``value < 1``.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"{fn}: {name} must be an int; got {type(value).__name__}"
        )
    if value < 1:
        raise ValueError(f"{fn}: {name} must be >= 1; got {value}")
    return value


def validate_unit_interval(name: str, fn: str, value: Any) -> float:
    """Confirm ``value`` is a finite real in ``[0, 1]``.

    Raises
    ------
    TypeError
        If ``value`` is not a real number (bool refused).
    ValueError
        If ``value`` is NaN/inf or out of ``[0, 1]``.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{fn}: {name} must be a real number; got {type(value).__name__}"
        )
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{fn}: {name} must be finite; got {v!r}")
    if v < 0.0 or v > 1.0:
        raise ValueError(f"{fn}: {name} must be in [0, 1]; got {v}")
    return v


def validate_bool(name: str, fn: str, value: Any) -> bool:
    """Confirm ``value`` is a Python ``bool`` (refuses truthy non-bools).

    Raises
    ------
    TypeError
        If ``value`` is not ``True`` or ``False``.
    """
    if not isinstance(value, bool):
        raise TypeError(
            f"{fn}: {name} must be a bool; got {type(value).__name__}"
        )
    return value


def validate_mat4_tuple(name: str, fn: str, value: Any) -> tuple:
    """Confirm ``value`` is a 16-element sequence of finite floats.

    Raises
    ------
    TypeError
        If ``value`` is not a 16-sequence or any element is not numeric.
    ValueError
        If the sequence has the wrong length or any element is NaN/inf.
    """
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
