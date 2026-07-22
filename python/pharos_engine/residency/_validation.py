"""Internal input-validation helpers for :class:`ResidencyManager`.

Generic ``validate_finite_2tuple`` and ``validate_path_like`` (used here as
``validate_save_dir``) live in :mod:`pharos_engine._validation`. Domain
helpers (``validate_entity_list``, ``validate_entity``) stay here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pharos_engine._validation import (
    validate_finite_2tuple,
    validate_path_like,
)


def validate_entity_list(name: str, fn: str, value: Any) -> list:
    """Confirm ``value`` is a concrete sequence (list/tuple) of objects."""
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
    """Confirm ``value`` looks like an Entity: has ``.id`` and ``.layers``."""
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
    """Confirm ``value`` is a ``str`` or ``Path`` usable as a directory."""
    return validate_path_like(name, fn, value)


__all__ = [
    "validate_finite_2tuple",
    "validate_entity_list",
    "validate_entity",
    "validate_save_dir",
]
