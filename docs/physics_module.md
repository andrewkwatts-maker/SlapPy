# Physics Module — `pharos_engine.physics`

Entry point for the hierarchical-hull per-pixel physics module.

- Single-file design overview, code-pasteable quickstart, joint
  examples, config knobs, GPU/CPU paths, and known limits.

---

## 1. Quickstart

Drop a steel ball onto a stone floor, run 90 frames, write a GIF.
Every symbol below is re-exported from `pharos_engine.physics`.

```python
from pathlib import Path

from pharos_engine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
    make_rect_silhouette,
)
from pharos_engine.physics.render import (
    PhysicsRenderer,
    RenderConfig,
    render_world_gif,
)
from pharos_engine.physics.particles import ParticleSystem
from pharos_engine.physics.debug_hud import DebugHUD

world = PhysicsWorld(world_bounds=(-200.0, -100.0, 200.0, 250.0))

ground = world.create_body(
    make_rect_silhouette(240, 16), "stone",
    position=(0.0, 180.0), fixed=True,
)
ball = world.create_body(
    make_circle_silhouette(24), "steel",
    position=(0.0, 0.0), velocity=(0.0, 0.0),
)

renderer = PhysicsRenderer(RenderConfig(width=320, height=240))
particles = ParticleSystem()
hud = DebugHUD()

frames = []
for f in range(90):
    contacts = world.step()                       # dt defaults to config
    particles.emit_from_contacts(contacts, world=world)
    particles.step(1.0 / 60.0)
    frame = renderer.render(world)
    particles.render(frame, world_view=renderer.config.world_view)
    frame = hud.render(frame, world,
                       frame_idx=world.frame,
                       contact_count=len(contacts))
    frames.append(frame)

renderer.save_gif(frames, Path("drop.gif"), fps=30)
```

For a one-call alternative, `render_world_gif(world, "drop.gif",
frame_count=90, fps=30)` wraps the loop above.

---

## 2. Architecture

The module pairs a **rigid bus** (one transform per body, stored as
SoA arrays on a `HullTree`) with a **per-pixel cell bus** (a fixed
`32×32×16` float32 grid per T2 hull, allocated from a `CellGridPool`).
Each frame: Velocity-Verlet integrates poses; a spatial-hash broadphase
+ Baraff/Witkin impulse resolves rigid contacts; the per-pixel kernel
substeps every active T2 hull's cell field (elasticity, plasticity,
brittle/ductile fracture, heat diffusion, fluid pressure projection);
`BoundaryExchange` conducts heat across body-body contact seams;
`spawn_fragment` runs connected-components on torn bonds and emits new
roots when a body splinters.

- **Hull tiers** — `TIER_T0` transform-only (no solver), `TIER_T1`
  analytic/reduced, `TIER_T2` full per-pixel (owns one cell-pool slot).
- **Cells** — 16 float32 channels per pixel: `u` (displacement), `v`
  (body-local velocity), plastic strain `xx/yy/xy`, pressure, damage,
  density, stretch, tear, heat, bond `n/e/s`. Layout shared between
  host, GPU, and the offline cache (`CELL_PIXEL_STRUCT`).
- **Rigid ↔ cell invariant** — the per-cell `v_local` field integrates
  to zero (linearly + angularly) in the body-local frame. Bulk motion
  lives on the rigid bus; the cell-velocity channel is deformation
  only. `PhysicsWorld._inject_local_velocity_field` enforces this.
- **GPU path** — indirect-dispatched WGSL kernel
  (`shaders/per_pixel_sim.wgsl`) with persistent residency. CPU path
  is a numpy shim that mirrors the WGSL kernel branch-for-branch.
- **Conservation** — mass / linear momentum / angular momentum / total
  energy are tracked through `world.conservation_totals()` and pinned
  by `test_conservation.py`.

---

## 3. Materials

Materials are the **source of truth** for every coefficient the kernel
multiplies into stress, strain, heat, and fracture. Swap a material to
swap the body's full mechanical character; the simulator never changes.

Resolve a material via `pharos_engine.deform_modes.cell_material_for(name)`
or pass the name string directly to `world.create_body(..., material=...)`.

