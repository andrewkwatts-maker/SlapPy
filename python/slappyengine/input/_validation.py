"""Internal input-validation helpers for the :class:`ActionMap` public API.

Shared rejection logic for :meth:`ActionMap.bind`, :meth:`ActionMap.unbind`,
:meth:`ActionMap.bind_axis`, :meth:`ActionMap.from_dict`. Internal
press/release dispatch trusts its inputs.

Engineering policy: O(1) checks only. ``bind("", "w")`` would silently
register an unaddressable action — refuse loudly so the typo surfaces
at the call site instead of as "input not responding" at runtime.
"""
from __future__ import annotations

from typing import Any


def validate_action_name(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a non-empty ``str`` action identifier.

    Raises
    ------
    TypeError
        If ``value`` is not a ``str`` (bytes refused).
    ValueError
        If ``value`` is the empty string.
    """
    if not isinstance(value, str):
        raise TypeError(
            f"{fn}: {name} must be a str; got {type(value).__name__}"
        )
    if not value:
        raise ValueError(f"{fn}: {name} must be non-empty")
    return value


def validate_keys_arg(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` is a non-empty key spec (str or non-empty iterable of strs).

    ``ActionMap.bind`` historically takes a single ``str`` key.  A ``str``
    is technically iterable, so we accept it as a single key.  An iterable
    of strings (list/tuple of key names) is also accepted but each member
    must be a non-empty ``str``.

    Raises
    ------
    TypeError
        If ``value`` is not a ``str`` or a non-string iterable of ``str``.
    ValueError
        If ``value`` is empty (empty string, empty list, …) or contains
        an empty-string entry.
    """
    # Single-string fast path — historical contract.
    if isinstance(value, str):
        if not value:
            raise ValueError(f"{fn}: {name} must be non-empty")
        return value

    # bytes refused — would iterate per-byte and look "valid"
    if isinstance(value, (bytes, bytearray)):
        raise TypeError(
            f"{fn}: {name} must be a str or iterable of str; "
            f"got {type(value).__name__}"
        )

    # Non-string iterable — list/tuple/set of keys.
    if not hasattr(value, "__iter__"):
        raise TypeError(
            f"{fn}: {name} must be a str or iterable of str; "
            f"got {type(value).__name__}"
        )

    # Need to materialise once to count + validate. Caller passes small lists.
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
