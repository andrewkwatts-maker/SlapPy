## Rust Port Audit — 2026-06-02

Read-only audit per architecture pattern *"Python = wrapper, Rust = engine; every hot path ports to Rust"* (memory note `project_architecture_pattern.md`).

**Deliverable:** classification of every per-frame kernel in the Python tree by Rust-migration status. No code changes were made.

**Method:**

1. Surveyed every `#[pyfunction]` / `#[pyclass]` / `#[pymodule]` in `src/`.
2. Inventoried the shipping `_core.cp313-win_amd64.pyd` (53 public symbols, see Section 1.2) and reconciled against `src/lib.rs`.
3. Grepped Python sources for `_core` / `_native_core` import sites (12 files use them today).
4. Cross-referenced `benchmarks/baseline_report.md` (six generations of data, latest 2026-06-01 v3) for per-frame CPU share.
5. Spot-read the six modules the user flagged plus the top-share kernels named in the baseline report.

---

### 1. Currently Rust-backed surface (`_core` exports)

#### 1.1 Tracked + registered in `src/lib.rs`

| Subsystem | `_core` symbol(s) | Source file |
|---|---|---|
| Spatial / hull | `convex_hull`, `bounding_box`, `pixel_edge_points` | `src/hull.rs` |
| IK | `compute_bone_lengths`, `solve_ik` | `src/ik_solver.rs` |
| Math (2D) | `Vec2`, `Vec4` | `src/math.rs` |
| Material graph | `compile_node_graph` | `src/node_compiler.rs` |
| Asset format | `lz4_compress`, `lz4_decompress` | `src/slap_format.rs` |
| Struct layout | `compute_layout`, `generate_wgsl_struct` | `src/struct_layout.rs` |
| Tile streaming | `TileCache` | `src/tile_cache.rs` |
| 3-D math (feature `3d`) | `Vec3`, `Mat4x4`, `Quaternion`, `AABB` | `src/math_3d.rs` |
| SDF (feature `3d`) | `SdfScene`, `SdfPrimitive` | `src/sdf.rs` |
| GI (feature `gi`) | (cascade / restir helpers — verify symbol list) | `src/gi.rs` |
| IBL (feature `ibl`) | (cubemap convolution helpers) | `src/ibl.rs` |
| Rigid-body 3-D | `PhysicsWorld`, `RigidBody`, `BodyType` | `src/physics.rs` |
| SDF collision | `SdfCollider` | `src/sdf_collision.rs` |

#### 1.2 Present in shipping `.pyd` but **NOT registered in tracked `src/lib.rs`**

The shipping `_core.cp313-win_amd64.pyd` exports **53 symbols**, but the committed `src/lib.rs` only references **13 modules** that account for ~30 of those. The 23-symbol gap is provided by four **untracked** source files (`git ls-files --others --exclude-standard src/`):

| Untracked file | Symbols (`_core.*`) | Used by |
|---|---|---|
| `src/raster.rs` | `rasterize_lines`, `rasterize_circles`, `rasterize_lines_hdr_rs`, `rasterize_textured_triangles`, `box_blur_rgb`, `alpha_composite_rgb`, `alpha_composite_hdr_rs`, `post_process_rgb`, `post_process_hdr_rs` | `softbody/render.py`, `fluid/render.py` |
| `src/pbf_solver.rs` | `pbf_step_full`, `pbf_iter`, `build_neighbour_table`, `friction_pass_rs` | `fluid/solver.py` |
| `src/softbody_solver.rs` | `slappyengine_step`, `project_distance_constraints`, `project_node_beam_contacts`, `project_node_node_pairs`, `build_contact_pairs`, `apply_plasticity`, `mark_breaks` | `softbody/solver.py`, `softbody/collision.py` |
| `src/fluid_shader.rs` | `surface_base_shade_rs`, `turbulence_foam_rs`, `refraction_warp_rs`, `specular_pass_rs`, `godrays_rs`, `speed_screen_rs`, `draw_droplet_tails_rs`, `sample_density_grid_rs`, `extract_isolines_rs`, `thermal_step_rs` | `fluid/render.py`, `fluid/surface.py`, `fluid/thermal_step.py` |

> **Finding F1 (CRITICAL, deferred — pre-existing condition):** The shipping wheel was built from a working tree where these files were `mod`-declared and `register`-called. The current committed `src/lib.rs` would produce a wheel missing all 23 symbols, so the next `maturin develop` from a clean checkout will break `slappyengine.fluid`, `slappyengine.softbody`, and the renderers. This is not a port — it is a tree-hygiene bug. Recommend reading the orphaned files and either tracking them or recovering the working binary's `lib.rs` from the wheel's metadata. Out of scope for this audit; flagged for next sprint as **build-reproducibility hotfix**.

---

### 2. Reference Python paths kept for parity testing (OK to remain)

