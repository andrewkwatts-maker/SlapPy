"""Internal input-validation helpers for the :class:`Camera` public API.

Shared rejection logic for the :class:`Camera` constructor and its
``position`` / ``zoom`` property setters. Internal matrix maths trusts
its inputs.

Engineering policy: O(1) checks only. Don't silently coerce — a NaN
position would corrupt the view matrix every frame after, so refuse at
the assignment site.
"""
from __future__ import annotations

import math
from typing import Any


def validate_finite_2tuple(name: str, fn: str, value: Any) -> tuple[float, float]:
    """Confirm ``value`` is a 2-element sequence of finite real numbers.

    Raises
    ------
    TypeError
        If ``value`` is not a 2-element sequence or members aren't numeric
        (bool refused).
    ValueError
        If the length isn't 2 or any element is NaN/inf.
    """
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__"):
        raise TypeError(
            f"{fn}: {name} must be a 2-tuple of floats; "
            f"got {type(value).__name__}"
        )
    if len(value) != 2:
        raise ValueError(
            f"{fn}: {name} must have length 2 (x, y); got length {len(value)}"
        )
    x, y = value[0], value[1]
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise TypeError(
            f"{fn}: {name}[0] must be a real number; got {type(x).__name__}"
        )
    if isinstance(y, bool) or not isinstance(y, (int, float)):
        raise TypeError(
            f"{fn}: {name}[1] must be a real number; got {type(y).__name__}"
        )
    fx, fy = float(x), float(y)
    if not math.isfinite(fx):
        raise ValueError(f"{fn}: {name}[0] must be finite; got {fx!r}")
    if not math.isfinite(fy):
        raise ValueError(f"{fn}: {name}[1] must be finite; got {fy!r}")
    return (fx, fy)


def validate_positive_finite_float(name: str, fn: str, value: Any) -> float:
    """Confirm ``value`` is a finite real number > 0.

    Raises
    ------
    TypeError
        If ``value`` is not a real number (bool refused).
    ValueError
        If ``value`` is NaN/inf or ≤ 0.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{fn}: {name} must be a real number; got {type(value).__name__}"
        )
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{fn}: {name} must be finite; got {v!r}")
    if v <= 0.0:
        raise ValueError(f"{fn}: {name} must be > 0; got {v}")
    return v


def validate_lerp(name: str, fn: str, value: Any) -> float:
    """Confirm ``value`` is a finite real number in ``(0, 1]`` for ``follow``.

    A NaN ``lerp`` would silently propagate NaN into the camera position the
    very next frame, blanking the renderer. A ``lerp == 0`` would freeze the
    camera (still a likely typo for ``1.0``). Negative or > 1 would over- or
    back-shoot the entity each frame, again almost certainly a typo.

    Raises
    ------
    TypeError
        If ``value`` is not a real number (bool refused — ``True`` silently
        meaning ``lerp=1.0`` would mask the typo).
    ValueError
        If ``value`` is NaN/inf, ≤ 0, or > 1.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{fn}: {name} must be a real number; got {type(value).__name__}"
        )
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{fn}: {name} must be finite; got {v!r}")
    if v <= 0.0:
        raise ValueError(f"{fn}: {name} must be in (0, 1]; got {v}")
    if v > 1.0:
        raise ValueError(f"{fn}: {name} must be in (0, 1]; got {v}")
    return v


def validate_positive_finite_or_none(name: str, fn: str, value: Any) -> float | None:
    """Confirm ``value`` is ``None`` or a finite real number > 0.

    Used for ``screen_w`` / ``screen_h`` overrides on :meth:`Camera.follow`.
    ``None`` falls back to ``_viewport_size`` so we preserve that semantic.

    Raises
    ------
    TypeError
        If ``value`` is not ``None`` or a real number (bool refused).
    ValueError
        If ``value`` is NaN/inf or ≤ 0.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{fn}: {name} must be a real number or None; got {type(value).__name__}"
        )
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{fn}: {name} must be finite; got {v!r}")
    if v <= 0.0:
        raise ValueError(f"{fn}: {name} must be > 0; got {v}")
    return v


def validate_follow_target(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` exposes a ``position`` attribute usable by ``follow``.

    The :meth:`Camera.follow` method dereferences ``entity.position[0]`` and
    ``entity.position[1]`` once per frame. ``None`` or an object missing the
    attribute would raise inside the hot loop with a confusing traceback;
    refusing at the boundary makes the authoring error obvious.

    Raises
    ------
    TypeError
        If ``value`` lacks a ``position`` attribute, or that attribute is not
        a 2-element subscriptable sequence of finite numbers.
    ValueError
        If ``value.position`` has wrong length or contains NaN/inf.
    """
    if value is None or not hasattr(value, "position"):
        raise TypeError(
            f"{fn}: {name} must be an object with a `.position` attribute; "
            f"got {type(value).__name__}"
        )
    pos = value.position
    if isinstance(pos, (str, bytes)) or not hasattr(pos, "__len__"):
        raise TypeError(
            f"{fn}: {name}.position must be a 2-element sequence; "
            f"got {type(pos).__name__}"
        )
    if len(pos) < 2:
        raise ValueError(
            f"{fn}: {name}.position must have length >= 2; got length {len(pos)}"
        )
    x, y = pos[0], pos[1]
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise TypeError(
            f"{fn}: {name}.position[0] must be a real number; "
            f"got {type(x).__name__}"
        )
    if isinstance(y, bool) or not isinstance(y, (int, float)):
        raise TypeError(
            f"{fn}: {name}.position[1] must be a real number; "
            f"got {type(y).__name__}"
        )
    if not math.isfinite(float(x)):
        raise ValueError(
            f"{fn}: {name}.position[0] must be finite; got {x!r}"
        )
    if not math.isfinite(float(y)):
        raise ValueError(
            f"{fn}: {name}.position[1] must be finite; got {y!r}"
        )
    return value


__all__ = [
    "validate_finite_2tuple",
    "validate_positive_finite_float",
    "validate_lerp",
    "validate_positive_finite_or_none",
    "validate_follow_target",
]
