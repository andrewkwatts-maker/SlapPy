<!-- handauthored: do not regenerate -->
# slappyengine.render.bvh_3d — API Reference

> Hand-written reference for the KK1 3D SAH bounding volume hierarchy.
> Accelerates the JJ5 scene walker's linear frustum loop by ~O(log N).
> Sibling references: [`render_scene_walker.md`](render_scene_walker.md)
> is the walker this BVH accelerates; [`render_shadows.md`](render_shadows.md)
> shares the same AABB / frustum conventions.

## Overview

`slappyengine.render.bvh_3d` is a docs-only top-down SAH BVH built
around three primitives: :class:`AABB3D` (immutable axis-aligned box),
:class:`BVHNode` (internal or leaf), and :class:`BVH3D` (the tree +
query surface). It plugs into [`render_scene_walker.py`](../architecture_overview.md)
by wrapping the walker's linear entity loop:

```
bvh = BVH3D([(entity_id, AABB3D(mn, mx)) for entity in scene])
visible_ids = bvh.query_frustum(Frustum.from_camera(camera))
```

Design constraints:

* Pure Python + numpy — no wgpu / Rust dependency. This is glue, not a
  per-frame kernel.
* Read-only integration with JJ5. `Frustum` is soft-imported so this
  module works in stripped builds; queries fall back on the
  duck-typed `intersects_aabb((mn, mx))` protocol.
* Deterministic: given identical `(id, AABB)` input, two builds produce
  identical topology — required for reproducible visual tests.
* Immutable AABB — refits produce new bounds so trees are safe to share
  across threads.

Build strategy: top-down partition; per internal node sort centroids
along each of the 3 axes, evaluate 32 SAH candidate splits
`|L|*area(L) + |R|*area(R)`, recurse. Buckets `<= 4` entities become
leaves. Refit rewrites a leaf's AABB and walks the parent chain
unioning children — O(depth). Rebuild re-runs the build from scratch
after many refits skew the tree.

## Public surface

```python
from slappyengine.render.bvh_3d import AABB3D, BVH3D, BVHNode
```

## Classes

### `AABB3D`

_dataclass — defined in `slappyengine.render.bvh_3d`_

```python
AABB3D(
    min: tuple[float, float, float],
    max: tuple[float, float, float],
)
```

Immutable (`frozen=True`). Constructor asserts `min <= max` per axis;
degenerate boxes where `min == max` represent a point. Exposes
`.surface_area`, `.union(other)`, `.contains_point(p)`, and
`.intersects(other)` helpers.

### `BVHNode`

_dataclass — defined in `slappyengine.render.bvh_3d`_

Internal / leaf node — carries `aabb`, `left`, `right`, `entity_ids`
(empty for internal nodes), and `depth`. Callers rarely construct
`BVHNode` directly; `BVH3D` builds them internally.

### `BVH3D`

_class — defined in `slappyengine.render.bvh_3d`_

```python
BVH3D(entries: list[tuple[str, AABB3D]])
```

Methods:

- `query_frustum(frustum) -> list[str]`
  — returns entity ids whose AABB intersects the frustum.
  Accepts anything with `intersects_aabb((mn, mx))`.
- `query_aabb(aabb: AABB3D) -> list[str]`
  — returns entity ids whose AABB intersects `aabb`. Useful for
  broadphase collision and picking.
- `query_ray(origin, direction) -> list[str]`
  — slab-test raycast (NN4 raycast). Returns ids sorted by hit
  distance.
- `update_entity(entity_id, aabb) -> None`
  — rewrite one leaf's AABB, propagate parent bounds. O(depth).
- `rebuild() -> None`
  — re-run the SAH build from scratch.

Raises:

- `TypeError` — on non-list / non-tuple `entries`.
- `ValueError` — on duplicate entity ids or on empty inputs.

## Usage

```python
from slappyengine.render.bvh_3d import AABB3D, BVH3D
from slappyengine.render.scene_walker import Frustum
from slappyengine.render import Camera3D

entries = [
    ("cube_a", AABB3D((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5))),
    ("cube_b", AABB3D((2.0, -0.5, -0.5), (3.0, 0.5, 0.5))),
    ("cube_c", AABB3D((10.0, 10.0, 10.0), (11.0, 11.0, 11.0))),
]
bvh = BVH3D(entries)

camera = Camera3D()
frustum = Frustum.from_camera(camera)
visible = bvh.query_frustum(frustum)
assert isinstance(visible, list)
```

## Skip the wrapper

`slappyengine.render.bvh_3d` is Python-only. There is **no** Rust
equivalent under `slappyengine._core` today. The FF4 rust-migration
audit ([`../rust_migration_audit_2026_07_05.md`](../rust_migration_audit_2026_07_05.md))
identifies BVH build/query as a plausible future kernel candidate when
scene sizes push into the thousands of entities; today all build and
query work happens in numpy.

If you have a compute-shader accelerated broadphase you prefer, wrap it
in a duck-typed object exposing `query_frustum(frustum)` and drop it
in — JJ5 does not import this module explicitly, it accepts anything
returning an id list.

## See also

- [`render_scene_walker.md`](render_scene_walker.md) — walker whose
  linear frustum loop this BVH accelerates.
- [`render_shadows.md`](render_shadows.md) — sibling render subpackage
  reference sharing the same AABB / frustum conventions.
- [`../rust_migration_audit_2026_07_05.md`](../rust_migration_audit_2026_07_05.md)
  — audit of the top Rust-port hot-path candidates.
