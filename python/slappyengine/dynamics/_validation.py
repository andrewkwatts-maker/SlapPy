"""Internal input-validation helpers for the dynamics public API.

These helpers are deliberately not re-exported through ``__init__``: they
exist so the public builders (:func:`build_rope`, :func:`build_ragdoll`,
:func:`solve_ik`, factory functions) can share precise error messages
without each repeating the same checks.

Engineering policy: validate at the system boundary; internal solver
calls trust their inputs. Add new helpers here when (and only when) two
or more public entry points need the same check.
"""
from __future__ import annotations

import math
from typing import Any


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


__all__ = ["validate_anchor", "validate_world"]
