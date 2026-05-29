"""Internal input-validation helpers for the ``telemetry`` public API.

Shared rejection logic for the pub/sub entry points (:func:`subscribe`,
:func:`emit`, :func:`set_history_capacity`, :func:`enable_pattern_index`).

Engineering policy: validate at the boundary; internal dispatch and
ring-buffer code trust their inputs. O(1) checks only — never scan
subscriber lists or payload dicts.
"""
from __future__ import annotations

from typing import Any


def validate_str(name: str, fn: str, value: Any, *, allow_empty: bool = True) -> str:
    """Confirm ``value`` is a ``str`` (and optionally non-empty).

    Raises
    ------
    TypeError
        If ``value`` is not a ``str``.
    ValueError
        If ``allow_empty=False`` and ``value`` is the empty string.
    """
    if not isinstance(value, str):
        raise TypeError(
            f"{fn}: {name} must be a str; got {type(value).__name__}"
        )
    if not allow_empty and not value:
        raise ValueError(f"{fn}: {name} must be non-empty")
    return value


def validate_callable(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` is callable (a function, bound method, lambda, …).

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


def validate_non_negative_int(name: str, fn: str, value: Any) -> int:
    """Confirm ``value`` is an integer ≥ 0.

    Floats are rejected so callers can't sneak ``2.5`` past the contract.
    ``bool`` is allowed (Python's ``True`` == 1, ``False`` == 0) only when
    the caller passed an explicit ``int`` — we reject ``bool`` here to
    keep ``set_history_capacity(True)`` from silently meaning "1".

    Raises
    ------
    TypeError
        If ``value`` is not a plain ``int``.
    ValueError
        If ``value < 0``.
    """
    # Reject bool explicitly — `isinstance(True, int)` is True, but
    # `set_history_capacity(True)` almost certainly indicates a bug.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"{fn}: {name} must be an int; got {type(value).__name__}"
        )
    if value < 0:
        raise ValueError(f"{fn}: {name} must be >= 0; got {value}")
    return value


def validate_bool(name: str, fn: str, value: Any) -> bool:
    """Confirm ``value`` is a Python ``bool`` (refuses truthy non-bools).

    Raises
    ------
    TypeError
        If ``value`` is not ``True`` or ``False``.
    """
    if not isinstance(value, bool):
        raise TypeError(
            f"{fn}: {name} must be a bool; got {type(value).__name__}"
        )
    return value


__all__ = [
    "validate_str",
    "validate_callable",
    "validate_non_negative_int",
    "validate_bool",
]
