"""Instanced rendering — draw N copies of one mesh in a single draw call.

Nova3D parity Sprint 16 / task LL3.

Layout
------
* :class:`InstanceData` — per-instance model matrices, colours, UV offsets.
* :class:`InstancedMesh` — pairs a ``Mesh`` with an ``InstanceData``.
* Factory helpers: :func:`grid`, :func:`random_scatter`, :func:`circle`,
  :func:`from_transforms`.
* Two UBO/SSBO packing helpers so callers can pick the right buffer kind
  depending on the instance count / backend limits.
* :func:`render_instanced` — module-level dispatch to
  :meth:`Renderer.submit_mesh` (either the real wgpu Renderer or the
  NullRenderer used in CI) that appends **exactly one** ``mesh`` draw call
  carrying an ``instance_count`` payload.

Both the ``Renderer`` and ``NullRenderer`` are treated as read-only; this
module never patches their classes at import time. The dispatch helper
records instance metadata into the null draw log via ``draw_log.append``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .mesh import Mesh


# ----------------------------------------------------------------------
# InstanceData
# ----------------------------------------------------------------------
@dataclass
class InstanceData:
    """Per-instance attribute pack for :class:`InstancedMesh`."""

    instance_transforms: np.ndarray  # (N, 4, 4) float32 model matrices
    instance_colors: np.ndarray | None = None  # (N, 4) float32 RGBA
    instance_uv_offsets: np.ndarray | None = None  # (N, 2) float32
    instance_count: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        m = np.asarray(self.instance_transforms, dtype=np.float32)
        if m.ndim != 3 or m.shape[1:] != (4, 4):
            raise ValueError(
                "InstanceData.instance_transforms must be (N, 4, 4), "
                f"got {m.shape}"
            )
        self.instance_transforms = np.ascontiguousarray(m, dtype=np.float32)
        n = int(m.shape[0])
        self.instance_count = n

        if self.instance_colors is not None:
            c = np.asarray(self.instance_colors, dtype=np.float32)
            if c.ndim != 2 or c.shape != (n, 4):
                raise ValueError(
                    f"InstanceData.instance_colors must be ({n}, 4), got {c.shape}"
                )
            self.instance_colors = np.ascontiguousarray(c, dtype=np.float32)

        if self.instance_uv_offsets is not None:
            u = np.asarray(self.instance_uv_offsets, dtype=np.float32)
            if u.ndim != 2 or u.shape != (n, 2):
                raise ValueError(
                    f"InstanceData.instance_uv_offsets must be ({n}, 2), got {u.shape}"
                )
            self.instance_uv_offsets = np.ascontiguousarray(u, dtype=np.float32)


# ----------------------------------------------------------------------
# InstancedMesh
# ----------------------------------------------------------------------
@dataclass
class InstancedMesh:
    """A mesh + its per-instance attribute pack + AABB union."""

    base_mesh: Mesh
    instance_data: InstanceData
    bounding_box_all: tuple[
        tuple[float, float, float], tuple[float, float, float]
    ] = field(init=False)

    def __post_init__(self) -> None:
        self.bounding_box_all = _compute_bounding_box_all(
            self.base_mesh, self.instance_data
        )

    # Convenience: proxy the cached instance count.
    @property
    def instance_count(self) -> int:
        return self.instance_data.instance_count


def _compute_bounding_box_all(
    base_mesh: Mesh, instance_data: InstanceData
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Union AABB over all instances (transforms the mesh AABB corners)."""
    (bmin, bmax) = base_mesh.bounding_box
    corners = np.array(
        [
            [bmin[0], bmin[1], bmin[2], 1.0],
            [bmax[0], bmin[1], bmin[2], 1.0],
            [bmin[0], bmax[1], bmin[2], 1.0],
            [bmax[0], bmax[1], bmin[2], 1.0],
            [bmin[0], bmin[1], bmax[2], 1.0],
            [bmax[0], bmin[1], bmax[2], 1.0],
            [bmin[0], bmax[1], bmax[2], 1.0],
            [bmax[0], bmax[1], bmax[2], 1.0],
        ],
        dtype=np.float32,
    )
    n = instance_data.instance_count
    if n == 0:
        return ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    ts = instance_data.instance_transforms  # (N, 4, 4)
    # (N, 8, 4) via einsum: transformed = T @ corners.T
    transformed = np.einsum("nij,cj->nci", ts, corners)  # (N, 8, 4)
    xyz = transformed[..., :3].reshape(-1, 3)
    lo = xyz.min(axis=0)
    hi = xyz.max(axis=0)
    return (
        (float(lo[0]), float(lo[1]), float(lo[2])),
        (float(hi[0]), float(hi[1]), float(hi[2])),
    )