| Name           | Character                                         | Key params |
|----------------|---------------------------------------------------|------------|
| `steel`        | Stiff, tough, dense alloy                         | `E=300, Y=0.30, brittle_modulus=2.5, restitution=0.55` |
| `iron`         | Softer than steel; dents readily                  | `E=200, Y=0.18, brittle_modulus=2.0` |
| `stone`        | Brittle masonry; cracks structurally              | `E=180, brittle_modulus=0.6, restitution=0.30` |
| `glass`        | Stiff and shatter-prone                           | `E=220, brittle_modulus=0.3, radial cracks` |
| `wood`         | Lightweight; grain-aligned cracks                 | `E=100, brittle_modulus=0.4, density_rho=0.7` |
| `rubber`       | Bouncy, grippy, never yields                      | `E=80, Y=999, restitution=0.85, μ_s=0.85` |
| `ice`          | Stiff + very brittle + frictionless               | `E=160, brittle_modulus=0.25, μ_k=0.03` |
| `mud`          | Viscous fluid; splashes but settles               | `is_fluid=True, viscosity=0.55, restitution=0.05` |
| `water`        | Canonical incompressible fluid                    | `is_fluid=True, E=10, frictionless` |
| `sand`         | Granular solid; disaggregates into a cloud        | `E=25, brittle_modulus=0.8, FRAGMENT` |
| `clay`         | Low stiffness; slow anneal back toward shape      | `E=40, remold_rate=0.01` |
| `lava` / `magma` | Self-emissive molten fluid                      | `is_fluid=True, initial_heat=12/18, radiance=8/12` |
| `concrete`     | Stiff, dense; fractures into rubble               | `E=250, brittle_modulus=0.5, density_rho=2.4` |
| `oil`          | Lighter-than-water highly viscous fluid           | `is_fluid=True, viscosity=0.45, density_rho=0.92` |
| `slime`        | Low-stiffness ductile; auto-repairs               | `E=20, remold_rate=0.05, RepairMode.AUTO` |
| `diamond`      | Effectively unfracturable                         | `E=600, brittle_modulus=12.0, restitution=0.85` |
| `paper`        | Light + very tear-prone                           | `tear_strength=0.3, tear_growth_rate=20` |
| `snow`         | Soft granular powder                              | `E=8, brittle_modulus=0.2, density_rho=0.3` |
| `gold`         | Very ductile heavy metal; dents profusely         | `E=180, density_rho=4.0, brittle_modulus=999` |

`list_materials()` returns the full registry; `register_material(name,
config)` adds a custom one.

---

## 4. Joints and constraints

Constraints run **after** `world.step()` as a separate position-based
projected Gauss-Seidel sweep (`ConstraintSolver`). They mutate only the
public rigid state on `HullTree` (position, velocity, angle, omega).
The solver respects `config.physics.constraints.enabled`.

```python
from pharos_engine.physics import (
    PhysicsWorld, make_circle_silhouette, make_rect_silhouette,
)
from pharos_engine.physics.constraints import (
    ConstraintSolver, PinConstraint, DistanceConstraint, WeldConstraint,
)

world = PhysicsWorld(world_bounds=(-200, -100, 200, 250))
chassis = world.create_body(make_rect_silhouette(60, 16),  "iron",   position=(0, 100))
wheel_l = world.create_body(make_circle_silhouette(20),    "rubber", position=(-20, 120))
wheel_r = world.create_body(make_circle_silhouette(20),    "rubber", position=( 20, 120))
turret  = world.create_body(make_rect_silhouette(20, 20),  "steel",  position=(0, 86))
strut_a = world.create_body(make_circle_silhouette(8),     "iron",   position=(-40, 90))
strut_b = world.create_body(make_circle_silhouette(8),     "iron",   position=( 40, 90))

solver = ConstraintSolver(iterations=4)
solver.add(PinConstraint(chassis, wheel_l, (-20, 12), (0, 0)))
solver.add(PinConstraint(chassis, wheel_r, ( 20, 12), (0, 0)))
solver.add(WeldConstraint(chassis, turret, (0, -8), (0, 8)))
solver.add(DistanceConstraint(strut_a, strut_b,
                              (0, 0), (0, 0), distance=80.0,
                              stiffness=1.0, break_strain=0.5))

for _ in range(120):
    world.step()
    solver.solve(world, world.config.world.default_dt)
    if solver.broken:
        for c in solver.broken:
            print("snapped:", c)
        solver.broken.clear()
```

| Constraint            | Locks                       | Break field            |
|-----------------------|-----------------------------|------------------------|
| `PinConstraint`       | Shared anchor point         | `break_force`          |
| `DistanceConstraint`  | Anchor-to-anchor distance   | `break_strain` (0..1)  |
| `WeldConstraint`      | Position **and** orientation| `break_force`          |

A constraint whose accumulated `last_impulse` exceeds its break
threshold is moved to `solver.broken` for game code to react to.

---

## 5. Configuration

All numeric defaults live in [`config/physics.yml`](../config/physics.yml).
`load_physics_config(path=None)` walks upward from the package to find
it; pass a preloaded `PhysicsYaml` into `PhysicsWorld(config=...)` to
override.

Top-level sections (each maps to a dataclass on `PhysicsYaml`):

| Section              | Purpose                                                                 |
|----------------------|-------------------------------------------------------------------------|
| `world:`             | `default_dt`, `substeps`, `gravity`                                     |
| `hull:`              | Capacities, tier promotion/demotion thresholds, settle frames           |
| `cell:`              | Per-cell kernel coefficients (CFL-sensitive)                            |
| `frontier:`          | Frontier-A* solver knobs                                                |
| `conservation:`      | Lagrange projection cadence, drift warning thresholds                   |
| `collision:`         | `contact_pair_max`, seam width                                          |
| `constraints:`       | `enabled`, `iterations` for `ConstraintSolver`                          |
| `gpu:`               | `enabled`, `debug_force_cpu`, `indirect_dispatch`, `persistent_residency` |
| `boundary_exchange:` | Cross-seam heat conduction (`enabled`, `strip_depth`)                   |
| `profile:`           | Hardware preset overlay — `desktop | mobile | web | high_end | auto`    |
| `memory:`            | Hard caps: `max_bodies`, `max_cell_pool_slots`, `max_particle_count`    |
| `media:`             | Default `fps`, `quality`, GIF palette size for `pharos_engine.media`     |

