<!-- handauthored: do not regenerate -->
# slappyengine.animation — API Reference

> Hand-written reference for the animation subpackage.
> Covers state-machine graphs, procedural rigging with control points
> and IK, and the video-frame import path. For per-pixel softbody and
> fluid animation see `slappyengine.softbody` / `slappyengine.fluid`;
> for tween / easing primitives used by the editor and HUD see
> `slappyengine.tools`.

```python
from slappyengine.animation import (
    AnimationGraph, AnimState, AnimTransition, AnimUpdate,
    ProceduralRig, ControlPoint,
)
```

## Overview

All names are lazy-loaded via `__getattr__` — importing
`slappyengine.animation` is cheap. Video-frame extraction lives in
`slappyengine.animation.video_import` and is **not** in `__all__` (it
pulls a `[video]` extra that most users will not install).

## AnimationGraph — state-machine playback

A clip-driven finite state machine. Each `AnimState` owns a list of
`clip_indices` into the asset's frame strip, plus a per-state `fps`
and a `loop` flag. Transitions are pure-Python callables — the graph
re-evaluates them every `update(dt)` and switches state on the first
match.

### AnimState

```python
AnimState(
    name: str,                       # non-empty
    clip_indices: list[int] = [],    # non-negative ints
    loop: bool = True,
    fps: float = 24.0,               # finite > 0
)
```

Validates in `__post_init__`:

- `name` must be a non-empty `str` (`ValueError` otherwise).
- `clip_indices` must be a `list` of non-negative `int`s (`bool` is
  rejected as a stand-in for `int`; `ValueError` / `TypeError`).
- `fps` must be a finite numeric `> 0`.

### AnimTransition

```python
AnimTransition(
    from_state: str,
    to_state: str,
    condition: Callable[[], bool] = lambda: False,
)
```

`condition` is the trigger predicate — the graph polls it once per
`update(dt)` against the current state. Same non-empty-string
validation on the state names; `condition` must be callable.

### AnimUpdate

The dataclass returned by `AnimationGraph.update(dt)`:

| Field | Type | Meaning |
|-------|------|---------|
| `state_name` | `str` | Current state after evaluating transitions. |
| `frame_index` | `int` | Resolved index into the asset's frame strip (i.e. `state.clip_indices[i]`, or the raw frame counter when `clip_indices` is empty). |
| `blend_fraction` | `float` | `[0.0, 1.0)` sub-frame phase — useful for cross-frame interpolation in the renderer. |

### AnimationGraph

```python
g = AnimationGraph()
g.add_state(AnimState("idle", clip_indices=[0, 1, 2, 3], fps=12))
g.add_state(AnimState("walk", clip_indices=[4, 5, 6, 7], fps=24))
g.add_transition(AnimTransition("idle", "walk", lambda: input.moving))
g.add_transition(AnimTransition("walk", "idle", lambda: not input.moving))
g.set_initial("idle")

upd = g.update(dt)
if upd:
    sprite.frame = upd.frame_index
```

Methods:

- `add_state(state)` — register a state by name; later additions with
  the same name overwrite.
- `add_transition(t)` — append a transition. Order matters: the first
  matching transition wins per tick.
- `set_initial(name)` — must be called before `update`; raises
  `ValueError` for unknown names.
- `update(dt) -> AnimUpdate | None` — advance the playhead by `dt`
  seconds. Returns `None` when no initial state is set; never raises
  on the empty-graph or zero-`dt` case (validates `dt` is finite
  `≥ 0`).
- `tick(dt) -> str | None` — convenience wrapper that returns just
  the new `state_name`. Used by examples and tests where the frame
  index is not interesting.
- `current_state` (property) — `AnimState | None`.

Per-frame stepping uses an accumulator on `_frame_timer`. When `dt *
fps` rolls past `1.0`, the graph advances `_current_frame` by the
integer part; the fractional remainder lands on `AnimUpdate.blend_fraction`
for the next render. `loop=True` wraps via modulo; `loop=False` clamps
at the final clip index.

## ProceduralRig + ControlPoint — dot-rigging + IK

A flat dictionary of named control points, each tagged with a parent
name to form a tree. The rig solves a per-tip IK pass against
user-supplied target positions and writes the new control-point
positions back.

### ControlPoint

```python
ControlPoint(
    name: str,
    uv: tuple[float, float],         # 0–1 texture-space position
    parent: str | None = None,       # parent's name
    constraint: str = "free",        # "free" | "hinge" | "slider"
    min_angle: float = -180.0,
    max_angle: float = 180.0,
)
```

`uv` is in normalised texture coordinates; angle limits are reserved
for the hinge / slider constraints (the current Rust solver honours
`free` only).

### ProceduralRig

```python
rig = ProceduralRig()
rig.add_point(ControlPoint("hip",   uv=(0.50, 0.55)))
rig.add_point(ControlPoint("knee",  uv=(0.50, 0.70), parent="hip"))
rig.add_point(ControlPoint("ankle", uv=(0.50, 0.90), parent="knee"))

pose = rig.solve_ik({"ankle": (0.55, 0.95)})
rig.apply_to(asset.cubes, pose)
```

Methods:

- `add_point(cp)` — insert / replace by name.
- `remove_point(name)` — silent if absent.
- `get_chain(root_name, tip_name) -> list[ControlPoint]` — walks
  `parent` links from tip to root, returning the chain root-first.
  Returns whatever chunk it found if the root is never hit (no
  exception).
- `solve_ik(target_positions: dict[name, (u, v)]) -> dict[name, (u, v)]`
  — for each tip in `target_positions`, find the chain root via
  `_find_root` (cycle-safe), gather chain positions, and delegate to
  `slappyengine._core.solve_ik` (Rust). When `_core` is unavailable
  the rig falls back to `_simple_stretch`, which just snaps the tip
  to the target — useful as a baseline for unit tests but visually
  poor.
- `apply_to(cube_array, pose)` — writes the solved positions back
  into the rig's own `ControlPoint.uv` fields. The `cube_array`
  argument is reserved for the upcoming asset-mesh deformation path.
- `points` (property) — list of every registered control point.

The Rust solver receives a flat `[(x, y), ...]` chain plus the target
`(x, y)` and per-bone lengths from `_core.compute_bone_lengths`.
Returns the new positions for every joint in the chain.

## Video frame import

```python
from slappyengine.animation.video_import import extract_frames

frames = extract_frames("animation.mp4", max_frames=256)
# frames: list[np.ndarray]  — each (H, W, 4) uint8 RGBA
```

`extract_frames(video_path, max_frames=256)` opens the file with
PyAV, decodes the first video stream, and returns up to `max_frames`
RGBA frames. Requires the `[video]` extra:

```
pip install SlapPyEngine[video]
```

Without PyAV installed the function raises `ImportError` with the
install hint baked in. This path is used by the editor's
"import animation" action and by the asset-pipeline tooling — runtime
animation playback does not need it.

## Inner modules

- `slappyengine.animation.graph` — `AnimationGraph`, `AnimState`,
  `AnimTransition`, `AnimUpdate`.
- `slappyengine.animation.procedural` — `ProceduralRig`, `ControlPoint`.
- `slappyengine.animation.video_import` — `extract_frames` (opt-in
  extra; not in `__all__`).

## See also

- [`studio.md`](studio.md) — `humanoid_stage` consumes the rig + IK
  surface for demo capture.
- [`ext.md`](ext.md) — `slappyengine.ext.animation` re-exports the
  same surface for back-compat imports.