# ----------------------------------------------------------------------
# Factory helpers
# ----------------------------------------------------------------------
def _translation_matrix(x: float, y: float, z: float) -> np.ndarray:
    m = np.eye(4, dtype=np.float32)
    m[0, 3] = float(x)
    m[1, 3] = float(y)
    m[2, 3] = float(z)
    return m


def grid(mesh: Mesh, rows: int, cols: int, spacing: float) -> InstancedMesh:
    """Row-major XZ grid centred on the origin.

    Instances are laid out on the XZ plane (Y = 0) with the given
    ``spacing``. Returns ``rows * cols`` instances.
    """
    if rows < 0 or cols < 0:
        raise ValueError("grid rows/cols must be non-negative")
    n = int(rows) * int(cols)
    ts = np.empty((n, 4, 4), dtype=np.float32)
    ts[:] = np.eye(4, dtype=np.float32)
    if n:
        half_r = (rows - 1) * 0.5
        half_c = (cols - 1) * 0.5
        idx = 0
        for r in range(rows):
            for c in range(cols):
                x = (c - half_c) * float(spacing)
                z = (r - half_r) * float(spacing)
                ts[idx] = _translation_matrix(x, 0.0, z)
                idx += 1
    return InstancedMesh(base_mesh=mesh, instance_data=InstanceData(ts))


def random_scatter(
    mesh: Mesh,
    count: int,
    region: tuple[
        tuple[float, float, float], tuple[float, float, float]
    ],
    *,
    seed: int = 0,
) -> InstancedMesh:
    """Scatter ``count`` instances inside the AABB ``region``.

    Deterministic under a fixed ``seed`` (default 0).
    """
    if count < 0:
        raise ValueError("random_scatter count must be non-negative")
    lo, hi = region
    lo_arr = np.asarray(lo, dtype=np.float32)
    hi_arr = np.asarray(hi, dtype=np.float32)
    rng = np.random.default_rng(int(seed))
    ts = np.empty((count, 4, 4), dtype=np.float32)
    ts[:] = np.eye(4, dtype=np.float32)
    if count:
        pts = rng.uniform(lo_arr, hi_arr, size=(count, 3)).astype(np.float32)
        ts[:, 0, 3] = pts[:, 0]
        ts[:, 1, 3] = pts[:, 1]
        ts[:, 2, 3] = pts[:, 2]
    return InstancedMesh(base_mesh=mesh, instance_data=InstanceData(ts))


def circle(mesh: Mesh, count: int, radius: float) -> InstancedMesh:
    """Place ``count`` instances equidistantly on a circle of ``radius`` in XZ."""
    if count < 0:
        raise ValueError("circle count must be non-negative")
    ts = np.empty((count, 4, 4), dtype=np.float32)
    ts[:] = np.eye(4, dtype=np.float32)
    if count:
        thetas = np.linspace(0.0, 2.0 * np.pi, count, endpoint=False)
        xs = np.cos(thetas) * float(radius)
        zs = np.sin(thetas) * float(radius)
        for i in range(count):
            ts[i] = _translation_matrix(float(xs[i]), 0.0, float(zs[i]))
    return InstancedMesh(base_mesh=mesh, instance_data=InstanceData(ts))


def from_transforms(mesh: Mesh, transforms) -> InstancedMesh:
    """Wrap an explicit list/array of 4x4 model matrices."""
    ts = np.asarray(transforms, dtype=np.float32)
    if ts.ndim == 2 and ts.shape == (4, 4):
        ts = ts[None, ...]
    if ts.ndim != 3 or ts.shape[1:] != (4, 4):
        raise ValueError(
            f"from_transforms expects (N, 4, 4) matrices, got shape {ts.shape}"
        )
    return InstancedMesh(base_mesh=mesh, instance_data=InstanceData(ts.copy()))


