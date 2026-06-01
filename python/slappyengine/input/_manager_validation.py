"""Internal input-validation helpers for the :class:`InputManager` public API.

Shared rejection logic for :meth:`InputManager.key_held`,
:meth:`InputManager.key_just_pressed`, :meth:`InputManager.key_just_released`,
:meth:`InputManager.axis`, and :meth:`InputManager.button`. Event-callback
internals (``_on_key_event`` / ``_on_pointer_event``) are wired by the
rendercanvas backend and trust their dispatcher.

Engineering policy (hardening round 9): validate at the public boundary;
the per-frame state sets trust their string keys. O(1) checks only — these
run on every key query in the game loop.

Silent-acceptance bugs found and refused here:

* ``key_held(b"a")`` — ``bytes.lower()`` returns ``bytes``, which then
  never matches the ``str`` keys in ``_held``. The query silently returns
  ``False`` forever.
* ``axis(gamepad_id, -1)`` — ``-1 < len(axes)`` is true, then ``axes[-1]``
  returns the LAST axis. Silent wrong-result, not a clean ``0.0``.
* ``axis(True, 0)`` — ``True`` silently becomes joystick id ``1``.
* ``button(0, True)`` — ``True`` silently becomes button index ``1``.
"""
from __future__ import annotations

from typing import Any


def validate_key_name(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a non-empty ``str`` key identifier.

    Empty strings would route to the no-key sentinel that ``_on_key_event``
    early-returns on, so a query for ``""`` would silently always return
    ``False`` — refuse so the typo surfaces.

    Raises
    ------
    TypeError
        If ``value`` is not a ``str`` (``bytes`` refused — ``bytes.lower()``
        returns ``bytes`` which silently never matches the ``str`` keys held
        in the manager state).
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


def validate_nonneg_int(name: str, fn: str, value: Any) -> int:
    """Confirm ``value`` is a plain ``int`` >= 0 (refuses ``bool``).

    Used for ``gamepad_id`` / ``axis_index`` / ``btn_index``. A negative
    index silently returns the LAST element of the GLFW axes/buttons tuple
    via Python's negative-indexing — a wrong-result bug, not a clean
    "no such gamepad" zero return.

    Raises
    ------
    TypeError
        If ``value`` is not a plain ``int`` (``bool`` refused — ``axis(True, 0)``
        silently meaning ``gamepad_id=1`` is almost certainly a bug).
    ValueError
        If ``value < 0``.
    """
    # bool is a subclass of int; refuse it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"{fn}: {name} must be an int; got {type(value).__name__}"
        )
    if value < 0:
        raise ValueError(f"{fn}: {name} must be >= 0; got {value}")
    return value


__all__ = [
    "validate_key_name",
    "validate_nonneg_int",
]
