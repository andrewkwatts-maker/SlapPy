"""Internal input-validation helpers for the ``Layer`` public API.

Shared rejection logic for :class:`Layer`, :class:`Layer2D`, :class:`Layer3D`
constructors and the ``from_image`` / ``blank`` / ``bake_to_2d`` /
``apply_heightmap`` classmethods.

Generic validators live in :mod:`pharos_engine._validation` and are
re-exported here for backwards compatibility. This file keeps the
domain-specific ``validate_layer_mode``, ``validate_struct_fields``, and
``validate_layer_arg`` checks.
"""
from __future__ import annotations

from typing import Any

from pharos_engine._validation import (
    validate_existing_file_path,
    validate_finite_float,
    validate_positive_int,
    validate_positive_size_2tuple,
    validate_str,
)


_VALID_MODES = frozenset({"2D", "3D"})


def validate_layer_mode(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is one of the allowed Layer modes (``"2D"`` / ``"3D"``)."""
    if not isinstance(value, str):
        raise TypeError(
            f"{fn}: {name} must be a str; got {type(value).__name__}"
        )
    if value not in _VALID_MODES:
        raise ValueError(
            f"{fn}: {name} must be one of {sorted(_VALID_MODES)}; got {value!r}"
        )
    return value


def validate_struct_fields(name: str, fn: str, value: Any) -> list:
    """Confirm ``value`` is a non-empty list/tuple of ``str`` field names."""
    if not isinstance(value, (list, tuple)):
        raise TypeError(
            f"{fn}: {name} must be a list/tuple of str; "
            f"got {type(value).__name__}"
        )
    if len(value) == 0:
        raise ValueError(f"{fn}: {name} must be non-empty")
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise TypeError(
                f"{fn}: {name}[{i}] must be a str; got {type(item).__name__}"
            )
    return list(value)


def validate_layer_arg(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` is a :class:`Layer` instance."""
    from pharos_engine.layer import Layer

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
    "validate_struct_fields",
    "validate_layer_arg",
]
