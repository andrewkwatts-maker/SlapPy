"""Internal input-validation helpers for the :mod:`slappyengine.strata` API.

Shared rejection logic for :class:`StrataLayer` and :class:`StrataWorld`
constructors and the ``set_active`` / ``get_layer`` / ``tick`` /
``begin_phase`` / ``end_phase`` methods.

Engineering policy: validate at the public boundary; the render-time tint
and alpha math below trust their inputs. O(1) checks only. Don't silently
coerce — a NaN ``tint`` channel would propagate through the entity
shader as fully black/transparent every frame after, and ``set_active``
taking ``True`` would silently mean "active layer 1" (often a typo for
``set_active(1)`` when copy-pasting from a boolean flag).
"""
from __future__ import annotations

import math
from typing import Any


def validate_non_empty_str(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a non-empty ``str``.

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


def validate_non_negative_int(name: str, fn: str, value: Any) -> int:
    """Confirm ``value`` is a plain ``int`` ≥ 0 (refuses ``bool`` and floats).

    Used for ``StrataLayer.index`` and ``StrataWorld.set_active`` /
    ``get_layer`` arguments. ``bool`` would silently slip past ``isinstance
    (..., int)`` and store ``True`` as the layer index, breaking equality
    checks against entity ``strata_layer`` ints downstream.

    Raises
    ------
    TypeError
        If ``value`` is not a plain ``int``.
    ValueError
        If ``value < 0``.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"{fn}: {name} must be an int; got {type(value).__name__}"
        )
    if value < 0:
        raise ValueError(f"{fn}: {name} must be >= 0; got {value}")
    return value


def validate_finite_float(name: str, fn: str, value: Any) -> float:
    """Confirm ``value`` is a finite real number (NaN/inf refused).

    Used for ``StrataLayer.parallax`` and :meth:`StrataWorld.tick` ``dt``.

    Raises
    ------
    TypeError
        If ``value`` is not a real number (bool refused).
    ValueError
        If ``value`` is NaN/inf.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{fn}: {name} must be a real number; got {type(value).__name__}"
        )
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{fn}: {name} must be finite; got {v!r}")
    return v


def validate_unit_float(name: str, fn: str, value: Any) -> float:
    """Confirm ``value`` is a finite real number in ``[0, 1]``.

    Used for ``StrataWorld.inactive_dim`` — the alpha multiplier for
    entities on inactive layers. A NaN here would silently render every
    inactive entity at NaN alpha (renders as fully opaque on some shaders,
    fully transparent on others). > 1 would over-brighten the inactive
    layer until it outshines the active layer — almost certainly a typo.

    Raises
    ------
    TypeError
        If ``value`` is not a real number (bool refused).
    ValueError
        If ``value`` is NaN/inf, < 0, or > 1.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{fn}: {name} must be a real number; got {type(value).__name__}"
        )
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{fn}: {name} must be finite; got {v!r}")
    if v < 0.0 or v > 1.0:
        raise ValueError(f"{fn}: {name} must be in [0, 1]; got {v}")
    return v


def validate_rgba_tuple(name: str, fn: str, value: Any) -> tuple[float, float, float, float]:
    """Confirm ``value`` is a 4-element sequence of finite real numbers.

    Used for ``StrataLayer.tint``. The renderer multiplies the sprite RGBA
    by this tuple, so a 3-tuple (e.g. ``(1.0, 1.0, 1.0)``) would silently
    drop the alpha channel and the shader would index out-of-bounds. NaN
    in any channel propagates through the multiply to give garbage colour.

    Raises
    ------
    TypeError
        If ``value`` is not a 4-element sequence, or members aren't numeric
        (bool refused).
    ValueError
        If the length isn't 4 or any element is NaN/inf.
    """
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__"):
        raise TypeError(
            f"{fn}: {name} must be a 4-tuple of floats; "
            f"got {type(value).__name__}"
        )
    if len(value) != 4:
        raise ValueError(
            f"{fn}: {name} must have length 4 (r, g, b, a); "
            f"got length {len(value)}"
        )
    out: list[float] = []
    for i, ch in enumerate(value):
        if isinstance(ch, bool) or not isinstance(ch, (int, float)):
            raise TypeError(
                f"{fn}: {name}[{i}] must be a real number; "
                f"got {type(ch).__name__}"
            )
        fv = float(ch)
        if not math.isfinite(fv):
            raise ValueError(
                f"{fn}: {name}[{i}] must be finite; got {fv!r}"
            )
        out.append(fv)
    return (out[0], out[1], out[2], out[3])


def validate_layer_list(name: str, fn: str, value: Any) -> list:
    """Confirm ``value`` is a non-empty list of :class:`StrataLayer`.

    An empty list would let :class:`StrataWorld` construct, then crash with
    ``IndexError`` inside ``active_layer`` on the first frame, and the
    ``set_active(n)`` modulo would :class:`ZeroDivisionError`. Refuse here
    so the authoring error is obvious at construction.

    Raises
    ------
    TypeError
        If ``value`` is not a list/tuple, or any element isn't a
        :class:`StrataLayer`.
    ValueError
        If ``value`` is empty.
    """
    # Import locally to avoid the strata → validation module cycle.
    from slappyengine.strata import StrataLayer

    if not isinstance(value, (list, tuple)):
        raise TypeError(
            f"{fn}: {name} must be a list of StrataLayer; "
            f"got {type(value).__name__}"
        )
    if len(value) == 0:
        raise ValueError(f"{fn}: {name} must be non-empty")
    for i, item in enumerate(value):
        if not isinstance(item, StrataLayer):
            raise TypeError(
                f"{fn}: {name}[{i}] must be a StrataLayer; "
                f"got {type(item).__name__}"
            )
    return list(value)


def validate_entity_arg(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` is non-``None`` and ``id()``-able for phase tracking.

    The phase-transition map keys on ``id(entity)``; ``None`` passing
    through would silently key on ``id(None)`` which is a process-wide
    singleton and would make every "phase out" call collide.

    Raises
    ------
    TypeError
        If ``value`` is ``None``.
    """
    if value is None:
        raise TypeError(f"{fn}: {name} must not be None")
    return value


__all__ = [
    "validate_non_empty_str",
    "validate_non_negative_int",
    "validate_finite_float",
    "validate_unit_float",
    "validate_rgba_tuple",
    "validate_layer_list",
    "validate_entity_arg",
]
