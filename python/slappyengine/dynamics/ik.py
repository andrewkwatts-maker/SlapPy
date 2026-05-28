"""2D inverse-kinematics over a node chain using CCD.

Cyclic Coordinate Descent walks the chain from tip to root, rotating each
joint to bring the tip closer to the target. Converges quickly for reachable
targets; degenerates gracefully for unreachable ones (the chain straightens
toward the target and the solver returns ``False``).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class IKChainSpec:
    """Description of a kinematic chain + target point."""
    node_indices: list[int]
    target: tuple[float, float]
    fixed_root: bool = True
    params: dict[str, Any] = field(default_factory=dict)


def _rotate_about(point: np.ndarray, pivot: np.ndarray, angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    d = point - pivot
    return pivot + np.array([c * d[0] - s * d[1], s * d[0] + c * d[1]])


def solve_ik(
    spec: IKChainSpec,
    world,
    iterations: int = 10,
    tolerance: float = 0.01,
) -> bool:
    """Solve the chain toward the target using CCD.

    Mutates ``world.positions`` in place for every node in
    ``spec.node_indices``. Returns ``True`` if the tip ends within
    ``tolerance`` of the target; ``False`` otherwise.
    """
    nodes = list(spec.node_indices)
    if len(nodes) < 2:
        return False
    target = np.asarray(spec.target, dtype=np.float64)
    tip_idx = nodes[-1]

    start = 1 if spec.fixed_root else 0
    for _ in range(int(max(1, iterations))):
        tip = world.positions[tip_idx]
        if float(np.linalg.norm(tip - target)) < tolerance:
            return True
        # Walk from second-to-last back toward the root.
        for k in range(len(nodes) - 2, start - 1, -1):
            pivot_idx = nodes[k]
            pivot = world.positions[pivot_idx].copy()
            tip = world.positions[tip_idx]
            to_tip = tip - pivot
            to_target = target - pivot
            n1 = float(np.linalg.norm(to_tip))
            n2 = float(np.linalg.norm(to_target))
            if n1 < 1e-9 or n2 < 1e-9:
                continue
            cos_a = float(np.clip(np.dot(to_tip, to_target) / (n1 * n2), -1.0, 1.0))
            cross = to_tip[0] * to_target[1] - to_tip[1] * to_target[0]
            angle = math.acos(cos_a)
            if cross < 0:
                angle = -angle
            # Rotate every downstream node about the pivot.
            for j in range(k + 1, len(nodes)):
                idx = nodes[j]
                world.positions[idx] = _rotate_about(world.positions[idx], pivot, angle)

    tip = world.positions[tip_idx]
    return float(np.linalg.norm(tip - target)) < tolerance


__all__ = ["IKChainSpec", "solve_ik"]
