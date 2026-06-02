"""Internal input-validation helpers for ``slappyengine.tools.sprite_audit``.

Generic ``validate_pathlike`` and ``validate_positive_int`` live in
:mod:`slappyengine._validation`. Domain-specific ``validate_pattern_list``,
``validate_rgba_tuple`` (int [0, 255] channel range — distinct from the
strata float [0, 1] tint), and ``validate_inventory_entry`` stay here.
"""
from __future__ import annotations

from typing import Any

from slappyengine._validation import (
    validate_pathlike,
    validate_positive_int,
)


def validate_pattern_list(name: str, fn: str, value: Any) -> list[str]:
    """Confirm ``value`` is a ``list`` of ``str`` glob patterns."""
    if isinstance(value, (str, bytes)):
        raise TypeError(
            f"{fn}: {name} must be a list of str; got a single "
            f"{type(value).__name__} (did you forget the brackets?)"
        )
    if not isinstance(value, list):
        raise TypeError(
            f"{fn}: {name} must be a list; got {type(value).__name__}"
        )
    for i, p in enumerate(value):
        if not isinstance(p, str):
            raise TypeError(
                f"{fn}: {name}[{i}] must be a str; got {type(p).__name__}"
            )
    return value


def validate_rgba_tuple(name: str, fn: str, value: Any) -> tuple[int, int, int, int]:
    """Confirm ``value`` is a 4-tuple/list of ints in ``[0, 255]``."""
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__"):
        raise TypeError(
            f"{fn}: {name} must be a 4-tuple of ints; "
            f"got {type(value).__name__}"
        )
    if len(value) != 4:
        raise ValueError(
            f"{fn}: {name} must have length 4 (R, G, B, A); "
            f"got length {len(value)}"
        )
    out: list[int] = []
    for i, v in enumerate(value):
        if isinstance(v, bool) or not isinstance(v, int):
            raise TypeError(
                f"{fn}: {name}[{i}] must be an int; got {type(v).__name__}"
            )
        if v < 0 or v > 255:
            raise ValueError(
                f"{fn}: {name}[{i}] must be in [0, 255]; got {v}"
            )
        out.append(v)
    return (out[0], out[1], out[2], out[3])


def validate_inventory_entry(fn: str, value: Any) -> Any:
    """Confirm ``value`` is a :class:`SpriteInventoryEntry`-shaped object."""
    required = ("alpha_coverage", "mean_rgb", "width", "height")
    missing = [m for m in required if not hasattr(value, m)]
    if missing:
        raise TypeError(
            f"{fn}: entry must be a SpriteInventoryEntry (or compatible); "
            f"got {type(value).__name__} missing {missing}"
        )
    return value


__all__ = [
    "validate_pathlike",
    "validate_pattern_list",
    "validate_positive_int",
    "validate_rgba_tuple",
    "validate_inventory_entry",
]
