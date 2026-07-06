<!-- handauthored: do not regenerate -->
# slappyengine.render.scene_walker — API Reference

> Hand-written reference for the JJ5 scene walker.
> Traverses an FF3 [`scenes.Scene`](../architecture_overview.md) and emits
> per-entity draw calls through the HH4 [`Renderer`](gpu.md), performing
> six-plane frustum culling along the way. Sibling references:
> [`render_bvh_3d.md`](render_bvh_3d.md) for the KK1 BVH that wraps this
> walker's linear entity loop, [`render_shadows.md`](render_shadows.md)
> for the JJ7 CSM math that shares camera conventions with `Frustum`,
> [`asset_import.md`](asset_import.md) for the loaders `_resolve_mesh_from_path`
> routes through.

## Overview

`slappyengine.render.scene_walker` is the docs-only bridge between the
FF3 scene data model (entities + `params` dicts on disk) and the HH4
renderer's `submit_mesh(mesh, transform, material)` surface. It reads a
scene, resolves each entity's mesh and material, composes a 4x4 TRS
matrix from `position` / `rotation` / `scale`, and submits every visible
entity through a pluggable renderer once per walk.

Culling is a pure numpy six-plane frustum extraction (Gribb-Hartmann,
inward-pointing planes) tested against each entity's transformed AABB
via the standard p-vertex fast test. The walker is intentionally
Python-only; hot loops still land in the HH4 renderer / Rust kernels
(see [`gpu.md`](gpu.md)).

## Public surface

```python
from slappyengine.render.scene_walker import (
    AssetCache,
    EntityDrawInfo,
    Frustum,
    RenderStats,
    SceneWalker,
    bridge_render_scene,
    render_scene,
)
```

## Classes

### `SceneWalker`

_class — defined in `slappyengine.render.scene_walker`_

Walks a scene once per `walk()` call and submits entities through the
renderer.

```python
SceneWalker(
    scene,
    *,
    prefab_library=None,
    asset_cache: AssetCache | None = None,
    material_registry=None,
    default_mesh: Mesh | None = None,
) -> None
```

Methods:

- `register_material(material_id: str, material: Material) -> None`
  — expose a `Material` under a string id used by scene entities'
  `params["material_id"]`.
- `resolve_entity(entity: dict) -> EntityDrawInfo | None`
  — dictionary in, resolved draw info out; returns `None` on malformed
  entity or unresolved prefab reference.
- `walk(renderer, camera, *, stats=None) -> RenderStats`
  — traverse once. `camera=None` disables frustum culling.
- `walk_with_lights(renderer, camera, lights, *, stats=None) -> RenderStats`
  — same as `walk`, but front-loads `renderer.set_lights(lights)` when
  the renderer exposes it.

Raises:

- `TypeError` — on `scene is None`, on a scene without `entities`, on a
  renderer without `submit_mesh`.

### `Frustum`

_dataclass — defined in `slappyengine.render.scene_walker`_

Six-plane view frustum extracted from a `view_projection()` 4x4.

```python
Frustum(planes: np.ndarray)  # (6, 4) float32
```

- `Frustum.from_camera(camera) -> Frustum` — accepts anything exposing
  `view_projection()`, or a raw 4x4 ndarray. Raises `TypeError` /
  `ValueError` on shape mismatch.
- `intersects_aabb(aabb) -> bool` — standard p-vertex plane test.

### `EntityDrawInfo`

_dataclass — defined in `slappyengine.render.scene_walker`_

Resolved per-entity draw record.

| Field | Type | Notes |
|-------|------|-------|
| `entity_id` | `str` | Echo of the FF3 id. |
| `mesh` | `Mesh \| None` | `None` = no renderable geometry. |
| `material` | `Material` | Falls back to `Material()`. |
| `transform_matrix` | `np.ndarray` | 4x4 T @ R @ S. |
| `visible` | `bool` | Culled entities set this to `False`. |
| `bounding_box` | `((mn), (mx))` | World-space AABB for the frustum test. |

### `AssetCache`

_class — defined in `slappyengine.render.scene_walker`_

Small `path -> Mesh` LRU with per-entry TTL. Constructor takes
`default_ttl_seconds: float = 600.0`. Methods: `get(path)`, `put(path, mesh)`,
`invalidate(path=None)`, plus `.hits` / `.misses` / `len()`.

### `RenderStats`

_dataclass — defined in `slappyengine.render.scene_walker`_

Per-walk metrics — `entities_walked`, `entities_culled`, `draw_calls`,
`wall_ms`.

## Functions

### `render_scene(scene, renderer, camera, *, lights=None, prefab_library=None, asset_cache=None, stats=None) -> RenderStats`

_defined in `slappyengine.render.scene_walker`_

One-shot Scene -> renderer pipeline. Opens / closes the renderer's frame
if it exposes `begin_frame` / `end_frame`, calls
`walker.walk_with_lights`, returns fresh `RenderStats`.

### `bridge_render_scene(app, scene, renderer, *, camera=None, lights=None) -> RenderStats`

_defined in `slappyengine.render.scene_walker`_

App-level bridge used by HH1's `App.render_frame_from_scene(scene)`.
Reads `app.camera`, `app.lights`, `app.prefab_library`, `app.asset_cache`
when the caller does not override them.

## Usage

```python
import numpy as np
from slappyengine.render.scene_walker import SceneWalker, RenderStats
from slappyengine.render import Camera3D, NullRenderer
from slappyengine.scenes.scene import Scene

scene = Scene()
scene.entities = [
    {"id": "cube_a", "position": (0.0, 0.0, 0.0), "params": {}},
    {"id": "cube_b", "position": (2.5, 0.0, 0.0), "params": {"scale": 0.5}},
]

camera = Camera3D()
renderer = NullRenderer()

walker = SceneWalker(scene)
stats = walker.walk(renderer, camera)
assert isinstance(stats, RenderStats)
```

## Skip the wrapper

`slappyengine.render.scene_walker` is Python-only glue. There is **no**
Rust equivalent under `slappyengine._core`; every function above (TRS
composition, plane extraction, AABB transform, per-entity dispatch)
lives in this file and calls into numpy for the array math. Bypassing
the wrapper for the walker itself would mean re-implementing the JJ5
contract in the caller — you almost certainly want to keep this file
and swap out the HH4 renderer instead.

The KK1 BVH ([`render_bvh_3d.md`](render_bvh_3d.md)) is the correct
"skip the linear walk" answer: build a `BVH3D` once, then query it every
frame instead of letting the walker iterate every entity.

## See also

- [`render_bvh_3d.md`](render_bvh_3d.md) — KK1 SAH BVH that accelerates
  the walker's linear frustum loop.
- [`render_shadows.md`](render_shadows.md) — JJ7 CSM math sharing the
  same camera conventions.
- [`asset_import.md`](asset_import.md) — importers the walker routes
  `params["mesh_path"]` through.
- [`gpu.md`](gpu.md) — HH4 renderer target of `submit_mesh` calls.
