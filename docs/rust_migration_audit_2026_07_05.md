# Rust Migration Audit — 2026-07-05 (FF4)

Docs-only sprint. This audit inventories every Rust kernel currently
shipped in the `_core` PyO3 extension, then walks the Python tree
looking for numpy-heavy / loop-heavy modules that would benefit from a
Rust backend. The ranking at the end feeds the next migration sprint.

Companion docs:

* `docs/rust_migration_plan.md` — original 7-step plan (Steps 1-6 shipped).
* `docs/rust_port_audit_2026_06_02.md` — the previous per-frame audit.
* `docs/cargo_audit_2026_06_02.md` — crate + wheel size housekeeping.
* Memory: `project_rust_migration_final_2026_05_26.md` — 18-kernel rollup.

---

## 1. Rust kernels already shipped

`src/*.rs` in the current tree. Two groups: modules wired via
`src/lib.rs` and always in the wheel (§1.1), plus files present in
`src/` whose `pyfunction`s are exported to Python at runtime via the
shipping `_core.cp313-win_amd64.pyd` even though `src/lib.rs` does not
`mod`-declare them (§1.2 — pre-existing tree-hygiene finding first
flagged in `rust_port_audit_2026_06_02.md` §1.2).

### 1.1 Tracked in `src/lib.rs`

| File | Purpose | PyO3 exports (top-level fns / classes) | Python caller |
|---|---|---|---|
| `src/hull.rs` | 2-D convex hull + bbox + pixel-edge sampling | `convex_hull` (`:5`), `bounding_box` (`:52`), `pixel_edge_points` (`:90`) | `compute/spatial.py`, `bvh_factory.py`, `physics/hull.py` |
| `src/ik_solver.rs` | 2-D FABRIK IK | `solve_ik` (`:56`), `compute_bone_lengths` (`:130`) | `animation/procedural.py` |
| `src/math.rs` | 2-D math primitives | `Vec2` (`:3`), `AABB` (`:60`) | `compute/pipeline.py`, math helpers |
| `src/node_compiler.rs` | Material-graph JSON → WGSL | `compile_node_graph` (`:272`) | `material/node_material.py`, `shader_gen.py` |
| `src/slap_format.rs` | LZ4 compress / decompress for `.slap` | `lz4_compress` (`:6`), `lz4_decompress` (`:14`) | `landscape.py`, `assets/` |
| `src/struct_layout.rs` | WGSL struct layout + generation | `compute_layout` (`:20`), `generate_wgsl_struct` (`:46`) | `struct_registry.py` |
| `src/tile_cache.rs` | LRU tile cache for streaming | `TileCache` (`:4`) | `landscape.py` |
| `src/physics.rs` | 3-D rigid-body world | `PhysicsWorld` (`:235`), `RigidBody` (`:88`), `BodyType` | `physics2/` |
| `src/sdf_collision.rs` | 3-D SDF push-out + overlap tests | `SdfCollider` (`:251`) | `bvh_factory.py`, `sdf_shapes.py` |
| `src/math_3d.rs` (feat `3d`) | 3-D math primitives | `Vec3`, `Vec4`, `Mat4x4`, `Quaternion` (`:9-297`) | 3-D pipeline, camera |
| `src/bvh.rs` (feat `3d`) | 3-D BVH build + queries | `BvhPrimitive`, `Bvh` (`:11-207`) | `bvh_factory.py` |
| `src/sdf.rs` (feat `3d`) | 3-D SDF scene primitives | `SdfPrimitive`, `SdfScene` (`:70-253`) | `bvh_factory.py` |
| `src/gi.rs` (feat `gi`) | Radiance cascade descriptor bookkeeping | `RadianceCascadeSystem`-descriptor class (`:33-152`) | `gi/cascade.py` |
| `src/ibl.rs` (feat `ibl`) | IBL cubemap SH coefficients | `SHProbe` (`:98-190`) | `lighting.py` |

### 1.2 Present in `src/` and exported by the shipping wheel, not `mod`-declared in `src/lib.rs`

These four files were added out-of-order (during the May 2026
migration cascades) and remain untracked in `src/lib.rs`. Their
symbols nevertheless show up in the built `_core.cp313-win_amd64.pyd`
because the wheel was baked from a working tree where
`mod softbody_solver; softbody_solver::register(m)?;` etc. were
present. Any clean `maturin develop` on the current commit produces a
wheel missing 20+ symbols — a build-reproducibility bug tracked in
`rust_port_audit_2026_06_02.md` finding F1.

