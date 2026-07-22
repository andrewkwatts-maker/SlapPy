# Repo Cleanup Survey — 2026-06-02

Survey produced after the 7-agent sprint batches landed ~50 commits on master in 24h.
Working tree at start: **399** entries from `git status --short` (397 untracked, 2 modified, 4 deletions).

This document is **survey + plan**. Only the `.gitignore` expansion is executed in this
sprint; no files are deleted yet. Deletion + module reshuffling happens in a follow-up
sprint with explicit approval.

**Executed 2026-06-02 (SAFE pass):**
- `ARCHITECTURE.md` and `ONBOARDING.md` moved from repo root to `docs/` (git rename detected, history preserved).
- `benchmarks/baseline_report.md.bak` deleted.
- `_prof_fluid_render.py`, `_prof_softbody_collision.py`, `_prof_softbody_render.py` deleted from repo root (confirmed not imported in `python/`, `SlapPyEngineTests/tests/`, or `SlapPyEngineExamples/examples/`).
- `.gitignore` tightened: added explicit `.ruff_cache/` entry.
- Test suite unchanged: 2547 passed, 6 failed, 22 skipped, 29 xfailed (failures pre-existing in editor_material and residency tests, unrelated to cleanup).

---

## 1. Generated artefacts to add to `.gitignore`

These directories/files are produced by tooling (profilers, audit scripts, smoke tests,
backup writes) and should never have been tracked. Adding them to `.gitignore` shrinks the
working-tree noise dramatically and prevents future accidental commits.

| Pattern                                | Rationale                                                                                                                 |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `_audit_snapshots/`                    | Output directory of the demo/audit refresh scripts (18 PNGs, regenerated on demand).                                      |
| `_prof_*.py`                           | One-shot profiling scripts at repo root (`_prof_fluid_render.py`, `_prof_softbody_collision.py`, `_prof_softbody_render.py`). They are throwaway; if any becomes permanent it should move to `benchmarks/`. |
| `*.bak`                                | Editor / tool backups (`benchmarks/baseline_report.md.bak`).                                                              |
| `docs/visual_diffs/`                   | Per-run image diffs produced by the visual harness (`hello_ragdoll_diff.png` etc.).                                       |
| `SlapPyEngineExamples/examples/output/**`                   | Sweeping rule: all generated example outputs are ignored by default.                                                      |
| Negated gallery artefacts              | Each PNG/GIF referenced by `docs/demo_gallery.md` is re-included via `!examples/output/<sub>/<file>` so the gallery still ships. |

### Gallery artefacts to keep tracked (re-included via `!` rules)

Extracted directly from `docs/demo_gallery.md`:

- `SlapPyEngineExamples/examples/output/hello_gi/hello_gi.png`
- `SlapPyEngineExamples/examples/output/humanoid/humanoid_ik_terrain.gif`
- `SlapPyEngineExamples/examples/output/humanoid/humanoid_walking.gif`
- `SlapPyEngineExamples/examples/output/ragdoll/hello_ragdoll.gif`
- `SlapPyEngineExamples/examples/output/rope/hello_rope.png`
- `SlapPyEngineExamples/examples/output/studio/hello_studio.gif`

All six are already tracked in git; the negation rules preserve them while the new wildcard
silences the 20+ untracked subdir entries (`buoyancy/`, `character/`, `fluid/`, `fracture/`,
`particles/`, `softbody/`, plus the two ad-hoc `humanoid/humanoid_destruction.gif` and
`humanoid/humanoid_standing.gif` files).

### Other obvious noise (added in this pass)

- `benchmarks/__pycache__/` (already caught by `__pycache__/`, but listed for clarity).
- `SlapPyEngineExamples/examples/legacy/output/` (legacy demo regeneration target).
- `SlapPyEngineTests/tests/output/` (companion to `SlapPyEngineTests/tests/visual/output/`, already ignored).

---

## 2. Working-tree-only WIP modules — classification

Untracked files under `python/pharos_engine/` and `python/tests/` fall into three buckets.
Counts are approximate; full list is in `git status --short`.

