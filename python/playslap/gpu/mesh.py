"""GpuMesh — vertex + index buffer holder for 3D Layer rendering."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import struct
import numpy as np


@dataclass
class MeshVertex:
    """Packed vertex: position(vec3) + normal(vec3) + uv(vec2) + tangent(vec4) = 48 bytes."""
    position: tuple[float, float, float]
    normal: tuple[float, float, float] = (0.0, 1.0, 0.0)
    uv: tuple[float, float] = (0.0, 0.0)
    tangent: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 1.0)

    def pack(self) -> bytes:
        return struct.pack(
            "3f3f2f4f",
            *self.position,
            *self.normal,
            *self.uv,
            *self.tangent,
        )


class GpuMesh:
    """CPU-side mesh data. Call upload() to create wgpu GPU buffers."""

    VERTEX_STRIDE = 48  # bytes: 3f+3f+2f+4f = 12 floats × 4 = 48

    def __init__(self, vertices: list[MeshVertex], indices: list[int]) -> None:
        self._vertices = vertices
        self._indices = indices
        self._vertex_buf = None   # wgpu.GPUBuffer, set by upload()
        self._index_buf = None

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def unit_cube(cls) -> "GpuMesh":
        """Create a unit cube (1×1×1, centered at origin) with normals + UVs.

        Uses 24 vertices (4 per face × 6 faces) so each face can have its
        own flat normal.  Produces 36 indices (2 triangles × 3 verts × 6 faces).

        Face order: +X, -X, +Y, -Y, +Z, -Z
        Tangent handedness is +1.0 (w component).
        """
        H = 0.5  # half-extent

        # Each face is defined by:
        #   normal, tangent (U direction), bitangent (V direction),
        #   and the 4 corner positions in CCW winding (front-face = CCW).
        # UV corners: bottom-left (0,1), bottom-right (1,1),
        #             top-right (1,0), top-left (0,0) — Y flipped for GPUs.

        vertices: list[MeshVertex] = []

        def _face(
            nx: float, ny: float, nz: float,       # face normal
            tx: float, ty: float, tz: float,       # tangent (U axis, rightward on face)
            corners: list[tuple[float, float, float]],  # 4 positions, CCW
        ) -> None:
            uvs = [(0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]
            tangent = (tx, ty, tz, 1.0)
            for pos, uv in zip(corners, uvs):
                vertices.append(MeshVertex(
                    position=pos,
                    normal=(nx, ny, nz),
                    uv=uv,
                    tangent=tangent,
                ))

        # +X face  (normal = +X, tangent = +Z, corners wind CCW viewed from +X)
        _face(1, 0, 0,  0, 0, 1, [
            ( H, -H,  H),
            ( H, -H, -H),
            ( H,  H, -H),
            ( H,  H,  H),
        ])

        # -X face  (normal = -X, tangent = -Z, corners wind CCW viewed from -X)
        _face(-1, 0, 0,  0, 0, -1, [
            (-H, -H, -H),
            (-H, -H,  H),
            (-H,  H,  H),
            (-H,  H, -H),
        ])

        # +Y face  (normal = +Y, tangent = +X, corners wind CCW viewed from +Y)
        _face(0, 1, 0,  1, 0, 0, [
            (-H,  H,  H),
            ( H,  H,  H),
            ( H,  H, -H),
            (-H,  H, -H),
        ])

        # -Y face  (normal = -Y, tangent = +X, corners wind CCW viewed from -Y)
        _face(0, -1, 0,  1, 0, 0, [
            (-H, -H, -H),
            ( H, -H, -H),
            ( H, -H,  H),
            (-H, -H,  H),
        ])

        # +Z face  (normal = +Z, tangent = +X, corners wind CCW viewed from +Z)
        _face(0, 0, 1,  1, 0, 0, [
            (-H, -H,  H),
            ( H, -H,  H),
            ( H,  H,  H),
            (-H,  H,  H),
        ])

        # -Z face  (normal = -Z, tangent = -X, corners wind CCW viewed from -Z)
        _face(0, 0, -1,  -1, 0, 0, [
            ( H, -H, -H),
            (-H, -H, -H),
            (-H,  H, -H),
            ( H,  H, -H),
        ])

        # Generate indices: for each face (groups of 4 verts), two triangles
        indices: list[int] = []
        for face in range(6):
            base = face * 4
            # CCW triangles: (0,1,2) and (0,2,3)
            indices += [base, base + 1, base + 2, base, base + 2, base + 3]

        return cls(vertices, indices)

    @classmethod
    def unit_quad(cls) -> "GpuMesh":
        """Create a unit quad (1×1 in XY plane) for 2D→3D texture projection."""
        vertices = [
            MeshVertex((-0.5, -0.5, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0)),
            MeshVertex(( 0.5, -0.5, 0.0), (0.0, 0.0, 1.0), (1.0, 1.0)),
            MeshVertex(( 0.5,  0.5, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0)),
            MeshVertex((-0.5,  0.5, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0)),
        ]
        return cls(vertices, [0, 1, 2, 0, 2, 3])

    # ------------------------------------------------------------------
    # Data accessors
    # ------------------------------------------------------------------

    def vertex_bytes(self) -> bytes:
        return b"".join(v.pack() for v in self._vertices)

    def index_bytes(self) -> bytes:
        return struct.pack(f"{len(self._indices)}I", *self._indices)

    # ------------------------------------------------------------------
    # GPU upload
    # ------------------------------------------------------------------

    def upload(self, device) -> None:
        """Create wgpu vertex and index buffers. Idempotent."""
        if self._vertex_buf is not None:
            return
        import wgpu
        vdata = self.vertex_bytes()
        idata = self.index_bytes()
        self._vertex_buf = device.create_buffer_with_data(
            data=vdata,
            usage=wgpu.BufferUsage.VERTEX,
        )
        self._index_buf = device.create_buffer_with_data(
            data=idata,
            usage=wgpu.BufferUsage.INDEX,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def vertex_buffer(self):
        return self._vertex_buf

    @property
    def index_buffer(self):
        return self._index_buf

    @property
    def vertex_count(self) -> int:
        return len(self._vertices)

    @property
    def index_count(self) -> int:
        return len(self._indices)
