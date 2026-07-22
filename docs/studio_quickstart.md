## studio Quickstart

A 5-minute tour of `pharos_engine.studio` — the high-level scene-scaffolding
helpers that wrap the rebuild physics stack (softbody + fluid + dynamics) into
~15-line demos. Every helper here is additive sugar: drop down to the raw
`SoftBodyWorld` / `FluidWorld` APIs whenever you outgrow it.

> Prerequisites: `PYTHONPATH=python` from repo root, Python 3.11+, the engine's
> Python dependencies (numpy, Pillow, pyyaml). No Rust toolchain needed for
> the physics rebuild — it's pure NumPy.

### Why studio

Building a soft-body demo by hand means creating a `SoftBodyWorld`, configuring
the floor + walls + contact, building a `SoftBodyRenderConfig`, building a
`SoftBodyRenderer`, picking a `view_box`, writing a 30-line render-step-encode
loop, and shipping it through `save_frames`. That's ~50 lines of plumbing per
demo, and every demo gets it slightly wrong.

`studio` collapses all of that into:

1. `softbody_stage(...)` / `fluid_stage(...)` / `fluid_with_softbody_stage(...)`
   / `humanoid_stage(...)` — build a `Stage` (world + renderer + view_box + dt).
2. `record(stage, frames=N, output=...)` — run the loop, save a GIF.
3. Optional `pre_step` / `post_step` callbacks for per-frame logic
   (IK, Archimedes upthrust, force application).

The stage's `world` / `softbody` / `fluid` fields are the real underlying
worlds — direct array access is always available.

### Softbody stage

A brittle stone cube dropped from height shatters on impact. The
`stone` material in `config/softbody.yml` has `yield_strain == break_strain`
and `plasticity_rate == 0`, so beams snap cleanly past their break threshold.

```python
from pharos_engine.softbody import make_lattice_body
from pharos_engine.studio import softbody_stage, record

stage = softbody_stage(view_box=(-1.6, 1.0, 1.6, 5.3),
                       width=320, height=240,
                       floor_y=5.0, floor_friction=0.2,
                       contact_enabled=True)
cube = make_lattice_body(stage.world, "stone",
                         width_cells=5, height_cells=5, cell_size=0.10,
                         position=(-0.25, 1.8))
cube.kick(stage.world, vy=8.0, twist=-0.6)
record(stage, frames=180, output="glass.gif")
```

`make_lattice_body(world, material, ...) -> BodyMeta` returns a handle whose
`node_slice` / `beam_slice` index into the world's SoA arrays. `cube.kick(...)`
is the chainable form of `studio.kick(world, slice, ...)`.

### Fluid stage

A small column of water dropped into a walled basin. `pool=` is forwarded to
`FluidWorld.add_block_of_particles`.

```python
from pharos_engine.studio import fluid_stage, record

stage = fluid_stage(view_box=(-1.6, 2.0, 1.6, 5.3),
                    width=384, height=288,
                    floor_y=5.0, walls=(-1.2, 1.2),
                    pool=dict(material="water", nx=14, ny=10, spacing=0.06,
                              origin=(-0.42, 2.4), jitter=0.05))
record(stage, frames=360, output="water_basin.gif")
```

`material=` picks an entry from `config/fluid.yml` — `water`, `lava`, `sand`,
`gravel`, `dust`, `ice`, `stone`. Granular materials (`is_granular: true`) pile
up via the Coulomb friction pass; lava cools toward stone if cold enough.

### Fluid + softbody (Archimedes)

Wood floats, steel sinks. `fluid_with_softbody_stage` builds a pre-settled
pool plus an empty softbody world; the buoyancy hook applies per-node
Archimedes upthrust each frame.

```python
from pharos_engine.fluid import apply_fluid_buoyancy
from pharos_engine.softbody import make_lattice_body
from pharos_engine.studio import Stage, fluid_with_softbody_stage, record

stage = fluid_with_softbody_stage(
    view_box=(-2.0, 2.0, 2.0, 6.2), width=480, height=320,
    floor_y=6.0, walls=(-1.8, 1.8),
    pool=dict(material="water", nx=28, ny=22, spacing=0.06,
              origin=(-0.84, 2.7), jitter=0.04),
    settle_steps=140)
drop_y = stage.surface_y - 0.6
wood = make_lattice_body(stage.softbody, "wood",
                        width_cells=4, height_cells=2, cell_size=0.10,
                        position=(-1.10, drop_y))
steel = make_lattice_body(stage.softbody, "steel",
                         width_cells=4, height_cells=2, cell_size=0.10,
                         position=(0.30, drop_y))

def archimedes(s: Stage) -> None:
    apply_fluid_buoyancy(s.fluid, s.softbody, s.dt,
                         body_meta=wood, surface_y=s.surface_y)
    apply_fluid_buoyancy(s.fluid, s.softbody, s.dt,
                         body_meta=steel, surface_y=s.surface_y)

record(stage, frames=200, output="buoyancy.gif", pre_step=archimedes)
```