Apply a profile programmatically:

```python
from pharos_engine.physics import load_with_profile, PROFILE_MOBILE
world_yaml = load_with_profile(profile=PROFILE_MOBILE)
```

Enforce the `memory:` caps:

```python
from pharos_engine.physics import MemoryBudget
budget = MemoryBudget.from_config()
budget.check(bodies=len(world.bodies),
             cell_slots=world.cell_pool.in_use_count)
```

---

## 6. GPU vs CPU paths

The per-pixel kernel has two implementations behind the same world step:

- **CPU** (numpy shim in `world._cpu_substep`) — canonical reference;
  runs on every substep when no wgpu adapter is available or
  `gpu.debug_force_cpu = true`.
- **GPU** (WGSL `shaders/per_pixel_sim.wgsl`) — indirect-dispatched,
  persistent-residency upload path. Default-on (`gpu.enabled=true`,
  `gpu.indirect_dispatch=true`, `gpu.persistent_residency=true`).

Decision points:

- The GPU path is used when an adapter is available **and**
  `gpu.enabled` **and not** `gpu.debug_force_cpu`.
- The CPU path is verified bit-equivalent to the GPU path on the
  `solo_drop` regression (`test_gpu_silent_zero_regression.py`).
- Set `gpu.debug_force_cpu: true` in `config/physics.yml` to pin the
  CPU path for debugging.

Performance (RTX 3070 Ti, wgpu 0.31, 60-frame median):

- Indirect dispatch: **30-32% faster** on fluid/fracture scenarios,
  within noise on solo_drop / multi-body / idle_settled.
- Persistent residency: **7.6× faster on `fluid_pool`** (139.9 → 18.3
  ms), **6.2× faster on `fracture`** (18.6 → 3.0 ms), never slower.
- Headline medians from `benchmarks/run_benchmarks.py`: solo drop
  0.18 ms, fifty-body 7.83 ms, idle-settled 1.36 ms.

Profiling harness: `pharos_engine.physics.profile.run_benchmark(...)`
and `baseline_scenarios()`.

---

## 7. Limits and caveats

- **Fluid pressure: CPU multigrid vs GPU single-grid SOR.** The CPU
  path runs a multi-grid V-cycle (`pressure_multigrid.py`,
  `vcycle_project`); the WGSL kernel ships only a single-grid Red-Black
  SOR. Long-wavelength fluid modes converge faster on CPU than GPU on
  identical iter counts. WP-H tracks the V-cycle WGSL port.
- **Cell grid is fixed 32×32.** `subdivide()` / `coalesce()` /
  `spawn_fragment()` exist on `HullTree`, but the world loop does not
  yet drive subdivide automatically (called manually or by
  `FrontierSolver`).
- **Wall friction reads body μ only** (no per-wall material).
- **Single-light, single-cascade `ShadowPass`.** Multi-light variants
  not yet wired.
- **CCD primitives are advisory.** `predict_contact_pairs` /
  `swept_aabb_overlap` ship, but `PhysicsWorld.step` does not integrate
  CCD into its main loop — tunnelling is a possibility for very fast
  bodies; call CCD helpers manually if needed.
- **CFL auto-substep can dominate.** Stiff materials (`steel`,
  `diamond`) on small cells force 4-16 substeps per frame. Drop `E` or
  raise cell size if the budget breaks.
- **No SVGF / temporal reprojection in the per-pixel pass yet.**

---

## 8. Examples

Runnable demo lives in [`../SlapPyEngineExamples/examples/`](../SlapPyEngineExamples/examples/):

| File                                                       | Demonstrates                                  |
|------------------------------------------------------------|-----------------------------------------------|
| [`hello_physics.py`](../SlapPyEngineExamples/examples/hello_physics.py)         | Minimal physics scene drop                    |

---

## Engine integration

- `PhysicsEngineBridge(world, *, event_publisher=None, auto_publish_events=True)` — auto-forwards each frame's contacts to a `PhysicsEventPublisher` (lazily built) so `Physics.Contact/Impact/Fragment/Settled` events fan out on the global `EventBus` with no manual wiring.
- `PhysicsEngineBridge.dispose()` — releases wrappers, callbacks, and publisher state; auto-registered against `Engine.on_end` by `bind_to_engine()`.
- `physics.yml → events.impact_impulse_threshold` — tunes the auto-publisher's impact gate (default 1.0).

---

## See also

- [`architecture_overview.md`](architecture_overview.md) — engine-wide architecture.
- [`material_catalog.md`](material_catalog.md) — material catalog overview.
- [`per_pixel_sim_audit_2026_05_31.md`](per_pixel_sim_audit_2026_05_31.md) — per-pixel sim audit (Sprint 3E).
