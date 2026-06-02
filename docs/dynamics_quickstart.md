# slappyengine.dynamics — Quickstart

`slappyengine.dynamics` is the unified 2D constraint subsystem for
SlapPyEngine. It is an **Extended Position-Based Dynamics (XPBD) solver** —
positions are projected directly, no separate force / acceleration pass —
exposed through a single `World.step()` entry point. There is no split
between "constraints" and "forces" on the public surface: every spring,
weld, hinge, motor, rope, ragdoll, IK chain, and humanoid skeleton
resolves to one of seven XPBD distance / angular projections built on top
of the same node array. Add the primitives you need, call `step()`, read
the positions back.

For the underlying theory and design tradeoffs see
[dynamics_design.md](dynamics_design.md); for the auto-generated reference
of every public class / function see [api/dynamics.md](api/dynamics.md).

## 0. Install

`slappyengine.dynamics` ships with the main wheel — no extra dependency.
Pure numpy on the hot path; the optional Rust kernels accelerate softbody
/ fluid layers but are not required for the joint solver itself.

```python
# pip install slappy-engine
import slappyengine
from slappyengine.dynamics import World, make_spring

print(slappyengine.__version__)
world = World(gravity=(0.0, -9.81))
assert hasattr(world, "step")
```

If you plan to follow the humanoid / softbody sections, also import
`slappyengine.softbody.SoftBodyWorld` — that path needs the Rust kernel
(bundled in the wheel) but no separate install step.

## 1. Your first rope

A pinned anchor with a hanging mass on a spring. No optional dependencies,
no GPU — pure numpy plus the engine. This is the canonical "does the
solver step" smoke test.

```python
from slappyengine.dynamics import World, make_spring

# 1. Build a world. Gravity is the standard engine convention (y up).
world = World(gravity=(0.0, -9.81))
world.solver_iterations = 8

# 2. Two nodes: a pinned anchor (mass = 0 => kinematic) and a free mass.
anchor = world.add_node((0.0, 2.0), mass=0.0)
bob    = world.add_node((0.0, 1.0), mass=1.0)

# 3. Connect them with a spring. make_spring returns a JointSpec(kind="spring")
#    with author-tuned soft defaults; for a stiff weld use make_distance instead.
world.add_joint(make_spring(
    anchor, bob,
    rest_length=1.0,
    stiffness=200.0,
    damping=0.1,
))

# 4. Step. Each frame: predict positions under gravity, project every joint
#    solver_iterations times, recover velocity from the position delta.
for frame in range(60):
    world.step(1.0 / 60.0)

print(f"bob position after 60 frames: {world.positions[bob]}")
```

Expected output is a value oscillating around `(0.0, 1.0)` (the spring's
rest position relative to the anchor at `(0, 2)`). For a multi-node rope
between two anchors with bend joints, see `build_rope` in section 5.

## 2. Add a ragdoll

`RagdollSpec(bones=[BoneSpec(...), ...])` describes a tree rooted at one
bone (`parent_idx=-1`). Each bone is realised as a distance constraint
along its `direction * length`; angle limits become hinge joints
between grandparent → child relative to the parent pivot.

```python
import math
from slappyengine.dynamics import BoneSpec, RagdollSpec, World, build_ragdoll

bones = [
    BoneSpec(parent_idx=-1, length=0.6, mass=4.0, direction=(0.0, -1.0)),
    BoneSpec(parent_idx=0,  length=0.3, mass=1.5, direction=(0.0,  1.0)),
    BoneSpec(parent_idx=0,  length=0.7, mass=1.5, direction=(-0.3, -1.0)),
    BoneSpec(parent_idx=0,  length=0.7, mass=1.5, direction=( 0.3, -1.0)),
]
world = World(gravity=(0.0, -9.81))
body  = build_ragdoll(RagdollSpec(bones=bones), world, anchor_pos=(0.0, 3.0))
for _ in range(60):
    world.step(1.0 / 60.0)
```

