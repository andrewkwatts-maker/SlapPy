# slappyengine.dynamics — 10-minute Quick Start

This guide gets you from `pip install slappy-engine` to a running rope
simulation in under 10 minutes. For the theory and tradeoffs see
[dynamics_design.md](dynamics_design.md); for full API reference see
[engine_surface_v030.md](engine_surface_v030.md).

## 0. Install

```bash
pip install slappy-engine
```

The `dynamics` subpackage is pure-Python on top of numpy. No GPU device is
required for any snippet on this page.

## 1. Your first rope

A `RopeSpec` is `node_count` beads connected by distance joints between two
anchor points. With `total_length > anchor_distance` the rope droops into a
catenary under gravity. The values below match
[examples/hello_rope.py](../examples/hello_rope.py) — a 24-node rope of
length 6.0 hung across a 4.0-unit span.

```python
from slappyengine.dynamics import RopeSpec, World, build_rope

world = World(gravity=(0.0, -9.81))
world.solver_iterations = 16

spec = RopeSpec(
    node_count=24,
    total_length=6.0,        # 50% slack over the 4.0 span
    mass_per_node=0.05,
    stiffness=2.0e6,
    damping=0.08,
    anchor_a_pinned=True,
    anchor_b_pinned=True,
)
body = build_rope(spec, world, anchor_a=(-2.0, 2.0), anchor_b=(2.0, 2.0))

for frame in range(120):
    world.step(1.0 / 60.0)

mid = body.node_offset + body.node_count // 2
print(f"frame 120 droop: {2.0 - float(world.positions[mid, 1]):.3f}")
print("settled")
```

Expected output: `frame 120 droop: 2.020` then `settled`. See the demo for
PIL rendering and a CLI wrapper.

## 2. Add a ragdoll

A `RagdollSpec` is a list of `BoneSpec` records. Each bone names its parent
by index (`-1` for root), a `direction` unit vector, and a `length`.
`build_ragdoll` wires every bone as a distance joint plus a hinge joint
enforcing the angle limit relative to the parent.

```python
import math
from slappyengine.dynamics import BoneSpec, RagdollSpec, World, build_ragdoll

bones = [
    BoneSpec(parent_idx=-1, length=0.6, mass=4.0,
             direction=(0.0, -1.0), label="torso"),
    BoneSpec(parent_idx=0,  length=0.3, mass=1.5,
             direction=(0.0,  1.0), label="head"),
    BoneSpec(parent_idx=0,  length=0.7, mass=1.5,
             direction=(-0.3, -1.0), label="leg_l"),
    BoneSpec(parent_idx=0,  length=0.7, mass=1.5,
             direction=( 0.3, -1.0), label="leg_r"),
]
spec = RagdollSpec(bones=bones)

world = World(gravity=(0.0, -9.81))
world.solver_iterations = 12
body = build_ragdoll(spec, world, anchor_pos=(0.0, 3.0), pin_root=False)

for frame in range(60):
    world.step(1.0 / 60.0)

ys = world.positions[list(body.node_indices), 1]
print(f"frame 60 lowest y: {float(ys.min()):.3f}")
print("settled")
```

The full 6-bone humanoid (with arms) is in
[examples/hello_ragdoll.py](../examples/hello_ragdoll.py).

## 3. Tracking a target with IK

`solve_ik` runs CCD (Cyclic Coordinate Descent) over a chain of node
indices, rotating each pivot to drive the tip toward `spec.target`. It
returns `True` when the tip lands within `tolerance` of the target.

```python
import math
from slappyengine.dynamics import IKChainSpec, JointSpec, World, solve_ik

world = World(gravity=(0.0, 0.0))   # IK is kinematic, no gravity
world.solver_iterations = 8

NODE_COUNT = 5
LINK_LENGTH = 1.0
node_indices = []
for i in range(NODE_COUNT):
    mass = 0.0 if i == 0 else 1.0   # base node is pinned
    node_indices.append(world.add_node((i * LINK_LENGTH, 0.0), mass=mass))

for i in range(NODE_COUNT - 1):
    world.add_joint(JointSpec(
        kind="distance",
        node_a=node_indices[i],
        node_b=node_indices[i + 1],
        rest_length=LINK_LENGTH,
        stiffness=1.0e7,
        damping=0.02,
    ))

spec = IKChainSpec(
    node_indices=list(node_indices),
    target=(2.0, 1.0),
    fixed_root=True,
)

converged = False
for frame in range(120):
    spec.target = (
        2.0 + 1.5 * math.sin(frame / 30.0),
        1.0 + 1.5 * math.cos(frame / 30.0),
    )
    converged = solve_ik(spec, world, iterations=20, tolerance=0.01)

tip = world.positions[node_indices[-1]]
print(f"frame 120 tip: ({tip[0]:.3f}, {tip[1]:.3f}); converged={converged}")
print("settled")
```

See [examples/hello_ik_chain.py](../examples/hello_ik_chain.py) for the
PIL renderer and convergence statistics over 240 frames.

## 4. Springs and motors

**Spring** — `make_spring` returns a `JointSpec(kind="spring")` with
softer authoring defaults than `kind="distance"`. Use it for suspension,
tethers, or any link that should oscillate.

```python
from slappyengine.dynamics import World, make_spring

world = World(gravity=(0.0, -9.81))
world.solver_iterations = 8
anchor = world.add_node((0.0, 2.0), mass=0.0)   # pinned
bob = world.add_node((0.0, 1.0), mass=1.0)
world.add_joint(make_spring(
    anchor, bob, rest_length=1.0, stiffness=200.0, damping=0.1,
))

for frame in range(60):
    world.step(1.0 / 60.0)

print(f"frame 60 bob y: {float(world.positions[bob, 1]):.3f}")
print("settled")
```