| File | Purpose | PyO3 exports | Python caller |
|---|---|---|---|
| `src/raster.rs` | Software rasterisation (lines, disks, blur, composite, LUT/CA) | `rasterize_lines` (`:95`), `rasterize_circles` (`:245`), `box_blur_rgb` (`:310`), `alpha_composite_rgb` (`:441`), `post_process_rgb` (`:500`), `rasterize_textured_triangles` (`:740`) | `softbody/render.py`, `fluid/render.py` |
| `src/softbody_solver.rs` | XPBD constraint projection + broadphase | `project_distance_constraints` (`:115`), `apply_plasticity` (`:292`), `mark_breaks` (`:383`), `build_contact_pairs` (`:487`), `project_node_beam_contacts` (`:838`), `project_node_node_pairs` (`:1132`), `pharos_engine_step` (`:1942`) | `softbody/solver.py`, `softbody/collision.py` |
| `src/pbf_solver.rs` | PBF density solve + neighbour table + friction + thermal | `build_neighbour_table` (`:72`), `pbf_iter` (`:243`), `friction_pass_rs` (`:528`), `thermal_step_rs` (`:672`), `pbf_step_full` (`:1307`) | `fluid/solver.py`, `fluid/thermal_step.py` |
| `src/fluid_shader.rs` | Fluid surface polish passes (foam, godrays, isolines, etc.) | `turbulence_foam_rs` (`:66`), `refraction_warp_rs` (`:123`), `godrays_rs` (`:213`), `specular_pass_rs` (`:293`), `draw_droplet_tails_rs` (`:467`), `alpha_composite_hdr_rs` (`:543`), `post_process_hdr_rs` (`:586`), `rasterize_lines_hdr_rs` (`:691`), `surface_base_shade_rs` (`:750`), `speed_screen_rs` (`:979`), `sample_density_grid_rs` (`:1056`), `extract_isolines_rs` (`:1225`) | `fluid/render.py`, `fluid/surface.py` |

**Total shipped kernels**: 13 tracked modules + 4 orphaned = 17 files,
covering ~53 public symbols in the shipping wheel.

**Coverage summary**:

* Softbody: XPBD projection, plasticity, break, broadphase, contact,
  full step. Rust-saturated.
* Fluid: PBF iter + step + neighbour + friction + thermal + surface
  shading. Rust-saturated.
* Renderer: line / disk raster, box blur, composite, HDR post. Both
  softbody and fluid renderers dispatch to Rust.
* Geometry: hull, BVH, SDF collision, tile cache.
* Math: 2-D + 3-D primitives, matrix / quaternion.
* Asset I/O: LZ4 compress / decompress.
* Shader tooling: struct layout, WGSL generation, material-node
  compile.

---

## 2. Python hot paths without a Rust backend

Grepped per the sprint scope. For each: hottest function, throughput
if measured, migration difficulty, expected speedup based on prior
port ratios.

Difficulty scale:

* **LOW** — 3-5 days, single kernel, no dispatch table, no state
  copy back per frame.
* **MEDIUM** — 1-2 weeks, single subsystem, may need dispatch table
  or persistent state.
* **HIGH** — 2-3+ weeks, cross-module, needs pyo3 dataclass ABI
  bridge or float-precision contract review.

Speedup baseline: shipped ports so far returned 3-8× for numpy-heavy
kernels and 8-30× for pure-Python inner loops (see
`project_rust_migration_final_2026_05.md`).

### 2.1 dynamics/