See [examples/hello_ragdoll.py](../SlapPyEngineExamples/examples/hello_ragdoll.py) for a
6-bone humanoid drop. Note `parent_idx` must reference an earlier index
in the `bones` list (the builder walks the list once). For the named
13-node anatomical skeleton (pelvis / neck / head / shoulders / hips /
ankles), use `build_humanoid` from section 5.

## 3. Tracking a target with IK

`solve_ik(spec, world, iterations=10, tolerance=0.01)` runs Cyclic
Coordinate Descent over `spec.node_indices`, rotating each pivot to drive
the tip toward `spec.target`. Returns `True` when the tip lands within
`tolerance`. It mutates positions in place and runs without `World.step()`
— pair it with `step()` for combined kinematic + dynamic chains.

```python
from slappyengine.dynamics import IKChainSpec, JointSpec, World, solve_ik

world = World(gravity=(0.0, 0.0))
chain = [world.add_node((i, 0.0), mass=0.0 if i == 0 else 1.0)
         for i in range(5)]
for i in range(4):
    world.add_joint(JointSpec(kind="distance", node_a=chain[i],
                              node_b=chain[i+1], rest_length=1.0,
                              stiffness=1.0e7, damping=0.02))
spec = IKChainSpec(node_indices=chain, target=(2.0, 1.0), fixed_root=True)
converged = solve_ik(spec, world, iterations=20, tolerance=0.01)
```

See [examples/hello_ik_chain.py](../SlapPyEngineExamples/examples/hello_ik_chain.py) for a
moving target swept over 240 frames. For analytic 2-bone foot IK on a
humanoid skeleton, see `place_feet_on_terrain` referenced in section 5.

## 4. Springs and motors

### `make_spring` — Hooke-style soft link

`make_spring(node_a, node_b, rest_length, stiffness=1.0e6, damping=0.05)`
returns a `JointSpec(kind="spring")` with bouncy author defaults. Use for
suspension, tethers, anything that should oscillate visibly.

```python
from slappyengine.dynamics import World, make_spring

world = World(gravity=(0.0, -9.81))
anchor = world.add_node((0.0, 2.0), mass=0.0)
bob    = world.add_node((0.0, 1.0), mass=1.0)
world.add_joint(make_spring(anchor, bob, rest_length=1.0,
                            stiffness=200.0, damping=0.1))
for _ in range(120):
    world.step(1.0 / 60.0)
print(world.positions[bob])
```

See [examples/hello_spring.py](../SlapPyEngineExamples/examples/hello_spring.py) for an
oscillator measured against the theoretical period `T = 2π·sqrt(m/k)`.

### `make_motor` — driven hub-rim wheel

`make_motor(hub, rim_a, rim_b, target_omega, max_torque, radius=...)` keeps
two rim nodes at fixed `radius` from a hub while applying a tangential
impulse that drives them toward `target_omega` (rad/s). `max_torque` caps
the per-substep |Δv|.

```python
from slappyengine.dynamics import World, make_motor

world = World(gravity=(0.0, 0.0))
hub   = world.add_node((0.0, 0.0), mass=0.0)
rim_a = world.add_node(( 1.0, 0.0), mass=1.0)
rim_b = world.add_node((-1.0, 0.0), mass=1.0)
world.add_joint(make_motor(hub=hub, rim_a=rim_a, rim_b=rim_b,
                           target_omega=3.14, max_torque=10.0, radius=1.0))
for _ in range(240):
    world.step(1.0 / 60.0)
```

See [examples/hello_motor.py](../SlapPyEngineExamples/examples/hello_motor.py) for the full
wheel rendering with frame trails. As of `cc11183`, `max_torque <= 0` and
non-finite `target_omega` raise `ValueError` rather than silently
no-opping.

### Joint kinds reference

Every joint is a `JointSpec` discriminated by the `kind` string. The seven
recognised values and the `params` dict each one consumes:

