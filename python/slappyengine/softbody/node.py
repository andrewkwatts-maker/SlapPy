from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class NodeSoA:
    pos: np.ndarray = field(default_factory=lambda: np.empty((0, 2), dtype=np.float32))
    prev_pos: np.ndarray = field(default_factory=lambda: np.empty((0, 2), dtype=np.float32))
    vel: np.ndarray = field(default_factory=lambda: np.empty((0, 2), dtype=np.float32))
    mass: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=np.float32))
    inv_mass: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=np.float32))
    fixed: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=bool))
    body_id: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=np.uint16))
    layer: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=np.uint8))
    damping: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=np.float32))

    @property
    def count(self) -> int:
        return int(self.pos.shape[0])

    def append(
        self,
        pos: np.ndarray,
        mass: np.ndarray,
        body_id: int,
        layer: int,
        damping: np.ndarray,
        fixed: np.ndarray | None = None,
    ) -> int:
        """Append a batch of nodes and return the index of the first new node."""
        pos = np.asarray(pos, dtype=np.float32).reshape(-1, 2)
        n = pos.shape[0]
        mass = np.asarray(mass, dtype=np.float32).reshape(-1)
        damping = np.asarray(damping, dtype=np.float32).reshape(-1)
        if mass.shape[0] != n or damping.shape[0] != n:
            raise ValueError("mass and damping length must match pos rows")
        if fixed is None:
            fixed_arr = np.zeros(n, dtype=bool)
        else:
            fixed_arr = np.asarray(fixed, dtype=bool).reshape(-1)
            if fixed_arr.shape[0] != n:
                raise ValueError("fixed length must match pos rows")
        inv_mass = np.where(fixed_arr, 0.0, 1.0 / np.maximum(mass, 1e-12)).astype(np.float32)

        start = self.count
        self.pos = np.concatenate([self.pos, pos], axis=0)
        self.prev_pos = np.concatenate([self.prev_pos, pos.copy()], axis=0)
        self.vel = np.concatenate([self.vel, np.zeros_like(pos)], axis=0)
        self.mass = np.concatenate([self.mass, mass])
        self.inv_mass = np.concatenate([self.inv_mass, inv_mass])
        self.fixed = np.concatenate([self.fixed, fixed_arr])
        self.body_id = np.concatenate([self.body_id, np.full(n, body_id, dtype=np.uint16)])
        self.layer = np.concatenate([self.layer, np.full(n, layer, dtype=np.uint8)])
        self.damping = np.concatenate([self.damping, damping])
        return start


__all__ = ["NodeSoA"]