Confirmed-acceptable Python implementations that intentionally shadow a Rust kernel:

| Module | Python symbol | Mirror in Rust | Rationale |
|---|---|---|---|
| `softbody/solver.py` | `_xpbd_step_numpy` | `_core.slappyengine_step` | golden reference for `SlapPyEngineTests/tests/test_softbody_numerics_parity.py` |
| `physics/particle_field.py` | `_kinetic_relax_legacy` | (no Rust yet; vectorised `_kinetic_relax` is the live path) | kept for parity in commit `8b53890` |
| `post_process/taa.py` | `TAA.resolve_numpy` | WGSL shader dispatch (not `_core`) | CPU fallback for headless test grids |
| `numerics/__init__` | `vcycle_poisson`, `sor_smooth`, `compute_residual` | (no Rust yet — see ROI table) | pure-numpy V-cycle is the *only* path today |
| `topology/__init__` | `connected_components`, `connected_components_grid` | (no Rust yet) | pure-numpy union-find; only path |
| `zones/__init__` | `ZoneManager._update_linear_scan` | (no Rust; spatial hash is also Python) | only path, but cold (see Section 4) |

The first three are healthy: the live engine path is Rust, the numpy is an explicit `_numpy`/`_legacy` reference. The bottom three look "fine" today but are full per-frame paths with no Rust counterpart — they are the live hot paths in their subsystem and should migrate (see Section 3).

---

### 3. Hot Python paths that should migrate (ranked by ROI)

ROI rank = `(measured per-frame ms × invocation frequency × scenario count it dominates) ÷ port-effort weeks`. ms numbers are quoted from `benchmarks/baseline_report.md` 2026-06-01 v3 unless flagged otherwise.

| Rank | Kernel | Module / function | Frame-share (latest baseline) | Est. Rust speedup | Port effort | Notes |
|---|---|---|---|---|---|---|
| **1** | `_slide` | `physics/particle_field.py:1947` (Particle pile cellular automaton) | **63 %** of Scenario C (10 200 particles, 7.6 fps → **3.1 fps** after workload bump) and 37 % of Scenario B (4 710 particles, 8.7 fps) | 8-15× (per-particle Python branch-heavy DDA-style loop → branch-predictable Rust) | medium (1-2 weeks; needs `_column_top`, `_set_phase`, RNG round-trip) | Single biggest per-frame share of any Python function in the engine. Memory says we want `_slide` next per `project_perf_render_2026_05.md` follow-up. |
| **2** | `World.step` (dynamics XPBD) | `dynamics/world.py:369` + `dynamics/joint.py` `resolve()` dispatch table | (not in particle baseline) ~0.7 ms / rope-20 today (stable tripwire), but scales O(`solver_iterations × len(joints)`) with a per-joint Python frame inside the inner loop | 5-10× (predicted by `docs/rust_port_plan_dynamics.md`) | medium-large (2-3 weeks; 7 joint kinds, plus Python `Joint` dataclass↔Rust ABI) | Plan already drafted in `docs/rust_port_plan_dynamics.md`. The CPU-side bottleneck for ragdolls / vehicle bodies. |
| **3** | `_collide` + `_drill_through` + `_slump_loose` (particle field) | `physics/particle_field.py:1590` / `:1677` / `:1122` | combined ~14 % Scenario B, ~9 % Scenario C; `_slump_loose` also dominates Scenario A at **32 %** | 6-12× (per-particle Python loops with sweep DDA + cellular automaton) | medium (each ~1 week) | These are next-tier targets after `_slide`. `_slump_loose` is Amdahl-blocked behind it on big scenes but is the #1 share on the small (680-2365 particle) scene. |
| 4 | `numerics.vcycle_poisson` (`_sor_sweep`, `_restrict_*`, `_prolong_bilinear`) | `numerics/__init__.py` | not in particle baseline, but the module docstring documents 28.9 → 11.8 ms wins from numpy edits and explicitly names "Rust port of `_sor_sweep` + `_restrict_*`" as the next perf step | 3-6× (numpy is already vectorised; Rust gains less than per-particle loops) | small-medium (1 week; well-isolated stencil kernels) | Sets up `slappyengine.numerics` as a Rust-backed kernel library reusable by future Eulerian fluids and the pressure-projection rewrite. |
| 5 | `topology.connected_components` | `topology/__init__.py:49` | unmeasured (only fires on softbody fragmentation events); union-find inner loop is pure Python `for k in range(n_edges)` | 15-30× (tightest Python inner loop — the ideal pyo3 target) | small (3-4 days) | Cold today but ROI per port-day is excellent; also unblocks faster `physics/cc_label` legacy path. |
| 6 | `thermal.HeatField.step` | `thermal/__init__.py:211` | unmeasured in current benchmarks; documented to substep when `coupling > 0.225` (≥ 4 sub-steps per 60 Hz frame at α·dt·k = 1) | 4-8× | small (2-3 days; mirrors `numerics._sor_sweep` structure) | Will dominate when fluid C4 thermal pass goes live (memory `project_sprint_2026_05_29.md` — held pending). |