| `kind`        | `params` keys                                        | Notes |
|---------------|------------------------------------------------------|-------|
| `"distance"`  | *(none)*                                             | Stiff fixed-length link. Use `make_distance` for the rigid-rod default. |
| `"spring"`    | *(none)*                                             | Same projection as `distance`; softer defaults via `make_spring`. |
| `"weld"`      | `{"rest_offset": (dx, dy)}` *(optional)*             | Stiff distance constraint at `rest_length` (default 0). |
| `"ball"`      | *(none)*                                             | Zero rest length distance; no angular limit. |
| `"hinge"`     | `{"anchor": int, "min_angle": float, "max_angle": float}` | Distance + angular clamp between `anchor->node_a` and `anchor->node_b`. |
| `"motor"`     | `{"hub": int, "axis": (ax, ay), "target_omega": float, "max_torque": float}` | Spins rim nodes around a hub via tangential impulse, capped per substep. |
| `"prismatic"` | `{"axis": (ax, ay), "min": float, "max": float}`     | Slot constraint: along-axis range, perpendicular drift cancelled. |

The full per-kind schema is in
[`KIND_PARAM_KEYS`](../python/slappyengine/dynamics/joint.py). Validation
runs in `JointSpec.__post_init__`: unknown kinds, negative indices, equal
nodes, NaN / infinite values, or out-of-range damping all raise at
construction.

## 4a. Builder conventions

Every public builder in `slappyengine.dynamics` falls into one of three
buckets. Learn the prefix and the contract follows.

| Prefix     | Returns                  | Mutates a world? | Use when                                          |
|------------|--------------------------|------------------|---------------------------------------------------|
| `make_*`   | `JointSpec` or `*Spec`   | **No**           | Batch-construct specs (serialise, edit, install later). |
| `build_*`  | A handle (`int`, `Body`, `Humanoid`) | **Yes**          | One-shot: spawn nodes / joints / beams now.       |
| `solve_*`  | `bool` (or status)       | Yes (positions only) | Drive existing nodes toward a target; no new entities. |

Concrete surface today:

* `make_*` — `make_distance`, `make_spring`, `make_motor` all return a
  pure `JointSpec`. They never touch a world; install the result with
  `world.add_joint(spec)` or batch them through `resolve_joint_specs`.
* `build_*` — `build_rope(spec, world, ...)`, `build_ragdoll(spec, world, ...)`,
  `build_humanoid(world, ...)`, `build_flesh_wrap(world, humanoid, ...)`
  all mutate the supplied world and return a handle covering the new
  entities (a `Body` for rope / ragdoll, a `Humanoid` for the skeleton
  factories).
* `solve_*` — `solve_ik(spec, world, ...)` rotates existing chain nodes
  toward `spec.target` and returns whether the tip converged. It does
  not add nodes.

The world is **always passed as a positional argument** (never via
keyword) so the builder can dispatch on its type. Spec-driven builders
(`build_rope`, `build_ragdoll`, `solve_ik`) take the spec at position 0
and the world at position 1; free-form builders (`build_humanoid`,
`build_flesh_wrap`) take the world at position 0.

`make_humanoid` and `wrap_in_flesh` are **deprecated aliases** for
`build_humanoid` and `build_flesh_wrap` respectively — they predate the
convention, mutate a `SoftBodyWorld`, and emit `DeprecationWarning` on
call. The old names will keep working for the v0.x line so games like
Ochema Circuit and Bullet Strata can migrate at their own pace.

```python
from slappyengine.dynamics import build_humanoid, build_flesh_wrap
from slappyengine.softbody import SoftBodyWorld

world = SoftBodyWorld()
hum   = build_humanoid(world, root_position=(0.0, 1.0))   # build_*: mutates, returns Humanoid
build_flesh_wrap(world, hum, muscle_offset=0.10)          # build_*: mutates, returns hum
```

