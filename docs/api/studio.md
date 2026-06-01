<!-- handauthored: do not regenerate -->
# slappyengine.studio — API Reference

> Hand-curated reference for the studio subpackage.
> The studio module is high-level scenario sugar: it wraps world setup,
> rendering and GIF capture so a working demo fits in ~15 lines of code
> instead of ~50. Every helper is additive — you can still build worlds
> directly (`SoftBodyWorld()` / `FluidWorld()` / `dynamics.World()`),
> run your own loop, and bring your own renderer.

```python
from slappyengine.studio import (
    Stage,
    record,
    softbody_stage,
    fluid_stage,
    fluid_with_softbody_stage,
    humanoid_stage,
    dynamics_stage,
    terrain_overlay,
    output_path,
    kick, anchor, centroid, translate,
)
```

## Stage

The central handle: a `dataclass` bundle of world(s) + renderer + view
+ timestep, returned by every `*_stage` factory.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `world` | `Any` | `None` | Primary world used for stepping. |
| `softbody` | `Any` | `None` | Optional softbody world. |
| `fluid` | `Any` | `None` | Optional fluid world. |
| `dynamics` | `Any` | `None` | Optional `slappyengine.dynamics.World`. |
| `renderer` | `Any` | `None` | `FluidRenderer` / `SoftBodyRenderer`, or `None` when a `render_fn` is supplied. |
| `view_box` | `(wx0, wy0, wx1, wy1)` | `(-2, -1, 2, 5)` | Camera rectangle in world coords. |
| `dt` | `float` | `1/60` | Per-frame timestep consumed by `record`. |
| `surface_y` | `float \| None` | `None` | Top-of-pool y after pre-settling, when the helper settled a fluid pool. |
| `body_metas` | `dict[str, Any]` | `{}` | Handles for bodies the helper auto-spawned, plus default-renderer overrides. |
| `render_fn` | `Callable[[Stage], PIL.Image] \| None` | `None` | Optional pure-PIL renderer used by `record` when no GPU renderer is present (set by `dynamics_stage`). |

`Stage.record(out_path, frames=120, *, fps=30, render_fn=None, step_world=True, pre_step=None, post_step=None, overlay=None)`
is the method form of the module-level `record`; passing `render_fn`
overrides the one bound on the stage just for this call.

## Stage factories

### `softbody_stage(*, view_box=(-2,-1,2,5), width=480, height=320, floor_y=None, gravity=None, contact_enabled=None, floor_friction=None, **renderer_overrides) -> Stage`

Builds a softbody-only stage with a `SoftBodyRenderer`. Sets the world's
config keys (`floor_y`, `gravity`, `contact.enabled`, `floor_friction`)
when each kwarg is supplied; pulls `default_dt` from the world config.

### `fluid_stage(*, view_box=(-2,2,2,6), width=480, height=320, floor_y=None, walls=None, pool=None, settle_steps=0, **renderer_overrides) -> Stage`

Builds a fluid-only stage with a `FluidRenderer`. `walls` is a
`(min, max)` x-extents pair. `pool` is forwarded to
`FluidWorld.add_block_of_particles`, e.g.
`pool=dict(material="water", nx=28, ny=22, spacing=0.06, origin=(-0.84, 2.7), jitter=0.04)`.
When `settle_steps > 0`, the fluid is pre-stepped that many frames and
`stage.surface_y` is set to the resulting top-of-pool y.

### `humanoid_stage(*, view_box=(-1.5,0,1.5,4), width=360, height=480, gravity=(0,0), contact_enabled=False, floor_y_far_below=100.0, debug_show_beams=True, debug_show_nodes=True, **renderer_overrides) -> Stage`

A softbody stage tuned for humanoid / kinematic IK demos: no gravity,
contact off, floor effectively disabled. Wireframe (beams + nodes) is
ON by default because humanoid skeletons have no texture topology
registered — they would render as an empty background otherwise. After
the stage is built, call `make_humanoid(stage.world, …)` to add the
skeleton, then optionally `place_feet_on_terrain` or `wrap_in_flesh`.

### `fluid_with_softbody_stage(*, view_box=(-2,2,2,6), width=480, height=320, floor_y=6.0, walls=(-1.8,1.8), pool=None, settle_steps=140, fluid_contact=False, sb_contact=False, **renderer_overrides) -> Stage`

Composite scene: a fluid world *and* a softbody world, drawn by a
shared `FluidRenderer` that paints both. Defaults match the buoyancy
demo — deep pool, walls in, fluid-softbody coupling disabled (use
`apply_fluid_buoyancy` from `slappyengine.fluid` for explicit
Archimedes). When `pool is None`, a sensible water block sized for the
default `view_box` is added. `stage.surface_y` is set from the settled
pool top.

### `dynamics_stage(world=None, *, gravity=(0,-9.81), solver_iterations=None, view_box=(-3,-3,3,3), width=480, height=320, floor_y=None, dt=None, render_fn=None, **render_overrides) -> Stage`

Builds a stage around a `slappyengine.dynamics.World`. The dynamics
world is the substrate for ropes, ragdolls, springs, motors and IK
chains. Unlike softbody / fluid, dynamics has **no shipped GPU
rasteriser** — this helper wires in a pure-PIL fallback
(`_default_dynamics_render`) that draws every joint as a line and every
node as a disk, with pinned nodes (`inv_mass == 0`) drawn in a separate
colour and an optional floor line at `floor_y`. A one-line
`stage.record(...)` therefore produces a meaningful GIF.

