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

from .body import Body
from .joint import JointSpec


@dataclass
class RopeSpec:
    """Description of a rope between two anchor points."""
    node_count: int
    total_length: float
    mass_per_node: float = 0.1
    stiffness: float = 1.0e6
    damping: float = 0.05
    bend_stiffness: float = 0.0
    anchor_a_pinned: bool = True
    anchor_b_pinned: bool = False
    params: dict[str, Any] = field(default_factory=dict)


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
    """
    n = int(spec.node_count)
    if n < 2:
        raise ValueError("RopeSpec.node_count must be >= 2")
    a = np.asarray(anchor_a, dtype=np.float64)
    b = np.asarray(anchor_b, dtype=np.float64)
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