## 5. Combining primitives

The dynamics surface composes — `build_rope`, `build_ragdoll`, and
`make_humanoid` all emit nodes / joints into the same world and can be
mixed freely in one `step()` loop.

### `build_rope` — chain between two anchors

`build_rope(spec, world, anchor_a, anchor_b)` lays `node_count` beads
linearly between the anchors, glues each pair with a distance joint, and
optionally adds bend joints across `(i, i+2)` for cable stiffness.
Returns a `Body` covering the spawned nodes.

```python
from slappyengine.dynamics import RopeSpec, World, build_rope

world = World(gravity=(0.0, -9.81))
world.solver_iterations = 16
spec = RopeSpec(node_count=24, total_length=6.0, mass_per_node=0.05,
                stiffness=2.0e6, damping=0.08,
                anchor_a_pinned=True, anchor_b_pinned=True)
body = build_rope(spec, world, anchor_a=(-2.0, 2.0), anchor_b=(2.0, 2.0))
for _ in range(120):
    world.step(1.0 / 60.0)
```

See [examples/hello_rope.py](../SlapPyEngineExamples/examples/hello_rope.py) for a 50%-slack
catenary that settles to a ~2.0-unit droop in 120 frames.

### `build_humanoid` — 13-node anatomical skeleton

`build_humanoid(world, root_position)` spawns a named skeleton (pelvis,
neck, head, shoulders / elbows / wrists, hips / knees / ankles) on a
**softbody** world that exposes `.nodes` / `.beams` SoA arrays. Pair with
`build_flesh_wrap` for muscle / skin layers and `place_feet_on_terrain`
for analytic 2-bone foot IK.

```python
from slappyengine.softbody import SoftBodyWorld
from slappyengine.dynamics import build_humanoid, build_flesh_wrap

world = SoftBodyWorld()
hum   = build_humanoid(world, root_position=(0.0, 1.0))
build_flesh_wrap(world, hum, muscle_offset=0.10, skin_offset=0.18)
for _ in range(60):
    world.step(1.0 / 60.0)
print("head node index:", hum.head, "ankle_l:", hum.ankle_l)
```

Unlike rope / ragdoll the humanoid factory requires the softbody world,
not the slim XPBD `World` — `build_humanoid` raises `TypeError` immediately
if the world is the wrong type. Combining a humanoid with a rope held in
its hand is one `add_joint(make_spring(hum.wrist_r, rope_end, ...))` call.

The legacy spellings `make_humanoid` / `wrap_in_flesh` still work but
emit `DeprecationWarning` — see section 4a for the rename rationale.

## 6. Rendering

The dynamics solver is headless: it owns positions and that is all. Wire
it to the engine renderer by reading `world.positions` each frame and
feeding the resulting points to whichever layer you prefer.

```python
from slappyengine.dynamics import World, make_spring

world = World(gravity=(0.0, -9.81))
anchor = world.add_node((0.0, 2.0), mass=0.0)
bob    = world.add_node((0.0, 1.0), mass=1.0)
world.add_joint(make_spring(anchor, bob, rest_length=1.0,
                            stiffness=200.0, damping=0.1))

def render_frame(layer):
    # world.positions is an (N, 2) numpy array; index by node id.
    layer.draw_line(world.positions[anchor], world.positions[bob])
    layer.draw_disk(world.positions[bob], radius=0.05)

for _ in range(60):
    world.step(1.0 / 60.0)
    # render_frame(my_layer)   # call inside your engine loop
```

For a richer demo of the full integration (sprite + line + glow + bloom
post-process) see [examples/hello_rope.py](../SlapPyEngineExamples/examples/hello_rope.py) and
the studio API in [studio_quickstart.md](studio_quickstart.md).

## 7. Common pitfalls

### Over-damping

