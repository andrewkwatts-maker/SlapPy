from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class ParticleSoA:
    pos: np.ndarray = field(default_factory=lambda: np.empty((0, 2), dtype=np.float32))
    prev_pos: np.ndarray = field(default_factory=lambda: np.empty((0, 2), dtype=np.float32))
    vel: np.ndarray = field(default_factory=lambda: np.empty((0, 2), dtype=np.float32))
    mass: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=np.float32))
    inv_mass: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=np.float32))
    density: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=np.float32))
    lambda_: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=np.float32))
    material_id: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=np.uint8))
    temperature: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=np.float32))

    @property
    def count(self) -> int:
        return int(self.pos.shape[0])

    def append(self, pos: np.ndarray, mass: float, material_id: int = 0,
               vel: np.ndarray | None = None,
               temperature: float = 20.0) -> int:
        pos = np.asarray(pos, dtype=np.float32).reshape(-1, 2)
        n = pos.shape[0]
        if n == 0:
            return self.count
        masses = np.full(n, float(mass), dtype=np.float32)
        inv = (1.0 / np.maximum(masses, 1e-12)).astype(np.float32)
        if vel is None:
            v = np.zeros_like(pos)
        else:
            v = np.asarray(vel, dtype=np.float32).reshape(-1, 2)
            if v.shape[0] == 1 and n > 1:
                v = np.broadcast_to(v, (n, 2)).astype(np.float32, copy=True)

        start = self.count
        self.pos = np.concatenate([self.pos, pos], axis=0)
        self.prev_pos = np.concatenate([self.prev_pos, pos.copy()], axis=0)
        self.vel = np.concatenate([self.vel, v], axis=0)
        self.mass = np.concatenate([self.mass, masses])
        self.inv_mass = np.concatenate([self.inv_mass, inv])
        self.density = np.concatenate([self.density, np.zeros(n, dtype=np.float32)])
        self.lambda_ = np.concatenate([self.lambda_, np.zeros(n, dtype=np.float32)])
        self.material_id = np.concatenate([self.material_id,
                                            np.full(n, material_id, dtype=np.uint8)])
        self.temperature = np.concatenate([self.temperature,
                                            np.full(n, float(temperature), dtype=np.float32)])
        return start


__all__ = ["ParticleSoA"]