`settle_steps=` runs `pbf_step` that many times before returning the stage,
so by the time you query `stage.surface_y` the water has reached equilibrium.

### Humanoid stage

The humanoid demos use kinematic IK rather than free-fall — 2D skeletons have
no out-of-plane rotational stability. `humanoid_stage` defaults gravity to
zero, contact off, and the floor far below, so the user fully controls poses
each frame.

```python
from pharos_engine.dynamics import make_humanoid, place_feet_on_terrain
from pharos_engine.studio import humanoid_stage, record

stage = humanoid_stage(view_box=(-1.2, 0.0, 1.2, 4.0),
                       width=320, height=400)
skel = make_humanoid(stage.world, root_position=(0.0, 1.5))
flat_y = 3.5
place_feet_on_terrain(stage.world, skel, lambda x: flat_y,
                      pelvis_height_above_terrain=0.95)
record(stage, frames=60, output="humanoid_standing.gif",
       step_world=False)
```

`step_world=False` freezes the world — useful for pose-only captures where
every frame is identical, or for IK demos where `pre_step` / `post_step`
re-solves the pose each frame.

For walking across terrain, combine `terrain_overlay` (paints the ground
line) with a `post_step` callback that slides the skeleton's x and re-runs
`place_feet_on_terrain` each frame — see
`SlapPyEngineExamples/examples/humanoid_ik_terrain_demo.py` for the full recipe.

### BodyMeta chainable methods

Every builder returns a `BodyMeta` (or `HumanoidSkeleton`) whose helpers
are the chainable duals of the module-level functions:

```python
from pharos_engine.softbody import SoftBodyWorld, make_lattice_body

world = SoftBodyWorld()
plank = (make_lattice_body(world, "wood", width_cells=6, height_cells=1,
                           cell_size=0.10, position=(0.0, 0.0))
         .translate(world, 1.0, 0.0)   # shift by (dx, dy)
         .kick(world, vx=2.0, vy=0.0)  # set uniform velocity
         .anchor(world))               # pin every node
print(plank.centroid(world))           # geometric centroid
print(plank.node_count(), plank.beam_count())
```

All four (`anchor` / `kick` / `translate` / `centroid`) also exist as
module-level functions in `pharos_engine.studio` that take a `node_slice`
tuple directly — useful when operating on partial slices or composite
bodies.

### Where to drop down

Studio is intentionally a thin layer. When you need something it doesn't
offer, reach into the underlying worlds directly. The stage exposes them as
plain attributes:

| Want to … | Reach for … |
|---|---|
| Set per-node mass, fixed flag, or damping | `stage.world.nodes.mass[i]`, `.fixed[i]`, `.damping[i]` |
| Add custom beam constraints | `stage.world.beams.append(...)` |
| Step the world yourself | `pharos_engine.softbody.step(world, dt=...)` |
| Step a fluid world yourself | `pharos_engine.fluid.pbf_step(fluid)` |
| Add particles at runtime | `stage.fluid.add_block_of_particles(material, ...)` |
| Build vehicles / ropes / ragdolls | `pharos_engine.softbody.build_vehicle`, `pharos_engine.dynamics.make_rope`, `pharos_engine.dynamics.make_ragdoll` |
| Apply motor torque to a joint | `pharos_engine.dynamics.apply_motor` |
| Solve a kinematic IK chain | `pharos_engine.dynamics.solve_ik` |

`record(...)` is also optional — it's a 20-line loop over `pre_step` →
`softbody_step` / `pbf_step` → `post_step` → `renderer.render` →
`Image.fromarray` → `save_frames`. Write your own when you need anything
non-standard (e.g. per-frame output paths, video instead of GIF, headless
benchmarks).

For the long-form catalog of materials, see
[material_catalog.md](material_catalog.md). For the wider architectural
picture, see [architecture_overview.md](architecture_overview.md).