Pass an existing `world` to drape the stage around it; pass `None` and
a fresh `World(gravity=…)` is constructed (with `solver_iterations`
applied when set). `render_overrides` accepts `bg`, `line_color`,
`node_color`, `pinned_color`, `floor_color`, `line_width`, and
`node_radius` — these are stored on `stage.body_metas` and consumed by
the default renderer. Override the renderer entirely via `render_fn`.

This entry point landed alongside the `render_fn` slot on `Stage` in
Sprint 7G (`a4cbc60`).

## `record(stage, frames=180, output=None, *, fps=30, step_world=True, pre_step=None, post_step=None, overlay=None) -> Path`

Runs the sim loop `frames` times, renders each frame, and saves the
result as a GIF (or whatever extension `output` carries; the underlying
`save_frames` handles encoding). Returns the resolved output path.

Step order per frame:

1. `pre_step(stage)` — apply forces, drive IK, retarget.
2. World step (when `step_world=True`): softbody → fluid → dynamics, in
   that order, for whichever worlds the stage carries.
3. `post_step(stage, frame_idx)` — sample data, mutate the scene.
4. Render — `stage.render_fn(stage)` takes precedence; otherwise the
   fluid renderer (if `stage.fluid is not None`) or the softbody
   renderer is used.
5. `overlay(img, view_box)` — last-mile compositing (terrain line, HUD,
   labels).

Set `step_world=False` for static / pose-only demos where the user
drives every frame manually via `pre_step` and `post_step` (e.g. the
IK-terrain demo that re-IKs the humanoid each frame, or the standing-
pose demo that captures the same frame N times).

## BodyMeta helpers — `kick` / `anchor` / `centroid` / `translate`

The studio API ships four module-level helpers that operate on a
`(node_start, node_end)` slice of a softbody world's nodes. These match
the `BodyMeta` convenience methods the original studio API attached to
body handles — they read the slice straight off `world.nodes`, so they
work on whatever is at that range whether the body was lattice-built,
flesh-wrapped, or hand-assembled.

| Helper | Effect |
|--------|--------|
| `kick(world, node_slice, vx=0, vy=0, *, twist=0)` | Sets a uniform velocity on the slice; `twist` adds a per-node x-velocity proportional to `(x - centroid_x)` so the body picks up spin around its vertical axis. |
| `anchor(world, node_slice)` | Pins every node in the slice (`fixed=True`, `inv_mass=0`). Idempotent. |
| `centroid(world, node_slice) -> (cx, cy)` | Returns the geometric centre of the slice. |
| `translate(world, node_slice, dx, dy)` | Shifts both `pos` and `prev_pos` by `(dx, dy)` so the XPBD integrator doesn't see a fictitious velocity from the displacement. |

## Overlays + paths

- `terrain_overlay(terrain_fn, *, color=(80,100,60), width_px=3, samples=240) -> Overlay`
  — builds an overlay callable that paints a 1D terrain line over each
  frame. `terrain_fn(x) -> y` follows the engine convention
  (positive `y` = down).
- `output_path(name, demo_file=None, *, subdir=None, ext="gif") -> Path`
  — resolves a standard `<root>/output/<subdir>/<name>.<ext>` path. When
  `demo_file=__file__`, anchors at the demo's parent directory; else
  uses CWD. Creates parent dirs.

## Choosing a stage

| Use case | Stage | Why |
|----------|-------|-----|
| Solid block falls, bounces, deforms | `softbody_stage` | Single XPBD softbody world + textured/wireframe softbody renderer. Cheapest stage. |
| Pool of water sloshing, sand piling | `fluid_stage` | Single PBF fluid world + marching-squares surface renderer. `pool=` + `settle_steps=` pre-build a pool. |
| Block floats / sinks / breaks waves on a pool | `fluid_with_softbody_stage` | Both worlds, shared `FluidRenderer` that draws both. Pair with `apply_fluid_buoyancy` for Archimedes coupling. |
| Humanoid pose, IK, ragdoll-on-terrain demo | `humanoid_stage` | Softbody world with gravity/contact disabled and wireframe ON by default so a skeleton is actually visible. |
| Rope swinging from a pin, motor-driven wheel | `dynamics_stage` | `dynamics.World` substrate (ropes, ragdolls, springs, motors, IK) + built-in pure-PIL line/disk renderer; no GPU needed. |
| Custom multi-system scene | any of the above | Override `stage.renderer` or pass `render_fn=` to bring your own per-frame PIL image. |

Rule of thumb: pick the simplest stage that owns the **physics world**
you need, then mix in everything else via `pre_step` and `post_step`.
Render hand-off (`render_fn`) is reserved for scenes that the shipped
softbody / fluid renderers can't draw — primarily the dynamics
substrate, which has no GPU rasteriser of its own.

## Inner module surface

- `slappyengine.studio.Stage` — bundle dataclass.
- `slappyengine.studio.record` — frame loop + GIF writer.
- `slappyengine.studio.softbody_stage` / `fluid_stage` /
  `humanoid_stage` / `fluid_with_softbody_stage` / `dynamics_stage` —
  factories.
- `slappyengine.studio.terrain_overlay` / `output_path` — helpers.
- `slappyengine.studio.kick` / `anchor` / `centroid` / `translate` —
  node-slice ops.
