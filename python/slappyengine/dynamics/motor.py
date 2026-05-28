"""Motor-flavoured :class:`JointSpec` builder.

A motor spins two rim nodes around a hub node. The substrate solver applies
tangential impulses bounded by ``max_torque`` per substep so the hub-rim pair
keeps a fixed radius while the rim picks up angular velocity ``target_omega``.

This is the primitive the vehicle drivetrain composes; ``apply_drivetrain_
torque`` in the softbody vehicle layer becomes a list of these.
"""
from __future__ import annotations

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
    """
    return JointSpec(
        kind="motor",
        node_a=int(rim_a),
        node_b=int(rim_b),
        rest_length=float(radius),
        stiffness=float(stiffness),
        damping=float(damping),
        params={
            "hub": int(hub),
            "axis": tuple(map(float, axis)),
            "target_omega": float(target_omega),
            "max_torque": float(max_torque),
        },
    )


__all__ = ["MotorSpec", "make_motor"]
