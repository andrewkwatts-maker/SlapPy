"""Internal input-validation helpers for the ``testing`` public API.

Shared rejection logic for the visual-regression entry points
(:func:`render_scene_to_png`, :func:`diff_pngs`, :func:`assert_scene_matches`).

Engineering policy: validate at the boundary; the frame-extraction
fallback chain and PIL save/open calls trust their inputs. O(1) checks
only — never iterate pixels for validation.
"""
from __future__ import annotations

import math
import os
import re
from pathlib import Path
from typing import Any

# Baseline names must match this — strict subset of POSIX portable filenames,
# guarantees no path-traversal characters (``/``, ``\``, ``..``) and no
# whitespace. Anchored both ends so partial matches don't sneak through.
_BASELINE_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def validate_pathlike(name: str, fn: str, value: Any) -> Path:
    """Confirm ``value`` is a ``str`` or :class:`os.PathLike` and return a Path.

    Raises
    ------
    TypeError
        If ``value`` is neither a ``str`` nor an :class:`os.PathLike`.
    """
    if isinstance(value, Path):
        return value
    if isinstance(value, (str, os.PathLike)):
        return Path(value)
    raise TypeError(
        f"{fn}: {name} must be str or os.PathLike; got {type(value).__name__}"
    )


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


def validate_non_negative_int(name: str, fn: str, value: Any) -> int:
    """Confirm ``value`` is an integer ≥ 0 (no floats, no bools).

    Raises
    ------
    TypeError
        If ``value`` is not a plain ``int``.
    ValueError
        If ``value < 0``.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"{fn}: {name} must be an int; got {type(value).__name__}"
        )
    if value < 0:
        raise ValueError(f"{fn}: {name} must be >= 0; got {value}")
    return value


def validate_tolerance(name: str, fn: str, value: Any, *, upper: float = 1.0) -> float:
    """Confirm ``value`` is a finite real in ``[0, upper]``.

    Raises
    ------
    TypeError
        If ``value`` is not a real number (bool refused).
    ValueError
        If ``value`` is NaN/inf or out of ``[0, upper]``.
    """
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


def validate_baseline_name(fn: str, value: Any) -> str:
    """Confirm ``value`` is a path-safe baseline stem.

    Rejects empty strings, anything containing path separators, ``..``,
    or characters outside ``[A-Za-z0-9_-]``. This blocks accidental
    path traversal (``../etc/passwd``) at the public boundary.

    Raises
    ------
    TypeError
        If ``value`` is not a ``str``.
    ValueError
        If ``value`` is empty or contains disallowed characters.
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
