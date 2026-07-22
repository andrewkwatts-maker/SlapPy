"""Internal input-validation helpers for the :class:`AssetDatabase` public API.

Generic ``validate_callable`` and ``validate_bool`` live in
:mod:`pharos_engine._validation`. ``validate_path_like`` is the shared
non-empty path validator (re-exported here as ``validate_path_like``).
Domain-specific ``validate_extension`` (the ``.ext`` format check) stays here.
"""
from __future__ import annotations

from typing import Any

from pharos_engine._validation import (
    validate_callable,
    validate_path_like,
)


def validate_bool(name: str, fn: str, value: Any) -> bool:
    """Confirm ``value`` is exactly a ``bool``.

    Domain-specific message (``"must be bool"``, without the leading "a")
    preserved for legacy assetdb callers; see
    ``pharos_engine._validation.validate_bool`` for the canonical form.
    """
    if not isinstance(value, bool):
        raise TypeError(
            f"{fn}: {name} must be bool; got {type(value).__name__}"
        )
    return value


def validate_extension(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a non-empty extension string starting with ``.``."""
    if isinstance(value, bool) or not isinstance(value, str):
        raise TypeError(
            f"{fn}: {name} must be a str; got {type(value).__name__}"
        )
    if value == "":
        raise ValueError(f"{fn}: {name} must not be empty")
    if not value.startswith("."):
        raise ValueError(
            f"{fn}: {name} must start with '.' (e.g. '.png'); got {value!r}"
        )
    if "/" in value or "\\" in value:
        raise ValueError(
            f"{fn}: {name} must be a bare extension, not a path; got {value!r}"
        )
    if len(value) < 2:
        raise ValueError(
            f"{fn}: {name} must include at least one char after '.'; got {value!r}"
        )
    if any(c.isspace() for c in value):
        raise ValueError(
            f"{fn}: {name} must not contain whitespace; got {value!r}"
        )
    return value.lower()


__all__ = [
    "validate_path_like",
    "validate_extension",
    "validate_callable",
    "validate_bool",
]
