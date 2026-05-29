"""Internal input-validation helpers for the :class:`EventBus` public API.

Shared rejection logic for :meth:`EventBus.publish`, :meth:`EventBus.subscribe`,
:meth:`EventBus.unsubscribe`, :meth:`EventBus.once`, and :meth:`EventBus.on`.

Engineering policy: validate at the public boundary; ``_listeners`` dispatch
trusts its keys. O(1) checks only — never iterate the subscriber list here.
"""
from __future__ import annotations

from typing import Any


def validate_event_type(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a non-empty ``str`` event-type identifier.

    Empty strings would silently subscribe / publish to a sentinel bucket
    that nothing else could ever address — almost certainly a bug.

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


def validate_callback(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` is callable (function, bound method, lambda, …).

    Raises
    ------
    TypeError
        If ``value`` is not callable.
    """
    if not callable(value):
        raise TypeError(
            f"{fn}: {name} must be callable; got {type(value).__name__}"
        )
    return value


__all__ = [
    "validate_event_type",
    "validate_callback",
]
