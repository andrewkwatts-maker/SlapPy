"""Internal input-validation helpers for the :mod:`pharos_engine.audio` API.

Generic ``validate_bool``, ``validate_finite_2tuple``, and
``validate_positive_int`` live in :mod:`pharos_engine._validation` and are
re-exported. Domain-specific helpers (``validate_path``, ``validate_volume``,
``validate_master_volume``, ``validate_positive_finite_float`` for
``max_dist``, and ``validate_sound_handle_or_none``) stay here.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from pharos_engine._validation import (
    validate_bool,
    validate_finite_2tuple,
    validate_positive_int,
)


# Hard cap on per-call ``volume``; ``master_volume`` is independently clamped.
_VOLUME_MAX = 10.0


def validate_path(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a non-empty ``str`` or :class:`Path` audio path."""
    if not isinstance(value, (str, Path)):
        raise TypeError(
            f"{fn}: {name} must be a str or Path; got {type(value).__name__}"
        )
    s = str(value)
    if not s or not s.strip():
        raise ValueError(f"{fn}: {name} must be a non-empty path")
    return s


def validate_volume(name: str, fn: str, value: Any) -> float:
    """Confirm ``value`` is a finite ``volume`` scalar in ``[0, _VOLUME_MAX]``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{fn}: {name} must be a real number; got {type(value).__name__}"
        )
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{fn}: {name} must be finite; got {v!r}")
    if v < 0.0:
        raise ValueError(f"{fn}: {name} must be >= 0; got {v}")
    if v > _VOLUME_MAX:
        raise ValueError(f"{fn}: {name} must be <= {_VOLUME_MAX}; got {v}")
    return v


def validate_master_volume(name: str, fn: str, value: Any) -> float:
    """Confirm ``value`` is a finite real number suitable for ``master_volume``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{fn}: {name} must be a real number; got {type(value).__name__}"
        )
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{fn}: {name} must be finite; got {v!r}")
    return v


def validate_positive_finite_float(name: str, fn: str, value: Any) -> float:
    """Confirm ``value`` is a finite real number > 0."""
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


def validate_sound_handle_or_none(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` is a :class:`SoundHandle` or ``None``."""
    if value is None:
        return None
    from pharos_engine.audio import SoundHandle

    if not isinstance(value, SoundHandle):
        raise TypeError(
            f"{fn}: {name} must be a SoundHandle or None; "
            f"got {type(value).__name__}"
        )
    return value


__all__ = [
    "validate_path",
    "validate_volume",
    "validate_master_volume",
    "validate_bool",
    "validate_finite_2tuple",
    "validate_positive_finite_float",
    "validate_sound_handle_or_none",
    "validate_positive_int",
]
