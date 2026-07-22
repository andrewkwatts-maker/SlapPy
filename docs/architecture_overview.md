## Architecture Overview — Rebuild Physics Stack

This is a 5-minute orientation for the rebuilt 2D physics layer
(`softbody` / `fluid` / `dynamics` / `studio`). For the wider engine
(rendering, scripts, scene system, Rust `_core` extension), see
[ARCHITECTURE.md](ARCHITECTURE.md). For per-pixel hierarchical-hull
physics (a separate experimental track), see [physics_module.md](physics_module.md).

### Dependency direction

```
                +-------------------+
                |   pharos_engine    |  user-facing entry point
                +---------+---------+
                          |
       +------------------+------------------+
       |                                     |
       v                                     v
+--------------+                   +----------------------+
|   studio     |  scene helpers,   |   engine / scene /   |  legacy game
|  (record,    |   GIF recording   |   scripts / lighting |  systems
|   Stage)     |                   +----------------------+
+------+-------+
       |
       v
+------------------+      +------------------+
|    dynamics      |----->|     softbody     |
| (joints, motors, |      |  (XPBD lattice,  |
|  ragdolls, IK,   |      |   nodes + beams) |
|  humanoid)       |      +--------+---------+
+------------------+               ^
                                   | (shared spatial-hash form)
                                   |
                          +--------+---------+
                          |      fluid       |
                          | (PBF particles,  |
                          |  buoyancy hook)  |
                          +------------------+
```

Arrows point from caller to callee. `dynamics` is a wider type system on
top of `softbody`'s XPBD solver — it doesn't add new physics, it
composes the existing distance-constraint primitive into ropes, ragdolls,
vehicles, IK chains, and humanoid skeletons. `fluid` is independent of
`softbody` but uses the same XPBD spatial-hash form for particle ↔ beam
contact.

### `pharos_engine.softbody` — XPBD lattice physics

BeamNG-style node-and-beam simulator in 2D, following the XPBD
formulation from Macklin et al. 2016 (*"XPBD: position-based simulation
of compliant constrained dynamics"*). State is SoA: `NodeSoA` (position,
velocity, mass, fixed-flag, body_id, layer) and `BeamSoA` (`node_a`,
`node_b`, `rest_length`, `stiffness`, `damping`, `break_strain`,
`yield_strain`, `plasticity_rate`, `broken`). `solver.step` runs N
substeps × M iterations of distance-constraint projection, applies
floor + body-body contact, and updates plastic rest-lengths past yield.
Materials and tuning live in `config/softbody.yml`. Topology builders
(`make_lattice_body`, `make_layered_creature`, `build_vehicle`) pack
typed primitives into the SoA arrays.

### `pharos_engine.fluid` — Position-Based Fluids

Particle fluid in 2D following Macklin & Müller 2013 (*"Position based
fluids"*). `ParticleSoA` carries position, velocity, mass, material_id,
temperature. `pbf_step` runs density-constraint projection, XSPH
viscosity, optional vorticity confinement, and a Coulomb-friction pass
for granular materials (sand, gravel, dust). A thermal pass diffuses
temperature and applies per-particle phase change (lava → stone,
ice → water) via material_id flips. `apply_fluid_buoyancy` implements
Archimedes coupling: per-node upthrust proportional to local fluid
density above each submerged softbody node. Materials live in
`config/fluid.yml`.

### `pharos_engine.dynamics` — unified primitive layer

A type system on top of softbody. The same primitive set composes into
lattices, vehicles, ropes, ragdolls, IK chains, and humanoid skeletons.
`JointSpec` is the central abstraction (distance / hinge / ball / weld
/ spring), and `resolve_joint_specs` lowers them into the underlying
XPBD beam representation. `MotorHandle` + `apply_motor` provides
motorised joints; `solve_ik` runs FABRIK-style 2-bone IK; `make_humanoid`
+ `place_feet_on_terrain` + `wrap_in_flesh` build a bones-and-flesh
humanoid.

### `pharos_engine.studio` — high-level scaffolding

Bundles world(s) + renderer + view_box + dt into a `Stage` dataclass
and provides `record(stage, frames=..., output=...)` to run the render
loop. Four scene factories: `softbody_stage`, `fluid_stage`,
`fluid_with_softbody_stage`, `humanoid_stage`. See
[studio_quickstart.md](studio_quickstart.md).

### Integration with the legacy engine

The rebuild stack is intentionally decoupled from `pharos_engine.engine`
/ `scene` / `scripts` / `lighting`. Two integration paths today:

- Use `studio` for cinematic GIF captures from a game's debug menu.
- Step `SoftBodyWorld` / `FluidWorld` from a `Script.on_update` hook
  and bridge transforms by reading `world.nodes.pos`.

A separate per-pixel hierarchical-hull system
([physics_module.md](physics_module.md)) ships its own component-based
engine integration. Both share XPBD math but not data structures.

### Where to look next

| Topic | File |
|---|---|
| `studio` quickstart | [studio_quickstart.md](studio_quickstart.md) |
| Material catalogs (softbody + fluid) | [material_catalog.md](material_catalog.md) |
| Softbody design rationale | [softbody_design.md](softbody_design.md) |
| Fluid kernel math + PBF derivation | [fluid_design.md](fluid_design.md) |
| Hierarchical-hull per-pixel physics | [physics_module.md](physics_module.md) |
| Legacy engine architecture | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Contributor onboarding | [ONBOARDING.md](ONBOARDING.md) |
