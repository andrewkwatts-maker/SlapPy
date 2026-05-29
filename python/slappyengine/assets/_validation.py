"""Internal input-validation helpers for the :class:`AssetDatabase` public API.

Shared rejection logic for the ``load`` / ``register_handler`` / ``watch`` /
``get_record`` boundaries. Internal cache lookups trust their inputs.

Engineering policy: O(1) checks only. Don't silently coerce — feeding
``Path(123)`` into ``load`` would resolve to a CWD-relative junk path, then
``os.stat`` would raise ``FileNotFoundError`` with no hint about the real
mistake. Reject at the assignment site.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


def validate_path_like(name: str, fn: str, value: Any) -> Path:
    """Confirm ``value`` is a non-empty ``str`` or ``pathlib.Path``.

    Returns a ``Path`` instance for downstream use. Does **not** stat the
    filesystem — that's the caller's job.

    Raises
    ------
    TypeError
        If ``value`` is neither ``str`` nor ``Path`` (``bytes`` refused —
        ``Path(b"x")`` is platform-dependent on Windows).
    ValueError
        If ``value`` is the empty string / empty path.
    """
    if isinstance(value, bool) or not isinstance(value, (str, Path)):
        raise TypeError(
            f"{fn}: {name} must be str or pathlib.Path; "
            f"got {type(value).__name__}"
        )
    if isinstance(value, str) and value == "":
        raise ValueError(f"{fn}: {name} must not be empty")
    if isinstance(value, Path) and str(value) == "":
        raise ValueError(f"{fn}: {name} must not be empty")
    return Path(value)


def validate_extension(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a non-empty extension string starting with ``.``.

    Returns the lower-cased extension so callers don't have to re-normalise.

    Raises
    ------
    TypeError
        If ``value`` is not a ``str``.
    ValueError
        If ``value`` is empty, doesn't start with ``.``, contains a path
        separator, or contains whitespace.
    """
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
    # An extension of just "." or with embedded whitespace is meaningless.
    if len(value) < 2:
        raise ValueError(
            f"{fn}: {name} must include at least one char after '.'; got {value!r}"
        )
    if any(c.isspace() for c in value):
        raise ValueError(
            f"{fn}: {name} must not contain whitespace; got {value!r}"
        )
    return value.lower()


def validate_callable(name: str, fn: str, value: Any) -> Callable:
    """Confirm ``value`` is callable.

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


def validate_bool(name: str, fn: str, value: Any) -> bool:
    """Confirm ``value`` is exactly a ``bool``.

    Refuses truthy ints like ``1`` because that silently widens the contract
    (``force_reload=1`` works only by Python's int↔bool conflation).

    Raises
    ------
    TypeError
        If ``value`` is not ``bool``.
    """
    if not isinstance(value, bool):
        raise TypeError(
            f"{fn}: {name} must be bool; got {type(value).__name__}"
        )
    return value


__all__ = [
    "validate_path_like",
    "validate_extension",
    "validate_callable",
    "validate_bool",
]
