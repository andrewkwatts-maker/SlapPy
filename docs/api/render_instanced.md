<!-- handauthored: do not regenerate -->
# pharos_engine.render.instanced — API Reference

> Hand-written reference for the LL3 instanced-mesh submission surface.
> Draws N copies of one :class:`~pharos_engine.render.mesh.Mesh` in a
> single draw call — grass fields, brick walls, particle billboards,
> foliage scatter. Sibling references:
> [`render_scene_walker.md`](render_scene_walker.md) is the frustum-cull
> feed that decides which instanced meshes reach the renderer this
> frame; [`render_bvh_3d.md`](render_bvh_3d.md) sits behind the walker
> for large scenes; [`capture.md`](capture.md) records the resulting
> output for regression baselines.

## Overview

`pharos_engine.render.instanced` is the Nova3D parity Sprint 16 landing
(task LL3). It packages three things into one module:

* A pair of dataclasses (:class:`InstanceData`, :class:`InstancedMesh`)
  that carry per-instance model matrices, RGBA colours, and UV
  offsets alongside the base mesh and a union AABB.
* Four factory helpers (:func:`grid`, :func:`random_scatter`,
  :func:`circle`, :func:`from_transforms`) that emit an
  :class:`InstancedMesh` from common authoring shorthand.
* Two byte-buffer packing helpers (:func:`pack_instance_ubo`,
  :func:`pack_instance_ssbo`) that flatten the per-instance attributes
  into the fixed strides consumed by :data:`INSTANCED_MESH_WGSL`.

Actual submission goes through :func:`render_instanced` which appends
**exactly one** `DrawCall(kind="mesh", ...)` carrying an
`instance_count` payload to the renderer's `draw_log`. Both the real
wgpu :class:`~pharos_engine.render.renderer.Renderer` and the headless
`NullRenderer` used in CI are supported.

## Public surface

```python
from pharos_engine.render.instanced import (
    InstanceData, InstancedMesh,
    grid, random_scatter, circle, from_transforms,
    pack_instance_ubo, pack_instance_ssbo,
    render_instanced, submit_instanced,
    INSTANCED_MESH_WGSL,
)
```

## Classes

### `InstanceData`

_dataclass — defined in `pharos_engine.render.instanced`_

Per-instance attribute pack. Validates shapes in `__post_init__`.

| Field | Type | Notes |
|-------|------|-------|
| `instance_transforms` | `np.ndarray[N, 4, 4] float32` | Required. Model matrices. |
| `instance_colors` | `np.ndarray[N, 4] float32 \| None` | Optional. RGBA per instance. |
| `instance_uv_offsets` | `np.ndarray[N, 2] float32 \| None` | Optional. |
| `instance_count` | `int` (init=False) | Cached `N`. |

Raises `ValueError` when transforms are not `(N, 4, 4)`, or when the
optional colour / UV arrays disagree with `N`.

### `InstancedMesh`

_dataclass — defined in `pharos_engine.render.instanced`_

```python
InstancedMesh(base_mesh: Mesh, instance_data: InstanceData)
```

Pairs a base :class:`~pharos_engine.render.mesh.Mesh` with its
per-instance attribute pack. `__post_init__` computes
`bounding_box_all` — the union AABB after applying every instance's
transform to the base mesh's corners. `instance_count` is proxied
through from the wrapped :class:`InstanceData`.

## Factory helpers

### `grid(mesh, rows, cols, spacing) -> InstancedMesh`

Row-major XZ grid centred on the origin (`Y = 0`). Raises `ValueError`
when `rows` or `cols` is negative.

### `random_scatter(mesh, count, region, *, seed=0) -> InstancedMesh`

Scatter `count` instances inside the AABB `region = ((lo_xyz), (hi_xyz))`.
Deterministic under a fixed `seed`.

### `circle(mesh, count, radius) -> InstancedMesh`

Place `count` instances equidistantly on a circle of `radius` in XZ.

### `from_transforms(mesh, transforms) -> InstancedMesh`

Wrap an explicit `(N, 4, 4)` array of model matrices (a single
`(4, 4)` is broadcast to `N=1`).

## Packing helpers

### `pack_instance_ubo(instance_data) -> bytes`

Model-matrices-only blob: `N * 64` bytes. Small-instance-count path
where the shader reads a fixed-size `array<mat4x4, K>` in a UBO.

### `pack_instance_ssbo(instance_data) -> bytes`

Full `mat4 + vec4 color + vec4 uv_offset_pad` stride (96 bytes per
instance) — matches :data:`INSTANCED_MESH_WGSL`'s `struct Instance`.
Both raise `TypeError` when the argument is not an :class:`InstanceData`.

## Functions

### `render_instanced(renderer, instanced_mesh, material, camera=None) -> None`

_defined in `pharos_engine.render.instanced`_

Submit `instanced_mesh` as a single draw call carrying `instance_count`
in the payload. On the NullRenderer path this appends the entry to
`renderer.draw_log`; on the wgpu path the same log entry is recorded
via `Renderer._null.draw_log.append` and the GPU submission is stubbed
(the CPU-side intent is what LL3 locked in).

Raises `TypeError` when `renderer` is `None` or `instanced_mesh` is
not an :class:`InstancedMesh`.

### `submit_instanced(renderer, instanced_mesh, material, camera=None) -> None`

Alias for :func:`render_instanced` with a Renderer-method-like name.

## Constants

### `INSTANCED_MESH_WGSL`

_str — defined in `pharos_engine.render.instanced`_

Full vertex + fragment WGSL that reads a base-mesh vertex stream once
and looks up `@builtin(instance_index)`-indexed per-instance data from
a storage buffer. Phong-lit forward output — matches the
`PHONG_3D_WGSL` binding conventions so it drops into the same render
passes.

## Usage

```python
import numpy as np
from pharos_engine.render.instanced import grid, render_instanced
from pharos_engine.render.mesh import Mesh
from pharos_engine.render.null_renderer import NullRenderer

# 8x8 grid of unit cubes, 2.0 units apart.
mesh = Mesh.cube()                # any (V, N, I)-shaped Mesh
instanced = grid(mesh, rows=8, cols=8, spacing=2.0)

renderer = NullRenderer()
render_instanced(renderer, instanced, material=None)

# Exactly one draw call for all 64 instances.
call = renderer.draw_log[-1]
assert call.kind == "mesh"
assert call.payload["instance_count"] == 64
assert call.payload["instanced"] is True
```

## Skip the wrapper

`pharos_engine.render.instanced` is Python-only. Grep of
`pharos_engine._core_facade.RUST_MODULE_MAP` shows **no** `instanced`
entry — the packing helpers already output contiguous float32 blocks
`numpy` builds at C-speed, and the dispatch cost is one Python append.
If a future GPU submission path lands, the `pack_instance_ssbo` byte
layout is stable and can feed a Rust-side upload without churning
the Python API.

For direct WGSL binding without the wrapper, take
:data:`INSTANCED_MESH_WGSL` as-is and upload
`pack_instance_ssbo(instance_data)` into your own SSBO at group 1,
binding 0.

## See also

- [`render_scene_walker.md`](render_scene_walker.md) — feeds instanced
  meshes through frustum culling before dispatch.
- [`render_bvh_3d.md`](render_bvh_3d.md) — sits between the walker and
  the renderer for large-N scenes.
- [`capture.md`](capture.md) — record the resulting output for
  regression baselines.