# ----------------------------------------------------------------------
# WGSL — vertex shader consumes an SSBO of per-instance model matrices.
# ----------------------------------------------------------------------
INSTANCED_MESH_WGSL = """// slappyengine instanced_mesh
// Per-instance rendering: reads the base mesh vertex stream once and
// fetches an @builtin(instance_index)-indexed per-instance transform out
// of a storage buffer (SSBO). Phong-lit forward output — matches
// PHONG_3D_WGSL binding conventions so it drops into the same passes.
struct Camera { view_proj: mat4x4<f32>, cam_pos: vec4<f32> };
struct LightSlot {
    pos_kind: vec4<f32>,
    dir_range: vec4<f32>,
    color_intensity: vec4<f32>,
    spot_enable_pad: vec4<f32>,
};
struct Lights {
    slots: array<LightSlot, 4>,
    ambient: vec4<f32>,
};
struct Instance {
    model: mat4x4<f32>,
    color: vec4<f32>,
    uv_offset_pad: vec4<f32>,
};
struct Instances {
    data: array<Instance>,
};

@group(0) @binding(0) var<uniform> cam: Camera;
@group(0) @binding(1) var<uniform> lights: Lights;
@group(1) @binding(0) var<storage, read> instances: Instances;

struct VSIn {
    @location(0) position: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) uv: vec2<f32>,
};
struct VSOut {
    @builtin(position) clip: vec4<f32>,
    @location(0) world_pos: vec3<f32>,
    @location(1) world_normal: vec3<f32>,
    @location(2) uv: vec2<f32>,
    @location(3) color: vec4<f32>,
};

@vertex
fn vs_main(in: VSIn, @builtin(instance_index) iid: u32) -> VSOut {
    var out: VSOut;
    let inst = instances.data[iid];
    let world = inst.model * vec4<f32>(in.position, 1.0);
    out.world_pos = world.xyz;
    let nrm4 = inst.model * vec4<f32>(in.normal, 0.0);
    out.world_normal = normalize(nrm4.xyz);
    out.uv = in.uv + inst.uv_offset_pad.xy;
    out.clip = cam.view_proj * world;
    out.color = inst.color;
    return out;
}

@fragment
fn fs_main(in: VSOut) -> @location(0) vec4<f32> {
    let n = normalize(in.world_normal);
    let base = in.color.rgb;
    var rgb = base * lights.ambient.rgb * lights.ambient.a;
    let view_dir = normalize(cam.cam_pos.xyz - in.world_pos);
    for (var i: i32 = 0; i < 4; i = i + 1) {
        let slot = lights.slots[i];
        if (slot.spot_enable_pad.y < 0.5) { continue; }
        let L = -normalize(slot.dir_range.xyz);
        let ndl = max(dot(n, L), 0.0);
        let h = normalize(L + view_dir);
        let spec = pow(max(dot(n, h), 0.0), 32.0);
        rgb = rgb + (base * ndl + spec * 0.4) * slot.color_intensity.rgb * slot.color_intensity.w;
    }
    return vec4<f32>(rgb, in.color.a);
}
"""


# ----------------------------------------------------------------------
# Packing helpers
# ----------------------------------------------------------------------
_INSTANCE_STRIDE_FLOATS = 16 + 4 + 4  # mat4 + color + uv_offset(pad)
_INSTANCE_STRIDE_BYTES = _INSTANCE_STRIDE_FLOATS * 4  # 96 bytes


def _flatten_instance_block(
    instance_data: InstanceData, *, with_extras: bool
) -> np.ndarray:
    """Contiguous float32 block, one instance per row.

    Layout when ``with_extras`` is True (SSBO / rich UBO)::
        [mat4x4 (16 floats)] [color (4)] [uv_offset xy pad pad (4)]

    Layout when ``with_extras`` is False (mat-only UBO)::
        [mat4x4 (16 floats)]
    """
    n = instance_data.instance_count
    ts = instance_data.instance_transforms.reshape(n, 16)
    if not with_extras:
        return np.ascontiguousarray(ts, dtype=np.float32)
    block = np.zeros((n, _INSTANCE_STRIDE_FLOATS), dtype=np.float32)
    block[:, 0:16] = ts
    if instance_data.instance_colors is not None:
        block[:, 16:20] = instance_data.instance_colors
    else:
        block[:, 16:20] = 1.0  # opaque white default
    if instance_data.instance_uv_offsets is not None:
        block[:, 20:22] = instance_data.instance_uv_offsets
    return np.ascontiguousarray(block, dtype=np.float32)


