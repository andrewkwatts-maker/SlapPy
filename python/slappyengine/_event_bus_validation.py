"""Internal input-validation helpers for the :class:`EventBus` public API.

Generic ``validate_callback`` lives in :mod:`slappyengine._validation` and
is re-exported. Domain-specific ``validate_event_type`` (non-empty event
identifier) and ``validate_bus_or_none`` stay here.
"""
from __future__ import annotations

from typing import Any

from slappyengine._validation import validate_callback


def validate_event_type(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a non-empty ``str`` event-type identifier."""
    if not isinstance(value, str):
        raise TypeError(
            f"{fn}: {name} must be a str; got {type(value).__name__}"
        )
    if not value:
        raise ValueError(f"{fn}: {name} must be non-empty")
    return value


def validate_event_type_or_none(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` is ``None`` or a non-empty ``str`` event type."""
    if value is None:
        return None
    return validate_event_type(name, fn, value)


def validate_bus_or_none(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` is ``None`` or an :class:`EventBus` instance."""
    if value is None:
        return None
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
