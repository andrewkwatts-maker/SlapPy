# ParticleField — design notes

Captures what worked, what didn't, and the rationale for the Phase 1+2
foundation cleanup. Used to seed `slappyengine/physics/` v2.

## What worked (keep)

### Per-pixel solid mask
- `mask: (H, W, 4) uint8` — alpha = solid/empty.
- Supports overhangs and caves naturally (no heightmap assumption).
- Cheap to query (O(1) per particle per frame).
- Settled particles bake into it; carve clears alpha back to 0.
- **Keep verbatim**.

### Per-pixel companions
- `loose: (H, W) bool` — distinguishes baked particles from fixed
  terrain. Slump pass only touches loose pixels so original terrain
  doesn't migrate.
- `_fixed_mask: (H, W) bool` — companion to loose; set by
  `fill_ground`, cleared by `carve`.
- `material_grid: (H, W) int8` — per-pixel material id; enables
  layered terrain (mud-over-rock blasts give correct ejecta).
- **Keep, generalise into a `PixelField` dataclass with named
  channels**.

### Polygon fragments (FragmentShape + FragmentFamily)
- Hierarchical: Material → FragmentFamily → FragmentShape → polygon
  vertices.
- Polygon = unit-space CCW vertex list, rasterised via PIL.
- Derives roughness, area, radius_at(θ), kick_factor(θ).
- Six predefined shapes (CIRCLE, ROUGH, SHARD, BOULDER, FLAKE, BLOB).
- Seven predefined families with weighted shape choices.
- **Keep verbatim**; one of the cleanest pieces.

### KE-driven impact model
- `ke = 0.5 * radius² * (vx² + vy²)`.
- Above `binding_force` → drill / displace.
- Saturating dig: `dig_px = max_px * (1 - exp(-0.6 * (ke / binding)))`.
- Per-material `loose_ground_multiplier` boosts dig inside a crater.
- **Keep**; conceptually clean physics.

### Drill mechanic (bullets / high-velocity)
- Material gets `drill_max_px`, `drill_velocity_loss`, `drill_eject_gain`.
- DDA-walk along velocity, clear alpha pixels, lose KE per pixel,
  optionally spawn ejecta.
- **Keep**; a fundamentally separate path from settling.

### Region grid for static cells
- `RegionGrid` from `baked_terrain.py`: track per-cell live count, idle
  cells transition to STATIC and skip the live loop.
- Critical for large maps with lots of settled debris.
- **Keep**; widely useful.

### Original-pixel colour sampling
- `blast.detonate` samples mask RGB in the carved bowl BEFORE clearing.
- Ejecta particles inherit the ground's hue instead of a detached
  palette.
- **Keep**.

### Random per-particle timing (settle_jitter, rigidify_at)
- Particles don't all settle / rigidify on the same frame — natural
  organic feel.
- **Keep**; widen to thermal-driven rigidify in future.

### Velocity-aware landing
- Rising particles (vy < 0) skip mask collision; only falling particles
  check. Replaces the hacky no_collide_frames grace.
- **Keep**.

### Mass conservation by 1-pixel bake
- Each particle stamps a small polygon (≈ chunk size), not a bloated
  disc. Total bake mass = sum of particle stamp areas, predictable.
- **Keep**; root cause of the "pile 10x bigger than crater" bug.

## What didn't work (cut or refactor)

### 6 overlapping particle state fields
- `landed`, `settled`, `bake_flag`, `kinetic_age`, `rigidify_at`,
  `settle_age` — 6 fields, 4 actual states + 2 timing axes.
- Phase transitions implicit (mutate two fields at once, lots of
  `if landed & ~settled` etc).
- **Refactor**: single `phase: int8` enum + `phase_age: int32` +
  `rigidify_at: int32`. Phases: AIRBORNE, LANDED, SETTLING, BAKED.

### Material as a 40-knob god-object
- Mixes physics, kinetic, settle, bake, drill, fluid, shape concerns
  in one frozen dataclass.
