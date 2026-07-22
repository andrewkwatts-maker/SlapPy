# WIP Subpackages Deferral — 2026-07-08 (AAA5)

Formal disposition doc for v0.4.0 ship-gate #11 ("softbody / fluid /
physics / physics2 WIP dirs committed or deferred"). Landed by AAA5
after the user answered VV7's ship-decision Q3 verbatim: **"Keep frozen
with docs deferral."**

This flips gate #11 from **FAILING** (uncommitted WIP work blocks
v0.4.0 tag) to **DEFERRED** (WIP work stays out of tree; wheel ships
without the subpackages; users install `pharos-engine==0.4.0` and get
a fully functional engine minus these four experimental modules).

Docs-only — no source is touched. No WIP subpackage lands in the
v0.4.0 wheel.

---

## 1. User decision (2026-07-08)

Verbatim record of the answer to VV7's Q3 ("gate #11 disposition")
solicited in `docs/v0_4_ship_decision_2026_07_07.md` § 8:

> **"Keep frozen with docs deferral."**

Interpretation:

* Do **not** land the four WIP subpackage trees into master before the
  v0.4.0 tag.
* Do **not** ship the four subpackages inside the v0.4.0 wheel.
* Do **not** delete them from the working tree either — they represent
  in-flight design work the user intends to reconcile in later minor
  cycles.
* **Do** record the disposition in a durable doc (this file) so future
  agents don't re-open the freeze question every sprint tick.
* **Do** point developers who want to try the WIP branches at a
  clone-and-copy path (§ 6) since none of the four modules are
  importable from a pip install.

---

## 2. What is frozen

Four Python subpackage trees + four Rust source modules are held out
of the v0.4.0 wheel. All appear as `??` (untracked) under `git status`
as of commit `c758122` (2026-07-08).

### 2.1 `python/pharos_engine/softbody/`

**Contents**: BeamNG-style soft-body lattice XPBD solver — 10 modules
(`__init__.py`, `beam.py`, `body_builders.py`, `collision.py`,
`material.py`, `node.py`, `render.py`, `solver.py`, `vehicle.py`,
`world.py`).

**History**: Started as the successor sprint-track to
`pharos_engine.dynamics.SoftBodyWorld` (which shipped in v0.3 and
remains the supported soft-body surface). The `softbody/` subpackage
adds:

* Explicit `BeamSoA` structure-of-arrays layout for the beam pool.
* `body_builders.make_lattice_body` + `make_layered_creature`
  authoring helpers (lattice topology + layered skin/muscle/bone).
* `SpatialHash` collision + `build_contact_pairs` /
  `project_contact_pairs` / `resolve_contacts` XPBD contact projection.
* `vehicle.py` vehicle-body factory (BeamNG-style chassis with
  suspension mount points).
* `render.py` diary-styled particle+beam renderer.

Rust pair: `src/softbody_solver.rs` (2200 lines).

### 2.2 `python/pharos_engine/fluid/`

**Contents**: Position-Based Fluids (PBF) 2D particle simulator —
12 modules (`__init__.py`, `buoyancy.py`, `contact.py`, `kernels.py`,
`material.py`, `particle.py`, `render.py`, `solver.py`, `surface.py`,
`thermal_step.py`, `world.py`).

**History**: Sibling sprint to `softbody/` — PBF (Macklin & Müller
2013) built on top of the same XPBD substrate so `softbody/` and
`fluid/` share contact projection. Public surface:

* `FluidWorld` container + `FluidMaterial` / `MATERIALS` / `WATER`.
* `ParticleSoA` particle block.
* `pbf_step` per-frame integrator (density constraint + XSPH viscosity
  + surface tension).
* `project_fluid_softbody_contacts` cross-solver bridge (fluid ↔
  softbody).
* `apply_fluid_buoyancy` per-node Archimedes upthrust.
* `FluidRenderer` filled-disc + halo particle renderer.

Rust pair: `src/pbf_solver.rs` (1509 lines) + `src/fluid_shader.rs`
(1319 lines).

### 2.3 `python/pharos_engine/physics/`

**Contents**: Hierarchical-hull per-pixel physics prototype —
30 modules including `body.py`, `hull.py`, `cell.py`,
`particle_field.py`, `particle_gpu.py`, `particle_graph.py`,
`splat.py`, `splatter_presets.py`, `boundary_exchange.py`,
`broadphase.py`, `cc_label.py`, `ccd.py`, `constraints.py`,
`debug_hud.py`, `event_publisher.py`, `fluid_bridge.py`,
`fragment.py`, `frontier.py`, `memory_budget.py`, `post_process.py`,
`pressure_multigrid.py`, `profile.py`, `profiles.py`, `render.py`,
`scene_loader.py`, `shadows.py`, `thermal.py`, `video.py`,
`world.py`, `baked_terrain.py`, `blast.py`, plus a `shaders/` WGSL
tree.

