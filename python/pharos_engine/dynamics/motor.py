"""Motor-flavoured :class:`JointSpec` builder.

A motor spins two rim nodes around a hub node. The substrate solver applies
tangential impulses bounded by ``max_torque`` per substep so the hub-rim pair
keeps a fixed radius while the rim picks up angular velocity ``target_omega``.

This is the primitive the vehicle drivetrain composes; ``apply_drivetrain_
torque`` in the softbody vehicle layer becomes a list of these.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .joint import JointSpec


@dataclass
class MotorSpec:
    """Pure-data record for a motor joint."""
    hub: int
    rim_a: int
    rim_b: int
    target_omega: float
    max_torque: float
    radius: float = 0.0
    axis: tuple[float, float] = (1.0, 0.0)
    stiffness: float = 1.0e8
    damping: float = 0.02
    params: dict[str, Any] = field(default_factory=dict)


def _check_node_index(fn: str, name: str, value: Any) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"{fn}: {name} must be int-coercible; got {value!r}"
        ) from exc
    if v < 0:
        raise ValueError(
            f"{fn}: {name} must be non-negative; got {value!r}"
        )
    return v


def make_motor(
    hub: int,
    rim_a: int,
    rim_b: int,
    target_omega: float,
    max_torque: float,
    radius: float = 0.0,
    axis: tuple[float, float] = (1.0, 0.0),
    stiffness: float = 1.0e8,
    damping: float = 0.02,
) -> JointSpec:
    """Construct a motor :class:`JointSpec` between hub and the two rim nodes.

    The solver reads ``params['hub']`` so ``node_a`` / ``node_b`` are kept as
    the rim pair — matching the JointSpec schema (two nodes per joint) while
    still expressing a three-body relation through ``params``.

    Raises
    ------
    TypeError
        If any index is not int-coercible, or ``axis`` is not a 2-sequence.
    ValueError
        If indices are negative, the hub coincides with a rim, the two rims
        coincide, ``target_omega`` is non-finite, ``max_torque <= 0``,
        ``radius < 0``, ``stiffness <= 0``, or ``damping`` is outside
        ``[0, 1]``.
    """
    h = _check_node_index("make_motor", "hub", hub)
    a = _check_node_index("make_motor", "rim_a", rim_a)
    b = _check_node_index("make_motor", "rim_b", rim_b)
    if a == b:
        raise ValueError(
            f"make_motor: rim_a and rim_b must differ; both are {a}"
        )
    if h == a or h == b:
        raise ValueError(
            f"make_motor: hub must differ from rim_a and rim_b; "
            f"got hub={h}, rim_a={a}, rim_b={b}"
        )
    omega = float(target_omega)
    if not math.isfinite(omega):
        raise ValueError(
            f"make_motor: target_omega must be finite; "
            f"got {target_omega!r}"
        )
    torque = float(max_torque)
    if not math.isfinite(torque) or torque <= 0.0:
        raise ValueError(
            f"make_motor: max_torque must be finite and > 0; "
            f"got {max_torque!r}"
        )
    r = float(radius)
    if not math.isfinite(r) or r < 0.0:
        raise ValueError(
            f"make_motor: radius must be finite and >= 0; "
            f"got {radius!r}"
        )
    if not hasattr(axis, "__len__") or len(axis) != 2:
        raise TypeError(
            f"make_motor: axis must be a 2-sequence; got {axis!r}"
        )
    try:
        ax_x = float(axis[0])
        ax_y = float(axis[1])
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"make_motor: axis entries must be float-coercible; "
            f"got {axis!r}"
        ) from exc
    if not (math.isfinite(ax_x) and math.isfinite(ax_y)):
        raise ValueError(
            f"make_motor: axis must contain finite values; got {axis!r}"
        )
    k = float(stiffness)
    if not math.isfinite(k) or k <= 0.0:
        raise ValueError(
            f"make_motor: stiffness must be finite and > 0; "
            f"got {stiffness!r}"
        )
    d = float(damping)
    if math.isnan(d) or not (0.0 <= d <= 1.0):
        raise ValueError(
            f"make_motor: damping must be in [0, 1]; got {damping!r}"
        )
    return JointSpec(
        kind="motor",
        node_a=a,
        node_b=b,
        rest_length=r,
        stiffness=k,
        damping=d,
        params={
            "hub": h,
            "axis": (ax_x, ax_y),
            "target_omega": omega,
            "max_torque": torque,
        },
    )


__all__ = ["MotorSpec", "make_motor"]
