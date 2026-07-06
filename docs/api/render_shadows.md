<!-- handauthored: do not regenerate -->
# slappyengine.render.shadows — API Reference

> Hand-written reference for the JJ7 cascaded shadow maps subsystem.
> Math + WGSL snippets for practical PSSM split scheme, directional-light
> view / ortho projection, texel-snap stabilisation, and a 4-cascade 3x3
> PCF sampler. Sibling references:
> [`render_scene_walker.md`](render_scene_walker.md) shares the camera /
> matrix conventions this module builds on;
> [`post_process.md`](post_process.md) hosts the `ShadowCSM` post-process
> pass wiring; the actual wgpu shadow pipeline lives inside the HH4
> renderer described in [`gpu.md`](gpu.md).

## Overview

`slappyengine.render.shadows` is the math + WGSL-source layer of the
Nova3D-parity cascaded shadow map (CSM) implementation. It computes
per-cascade splits, light-space view / ortho projections, and packs the
result into a UBO blob the shader consumes. Downstream renderers
allocate the `texture_depth_2d_array` and dispatch the depth-only pass;
this module owns none of the GPU wiring.

The Engel/Zhang "practical PSSM" split scheme blends uniform and
logarithmic splits via the `cascade_split_lambda` knob (0 = uniform,
1 = logarithmic). Frustum corners are transformed into light space to
compute the ortho AABB, then optionally snapped to a texel-sized grid
so cascades stop shimmering as the camera slides.

## Public surface

```python
from slappyengine.render.shadows import (
    CSMBuilder,
    CascadeSplit,
    ShadowMapConfig,
    SHADOW_DEPTH_ONLY_WGSL,
    SHADOW_SAMPLE_WGSL_SNIPPET,
    SHADOW_SAMPLER_DESC,
    find_cascade_for_world_pos,
    pack_cascade_ubo,
)
```

## Classes

### `ShadowMapConfig`

_dataclass — defined in `slappyengine.render.shadows`_

```python
ShadowMapConfig(
    resolution: int = 2048,
    cascade_count: int = 4,
    cascade_split_lambda: float = 0.5,
    max_shadow_distance: float = 100.0,
    stabilize_cascades: bool = True,
)
```

`resolution` is per-cascade texture side length (square, power-of-two
preferred). `cascade_split_lambda` in `[0, 1]` blends uniform and
logarithmic splits.

### `CascadeSplit`

_dataclass — defined in `slappyengine.render.shadows`_

Populated by `CSMBuilder.build_cascades`.

| Field | Type | Notes |
|-------|------|-------|
| `near_z` / `far_z` | `float` | Split's near / far in view-space z. |
| `light_view_matrix` | `np.ndarray` | 4x4 float32 view. |
| `light_projection_matrix` | `np.ndarray` | 4x4 float32 ortho with reverse-Y `z in [0, 1]`. |
| `light_view_projection` | `np.ndarray` | Product; consumed by the shader. |
| `shadow_map_index` | `int` | 0..cascade_count-1. |

### `CSMBuilder`

_class — defined in `slappyengine.render.shadows`_

Container of static / classmethod helpers. Every method is functional
and matrix-only — no wgpu / GPU handles.

- `compute_cascade_splits(near, far, count, lambda_) -> list[(n, f)]`
  — practical PSSM splits. Raises `ValueError` when `far <= near`.
- `compute_light_view(directional_light) -> (4, 4) float32`
  — right-handed `look_at` synthesised from the light's `direction`.
- `frustum_corners_world(view_projection) -> (8, 3) float32`
  — invert `view_projection`, transform the NDC cube corners.
- `compute_ortho_bounds(view_projection, light_view) -> (l, r, b, t, n, f)`
  — light-space AABB of the view frustum.
- `stabilize(bounds, resolution) -> bounds` — texel-snap the AABB origin.
- `build_cascades(camera, light, config) -> list[CascadeSplit]`
  — full setup. Snapshots camera near/far, mutates them per cascade,
  restores in a `finally`.

## Functions

### `pack_cascade_ubo(cascades) -> bytes`

_defined in `slappyengine.render.shadows`_

Pack up to 4 `light_view_projection` matrices into a 256-byte
`array<mat4x4<f32>, 4>` UBO blob. Missing cascades are zero-filled.

### `find_cascade_for_world_pos(world_pos, cascades) -> int`

_defined in `slappyengine.render.shadows`_

Return the tightest cascade index whose projection covers `world_pos`.
Falls back to the last cascade index for points beyond the last split so
the shader still samples something.

## Constants

### `SHADOW_DEPTH_ONLY_WGSL`

WGSL source for the depth-only vertex + minimal fragment stub. The
fragment returns `vec4<f32>(0.0)` so API-validation layers that reject
depth-only pipelines still accept the module.

### `SHADOW_SAMPLE_WGSL_SNIPPET`

Fragment-shader snippet that samples the 4-cascade
`texture_depth_2d_array` with 3x3 PCF and returns a `[0, 1]` visibility
scalar. Consumers concatenate this into their lit shader.

### `SHADOW_SAMPLER_DESC`

Sampler descriptor dict (`compare="less_equal"`, linear min/mag) for the
comparison sampler the snippet reads.

## Usage

```python
from slappyengine.render import Camera3D
from slappyengine.render.light import Light
from slappyengine.render.shadows import (
    CSMBuilder, ShadowMapConfig, pack_cascade_ubo,
)

camera = Camera3D()
sun = Light(kind="directional", direction=(-0.5, -1.0, -0.2))
config = ShadowMapConfig(cascade_count=4, resolution=1024)

cascades = CSMBuilder.build_cascades(camera, sun, config)
ubo_bytes = pack_cascade_ubo(cascades)
assert len(ubo_bytes) == 256
```

## Skip the wrapper

`slappyengine.render.shadows` is Python-only. There is **no** Rust
equivalent under `slappyengine._core`; the split / view / ortho math is
pure numpy, and the WGSL sources are string constants that the HH4
renderer submits directly to wgpu. Bypassing the wrapper for the CSM
math would mean re-implementing Engel/Zhang PSSM in the caller — not
recommended. If the CSM setup becomes a per-frame hot path in the
future, this is the module that would be promoted to a Rust kernel
(see [`../rust_migration_audit_2026_07_05.md`](../rust_migration_audit_2026_07_05.md)).

## See also

- [`render_scene_walker.md`](render_scene_walker.md) — JJ5 walker whose
  camera conventions this module shares.
- [`post_process.md`](post_process.md) — `ShadowCSM` post-process pass
  that consumes the packed UBO.
- [`gpu.md`](gpu.md) — HH4 renderer that allocates the shadow
  `texture_depth_2d_array` and dispatches the depth-only pass.