### (a) Should be committed — useful new code referenced by tests/docs/examples

These are **finished, imported, and tested** modules from the recent sprints. They should
be staged in a follow-up commit with their corresponding tests.

- `python/pharos_engine/asset_manifest.py`, `build_gen.py`, `content_encrypt.py`, `docs_gen.py`
  — usability sprint deliverables (see `project_usability_sprint.md`).
- `python/pharos_engine/cylinder_sprite.py`, `vehicle_parts.py`, `drivetrain.py`,
  `suspension.py` — vehicle sim sprint (covered by `test_vehicle_parts.py`,
  `test_vehicle_physics_script.py`).
- `python/pharos_engine/deform_controller.py`, `deform_modes.py`, `deform_crack.py`,
  `deform_repair.py`, `deform_zones.py` — Bullet Strata integration; **decision pending**
  whether these stay (Phase D doomed-list candidates).
- `python/pharos_engine/collision_pixel.py`, `pixel_material.py`, `pixel_struct.py`,
  `bvh_factory.py`, `spline.py`, `track.py`, `trigger.py`, `visibility.py`,
  `input_provider.py`, `media.py` — covered by matching `test_*.py` files.
- `python/pharos_engine/compute/{hull,library,shader_cache,wgsl_chunks}.py` +
  `compute/defaults/` — compute pipeline plumbing.
- `python/pharos_engine/post_process/{motion_blur,ssr}.py` — Q4 post-process passes.
- `python/pharos_engine/gpu/adaptive_quality.py` — covered by `test_adaptive_quality.py`.
- `python/pharos_engine/tools/{audio_tools,sprite_tools,texture_tools,track_tools,video}.py`
  — tooling sprint deliverables (`test_sprite_tools.py`, `test_audio_tools.py`, etc.).
- `python/pharos_engine/ui/debug_overlay.py`,
  `ui/editor/script_binding_panel.py`, `ui/widgets/` — editor sprint deliverables.
- `python/tests/` — **entire directory** (200+ files). The tests are why we know (a) works.
  These must land together with the modules they cover.
- New shaders under `shaders/` (`bloom.wgsl`, `dof.wgsl`, `ssr.wgsl`, `motion_blur.wgsl`,
  `film_grain.wgsl`, `deform_*.wgsl`, `mesh_frag_gbuffer.wgsl`, `chunks/`).
- New Rust kernels under `src/` (`fluid_shader.rs`, `pbf_solver.rs`, `raster.rs`,
  `softbody_solver.rs`) — referenced from the rust migration memory entries.
- `.github/workflows/physics-coverage.yml`, `.github/workflows/physics-tests.yml` — CI.
- `config/{fluid,physics,physics2,softbody}.yml` — YAML defaults.

### (b) Should be deleted — superseded by the rebuild

Survey only; no action this sprint.

- `python/pharos_engine/physics/cc_label.py` — superseded by `pharos_engine.topology`
  (MEMORY says topology subpackage took over connected-component labelling).
- `python/pharos_engine/physics2/material.py` — appears to be a half-started parallel
  rewrite; mainline material lives in `pharos_engine.material.*`. Confirm before delete.
- `python/pharos_engine/deform_{controller,crack,modes,repair,zones}.py` — listed in the
  Phase D doomed file set per `phase_d_strip_plan_2026_05_31.md`. Cross-check whether the
  Bullet Strata integration still imports them; if not, delete.
- `python/pharos_engine/physics/{ccd,constraints,debug_hud,frontier,hull,memory_budget,`
  `pressure_multigrid,scene_loader,shadows,world,broadphase,cell,profiles,post_process,`
  `render,particle_graph,particles,event_publisher,boundary_exchange,body,video,profile}.py`
  — large block of `physics/` files dropped in untracked. Many duplicate functionality now
  living in `physics/` (already-tracked) or `dynamics/` / `numerics/` / `zones/` /
  `thermal/` subpackages. Each one needs an individual decision; this is the **largest
  single cleanup win** identified.
