<!-- handauthored: do not regenerate -->
# slappyengine.gpu — API Reference

> Hand-written reference for the renderer GPU subpackage. Covers the
> wgpu context wrapper, the entity / mesh render pipelines, the
> texture and buffer managers, the PBR material struct, the IBL and
> clustered-lighting helpers, and the SDF-extrude mesh generator.
>
> For the compute-shader dispatch surface (stats, spatial, pixel
> mutation), see [`compute.md`](compute.md). For the lighting compute
> kernels see [`gi.md`](gi.md).

```python
from slappyengine.gpu import (
    GPUContext, BufferManager, TextureManager, MaterialBuffer,
    RenderPipeline, EntityRenderer,
    MeshPipeline, MeshRenderer, GpuMesh, MeshVertex, PbrMaterial,
    IBLSystem, ClusterPipeline, Cluster3DSystem, SdfRenderer,
)
```

## Overview

Every name is **lazy-loaded** via `__getattr__` (see `gpu/__init__.py`'s
`_LAZY_MAP`), so importing `slappyengine.gpu` is cheap — wgpu does not
land until you actually touch a class. Headless CI imports the engine
without ever instantiating any GPU symbol.

## GPUContext

Owns the wgpu adapter, device, queue, and surface configuration. One
per `Engine`.

```python
ctx = GPUContext(canvas)          # WgpuCanvas from wgpu.gui.auto
ctx.initialize(cfg=engine_cfg)    # picks backend + power-pref from cfg.rendering
```

`initialize(cfg)` reads `cfg.rendering.backend` (auto / vulkan / metal /
dx12 / webgpu / gl) and `cfg.rendering.power_preference`
(`auto` / `high_performance` / `low_power`) and:

1. Calls `set_instance_extras(backends=[…])` to restrict wgpu before the
   first adapter request (silently falls back to auto on failure).
2. Requests the adapter + device, logs the chosen device + backend.
3. Configures the canvas surface with
   `RENDER_ATTACHMENT | COPY_SRC` (lighting needs `COPY_SRC` to copy
   the scene texture into its own offscreen target).

Convenience methods used everywhere downstream:

| Method | Effect |
|---|---|
| `get_current_texture()` | Acquire the next swapchain image. |
| `create_encoder(label="")` | New `GPUCommandEncoder`. |
| `submit(*encoders)` | Finish each encoder and submit in order. |
| `create_buffer(*, size, usage, …)` | Pass-through to `device.create_buffer`. |
| `write_buffer(buf, data, offset=0)` | Pass-through to `queue.write_buffer`. |
| `write_texture(dst, data, layout, size)` | Pass-through to `queue.write_texture`. |
| `limits` (property) | `device.limits`. |

## BufferManager

Allocates and caches storage / uniform / vertex / index buffers, keyed
by `id(layer)` so the same `Layer` always gets the same GPU buffer.

| Method | Effect |
|---|---|
| `create_pixel_buffer(layer)` | `w*h*registry.stride_bytes()` storage buffer, 16-byte aligned, init with per-channel defaults from the `StructRegistry`. |
| `get_pixel_buffer(layer)` / `release_pixel_buffer(layer)` | Cache lookup / destroy + evict. |
| `update_pixel_buffer(layer, data)` | `queue.write_buffer` the whole region. |
| `create_uniform_buffer(name, size_bytes)` | 256-byte-aligned uniform (wgpu requirement); cached by name. |
| `update_uniform(name, data)` | `bytes` or `np.ndarray` → `queue.write_buffer`. |
| `create_quad_geometry()` | Returns `(vbuf, ibuf)` — `[x,y,u,v]×4`, 6 indices, span `[0,0]→[1,1]` (vertex shader scales by entity size). |
| `create_material_buffer(material_map)` | Owns one `MaterialBuffer` per scene. |
| `destroy_all()` | Frees every cached buffer. |

`create_pixel_buffer` will raise `ValueError` if `layer.size` is `None`
— load the image data first.

## TextureManager

Caches wgpu textures, keyed by `id(layer)` (and `("array", id(cube_array))`
for `CubeArray` layouts).

