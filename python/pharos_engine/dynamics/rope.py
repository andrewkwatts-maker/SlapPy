"""Rope authoring spec + builder.

A rope is a chain of ``N`` nodes laid between two anchor positions, glued
end-to-end by distance joints, optionally with low-stiffness bend joints
spanning three adjacent nodes for a stiffer cable feel.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ._validation import validate_anchor, validate_world
from .body import Body
from .joint import JointSpec


@dataclass
class RopeSpec:
    """Description of a rope between two anchor points.

    Raises
    ------
    TypeError
        If ``params`` is not a ``dict``.
    ValueError
        If ``node_count < 2``, ``total_length <= 0``, ``mass_per_node <= 0``,
        ``stiffness <= 0``, ``damping`` is outside ``[0, 1]``, or
        ``bend_stiffness`` is negative.
    """
    node_count: int
    total_length: float
    mass_per_node: float = 0.1
    stiffness: float = 1.0e6
    damping: float = 0.05
    bend_stiffness: float = 0.0
    anchor_a_pinned: bool = True
    anchor_b_pinned: bool = False
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.params, dict):
            raise TypeError(
                f"RopeSpec.params must be a dict; got "
                f"{type(self.params).__name__}"
            )
        try:
            n = int(self.node_count)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                f"RopeSpec.node_count must be int-coercible; "
                f"got {self.node_count!r}"
            ) from exc
        if n < 2:
            raise ValueError(
                f"RopeSpec.node_count must be >= 2 (need at least two nodes "
                f"to form a segment); got {self.node_count!r}"
            )
        total_length = float(self.total_length)
        if not math.isfinite(total_length) or total_length <= 0.0:
            raise ValueError(
                f"RopeSpec.total_length must be finite and > 0; "
                f"got {self.total_length!r}"
            )
        mass = float(self.mass_per_node)
        if not math.isfinite(mass) or mass <= 0.0:
            raise ValueError(
                f"RopeSpec.mass_per_node must be finite and > 0; "
                f"got {self.mass_per_node!r}"
            )
        stiffness = float(self.stiffness)
        if not math.isfinite(stiffness) or stiffness <= 0.0:
            raise ValueError(
                f"RopeSpec.stiffness must be finite and > 0; "
                f"got {self.stiffness!r}"
            )
        damping = float(self.damping)
        if math.isnan(damping) or not (0.0 <= damping <= 1.0):
            raise ValueError(
                f"RopeSpec.damping must be in [0, 1]; got {self.damping!r}"
            )
        bend = float(self.bend_stiffness)
        if math.isnan(bend) or bend < 0.0:
            raise ValueError(
                f"RopeSpec.bend_stiffness must be >= 0; "
                f"got {self.bend_stiffness!r}"
            )


def build_rope(
    spec: RopeSpec,
    world,
    anchor_a: tuple[float, float],
    anchor_b: tuple[float, float],
) -> Body:
    """Spawn nodes + joints describing the rope.

    Returns a :class:`Body` whose ``node_offset`` / ``node_count`` cover the
    spawned nodes. The first and last nodes are pinned according to the
    spec's ``anchor_*_pinned`` flags.

    Raises
    ------
    TypeError
        If ``spec`` is not a :class:`RopeSpec`, ``world`` is not a compatible
        world object, or the anchors are not 2-sequences.
    ValueError
        If anchor entries are non-finite or ``anchor_a == anchor_b``.
    """
    if not isinstance(spec, RopeSpec):
        raise TypeError(
            f"build_rope: spec must be a RopeSpec; "
            f"got {type(spec).__name__}"
        )
    validate_world("build_rope", world)
    ax, ay = validate_anchor("anchor_a", "build_rope", anchor_a)
    bx, by = validate_anchor("anchor_b", "build_rope", anchor_b)
    if ax == bx and ay == by:
        raise ValueError(
            f"build_rope: anchor_a and anchor_b must differ; "
            f"both are ({ax!r}, {ay!r})"
        )
    n = int(spec.node_count)
    a = np.asarray((ax, ay), dtype=np.float64)
    b = np.asarray((bx, by), dtype=np.float64)
    positions = np.linspace(a, b, n)
    segment_len = float(spec.total_length) / (n - 1)

    masses = np.full((n,), float(spec.mass_per_node), dtype=np.float64)
    if spec.anchor_a_pinned:
        masses[0] = 0.0
    if spec.anchor_b_pinned:
        masses[-1] = 0.0
    offset, count = world.add_nodes(positions, masses)

    # Per-segment distance joints.
    for i in range(n - 1):
        world.add_joint(
            JointSpec(
                kind="distance",
                node_a=offset + i,
                node_b=offset + i + 1,
                rest_length=segment_len,
                stiffness=spec.stiffness,
                damping=spec.damping,
            )
        )

    # Optional bend joints between (i, i+2) acting like a triangle distance
    # constraint that resists folding. Cheap; stays inside the distance kernel.
    if spec.bend_stiffness > 0.0:
        bend_rest = 2.0 * segment_len
        for i in range(n - 2):
            world.add_joint(
                JointSpec(
                    kind="distance",
                    node_a=offset + i,
                    node_b=offset + i + 2,
                    rest_length=bend_rest,
                    stiffness=spec.bend_stiffness,
                    damping=spec.damping,
                )
            )

    body = Body(
        kind="rope",
        parameters={"spec": spec},
        node_offset=offset,
        node_count=count,
        label="rope",
    )
    world.register_body(body)
    return body


__all__ = ["RopeSpec", "build_rope"]