| Module | Hottest function | Baseline | Difficulty | Est. speedup | Notes |
|---|---|---|---|---|---|
| `dynamics/world.py` | `World.step` (`:369`) — the outer XPBD loop | ~0.7 ms / rope-20 today; scales O(`solver_iterations × len(joints)`) with a Python frame per joint | HIGH | 5-10× | Draft plan exists in `docs/rust_port_plan_dynamics.md`. Needs `JointSpec` ↔ Rust dataclass ABI + a dispatch table for the 7 joint kinds. CPU bottleneck for ragdoll / vehicle rigs. |
| `dynamics/joint.py` | `resolve` (`:415`) dispatched over `_DISPATCH` table (`:404`) | Runs inside inner loop of `World.step`; ~7 branches per joint per iter | HIGH | included in `World.step` port | The seven `_resolve_*` handlers (distance / spring / weld / ball / hinge / motor / prismatic) collectively are the per-iter cost. Port them as Rust `match` on a `u32` `kind` tag. |
| `dynamics/humanoid.py` | `HumanoidRig.update` chain (683 lines total) | unmeasured; runs on every ragdoll body | MEDIUM | 3-5× | Pose-blending + limb IK dispatch; mostly composes existing `_core.solve_ik`. Migration payoff comes from removing the per-limb Python dispatch overhead. |
| `dynamics/ragdoll.py` / `rope.py` / `spring.py` | Constructor + per-step glue | Cold — one-shot at construction, per-step calls just forward to `World.step` | — | — | Should stay Python. |

### 2.2 numerics/

| Module | Hottest function | Baseline | Difficulty | Est. speedup | Notes |
|---|---|---|---|---|---|
| `numerics/__init__.py` | `_sor_sweep` (`:191`) | Module docstring documents 28.9 → 11.8 ms after numpy hardening; still names Rust port as next perf step | LOW-MEDIUM | 3-6× | Well-isolated 5-point stencil kernel. Already numpy-vectorised so gains are less than per-particle Python loops, but it's called `iters_per_level × 2 × levels` times per V-cycle → high call count. Also unblocks reuse from a future Eulerian fluid step. |
| `numerics/__init__.py` | `_restrict_2x2` (`:89`), `_restrict_mask` (`:105`), `_prolong_bilinear` (`:131`) | ~17% of a V-cycle | LOW | 5-8× | Trivial strided-slice operators; SIMD-friendly. |
| `numerics/__init__.py` | `_compute_residual` (`:249`) | fires once per level per V-cycle | LOW | 3-5× | Same 5-point stencil shape as `_sor_sweep`. Piggybacks on the same Rust translation. |

### 2.3 gi/ (radiance cascades, ReSTIR, SVGF)

| Module | Hottest function | Notes |
|---|---|---|
| `gi/cascade.py` | `RadianceCascadeSystem.dispatch` (`:73`) → `_pass_inject`/`_merge`/`_temporal`/`_apply` | GPU dispatch wrapper. All heavy work is inside WGSL compute shaders; Python only builds bind-groups + uniforms. **Not a Rust candidate** — Python is glue only. |
| `gi/restir.py` | `ReSTIRSystem.dispatch` | Same shape as cascade — GPU-dispatch glue. |
| `gi/svgf.py` | `SVGFSystem.filter` | Same — WGSL a-trous filter. |

**Verdict**: GI is entirely GPU. No Rust migration applies.

### 2.4 post_process/ (bloom W4, TAA W3, chain manifest X5)

Post-process passes are WGSL-shader dispatchers. The Python side
packs UBOs (`_ubo.py`, ~300 lines of `struct.pack`) and calls the
executor (`executor.py:20 _splice_runtime_params`, `PostProcessExecutor`).

| Module | Hottest path | Rust candidate? |
|---|---|---|
| `post_process/bloom.py` (864 lines) | `smooth_threshold` (`:44`) has a numpy fallback that reproduces the WGSL Lottes 2017 curve on the CPU for headless tests | **NO for the shipped path.** The runtime path is a WGSL shader on wgpu. The `smooth_threshold` CPU fallback is only exercised by unit tests. |
| `post_process/taa.py` (667 lines) | `TAA.resolve_numpy` — variance-clip YCoCg CPU fallback documented in `rust_port_audit_2026_06_02.md` §2 | **NO.** Same story. Fallback only, GPU path is WGSL. |
| `post_process/chain_manifest.py` (614 lines) | `apply_manifest` (`:556`), `topological_order` (`:223`), `_handle_*` dispatch table | **NO.** Chain manifest is authoring-time: parse YAML → topo sort → dispatch. Runs once at chain load. Cold per-frame. |
| `post_process/executor.py` | `_splice_runtime_params` (`:20`) + wgpu bind-group building | **NO.** Wgpu FFI plumbing. |
| `post_process/chain_baker.py` (488 lines) | `bake_chain` | **NO.** Runs once at build time (baked chain artifacts). |

**Verdict**: `post_process/` is a WGSL frontend. No Rust migration
applies.

