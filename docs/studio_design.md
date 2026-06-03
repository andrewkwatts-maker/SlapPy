# slappyengine.studio — Design Reference

`slappyengine.studio` is the engine's **demo-authoring sugar layer**.
It exists so a working physics-and-render scene fits in ~15 lines of
Python instead of ~50, without locking callers out of the underlying
worlds and renderers. Every helper is additive — `softbody_stage(...)`
returns a `Stage` bundle the caller can freely mutate, the bundle's
fields stay accessible, and the standard `Stage.record(...)` GIF loop is
overridable at every step.

For the runtime API surface (factory signatures, Stage fields, the
record contract), see the companion [API reference](api/studio.md).

## Design goals

The studio API was born out of a fairly specific frustration. Pre-studio
demos looked like this:

```python
world = SoftBodyWorld()
world.config.set("floor_y", 0.0)
world.config.set("gravity", (0.0, -9.81))
cube = make_lattice_body(world, "stone", width_cells=5, height_cells=5,
                         cell_size=0.10, position=(-0.25, 1.8))
cube.kick(world, vy=8.0, twist=-0.6)

renderer = SoftBodyRenderer(view_box=(-2, -1, 2, 5), width=480, height=320)
dt = world.config.default_dt
frames = []
for _ in range(180):
    world.step(dt)
    img = renderer.render(world)
    frames.append(img)
save_frames(frames, "examples/output/glass.gif", fps=30)
```

Forty-odd lines of setup before a single line of *scene logic*. The
studio rewrite collapses that into:

```python
stage = softbody_stage(view_box=(-2, -1, 2, 5))
cube = make_lattice_body(stage.world, "stone", width_cells=5, height_cells=5,
                         cell_size=0.10, position=(-0.25, 1.8))
cube.kick(stage.world, vy=8.0, twist=-0.6)
record(stage, frames=180, output="examples/output/glass.gif")
```

Three constraints fell out of this rewrite and have stuck since:

1. **Additive sugar, never a wall.** Every helper returns or operates
   on a plain `Stage` dataclass. Nothing is hidden — `stage.world`,
   `stage.renderer`, `stage.dt`, and every body-meta handle is exposed.
   A demo that needs custom per-frame logic just hooks `pre_step=` /
   `post_step=` into `record()`.
2. **One opinionated stage per substrate.** `softbody_stage`,
   `fluid_stage`, `humanoid_stage`, `fluid_with_softbody_stage`, and
   `dynamics_stage` each own their substrate and their default
   renderer. Mixing two substrates means either using
   `fluid_with_softbody_stage` (the shipped composite) or extending a
   single-substrate stage by hand — the API doesn't try to be
   everything to everyone.
3. **`record()` is the universal exit point.** All five stages produce
   GIFs via the same `record()` call, which drives the per-frame loop
   in a fixed step order (`pre_step → world step → post_step → render →
   overlay`). This is what makes the demos look uniform across the
   shipped gallery — they all share the same frame loop.

## The Stage bundle

`Stage` is a frozen-shape `dataclass` carrying every per-scene piece of
state the demo loop touches:

```python
@dataclass
class Stage:
    world: Any = None              # primary world (softbody / dynamics)
    softbody: Any = None           # optional second world
    fluid: Any = None              # optional fluid world
    dynamics: Any = None           # optional dynamics world
    renderer: Any = None           # primary renderer (or None)
    view_box: tuple = (-2, -1, 2, 5)
    dt: float = 1 / 60
    surface_y: float | None = None # top-of-pool after settle (fluid stages)
    body_metas: dict[str, Any] = field(default_factory=dict)
    render_fn: Callable[[Stage], Image] | None = None
```

The bundle is **mutable** by design — `stage.dt = 1 / 120` is the
intended way to bump the timestep, not "construct a different stage".
This keeps the per-demo footprint small (no `StageConfig` /
`StageOptions` layer).

### Why `body_metas` is a dict, not a list

Demos routinely need to refer back to specific bodies the helper
auto-spawned — the buoyancy demo's wood block, the IK-terrain demo's
humanoid skeleton, the dynamics-stage default renderer's colour
overrides. A `dict[str, Any]` lets the helper register named handles
without imposing an order:

```python
stage.body_metas["block"] = body_meta
stage.body_metas["bg"] = (255, 255, 255)
stage.body_metas["line_color"] = (32, 32, 32)
```