| Method | Effect |
|---|---|
| `upload_layer(layer)` | RGBA8 2D texture from `layer._image_data`; creates a 1×1 zero texture if the layer has no data yet. |
| `upload_frame_array(layer, frame_count, frame_data)` | Animation frame array as a `Texture2DArray` (`array_layer_count = frame_count`). |
| `upload_layer_array(cube_array)` | Pack a `CubeArray`'s layers into a single `Texture2DArray`; auto-invalidates if depth changes. |
| `create_view(texture, dimension="2d")` | `"2d"` or `"2d-array"`. |
| `create_array_view(texture)` | Shortcut for the 2d-array view. |
| `create_sampler(filter_mode="nearest")` | `nearest` or `linear`, `clamp_to_edge` U/V, nearest mip filter. |
| `invalidate(layer)` / `invalidate_array(cube_array)` | Drop a single cache entry. |
| `destroy_all()` | Destroy every cached texture. |

## RenderPipeline + EntityRenderer

The default 2D-entity render path: one quad per visible
`RenderTarget`, sorted by `z_order`.

- `RenderPipeline(ctx).build()` compiles `quad_vert.wgsl` +
  `quad_frag.wgsl` + `quad_frag_array.wgsl`, builds the two bind-group
  layouts (camera uniform, texture+sampler), and emits two pipelines
  — one for plain 2D textures, one for the `Texture2DArray` path used
  by `CubeArray` / frame animations.
- `EntityRenderer(ctx, tex_mgr, buf_mgr, pipeline).initialize()`
  allocates a shared quad VBO/IBO, a 64-byte camera uniform
  (`view_matrix()`), and a nearest sampler.
- `render(scene, pass_enc)` filters `scene.entities` to visible
  `RenderTarget`s, sorts by `z_order`, and dispatches the matching
  pipeline (array vs. flat) per entity.

## MaterialBuffer

Packs the engine's `MaterialMap` into a 32-byte std430 entry per
material — `[r_min, r_max, g_min, g_max, b_min, b_max, material_index,
_pad]` — uploaded as a storage buffer. `update(material_map)`
re-allocates if the count changes or just rewrites the existing buffer
otherwise. Used by the pixel-classification shader to look up
material indices from RGB inputs.

## 3D mesh pipeline

Stack: `MeshPipeline` (one per `GPUContext`) → `MeshRenderer` (one per
3D `Layer`) → `GpuMesh` (one per mesh asset) + `PbrMaterial` (per-mesh
material).

### MeshPipeline

Compiles `mesh_vert_3d.wgsl` + `mesh_frag_pbr_simple.wgsl` once and
manages a shared depth texture.

> **Sprint 7B binding fix.** Earlier revisions wired
> `mesh_frag_pbr.wgsl`, whose declared bindings include textures,
> dynamic lights, and IBL on groups 1 / 2. The current pipeline binds
> only `group(0).0` (MeshUniforms — 256 bytes) and `group(1).0`
> (PBR material — 48 bytes), so it pairs with the **simple** fragment
> shader. The full PBR shader is reserved for `ClusterPipeline` /
> `IBLSystem` which provide the extra resources.

Vertex layout (48 bytes/vertex, single interleaved slot):

```
@location(0) position : vec3<f32>   offset  0
@location(1) normal   : vec3<f32>   offset 12
@location(2) uv       : vec2<f32>   offset 24
@location(3) tangent  : vec4<f32>   offset 32
```

`triangle_list`, `cull=back`, `front_face=ccw`, depth `depth24plus`
with `compare=less`, `write=true`, opaque colour target (compositor
blends 3D over 2D).

Surface:

- `ensure_depth_texture(width, height)` — recreates the depth target
  iff the viewport size changed; call at the start of every frame.
- `make_camera_bind_group(camera_buf)` / `make_material_bind_group(mat_buf)`
  — factories; the `MeshRenderer` calls these whenever its underlying
  uniform changes.
- Properties: `pipeline`, `depth_view`, `camera_bgl`, `material_bgl`.
  `depth_view` raises `RuntimeError` if `ensure_depth_texture` has not
  been called.

### MeshRenderer

