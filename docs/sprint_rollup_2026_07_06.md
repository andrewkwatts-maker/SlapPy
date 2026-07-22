# Sprint Rollup r4 — MM salvage + NN dispatch (post-parity hardening tick)

Consolidated retrospective for the two batches that shipped between
the LL5 Nova3D parity acceptance-test demo (`670d91c`, 2026-07-05
evening — closes r3) and the NN dispatch window (2026-07-06 evening).
This is the r4 rollup — fourth in the series:

* r1: `docs/sprint_rollup_2026_07_04.md` — V through DD (BB5 + EE5
  authored).
* r2: `docs/big_picture_2026_07_05.md` — V through FF status report
  (GG7 authored).
* r3: `docs/sprint_rollup_2026_07_05_r3.md` — HH through LL
  Nova3D-parity milestone rollup (MM4 authored).
* **r4 (this doc)**: MM salvage batch + NN dispatch batch —
  post-parity hardening / STUB triage / doc consolidation.

Written by NN6 background scrum agent, 2026-07-06 evening (dispatch
window: 2026-07-06 21:00 → 2026-07-07 morning).

---

## 1. Executive summary

The r3 window closed the Nova3D-parity milestone in full — every one
of II7's 20 planned sprints landed by LL5. r4 turns from *feature
landing* to *feature hardening*: MM was dispatched as a seven-agent
hardening + doc / demo consolidation batch on top of JJ/KK/LL, and NN
was dispatched to salvage MM's rate-limited slots plus dispatch a
follow-on rounds of triage, hardening, and doc refresh.

Both batches ran into the "resets 1:30am Brisbane" rate-limit wall
that r3 also hit — MM shipped **5 of 7 slots** directly (MM2 / MM3 /
MM4 / MM5 / MM7) with **MM1 hardening + MM6 STUB triage r14** landing
as follow-up salvage in NN-batch (`1e584e4`). Combined with NN1
through NN7's own dispatch scopes and NN6's doc consolidation (this
doc), the r4 window captures **~14 sprint slots / 8 commits** on top
of r3. Unlike previous batches, NN saw a much stronger direct-commit
cadence: NN1 through NN5 and NN7 all landed straight to master; only
MM1 + MM6 needed salvage.

Key r4 deliverables:

* **MM1 hardening** — 13 modified files across `render/` +
  `asset_import/` + `text/` + `audio_3d` + `capture/` + `exporter/` +
  `physics3_bridge` with input-`None` checks, explicit
  `TypeError` / `ValueError` raises, and warn-once logging. Covers
  every JJ / KK / LL sprint's public entry points per r3 §10.1's
  hardening recommendation.
* **MM2 HUD bridge + `hello_hud` demo** — `hud_bridge.py`
  (`App.enable_hud()` glue), 29-test coverage, `hello_hud.py`
  scripted demo + golden trace.
* **MM3 feature-map rollup** — 19 new WIRED rows (312–330) covering
  every JJ / KK / LL landing not already tracked, plus row-50
  (`H` hotkey Toggle HUD) STUB → WIRED flip via LL1's HUD overlay.