Demo callers fetch by name (`stage.body_metas["block"]`). The keys are
documented per factory in [`api/studio.md`](api/studio.md).

## The `render_fn` hook

The studio API split the render side into two roles:

- **`stage.renderer`** — a stateful object (`SoftBodyRenderer`,
  `FluidRenderer`) with its own `render(world) -> Image` method,
  produced by the shipped softbody / fluid renderers. This is the
  "standard" path; most stages use it.
- **`stage.render_fn`** — a pure callable `(Stage) -> PIL.Image`,
  introduced by `dynamics_stage` (Sprint 7G, commit `a4cbc60`).

The split exists because the dynamics substrate has **no shipped GPU
rasteriser**. Ropes, ragdolls, springs, motors, and IK chains live as
abstract joint/body records; no SDF, no per-pixel shader. The dynamics
stage therefore wires in a pure-PIL fallback that draws every joint as a
line and every node as a disk:

```python
def _default_dynamics_render(stage: Stage) -> Image:
    img = Image.new("RGBA", (stage._w, stage._h), bg)
    draw = ImageDraw.Draw(img)
    for joint in stage.world.joints:
        a, b = stage.world.bodies[joint.a].pos, stage.world.bodies[joint.b].pos
        draw.line([world_to_screen(a, view_box, w, h),
                   world_to_screen(b, view_box, w, h)],
                  fill=line_color, width=line_width)
    for body in stage.world.bodies:
        if body.inv_mass == 0:    # pinned
            color = pinned_color
        else:
            color = node_color
        ...
    return img
```

A one-line `stage.record(...)` produces a meaningful GIF for any
dynamics scene without the caller bringing a renderer. Override the
default renderer entirely by passing `render_fn=` to `dynamics_stage()`
or directly assigning `stage.render_fn`.

### Precedence

```text
   record(stage, ...)
            │
            ▼
   if stage.render_fn is not None:
       img = stage.render_fn(stage)
   elif stage.fluid is not None:
       img = stage.renderer.render(stage.fluid)   # FluidRenderer
   else:
       img = stage.renderer.render(stage.world)   # SoftBodyRenderer
```

`render_fn` wins over the shipped renderers; the per-call
`record(stage, render_fn=my_fn)` overrides anything bound on the stage
just for that call.

## The `record()` contract

```python
def record(
    stage: Stage,
    frames: int = 180,
    output: str | Path | None = None,
    *,
    fps: int = 30,
    step_world: bool = True,
    pre_step:  Callable[[Stage], None] | None = None,
    post_step: Callable[[Stage, int], None] | None = None,
    overlay:   Callable[[Image, tuple], None] | None = None,
) -> Path:
```

The frame loop is **explicit and small**:

```text
for frame_idx in range(frames):
    1. pre_step(stage)                          # apply forces, retarget IK
    2. if step_world:                            # step every world the stage owns
           if stage.softbody:  step_softbody()
           if stage.fluid:     step_fluid()
           if stage.dynamics:  step_dynamics()
    3. post_step(stage, frame_idx)               # sample data, mutate scene
    4. img = render(stage)                       # render_fn / fluid / softbody
    5. overlay(img, view_box)                    # terrain line, HUD, labels
    6. frames.append(img)
save_frames(frames, output, fps=fps)
```

