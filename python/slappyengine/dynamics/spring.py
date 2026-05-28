"""Spring-flavoured :class:`JointSpec` builder.

Springs reuse the distance projection in :mod:`slappyengine.dynamics.joint`
with author-tuned softer defaults so the same backend can express both stiff
welds and bouncy suspension.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .joint import JointSpec


@dataclass
class SpringSpec:
    """Pure-data record for a spring; resolves to ``JointSpec(kind='spring')``.

    Useful as a serialisable preset; the :func:`make_spring` builder unpacks
    one of these into a :class:`JointSpec` for the solver.
    """
    node_a: int
    node_b: int
    rest_length: float
    stiffness: float = 1.0e6
    damping: float = 0.05
    params: dict[str, Any] = field(default_factory=dict)


def make_spring(
    node_a: int,
    node_b: int,
    rest_length: float,
    stiffness: float = 1.0e6,
    damping: float = 0.05,
) -> JointSpec:
    """Build a spring constraint between two nodes."""
    return JointSpec(
        kind="spring",
        node_a=int(node_a),
        node_b=int(node_b),
        rest_length=float(rest_length),
        stiffness=float(stiffness),
        damping=float(damping),
        params={},
    )


__all__ = ["SpringSpec", "make_spring"]