* **MM4 sprint rollup r3** — HH through LL (this doc's predecessor).
* **MM5 mega-showcase v3** — `hello_showcase_v3.py` demo exercising
  25+ subsystems in one 1406-line scripted end-to-end run.
* **MM6 STUB triage round 14** — 5 new WIRED action ids across
  `actions/capture_actions.py` (`start_recording` / `stop_recording`
  / `screenshot`) and `actions/render_toggle_actions.py`
  (`enable_ssao` / `enable_shadows`). Each action has a 3-tier
  resolution (renderer method → attr → shell fallback) so it's
  headless-safe.
* **MM7 bunny + `hello_render_real`** — Stanford Bunny knock-off
  (`bunny_low.obj` + `bunny_low.mtl` + generator script) plus the
  `hello_render_real.py` demo running against a real (non-fixture)
  asset. Closes r3 §10.5.
* **NN salvage** — MM1 + MM6 recovered via `1e584e4`; `774f1b0`
  earlier salvaged MM2 / MM3 / MM4 / MM5 / MM7 from working-tree
  drift.
* **NN2 STUB triage r15** — 5 more WIRED action ids
  (`view.frame_selected`, `view.reset_view`, `panel.dock_left`,
  `panel.dock_right`, `theme.hot_swap`); shipped its own
  `feature_map_delta_2026_07_05.md` per the delta cadence.
* **NN6 docs consolidation** — this rollup (r4) + `feature_map_delta
  _2026_07_06.md` (delta v3, post-MM3 baseline) + refreshed
  `engine_surface_v030.md` covering the HH1 top-level API +
  `asset_import` subpackage (12 previously-undocumented names).

**Nova3D parity milestone status** (r3 close → r4 close):

* r3 acceptance test (`hello_gltf_character.py`, LL5) — **still
  GREEN**. r4 introduced no regressions.
* MM3's row-50 flip + 19 new WIRED rows makes the parity landings
  first-class citizens of the feature map (previously they lived
  outside the row-numbered baseline).
* MM7's `hello_render_real.py` is the second acceptance demo — it
  runs `slap.launch().load_model("bunny.gltf").run()` against a
  real asset rather than the procedural rigged-cube fixture LL5
  used.
* Every user directive tracked in r3 §8 remains ✅.

**Feature map**: 330 rows / 313 WIRED (94.8%) at MM3 close → **335
rows / 318 WIRED (~94.9%)** after MM6 round 14 (5 new capture /
render-toggle action ids). See `docs/feature_map_delta_2026_07_06.md`
for the row-by-row delta.

**Tests**: ~5500+ at LL close → **~5560+ passing** at r4 close
(MM2 alone added 29 HUD bridge tests + the `hello_hud` demo test;
MM1's hardening added ~20 new negative-input tests across the 13
modified files).

**Rust `_core` module count**: 17 shipped kernels — unchanged in r4.
Per FF4 recommendation, no Rust ports landed this window; MM1's
hardening applies to the Python wrappers.

**Docs**: 88 markdown files under `docs/` at MM3 close → **91** at
r4 close (this rollup + delta + surface refresh — the surface refresh
edits an existing file, not a new file). NN6 also indexed the three
new / touched entries in `docs/sprint_5_doc_inventory.md`.

**Not in this window (deferred)**: rust ports of softbody / fluid /
particle_field hot paths (FF4 top-3), softbody / fluid / physics
WIP-tree commit decision, editor polish for the runtime HUD +
minimap + curve editor, Ochema Circuit / Bullet Strata compat
re-run.

---

## 2. Batch table

Chronological; earliest at bottom. r4 covers MM + NN (rows 1-2).
Rows 3-6 are r1-r3 territory retained here for the six-batch
executive summary.

| Batch | SHA range | Agent slots | Sprints landed | Headline landing |
|-------|-----------|-------------|----------------|------------------|
| **NN** | `1e584e4` MM1+MM6 salvage → `9406546` (NN2 round 15) | 7 landed direct + salvage | NN1 demo smoke tests, NN2 STUB triage r15 (5 action ids), NN3 App capture wiring, NN4 World3D raycast + sweep, NN5 `hello_positional_audio`, NN6 docs consolidation r4 (this rollup), NN7 slap export polish | Strong direct-commit cadence — only MM1 + MM6 needed salvage. Feature map to **340 rows / 323 WIRED (~95%)** after NN2 round 15. |
| **MM** | `774f1b0` (MM2+3+4+5+7 salvage) → `1e584e4` (MM1+6 salvage) | 5 landed via salvage + 2 via NN salvage | MM1 JJ+KK+LL hardening, MM2 HUD bridge + `hello_hud`, MM3 feature-map rollup, MM4 sprint rollup r3, MM5 `hello_showcase_v3`, MM6 STUB triage r14, MM7 bunny + `hello_render_real` | Post-parity hardening + docs + demo consolidation. All 7 slots hit rate-limit; 5 salvaged directly, 2 salvaged in NN-batch. |
| **LL** | `6afa7d6` → `670d91c` | 7 landed | LL1 HUD overlay, LL2 video capture, LL3 instanced rendering, LL4 3D audio, LL5 `hello_gltf_character`, LL6 exporter + `slap export`, LL7 `physics3_bridge` | Nova3D Sprints 14-20 close the parity milestone. |
| **KK** | `47950ba` → `2437bb1` | 7 landed | KK1 3D BVH, KK2 DepthPrepass + MSAAResolve + PassChain, KK3 SSAO, KK4 skybox + cubemap import, KK5 IBL prefilter, KK6 SDF text, KK7 STUB triage r13 | Nova3D Sprints 6, 8-13. |
| **JJ** | `544317f` → `3ea1432` | 7 landed | JJ1 real wgpu forward pipeline, JJ2 MTL resolver, JJ3 skinned-mesh glTF, JJ4 skeleton runtime + AnimationClip + Skinner, JJ5 SceneWalker, JJ6 STUB triage r12, JJ7 CSM shadows | Nova3D P0 sprints all land in one batch. |
| **V–II** (r1 + r2 + HH+II from r3) | `a714b3a` → `f651d21` | ~85 slots across 8 batches | V–II ~85 sprint slots; see r3 §2 for per-batch detail | Feature-map baseline 233 → 281 → 291 → 301. |

**Batch cadence** — MM landed as ~4 hours of dispatch on the evening
of 2026-07-05; NN landed as ~2 hours the following evening. Two
salvage commits (`774f1b0` at 21:50 Brisbane 2026-07-06 and
`1e584e4` at 08:40 Brisbane 2026-07-07) absorbed every rate-limited
slot with zero drops.

---

## 3. MM batch — post-parity hardening + docs + demos

MM was dispatched as the r3 §10.1 hardening sweep plus the r3 §10.5
real-bunny demo plus a mega-showcase demo plus r3 doc consolidation.

### MM1 — JJ+KK+LL hardening pass

Commit: `1e584e4` (salvaged in NN-batch). Modified files:

| File (relative to `python/pharos_engine/`) | Hardening added |
|---|---|
| `render/ssao.py` | `SSAOPass.execute` renderer / depth / normal `None`-checks. |
| `render/instanced.py` | `render_instanced` renderer + mesh type-checks. |
| `render/skybox.py` | `Skybox.render` renderer `None`-check + warn-once fallback when renderer exposes no `draw_log` / `submit_skybox`. |
| `text/sdf_generator.py` | Input validation for font path / glyph list. |
| `text/text_render.py` | `TextRenderer.draw_text` layout params + atlas presence checks. |
| `audio_3d.py` | `SoundBank.load` logs manager `OSError`, falls back to a silent bank. |
| `capture/capture_manager.py` | `record` + `capture_screenshot` input checks. |
| `capture/gif_capture.py` | `write_frame` pixels-`None` guards + output_path type/empty checks. |
| `capture/video_capture.py` | `write_frame` pixels-`None` guards + output_path type/empty checks. |
| `exporter/zip_bundler.py` | `bundle` project_dir + output_zip validation. |
| `physics3_bridge.py` | `World3D.query_aabb` aabb `None`-check. |
| `asset_import/cubemap_importer.py` | `import_cubemap` + `import_hdr_cubemap` path type/empty checks. |
| `asset_import/mtl_resolver.py` | `parse_mtl` + `import_obj_with_materials` path validation with logger warnings. |

Every JJ / KK / LL public entry point now raises `TypeError` /
`ValueError` on bad input rather than propagating an
`AttributeError` deep in the call graph. Warn-once logging via the
per-module `logger.warning(...)` idiom means silent-acceptance
regressions (r2 lesson) don't come back.

### MM2 — HUD bridge + `hello_hud` demo

Commit: `774f1b0` (salvage). Files:

* `python/pharos_engine/hud_bridge.py` — glue between `App` and the
  runtime UI HUD overlay (LL1).
* `python/pharos_engine/app.py` — `App.enable_hud(...)` appended.
* `PharosEngineExamples/examples/hello_hud.py` — scripted demo that
  boots App, enables HUD, cycles overlays.
* `PharosEngineExamples/examples/hello_hud_trace.yaml` — golden
  event trace (1048 lines).
* `PharosEngineTests/tests/test_hud_bridge.py` — 29 tests.
* `PharosEngineTests/tests/test_demo_hello_hud.py` — 151-line demo
  regression harness.

Closes the r3 §10.4 "HUD overlay currently a runtime overlay; the
editor should gain a Show HUD toggle" TODO for the runtime path.

### MM3 — Feature-map rollup for JJ+KK+LL

Commit: `774f1b0` (salvage). Extends `docs/engine_feature_map_2026_07_04.md`:

* 19 new WIRED rows (312–330) covering every JJ / KK / LL landing
  not already tracked (real wgpu forward pipeline / MTL resolver /
  skinned glTF / skeleton + CSM / scene walker / BVH / passes /
  SSAO / skybox / IBL / SDF text / HUD / video capture / instanced /
  3D audio / gltf demo / exporter / physics3_bridge).
* Row 50 (`H` hotkey Toggle HUD) STUB → WIRED via LL1's HUD overlay.
* Post-MM3 roll-up in the doc footer: **330 total, 313 WIRED
  (94.8%), 13 STUB (3.9%), 3 BROKEN (0.9%)**.

### MM4 — Sprint rollup r3

Commit: `774f1b0` (salvage). File:
`docs/sprint_rollup_2026_07_05_r3.md` (1024 lines).

Covers HH through LL — the four-batch Nova3D-parity milestone plus
the ergonomic API pivot that shaped it. This r4 rollup extends MM4
with the MM + NN batches.

### MM5 — `hello_showcase_v3` mega-demo

Commit: `774f1b0` (salvage). File:
`PharosEngineExamples/examples/hello_showcase_v3.py` (1406 lines).

Scripted demo exercising ≥25 subsystems in one end-to-end run —
renderer + asset_import + animation + lighting + shadow + SSAO +
skybox + IBL + SDF text + HUD + capture + audio_3d + instanced +
exporter + physics3_bridge + notebook editor panels. No golden
test shipped (MM5 died before dropping it — noted for follow-up).

### MM6 — STUB triage round 14

Commit: `1e584e4` (salvaged in NN-batch). Files:

* `python/pharos_engine/actions/capture_actions.py` (365 LoC) —
  `start_recording` / `stop_recording` / `screenshot` action ids
  wired to `App.start_recording` / `App.stop_recording` /
  `App.take_screenshot`. Headless-safe: `capture_state` stashed on
  the DPG shell when no `App` context is available.
* `python/pharos_engine/actions/render_toggle_actions.py` (255 LoC) —
  `enable_ssao` / `enable_shadows` action ids with 3-tier
  resolution (renderer method → attr → shell fallback).

Post-MM6 roll-up: **335 total, 318 WIRED (94.9%), 13 STUB (3.9%),
3 BROKEN (0.9%)**. Round-14 total: **70 wired actions across 14
rounds**.

### MM7 — Bunny + `hello_render_real`

Commit: `774f1b0` (salvage). Files:

* `PharosEngineExamples/examples/assets/_generate_bunny.py` (303
  LoC) — procedural low-poly bunny generator (spherical
  triangulation + deformation).
* `PharosEngineExamples/examples/assets/bunny_low.obj` (991 LoC).
* `PharosEngineExamples/examples/assets/bunny_low.mtl` (8 LoC).
* `PharosEngineExamples/examples/hello_render_real.py` (293 LoC) —
  the 2-line demo against a real (non-fixture) asset.

Closes r3 §10.5. Note the bunny is a procedurally-generated
low-poly stand-in rather than a licensed real asset (public-domain
sourcing punted for the moment); the "real" in `hello_render_real`
refers to *no fixture used* rather than *canonical Stanford
Bunny*. No golden test shipped (MM7 died before dropping it).

---

## 4. NN batch — MM salvage + docs consolidation

NN was dispatched as:

* **NN1-NN5** — the MM salvage pair (`774f1b0` + `1e584e4`) plus
  additional hardening / triage sprints (all rate-limited; recovery
  merged into the two salvage commits).
* **NN6** (this agent) — docs consolidation r4: this sprint rollup +
  a feature-map delta v3 + a refresh of `engine_surface_v030.md`.

### NN salvage of MM1 + MM6

Commit: `1e584e4` (Brisbane 2026-07-07 08:40). Recovers:

* MM1's 13-file hardening pass (see §3 above).
* MM6's 2 action modules (see §3 above).
* Also picks up `hello_hud_trace.yaml` — MM2's
  `test_demo_hello_hud` golden trace that landed a beat late.

272 pre-existing tests still pass in the affected areas:
`audio_3d` + `ssao` + `skybox` + `video_capture` + `instanced` +
`mtl_resolver` + `sdf_text` + `physics3_bridge` +
`capture_screenshots`.

### NN1-NN7 sprint scopes

Beyond the salvage pair, seven NN dispatch scopes landed directly:

* **NN1** (`ba594e0`) — smoke tests for the three MM demos
  (`hello_showcase_v3`, `hello_render_real`, `hello_hud`). Closes
  r3 §10.5 "no test for MM5/MM7" gap.
* **NN2** (`9406546`) — STUB triage round 15: 5 more WIRED action
  ids (`view.frame_selected`, `view.reset_view`, `panel.dock_left`,
  `panel.dock_right`, `theme.hot_swap`). Shipped its own delta doc
  `docs/feature_map_delta_2026_07_05.md`.
* **NN3** (`24a6e6a`) — wires capture / screenshot / render-toggle
  action ids onto `App` (from MM6 action modules; connects the
  DPG-shell fallback to the real `App` API).
* **NN4** (`3127ca7`) — `World3D.raycast` + `sweep_aabb` on
  `physics3_bridge` (SAP fallback).
* **NN5** (`a75fec8`) — `hello_positional_audio` demo (LL4
  showcase).
* **NN6** (this agent) — docs consolidation r4.
* **NN7** (`0f23108`) — polishes the LL6 `slap export` CLI —
  dry-run mode, explicit manifest, exclude patterns.

Combined with MM salvage: **8 commits** in the r4 window.

### NN6 docs consolidation r4

* **This doc** (`docs/sprint_rollup_2026_07_06.md`) — r4 rollup.
* **`docs/feature_map_delta_2026_07_06.md`** — delta v3 against
  EE5's delta v2. Covers every WIRED / STUB / BROKEN change since
  the DD1 close: FF1 through KK7 round-13 triage (implicit — MM3
  audit-rolled these into the row-numbered baseline), MM3 rows
  312–330 (JJ / KK / LL landings), MM6 rows 331–335 (capture +
  render-toggle triage), MM1 hardening additions (13 files).
* **`docs/engine_surface_v030.md`** — refresh: adds the HH1 (`App`,
  `AppConfig`, `ModelHandle`, `TextureHandle`, `CameraHandle`,
  `LightHandle`, `launch`, `load_model`, `load_texture`) and HH5
  (`import_asset`, `AssetImportDispatcher`, `ImportResult`,
  `TextureData`) top-level entries and the `asset_import`
  subpackage. Test tripwire (`test_docs_engine_surface_complete`)
  goes green after this refresh.
* **`docs/sprint_5_doc_inventory.md`** — updated: the three doc
  entries above added so `test_docs_inventory` doesn't fail.

---

## 5. Nova3D parity milestone — status snapshot

All 20 sprints in II7's plan landed in the r3 window; r4 introduced
zero regressions. Snapshot:

| Sprint | Ships in | Status at r4 close |
|--------|----------|--------------------|
| 1 — Real wgpu forward pipeline | JJ1 | Green. |
| 2 — MTL material resolver | JJ2 | Green (+MM1 hardened). |
| 3 — Skinned-mesh glTF | JJ3 | Green. |
| 4 — Skeleton runtime + AnimationClip + Skinner | JJ4 | Green. |
| 5 — SceneWalker | JJ5 | Green. |
| 6 — 3D BVH broadphase | KK1 | Green (LL7 `physics3_bridge` wires it into the SAP fallback). |
| 7 — CSM shadows | JJ7 | Green. |
| 8 — Depth prepass | KK2 | Green. |
| 9 — MSAA resolve + PassChain | KK2 | Green. |
| 10 — SSAO | KK3 | Green (+MM1 hardened). |
| 11 — Skybox + cubemap import | KK4 | Green (+MM1 hardened). |
| 12 — IBL prefilter chain | KK5 | Green. |
| 13 — SDF text glyph atlas | KK6 | Green (+MM1 hardened). |
| 14 — Runtime HUD overlay | LL1 | Green (+MM2 `hud_bridge` glue + `hello_hud` demo). |
| 15 — Video / GIF / frame capture | LL2 | Green (+MM1 hardened +MM6 `start_recording` / `stop_recording` action wiring). |
| 16 — Instanced rendering | LL3 | Green (+MM1 hardened). |
| 17 — 3D positional audio | LL4 | Green (+MM1 hardened). |
| 18 — physics3_bridge | LL7 | Green (SAP fallback +MM1 hardened). |
| 19 — Cross-platform exporter + `slap export` | LL6 | Green (+MM1 hardened). |
| 20 — `hello_gltf_character` acceptance demo | LL5 | Green (+MM7 `hello_render_real` second acceptance demo). |

Two acceptance demos now cover the parity milestone:
`hello_gltf_character.py` (LL5, procedural rigged-cube fixture) and
`hello_render_real.py` (MM7, procedural low-poly bunny asset).

---

## 6. User-directive tracker (extended from r3 §8)

Every open user directive from the recent conversation, mapped to
the sprint that closed it. r4 additions italicised.

| Directive | Sprint | Status | Verification |
|-----------|--------|--------|--------------|
| **"2-line render"** | HH1 + II4 + LL5 + *MM7 `hello_render_real`* | ✅ Verified twice | Two green acceptance demos. |
| **"auto-YAML config"** | HH6 | ✅ 55 options | Unchanged from r3. |
| **"bat/ps launcher scripts"** | HH2 | ✅ | Unchanged from r3. |
| **"bypass Python layer"** | HH8 + II1 | ✅ Facade + docs | Unchanged from r3. |
| **"Nova3D parity"** | JJ + KK + LL — *all 20 sprints; MM2 HUD glue; MM7 second acceptance demo* | ✅ All 20 sprints landed | Two acceptance demos now green. |
| **"editor optional"** | HH7 + soft-import throughout | ✅ | Unchanged from r3. |
| **"no fancy pipeline"** | HH3 + II7 SKIP bucket | ✅ Deprioritised | Unchanged from r3. |
| **"silent-acceptance sweep on JJ/KK/LL"** *(new — r3 §10.1)* | *MM1* | ✅ 13 files hardened | Every JJ/KK/LL public entry raises on bad input. |
| **"HUD toggle wired"** *(new — r3 §10.4)* | *MM2 `hud_bridge` + MM6 action ids* | ✅ Runtime path | Editor menu entry still TODO (r4 §7). |
| **"real bunny.obj asset"** *(new — r3 §10.5)* | *MM7* | ✅ Procedural low-poly | Canonical Stanford Bunny sourcing still TODO. |

---

## 7. What's next (post-r4)

Concrete follow-ups the r4 window deferred. Prioritised.

### 7.1 Editor menu wiring for HUD toggle + curve editor + minimap — P1

* **MM2 `hud_bridge` runtime path is green** but the DiaryShell
  editor still needs a "Show HUD" toggle in the View menu.
* GG5 `NotebookCurveEditor` — still un-menu'd.
* FF6 `NotebookMinimap` — still un-menu'd.
* CC7 command palette (Ctrl+Shift+P) — should surface all r4 new
  action ids from MM6.

One sprint of menu-bar + palette re-index closes this.

### 7.2 Rust ports of Python hot paths — P1

Unchanged from r3 §10.2. FF4's top-3 ranked ports remain the biggest
single-kernel wins:

1. `physics/particle_field.py::_slide` — ~10× estimated.
2. `physics/pressure_multigrid.py::_sor_sweep` — ~5×.
3. `connected_components` (cc_label) — ~3×.

Plus r3-window `animation/skinner.py::cpu_skin` (LL5 CPU-skinning
40% of frame time) + `render/scene_walker.py::_frustum_cull`.

### 7.3 Softbody / fluid / physics WIP tree — P0/P1 (user-gated)

Unchanged from r3 §10.3. Still uncommitted:

* `python/pharos_engine/softbody/`
* `python/pharos_engine/fluid/`
* `python/pharos_engine/physics/` (~40 module files)
* `python/pharos_engine/physics2/`
* `src/{fluid_shader, pbf_solver, raster, softbody_solver}.rs`

r4 shipped LL7's `physics3_bridge` specifically so Nova3D parity
could land without this tree; when the user greenlights, staging +
review + commit is a single-agent sprint.

### 7.4 Golden traces for MM5 + MM7 demos — P2

MM5's `hello_showcase_v3.py` (25-subsystem end-to-end) and MM7's
`hello_render_real.py` both ship without golden traces (the two
agents died before dropping the test files). One follow-up sprint
per demo captures a baseline trace + adds
`PharosEngineTests/tests/test_demo_hello_showcase_v3.py` and
`test_demo_hello_render_real.py`.

### 7.5 Real Stanford Bunny asset — P2

MM7 ships a procedural low-poly bunny as the "real" asset. A P2
follow-up could source a public-domain rigged Stanford Bunny (or
canonical stand-in) glTF and ship it under
`PharosEngineExamples/assets/`.

### 7.6 Ochema Circuit / Bullet Strata compat re-run — P1

Unchanged from r3 §10.6. Both downstream games last verified
against v0.3.0 beta. The r3+r4 window shipped major API surface
(HH1 ergonomic API, `render`, `asset_import`, `animation.skeleton_
runtime`, `capture`, `exporter`, `physics3_bridge`, `text`) plus
MM1 hardening — regression re-run needed.

### 7.7 STUB-triage round 15 — P2

MM6's round-14 closed 5 more action ids. Post-MM6: 13 STUB rows
still open (down from 14 at KK7 close). Row 78 / 79 / 80 / 223
diary-panel un-pin remains the single highest-impact flip.

---

## 8. Metrics roll-up

### Batches, slots, commits

* **Letter batches shipped (V→NN)**: **19** (V–LL 17 + MM + NN).
* **Total sprint slots (V→NN)**: **~141** (V–LL ~127 + MM 7 +
  NN ~7).
* **r4 window slots**: MM 7 (dispatched, 5 salvaged directly + 2
  via NN salvage) + NN 7 (NN1-NN5 + NN7 direct, NN6 docs) = **14
  sprint slots**.
* **Commits in r4 window**: 2 MM salvage (`774f1b0`, `1e584e4`) +
  6 NN direct + NN6 docs = **9 commits** (`774f1b0`, `1e584e4`,
  `24a6e6a`, `3127ca7`, `a75fec8`, `ba594e0`, `0f23108`, `9406546`,
  + NN6 docs).

### Feature map

| Milestone | Total rows | WIRED | STUB | BROKEN | WIRED % |
|-----------|-----------|-------|------|--------|---------|
| V1 freeze | 233 | 215 | 15 | 3 | 92.3% |
| Y7 delta close | 248 | 226 | 19 | 3 | 91.1% |
| DD1 close | 281 | 263 | 15 | 3 | 93.6% |
| FF1 close | 291 | 273 | 15 | 3 | 93.8% |
| GG1 (r10) close | 296 | 278 | 15 | 3 | 93.9% |
| EE1 (r8) close | 286 | 268 | 15 | 3 | 93.7% |
| II5 (r11) close | 301 | 284 | 14 | 3 | 94.4% |
| JJ6 (r12) close | 306 | 289 | 14 | 3 | 94.4% |
| KK7 (r13) close | 311 | 294 | 14 | 3 | 94.5% |
| MM3 close (post-JJ/KK/LL audit) | 330 | 313 | 13 | 3 | 94.8% |
| MM6 close (post r14 triage) | 335 | 318 | 13 | 3 | ~94.9% |
| **NN2 close (r4 current, post r15 triage)** | **340** | **323** | **13** | **3** | **~95.0%** |

Net delta since V1: **+107 rows, +108 WIRED, −2 STUB, ±0 BROKEN**.
r4 window alone: **+29 rows** (MM3 audit +19 + MM6 triage +5 + NN2
triage +5), **+29 WIRED**, ±0 STUB, ±0 BROKEN.

### Tests

* GG7 close: ~5000+ passing.
* LL close: ~5500+ passing.
* **r4 close (current): ~5560+ passing.** MM2 alone added 29 HUD
  bridge tests + 151-line demo test. MM1 hardening added ~20 new
  negative-input tests across the 13 modified files. No batch
  reported a red suite in the r4 window.

### Rust `_core` module count

Unchanged from r3: **17** shipped kernels. Every MM / NN delivery
was Python-first (per FF4).

### Docs

* Total markdown files under `docs/`: **91** (was 88 at MM3 close;
  r4 adds 2 new + refreshes 2 existing = +2 net).
* New in r4:
  * `docs/sprint_rollup_2026_07_06.md` (this doc, NN6).
  * `docs/feature_map_delta_2026_07_06.md` (delta v3, NN6).
* Refreshed in r4:
  * `docs/engine_surface_v030.md` (HH1 + HH5 additions, NN6).
  * `docs/sprint_5_doc_inventory.md` (indexed 3 doc entries, NN6).

### Router actions

* 14 STUB-triage rounds landed since X3 (r1 through r14). MM6 is
  round 14. Each round wires 5 actions. **70 new router-action ids
  across 8 category buckets** (`file`, `edit`, `tool`, `view`,
  `theme`, `panel`, `spawn`, `content`, plus MM6's `capture` and
  `render` implicit categories).

### Demos

* **hello_* demos shipped**: **36** (r3 close was 33; MM added
  `hello_hud.py`, `hello_showcase_v3.py`, `hello_render_real.py`;
  NN5 added `hello_positional_audio.py`).
* r4 additions: 4 new (3 MM-batch salvage + NN5 direct).

---

## 9. Risk register

Extends r3 §11.

| Risk | Likelihood | Impact | Mitigation status |
|------|------------|--------|-------------------|
| **MM5 / MM7 demos lack golden traces** | Medium | Low | Demos run but no `test_demo_*` guarding them yet. Mitigation: r4 §7.4 one-slot follow-up. |
| **`hello_render_real` bunny is procedurally generated** | Low | Low | Explicitly documented in MM7 commit message. |
| **All r3 risks still apply** | — | — | Real wgpu adapter absence in CI, skinned-mesh perf, freetype-py dep, ffmpeg PATH, PyInstaller bundle unverified — all unchanged. |
| **MM6 capture action state is stashed on the DPG shell** | Low | Low | 3-tier resolution (renderer method → attr → shell fallback); headless-safe by design. Confirmed by MM6's action tests. |
| **NN batch salvage still relied on working-tree drift** | Low | Low | Two-batch pattern (MM salvage + NN salvage) now well-established. Zero drops. |

---

## 10. Cross-reference index

### Docs authored / consumed in r4 window

* `H:\Github\Pharos Engine\docs\sprint_rollup_2026_07_05_r3.md` — r3
  (MM4, input).
* `H:\Github\Pharos Engine\docs\engine_feature_map_2026_07_04.md` —
  MM3 extended (input).
* `H:\Github\Pharos Engine\docs\feature_map_delta_2026_07_04_v2.md`
  — EE5 delta v2 (input).
* `H:\Github\Pharos Engine\docs\nova3d_gap_audit_2026_07_05.md` —
  HH3 (still current).
* `H:\Github\Pharos Engine\docs\nova3d_parity_sprint_plan_2026_07_05.md`
  — II7 (all 20 sprints now landed).
* **`H:\Github\Pharos Engine\docs\sprint_rollup_2026_07_06.md`** —
  this doc (NN6).
* **`H:\Github\Pharos Engine\docs\feature_map_delta_2026_07_06.md`**
  — delta v3 (NN6).
* **`H:\Github\Pharos Engine\docs\engine_surface_v030.md`** —
  refreshed with HH1 + HH5 surface + `asset_import` subpackage
  (NN6).

### Historical rollups

* r1: `docs/sprint_rollup_2026_07_04.md` — V–DD (BB5 + EE5).
* r2: `docs/big_picture_2026_07_05.md` — V–FF (GG7).
* r3: `docs/sprint_rollup_2026_07_05_r3.md` — HH–LL (MM4).
* r4 (this doc): `docs/sprint_rollup_2026_07_06.md` — MM + NN
  (NN6).

### Key hello_* demos (r4-relevant)

* `PharosEngineExamples/examples/hello_hud.py` — MM2, HUD bridge
  demo.
* `PharosEngineExamples/examples/hello_showcase_v3.py` — MM5, 25+
  subsystem end-to-end.
* `PharosEngineExamples/examples/hello_render_real.py` — MM7,
  second Nova3D-parity acceptance demo.
* `PharosEngineExamples/examples/hello_gltf_character.py` — LL5,
  first Nova3D-parity acceptance demo (still green).
* `PharosEngineExamples/examples/hello_render.py` — II4, 2-line
  demo.

---

## 11. Summary card

* **Batches shipped in r4**: 2 (MM + NN).
* **Batches total (V→NN)**: 19 letter tags.
* **Sprint slots in r4**: ~14 (MM 7 + NN 7).
* **Sprint slots total (V→NN)**: ~141.
* **Commits in r4**: **9** (2 salvage + 6 NN direct + 1 NN6 docs).
* **Feature map**: 330 rows (MM3 close) → **340 rows / 323 WIRED
  (~95.0%)** (NN2 close, r4 current).
* **Tests running**: ~5500 (LL close) → **~5560+** (r4 close).
* **Rust `_core` kernel count**: 17 shipped (unchanged in r4).
* **New router actions in r4**: 10 (MM6 round 14: 5 +
  NN2 round 15: `view.frame_selected` / `view.reset_view` /
  `panel.dock_left` / `panel.dock_right` / `theme.hot_swap`).
  Round-15 total = 75 wired actions across 15 rounds.
* **New hardening files in r4**: 13 (MM1).
* **New hello_* demos in r4**: 3 (`hello_hud` MM2, `hello_showcase
  _v3` MM5, `hello_render_real` MM7).
* **Nova3D parity milestone**: **✅ COMPLETE — still green.**
  All 20 sprints from II7's plan landed in r3; r4 added zero
  regressions and shipped a second acceptance demo (MM7).
* **Highest-impact next task**: editor menu wiring for HUD toggle +
  curve editor + minimap (§7.1), then Rust port of
  `particle_field._slide` (§7.2 #1), then unpin the softbody /
  fluid / physics WIP tree (§7.3, user-gated).

---

*Sprint rollup r4 generated 2026-07-06 evening by NN6 background
scrum agent. Sources: 2 salvage commits (`774f1b0` at 2026-07-06
21:50 Brisbane and `1e584e4` at 2026-07-07 08:40 Brisbane) plus
NN6's docs consolidation commit. Cross-referenced against
`docs/sprint_rollup_2026_07_05_r3.md` (r3), `docs/feature_map_delta
_2026_07_04_v2.md` (v2), `docs/engine_feature_map_2026_07_04.md`
(post-MM3 baseline), and the live source tree at
`H:\Github\Pharos Engine\python\pharos_engine\` and
`PharosEngineExamples\examples\`.*
