"""Internal input-validation helpers for the :class:`ResidencyManager` public
boundary.

Shared rejection logic for ``__init__`` / ``update`` / ``tier`` / ``evict_*``
/ ``prefetch``. The internal tier transitions trust their inputs.

Engineering policy: O(1) checks only. Don't silently coerce — letting a
non-finite ``camera_pos`` through would compute a NaN distance for every
entity and tier them all to DISK on the next frame. Reject at the boundary.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any


def validate_finite_2tuple(name: str, fn: str, value: Any) -> tuple[float, float]:
    """Confirm ``value`` is a 2-element sequence of finite real numbers.

    Raises
    ------
    TypeError
        If ``value`` is not a 2-element sequence or members aren't numeric.
    ValueError
        If the length isn't 2 or any element is NaN/inf.
    """
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__"):
        raise TypeError(
            f"{fn}: {name} must be a 2-tuple of floats; "
            f"got {type(value).__name__}"
        )
    if len(value) != 2:
        raise ValueError(
            f"{fn}: {name} must have length 2 (x, y); got length {len(value)}"
        )
    x, y = value[0], value[1]
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise TypeError(
            f"{fn}: {name}[0] must be a real number; got {type(x).__name__}"
        )
    if isinstance(y, bool) or not isinstance(y, (int, float)):
        raise TypeError(
            f"{fn}: {name}[1] must be a real number; got {type(y).__name__}"
        )
    fx, fy = float(x), float(y)
    if not math.isfinite(fx):
        raise ValueError(f"{fn}: {name}[0] must be finite; got {fx!r}")
    if not math.isfinite(fy):
        raise ValueError(f"{fn}: {name}[1] must be finite; got {fy!r}")
    return (fx, fy)


def validate_entity_list(name: str, fn: str, value: Any) -> list:
    """Confirm ``value`` is a concrete sequence (list/tuple) of objects.

    A bare generator would be consumed once silently and leave the manager
    with stale tiers on the next call. Refuse anything we can't ``len()``.

    Raises
    ------
    TypeError
        If ``value`` is not list/tuple, or is a string/bytes/mapping.
    """
    # Reject strings/bytes (iterable but obviously wrong) and dicts/sets
    # (caller probably meant ``dict.values()``).
    if isinstance(value, (str, bytes, dict, set)):
        raise TypeError(
            f"{fn}: {name} must be a list or tuple of entities; "
            f"got {type(value).__name__}"
        )
    if not isinstance(value, (list, tuple)):
        raise TypeError(
            f"{fn}: {name} must be a list or tuple of entities; "
            f"got {type(value).__name__}"
        )
    return list(value)


def validate_entity(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` looks like an Entity: has ``.id`` and ``.layers``.

    We avoid importing :class:`Entity` here to keep this module GPU-stack
    free; duck-typing is correct for the residency boundary because
    :class:`Asset` (a different base class) is the only legitimate input
    today.

    Raises
    ------
    TypeError
        If ``value`` is ``None`` or lacks the duck-typed attributes the
        manager touches.
    """
    if value is None:
        raise TypeError(f"{fn}: {name} must not be None")
    if not hasattr(value, "id"):
        raise TypeError(
            f"{fn}: {name} must have an 'id' attribute (got "
            f"{type(value).__name__})"
        )
    if not hasattr(value, "layers"):
        raise TypeError(
            f"{fn}: {name} must have a 'layers' attribute (got "
            f"{type(value).__name__})"
        )
    return value


def validate_save_dir(name: str, fn: str, value: Any) -> Path:
    """Confirm ``value`` is a ``str`` or ``Path`` usable as a directory.

    Does not create the directory — that's the caller's job (``__init__``
    already calls ``mkdir``).

    Raises
    ------
    TypeError
        If ``value`` is neither ``str`` nor ``Path``.
    ValueError
        If ``value`` is the empty string.
    """
    if isinstance(value, bool) or not isinstance(value, (str, Path)):
        raise TypeError(
            f"{fn}: {name} must be str or pathlib.Path; "
            f"got {type(value).__name__}"
        )
    if isinstance(value, str) and value == "":
        raise ValueError(f"{fn}: {name} must not be empty")
    if isinstance(value, Path) and str(value) == "":
        raise ValueError(f"{fn}: {name} must not be empty")
    return Path(value)


__all__ = [
    "validate_finite_2tuple",
    "validate_entity_list",
    "validate_entity",
    "validate_save_dir",
]
