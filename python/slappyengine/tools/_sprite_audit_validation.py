"""Internal input-validation helpers for ``slappyengine.tools.sprite_audit``.

Shared rejection logic for the inventory / visualisation / quality
entry points. Each helper raises with a precise message so authoring
errors surface at the boundary instead of as an opaque PIL or numpy
exception five frames deeper.

Engineering policy: O(1) checks at the boundary. Walking a directory
or opening a file is the job of the public function, not the validator.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


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


def validate_pattern_list(name: str, fn: str, value: Any) -> list[str]:
    """Confirm ``value`` is a ``list`` of ``str`` glob patterns.

    Rejects raw ``str`` (which would silently iterate per-character),
    tuples, and any element that isn't a plain ``str``.

    Raises
    ------
    TypeError
        If ``value`` is not a list, or any element is not a ``str``.
    """
    # Reject str outright — a single string would be iterated per character.
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


def validate_rgba_tuple(name: str, fn: str, value: Any) -> tuple[int, int, int, int]:
    """Confirm ``value`` is a 4-tuple/list of ints in ``[0, 255]``.

    Raises
    ------
    TypeError
        If ``value`` is not a 4-sequence or any element is not ``int``.
    ValueError
        If the sequence has the wrong length or any element is out of range.
    """
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
    """Confirm ``value`` is a :class:`SpriteInventoryEntry`-shaped object.

    Duck-typed: requires the public dataclass fields the assessor reads
    (``alpha_coverage``, ``mean_rgb``, ``width``, ``height``).

    Raises
    ------
    TypeError
        If the value is missing any required field.
    """
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
