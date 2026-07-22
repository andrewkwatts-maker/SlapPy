"""Internal input-validation helpers for the ``testing`` public API.

Generic validators live in :mod:`pharos_engine._validation`. Domain-specific
``validate_tolerance`` (with the ``upper`` kwarg) and ``validate_baseline_name``
(path-safe baseline stem regex) stay here.
"""
from __future__ import annotations

import math
import re
from typing import Any

from pharos_engine._validation import (
    validate_non_negative_float,
    validate_non_negative_int,
    validate_pathlike,
    validate_positive_int,
)


# Baseline names must match this — strict subset of POSIX portable filenames,
# guarantees no path-traversal characters (``/``, ``\``, ``..``) and no
# whitespace.
_BASELINE_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def validate_tolerance(name: str, fn: str, value: Any, *, upper: float = 1.0) -> float:
    """Confirm ``value`` is a finite real in ``[0, upper]``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{fn}: {name} must be a real number; got {type(value).__name__}"
        )
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{fn}: {name} must be finite; got {v!r}")
    if v < 0.0 or v > upper:
        raise ValueError(
            f"{fn}: {name} must be in [0, {upper}]; got {v}"
        )
    return v


def validate_baseline_name(fn: str, value: Any) -> str:
    """Confirm ``value`` is a path-safe baseline stem.

    Rejects empty strings, anything containing path separators, ``..``,
    or characters outside ``[A-Za-z0-9_-]``.
    """
    if not isinstance(value, str):
        raise TypeError(
            f"{fn}: baseline_name must be a str; got {type(value).__name__}"
        )
    if not value:
        raise ValueError(f"{fn}: baseline_name must be non-empty")
    if not _BASELINE_NAME_RE.match(value):
        raise ValueError(
            f"{fn}: baseline_name must match [A-Za-z0-9_-]+ "
            f"(no path separators, dots, or whitespace); got {value!r}"
        )
    return value


__all__ = [
    "validate_pathlike",
    "validate_positive_int",
    "validate_non_negative_int",
    "validate_tolerance",
    "validate_non_negative_float",
    "validate_baseline_name",
]