- `SlapPyEngineExamples/examples/legacy/physics_*_demo.py` — legacy demos kept for reference; move to
  `SlapPyEngineExamples/examples/legacy/` if not already (they appear to be there already, so likely just
  needs to be staged, not deleted).
- Root-level `_prof_*.py` (already covered by gitignore expansion).

### (c) WIP — leave alone (actively iterated)

Per user constraint, do not touch:

- `python/pharos_engine/softbody/` (whole subpackage)
- `python/pharos_engine/fluid/` (whole subpackage)
- `python/pharos_engine/physics/particle_field.py` + `particle_gpu*.py` — active sprint work

Other actively-iterated areas spotted during the survey, leave for the owning sprint:

- `python/pharos_engine/testing/baselines/*.png` — visual regression baselines
  (`outline_round5_legacy.png`, `outline_round5_smooth.png`). Stage them in a baseline-only
  commit once their owning test stabilises.
- `SlapPyEngineTests/tests/visual/scenes/` and `SlapPyEngineTests/tests/visual/test_vis_*.py` — visual harness scenes are
  evolving; stage with the harness owner.

---

## 3. Root-level files that should move or be deleted

| File                                              | Status                                                                                                         | Recommendation                                                                                                                              |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `_prof_fluid_render.py`                           | Untracked at repo root.                                                                                         | Move to `benchmarks/` or delete; covered by `.gitignore` change so it stops appearing in `git status`. **Executed 2026-06-02: deleted (confirmed not imported anywhere).** |
| `_prof_softbody_collision.py`                     | Untracked at repo root.                                                                                         | Same as above. **Executed 2026-06-02: deleted (confirmed not imported anywhere).**                                                          |
| `_prof_softbody_render.py`                        | Untracked at repo root.                                                                                         | Same as above. **Executed 2026-06-02: deleted (confirmed not imported anywhere).**                                                          |
| `ARCHITECTURE.md` (root)                          | **Deleted** in working tree (`D`); `docs/ARCHITECTURE.md` is the new copy (untracked).                          | Canonical location should be `docs/ARCHITECTURE.md` — `docs/architecture_overview.md` already cross-references `docs/ARCHITECTURE.md`. Commit the move (`git rm` root, `git add` docs/) in the follow-up sprint. **Executed 2026-06-02: moved to `docs/ARCHITECTURE.md` (git detected as rename `R`, history preserved).** |
| `ONBOARDING.md` (root)                            | **Deleted** in working tree (`D`); `docs/ONBOARDING.md` is the new copy (untracked).                            | Same treatment as ARCHITECTURE.md — move under `docs/`. **Executed 2026-06-02: moved to `docs/ONBOARDING.md` (git detected as rename `R`, history preserved).** |
| `benchmarks/baseline_report.md.bak`               | Editor backup of `baseline_report.md`.                                                                          | Delete; ignored going forward via `*.bak`. **Executed 2026-06-02: deleted.**                                                                |
| `_audit_snapshots/` (root)                        | Untracked snapshot directory (18 PNGs).                                                                         | Delete or move under `benchmarks/`; ignored going forward. (Not executed in 2026-06-02 SAFE pass — covered by gitignore only.)             |

---

## 4. Biggest cleanup wins identified for the next sprint

1. **Stage the (a) bucket in one large commit.** Hundreds of untracked python files that are
   already imported and tested would drop the `git status` count from ~400 to under 50.
2. **Cull the (b) bucket — physics/ duplicates.** ~25 untracked files in
   `python/pharos_engine/physics/` shadow the already-tracked subpackages. Single highest
   cleanup win once individually triaged.
3. **Move `ARCHITECTURE.md` and `ONBOARDING.md` under `docs/`.** They are already deleted at
   root; the staged-in-working-tree copies under `docs/` are the same content. Just needs a
   single `git rm` + `git add` commit.
4. **Decide the deform_* fate.** Five `deform_*.py` modules + companion tests + shader
   files: either keep (and stage) or delete per Phase D doomed list. Single decision unlocks
   ~15 files.