**Motor** — `make_motor` spins two `rim` nodes around a `hub` toward
`target_omega`, capped per substep by `max_torque`. Note: as of
`cc11183`, `max_torque <= 0` and missing `target_omega` raise
`ValueError` at construction (previously they silently disabled the
spin).

```python
import math
from slappyengine.dynamics import World, make_motor

world = World(gravity=(0.0, 0.0))
world.solver_iterations = 8

radius = 0.5
hub = world.add_node((0.0, 0.0), mass=0.0)         # pinned hub
rim_a = world.add_node(( radius, 0.0), mass=1.0)
rim_b = world.add_node((-radius, 0.0), mass=1.0)
world.add_joint(make_motor(
    hub=hub, rim_a=rim_a, rim_b=rim_b,
    target_omega=4.0,   # rad/s
    max_torque=10.0,    # |Δv| cap per substep
    radius=radius,
))

initial = world.positions[rim_a].copy()
for frame in range(120):
    world.step(1.0 / 60.0)

now = world.positions[rim_a]
angle = math.atan2(now[1], now[0]) - math.atan2(initial[1], initial[0])
print(f"frame 120 rim_a angle delta: {angle:.3f} rad")
print("settled")
```

## 5. Combining primitives

Every builder writes into the same `World`, so you can mix them freely.
Here is a single-wheel cart: a chassis welded by a stiff distance joint,
a wheel hub suspended by two springs, and a motor driving the rim.

```python
from slappyengine.dynamics import World, make_spring, make_motor, JointSpec

world = World(gravity=(0.0, -9.81))
world.solver_iterations = 16

# Chassis: two nodes joined by a stiff distance joint.
chassis_l = world.add_node((-0.5, 1.0), mass=2.0)
chassis_r = world.add_node(( 0.5, 1.0), mass=2.0)
world.add_joint(JointSpec(
    kind="distance", node_a=chassis_l, node_b=chassis_r,
    rest_length=1.0, stiffness=1.0e7, damping=0.05,
))

# Wheel: hub + two rim nodes.
radius = 0.25
hub = world.add_node((0.0, 0.4), mass=1.0)
rim_a = world.add_node(( radius, 0.4), mass=0.3)
rim_b = world.add_node((-radius, 0.4), mass=0.3)

# Suspension: springs from each chassis corner to the hub.
world.add_joint(make_spring(
    chassis_l, hub, rest_length=0.7, stiffness=5.0e3, damping=0.2,
))
world.add_joint(make_spring(
    chassis_r, hub, rest_length=0.7, stiffness=5.0e3, damping=0.2,
))

# Drive the wheel.
world.add_joint(make_motor(
    hub=hub, rim_a=rim_a, rim_b=rim_b,
    target_omega=2.0, max_torque=5.0, radius=radius,
))

for frame in range(60):
    world.step(1.0 / 60.0)

print(f"frame 60 chassis y: {float(world.positions[chassis_l, 1]):.3f}")
print("settled")
```

For a full-featured vehicle (drivetrain modes, tire scrolling, multi-wheel
chassis) reach for `slappyengine.softbody.vehicle.build_vehicle` — the
legacy higher-level builder that composes the same primitives.

## 6. Rendering

The dynamics module only mutates numpy arrays — `world.positions`,
`world.velocities`, `world.inv_masses`. For headless visual verification
use `slappyengine.testing.render_scene_to_png` (writes a PNG, diffs
against a baseline, fails on regression). For ad-hoc visualisation copy
the pure-PIL renderer used by the demos — see `_render_frame` in any of
[examples/hello_rope.py](../examples/hello_rope.py),
[examples/hello_ragdoll.py](../examples/hello_ragdoll.py), or
[examples/hello_ik_chain.py](../examples/hello_ik_chain.py). They take an
RGBA image and draw line segments between bonded nodes plus dots at each
node — about 30 lines, no GPU.

## 7. Common pitfalls

- **"My rope just hangs straight"** — check `total_length > anchor_distance`.
  If they are equal the rope has no slack and the catenary collapses to a
  near-straight line (droop ~0.4 instead of ~2.0 in the section 1 example).
- **"Motor doesn't spin"** — set `target_omega` AND `max_torque > 0`. As of
  commit `cc11183`, `make_motor` raises `ValueError` instead of silently
  no-opping when these are missing or zero — so a quietly-still wheel now
  surfaces as a constructor error you can fix immediately.
- **"Solver explodes / NaN"** — reduce `dt`, increase `solver_iterations`.
  At `dt = 0.5` with `solver_iterations = 1` the rope from section 1 flies
  away to RMS ~1000 in 20 frames. The recommended starting point is
  `dt = 1/60` with `solver_iterations` between 8 (default) and 16.
- **"Joint never converges"** — relax `tolerance`, check `JointSpec.kind`
  is supported. `solve_ik` returns `False` whenever the tip cannot land
  within `tolerance` of the target (e.g. the target is outside the chain's
  reach); widen `tolerance` to accept "best effort". For `JointSpec`,
  `kind` must be one of `"distance"`, `"spring"`, `"weld"`, `"ball"`,
  `"hinge"`, `"motor"`, `"prismatic"` — any other value raises
  `ValueError` at construction.

## See also

- [examples/hello_rope.py](../examples/hello_rope.py) — catenary droop demo
- [examples/hello_ragdoll.py](../examples/hello_ragdoll.py) — humanoid drop
- [examples/hello_ik_chain.py](../examples/hello_ik_chain.py) — CCD IK chain
- [dynamics_design.md](dynamics_design.md) — when to use which primitive
- [engine_surface_v030.md](engine_surface_v030.md) — full API reference