Five hooks: `pre_step`, world-step gate, `post_step`, `render_fn`,
`overlay`. That's the complete extension surface — anything a demo
wants to do that the helpers don't shipped-support, it can do via one
of these five hooks. Anything beyond that means the caller has
out-grown the studio API and should drop down to the bare worlds and
renderers (which is fine — that's the additive contract).

### `step_world=False`

Demos that drive every frame manually (the IK-terrain demo that re-IKs
the humanoid each frame; the pose-capture demo that grabs the same
frame N times) pass `step_world=False` to skip the world step. The
caller drives positions through `pre_step` / `post_step` and `record()`
just captures the frames.

This is the cleanest split between "physics-driven" and "animation-
driven" demos. The same stage, the same `record()` call, just one
boolean.

## BodyMeta helpers — `kick` / `anchor` / `centroid` / `translate`

Pre-studio softbody worlds exposed body operations as methods on a
returned `BodyMeta` object:

```python
cube = make_lattice_body(world, ...)
cube.kick(world, vy=8.0)          # method on the meta
cube.anchor(world)                 # method on the meta
```

The studio API ships four module-level helpers that operate on a
`(node_start, node_end)` slice of a world's node array:

```python
from slappyengine.studio import kick, anchor, centroid, translate

cube = make_lattice_body(world, ...)
kick(world, cube.slice, vy=8.0, twist=-0.6)
anchor(world, cube.slice)
cx, cy = centroid(world, cube.slice)
translate(world, cube.slice, dx=0.5, dy=0.0)
```

The reason for the move: a meta-method assumes the meta knows how to
locate "its" nodes. That assumption breaks the moment a body is
flesh-wrapped, lattice-built, or hand-assembled — the slice into
`world.nodes` is the canonical "what is this body" handle, not the
`BodyMeta`. The module-level helpers operate on the slice directly,
which works on every body type uniformly.

The four operations are deliberately small. Anything more elaborate
(re-mass, re-material, deform) calls down to the world's own API.

### `translate` and the XPBD integrator

`translate(world, node_slice, dx, dy)` shifts both `pos` and `prev_pos`
by `(dx, dy)`. The double-shift is load-bearing: XPBD's velocity-from-
position estimator computes `v = (pos - prev_pos) / dt`. Shifting only
`pos` would make the integrator see a fictitious one-frame velocity
proportional to the displacement — visible as a sudden kick. Shifting
both keeps `v` unchanged.

This subtlety is exactly the kind of footgun the studio API hides
without taking it away from callers who need to know.

## Overlay hook

`overlay(img, view_box)` is called last, after the renderer has produced
its frame. The shipped `terrain_overlay(terrain_fn, ...)` factory
returns an overlay that paints a 1D terrain line over each frame — used
by the IK-terrain demo and the landscape demos. The signature is
intentionally minimal so demos can compose their own (HUD labels, frame
counters, debug arrows) without going through a custom renderer.

## Choosing a stage

| Use case | Stage | Why |
|----------|-------|-----|
| Solid block falls, bounces, deforms | `softbody_stage` | Single XPBD softbody world + textured/wireframe softbody renderer. Cheapest stage. |
| Pool of water sloshing, sand piling | `fluid_stage` | Single PBF fluid world + marching-squares surface renderer. `pool=` + `settle_steps=` pre-build a pool. |
| Block floats / sinks / breaks waves on a pool | `fluid_with_softbody_stage` | Both worlds, shared `FluidRenderer` that draws both. Pair with `apply_fluid_buoyancy` for Archimedes coupling. |
| Humanoid pose, IK, ragdoll-on-terrain demo | `humanoid_stage` | Softbody world with gravity/contact disabled and wireframe ON by default. |
| Rope swinging from a pin, motor-driven wheel | `dynamics_stage` | `dynamics.World` substrate + built-in pure-PIL line/disk renderer. |
| Custom multi-system scene | any of the above | Override `stage.renderer` or `render_fn=` to bring your own per-frame PIL image. |

Rule of thumb: pick the simplest stage that owns the **physics world**
you need, then mix in everything else via `pre_step` and `post_step`.

## When to migrate to Rust

The studio module is pure orchestration — no per-frame numeric work.
The per-frame Python cost is one dict lookup, one or two `world.step()`
calls (which already drop to Rust), and a `renderer.render()` call (the
softbody / fluid renderers have already been ported to Rust as of the
2026-05-26 renderer batching sprint). Total per-frame Python overhead
is sub-100-µs.

The Rust-migration plan
([`rust_migration_plan.md`](rust_migration_plan.md)) does not target
this subpackage. The natural next step is **adding more stage
factories** (e.g. `iso_stage` for Stone Keep-style scenes) rather than
porting existing code.

## See also

- [`api/studio.md`](api/studio.md) — full factory signatures, the
  Stage field table, the BodyMeta helper contract.
- [`studio_quickstart.md`](studio_quickstart.md) — 5-minute tour with
  runnable code.
- [`api/testing.md`](api/testing.md) — `record()` outputs feed the same
  visual-regression harness used by the engine suite.
- [`api/animation.md`](api/animation.md) — `humanoid_stage` pairs with
  the procedural-rig + IK surface.
- [`softbody_design.md`](softbody_design.md) — the softbody substrate
  the softbody / humanoid / composite stages run on.
- [`fluid_design.md`](fluid_design.md) — the fluid substrate.
- [`dynamics_design.md`](dynamics_design.md) — the dynamics substrate
  the `dynamics_stage` runs on.
- [`demo_gallery.md`](demo_gallery.md) — the six flagship runnable
  demos that exercise every stage.
