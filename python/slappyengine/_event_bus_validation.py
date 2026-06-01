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


def validate_event_type_or_none(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` is ``None`` or a non-empty ``str`` event type.

    Used by :meth:`EventBus.clear` whose ``None`` sentinel clears all
    listeners. A non-``None`` non-``str`` would silently no-op
    (``dict.pop(non_str, None)``) — refuse so the typo surfaces.

    Raises
    ------
    TypeError
        If ``value`` is not ``None`` and not a ``str``.
    ValueError
        If ``value`` is the empty string.
    """
    if value is None:
        return None
    return validate_event_type(name, fn, value)


def validate_bus_or_none(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` is ``None`` or an :class:`EventBus` instance.

    Used by :class:`Observable.__init__`. A fake bus duck-typing with a
    ``publish`` attribute would silently route events into the void;
    refuse so the constructor crashes at the assignment site.

    Raises
    ------
    TypeError
        If ``value`` is not ``None`` and not an :class:`EventBus`.
    """
    if value is None:
        return None
    # Local import to avoid module-level cycle (event_bus imports this file).
    from slappyengine.event_bus import EventBus

    if not isinstance(value, EventBus):
        raise TypeError(
            f"{fn}: {name} must be an EventBus or None; "
            f"got {type(value).__name__}"
        )
    return value


__all__ = [
    "validate_event_type",
    "validate_event_type_or_none",
    "validate_callback",
    "validate_bus_or_none",
]
