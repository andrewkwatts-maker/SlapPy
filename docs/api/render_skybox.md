<!-- handauthored: do not regenerate -->
# slappyengine.render.skybox — API Reference

> Hand-written reference for the KK4 cubemap skybox surface.
> Draws a full-screen cube whose vertices are pushed to the far plane
> (`z = w` after projection) and samples a cubemap keyed by the
> fragment's world-space direction. Sibling references:
> [`render_scene_walker.md`](render_scene_walker.md) is the traversal
> layer that dispatches the skybox alongside opaque geometry;
> [`asset_import.md`](asset_import.md) supplies the six-face cubemap
> loader that feeds :class:`CubemapData`.

## Overview

`slappyengine.render.skybox` is the Nova3D parity Sprint 11 landing
(task KK4). It packages:

* :class:`CubeFace` — the six-face enum in standard GPU order
  (POSX / NEGX / POSY / NEGY / POSZ / NEGZ).
* :class:`CubemapData` — a CPU-side cubemap dataclass carrying six
  square HxWx4 `uint8` arrays, one per face, with `__post_init__`
  validation.
* :class:`Skybox` — the bindable pass. Owns the unit-cube geometry,
  the cubemap, and the "view-matrix with translation stripped" helper
  so the sky stays centred on the camera.
* :data:`SKYBOX_WGSL` — vertex + fragment source.
* :func:`sample_direction_from_cubemap` — CPU-side nearest-texel
  sampler used by tests and numpy fallback paths.
* :func:`procedural_gradient_sky` — three-stop (top / horizon / ground)
  gradient cubemap builder — no texture files required.

Cube-face sampling follows the standard Direct3D / glTF convention;
the module docstring holds the full axis / UV table.

## Public surface

```python
from slappyengine.render.skybox import (
    CubeFace, CubemapData, Skybox,
    procedural_gradient_sky,
    sample_direction_from_cubemap,
    ALL_FACES,
    SKYBOX_WGSL,
)
```

## Classes

### `CubeFace`

_IntEnum — defined in `slappyengine.render.skybox`_

Six values in the standard GPU order:

| Value | Face | Axis |
|-------|------|------|
| 0 | `POSX` | +X |
| 1 | `NEGX` | -X |
| 2 | `POSY` | +Y |
| 3 | `NEGY` | -Y |
| 4 | `POSZ` | +Z |
| 5 | `NEGZ` | -Z |

### `CubemapData`

_dataclass — defined in `slappyengine.render.skybox`_

```python
CubemapData(
    faces: dict[CubeFace, np.ndarray] | None = None,  # (H, W, 4) uint8
    resolution: int = 1,
    format: str = "rgba8",
)
```

`__post_init__` fills any missing face with a black `(res, res, 4)`
placeholder and validates that every provided face is square, HxWx4,
matches `resolution`, and uses `uint8`.

Methods:

- `face(face) -> np.ndarray` — return the `(res, res, 4)` array for
  the requested :class:`CubeFace` (accepts an int too).
- `is_power_of_two` (property) — mip-friendliness hint; not enforced.

Raises `ValueError` when `resolution <= 0`, any face is non-square /
wrong shape / wrong `resolution`, or `format != "rgba8"`.

### `Skybox`

_dataclass — defined in `slappyengine.render.skybox`_

```python
Skybox(
    cubemap: CubemapData,
    camera: Camera3D | None = None,
    depth_write: bool = False,
    depth_test: str = "less_equal",
)
```

Owns the 36-vertex unit-cube geometry and the cubemap. Exposes:

- `vertices -> np.ndarray[36, 3]`
- `triangle_count -> int` (always 12)
- `view_matrix_no_translation(camera=None) -> np.ndarray[4, 4]` —
  returns the camera's `view_matrix()` with translation stripped so
  the sky moves with the camera and only rotation samples the cubemap.
- `render(renderer, camera=None) -> None` — submits a
  `DrawCall("skybox", ...)` on the null path, or delegates to
  `renderer.submit_skybox` / `renderer.draw_skybox` when present.
  Raises `TypeError` when `renderer` is `None`. Warns once per
  renderer instance when no known hook is available.

## Functions

### `sample_direction_from_cubemap(direction, cubemap) -> tuple[r, g, b, a]`

_defined in `slappyengine.render.skybox`_

CPU-side nearest-texel sample of `cubemap` along `direction`. Returns
RGBA components in `[0, 1]`. Picks the face whose axis has the largest
absolute component in the incoming direction, then divides the other
two components by that axis to get UV in `[0, 1]`.

### `procedural_gradient_sky(top_color, horizon_color, ground_color, resolution=256) -> CubemapData`

_defined in `slappyengine.render.skybox`_

Build a three-stop gradient cubemap. The gradient is computed per
fragment as a function of the world-space Y component:
`y=+1 -> top_color`, `y=0 -> horizon_color`, `y=-1 -> ground_color`.
All six faces are generated consistently so a subsequent
:func:`sample_direction_from_cubemap` call reads back the expected
colour. Raises `ValueError` when `resolution <= 0`.

## Constants

### `SKYBOX_WGSL`

_str — defined in `slappyengine.render.skybox`_

Vertex + fragment WGSL that pushes the cube to the far plane
(`c.z = c.w`) and samples the cubemap with the normalised world-space
direction of the fragment.

### `ALL_FACES`

_tuple[CubeFace, ...] — defined in `slappyengine.render.skybox`_

Immutable tuple of the six faces in enum order — useful for iteration.

## Usage

```python
from slappyengine.render.skybox import Skybox, procedural_gradient_sky
from slappyengine.render.null_renderer import NullRenderer

cubemap = procedural_gradient_sky(
    top_color=(0.35, 0.55, 0.90),
    horizon_color=(0.85, 0.90, 0.98),
    ground_color=(0.18, 0.15, 0.12),
    resolution=128,
)
sky = Skybox(cubemap=cubemap)

renderer = NullRenderer()
sky.render(renderer)

call = renderer.draw_log[-1]
assert call.kind == "skybox"
assert call.payload["triangle_count"] == 12
assert call.payload["resolution"] == 128
```

## Skip the wrapper

`slappyengine.render.skybox` is Python-only. Grep of
`slappyengine._core_facade.RUST_MODULE_MAP` shows **no** `skybox`
entry — the gradient builder is a one-shot numpy vectorised pass
(runs in µs for 256²) and the CPU sampler exists only for tests.

For direct wgpu binding without the wrapper, take :data:`SKYBOX_WGSL`
as-is, upload the six `CubemapData.face(f)` arrays into a
`texture_cube<f32>` at group 1 binding 0, and pass the
`Skybox.view_matrix_no_translation(camera)` plus projection matrix
into the group-0 UBO.

## See also

- [`render_scene_walker.md`](render_scene_walker.md) — traversal
  layer that dispatches the skybox alongside opaque geometry.
- [`asset_import.md`](asset_import.md) — six-face cubemap loader
  that emits a :class:`CubemapData`.
- [`render_bvh_3d.md`](render_bvh_3d.md) — spatial acceleration for
  the rest of the scene the skybox draws behind.
