from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class BeamSoA:
    node_a: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=np.uint32))
    node_b: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=np.uint32))
    rest_length: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=np.float32))
    initial_rest_length: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=np.float32))
    stiffness: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=np.float32))
    damping: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=np.float32))
    break_strain: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=np.float32))
    yield_strain: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=np.float32))
    plasticity_rate: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=np.float32))
    broken: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=bool))
    body_id: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=np.uint16))

    @property
    def count(self) -> int:
        return int(self.node_a.shape[0])

    def append(
        self,
        node_a: np.ndarray,
        node_b: np.ndarray,
        rest_length: np.ndarray,
        stiffness: np.ndarray,
        damping: np.ndarray,
        break_strain: np.ndarray,
        body_id: int,
        yield_strain: np.ndarray | None = None,
        plasticity_rate: np.ndarray | None = None,
    ) -> int:
        node_a = np.asarray(node_a, dtype=np.uint32).reshape(-1)
        node_b = np.asarray(node_b, dtype=np.uint32).reshape(-1)
        rest_length = np.asarray(rest_length, dtype=np.float32).reshape(-1)
        stiffness = np.asarray(stiffness, dtype=np.float32).reshape(-1)
        damping = np.asarray(damping, dtype=np.float32).reshape(-1)
        break_strain = np.asarray(break_strain, dtype=np.float32).reshape(-1)
        n = node_a.shape[0]
        if yield_strain is None:
            yield_strain_arr = np.zeros(n, dtype=np.float32)
        else:
            yield_strain_arr = np.asarray(yield_strain, dtype=np.float32).reshape(-1)
        if plasticity_rate is None:
            plasticity_rate_arr = np.zeros(n, dtype=np.float32)
        else:
            plasticity_rate_arr = np.asarray(plasticity_rate, dtype=np.float32).reshape(-1)
        if not (node_b.shape[0] == n == rest_length.shape[0] == stiffness.shape[0]
                == damping.shape[0] == break_strain.shape[0]
                == yield_strain_arr.shape[0] == plasticity_rate_arr.shape[0]):
            raise ValueError("beam SoA append: all input arrays must share length")

        start = self.count
        self.node_a = np.concatenate([self.node_a, node_a])
        self.node_b = np.concatenate([self.node_b, node_b])
        self.rest_length = np.concatenate([self.rest_length, rest_length])
        self.initial_rest_length = np.concatenate([self.initial_rest_length, rest_length.copy()])
        self.stiffness = np.concatenate([self.stiffness, stiffness])
        self.damping = np.concatenate([self.damping, damping])
        self.break_strain = np.concatenate([self.break_strain, break_strain])
        self.yield_strain = np.concatenate([self.yield_strain, yield_strain_arr])
        self.plasticity_rate = np.concatenate([self.plasticity_rate, plasticity_rate_arr])
        self.broken = np.concatenate([self.broken, np.zeros(n, dtype=bool)])
        self.body_id = np.concatenate([self.body_id, np.full(n, body_id, dtype=np.uint16)])
        return start


__all__ = ["BeamSoA"]