```python
renderer = MeshRenderer(gpu, pipeline)
renderer.set_mesh(GpuMesh.unit_cube())
renderer.set_material(PbrMaterial(metallic=0.0, roughness=0.5))
renderer.update_camera(model, view, proj, normal_matrix)
renderer.draw(render_pass)
```

- `set_mesh(mesh)` — calls `mesh.upload(device)` (idempotent).
- `set_material(material)` — first call allocates a 48-byte uniform;
  subsequent calls reuse the buffer and rebuild only the bind group.
- `update_camera(model, view, proj, normal_matrix)` — packs 64 × f32
  (256 bytes) matching the WGSL `MeshUniforms` struct.
- `draw(render_pass)` — no-op if any of mesh / camera BG / material BG
  is unset, so partial setup is safe.
- `render_to_texture(width, height, output_format="rgba8unorm")`
  → `wgpu.GPUTexture` — used by `Layer.bake_to_2d` for thumbnails /
  baking; the caller owns the returned texture.

### GpuMesh + MeshVertex

`MeshVertex(position, normal, uv, tangent)` is a packed dataclass
(`pack() -> bytes` = `struct.pack("3f3f2f4f", …)`).

`GpuMesh(vertices, indices)`:

- `unit_cube()` classmethod — 24 verts (4/face × 6 faces) + 36 indices,
  per-face flat normals + tangents. UVs use Y-flipped corners for GPU
  conventions.
- `unit_quad()` classmethod — XY plane quad for 2D→3D texture
  projection.
- `vertex_bytes()` / `index_bytes()` — raw bytes for upload.
- `upload(device)` — idempotent vertex+index buffer creation.
- Properties: `vertex_buffer`, `index_buffer`, `vertex_count`,
  `index_count`.

### PbrMaterial

```python
PbrMaterial(
    metallic=0.0, roughness=0.5, ior=1.5,
    albedo_color=(1, 1, 1, 1),
    emissive_color=(0, 0, 0), emissive_strength=0.0,
    albedo_texture=None, normal_map=None,
)
```

`to_gpu_bytes()` packs a 48-byte std430 struct (vec4 albedo, three
scalars + pad, vec3 emissive, scalar emissive_strength). The texture
paths are reserved for the textured pipelines — the simple shader
ignores them.

## SdfRenderer + SdfExtruder

`SdfRenderer` (in `gpu/sdf_renderer.py`) is the full SDF-based 2D
renderer used by `Layer(mode="sdf")` — see source for the per-shape
shader catalogue.

`SdfExtruder` (`gpu/sdf_extruder.py`, **not** in `__all__` but
load-bearing for 2D→3D baking) generates a `GpuMesh` from a 2D alpha
mask:

```python
mesh = SdfExtruder(gpu=ctx).extrude(mask, depth=1.0, scale=1.0, threshold=0.5)
# or:
mesh = SdfExtruder.from_layer(layer_2d, depth=1.0, scale=1.0, gpu=ctx)
```

`extrude(mask, depth, scale, threshold)` accepts `uint8` 0–255 or
`float32` 0.0–1.0, in `(H, W)` / `(H, W, C)` / `(H, W, 4)` (alpha
channel) forms. If a `GPUContext` is supplied the dispatch runs as a
compute shader (`shaders/sdf_3d_extrude.wgsl`); any GPU failure
**degrades gracefully** to the CPU path, which mirrors the WGSL
algorithm exactly so results are byte-equivalent modulo float
ordering. The GPU path is O(pixels), fully parallel, and reads back
through MAP_READ-mapped staging buffers.

## IBL + clustered lighting

- `IBLSystem(ctx)` — image-based lighting helpers: env-map upload,
  irradiance / radiance prefilter dispatches, BRDF LUT. Bound on the
  full PBR shader's group(2).
- `ClusterPipeline(ctx)` — 2D clustered light pipeline (XY tile
  binning).
- `Cluster3DSystem(ctx)` — 3D froxel clustering for the volumetric
  fog + 3D-mesh lighting paths.

These are the "wire the full PBR shader" side of the GPU stack and
are covered in detail by the lighting design docs
(`lighting_presets.md`, `docs/api/gi.md`).
