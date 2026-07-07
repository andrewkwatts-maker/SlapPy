<!-- handauthored: do not regenerate -->
# slappyengine.physics3_bridge — API Reference

> Hand-written reference for the LL7 3D physics bridge — plus the NN4
> raycast / AABB-sweep surface and the OO2 BVH-accelerated raycast
> path. Backend-agnostic dynamics wrapper: prefers the WIP
> :mod:`slappyengine.physics` tree when importable, else falls back on
> a built-in semi-implicit Euler + SAP shim. Sibling references:
> [`render_bvh_3d.md`](render_bvh_3d.md) is the KK1 BVH surface the
> OO2 fast path shares; [`dynamics.md`](dynamics.md) is the 2D dynamics
> surface this API deliberately mirrors so game code can swap
> tuple-lengths and port up.

## Overview

`slappyengine.physics3_bridge` is the Nova3D parity Sprint 18 landing
(task LL7) plus two follow-ups: NN4 added first-hit
:meth:`~World3D.raycast` + AABB :meth:`~World3D.sweep_aabb`, and OO2
plugged the KK1 :class:`~slappyengine.render.bvh_3d.BVH3D` into raycast
so scenes above eight bodies use O(log N) tree traversal.

Games and demos that want *some* 3D dynamics should not hard-depend on
the untracked WIP `slappyengine.physics` tree. This module gives them a
stable Python-level surface with two implementations:

* `backend="physics"` — delegates to :mod:`slappyengine.physics` when
  importable. Bodies keep their kinematic attributes on the shim side;
  the real physics tree handles contacts and constraints.
* `backend="fallback"` — a minimal built-in world doing semi-implicit
  Euler, sweep-and-prune along X, sphere-sphere collision response,
  and a naive ray-AABB test. A *prototyping* solver, not a real engine
  — it exists so downstream code can be written, tested, and demoed
  even when the WIP tree is stripped from a build.

The soft-import contract mirrors what
:mod:`slappyengine.render.bvh_3d` does for JJ5's frustum: try the
richer thing, fall back on a duck-typed local implementation, never
raise at import time.

## Public surface

```python
from slappyengine.physics3_bridge import (
    Body3D, World3D, PhysicsBackendError,
    RaycastHit, SweepHit,
    resolve_physics3_backend,
    AABB3D,     # re-export of render.bvh_3d.AABB3D or None
)
```

## Classes

### `Body3D`

_dataclass — defined in `slappyengine.physics3_bridge`_

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `position` | `tuple[float, float, float]` | `(0, 0, 0)` | World-space centroid. |
| `orientation` | `tuple[float, float, float, float]` | `(1, 0, 0, 0)` | Unit quaternion `(w, x, y, z)`. |
| `linear_velocity` | `tuple[float, float, float]` | `(0, 0, 0)` | |
| `angular_velocity` | `tuple[float, float, float]` | `(0, 0, 0)` | Body space. |
| `mass` | `float` | `1.0` | `0.0` = static. |
| `shape_kind` | `str` | `"sphere"` | One of sphere / box / capsule / mesh. |
| `shape_params` | `dict` | `{}` | Free-form. See module docstring for keys. |

Methods:

- `radius() -> float` — best-effort bounding radius used by the
  fallback broadphase.
- `aabb() -> ((min), (max))` — loose axis-aligned bounding box in
  world space (rotation ignored — the fallback uses the bounding
  sphere; over-estimating is fine for a prototype broadphase).
- `aabb3d() -> AABB3D | tuple` — returns the KK1 :class:`AABB3D` when
  the `render.bvh_3d` module is importable, else a `(min, max)` pair.

Raises `ValueError` for negative mass or an unknown `shape_kind`;
`TypeError` when `shape_params` is not a dict.

### `World3D`

_class — defined in `slappyengine.physics3_bridge`_

```python
World3D(
    gravity: tuple[float, float, float] = (0.0, -9.81, 0.0),
    backend: str = "auto",  # "auto" | "physics" | "fallback"
)
```

Backend-agnostic 3D physics world. `backend="auto"` picks the best
available implementation at construction time; `"physics"` forces the
WIP tree (raises :class:`PhysicsBackendError` if missing);
`"fallback"` forces the built-in shim (useful for deterministic tests).

Lifetime + query surface:

- `add_body(body) -> int` — insert and return a stable handle.
- `remove_body(handle) -> None` — raises `KeyError` on unknown handle.
- `get_body(handle) -> Body3D`
- `bodies -> dict[int, Body3D]` (public attribute)
- `step(dt) -> None` — advance the simulation. Raises
  `PhysicsBackendError` when the backend tag is `"none"`.
