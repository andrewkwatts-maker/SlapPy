"""Internal input-validation helpers for the dynamics public API.

These helpers are deliberately not re-exported through ``__init__``: they
exist so the public builders (:func:`build_rope`, :func:`build_ragdoll`,
:func:`solve_ik`, factory functions) and the :class:`~.world.World`
public-boundary methods can share precise error messages without each
repeating the same checks.

Engineering policy: validate at the system boundary; internal solver
calls trust their inputs. Add new helpers here when (and only when) two
or more public entry points need the same check.
"""
from __future__ import annotations

import math
from typing import Any


# Hard cap on ``World.solver_iterations`` — values much above this either
# stall demos (each iteration touches every joint) or indicate the caller
# fat-fingered a ``stiffness`` for an ``iterations`` count. The XPBD
# convergence ceiling for the sub-systems we ship is ~64.
_SOLVER_ITERATIONS_MAX = 100

# Hard cap on a single ``World.step`` ``dt``. Above ~1.0 s the integrator
# tunnels through joints regardless of solver_iterations; values like
# ``1e6`` (a unit-conversion typo from microseconds) silently blow the
# scene up to NaN positions. Cap at 1.0 — anything slower is a paused
# game and should be skipped in the caller, not stepped in giant chunks.
_DT_MAX = 1.0


def validate_anchor(name: str, fn: str, anchor: Any) -> tuple[float, float]:
    """Coerce ``anchor`` to a 2-tuple of finite floats.

    Parameters
    ----------
    name:
        Parameter name to surface in error messages (e.g. ``"anchor_a"``).
    fn:
        Calling function name (e.g. ``"build_rope"``).
    anchor:
        Value supplied by the user.

    Raises
    ------
    TypeError
        If ``anchor`` is not a 2-element sequence of float-coercible items.
    ValueError
        If ``anchor`` has the wrong length or contains non-finite entries.
    """
    if isinstance(anchor, (str, bytes)) or not hasattr(anchor, "__len__"):
        raise TypeError(
            f"{fn}: {name} must be a 2-sequence of floats; "
            f"got {type(anchor).__name__}"
        )
    if len(anchor) != 2:
        raise ValueError(
            f"{fn}: {name} must have length 2 (x, y); "
            f"got length {len(anchor)}"
        )
    try:
        x = float(anchor[0])
        y = float(anchor[1])
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"{fn}: {name} entries must be float-coercible; got {anchor!r}"
        ) from exc
    if not (math.isfinite(x) and math.isfinite(y)):
        raise ValueError(
            f"{fn}: {name} must contain finite values; got ({x!r}, {y!r})"
        )
    return x, y


def validate_world(fn: str, world: Any) -> None:
    """Confirm ``world`` is a :class:`~.world.World` (or compatible duck).

    Raises
    ------
    TypeError
        If ``world`` is missing any of the required mutator methods
        (``add_nodes``, ``add_node``, ``add_joint``, ``register_body``).
    """
    # Lazy import to avoid a cycle at module load.
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


def validate_gravity(name: str, fn: str, value: Any) -> tuple[float, float]:
    """Coerce ``value`` to a 2-tuple of finite floats for ``World.gravity``.

    NaN gravity poisons every node position on the first step; +inf
    silently produces NaN velocities through the integrator. Refuse both
    at construction time so the failure surfaces at the ``World()`` call
    instead of as garbled positions several frames later.

    Raises
    ------
    TypeError
        If ``value`` is not a 2-sequence of float-coercible items.
    ValueError
        If ``value`` has the wrong length or contains non-finite entries.
    """
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__"):
        raise TypeError(
            f"{fn}: {name} must be a 2-sequence of floats; "
            f"got {type(value).__name__}"
        )
    if len(value) != 2:
        raise ValueError(
            f"{fn}: {name} must have length 2 (gx, gy); "
            f"got length {len(value)}"
        )
    try:
        gx = float(value[0])
        gy = float(value[1])
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"{fn}: {name} entries must be float-coercible; got {value!r}"
        ) from exc
    if not (math.isfinite(gx) and math.isfinite(gy)):
        raise ValueError(
            f"{fn}: {name} must contain finite values; got ({gx!r}, {gy!r})"
        )
    return gx, gy