**History**: The oldest of the four WIP trees. Original per-pixel
materials-simulation prototype from the 2025 Q4 arc (nested hulls
with √2 layers, state-disagreement subdivision criterion, transforms
at hull level — see `docs/materials_hierarchical_hulls` memory entry).
Long superseded by `pharos_engine.physics3_bridge` (LL7 landing,
BVH-accelerated 3D via wgpu + `_core.bvh`) for downstream games.
Retained on disk as an archival artefact for anyone who wants to
resume the per-pixel arc; not maintained.

Reference doc `docs/physics_module.md` describes the design intent
but points at the (frozen, un-shipped) tree.

Rust pair: none directly — `src/physics.rs` is a tracked module that
covers the shipped physics3_bridge path.

### 2.4 `python/pharos_engine/physics2/`

**Contents**: One file — `material.py` (`Material2` dataclass with
density / stiffness / viscosity / plasticity_rate / fracture_strain /
melt_temperature / YAML round-trip).

**History**: Second-generation scratch pad for the physics rewrite —
intended to be the successor to `physics/` with a cleaner material
catalog and a smaller module surface. Was started but never grew
past the material dataclass. Effectively a placeholder for future
consolidation with `dynamics` + `physics3_bridge` under a single
per-pixel-optional dispatch layer.

### 2.5 Rust source modules

Four `src/*.rs` files are untracked and correspond to the WIP
subpackages above:

| Module | Lines | Pairs with |
|---|---|---|
| `src/raster.rs` | 915 | Currently orphan — was raster kernels for the physics/ per-pixel renderer; overlaps functionality now in `_core.raster`. |
| `src/pbf_solver.rs` | 1509 | `python/pharos_engine/fluid/` |
| `src/fluid_shader.rs` | 1319 | `python/pharos_engine/fluid/` (WGSL surface shading) |
| `src/softbody_solver.rs` | 2200 | `python/pharos_engine/softbody/` |

None are declared in `src/lib.rs` (PP3 audit confirms 14 `mod`
declarations vs 14 tracked `src/*.rs` files; the four modules above
are the F1 "untracked but scoped to gate #11" set). `cargo check` +
`cargo test` stay green because the untracked files are not compiled.

---

## 3. Why frozen

The user has WIP work-in-progress that has not been reconciled with
the engine's shipped stack. Each subpackage lacks the four
production-readiness artefacts required for a public ship:

1. **Signed-off commits from the user** — none of the four trees has
   ever been committed to master. The initial commits would encode
   design decisions the user has not yet fixed (material catalog
   layout, XPBD substep budget, PBF density-constraint iteration
   count, per-pixel struct layout — the same decisions that stalled
   the earlier per-pixel arc).
2. **Regression test coverage from engine perspective** — no
   `PharosEngineTests/tests/test_softbody_*.py` /
   `test_fluid_*.py` / `test_physics_*.py` / `test_physics2_*.py`
   suite exists. Landing without tests would mean an entire subpackage
   ships with zero tripwire coverage; a downstream breakage would go
   undetected until a game team hit it.
3. **Documentation** — reference docs `docs/softbody_design.md`,
   `docs/fluid_design.md`, `docs/physics_module.md`,
   `docs/material_catalog.md` describe the intended design surface but
   are written against the shipped `dynamics` fallback. No user-facing
   quickstart / API-ref lands would be truthful before the modules
   themselves stabilise. `docs/api/README.md` § "WIP subpackages" (line 88+)
   already documents that no `docs/api/softbody.md` /
   `docs/api/fluid.md` / `docs/api/physics.md` / `docs/api/physics2.md`
   will be produced during the freeze — a policy decision this doc
   formalises.