XPBD position damping is applied **per inner-loop iteration**. With
`World.solver_iterations = N` and per-joint `damping = d`, the effective
per-step damping is `1 - (1 - d)^N`. Once this exceeds the
`OVERDAMPING_THRESHOLD` of 0.5 the spring converges to equilibrium inside
a single `step()` and visually behaves like a stiff weld rather than a
spring.

Practical rule: **keep `solver_iterations * damping ≲ 0.3`**. The
default 8 iterations + 0.05 damping gives an effective per-step damping
of ~0.34 (right at the edge of the band) — bump damping above ~0.04 only
when you've also dropped iterations.

The first time `World.step()` detects a configuration above the
threshold it emits a `RuntimeWarning` with the offending joint id, the
computed effective damping, and a suggested replacement value. Subsequent
joints with the **same** `(kind, damping, iters)` tuple are silenced via
the process-wide throttle introduced in Sprint 2G (see
`_OVER_DAMPED_WARNED` in
[`world.py`](../python/slappyengine/dynamics/world.py)) — without it,
demos like `hello_rope` would emit 70+ identical diagnostics on startup.
Tests that need to re-observe the warning call
`slappyengine.dynamics.world._reset_warning_cache()` in a fixture.

To silence the warning entirely set `world.warn_overdamping = False`.

### Other gotchas

* **Wrong world type for `make_humanoid`** — it raises `TypeError` if you
  pass the slim XPBD `World` instead of `SoftBodyWorld`. The error
  message points at the right import.
* **`parent_idx` ordering** — `BoneSpec.parent_idx` must reference an
  earlier index in the list; the builder walks once and does not sort.
* **`max_torque <= 0` on motors** — raises `ValueError` since `cc11183`;
  previously it silently no-opped.
* **Velocity drift on pinned nodes** — anchors created with `mass=0.0`
  ignore position projections, but if you also pass a non-zero initial
  velocity it persists. Re-pin by setting `world.velocities[anchor] = 0`.

### Editor integration

Every dynamics dataclass (`Body`, `Material`, `JointSpec`, `MotorSpec`,
`SpringSpec`, `RopeSpec`, `IKChainSpec`, `RagdollSpec`, `BoneSpec`) is a
plain Python dataclass, so the editor's
[`PropertyInspector`](../python/slappyengine/ui/editor/property_inspector.py)
reflects them through the standard primitive-widget path. Spawn-menu
actions live in
[`spawn_menu.py`](../python/slappyengine/ui/editor/spawn_menu.py); Sprint
3G added the **Humanoid** spawn entry mirroring `make_humanoid`'s kwargs.

### Performance

End-to-end timings (CPU baseline at 60 Hz with 8 solver iterations,
Sprint 4 of the perf push) are tracked in
[`benchmarks/baseline_report.md`](../benchmarks/baseline_report.md). At
the time of writing the dynamics substrate steps a 24-node rope at
~1000 fps and a 6-bone ragdoll at ~600 fps on a single Python thread;
the Rust kernel migration (Tiers 1-10) carries the heavy lifting for the
softbody / fluid paths layered on top.

## See also

* [dynamics_design.md](dynamics_design.md) — why XPBD; where each
  primitive sits in the type system; failure modes.
* [api/dynamics.md](api/dynamics.md) — auto-generated reference for every
  public class / function / field.
* [examples/hello_spring.py](../SlapPyEngineExamples/examples/hello_spring.py),
  [hello_joint.py](../SlapPyEngineExamples/examples/hello_joint.py),
  [hello_motor.py](../SlapPyEngineExamples/examples/hello_motor.py),
  [hello_rope.py](../SlapPyEngineExamples/examples/hello_rope.py),
  [hello_ragdoll.py](../SlapPyEngineExamples/examples/hello_ragdoll.py),
  [hello_ik_chain.py](../SlapPyEngineExamples/examples/hello_ik_chain.py),
  [hello_dynamics_serialize.py](../SlapPyEngineExamples/examples/hello_dynamics_serialize.py)
  — runnable demos for every primitive on this page.
