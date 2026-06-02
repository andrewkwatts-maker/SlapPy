"""Internal input-validation helpers for the dynamics public API.

Generic ``validate_finite_2tuple``, ``validate_positive_int``,
``validate_positive_float``, ``validate_non_negative_float`` live in
:mod:`slappyengine._validation` and are wrapped under domain-friendly
names here. ``validate_world``, ``validate_body``, ``validate_joint`` are
duck-typed checks for dynamics types and stay here.
"""
from __future__ import annotations

from typing import Any

from slappyengine._validation import (
    validate_finite_2tuple,
    validate_non_negative_float,
    validate_positive_float,
    validate_positive_int,
)


_SOLVER_ITERATIONS_MAX = 100
_DT_MAX = 1.0


def validate_anchor(name: str, fn: str, anchor: Any) -> tuple[float, float]:
    """Coerce ``anchor`` to a 2-tuple of finite floats."""
    return validate_finite_2tuple(name, fn, anchor)


def validate_gravity(name: str, fn: str, value: Any) -> tuple[float, float]:
    """Coerce ``value`` to a 2-tuple of finite floats for ``World.gravity``."""
    return validate_finite_2tuple(name, fn, value)


def validate_position(name: str, fn: str, value: Any) -> tuple[float, float]:
    """Coerce ``value`` to a 2-tuple of finite floats for a node position."""
    return validate_finite_2tuple(name, fn, value)


def validate_solver_iterations(name: str, fn: str, value: Any) -> int:
    """Confirm ``value`` is an ``int`` in ``[1, _SOLVER_ITERATIONS_MAX]``."""
    return validate_positive_int(name, fn, value, maximum=_SOLVER_ITERATIONS_MAX)


def validate_dt(name: str, fn: str, value: Any) -> float:
    """Confirm ``value`` is a finite float in ``(0, _DT_MAX]``."""
    v = validate_positive_float(name, fn, value)
    if v > _DT_MAX:
        raise ValueError(f"{fn}: {name} must be <= {_DT_MAX}; got {v}")
    return v


def validate_mass(name: str, fn: str, value: Any) -> float:
    """Confirm ``value`` is a finite, non-negative float for a node mass."""
    return validate_non_negative_float(name, fn, value)


def validate_world(fn: str, world: Any) -> None:
    """Confirm ``world`` is a :class:`~.world.World` (or compatible duck)."""
    from .world import World as _World

    if isinstance(world, _World):
        return
    required = ("add_nodes", "add_node", "add_joint", "register_body")
    missing = [m for m in required if not hasattr(world, m)]
    if missing:
        raise TypeError(
            f"{fn}: world must be a slappyengine.dynamics.World "
            f"(or compatible); got {type(world).__name__} missing "
            f"{missing}"
        )


def validate_body(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` is a :class:`~.body.Body` ready to register."""
    from .body import Body as _Body

    if not isinstance(value, _Body):
        raise TypeError(
            f"{fn}: {name} must be a slappyengine.dynamics.Body; "
            f"got {type(value).__name__}"
        )
    return value


def validate_joint(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` is a :class:`~.joint.JointSpec` instance."""
    from .joint import JointSpec as _JointSpec

    if not isinstance(value, _JointSpec):
        raise TypeError(
            f"{fn}: {name} must be a slappyengine.dynamics.JointSpec; "
            f"got {type(value).__name__}"
        )
    return value


__all__ = [
    "validate_anchor",
    "validate_world",
    "validate_gravity",
    "validate_solver_iterations",
    "validate_dt",
    "validate_position",
    "validate_mass",
    "validate_body",
    "validate_joint",
]
