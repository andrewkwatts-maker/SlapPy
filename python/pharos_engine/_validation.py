"""Shared input-validation helpers for the pharos_engine public API.

Background
----------
Across 12 rounds of public-boundary hardening (one per subsystem) we
accreted ~15 per-subsystem ``_*_validation.py`` modules. Each grew the
same boilerplate ``validate_str`` / ``validate_finite_float`` /
``validate_positive_int`` / ``validate_finite_2tuple`` / ``validate_bool``
helpers, each with subtly different rules:

* some refused ``bool`` masquerading as ``int``; some accepted it
* some accepted numpy scalars (``np.float64``, ``np.int64``); some refused
* some refused ``bytes`` masquerading as ``str``; one ``str`` helper
  accepted whatever ``isinstance(x, str)`` returned (so a ``bytearray``
  would have slipped through if anyone ever tried)
* one ``non_negative_int`` happily accepted ``True`` and returned ``1``

This module collapses every truly-shared check into a single canonical
implementation. The per-subsystem ``_*_validation.py`` modules now
re-export from here and keep only the domain-specific validators
(``validate_layer_mode`` / ``validate_event_type`` / ``validate_joint``).

Canonical rules (applied uniformly here):

* ``str`` checks reject ``bytes`` / ``bytearray`` / any non-``str``
  subclass that isn't a plain ``str``
* ``int`` checks reject ``bool`` outright (``isinstance(True, int)`` is
  True in Python, but that's almost always a bug at the boundary)
* numeric checks accept Python ``int`` / ``float`` AND numpy scalar
  ``np.integer`` / ``np.floating`` — the numerics, thermal, zones and
  iso subsystems pass them through routinely and refusing was an
  accidental regression in the non-numpy callers
* ``allow_empty=False`` on string helpers refuses ``""`` consistently
* every error message uses the ``"{fn}: {name} ..."`` prefix so users
  can grep the traceback for the call site

Engineering policy: O(1) checks only. The slow path is the bug message,
not the happy path.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, Callable

import numpy as np


# ---------------------------------------------------------------------------
# Internal helpers — keep error messages identical across all callers.
# ---------------------------------------------------------------------------

_REAL_TYPES: tuple[type, ...] = (int, float, np.integer, np.floating)


def _is_real_number(value: Any) -> bool:
    """``True`` iff *value* is a finite-or-not real number (bool excluded)."""
    if isinstance(value, bool):
        return False
    return isinstance(value, _REAL_TYPES)


# ---------------------------------------------------------------------------
# String / identifier validators
# ---------------------------------------------------------------------------


def validate_str(
    name: str, fn: str, value: Any, *, allow_empty: bool = True
) -> str:
    """Confirm *value* is a plain ``str`` (and optionally non-empty).

    Refuses ``bytes`` / ``bytearray`` — those iterate per-byte downstream
    and silently never match the ``str`` keys used by event-bus, input,
    audio, etc.

    Raises
    ------
    TypeError
        If *value* is not a ``str``.
    ValueError
        If ``allow_empty=False`` and *value* is the empty string.
    """
    # bool is a subclass of int, but isinstance(True, str) is False, so we
    # don't need to special-case it here.
    if not isinstance(value, str):
        raise TypeError(
            f"{fn}: {name} must be a str; got {type(value).__name__}"
        )
    if not allow_empty and not value:
        raise ValueError(f"{fn}: {name} must be non-empty")
    return value


def validate_non_empty_str(name: str, fn: str, value: Any) -> str:
    """Confirm *value* is a non-empty ``str`` (alias for ``allow_empty=False``)."""
    return validate_str(name, fn, value, allow_empty=False)


def validate_optional_str(name: str, fn: str, value: Any) -> str | None:
    """Confirm *value* is ``None`` or a ``str`` (empty allowed)."""
    if value is None:
        return None
    return validate_str(name, fn, value)


# ---------------------------------------------------------------------------
# Boolean validator
# ---------------------------------------------------------------------------


def validate_bool(name: str, fn: str, value: Any) -> bool:
    """Confirm *value* is exactly a Python ``bool``.

    Refuses truthy ``int`` / ``str`` / ``None`` so callers can't widen the
    contract by accident (e.g. ``play(..., loop=1)`` looking like "loop
    1 extra time").

    Raises
    ------
    TypeError
        If *value* is not ``True`` or ``False``.
    """
    if not isinstance(value, bool):
        raise TypeError(
            f"{fn}: {name} must be a bool; got {type(value).__name__}"
        )
    return value


# ---------------------------------------------------------------------------
# Integer validators
# ---------------------------------------------------------------------------


def _coerce_int_strict(name: str, fn: str, value: Any) -> int:
    """Internal: refuse bool + non-int, return a plain ``int``."""
    if isinstance(value, bool):
        raise TypeError(
            f"{fn}: {name} must be an int; got {type(value).__name__}"
        )
    if isinstance(value, (int, np.integer)):
        return int(value)
    raise TypeError(
        f"{fn}: {name} must be an int; got {type(value).__name__}"
    )


def validate_int(name: str, fn: str, value: Any) -> int:
    """Confirm *value* is a plain ``int`` (or ``np.integer``). Refuses ``bool``."""
    return _coerce_int_strict(name, fn, value)


def validate_positive_int(
    name: str, fn: str, value: Any, *, maximum: int | None = None
) -> int:
    """Confirm *value* is an integer ≥ 1 (and optionally ≤ ``maximum``)."""
    v = _coerce_int_strict(name, fn, value)
    if v < 1:
        raise ValueError(f"{fn}: {name} must be >= 1; got {v}")
    if maximum is not None and v > maximum:
        raise ValueError(f"{fn}: {name} must be <= {maximum}; got {v}")
    return v


def validate_non_negative_int(name: str, fn: str, value: Any) -> int:
    """Confirm *value* is an integer ≥ 0."""
    v = _coerce_int_strict(name, fn, value)
    if v < 0:
        raise ValueError(f"{fn}: {name} must be >= 0; got {v}")
    return v


# ---------------------------------------------------------------------------
# Floating-point validators
# ---------------------------------------------------------------------------


def validate_finite_float(name: str, fn: str, value: Any) -> float:
    """Confirm *value* is a finite real number (NaN/inf refused).

    Accepts Python ``int`` / ``float`` and numpy scalar ``np.integer`` /
    ``np.floating``. Refuses ``bool``.
    """
    if not _is_real_number(value):
        raise TypeError(
            f"{fn}: {name} must be a real number; got {type(value).__name__}"
        )
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{fn}: {name} must be finite; got {v!r}")
    return v


def validate_positive_float(name: str, fn: str, value: Any) -> float:
    """Confirm *value* is a finite real number > 0."""
    v = validate_finite_float(name, fn, value)
    if v <= 0.0:
        raise ValueError(f"{fn}: {name} must be > 0; got {v}")
    return v


def validate_non_negative_float(name: str, fn: str, value: Any) -> float:
    """Confirm *value* is a finite real number ≥ 0."""
    v = validate_finite_float(name, fn, value)
    if v < 0.0:
        raise ValueError(f"{fn}: {name} must be >= 0; got {v}")
    return v


def validate_unit_float(name: str, fn: str, value: Any) -> float:
    """Confirm *value* is a finite real number in ``[0, 1]``."""
    v = validate_finite_float(name, fn, value)
    if v < 0.0 or v > 1.0:
        raise ValueError(f"{fn}: {name} must be in [0, 1]; got {v}")
    return v


# Backwards-compatible alias (post_process uses "unit_interval" name).
validate_unit_interval = validate_unit_float


def validate_finite_or_none(name: str, fn: str, value: Any) -> float | None:
    """Confirm *value* is ``None`` or a finite real number."""
    if value is None:
        return None
    return validate_finite_float(name, fn, value)


def validate_positive_finite_or_none(
    name: str, fn: str, value: Any
) -> float | None:
    """Confirm *value* is ``None`` or a finite real number > 0."""
    if value is None:
        return None
    return validate_positive_float(name, fn, value)


# ---------------------------------------------------------------------------
# Tuple / sequence validators
# ---------------------------------------------------------------------------


def validate_finite_2tuple(
    name: str, fn: str, value: Any
) -> tuple[float, float]:
    """Confirm *value* is a 2-element sequence of finite real numbers."""
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__"):
        raise TypeError(
            f"{fn}: {name} must be a 2-tuple of floats; "
            f"got {type(value).__name__}"
        )
    if len(value) != 2:
        raise ValueError(
            f"{fn}: {name} must have length 2 (x, y); got length {len(value)}"
        )
    x = validate_finite_float(f"{name}[0]", fn, value[0])
    y = validate_finite_float(f"{name}[1]", fn, value[1])
    return (x, y)


def validate_positive_size_2tuple(
    name: str, fn: str, value: Any
) -> tuple[int, int]:
    """Confirm *value* is a 2-element sequence of positive ints (e.g. ``(w, h)``)."""
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__"):
        raise TypeError(
            f"{fn}: {name} must be a 2-tuple of ints; "
            f"got {type(value).__name__}"
        )
    if len(value) != 2:
        raise ValueError(
            f"{fn}: {name} must have length 2 (width, height); "
            f"got length {len(value)}"
        )
    w = validate_positive_int(f"{name}[0] (width)", fn, value[0])
    h = validate_positive_int(f"{name}[1] (height)", fn, value[1])
    return (w, h)


# ---------------------------------------------------------------------------
# Callable validator
# ---------------------------------------------------------------------------


def validate_callable(name: str, fn: str, value: Any) -> Callable:
    """Confirm *value* is callable (function, bound method, lambda, …)."""
    if not callable(value):
        raise TypeError(
            f"{fn}: {name} must be callable; got {type(value).__name__}"
        )
    return value


# Legacy alias — event_bus historically called this ``validate_callback``.
validate_callback = validate_callable


# ---------------------------------------------------------------------------
# Path validators
# ---------------------------------------------------------------------------


def validate_path_like(name: str, fn: str, value: Any) -> Path:
    """Confirm *value* is a non-empty ``str`` or :class:`Path` and return ``Path``.

    Does NOT stat the filesystem. Refuses ``bool`` and ``bytes``.
    """
    if isinstance(value, bool) or not isinstance(value, (str, Path, os.PathLike)):
        raise TypeError(
            f"{fn}: {name} must be str or pathlib.Path; "
            f"got {type(value).__name__}"
        )
    s = str(value)
    if s == "":
        raise ValueError(f"{fn}: {name} must not be empty")
    return Path(value)


# Alias — testing/tools historically called this ``validate_pathlike``.
validate_pathlike = validate_path_like


def validate_optional_path_like(
    name: str, fn: str, value: Any
) -> Path | None:
    """Confirm *value* is ``None`` or a non-empty path-like."""
    if value is None:
        return None
    return validate_path_like(name, fn, value)


def validate_existing_file_path(name: str, fn: str, value: Any) -> Path:
    """Confirm *value* points to an existing regular file (not a dir)."""
    p = validate_path_like(name, fn, value)
    if not p.exists():
        raise FileNotFoundError(
            f"{fn}: {name} not found: {os.fspath(p)!r}"
        )
    if not p.is_file():
        raise FileNotFoundError(
            f"{fn}: {name} is not a regular file: {os.fspath(p)!r}"
        )
    return p


__all__ = [
    # strings
    "validate_str",
    "validate_non_empty_str",
    "validate_optional_str",
    # bools
    "validate_bool",
    # ints
    "validate_int",
    "validate_positive_int",
    "validate_non_negative_int",
    # floats
    "validate_finite_float",
    "validate_positive_float",
    "validate_non_negative_float",
    "validate_unit_float",
    "validate_unit_interval",
    "validate_finite_or_none",
    "validate_positive_finite_or_none",
    # tuples
    "validate_finite_2tuple",
    "validate_positive_size_2tuple",
    # callables
    "validate_callable",
    "validate_callback",
    # paths
    "validate_path_like",
    "validate_pathlike",
    "validate_optional_path_like",
    "validate_existing_file_path",
]
