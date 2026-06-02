"""Internal input-validation helpers for the :class:`ActionMap` public API.

``validate_action_name`` delegates to the shared ``validate_non_empty_str``;
``validate_keys_arg`` (single str or non-empty iterable of strs) stays here
because it has bespoke per-element rules.
"""
from __future__ import annotations

from typing import Any

from slappyengine._validation import validate_non_empty_str


def validate_action_name(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a non-empty ``str`` action identifier."""
    return validate_non_empty_str(name, fn, value)


def validate_keys_arg(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` is a non-empty key spec (str or non-empty iterable of strs)."""
    if isinstance(value, str):
        if not value:
            raise ValueError(f"{fn}: {name} must be non-empty")
        return value

    if isinstance(value, (bytes, bytearray)):
        raise TypeError(
            f"{fn}: {name} must be a str or iterable of str; "
            f"got {type(value).__name__}"
        )

    if not hasattr(value, "__iter__"):
        raise TypeError(
            f"{fn}: {name} must be a str or iterable of str; "
            f"got {type(value).__name__}"
        )

    try:
        items = list(value)
    except TypeError as exc:
        raise TypeError(
            f"{fn}: {name} must be a str or iterable of str; "
            f"got {type(value).__name__}"
        ) from exc

    if not items:
        raise ValueError(f"{fn}: {name} must be non-empty (got empty iterable)")
    for i, k in enumerate(items):
        if not isinstance(k, str):
            raise TypeError(
                f"{fn}: {name}[{i}] must be a str; got {type(k).__name__}"
            )
        if not k:
            raise ValueError(f"{fn}: {name}[{i}] must be non-empty")
    return items


__all__ = [
    "validate_action_name",
    "validate_keys_arg",
]