- Defaults span 5 conceptual groups; hard to scan.
- **Refactor**: split into ~6 grouped sub-dataclasses, each with
  ~5 fields. Material composes them.

### _fluid_relax and _kinetic_relax duplicate the same algorithm
- Both: cell-bin particles by spatial hash, walk in-cell pairs, push
  apart within rest distance.
- Differ only in strength function and eligibility filter.
- **Refactor**: one `_pairwise_constraint(eligible_fn, rest, strength_fn)`.

### SplatterPreset legacy bloat
- 60+ fields, large overlap with new Material.
- Used as a "recipe to translate into Material + DetonateCurves" by
  `blast.material_from_preset` + `ensure_preset_material`.
- **Cut**; replace with `DetonationRecipe` that references Material
  by name + holds particle counts + curve overrides.

### Naive _fluid_relax (vs real PBF)
- The existing `slappyengine.fluid.pbf_step` is proper Macklin 2013
  with Rust kernels.
- My naive bin-and-push approach is a poor substitute.
- **Refactor**: bridge — fluid-material particles in ParticleField
  route through `pbf_step` each step.

### bake_radius derived from particle.radius - 1 (ad hoc)
- Mass calc tied to a magic offset.
- **Refactor**: explicit `MatBake.stamp_radius_range` per material,
  sampled per particle at spawn. Decouple visual airborne radius
  from bake stamp size.

### Slide-redirect that only sees ±1 cols, then ±5 cols
- Iterated tweaks without principle.
- **Refactor**: roll-downhill is a CA on the loose mask, run as
  part of slump, not as a slide hack.

## Open questions for v2

### PBF bridge architecture
- Each step: extract fluid subset → build FluidWorld with mask as
  collider → call `pbf_step` → write positions/velocities back.
- Cost: rebuilds FluidWorld every step.
- Alternative: keep a persistent FluidWorld, sync it with the
  ParticleField subset.
- TBD.

### Per-pixel temperature field
- Need a temperature_grid and per-particle temperature.
- Phase changes: snow → water above melt_temp; lava → rock below
  freeze_temp; water → ice below freeze_temp.
- Thermal sources (campfire, lava puddle) as "heat stamps" that
  diffuse into nearby pixels.
- Use existing `slappyengine.thermal` module? It already has heat
  diffusion math.

### Fragment-into-smaller-particles
- High-KE impact on can_fracture material → break the polygon into
  N smaller polygons + spawn them as new particles.
- Polygon decomposition algorithms: ear clipping for triangulation,
  Voronoi shatter for random splits.
- TBD — substantial new feature.

### Inter-particle collision (proper rigid-body)
- User asked for "particles can't stack on top of each other".
- Current approximation: pairwise push-apart relax.
- Proper solution: continuous broadphase + impulse-based collision
  with restitution.
- Cost: significantly more than pairwise relax.
- Decision: keep relax approximation; add a "settle delay" so
  particles jostle before baking. Real rigid-body is out of scope
  for now.

## Phase 1+2 scope

**Phase 1: State consolidation**
- `phase: int8` enum (AIRBORNE=0, LANDED=1, SETTLING=2, BAKED=3)
- `phase_age: int32` — frames in current phase
- `rigidify_at: int32` — timeout for kinetic→rigid (kept separate)
- One `_advance_phase()` method makes transitions explicit
- All existing logic adapted to phase queries

**Phase 2: Material grouping**
- `MaterialPhysics` — binding_force, cohesion, density, gravity_scale,
  air_drag, friction
- `MaterialKinetic` — fluidity, rigidify_frames_min/max,
  impact_stickiness, tumble_kick
- `MaterialSettle` — speed_threshold, jitter, slump_angle, mass_gain
- `MaterialBake` — stamp_radius_range, fragment_family, jagged
- `MaterialDrill` — max_px, velocity_loss, eject_gain
- `MaterialFluid` (Optional) — rest_distance, pressure_factor,
  iterations, surface_flow

Material composes them. Built-ins (WATER, SAND_MAT, etc.) construct
through helper builders for readability.