def pack_instance_ubo(instance_data: InstanceData) -> bytes:
    """Pack per-instance model matrices into a uniform-buffer blob.

    Contains **only** the model matrices (``N * 64 bytes``) — this is the
    small-instance-count path where downstream shaders read a fixed-size
    array<mat4x4, K>.
    """
    if not isinstance(instance_data, InstanceData):
        raise TypeError("pack_instance_ubo expects an InstanceData")
    ts = instance_data.instance_transforms  # (N, 4, 4) float32
    return np.ascontiguousarray(ts, dtype=np.float32).tobytes()


def pack_instance_ssbo(instance_data: InstanceData) -> bytes:
    """Pack model + color + uv_offset into a storage-buffer blob.

    Stride is 96 bytes per instance: ``mat4x4 (64) + vec4 color (16) +
    vec4 uv_offset_pad (16)``. This matches :data:`INSTANCED_MESH_WGSL`'s
    ``struct Instance`` layout.
    """
    if not isinstance(instance_data, InstanceData):
        raise TypeError("pack_instance_ssbo expects an InstanceData")
    block = _flatten_instance_block(instance_data, with_extras=True)
    return block.tobytes()


# ----------------------------------------------------------------------
# Dispatch — one draw call, N instances.
# ----------------------------------------------------------------------
def _null_of(renderer: Any) -> Any:
    """Return the underlying NullRenderer for both wgpu Renderer + NullRenderer."""
    n = getattr(renderer, "_null", None)
    return n if n is not None else renderer


def render_instanced(
    renderer: Any,
    instanced_mesh: InstancedMesh,
    material: Any,
    camera: Any | None = None,
) -> None:
    """Submit ``instanced_mesh`` as a single instanced draw call.

    * On the NullRenderer path (headless / CI / ``App(enable_gpu=False)``)
      this appends **one** ``DrawCall(kind="mesh", ...)`` with
      ``instance_count`` in the payload, matching the "one draw call for
      N instances" contract.
    * On the wgpu path the same log entry is recorded via
      ``Renderer._null.draw_log.append`` and the real submission would go
      through the instanced pipeline (out-of-scope for LL3 — the CPU
      Renderer records the intent and the GPU path is stubbed).

    ``camera`` is optional; when provided the renderer's camera state is
    updated via :meth:`set_camera` before submission.

    Raises
    ------
    TypeError
        If *renderer* is ``None`` or *instanced_mesh* is not an
        :class:`InstancedMesh`.
    """
    from .null_renderer import DrawCall  # local import to avoid cycles

    if renderer is None:
        raise TypeError("render_instanced: renderer must not be None")
    if not isinstance(instanced_mesh, InstancedMesh):
        raise TypeError(
            "render_instanced: instanced_mesh must be InstancedMesh; "
            f"got {type(instanced_mesh).__name__}"
        )
    if camera is not None and hasattr(renderer, "set_camera"):
        if hasattr(camera, "view_matrix") and hasattr(camera, "projection_matrix"):
            renderer.set_camera(camera.view_matrix(), camera.projection_matrix())

    null = _null_of(renderer)
    payload = {
        "vertex_count": int(instanced_mesh.base_mesh.vertices.shape[0]),
        "triangle_count": int(instanced_mesh.base_mesh.indices.shape[0]),
        "instance_count": int(instanced_mesh.instance_count),
        "instanced": True,
        "material_name": getattr(material, "name", "default"),
        "base_color": getattr(material, "base_color", (1.0, 1.0, 1.0, 1.0)),
        "alpha_mode": getattr(material, "alpha_mode", "opaque"),
        "bounding_box_all": instanced_mesh.bounding_box_all,
    }
    null.draw_log.append(DrawCall("mesh", payload))


# Convenience method-style entry point — some call sites prefer OO style.
def submit_instanced(
    renderer: Any,
    instanced_mesh: InstancedMesh,
    material: Any,
    camera: Any | None = None,
) -> None:
    """Alias for :func:`render_instanced` with a Renderer-method-like name."""
    render_instanced(renderer, instanced_mesh, material, camera)


__all__ = [
    "INSTANCED_MESH_WGSL",
    "InstanceData",
    "InstancedMesh",
    "circle",
    "from_transforms",
    "grid",
    "pack_instance_ssbo",
    "pack_instance_ubo",
    "random_scatter",
    "render_instanced",
    "submit_instanced",
]
