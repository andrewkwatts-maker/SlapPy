"""Mesh dataclass — CPU-side triangle mesh + GPU upload handle."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class MeshHandle:
    """Opaque handle for an uploaded mesh.

    ``buffer_id`` is a monotonic id assigned by the owning renderer;
    ``gpu_buffers`` holds the actual wgpu buffers when wgpu is present,
    or ``None`` for :class:`~pharos_engine.render.null_renderer.NullRenderer`.
    """

    buffer_id: int
    vertex_count: int
    index_count: int
    gpu_buffers: Any | None = None


@dataclass
class Mesh:
    vertices: np.ndarray  # (N, 3) float32
    indices: np.ndarray   # (M, 3) uint32
    normals: np.ndarray | None = None
    uvs: np.ndarray | None = None
    material_id: int | None = None
    bounding_box: tuple[tuple[float, float, float], tuple[float, float, float]] = field(
        default_factory=lambda: ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    )

    def __post_init__(self) -> None:
        self.vertices = np.ascontiguousarray(self.vertices, dtype=np.float32)
        self.indices = np.ascontiguousarray(self.indices, dtype=np.uint32)
        if self.vertices.ndim != 2 or self.vertices.shape[1] != 3:
            raise ValueError(
                f"Mesh.vertices must have shape (N, 3), got {self.vertices.shape}"
            )
        if self.indices.ndim != 2 or self.indices.shape[1] != 3:
            raise ValueError(
                f"Mesh.indices must have shape (M, 3), got {self.indices.shape}"
            )
        if self.normals is not None:
            self.normals = np.ascontiguousarray(self.normals, dtype=np.float32)
            if self.normals.shape != self.vertices.shape:
                raise ValueError(
                    f"Mesh.normals shape {self.normals.shape} must match vertices"
                )
        if self.uvs is not None:
            self.uvs = np.ascontiguousarray(self.uvs, dtype=np.float32)
            if self.uvs.ndim != 2 or self.uvs.shape[0] != self.vertices.shape[0] or self.uvs.shape[1] != 2:
                raise ValueError(
                    f"Mesh.uvs must have shape (N, 2), got {self.uvs.shape}"
                )
        if self.vertices.size:
            self.bounding_box = (
                tuple(float(x) for x in self.vertices.min(axis=0)),
                tuple(float(x) for x in self.vertices.max(axis=0)),
            )

    # ------------------------------------------------------------------
    @classmethod
    def from_arrays(
        cls,
        vertices: np.ndarray,
        indices: np.ndarray,
        *,
        normals: np.ndarray | None = None,
        uvs: np.ndarray | None = None,
        material_id: int | None = None,
    ) -> "Mesh":
        return cls(
            vertices=vertices,
            indices=indices,
            normals=normals,
            uvs=uvs,
            material_id=material_id,
        )

    # ------------------------------------------------------------------
    def upload_to_gpu(self, renderer) -> MeshHandle:
        return renderer._upload_mesh(self)

    # ------------------------------------------------------------------
    def triangle_count(self) -> int:
        return int(self.indices.shape[0])

    # ------------------------------------------------------------------
    def compute_normals(self) -> np.ndarray:
        """Recompute per-vertex normals from triangle averages."""
        v = self.vertices
        idx = self.indices
        tri = v[idx]  # (M, 3, 3)
        edge1 = tri[:, 1] - tri[:, 0]
        edge2 = tri[:, 2] - tri[:, 0]
        face_n = np.cross(edge1, edge2)
        norms = np.zeros_like(v)
        for i in range(3):
            np.add.at(norms, idx[:, i], face_n)
        lens = np.linalg.norm(norms, axis=1, keepdims=True)
        lens[lens == 0] = 1.0
        return (norms / lens).astype(np.float32)


# ----------------------------------------------------------------------
# Convenience primitives
# ----------------------------------------------------------------------
def cube(size: float = 1.0) -> Mesh:
    s = 0.5 * size
    v = np.array(
        [
            [-s, -s, -s], [s, -s, -s], [s, s, -s], [-s, s, -s],
            [-s, -s, s],  [s, -s, s],  [s, s, s],  [-s, s, s],
        ],
        dtype=np.float32,
    )
    i = np.array(
        [
            [0, 2, 1], [0, 3, 2],  # -Z
            [4, 5, 6], [4, 6, 7],  # +Z
            [0, 1, 5], [0, 5, 4],  # -Y
            [3, 6, 2], [3, 7, 6],  # +Y
            [0, 4, 7], [0, 7, 3],  # -X
            [1, 2, 6], [1, 6, 5],  # +X
        ],
        dtype=np.uint32,
    )
    return Mesh(vertices=v, indices=i)


def quad(size: float = 1.0) -> Mesh:
    s = 0.5 * size
    v = np.array(
        [[-s, -s, 0.0], [s, -s, 0.0], [s, s, 0.0], [-s, s, 0.0]],
        dtype=np.float32,
    )
    uvs = np.array(
        [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]], dtype=np.float32
    )
    i = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.uint32)
    return Mesh(vertices=v, indices=i, uvs=uvs)