#### Not on the rank because they're cold

* `zones.ZoneManager.update` — spatial-hashed; `_update_spatial_hash` runs O(entities + zones·cells) in Python but typical scenes have ≤ 64 entities and ≤ 32 zones → < 0.1 ms / frame even pessimistically.
* `dynamics.World._check_overdamping` — once-per-step set lookup; cheap and intentionally process-throttled.
* `physics.cc_label.connected_components` — BFS on a 32×32 grid; fires only on fragmentation, ~1 ms when it does.

---

### 4. Cold Python (OK to remain — config / setup / authoring)

The following Python is correctly Python — it runs at authoring time, scene load, or rarely-fires events. **Do not migrate.**

* `assets/`, `build/`, `cli.py`, `config.py`, `tools/` — all config/scaffolding.
* `ai/`, `editor/`, `ui/editor/` — UI and dev-loop tooling.
* `material/node_material.py`, `shader_gen.py`, `shader_binding.py` — already delegate the compile to `_core.compile_node_graph` / `_core.generate_wgsl_struct`; the wrapper is glue.
* `dynamics/serialize.py`, `dynamics/_validation.py`, all `_validation.py` modules — once-per-construction.
* `gi/cascade.py`, `gi/restir.py`, `gi/svgf.py` — GPU dispatch wrappers; the heavy work runs in WGSL not Python.
* `post_process/*.py` — every pass dispatches a WGSL shader. The `resolve_numpy` methods (only `taa.py` currently has one) are headless-test fallbacks.
* `gpu/*.py` — wgpu plumbing; the heavy work is on the device.
* `compute/pipeline.py`, `compute/spatial.py` — already delegate (`_core.convex_hull`) where it matters.
* `audio_runtime.py`, `audio.py`, `event_bus.py` — already validated as < 1 % of frame budget in baseline v3 §"Hardening overhead audit".
* `landscape.py` — uses `_core.TileCache`; the per-tile work is Rust.
* `bvh_factory.py` — delegates to `_core.SdfScene` when available.
* `animation/procedural.py` — delegates to `_core.compute_bone_lengths` / `_core.solve_ik`.
* `softbody/*`, `fluid/*` — already Rust-migrated per `project_rust_migration_final_2026_05.md`; the Python here is per-frame glue, parity-test scaffolding (`solver.py` kept `_xpbd_step_numpy`), and authoring helpers. Confirmed by grep: 19 `_native_core.*` call sites across these two subpackages — they are the engine's most Rust-saturated subsystems.

---

### 5. Top 3 ROI picks (executive summary)

1. **`_slide` (particle pile CA)** — sole biggest per-frame win available; 63 % of Scenario C goes here today. A 10× Rust port roughly doubles end-to-end fps on the largest particle scene.
2. **`dynamics.World.step` + joint resolver** — already has a drafted Rust plan (`docs/rust_port_plan_dynamics.md`); the per-joint Python frame inside an `iters × n_joints` loop is exactly the shape Rust eats for breakfast. Unlocks vehicle / ragdoll bodies above their current solver-iteration ceiling.
3. **`numerics.vcycle_poisson`** — small surface area, well-isolated kernels, the module docstring already names it as the next perf step. Establishes `slappyengine.numerics` as a Rust kernel library before the Eulerian fluid step lands and starts calling it every frame.

The three together: ~1 sprint of audit-validated, baseline-instrumented Rust work; net engine-wide fps lift estimated at **1.8-2.3×** on the heaviest scenarios.

---

### 6. Cross-references

* `docs/rust_port_plan_dynamics.md` — pre-existing drafted plan for ROI pick #2.
* `docs/rust_migration_plan.md` — original 7-step plan; steps 1-4 landed per memory `project_rust_steps_1_4_2026_05.md`; steps 5-7 cover what this audit re-confirms is still open.
* `benchmarks/baseline_report.md` — primary evidence base; six refresh cycles since 2026-05-31.
* `memory/project_rust_migration_final_2026_05.md` — last full pass; says "18 Rust kernels". Shipping `_core` count today is 53 public symbols (some are classes / methods, not standalone kernels); the count discrepancy is explained by Section 1.2's untracked sources.
* `memory/project_architecture_pattern.md` — the directive this audit serves.

---

**Constraint compliance:**

* No edits to `python/slappyengine/softbody/` or `python/slappyengine/fluid/` (verified — both are already Rust-backed and only spot-read).
* No source-code ports performed — this is a read-only audit + one markdown commit.
* No migration without explicit user approval per item.