### 2.5 visual_scripting/codegen.py (X1 fixed 8 bugs)

`codegen.py` (1236 lines) — `python_to_graph` (AST → graph) +
`graph_to_python` re-export from `codegen_python.py`. This runs at
authoring time (script save / load), not per frame. Cold.

**Verdict**: Not a Rust candidate — authoring only, and the hot work
is `ast.parse`, which is already C-implemented.

### 2.6 prefabs/preview_baker.py (BB6 renders PIL previews)

`PreviewBaker` (510 lines) — bakes 64×64 PIL previews for the editor
spawn menu. Called once per prefab at first-run scaffold time; the
result is checked into `python/pharos_engine/prefabs/baked/previews/*.png`.

**Verdict**: One-shot authoring pipeline. No Rust win.

### 2.7 ui/theme renderers (numpy fallback)

Three renderers with the same wgpu-first / numpy-fallback shape as
`wgsl_backgrounds.py`:

| Module | Hottest path | Notes |
|---|---|---|
| `ui/theme/washi_tape/renderer.py` | `render_tape` (`:475`) → `_FALLBACKS[style_id]` (per-style numpy pattern paint) | Renders 64×24-ish swatches for editor / theme previews. Currently baked once per theme change. |
| `ui/theme/page_linings/renderer.py` | `render_lining` — tileable pattern paint | Same shape. |
| `ui/theme/edge_strokes/renderer.py` | `render_stroke_border` / `bake_stroke_texture` | Four border strips per panel. |

**Verdict**: These already have both a **wgpu path** (preferred when
wgpu is present) and a numpy fallback. Migrating the numpy fallbacks
to Rust would help headless test runs but has near-zero per-frame
impact — they bake to texture once and the texture is reused. **LOW
priority.** Skip.

### 2.8 Hot Python found *outside* the sprint's scope list

Same as the previous audit, still open, still #1 ROI:

| Module | Hottest function | Baseline | Difficulty | Est. speedup |
|---|---|---|---|---|
| `physics/particle_field.py` (2243 lines) | `_slide` (`:1947`) | 63% of Scenario C (10 200 particles, 7.6 → 3.1 fps under workload bump); 37% of Scenario B | MEDIUM | 8-15× |
| `physics/particle_field.py` | `_collide` (`:1590`), `_drill_through` (`:1677`), `_slump_loose` (`:1122`) | ~14% Scenario B, ~9% Scenario C; `_slump_loose` is 32% Scenario A | MEDIUM | 6-12× |
| `physics/particle_field.py` | `_kinetic_relax` (`:1246`), `_fluid_relax` (`:1527`) | unmeasured, per-particle inner loop | MEDIUM | 5-10× |
| `physics/thermal.py` | `HeatField.step` | unmeasured; substeps ≥ 4 when coupling > 0.225 | LOW-MEDIUM | 4-8× |
| `topology/__init__.py` | `connected_components` (`:49`) | union-find inner loop is pure Python — cold today but fires on softbody fragmentation | LOW | 15-30× |
| `physics/cc_label.py` | `connected_components` | BFS on 32×32 grid; ~1 ms per fragmentation event | LOW | 10× |

These are re-asserted from the prior audit; nothing in the FF-batch
sprints removed them.

---

## 3. Migration priority ranking

