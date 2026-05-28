"""Minimal XPBD-style node world that backs the dynamics primitives.

This is intentionally a thin substrate — just enough to step joints and
verify the unified type system. The full softbody package (lattices, contact,
rendering) layers on top of this and is documented separately.

Node arrays are kept as ``numpy`` matrices of shape ``(N, 2)`` so we can
vectorise distance/angular constraints. A node with ``inv_mass == 0`` is
treated as a kinematic anchor.
"""
from __future__ import annotations

from typing import Any

import numpy as np


class World:
    """Container of nodes + bodies + joints with a single :meth:`step` loop.

    Coordinates are 2D — the dynamics primitives target the engine's
    planar XPBD layer; the rust ``_core.physics`` rigid-body world covers
    full 3D. Mixing both is intentional.
    """

    def __init__(self, gravity: tuple[float, float] = (0.0, -9.81)) -> None:
        # Geometry / mass
        self.positions: np.ndarray = np.zeros((0, 2), dtype=np.float64)
        self.prev_positions: np.ndarray = np.zeros((0, 2), dtype=np.float64)
        self.velocities: np.ndarray = np.zeros((0, 2), dtype=np.float64)
        self.inv_masses: np.ndarray = np.zeros((0,), dtype=np.float64)
        # Bodies and joints
        self.bodies: list[Any] = []
        self.joints: list[Any] = []
        # Tuning
        self.gravity = np.asarray(gravity, dtype=np.float64)
        self.solver_iterations: int = 8
        # Time tracking
        self.frame: int = 0

    # ------------------------------------------------------------------ nodes
    def add_node(self, pos: tuple[float, float], mass: float = 1.0) -> int:
        """Append a node, returning its absolute index. ``mass == 0`` pins it."""
        idx = self.positions.shape[0]
        p = np.asarray(pos, dtype=np.float64).reshape(1, 2)
        self.positions = np.vstack([self.positions, p])
        self.prev_positions = np.vstack([self.prev_positions, p])
        self.velocities = np.vstack(
            [self.velocities, np.zeros((1, 2), dtype=np.float64)]
        )
        inv_m = 0.0 if mass <= 0.0 else 1.0 / mass
        self.inv_masses = np.append(self.inv_masses, inv_m)
        return idx

    def add_nodes(
        self, positions: np.ndarray, masses: np.ndarray | float = 1.0
    ) -> tuple[int, int]:
        """Bulk-append nodes. Returns ``(offset, count)``."""
        positions = np.asarray(positions, dtype=np.float64).reshape(-1, 2)
        n = positions.shape[0]
        offset = self.positions.shape[0]
        if np.isscalar(masses):
            mass_arr = np.full((n,), float(masses), dtype=np.float64)
        else:
            mass_arr = np.asarray(masses, dtype=np.float64).reshape(-1)
        inv_m = np.where(mass_arr <= 0.0, 0.0, 1.0 / np.where(mass_arr > 0, mass_arr, 1.0))
        self.positions = np.vstack([self.positions, positions])
        self.prev_positions = np.vstack([self.prev_positions, positions.copy()])
        self.velocities = np.vstack(
            [self.velocities, np.zeros((n, 2), dtype=np.float64)]
        )
        self.inv_masses = np.concatenate([self.inv_masses, inv_m])
        return offset, n

    # ----------------------------------------------------------------- bodies
    def register_body(self, body: Any) -> Any:
        self.bodies.append(body)
        return body

    # ----------------------------------------------------------------- joints
    def add_joint(self, joint: Any) -> Any:
        self.joints.append(joint)
        return joint

    # --------------------------------------------------------------- stepping
    def step(self, dt: float) -> None:
        """Integrate one frame using XPBD-style position projection.

        1. Predict positions using gravity + current velocity.
        2. Iterate the joint list ``solver_iterations`` times, calling
           :func:`slappyengine.dynamics.joint.resolve` to project each
           constraint.
        3. Recover velocity from the position delta.
        """
        if self.positions.shape[0] == 0:
            self.frame += 1
            return
        from .joint import resolve as _resolve_joint

        inv_m = self.inv_masses[:, None]
        # 1. Integrate
        self.velocities += self.gravity[None, :] * dt * (inv_m > 0)
        self.prev_positions = self.positions.copy()
        self.positions = self.positions + self.velocities * dt * (inv_m > 0)

        # 2. Constraint solve
        for _ in range(max(1, self.solver_iterations)):
            for joint in self.joints:
                if not getattr(joint, "enabled", True):
                    continue
                _resolve_joint(joint, self, dt)

        # 3. Velocity recovery
        new_vel = (self.positions - self.prev_positions) / max(dt, 1e-9)
        # Preserve zeros on pinned nodes
        pinned = (self.inv_masses == 0.0)
        new_vel[pinned] = 0.0
        self.velocities = new_vel
        self.frame += 1


# Backwards-compat alias matching the plan's `SoftBodyWorld` references.
SoftBodyWorld = World


__all__ = ["World", "SoftBodyWorld"]
