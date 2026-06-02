"""Internal input-validation helpers for the :class:`InputManager` public API.

Generic ``validate_non_negative_int`` (re-exported as ``validate_nonneg_int``
for legacy callers) lives in :mod:`slappyengine._validation`. Domain-specific
``validate_key_name`` stays here.
"""
from __future__ import annotations

from typing import Any

from slappyengine._validation import (
    validate_non_negative_int as validate_nonneg_int,
)


def validate_key_name(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a non-empty ``str`` key identifier.

    ``bytes`` are refused because ``bytes.lower()`` returns ``bytes`` which
    silently never matches the ``str`` keys held in the manager state.
    """
    if not isinstance(value, str):
        raise TypeError(
            f"{fn}: {name} must be a str; got {type(value).__name__}"
        )
    if not value:
        raise ValueError(f"{fn}: {name} must be non-empty")
    return value


__all__ = [
    "validate_key_name",
    "validate_nonneg_int",
]
