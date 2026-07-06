<!-- handauthored: do not regenerate -->
# slappyengine.animation.skeleton_runtime — API Reference

> Hand-written reference for the JJ4 skinned skeleton runtime.
> Adds bone-hierarchy pose + linear-blend skinning + clip playback on
> top of the AnimationGraph state-machine layer already documented in
> [`animation.md`](animation.md). Sibling references:
> [`asset_import.md`](asset_import.md) is where :class:`SkinnedMeshData`
> and :class:`Skeleton` come from; [`animation.md`](animation.md) covers
> the AnimationGraph / ProceduralRig / video-import surface.

## Overview

`slappyengine.animation.skeleton_runtime` (plus its two siblings
`clip.py` and `skinner.py`) is the JJ4 skinned-mesh runtime. It builds
on the following contract:

* :class:`Skeleton` + :class:`SkeletonNode` describe the bind pose,
  parent hierarchy, and inverse-bind matrices — usually loaded from a
  glTF file via [`asset_import.import_gltf`](asset_import.md).
* :class:`PoseState` carries per-joint TRS overrides ("what does the
  animator say each bone should be right now?").
* :class:`PosedSkeleton` composes local TRS -> world matrices ->
  skinning palette (`world @ inverse_bind`).
* :class:`Skinner` applies linear blend skinning (LBS) to a
  :class:`SkinnedMeshData` given a palette.
* :class:`AnimationClip` sampling + :class:`Skinner` glue lives in
  :class:`Animator`, which is the ergonomic entry point most callers
  should reach for.

Every symbol is re-exported at :mod:`slappyengine.animation` top level
so users import from there.

## Public surface

```python
from slappyengine.animation import (
    Skeleton, SkeletonNode, SkinnedMeshData,
    PoseState, PosedSkeleton,
    AnimationChannel, AnimationClip,
    Skinner, Animator,
    quat_slerp, compose_trs,
)
```

## Classes

### `SkeletonNode`

_dataclass — defined in `slappyengine.animation.skeleton_runtime`_

One bone. Carries `name: str`, `parent_index: int` (-1 for root),
`translation`, `rotation` (quaternion `x, y, z, w`), `scale`, and a
cached `local_matrix` computed by :func:`compose_trs`.

### `Skeleton`

_dataclass — defined in `slappyengine.animation.skeleton_runtime`_

Ordered list of :class:`SkeletonNode` plus per-joint
`inverse_bind_matrices: np.ndarray[N, 4, 4]`. Joints must be listed in
topological order (parents before children).

Exposes:

- `joint_count -> int`
- `root_indices -> list[int]`
- `find(name) -> int` — index or `-1`.

### `SkinnedMeshData`

_dataclass — defined in `slappyengine.animation.skeleton_runtime`_

Vertex-side skinning payload.

| Field | Type | Notes |
|-------|------|-------|
| `positions` | `np.ndarray[V, 3] float32` | Bind-pose positions. |
| `normals` | `np.ndarray[V, 3] float32 \| None` | Optional. |
| `joints` | `np.ndarray[V, 4] int32` | Per-vertex joint indices. |
| `weights` | `np.ndarray[V, 4] float32` | Per-vertex weights (sum ~ 1.0). |
| `indices` | `np.ndarray[T, 3] uint32` | Triangle list. |

### `PoseState`

_dataclass — defined in `slappyengine.animation.skeleton_runtime`_

Per-joint TRS overrides applied on top of the bind pose. Constructed
via `PoseState.from_skeleton(skeleton)` — returns a zero-delta pose that
`PosedSkeleton` treats as identity.

### `PosedSkeleton`

_class — defined in `slappyengine.animation.skeleton_runtime`_

```python
PosedSkeleton(skeleton: Skeleton)
```

Methods:

- `reset_to_bind_pose() -> None`
- `apply_pose(pose_state: PoseState) -> None`
- `compute_world_matrices() -> np.ndarray[N, 4, 4]`
- `compute_skinning_palette(inverse_bind_matrices=None) -> np.ndarray[N, 4, 4]`
  — `world @ inverse_bind`. Uses the skeleton's own IBMs when the
  argument is omitted.

### `AnimationChannel`

_dataclass — defined in `slappyengine.animation.clip`_

One (joint, path) sampling channel — `joint_index`, `path` in
`{"translation", "rotation", "scale"}`, `times: np.ndarray`,
`values: np.ndarray`, `interpolation` in
`{"STEP", "LINEAR", "CUBICSPLINE"}`.

### `AnimationClip`

_dataclass — defined in `slappyengine.animation.clip`_

Named list of channels + duration.

- `sample(time: float, pose: PoseState) -> None`
  — writes the sampled TRS deltas into `pose` in-place. Handles LERP for
  T/S and SLERP for R (rotation). CUBICSPLINE channels use the standard
  Hermite tangent pair per glTF.

### `Skinner`

_class — defined in `slappyengine.animation.skinner`_

CPU linear blend skinner. Consumes a :class:`SkinnedMeshData` on
construction. Call `skin(palette=palette) -> np.ndarray[V, 3]` per frame.

Raises:

- `TypeError` — when the mesh has no `positions`.
- `ValueError` — when `joints.shape != weights.shape`, or per-vertex
  influence count is not 4.

### `Animator`

_class — defined in `slappyengine.animation.skinner`_

```python
Animator(
    skinned_mesh: SkinnedMeshData,
    skeleton: Skeleton,
    clips: dict[str, AnimationClip] | None = None,
)
```

Ergonomic wrapper. Methods:

- `add_clip(clip)`, `play(name, loop=True)`, `pause()`, `stop()`.
- `advance(dt) -> np.ndarray[V, 3]` — sample current clip, apply pose,
  compute palette, skin, return new positions.

Raises `KeyError` on unknown clip name, `ValueError` on empty clip name.

## Functions

### `compose_trs(t, r, s) -> np.ndarray[4, 4]`

_defined in `slappyengine.animation.skeleton_runtime`_

Build a TRS matrix from a translation 3-vector, rotation quaternion
`(x, y, z, w)`, and scale 3-vector.

### `quat_slerp(q0, q1, t) -> np.ndarray[4]`

_defined in `slappyengine.animation.clip`_

Standard shortest-arc spherical linear quaternion interpolation.

## Usage

```python
from slappyengine.asset_import import import_gltf
from slappyengine.animation import Animator

result = import_gltf("assets/hero.gltf")
mesh = result.primary_mesh          # SkinnedMeshData
skeleton = result.primary_skeleton  # Skeleton
clips = {c.name: c for c in result.animations}

animator = Animator(mesh, skeleton, clips=clips)
animator.play("walk", loop=True)

for _ in range(60):
    positions = animator.advance(1.0 / 60.0)
    # positions: (V, 3) float32 — hand to renderer.
```

## Skip the wrapper

`slappyengine.animation.skeleton_runtime` / `.clip` / `.skinner` are
Python-only. There is **no** Rust equivalent under `slappyengine._core`
today; every LBS deform and clip sample runs in numpy. `Skinner.skin`
is the obvious future rust-kernel candidate — the JJ4 landing
deliberately sketched a `palette + bind_positions + joints + weights`
signature that maps cleanly to a Rust `ndarray` view. See
[`../rust_migration_audit_2026_07_05.md`](../rust_migration_audit_2026_07_05.md)
for the current ranking.

For now, callers who want GPU skinning should replace :class:`Skinner`
with their own compute-shader path — :class:`Animator` accepts any
skinner exposing `skin(palette=...) -> np.ndarray`.

## See also

- [`animation.md`](animation.md) — AnimationGraph, ProceduralRig, and
  the video-frame import path.
- [`asset_import.md`](asset_import.md) — JJ3 glTF loader that emits
  :class:`Skeleton` + :class:`SkinnedMeshData`.
- [`render_scene_walker.md`](render_scene_walker.md) — target of the
  animator's skinned positions.
