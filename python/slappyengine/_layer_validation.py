"""Internal input-validation helpers for the ``Layer`` public API.

Shared rejection logic for :class:`Layer`, :class:`Layer2D`, :class:`Layer3D`
constructors and the ``from_image`` / ``blank`` / ``bake_to_2d`` /
``apply_heightmap`` classmethods.

Engineering policy: validate at the boundary; internal mesh / GPU code
trusts its inputs. O(1) checks only — never scan numpy buffers here.
Don't silently coerce — refuse loudly so the authoring error surfaces at
the layer-construction site instead of as a blank or garbled texture
several frames later.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any


_VALID_MODES = frozenset({"2D", "3D"})


def validate_str(name: str, fn: str, value: Any, *, allow_empty: bool = True) -> str:
    """Confirm ``value`` is a ``str`` (and optionally non-empty).

    Raises
    ------
    TypeError
        If ``value`` is not a ``str``.
    ValueError
        If ``allow_empty=False`` and ``value`` is the empty string.
    """
    if not isinstance(value, str):
        raise TypeError(
            f"{fn}: {name} must be a str; got {type(value).__name__}"
        )
    if not allow_empty and not value:
        raise ValueError(f"{fn}: {name} must be non-empty")
    return value


def validate_layer_mode(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is one of the allowed Layer modes (``"2D"`` / ``"3D"``).

    Raises
    ------
    TypeError
        If ``value`` is not a ``str``.
    ValueError
        If ``value`` is not in ``{"2D", "3D"}``.
    """
    if not isinstance(value, str):
        raise TypeError(
            f"{fn}: {name} must be a str; got {type(value).__name__}"
        )
    if value not in _VALID_MODES:
        raise ValueError(
            f"{fn}: {name} must be one of {sorted(_VALID_MODES)}; got {value!r}"
        )
    return value


def validate_positive_int(name: str, fn: str, value: Any) -> int:
    """Confirm ``value`` is an integer ≥ 1 (refuses ``bool`` and floats).

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


def validate_positive_size_2tuple(name: str, fn: str, value: Any) -> tuple[int, int]:
    """Confirm ``value`` is a 2-element sequence of positive ints.

    Raises
    ------
    TypeError
        If ``value`` is not a 2-element sequence or its members are not ints.
    ValueError
        If the length isn't 2 or any element is < 1.
    """
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
    w, h = value[0], value[1]
    if isinstance(w, bool) or not isinstance(w, int):
        raise TypeError(
            f"{fn}: {name}[0] (width) must be an int; got {type(w).__name__}"
        )
    if isinstance(h, bool) or not isinstance(h, int):
        raise TypeError(
            f"{fn}: {name}[1] (height) must be an int; got {type(h).__name__}"
        )
    if w < 1:
        raise ValueError(f"{fn}: {name}[0] (width) must be >= 1; got {w}")
    if h < 1:
        raise ValueError(f"{fn}: {name}[1] (height) must be >= 1; got {h}")
    return (w, h)


def validate_existing_file_path(name: str, fn: str, value: Any) -> Path:
    """Confirm ``value`` is a path-like pointing to an existing file.

    Raises
    ------
    TypeError
        If ``value`` is not a str or :class:`Path` (bytes refused).
    FileNotFoundError
        If the path doesn't exist or isn't a regular file.
    """
    if not isinstance(value, (str, Path)):
        raise TypeError(
            f"{fn}: {name} must be a str or Path; got {type(value).__name__}"
        )
    p = Path(value)
    if not p.exists():
        raise FileNotFoundError(
            f"{fn}: {name} not found: {os.fspath(p)!r}"
        )
    if not p.is_file():
        raise FileNotFoundError(
            f"{fn}: {name} is not a regular file: {os.fspath(p)!r}"
        )
    return p


def validate_finite_float(name: str, fn: str, value: Any) -> float:
    """Confirm ``value`` is a finite real number (NaN/inf refused).

    Raises
    ------
    TypeError
        If ``value`` is not a real number (bool refused).
    ValueError
        If ``value`` is NaN/inf.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{fn}: {name} must be a real number; got {type(value).__name__}"
        )
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{fn}: {name} must be finite; got {v!r}")
    return v


def validate_layer_arg(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` quacks like a :class:`Layer` (has ``_image_data``).

    Cheap structural check — refuses ``None``, ``dict``, raw ndarrays, etc.,
    that would silently produce blank output two stack frames later.

    Raises
    ------
    TypeError
        If ``value`` does not expose the ``_image_data`` attribute that
        downstream baking code relies on.
    """
    # Import locally to avoid the layer module → validation module cycle.
    from slappyengine.layer import Layer

    if not isinstance(value, Layer):
        raise TypeError(
            f"{fn}: {name} must be a Layer/Layer2D/Layer3D; "
            f"got {type(value).__name__}"
        )
    return value


__all__ = [
    "validate_str",
    "validate_layer_mode",
    "validate_positive_int",
    "validate_positive_size_2tuple",
    "validate_existing_file_path",
    "validate_finite_float",
    "validate_layer_arg",
]
