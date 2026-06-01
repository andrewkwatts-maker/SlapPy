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

from ._validation import validate_anchor, validate_world


def _positions_view(world):
    """Return the ``(N, 2)`` positions array of either a dynamics ``World``
    or a softbody ``SoftBodyWorld`` (``world.nodes.pos``). The IK solver
    only needs random-access read/write to this array; the rest of the
    world's API is unused.
    """
    if hasattr(world, "positions"):
        return world.positions
    nodes = getattr(world, "nodes", None)
    if nodes is not None and hasattr(nodes, "pos"):
        return nodes.pos
    raise AttributeError(
        f"solve_ik: world {type(world).__name__} has no .positions array "
        f"or .nodes.pos SoA"
    )


@dataclass
class IKChainSpec:
    """Description of a kinematic chain + target point.

    Raises
    ------
    TypeError
        If ``node_indices`` is not a sequence or ``params`` is not a dict.
    ValueError
        If ``node_indices`` is empty, contains negatives or non-ints, or
        ``target`` is not a finite 2-tuple.
    """
    node_indices: list[int]
    target: tuple[float, float]
    fixed_root: bool = True
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.node_indices, (str, bytes)) or not hasattr(
            self.node_indices, "__iter__"
        ):
            raise TypeError(
                f"IKChainSpec.node_indices must be a sequence; "
                f"got {type(self.node_indices).__name__}"
            )
        nodes = list(self.node_indices)
        if not nodes:
            raise ValueError(
                "IKChainSpec.node_indices must not be empty"
            )
        for k, idx in enumerate(nodes):
            # Reject floats / bools / strings before int() — int(1.5) silently
            # truncates to 1 which was the docstring-vs-validator mismatch the
            # API ref auto-gen agent surfaced.
            if isinstance(idx, bool) or not isinstance(idx, int):
                raise TypeError(
                    f"IKChainSpec.node_indices[{k}] must be int; "
                    f"got {type(idx).__name__} {idx!r}"
                )
            if idx < 0:
                raise ValueError(
                    f"IKChainSpec.node_indices[{k}] must be non-negative; "
                    f"got {idx!r}"
                )
        # target: finite 2-tuple
        tx, ty = validate_anchor("target", "IKChainSpec", self.target)
        # Normalise so callers see consistent shapes downstream.
        self.target = (tx, ty)
        if not isinstance(self.params, dict):
            raise TypeError(
                f"IKChainSpec.params must be a dict; "
                f"got {type(self.params).__name__}"
            )


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

    Raises
    ------
    TypeError
        If ``spec`` is not an :class:`IKChainSpec` or ``world`` is not
        a compatible world object.
    ValueError
        If ``iterations <= 0`` or ``tolerance <= 0``.
    """
    if not isinstance(spec, IKChainSpec):
        raise TypeError(
            f"solve_ik: spec must be an IKChainSpec; "
            f"got {type(spec).__name__}"
        )
    # Accept either a dynamics ``World`` (the XPBD substrate) or a softbody
    # ``SoftBodyWorld`` duck — the solver only needs index access to the
    # node positions array.
    if not (
        hasattr(world, "positions")
        or (hasattr(world, "nodes") and hasattr(world.nodes, "pos"))
    ):
        validate_world("solve_ik", world)
    try:
        iters = int(iterations)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"solve_ik: iterations must be int-coercible; "
            f"got {iterations!r}"
        ) from exc
    if iters <= 0:
        raise ValueError(
            f"solve_ik: iterations must be > 0; got {iterations!r}"
        )
    tol = float(tolerance)
    if not math.isfinite(tol) or tol <= 0.0:
        raise ValueError(
            f"solve_ik: tolerance must be finite and > 0; "
            f"got {tolerance!r}"
        )
    nodes = list(spec.node_indices)
    if len(nodes) < 2:
        return False
    target = np.asarray(spec.target, dtype=np.float64)
    tip_idx = nodes[-1]

    positions = _positions_view(world)
    start = 1 if spec.fixed_root else 0
    for _ in range(int(max(1, iterations))):
        tip = positions[tip_idx]
        if float(np.linalg.norm(tip - target)) < tolerance:
            return True
        # Walk from second-to-last back toward the root.
        for k in range(len(nodes) - 2, start - 1, -1):
            pivot_idx = nodes[k]
            pivot = positions[pivot_idx].copy()
            tip = positions[tip_idx]
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
                positions[idx] = _rotate_about(positions[idx], pivot, angle)

    tip = positions[tip_idx]
    return float(np.linalg.norm(tip - target)) < tolerance


__all__ = ["IKChainSpec", "solve_ik"]