- `query_aabb(aabb) -> list[int]` — SAP-style overlap query.
- `query_ray(origin, direction) -> list[tuple[int, t_hit]]` — all
  forward-facing hits, sorted by `t`.

NN4 first-hit surface:

- `raycast(origin, direction, max_distance=inf, *, use_bvh=None) -> RaycastHit | None`
  — closest forward-facing hit under `max_distance`. `use_bvh=None`
  auto-picks: BVH when `len(bodies) >= 8` and the BVH module is
  importable, else linear. `True` / `False` force the path.
- `sweep_aabb(aabb, displacement) -> SweepHit | None` — swept-AABB
  first-touch, TOI in `[0, 1]`, axis-aligned contact normal.

Attributes: `gravity`, `backend` (the tag returned by
:func:`resolve_physics3_backend` at construction).

### `RaycastHit`

_frozen dataclass — defined in `slappyengine.physics3_bridge`_

Returned by :meth:`World3D.raycast`. Fields: `body_id: int`,
`distance: float`, `point: (x, y, z)`, `normal: (x, y, z)`.

### `SweepHit`

_frozen dataclass — defined in `slappyengine.physics3_bridge`_

Returned by :meth:`World3D.sweep_aabb`. Fields: `body_id: int`,
`time_of_impact: float ∈ [0, 1]`, `contact_normal: (x, y, z)`.

### `PhysicsBackendError`

_RuntimeError subclass — defined in `slappyengine.physics3_bridge`_

Raised when neither the WIP physics tree nor the numpy-backed
fallback is usable (in practice: numpy is missing from the install).

## Functions

### `resolve_physics3_backend() -> str`

_defined in `slappyengine.physics3_bridge`_

Return the preferred backend tag: `"physics"` when the WIP tree
imports cleanly, else `"fallback"` when numpy is importable, else
`"none"`. Cheap to call every frame but stable for the process
lifetime — cache at import time.

## Constants

### `AABB3D`

_type | None — defined in `slappyengine.physics3_bridge`_

Re-export of :class:`slappyengine.render.bvh_3d.AABB3D` when the
render tree is importable, else `None`. `isinstance(x, AABB3D)`
guards must include a `None` check.

## Usage

```python
from slappyengine.physics3_bridge import (
    Body3D, World3D, resolve_physics3_backend,
)

print("backend:", resolve_physics3_backend())  # "physics" or "fallback"

world = World3D(gravity=(0.0, -9.81, 0.0), backend="fallback")

ground = Body3D(position=(0, -1, 0), mass=0.0, shape_kind="box",
                shape_params={"half_extents": (10, 0.5, 10)})
ball = Body3D(position=(0, 5, 0), mass=1.0, shape_kind="sphere",
              shape_params={"radius": 0.5})
gh = world.add_body(ground)
bh = world.add_body(ball)

for _ in range(30):
    world.step(1.0 / 60.0)

hit = world.raycast(origin=(0, 20, 0), direction=(0, -1, 0))
assert hit is not None
assert hit.body_id in (gh, bh)
assert hit.distance > 0.0
```

## Skip the wrapper

`slappyengine.physics3_bridge` is a Python-side shim. Rust support
lives in the `_core` submodules it *soft-imports through*:

* `slappyengine._core.bvh` — from `src/bvh.rs`, exposes
  `BvhPrimitive` + `Bvh`. Powers the OO2 raycast fast path via
  :mod:`slappyengine.render.bvh_3d`.
* `slappyengine._core.physics` — from `src/physics.rs`, exposes
  `BodyType`, `RigidBody`, `PhysicsWorld`. Consumed by the WIP
  :mod:`slappyengine.physics2` tree, not directly by this shim.

Both entries appear in `slappyengine._core_facade.RUST_MODULE_MAP`.
Games that want raw Rust dynamics without the wrapper should target
`_core.physics` directly (or use `slappyengine.physics2` when it
stabilises); games that want the raycast tree without the world go
through :class:`slappyengine.render.bvh_3d.BVH3D`.

## See also

- [`render_bvh_3d.md`](render_bvh_3d.md) — KK1 SAH BVH the OO2 raycast
  path delegates into.
- [`dynamics.md`](dynamics.md) — 2D dynamics surface this API
  deliberately mirrors.
- [`render_scene_walker.md`](render_scene_walker.md) — pairs with the
  BVH for frustum culling.
