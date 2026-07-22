"""Internal input-validation helpers for the :class:`Asset` public API.

Generic ``validate_finite_2tuple``, ``validate_positive_size_2tuple``, and
``validate_existing_file_path`` live in :mod:`pharos_engine._validation`.
``validate_optional_output_path`` delegates to the shared
``validate_optional_path_like``. Asset-specific helpers stay here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pharos_engine._validation import (
    validate_existing_file_path,
    validate_finite_2tuple,
    validate_positive_size_2tuple,
)


def validate_name(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a ``str`` (empty allowed — Asset accepts "")."""
    if isinstance(value, bool) or not isinstance(value, str):
        raise TypeError(
            f"{fn}: {name} must be a str; got {type(value).__name__}"
        )
    return value


def validate_node_material(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` is a :class:`NodeMaterial` instance."""
    from pharos_engine.material.node_material import NodeMaterial

    if not isinstance(value, NodeMaterial):
        raise TypeError(
            f"{fn}: {name} must be a NodeMaterial; "
            f"got {type(value).__name__}"
        )
    return value


def validate_blend(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a non-empty ``str`` blend mode tag."""
    if isinstance(value, bool) or not isinstance(value, str):
        raise TypeError(
            f"{fn}: {name} must be a str; got {type(value).__name__}"
        )
    if value == "":
        raise ValueError(f"{fn}: {name} must not be empty")
    return value


def validate_layer_arg(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` is a :class:`Layer` instance."""
    from pharos_engine.layer import Layer

    if not isinstance(value, Layer):
        raise TypeError(
            f"{fn}: {name} must be a Layer/Layer2D/Layer3D; "
            f"got {type(value).__name__}"
        )
    return value


def validate_optional_name(name: str, fn: str, value: Any) -> str | None:
    """Confirm ``value`` is ``None`` or a ``str``."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, str):
        raise TypeError(
            f"{fn}: {name} must be a str or None; got {type(value).__name__}"
        )
    return value


def validate_optional_output_path(name: str, fn: str, value: Any) -> Path | None:
    """Confirm ``value`` is ``None`` or a non-empty ``str``/``Path``.

    Domain-specific error message preserved for legacy callers: the test
    suite asserts on ``"must be str, pathlib.Path, or None"``, whereas the
    shared ``validate_optional_path_like`` says ``"must be str or pathlib.Path"``.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, Path)):
        raise TypeError(
            f"{fn}: {name} must be str, pathlib.Path, or None; "
            f"got {type(value).__name__}"
        )
    if isinstance(value, str) and value == "":
        raise ValueError(f"{fn}: {name} must not be empty")
    if isinstance(value, Path) and str(value) == "":
        raise ValueError(f"{fn}: {name} must not be empty")
    return Path(value)


__all__ = [
    "validate_name",
    "validate_finite_2tuple",
    "validate_positive_size_2tuple",
    "validate_node_material",
    "validate_blend",
    "validate_layer_arg",
    "validate_existing_file_path",
    "validate_optional_name",
    "validate_optional_output_path",
]