Rank formula: **(estimated speedup × user-visible impact) ÷
difficulty**, where user-visible impact is scored 1 (headless test
only) to 5 (dominates a shipping demo's fps).

| # | Kernel | Speedup | Impact | Difficulty | Score | Comment |
|---|---|---|---|---|---|---|
| 1 | `particle_field.py:_slide` (`:1947`) | 10× | 5 (biggest single per-frame share) | MEDIUM | 25 | Same #1 pick as June audit. `docs/rust_port_audit_2026_06_02.md` names it. |
| 2 | `dynamics/world.py:World.step` + `joint.py:resolve` dispatch (`:415`) | 6× | 4 (ragdoll / vehicle / rope demos) | HIGH | 8 | Plan drafted at `docs/rust_port_plan_dynamics.md`. High but bounded. |
| 3 | `numerics/__init__.py:_sor_sweep` (`:191`) + `_restrict_*` (`:89, :105`) + `_compute_residual` (`:249`) | 4× | 4 (pressure projection every fluid frame once Eulerian ships) | LOW-MED | 16 | Well-isolated; module docstring already names it as next perf step. |
| 4 | `particle_field.py:_slump_loose` (`:1122`) | 8× | 4 (dominant on the 680-2365 particle Scenario A) | MEDIUM | 16 | Same shape as `_slide`; Amdahl-blocked behind it on big scenes. |
| 5 | `particle_field.py:_collide` (`:1590`) + `_drill_through` (`:1677`) | 8× | 3 | MEDIUM | 12 | Per-particle sweep DDA; branch-heavy. |
| 6 | `topology/__init__.py:connected_components` (`:49`) | 20× | 2 (only fires on fragmentation, not per frame) | LOW | 13 | Cheap port; ideal pyo3 target. Also unblocks `physics/cc_label`. |
| 7 | `physics/thermal.py:HeatField.step` | 6× | 3 (rises once fluid C4 thermal pass lands) | LOW-MED | 9 | Mirrors `numerics._sor_sweep` shape; free ride if `_sor_sweep` ports first. |
| 8 | `physics/cc_label.py:connected_components` | 10× | 2 | LOW | 10 | Same union-find shape as `topology.connected_components`. |
| 9 | `dynamics/humanoid.py:HumanoidRig.update` | 4× | 3 | MEDIUM | 6 | Composes `_core.solve_ik`; win comes from removing per-limb dispatch. |
| 10 | `particle_field.py:_kinetic_relax` (`:1246`) / `_fluid_relax` (`:1527`) | 6× | 3 | MEDIUM | 6 | Middle-tier; would follow `_slide` and `_slump_loose`. |

**Top 3 by score**: `_slide`, `numerics._sor_sweep`,
`_slump_loose`. The dynamics `World.step` port has higher user-visible
impact but its HIGH difficulty (and drafted-not-executed plan) pushes
it to #2 by score and #4 by pragmatic sprint-planning order.

---

## 4. Non-migrations — Python that should stay Python

Confirmed cold / authoring-only / GPU-glue paths from the audit. **Do
not migrate.**

* **Editor UI (Dear PyGui-bound)**: `ui/editor/`, `ui/theme/*/renderer.py`,
  `ui/editor/editor_undo.py`, `notebook_diary_page`, notebook editor
  panels. Tied to the DPG event loop; the per-frame work is DPG's
  render, not our Python.
* **Asset registration + config**: `assets/`, `asset_manifest.py`,
  `build/`, `build_gen.py`, `config.py`, `cli.py`, `tools/`,
  `content_encrypt.py`. All run at import / build / boot time.
* **Docs generation**: `docs_gen.py`. Runs offline.
* **GI GPU dispatchers**: `gi/cascade.py`, `gi/restir.py`, `gi/svgf.py`.
  All heavy work is inside WGSL compute shaders; Python only builds
  bind-groups. Confirmed by reading the four dispatch methods.
* **Post-process pipeline**: `post_process/*.py`. Every pass dispatches
  a WGSL shader; the `resolve_numpy` methods are headless-test
  fallbacks only.
* **Compute pipeline glue**: `compute/pipeline.py`, `compute/spatial.py`,
  `compute/library.py`. Already delegate to `_core.convex_hull` etc.
  where relevant.
* **Serialisation + validation**: `dynamics/serialize.py` (993 lines),
  every `_validation.py`, `dynamics/_validation.py`. Once per
  construction / save.
* **Visual scripting codegen**: `visual_scripting/codegen.py`,
  `codegen_python.py`. Runs at script save / load; `ast.parse` is
  already C.
* **Prefab preview baker**: `prefabs/preview_baker.py`. One-shot
  authoring at first-run scaffold; results are checked into
  `prefabs/baked/`.
* **Audio, event bus, input**: `audio.py`, `audio_runtime.py`,
  `event_bus.py`, `input.py`. Baseline v3 §"Hardening overhead audit"
  confirmed <1% frame budget.
* **Landscape / BVH factory / animation procedural**: already delegate
  to `_core.TileCache`, `_core.SdfScene`, `_core.solve_ik` and
  `_core.compute_bone_lengths` respectively.

---

## 5. Trade-offs

### Wheel size

Current shipping `_core.cp313-win_amd64.pyd` is ~798 KiB (release,
pre-strip; see `cargo_audit_2026_06_02.md`). Each additional Rust
module adds:

* ~20-60 KiB stripped-release for a straightforward kernel (raster,
  sor-sweep shape).
* ~80-150 KiB for a dispatch-table subsystem with 7 handlers
  (dynamics/joint).

Ports 1-8 in the ranking would land the wheel around 1.1-1.3 MiB —
still comfortably below the 5 MiB PyPI convention and dwarfed by the
`wgpu` wheel (~13 MiB).

### Cross-platform compile

The current build ships x86-64 Windows only. `maturin build` is
green per `cargo_audit_2026_06_02.md`. Any new module has to keep the
same portability profile:

* **`rayon`** — already a dep; parallel joins work on all three
  major platforms.
* **`wide` (SIMD)** — currently referenced only by the orphaned
  `pbf_solver.rs`. Portable across x86-64 + aarch64 (used by
  `pbf_solver` for its f32x4 inner loop). Adding it to `Cargo.toml`
  is safe.
* **`ahash` / `rustc_hash`** — proposed for the softbody broadphase
  hash-set. Both are pure Rust, no unsafe intrinsics beyond stable
  SIMD, portable.

No cross-compile blockers found for the top 10 ports.

### PyO3 version bump risks

Currently pinned at `pyo3 = "0.22"`. Notes:

* PyO3 0.22 → 0.23 API is stable for `#[pyfunction]` and `PyBuffer`
  — the two main tools every current kernel uses. The
  `Bound<'py, PyByteArray>` idiom used across `raster.rs` etc. is
  0.22 native, unchanged in 0.23.
* PyO3 0.23 → 0.24 tightens the GIL-token model (`Python<'py>` vs
  `Bound<'py, T>` lifetimes). Every existing kernel already uses
  the `Bound<'_, PyModule>` register signature so the migration is
  mechanical.
* Bump when a shipped kernel actively benefits (e.g. new `PyArray`
  ergonomics land) — not speculatively.

### Precision / determinism

The `rust_migration_plan.md` risk register documents the
float-summation-order regressions the softbody port hit. Any new port
inherits the same rule:

* Preserve `np.add.at` iteration order — never re-order via hash-set
  or unordered_map on writable-scatter paths.
* Add a regression test on the FIRST step that runs a canonical
  scene for N frames and pins a scalar (chassis x, particle centroid,
  V-cycle L2 residual) to a 1e-3 tolerance.
* For pressure / SOR: the checkerboard update is order-safe (red then
  black), so the Rust port is regression-free at the algorithm level.

### Dev-loop cost

Each port costs a `maturin develop --release` rebuild (~90 s clean,
~15 s incremental). The current build time on x86-64 Windows is
comfortable; adding 3-4 kernels next sprint bumps clean rebuild to
~110 s — still below the pain threshold.

---

## 6. Recommended sprint slate (executive summary)

Next perf sprint should batch:

1. **`_slide` port** — biggest single-kernel win in the tree. Deliver
   `src/particle_field.rs` with `slide_rs` + `column_top_lut` +
   `set_phase_rs`. Est. 1-2 weeks incl. regression tests.
2. **`numerics._sor_sweep` + `_restrict_*` + `_compute_residual`**
   port — smallest surface area, well-isolated, unblocks Eulerian
   fluid + inflated softbody pressure projection. Est. 3-5 days.
3. **`topology.connected_components` port** — cheapest fast-win; also
   unblocks `physics/cc_label`. Est. 2-3 days.

Combined: ~2 sprint-weeks of Rust work, projected engine-wide fps
lift of **1.5-2.2×** on the particle-heavy scenarios (Scenario A/B/C)
and ~1.3× on any scene that runs a V-cycle pressure solve. Dynamics
`World.step` deferred to a follow-up sprint since it needs the
drafted `rust_port_plan_dynamics.md` to be re-costed against current
`joint.py` (619 lines).

---

## 7. Cross-references

* `docs/rust_migration_plan.md` — 7-step plan (Steps 1-6 shipped).
* `docs/rust_port_audit_2026_06_02.md` — previous per-frame audit.
* `docs/cargo_audit_2026_06_02.md` — crate hygiene.
* `docs/rust_port_plan_dynamics.md` — drafted dynamics port plan
  (referenced from June audit; not read this sprint).
* `benchmarks/baseline_report.md` — per-scenario fps + hot-function
  frame-share numbers.
* Memory: `project_rust_migration_final_2026_05_26.md`,
  `project_architecture_pattern.md`.