def validate_solver_iterations(name: str, fn: str, value: Any) -> int:
    """Confirm ``value`` is an ``int`` in ``[1, _SOLVER_ITERATIONS_MAX]``.

    ``bool`` is refused so ``World.solver_iterations = True`` doesn't
    silently mean "1 iteration".

    Raises
    ------
    TypeError
        If ``value`` is not a plain ``int`` (bool refused).
    ValueError
        If ``value`` is below 1 or above ``_SOLVER_ITERATIONS_MAX``.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"{fn}: {name} must be an int; got {type(value).__name__}"
        )
    if value < 1:
        raise ValueError(f"{fn}: {name} must be >= 1; got {value}")
    if value > _SOLVER_ITERATIONS_MAX:
        raise ValueError(
            f"{fn}: {name} must be <= {_SOLVER_ITERATIONS_MAX}; got {value}"
        )
    return value


def validate_dt(name: str, fn: str, value: Any) -> float:
    """Confirm ``value`` is a finite float in ``(0, _DT_MAX]``.

    ``bool`` is refused. ``dt == 0`` would divide-by-zero in the velocity
    recovery step (we guard with ``max(dt, 1e-9)`` but the resulting
    velocity blows up to 1e9 and poisons all downstream physics);
    ``dt > 1.0`` lets nodes tunnel through every constraint regardless of
    ``solver_iterations``.

    Raises
    ------
    TypeError
        If ``value`` is not a real number (bool refused).
    ValueError
        If ``value`` is NaN/inf, ≤ 0, or > ``_DT_MAX``.
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
    if v > _DT_MAX:
        raise ValueError(
            f"{fn}: {name} must be <= {_DT_MAX}; got {v}"
        )
    return v


def validate_position(name: str, fn: str, value: Any) -> tuple[float, float]:
    """Coerce ``value`` to a 2-tuple of finite floats for a node position.

    Almost identical to :func:`validate_anchor` but exposed under a name
    that reads better at ``add_node`` call sites.

    Raises
    ------
    TypeError
        If ``value`` is not a 2-sequence of float-coercible items.
    ValueError
        If ``value`` has the wrong length or contains non-finite entries.
    """
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__"):
        raise TypeError(
            f"{fn}: {name} must be a 2-sequence of floats; "
            f"got {type(value).__name__}"
        )
    if len(value) != 2:
        raise ValueError(
            f"{fn}: {name} must have length 2 (x, y); "
            f"got length {len(value)}"
        )
    try:
        x = float(value[0])
        y = float(value[1])
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"{fn}: {name} entries must be float-coercible; got {value!r}"
        ) from exc
    if not (math.isfinite(x) and math.isfinite(y)):
        raise ValueError(
            f"{fn}: {name} must contain finite values; got ({x!r}, {y!r})"
        )
    return x, y


def validate_mass(name: str, fn: str, value: Any) -> float:
    """Confirm ``value`` is a finite, non-negative float for a node mass.

    ``mass == 0`` is the documented pin sentinel and stays allowed.
    Negative mass would silently flip to ``inv_mass < 0`` in :func:`add_node`
    (the ``mass <= 0`` branch sets ``inv_m = 0``) and behave as a pin —
    refuse so authoring typos don't silently freeze nodes.

    Raises
    ------
    TypeError
        If ``value`` is not a real number (bool refused).
    ValueError
        If ``value`` is NaN/inf or negative.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{fn}: {name} must be a real number; got {type(value).__name__}"
        )
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{fn}: {name} must be finite; got {v!r}")
    if v < 0.0:
        raise ValueError(f"{fn}: {name} must be >= 0; got {v}")
    return v


def validate_body(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` is a :class:`~.body.Body` ready to register.

    A raw ``dict`` slipping into ``World.bodies`` would silently work
    until something downstream (renderer, serialiser) looked for
    ``node_offset`` / ``node_count`` and crashed three frames later.

    Raises
    ------
    TypeError
        If ``value`` is not a :class:`Body` instance.
    """
    # Lazy import to avoid a cycle at module load.
    from .body import Body as _Body

    if not isinstance(value, _Body):
        raise TypeError(
            f"{fn}: {name} must be a slappyengine.dynamics.Body; "
            f"got {type(value).__name__}"
        )
    return value


def validate_joint(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` is a :class:`~.joint.JointSpec` instance.

    A raw ``dict`` would silently make it into ``World.joints`` and only
    blow up inside :func:`~.joint.resolve` with a confusing
    ``AttributeError: 'dict' object has no attribute 'kind'``.

    Raises
    ------
    TypeError
        If ``value`` is not a :class:`JointSpec` instance.
    """
    # Lazy import to avoid a cycle at module load.
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
