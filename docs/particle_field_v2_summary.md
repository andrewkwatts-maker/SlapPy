# ParticleField v2 — sprint summary

What landed in this multi-hour refactor sprint, in commit order:

## Foundation

1. **Polygon `FragmentShape` + `FragmentFamily` hierarchy** —
   Material → FragmentFamily → FragmentShape → polygon vertices.
   Six predefined shapes (CIRCLE, ROUGH, SHARD, BOULDER, FLAKE, BLOB),
   seven families. Polygons rasterise via PIL scanline fill;
   `bake_mask_xy` supports non-uniform scaling for splat deformation.
2. **Per-pixel `material_grid`** alongside the RGBA mask. Layered
   terrain stays material-aware through carves.
3. **Per-material `render_mode`** (`discs` or `marching_squares`).
   WATER defaults to marching_squares; mixed scenes render some
   particles as pixels, others as iso-surface in one call.
4. **Visual regression demo** — `visual_check_demo.py` renders a
   1×5 grid for sand/mud/sloppy/rock/snow in 3 s. Used as the
   behaviour-check at each commit.
5. **Design notes** — `docs/particle_field_design.md` captures
   what worked, what to refactor, ideas to keep.

## Phase 1: state machine consolidation

Six implicit state fields (`landed`, `settled`, `bake_flag`,
`kinetic_age`, `rigidify_at`, `settle_age`) replaced with one
explicit `Phase(IntEnum)` (AIRBORNE / LANDED / SETTLING / BAKED)
+ `phase_age` + `_set_phase()` transition helper. Legacy bool
arrays kept as derived views so the 99 tests stay green.

## Parallel agent work (4 independent modules)

1. **`physics/blast.py`** — `detonate` samples `material_grid` so
   layered terrain (mud-over-rock) yields ejecta whose material
   matches each chunk's origin layer.
2. **`physics/splat.py`** — `SplatConfig` + `compute_splat`: maps
   impact velocity + current fluidity to a polygon (scale_x,
   scale_y, rotation) tuple. Standalone module, 8 tests.
3. **`physics/thermal.py`** — `ThermalProfile` per material,
   `step_temperatures` and `detect_phase_changes` functions,
   `TemperatureField` wrapping the existing `pharos_engine.thermal`
   HeatField. Standalone, 9 tests.
4. **`physics/fluid_bridge.py`** — `bridge_step` wraps the canonical
   PBF (`pharos_engine.fluid.solver.pbf_step`, Rust-accelerated) so
   ParticleField fluid materials use proper Macklin 2013 density
   relaxation instead of a naive substitute. Standalone, 4 tests.

## Integration

5. **Splat into the bake pipeline** — Material gains `splat_squash`,
   `splat_stretch`, `splat_fluidity_gate`. MUD set to (0.5, 0.4, 0.1);
   rock/snow stay at 0 (no deformation). `impact_vel` captured at
   landing in `_collide`. The bake builder picks splat-deformed
   masks for materials that have splat enabled.
6. **PBF bridge into `step()`** — `use_pbf_bridge=True` by default;
   fluid materials extract their subset, route through
   `bridge_step` (which handles mask collision via post-step
   projection), write positions/velocities back. The legacy
   `_fluid_relax` stays as a fallback.
7. **Thermal step into `step()`** — `_thermal_step` runs before the
   fluid path: per-particle temperature relaxation +
   detect_phase_changes flips `material_id` for crossings.
   SNOW melts to water in flight (visible in `visual_check.gif` —
   only 887/1450 snow particles settle as snow; the rest become
   water mid-flight and route through PBF).

## Per-particle SoA fields after this sprint

```
pos, vel              — position, velocity (float32 N×2)
material_id           — int32 (current material; can change on
                       thermal phase change)
radius                — airborne visual radius (float32)
bake_radius           — settled stamp size (int32)
color                 — current colour (uint8 N×3)
phase                 — int8 enum (AIRBORNE / LANDED / SETTLING / BAKED)
phase_age             — frames in current phase (int32)
landed, settled,
bake_flag             — derived bool views kept in sync by _set_phase
shape_idx             — index into material.fragment_family.shapes
shape_rotation        — random rotation per particle (float32)
kinetic_age           — frames since spawn (int32)
rigidify_at           — random kinetic→rigid timeout (int32)
settle_age            — stub (used by future settle-period work)
impact_vel            — velocity captured at landing (float32 N×2)
temperature           — current temperature in °C (float32)
```

## Per-pixel field state

```
mask                  — RGBA + alpha = solid (uint8 H×W×4)
material_grid         — material id per pixel (int8, -1 = unknown)
loose                 — settled-particle pixels eligible for slump
_fixed_mask           — pixels written by fill_ground, exempt from slump
```

## Test coverage at end of sprint

```
test_particle_field.py     34 pass
test_blast.py              13 pass
test_baked_terrain.py      10 pass
test_fragment.py           21 pass
test_splat.py               8 pass
test_thermal_physics.py     9 pass
test_fluid_bridge.py        4 pass
———————————————————————————————————
                          99 pass
```

## Deferred (won't do, with rationale)

- **Phase 2 Material grouping into sub-dataclasses** — would touch
  ~200 read sites for cosmetic cleanup. Material has 30+ fields but
  they're grouped by section comments which makes navigating easy
  enough. Future refactor if Material crosses 50 fields.
- **`SplatterPreset` removal** — still used by `blast.detonate` as
  the legacy recipe shape. Could be replaced by `DetonationRecipe`
  but the API works for now.

## Future work (recorded for handoff)

- Fragment fracture: split a polygon into N sub-polygons on high-KE
  impact. Voronoi or ear-clipping for the geometry.
- Per-pixel temperature_grid: would let lava puddles warm nearby
  fluid pixels.
- Proper rigid-body inter-particle collision (current pairwise
  push-apart is a relaxation approximation).
- Bridge to existing `pharos_engine.fluid` rendering (surface_mode,
  marching squares with refraction + godrays).

## Visual regression at end

`SlapPyEngineExamples/examples/output/particles/visual_check.gif` — 1×5 grid, 60 frames,
3 s render, ~1.2 MB. Compare against earlier commits' baselines to
spot behaviour drift. Stats at final commit:

```
sand   1013/1020  pile_max=95   crater_max=12
mud     893/900   pile_max=93   crater_max=10
sloppy  155/680   pile_max=88   crater_max=15  (long-airborne fountain)
rock    596/600   pile_max=95   crater_max=15
snow    887/1450  pile_max=100  crater_max=3   (563 melted → water)
```

The snow row in particular shows thermal phase change working end-to-end.