4. **Cross-subsystem integration testing** — the Ochema Circuit +
   Bullet Strata game-compat tripwire (gate #12, YY3 = 91.8% F1) is
   run against the *shipped* engine surface. Landing four uncovered
   subpackages after the tripwire runs would invalidate the recovery
   arc's evidence — a downstream game could import `pharos_engine.fluid`
   and blow up in a way YY3's data never caught.

All four gaps close together the day the user runs a landing sprint;
until then the trees are inert on disk.

---

## 4. Impact on v0.4.0 users

**Zero impact.** The engine ships and works without the WIP
subpackages. Concretely:

* `pip install pharos-engine==0.4.0` installs the wheel built from
  the tracked source tree. `git ls-files` = the wheel manifest set;
  untracked WIP dirs never enter the wheel.
* Physics-adjacent public surfaces users depend on today are covered
  by shipped subpackages:
  * Soft-body / rope / ragdoll → `pharos_engine.dynamics.SoftBodyWorld`
    + `Body` + `JointSpec` + `build_*` / `make_*` helpers
    (see `docs/api/dynamics.md`).
  * 3D rigid physics → `pharos_engine.physics3_bridge`
    (see `docs/api/physics3_bridge.md`).
  * 2D top-down / iso combat → `pharos_engine.iso.combat`
    (Stone Keep-tested; see `docs/api/iso.md`).
  * Post-process, GI, materials, numerics, thermal — all shipped and
    surfaced in `pharos_engine.__all__` (see `docs/engine_surface_v030.md`).
* No import path in the shipped `pharos_engine` namespace resolves to
  a WIP subpackage. `import pharos_engine.softbody` /
  `import pharos_engine.fluid` / `import pharos_engine.physics` /
  `import pharos_engine.physics2` all raise `ModuleNotFoundError`.
  Downstream games that were previously touching those namespaces
  (Ochema Circuit did briefly touch `pharos_engine.softbody` — see
  AA3's `docs/diary_softbody_bridge_2026_07_04.md`) already have a
  shim path via `pharos_engine.dynamics.SoftBodyWorld`.
* Engine feature-map (`docs/feature_map_2026_06_03.md` + deltas
  through `feature_map_delta_2026_07_17.md`) does not depend on any
  WIP row; no WIRED count regresses.

Users installing v0.4.0 from PyPI see a fully functional engine.
The freeze is invisible to them.

---

## 5. Roadmap for un-freezing

Each WIP tree carries a target minor version for the un-freeze
landing sprint. Targets are advisory — the user retains the freeze
directive until an explicit un-freeze commit lands per subpackage.

| Subpackage | Target version | Landing scope |
|---|---|---|
| `python/pharos_engine/softbody/` | **v0.5** | Paired with a new physics reconcile sprint that harmonises `softbody/` with the shipped `dynamics.SoftBodyWorld` — likely by promoting `softbody/` to the canonical XPBD substrate and thinning `dynamics.SoftBodyWorld` to a compatibility alias. Full test-suite + `docs/api/softbody.md` refresh. |
| `python/pharos_engine/fluid/` | **v0.5** | Sibling landing to `softbody/` since the two share XPBD contact projection. Ships together as the paired "rebuilt 2D physics layer" milestone. `src/pbf_solver.rs` + `src/fluid_shader.rs` land into `src/lib.rs` `mod` declarations at the same commit. Full test-suite + `docs/api/fluid.md` refresh. |
| `python/pharos_engine/physics/` | **v1.0 — marked for removal** | The hierarchical-hull per-pixel prototype is superseded by `pharos_engine.physics3_bridge`. Target disposition is deletion (not un-freeze) unless the user revives the per-pixel arc explicitly. Retained on disk for archival read-only reference until the v1.0 tag sprint. |
| `python/pharos_engine/physics2/` | **v0.6** | Successor to `physics/` — needs actual solver + test coverage before it becomes a shipped subpackage. Currently one dataclass file; needs to grow into a real Rust-backed per-pixel dispatch layer paired with `_core.raster` or `src/raster.rs`. If growth stalls again, target flips to "delete" alongside `physics/` at v1.0. |

Rust source modules follow their Python pair: `src/softbody_solver.rs`
+ `src/pbf_solver.rs` + `src/fluid_shader.rs` land at v0.5.
`src/raster.rs` targets deletion at v1.0 unless `physics2/` grows into
the surface that would consume it.

Un-freeze pre-flight checklist (per subpackage):

1. User commits the tree with a signed-off commit message.
2. Engine-side tripwire tests land in `PharosEngineTests/tests/`.
3. `docs/api/<pkg>.md` written (template `docs/api/_template.md`).
4. `docs/api/README.md` migrates the row from "WIP subpackages" to
   "Shipped subpackages WITH references".
5. Ochema Circuit + Bullet Strata game-compat tripwire re-runs to
   confirm no regression.
6. Feature map delta row added.
7. Rust pair (if any) declared in `src/lib.rs`.
8. `docs/sprint_5_doc_inventory.md` picks up the new API ref.

---

## 6. How to try WIP subpackages if you're bold

Developers who want to check out the WIP branches for research /
experimentation / porting into their own project can do so at their
own risk. There is no PyPI path; the modules do not ship in wheels.

Steps:

1. **Clone the repo** (not `pip install`):
   ```
   git clone https://github.com/<owner>/SlapPyEngine.git
   cd Pharos Engine
   git checkout <sha-of-interest>
   ```
2. **Copy the subpackage into your own project**:
   ```
   cp -r python/pharos_engine/softbody /path/to/your/project/vendor/softbody
   # ...or fluid / physics / physics2 as needed
   ```
3. **Import from your vendor path**, not from `pharos_engine`:
   ```python
   from vendor.softbody import SoftBodyWorld  # your copy
   # NOT: from pharos_engine.softbody import ...  # will fail on pip install
   ```

**No warranty.** The trees:

* May not work with any tagged version of `pharos-engine` on PyPI —
  they read/write internal APIs that pip-installed users cannot see.
* May be reorganised, renamed, or deleted between commits without a
  deprecation cycle. The `docs/backcompat_contract_2026_07_07.md`
  STABLE promise does **not** cover WIP subpackages.
* May fail to import on some Python versions if they touch internal
  `_core` PyO3 surface that is version-locked.
* May depend on the untracked Rust source files (`src/raster.rs` etc.)
  — if you want the Rust-accelerated paths you must run
  `maturin develop` against a full clone; the shipped `_core` wheel
  does not include those kernels.

If you are a game team porting away from an internal fork, prefer the
un-freeze roadmap in § 5 over the vendor-copy path — the un-freeze
lands come with tripwire coverage the vendor path cannot inherit.

---

## 7. Gate #11 status refresh

Gate #11 in `docs/v0_4_gate_reconciliation_2026_07_07.md` row 11
updates from **FAILING** to **DEFERRED**:

| # | Gate | Status (post-AAA5) | Evidence |
|---|---|---|---|
| 11 | Softbody / fluid / physics / physics2 WIP dirs committed or deferred | **DEFERRED** | User decision 2026-07-08 verbatim: "Keep frozen with docs deferral." Formalised in this doc (`docs/wip_subpackages_deferral_2026_07_08.md`). Wheel ships without any WIP subpackage; roadmap for un-freeze in § 5. Overrides RR6's "user greenlights the unfreeze" path (option 1 in § 4.2) with RR6's option 2 (formal deferral). |

Refreshed gate-count delta: RR6's `9 GREEN + 1 DRAFT + 2 FAILING +
1 YELLOW + 1 needs-verify + 1 deferred` (post YY1) advances one slot
along the deferred column: **9 GREEN + 1 DRAFT + 1 FAILING + 1 YELLOW
+ 1 needs-verify + 2 deferred**. Only gate #1 (version bump) remains
FAILING among the P0 blockers, and gate #12 (game-compat, YELLOW at
91.8% F1 post-YY1 or 92.4% F1 post-ZZ1) can ship-at-YELLOW per
`docs/v0_4_ship_decision_2026_07_07.md` § 8 Option E/F.

Practical effect: gate #11 no longer blocks the v0.4.0 tag. The
tag-ceremony pre-flight in
`docs/v0_4_tag_rehearsal_2026_07_08.md` § 3 can proceed on gate #1
+ gate #12 threshold alone, with this doc as the gate #11 evidence
artefact.

---

## 8. Cross-reference

* [`docs/v0_4_release_readiness_2026_07_06.md`](v0_4_release_readiness_2026_07_06.md)
  — OO7 original 15-gate audit that flagged gate #11 FAILING.
* [`docs/v0_4_gate_reconciliation_2026_07_07.md`](v0_4_gate_reconciliation_2026_07_07.md)
  — RR6 second-pass reconciliation; row 11 refresh evidence points at
  this doc.
* [`docs/v0_4_ship_decision_2026_07_07.md`](v0_4_ship_decision_2026_07_07.md)
  — VV7 ship-decision doc; § 8 Q3 solicited the user answer this doc
  formalises.
* [`docs/v0_4_tag_rehearsal_2026_07_08.md`](v0_4_tag_rehearsal_2026_07_08.md)
  — ZZ7 tag ceremony rehearsal; § 3 pre-flight consumes this doc as
  gate #11 evidence.
* [`docs/api/README.md`](api/README.md) § "WIP subpackages — refs
  deliberately withheld" (line 88+) — pre-existing policy this doc
  formalises with a version-target roadmap.
* [`docs/diary_softbody_bridge_2026_07_04.md`](diary_softbody_bridge_2026_07_04.md)
  — AA3 downstream shim for callers that were importing
  `pharos_engine.softbody`; the fallback path that lets the freeze
  hold without breaking Ochema Circuit's diary panel.
* [`docs/sprint_5_doc_inventory.md`](sprint_5_doc_inventory.md) —
  updated by AAA5 to index this doc.

---

*Deferral doc authored 2026-07-08 by AAA5 background scrum agent
after user answered VV7's Q3 "gate #11 disposition" with "Keep frozen
with docs deferral." Docs-only landing. No WIP subpackage source
touched; no `src/lib.rs` change; no wheel manifest change. Gate #11
refreshed from FAILING to DEFERRED at
`docs/v0_4_gate_reconciliation_2026_07_07.md` row 11.*
