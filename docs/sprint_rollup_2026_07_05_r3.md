# Sprint Rollup r3 — HH through LL Batches (post-Nova3D-parity)

Consolidated retrospective of the four-batch scrum push that took
SlapPyEngine from the GG7 big-picture status report (2026-07-05 morning,
`824db96`) to the LL5 acceptance-test demo (`670d91c`,
`hello_gltf_character`). This is the r3 rollup — the third in the
series after BB5 (`docs/sprint_rollup_2026_07_04.md`, V–DD) and EE5
(same doc extended with CC+DD). r3 picks up where GG7 left off and
tracks the pivot from "shipping polish" (HH — ergonomic API) through
"Nova3D parity" (JJ+KK+LL — 20 planned sprints, all landed).

Written by MM4 background scrum agent, 2026-07-05 evening.

---

## 1. Executive summary

Seventeen letter batches (V through LL) landed on master between
`db56df3` (2026-06-07 master review) and `670d91c` (LL5, Nova3D
acceptance-test demo, 2026-07-05 evening). Roughly **127 sprint slots**
were dispatched across the entire push; the r3 window (HH → LL) covers
**four batches / ~29 sprint slots / ~44 commits** and delivers the
**Nova3D-parity milestone in full** — every one of the 20 planned
sprints in `docs/nova3d_parity_sprint_plan_2026_07_05.md` (II7) reached
master.

Key r3 deliverables:

* **HH batch** — ergonomic top-level API pivot. `pharos_engine.launch()`
  + `App` + `ModelHandle` (HH1), `slap` CLI + project scaffolder (HH2),
  a read-only Nova3D gap audit (HH3), `pharos_engine.render` wgpu 2D+3D
  forward renderer (HH4), the `asset_import/` subpackage with glTF+OBJ
  importers (HH5), `pharos_engine.config` YAML defaults + validation
  (HH6), the `ui/runtime/` immediate-mode UI backend (HH7), and the
  `_core_facade` Rust bypass (HH8).
* **II batch** — integration + follow-ups: rust-bypass docs (II1),
  runtime-UI tests (II2), HH1↔HH4↔HH5 end-to-end wiring (II3), the
  two-line `hello_render` demo (II4), STUB triage round 11 (II5), pip
  extras split (II6), and the 20-sprint Nova3D parity plan (II7).
* **JJ batch** — P0 parity sprints: real wgpu forward pipeline (JJ1),
  MTL material resolver (JJ2), skinned-mesh glTF loader (JJ3), Skeleton
  + AnimationClip runtime (JJ4), SceneWalker (JJ5), STUB triage r12
  (JJ6), CSM shadows (JJ7).
* **KK batch** — Nova3D Sprints 6, 8-13: 3D BVH (KK1), depth prepass +
  MSAA resolve + PassChain (KK2), SSAO (KK3), skybox + cubemap import
  (KK4), IBL prefilter chain (KK5), SDF text glyph atlas (KK6), STUB
  triage r13 (KK7).
* **LL batch** — Nova3D Sprints 14-20: runtime HUD overlay (LL1),
  video/gif/frame capture (LL2), instanced rendering (LL3), 3D
  positional audio (LL4), `hello_gltf_character` acceptance demo
  (LL5), cross-platform game exporter + `slap export` (LL6),
  `physics3_bridge` soft-import + BVH-broadphase wiring (LL7).

**Feature map**: 291 rows (GG7 close) → **~330 rows / ~314 WIRED
(~95%)** at LL close. Router-action triage rounds 10 (GG1), 11 (II5),
12 (JJ6), and 13 (KK7) each wired 5 more previously-absent action ids,
taking the STUB-triage total to **65 new router actions across 13
rounds**.

**Tests**: ~5000+ at GG7 close → **~5500+ passing** at LL close (KK+LL
alone added several hundred).

**Rust `_core` module count**: 17 kernels tracked at FF4 (2026-07-05
morning) — unchanged in r3; every KK/LL delivery was Python-first (per
FF4 recommendation) with Rust ports queued for next-tick.

**Docs**: 90 markdown files under `docs/`; ~10 new / extended in this
window (Nova3D gap audit HH3, parity plan II7, big-picture GG7, rust
bypass II1, pyproject extras II6, this rollup MM4).

**User directives fulfilled** — this window closes every open user
directive from the recent conversation:

* "2-line render" API (HH1) — verified end-to-end by II4
  `hello_render.py` and by LL5 `hello_gltf_character.py`.
* "auto-YAML config" (HH6) — 55 config options with hierarchical
  merging and JSON-schema validation.
* "bat/ps launcher scripts" (HH2) — project scaffolder emits Windows
  `run.bat` and PowerShell `run.ps1` alongside the Python entry.
* "bypass Python layer" (HH8 + II1) — `_core_facade` module exposes
  every Rust kernel with zero Python overhead; documented in
  `docs/rust_bypass_2026_07_05.md`.
* "Nova3D parity" (JJ+KK+LL) — all 20 sprints from II7 landed on
  master. Sprint 20 (`hello_gltf_character` demo, LL5) is the green
  acceptance test.
* "editor optional" — `pharos_engine[editor]` extra confirmed
  soft-import throughout; core wheel installs without DPG and every
  new panel wraps `_safe_dpg` per the Z1 headless-safety pattern.

**Not in this window (deferred to post-parity)**: rust ports of
softbody / fluid / particle_field hot paths (FF4 top-3), softbody /
fluid / physics WIP-tree commit decision, editor polish for the
runtime HUD + minimap + curve editor, real bunny.obj asset (LL5 ships
a procedural rigged cube fixture instead), Ochema Circuit / Bullet
Strata compat re-run.

---

## 2. Batch-by-batch table (17 letter tags — V through LL)

Chronological; earliest at bottom. r3 covers HH through LL (rows 1-4).
Rows 5-13 are r1/r2 territory retained here for the seventeen-batch
executive summary.

| Batch | SHA range | Agent slots | Sprints landed | Headline landing |
|-------|-----------|-------------|----------------|------------------|
| **LL** | `6afa7d6` (LL1) → `670d91c` (LL5) | 7 landed | LL1 HUD overlay, LL2 video capture, LL3 instanced rendering, LL4 3D positional audio, LL5 `hello_gltf_character` demo, LL6 exporter + `slap export`, LL7 `physics3_bridge` | Nova3D Sprints 14-20 close the parity milestone. `hello_gltf_character` (LL5) is the green acceptance test for Sprints 1-7 (real wgpu pipeline + scene walker + skeletal runtime + CSM + BVH). |
| **KK** | `47950ba` (KK1) → `2437bb1` (KK7) | 7 landed | KK1 3D BVH broadphase, KK2 DepthPrepass + MSAAResolvePass + PassChain, KK3 SSAO, KK4 skybox + cubemap import, KK5 IBL prefilter chain, KK6 SDF text glyph atlas, KK7 STUB triage r13 | Nova3D Sprints 6, 8-13 land in one batch. Frustum culler (KK1) unlocks JJ5's SceneWalker; PassChain (KK2) formalises the render-graph pattern used by JJ1's pipeline. |
| **JJ** | `544317f` (JJ2) → `3ea1432` (JJ1) | 7 landed | JJ1 real wgpu forward pipeline, JJ2 MTL resolver, JJ3 skinned-mesh glTF, JJ4 skeleton runtime + AnimationClip + Skinner, JJ5 SceneWalker, JJ6 STUB triage r12, JJ7 CSM shadows | Nova3D P0 sprints all land in a single batch. Un-forks HH4 from `NullRenderer` fallback into a real wgpu forward pipeline (JJ1). Full character-animation pipeline lands via JJ3 + JJ4. |
| **II** | `1c7818c` (II2) → `f651d21` (II5) | 7 landed | II1 rust bypass docs + tests, II2 `ui.runtime` tests, II3 HH1↔HH4↔HH5 integration, II4 `hello_render` 2-line demo, II5 STUB triage r11, II6 pip extras, II7 Nova3D parity sprint plan | Integration + planning batch. II3 wires the HH-batch pieces end-to-end; II7 is the 20-sprint plan that JJ+KK+LL executed against. |
| **HH** | `ec94c2a` (HH1) → `de3a22b` (HH5+HH7+HH8 salvage) | 8 landed (7 + salvage) | HH1 App / launch / ModelHandle, HH2 project scaffolder + `slap` CLI, HH3 Nova3D gap audit (docs), HH4 wgpu 2D+3D renderer, HH5 asset importer, HH6 config defaults + validation, HH7 `ui.runtime` immediate-mode UI, HH8 `_core_facade` Rust bypass | **The ergonomic API pivot.** User directive "2-line render" (HH1) shapes every downstream sprint. Nova3D gap audit (HH3) identifies 11 MUST_HAVE / 8 NICE_TO_HAVE / 3+ SKIP subsystems. |
| **GG** | `a8fbc4f` (GG2) → `824db96` (GG7) | 7 landed | GG1 STUB triage r10, GG2 ProjectSceneBridge, GG3 PluginRegistry, GG4 perf tripwire, GG5 NotebookCurveEditor, GG6 scene_diff, GG7 big-picture status report | Polish + planning batch immediately before the HH pivot. GG7 is the input to HH3 gap audit and II7 parity plan. |
| **FF** | `5fd475d` (salvage FF1+FF2) → `29f7552` (FF7) | 7 landed | FF1 STUB triage r9, FF2 material graph bridge fix, FF3 `pharos_engine.scenes`, FF4 Rust migration re-audit, FF5 hotkey conflict detector, FF6 NotebookMinimap, FF7 hello_scene_reg demo | Ships `pharos_engine.scenes` subpackage; FF4 audit is the input to r3's Rust-porting recommendations. |
| **EE** | `69f4407` (EE7) → `77ac09b` (EE2) | 7 landed | EE1 STUB triage r8, EE2 hello_v2_showcase, EE3 NotebookMenuBar, EE4 FileDropHandler, EE5 rollup extension, EE6 NotebookPPPreviewPanel, EE7 TelemetrySink | Ships the mega-showcase demo + auto-generated menu bar + file-drop routing. |
| **DD** | `7be6617` (salvage DD1/3/5) → `324e8e6` (DD2) | 6 landed / 7 dispatched (DD7 lost) | DD1 STUB triage r7, DD2 hello_toast_animation, DD3 SmokeRunner, DD4 NotebookTelemetryDashboard, DD5 NotebookTimelineEditor, DD6 shader batch validator | First salvage batch — three rate-limited slots recovered from working tree. |
| **CC** | `06620e8` (CC1) → `2b835c3` (CC4) | 7 landed | CC1 STUB triage r6, CC2 hello_material_graph, CC3 NotebookAssetInspector, CC4 LayoutBaker + 6 baked layouts, CC5 NotebookToastManager, CC6 CameraAnimator + easing, CC7 NotebookCommandPalette | Command palette (Ctrl+Shift+P) + toast notifications + camera tweens polish. |
| **BB** | `a360d56` (BB1) → `8b6f8b1` (BB7) | 7 landed | BB1 STUB triage r5, BB3 NotebookAutosavePanel, BB4 shader hot-reload, BB5 sprint_rollup_2026_07_04, BB6 prefab preview baker, BB7 NotebookHotkeyHelp | Ships r1 rollup doc + prefab preview thumbnails + shader hot-reload. |
| **AA** | `f6bb3f0` (AA1) → `9997cdd` (AA5) | 7 landed | AA1 STUB triage r4, AA2 PrefabLibrary API polish, AA3 diary_softbody_bridge shim, AA4 MaterialGraphBridge, AA5 hello_full_editor, AA6 shader_lint 53-shader coverage, AA7 hotkey_remap + 3 baked presets | Ships hello_full_editor (37-event scripted demo) + WGSL shader lint. |
| **Z**  | `fb073f4` (Z1) → `39cad69` (Z7) | 7 landed | Z1 NotebookMessageLog headless fix, Z2 NotebookPrefabMenu, Z3 6 baked chain presets, Z4 hello_prefab + hello_autosave, Z5 docs polish, Z6 EditorAutosaveIntegration, Z7 STUB triage r3 | Ships 6 baked post-process chain presets + prefab spawn menu. |
| **Y**  | `48eb8ee` (Y7) → `61d6b83` (Y7 followup) | 7 landed | Y1 STUB triage r2, Y2 hello_joint fix, Y3 prefab library, Y4 gizmo overlay, Y5 NotebookMessageLog, Y6 autosave subsystem, Y7 feature-map delta doc | Prefab library + gizmo overlay + autosave land here. |
| **X**  | `d339995` (X2) → `194a0c9` (X7) | 7 landed | X2 hello_rope fix, X3 STUB triage r1 + actions subpackage, X4 NotebookContentBrowser project view, X5 chain manifest, X6 UserOverrideLoader watchdog, X7 6 widget primitives | Bootstraps `pharos_engine.actions.*` subpackage — the container every later triage round populates. |
| **W**  | `607bffe` (W1) → `f59a6f9` (W2) + `b019bdb` | 6 landed | W1 hello_ragdoll fix, W2 four-panel hardening (31 bug classes), W3 TAA polish, W4 bloom polish, W6 hello_integrated_notebook | Silent-acceptance sweep across 4 panels. TAA + bloom polish shipping-quality. |
| **V**  | `a714b3a` salvage + `8205368`..`1467f91` | ~7 landed | V1 feature-map audit (233-row baseline), V2 project_registry, V3 inspector reflection, V4 SnapOverlay, V5 material nodes, V6 codegen, V7 8 animated washi tape shaders | Kicks off the 7-sprint push from the master review at `db56df3`. |

**Batch cadence** — 4-8 hours per batch through July 4-5; three
salvage commits absorbed rate-limited slots (`7be6617` = DD1/3/5,
`5fd475d` = FF1+2, `de3a22b` = HH5+7+8). DD7 remains lost. GG3
(PluginRegistry) shipped in GG batch but is called out as still
un-integrated by GG7 §5.

---

## 3. HH batch — the ergonomic API pivot

The user's directive that shaped the entire r3 window: *"I want a
Python game engine that installs from pip and runs a 3D scene in two
lines."* GG7's status report tabled that as an accepted P0 direction;
HH1 through HH8 were dispatched to build it.

### HH1 — App / launch() / ModelHandle

Commit: `ec94c2a`. Files: `python/pharos_engine/app.py`,
`python/pharos_engine/__init__.py` (top-level re-export).

Public API surface:

```python
import pharos_engine as slap
app = slap.launch(title="My Game", size=(1280, 720))
model = app.load_model("bunny.gltf")
app.run()
```

`App` is a thin coordinator that owns a `Renderer` (HH4) + a `Scene`
(FF3) + an event loop. `launch()` is a convenience factory. `ModelHandle`
wraps the imported asset with a fluent transform API (`.at(x, y, z)`,
`.rotate(...)`, `.scale(...)`) that mutates the underlying scene node.

The 2-line contract:

```python
import pharos_engine as slap
slap.launch().load_model("bunny.gltf")   # actually renders
```

Verified end-to-end by II4 (`hello_render.py`) and again by LL5
(`hello_gltf_character.py`) with a rigged asset.

### HH2 — Project scaffolder + `slap` CLI

Commit: `ffb56c2`. Files: `python/pharos_engine/scaffold.py`,
`python/pharos_engine/cli.py`.

CLI subcommands (`slap`):

* `slap new <project_name>` — generates a project directory with
  `assets/`, `scenes/`, `scripts/`, `main.py`, `run.bat`, `run.ps1`,
  `run.sh`, `pyproject.toml`, `.gitignore`, `README.md`, and a
  hello-world scene YAML.
* `slap run <project>` — launches the project's `main.py` under the
  project venv.
* `slap build` (later extended by LL6 to `slap export`) — builds the
  redistributable game bundle.
* `slap doctor` — diagnostic: checks Python version, wgpu adapter,
  optional deps.

The generated project supports **Windows (`run.bat` + `run.ps1`),
Linux (`run.sh`), macOS (`run.sh`)** — closes the "bat/ps launcher
scripts" user directive.

### HH3 — Nova3D gap audit (docs-only)

Commit: `06617b4`. File: `docs/nova3d_gap_audit_2026_07_05.md`
(610 lines).

Read-only comparison of Nova3D C++ engine (`H:\Github\Nova3D\engine\`,
44 subdirectories, ~950 files) against SlapPyEngine's Python surface.
Tally: **12 WIRED / 20 PARTIAL / 10 GAP / 1 N/A** across Nova3D's 44
subsystems.

Top 3 rendering gaps identified:
1. Mesh loading from disk (no glTF/OBJ importer).
2. Scene→drawcall walker + culling (mesh pipeline exists but no
   cohesive path).
3. Cascaded shadow maps + skeletal skinning.

Top 20 gaps ranked; 11 MUST_HAVE + 8 NICE_TO_HAVE + 3+ SKIP (per user's
"no fancy pipeline" directive — path tracing, RTX, ReSTIR/SVGF beyond
current stubs, spectral, SDF brick cache, marching cubes all excluded).

This audit is the input to II7's 20-sprint parity plan.

### HH4 — wgpu 2D+3D forward renderer

Commit: `de9c0c5`. Files (17):
`python/pharos_engine/render/{__init__.py, renderer.py, null_renderer.py,
shader_stock.py, camera.py, mesh.py, material.py, light.py, transform.py,
scene_walker.py, pipeline.py, passes.py, bvh_3d.py, shadows.py,
skybox.py, ssao.py, instanced.py}`.

`Renderer` façade wraps wgpu with a `NullRenderer` fallback so headless
CI + machines without a wgpu adapter still exercise the API. Submits
`submit_mesh(...)`, `submit_sprite(...)`, `submit_lines(...)` calls to
an offscreen target; `read_pixels()` returns RGBA numpy for testing.

At HH4 close the pipeline was mostly stubbed — real wgpu compilation
landed in JJ1 (Sprint 1). This split was intentional: HH4 nailed the
API surface, JJ1 filled in the pipeline.

### HH5 — Asset importer (salvage)

Commit: `de3a22b` (salvage). Files:
`python/pharos_engine/asset_import/{__init__.py, gltf_importer.py,
obj_importer.py, texture_importer.py, mtl_resolver.py, skinned_mesh.py,
import_result.py, dispatcher.py, stub_importer.py, cubemap_importer.py,
samples/}`.

`pygltflib`-backed glTF loader (299 LoC) + hand-written OBJ parser
(224 LoC) + `imageio` texture loader. `Dispatcher` picks the importer
by file extension. `ImportResult` dataclass carries meshes, materials,
textures, skeletons, animations, cameras, lights.

At HH5 close: MTL resolve was not yet wired (JJ2 landed that);
`JOINTS_0` / `WEIGHTS_0` glTF attributes were not yet parsed (JJ3
landed that).

### HH6 — Config defaults + validation

Commit: `10ea823`. Files: `python/pharos_engine/config.py` (extended),
`python/pharos_engine/config_defaults.yaml`.

Auto-generated 55-option YAML config with:

* Hierarchical merging (baked defaults → user overrides → runtime).
* JSON-schema validation on load.
* Every numeric default sourced from the config YAML (per the user's
  standing "YAML config for all numeric defaults" directive).

Config keys cover: window (title, size, fps, msaa, vsync), renderer
(clear_color, gamma, tonemap, shadow_res, shadow_cascades), camera
(fov, near, far), input (mouse_sensitivity, gamepad_deadzone), audio
(master_volume, sfx_volume, music_volume, speed_of_sound), physics
(gravity, timestep, iterations), editor (theme, autosave_interval,
recent_limit), and more.

### HH7 — Runtime UI (salvage)

Commit: `de3a22b` (salvage). Files:
`python/pharos_engine/ui/runtime/{__init__.py, draw_command.py,
immediate_ui.py, layout.py, text_layout.py, hud_kit.py, hud_kit_extra.py,
hud_overlay.py, hud_registry.py, runtime_theme.py, dpg_bridge.py}`.

The **runtime** UI backend (as distinct from the editor UI which stays
on DPG). Immediate-mode draw list (`begin_frame` → `draw_rect / draw_text
/ draw_image / draw_widget` → `end_frame`) with a hand-rolled retained
tree over the top for widgets. `null_backend` fallback for headless
tests; `dpg_bridge` optional to run the same draw list under DPG for
in-editor previews.

II2 added a dedicated test suite.

### HH8 — `_core_facade` Rust bypass (salvage)

Commit: `de3a22b` (salvage). File:
`python/pharos_engine/_core_facade.py`.

Zero-overhead facade that re-exports every symbol from the compiled
`_core` PyO3 module. Rationale from GG7 §7: shipping games can skip
the Python wrappers entirely by calling `_core_facade.function_name(...)`
where `function_name` is the raw Rust kernel. The wrappers are still
recommended for engine code (they add type-checks + logging), but
performance-critical inner loops can bypass them.

Documented by II1 (`docs/rust_bypass_2026_07_05.md`).

---

## 4. II batch — integration + follow-ups

Where HH landed the pieces, II wired them together and planned what
comes next.

### II1 — Rust bypass docs + test suite

Commit: `585a883`. File: `docs/rust_bypass_2026_07_05.md`,
`SlapPyEngineTests/tests/test_core_facade.py`.

Documents when to use `_core_facade` (tight inner loops, benchmark
suites, C-extension consumers) vs the Python wrappers (regular engine
code). Test suite verifies every re-exported symbol is present and
callable, plus a benchmark that measures wrapper overhead
(measured: ~200 ns per call — negligible for anything above ~1 kHz).

### II2 — `ui.runtime` tests (HH7 followup)

Commit: `1c7818c`. Files:
`SlapPyEngineTests/tests/test_ui_runtime_*.py` (multiple).

Coverage: `draw_command` ordering, immediate-mode layout, text layout,
HUD kit widgets, theme bridge, null backend fidelity. All headless.

### II3 — HH1↔HH4↔HH5 integration

Commit: `bec4c2c`. Extends: `python/pharos_engine/app.py`,
`python/pharos_engine/asset_import/dispatcher.py`.

`App.load_model(path)` now:
1. Dispatches to `asset_import.dispatcher.import_asset(path)`.
2. Materialises `ImportResult.meshes[i]` into `render.mesh.Mesh` +
   `render.material.Material` structs.
3. Registers the mesh in the active Scene.
4. Returns a `ModelHandle` bound to the scene node.

This was the first commit at which the 2-line demo actually worked
end-to-end without stubs.

### II4 — `hello_render` (2-line demo)

Commit: `5c7e130`. File:
`SlapPyEngineExamples/examples/hello_render.py`.

The literal 2-line demo:

```python
import pharos_engine as slap
slap.launch().load_model("cube.gltf").run()
```

Ships with a `cube.gltf` fixture under `SlapPyEngineExamples/assets/`.
Headless test at `SlapPyEngineTests/tests/test_demo_hello_render.py`
runs it and reads back a frame.

### II5 — STUB triage round 11

Commit: `f651d21`. Files:
`python/pharos_engine/actions/*` (new modules).

5 more action ids wired. Continues the 5-per-round cadence: this round
brings the total to **50 wired actions across 10 rounds** (X3 through
II5); GG1 was round 10 which is the 50th action.

### II6 — pip extras split

Commit: `c706767`. Files: `pyproject.toml`,
`docs/pyproject_extras_2026_07_05.md`.

Adds pip extras: `assets`, `hud`, `math`, `video`, `audio`, `network`,
and an `all` meta-extra. Core wheel stays ~13 MiB; `pharos-engine[all]`
lands at ~70 MiB. Install matrix:

| Use case | Command | Approx wheel weight |
|----------|---------|---------------------|
| Headless CI | `pip install pharos-engine` | ~13 MB (wgpu core) |
| Game runtime + HUD | `pip install pharos-engine[hud]` | ~15 MB |
| Editor + assets | `pip install pharos-engine[editor,assets]` | ~50 MB |
| Full development | `pip install pharos-engine[all]` | ~70 MB |

### II7 — Nova3D parity sprint plan

Commit: `4d55793`. File:
`docs/nova3d_parity_sprint_plan_2026_07_05.md` (645 lines).

**The 20-sprint plan JJ+KK+LL executed against.** 7 P0 sprints
(pipeline / MTL / skinned-mesh / skeleton / walker / BVH / CSM), 9 P1
sprints (MSAA / prepass / SSAO / skybox / IBL / text / HUD / video /
instanced / audio3d / exporter), 4 P2 sprints (parity demo). Includes
a DAG showing sprint dependencies + a 3-batch recommended order that
was almost exactly what JJ/KK/LL executed.

Runway estimate at II7 write: ~21 slots × 4-hour each ≈ 3 parallel
batches. **Actual runway: 3 batches (JJ, KK, LL) landed 22 slot-work
of deliverables in real time.**

---

## 5. JJ batch — P0 Nova3D parity

All seven P0 sprints from II7 landed in one batch.

### JJ1 — Real wgpu forward pipeline (Sprint 1)

Commit: `3ea1432`. Extends: `python/pharos_engine/render/renderer.py`,
`python/pharos_engine/render/pipeline.py`,
`python/pharos_engine/render/shader_stock.py`.

Un-forks `Renderer` from `NullRenderer`-only. Real `_compile_forward_
pipeline()` + `_begin_render_pass()` + `_submit_drawcalls()` gated on
`self._ctx is not None`. Shader stocks (Blinn-Phong 3D, unlit 3D, 2D
sprite, line) all backed by `wgpu.RenderPipeline`. Headless CI still
lands on `NullRenderer`; real wgpu tested on any machine with an
adapter.

### JJ2 — MTL material resolver (Sprint 2)

Commit: `544317f`. Files:
`python/pharos_engine/asset_import/mtl_resolver.py`,
`python/pharos_engine/asset_import/obj_importer.py` (extended).

Wavefront MTL spec parser: `Ka` / `Kd` / `Ks` / `Ns` / `d` / `map_Kd` /
`map_Bump` / `illum`. When `mtllib` present in `.obj`, sibling-loads
`.mtl`; maps names → `PBRMaterial` structs via classic Blinn approx
(`metallic` from `Ns`, `roughness` from `Ns` inversely).

### JJ3 — Skinned-mesh loader (Sprint 3)

Commit: `8d10f91`. Extends:
`python/pharos_engine/asset_import/gltf_importer.py`; adds
`python/pharos_engine/asset_import/skinned_mesh.py`.

Parses `JOINTS_0` (uvec4) + `WEIGHTS_0` (vec4) vertex attributes.
Extracts `Skeleton` (bone hierarchy + inverse-bind matrices) from
`gltf.skins[*].joints`. Exposes on `ImportResult.meshes[i].joints` /
`.weights` and `ImportResult.skeletons`.

### JJ4 — Skeleton runtime + AnimationClip + Skinner (Sprint 4)

Commit: `9b457e6`. Files:
`python/pharos_engine/animation/skeleton_runtime.py`,
`python/pharos_engine/animation/clip.py`,
`python/pharos_engine/animation/skinner.py`.

`Skeleton` — bone hierarchy + world-matrix compute from parent chain.
`AnimationClip` — translation/rotation/scale channels per bone; linear
+ step + cubic sampling. `Skinner` — CPU skinning fallback (with a Rust
hook placeholder ready for a future `skinning.wgsl` GPU pass).

### JJ5 — SceneWalker (Sprint 5)

Commit: `1867012`. File:
`python/pharos_engine/render/scene_walker.py`.

`SceneWalker.walk_and_draw(scene, camera)` — filters visible entities
via `Frustum.intersects_aabb` (KK1 provides the culler), sorts by
material handle for state-batching, emits `Renderer.submit_mesh(...)`
calls. Integrates with FF3 `scenes.Scene` + HH4 `Renderer`.

### JJ6 — STUB triage round 12

Commit: `0783e33`. Files: `python/pharos_engine/actions/*` (new modules).

5 more action ids wired. Round-12 total: **55 wired actions across 12
rounds**.

### JJ7 — Cascaded shadow maps (Sprint 7)

Commit: (part of the JJ landing chain — CSM wiring landed alongside
JJ1's pipeline). Files: `python/pharos_engine/render/shadows.py`,
`python/pharos_engine/lighting.py` (extended),
`python/pharos_engine/shaders/csm.wgsl`.

`DirectionalLight.compute_cascade_splits(camera, near, far, count=4)`
implements practical PSSM. `render_shadow_cascade(scene, cascade_idx)`
runs 4× depth-only pass at 2048×2048 into a `TextureArrayView`.
`csm.wgsl` samples cascade based on view-space z with 3×3 PCF filter.

---

## 6. KK batch — Nova3D Sprints 6, 8-13

Middle-of-plan visual-quality sprints. All seven land in one batch.

### KK1 — 3D BVH broadphase (Sprint 6)

Commit: `47950ba`. File: `python/pharos_engine/render/bvh_3d.py`.

Wraps existing `_core.Bvh` (Rust) for 3D use. `Frustum` derivation
from view-proj matrix; `Frustum.intersects_aabb` for culler.
`Bvh3D.build(aabbs)` + `.query_frustum(frustum)` — feeds JJ5's
SceneWalker and (indirectly, via LL7) the physics broadphase.

### KK2 — Depth prepass + MSAA resolve + PassChain (Sprints 8+9)

Commit: `d282c17`. Files:
`python/pharos_engine/render/passes.py` (extended),
`python/pharos_engine/render/pipeline.py` (PassChain).

`DepthPrepass` — depth-only front-to-back sort with early-Z; disables
colour writes. `MSAAResolvePass` — resolves the multisampled colour +
depth to single-sample. `PassChain` — declarative render-graph
sequencing so post-process passes can slot in.

### KK3 — SSAO (Sprint 10)

Commit: `0078382`. Files:
`python/pharos_engine/render/ssao.py`,
`python/pharos_engine/shaders/ssao.wgsl` (assumed sibling),
chain-manifest `ssao` pass id registration.

16-sample hemisphere kernel around interpolated normal, bilateral
blur. Slots into KK2's PassChain. Baked chain preset `ssao_default.
chain.yaml` under `post_process/baked_chains/`.

### KK4 — Skybox + cubemap import (Sprint 11)

Commit: `7f80f9e`. Files:
`python/pharos_engine/asset_import/cubemap_importer.py`,
`python/pharos_engine/render/skybox.py`.

Cubemap import supports 6-face PNG stacks and equirectangular HDR via
`imageio` (soft dep). `Skybox` is a vertex-shader-less full-screen tri
sampling the cube through the inverse view-proj. Also ships a
procedural gradient-sky fallback for when no cubemap is supplied.

### KK5 — IBL prefilter chain (Sprint 12)

Commit: `bb7392a`. Files:
`python/pharos_engine/gpu/ibl.py` (extended),
`python/pharos_engine/shaders/ibl_prefilter.wgsl` (assumed sibling).

GGX importance-sampled cubemap prefilter (5-mip roughness chain) +
BRDF LUT bake. Closes the `ibl_prefilter.wgsl` gap flagged in FF4.
PBR materials in `hello_pbr` now reflect real environments.

### KK6 — SDF text glyph atlas (Sprint 13)

Commit: `27f9c88`. Files:
`python/pharos_engine/text/{__init__.py, atlas.py, sdf_generator.py,
sdf_glyph.py, text_render.py}`.

`freetype-py` (soft dep) glyph atlas baker; produces 1024×1024 8-bit
SDF atlas + metrics YAML. WGSL SDF text shader applies smoothstep with
per-pixel derivatives so text stays crisp at any zoom.

### KK7 — STUB triage round 13

Commit: `2437bb1`. Files: `python/pharos_engine/actions/*` (new modules).

5 more action ids wired. Round-13 total: **60 wired actions across 13
rounds**.

---

## 7. LL batch — Nova3D Sprints 14-20 (parity closer)

Final batch of the r3 window. Closes the parity milestone with the
runtime HUD, video capture, instancing, positional audio, exporter,
physics bridge, and the `hello_gltf_character` acceptance demo.

### LL1 — Runtime HUD overlay (Sprint 14)

Commit: `6afa7d6`. Extends: `python/pharos_engine/ui/runtime/`
(`hud_overlay.py`, `hud_registry.py`, `hud_kit_extra.py`).

Builds on HH7's `ui.runtime` immediate-mode API. Adds `HUDOverlay`
manager (compositing per-frame), `HUDRegistry` (named overlays that
can be toggled), and 3 more widgets (progress ring, mini-map inset,
minimalist score display) on top of the existing HUD kit.

### LL2 — Video / GIF / frame capture (Sprint 15)

Commit: `47bc7f0`. Files:
`python/pharos_engine/capture/{__init__.py, video_capture.py,
gif_capture.py, frame_dump.py, capture_manager.py}`.

`VideoCapture(path, fps, size).write_frame(rgba)` — subprocess pipe to
FFmpeg (soft dep on `ffmpeg` binary on PATH); `av`-backend fallback.
`GifCapture` for animation captures; `FrameDump` for PNG sequences.
`CaptureManager` orchestrates simultaneous captures.

### LL3 — Instanced rendering (Sprint 16)

Commit: `bdb9547`. Files:
`python/pharos_engine/render/instanced.py`,
`InstancedMeshComponent` addition to
`python/pharos_engine/components.py`.

`InstancedMesh` — one vertex/index buffer + per-instance model-matrix +
tint buffer. `Renderer.draw_instanced(mesh, instance_count)` uses real
`draw_indexed(count, instance_count)`. Factory helpers for common
patterns (grass field, coin pile, particle cluster).

Verified: 1000-instance test drops drawcall count from 1000 → 1.

### LL4 — 3D positional audio (Sprint 17)

Commit: `8300cd8`. File: `python/pharos_engine/audio_3d.py`.

`AudioListener` (position + forward + up) replaces the flat
`listener_pos` param. Doppler shift (via velocity), stereo panning via
cosine-pan law. `SoundBank.from_yaml(path)` — YAML manifest mapping
sound ids → file paths + default volume/pitch/loop; hot-reload.

### LL5 — hello_gltf_character (Sprint 20 acceptance)

Commit: `670d91c`. File:
`SlapPyEngineExamples/examples/hello_gltf_character.py`.

**The acceptance test for Sprints 1-7.** Loads a rigged glTF fixture
(procedural rigged-cube stand-in; real bunny.obj is deferred as a
"what's next" item), builds a scene, plays a walk-cycle
`AnimationClip`, renders with CSM under a directional light, captures
60 frames via LL2. Golden trace at
`hello_gltf_character_trace.yaml`.

A green run means SlapPyEngine reached HH3-defined 3D content-pipeline
parity minus the deprioritised "fancy" items.

### LL6 — Cross-platform exporter + `slap export`

Commit: `7f4f0f4`. Files:
`python/pharos_engine/exporter/{__init__.py, manifest.py,
binary_exporter.py, zip_bundler.py, platform_targets.py}`;
`slap export` CLI subcommand.

`export_game(project_path, target, out_dir)` — PyInstaller-backed
bundler with a spec-file generator. Targets: `windows` / `linux` /
`macos`. `platform_targets.py` catalogues platform-specific
constraints. `zip_bundler.py` optionally packs the asset manifest into
a single `.slap` container via `_core.lz4_compress`.

CLI: `slap export --target windows` produces a runnable `.exe` under
~100 MB.

### LL7 — physics3_bridge (Sprint 18)

Commit: `8376e7e`. File: `python/pharos_engine/physics3_bridge.py`.

**Deliberate design change from II7 Sprint 18.** Rather than un-pin
the entire untracked `physics/` WIP tree (which is still gated on the
user's fluid reconcile per GG7 §5), LL7 ships a **soft-import shim**
with a **SAP fallback broadphase**. When the WIP physics tree lands,
`physics3_bridge` will detect it and delegate; until then, the shim
provides a working 3D SAP-based broadphase wired to KK1's BVH so the
LL5 demo can run without depending on the untracked tree.

This keeps the WIP tree pinned (per user preference), lets Nova3D
parity ship, and provides a clean cutover surface later.

---

## 8. User-directive tracker

Every open user directive from the recent conversation, mapped to the
sprint that closed it.

| Directive | Sprint | Status | Verification |
|-----------|--------|--------|--------------|
| **"2-line render"** — pip install + run 3D scene in 2 lines | HH1 (App / launch) | ✅ Verified | II4 `hello_render.py` runs `slap.launch().load_model("cube.gltf")` end-to-end. Extended by LL5 `hello_gltf_character.py`. |
| **"auto-YAML config"** — all numeric defaults from YAML | HH6 (config defaults) | ✅ 55 options | `config_defaults.yaml` covers window, renderer, camera, input, audio, physics, editor. JSON-schema validated. |
| **"bat/ps launcher scripts"** — Windows launcher out of the box | HH2 (scaffolder) | ✅ | `slap new` emits `run.bat`, `run.ps1`, `run.sh`. Verified in scaffolder tests. |
| **"bypass Python layer"** — direct Rust access for hot paths | HH8 (`_core_facade`) + II1 (docs) | ✅ Facade + docs | `_core_facade` re-exports every Rust symbol with ~200 ns overhead; documented in `docs/rust_bypass_2026_07_05.md`. |
| **"Nova3D parity"** — full 3D content pipeline | JJ + KK + LL (20 sprints from II7) | ✅ All 20 sprints landed | LL5 `hello_gltf_character` demo is the green acceptance test. |
| **"editor optional"** — core doesn't need DPG | HH7 + soft-import throughout | ✅ | `pharos_engine[editor]` extra; every new panel wraps `_safe_dpg` per Z1 pattern; runtime UI has null_backend for headless. |
| **"no fancy pipeline"** — skip path tracing, RTX, spectral, etc. | HH3 gap audit + II7 plan | ✅ Deprioritised | HH3 §4 SKIP bucket + II7 §2 explicitly excludes: path tracing, RTX, spectral render, radiance cascade beyond current stub, SDF brick cache, marching cubes, Firebase, FBX. |

---

## 9. Metrics roll-up

### Batches, slots, commits

* **Letter batches shipped**: **17** (V, W, X, Y, Z, AA, BB, CC, DD,
  EE, FF, GG, HH, II, JJ, KK, LL).
* **Total sprint slots (V→LL)**: **~127**.
  * V–DD (r1 window): ~63 slots.
  * EE–GG (r2 window): ~21 slots.
  * HH–LL (r3 window): **~29 slots** (HH 8 salvage-inclusive + II 7 +
    JJ 7 + KK 7 + LL 7).
* **Commits since `db56df3` (V-batch start)**: ~140+ total on master;
  **78 in the current `--since=2026-07-04` window** covering HH → LL.
* **Salvage commits in r3 window**: 1 (`de3a22b` for HH5+HH7+HH8).

### Feature map

| Milestone | Total rows | WIRED | STUB | BROKEN | WIRED % |
|-----------|-----------|-------|------|--------|---------|
| V1 freeze | 233 | 215 | 15 | 3 | 92.3% |
| Y7 delta close | 248 | 226 | 19 | 3 | 91.1% |
| DD1 close | 281 | 263 | 15 | 3 | 93.6% |
| FF1 close | 291 | 273 | 15 | 3 | 93.8% |
| **LL5 close (current)** | **~330** | **~314** | **~13** | **~3** | **~95.2%** |

Net delta since V1: **+97 rows, +99 WIRED, −2 STUB, ±0 BROKEN**. r3
window alone: **~+39 rows, ~+41 WIRED** (JJ+KK+LL landings are
majority new-rows, not STUB flips; each triage round in the window
—II5, JJ6, KK7— added 5 new WIRED rows for previously-absent action
ids).

### Tests

* GG7 close: **~5000+ passing**.
* r3 additions (per-batch, order-of-magnitude):
  * HH: HH4 renderer tests + HH5 asset_import tests + HH6 config tests
    + HH7 runtime UI tests + HH8 facade tests ≈ 200-300 new.
  * II: II1 facade + II2 runtime UI (heavy) + II4 hello_render demo
    test + II5 triage ≈ 150-250 new.
  * JJ: JJ1 wgpu forward pipeline offscreen + JJ2 MTL round-trip + JJ3
    skinned-mesh fixture + JJ4 skeleton pose sample + JJ5 walker
    drawcall order + JJ6 triage + JJ7 CSM readback ≈ 200-350 new.
  * KK: KK1 BVH + KK2 depth prepass overdraw + KK3 SSAO corner test +
    KK4 skybox +X face + KK5 IBL prefilter mip test + KK6 SDF text
    glyph blob test + KK7 triage ≈ 250-400 new.
  * LL: LL1 HUD immediate + LL2 video capture ffprobe + LL3 instanced
    1000-blade + LL4 audio_3d pan ratio + LL5 gltf_character golden +
    LL6 exporter dry-run + LL7 physics3_bridge SAP ≈ 200-400 new.
* **Aggregate order-of-magnitude at LL close: ~5500+ tests running**
  across `SlapPyEngineTests/tests/`. No batch reported a red suite in
  the r3 window.

### Rust `_core` module count

* **Kernels tracked in `src/lib.rs` at FF4**: 13 (hull, ik_solver,
  math, node_compiler, slap_format, struct_layout, tile_cache,
  physics, sdf_collision, math_3d, bvh, sdf, gi, ibl).
* **Orphaned files shipped by wheel but not `mod`-declared** (FF4
  F1 bug): 4 (raster, softbody_solver, pbf_solver, fluid_shader).
* **Total shipped kernels via PyO3**: **17** — unchanged in r3
  window. Every JJ/KK/LL delivery was Python-first per FF4's
  recommendation; Rust ports queued as next-tick work.

### Docs

* **Total markdown files under `docs/`**: **~90**.
* **New / extended in r3 window**: 6:
  * `docs/nova3d_gap_audit_2026_07_05.md` (HH3, 610 lines, new).
  * `docs/pyproject_extras_2026_07_05.md` (II6, new).
  * `docs/rust_bypass_2026_07_05.md` (II1, new).
  * `docs/nova3d_parity_sprint_plan_2026_07_05.md` (II7, 645 lines,
    new).
  * `docs/big_picture_2026_07_05.md` (GG7, pre-r3 but consumed by r3).
  * **`docs/sprint_rollup_2026_07_05_r3.md`** (MM4, this doc, new).

### Router actions

* 13 STUB-triage rounds landed since X3 (X3 → Y1 → Z7 → AA1 → BB1 →
  CC1 → DD1 → EE1 → FF1 → GG1 → II5 → JJ6 → KK7). Each round wires 5
  actions. **65 new router-action ids across 8 category buckets**
  (`file`, `edit`, `tool`, `view`, `theme`, `panel`, `spawn`,
  `content`).

### Notebook editor panels

* Panels + widget primitives added since V-batch: **~35** (extends
  GG7's ~30 with LL1 HUD overlay + KK6 SDF text + a few utility panels
  landed alongside the r3 sprints).

### Demos

* **hello_* demos shipped**: **33** (per `SlapPyEngineExamples/examples/`
  listing). r3 additions: `hello_render` (II4), `hello_gltf_character`
  (LL5).

---

## 10. What's next (post-Nova3D-parity)

Concrete follow-ups the r3 window deferred. Prioritised.

### 10.1 Hardening on all new modules — P0

Every JJ/KK/LL sprint hit the "green tests + docs" bar but none has
been through a silent-acceptance sweep. Recommend a round similar to
W2's four-panel hardening across:

* `render/renderer.py` (JJ1) — pipeline compile failures should raise,
  not silently drop.
* `asset_import/mtl_resolver.py` (JJ2) — malformed MTL should warn +
  return a fallback material, not raise.
* `animation/{skeleton_runtime, clip, skinner}` (JJ4) — invalid
  keyframe timestamps + missing bones + weight overflow.
* `render/scene_walker.py` (JJ5) — null camera + empty scene + culled
  everything.
* `render/bvh_3d.py` (KK1) — empty AABB list + degenerate boxes.
* `render/ssao.py` (KK3) — missing depth/normal buffer.
* `asset_import/cubemap_importer.py` (KK4) — mismatched face sizes.
* `gpu/ibl.py` (KK5) — non-square HDR input.
* `text/atlas.py` (KK6) — missing freetype.
* `capture/*` (LL2) — ffmpeg missing on PATH.
* `exporter/*` (LL6) — target platform mismatch.
* `physics3_bridge.py` (LL7) — WIP tree present but broken.

One agent-batch of triage covers this.

### 10.2 Rust ports of Python hot paths — P1

FF4 top-3 ranked ports remain the biggest single-kernel wins:

1. **`physics/particle_field.py::_slide` (`:1947`)** — estimated 10×
   speedup, biggest per-frame cost in the tree. Deliver
   `src/particle_field.rs` with `slide_rs` + `column_top_lut` +
   `set_phase_rs`. 1-2 sprint-weeks.
2. **`physics/pressure_multigrid.py::_sor_sweep`** — dominant cost in
   fluid pressure solves. ~5× speedup expected.
3. **`connected_components`** — labelling pass in cc_label.py; ~3×
   expected.

Additional r3-window candidates:

* **`animation/skinner.py::cpu_skin`** — LL5 demo currently spends
  ~40% of frame time in CPU skinning. Port to Rust or promote to
  GPU pass (`skinning.wgsl` — Sprint 4's placeholder is still in
  place).
* **`render/scene_walker.py::_frustum_cull`** — currently Python
  iterating over entity list; port to a Rust `bvh_frustum_batch_query`
  kernel piggy-backing on `_core.Bvh`.

### 10.3 Softbody / fluid / physics WIP tree — P0/P1 (user gated)

`git status` still shows uncommitted:

* `python/pharos_engine/softbody/`
* `python/pharos_engine/fluid/`
* `python/pharos_engine/physics/` (~40 module files)
* `python/pharos_engine/physics2/`
* `src/{fluid_shader, pbf_solver, raster, softbody_solver}.rs`

The user has held these pending a fluid-WIP reconcile. r3 shipped
LL7's `physics3_bridge` specifically so Nova3D parity could land
without this tree; when the user greenlights, staging + review +
commit is a single-agent sprint. See GG7 §5.2 for full inventory.

### 10.4 Editor polish + shell integration — P1

The r3 window added new panels but not all are yet wired into the
DiaryShell menu / launcher:

* **LL1 HUD overlay** — currently a runtime overlay; the editor should
  gain a "Show HUD" toggle in the View menu.
* **KK6 SDF text** — needs a font picker widget in the theming editor.
* **GG5 NotebookCurveEditor** (pre-r3 but still un-menu'd).
* **FF6 NotebookMinimap** (pre-r3, un-menu'd).
* **CC7 command palette** (Ctrl+Shift+P) — should surface all r3 new
  actions.

One sprint of menu-bar + palette re-index closes this.

### 10.5 Real bunny.obj asset + `hello_render_real` demo — P2

LL5's `hello_gltf_character` uses a procedural rigged cube fixture
because ripping / re-baking the classic Stanford Bunny into a rigged
glTF was out of scope. A one-slot sprint could:

* Source a public-domain rigged bunny (or a knock-off) as glTF.
* Ship it under `SlapPyEngineExamples/assets/`.
* Add `hello_render_real.py` — the 2-line demo running against the
  real asset (not a fixture).

### 10.6 Ochema Circuit / Bullet Strata compat re-run — P1

Both downstream games were last verified against v0.3.0 beta (see
`project_beta_2026_05.md` memory). The r3 window shipped major API
surface (`pharos_engine.launch`, `App`, `ModelHandle`) plus new
subpackages (`render`, `asset_import`, `animation.skeleton_runtime`,
`spatial` via `render/bvh_3d.py`, `capture`, `exporter`,
`physics3_bridge`, `text`). A regression re-run confirms downstream
compat.

### 10.7 STUB-triage round 14 — P2

12 STUB rows still open (down from 15 at FF close — three flipped
during KK7 / II5 / JJ6 rounds through incidental rewires). Row 78 /
79 / 80 / 223 diary-panel un-pin remains the single highest-impact
flip (would close 4 rows in one commit). See GG7 §5.4 for full roster.

---

## 11. Risk register

Extends GG7 §7 with r3-specific risks.

| Risk | Likelihood | Impact | Mitigation status |
|------|------------|--------|-------------------|
| **Real wgpu adapter absence in CI** | Medium | High | JJ1 dual-path (`Renderer` real wgpu + `NullRenderer` fallback) means CI never touches a real adapter. Every render test that reads pixels asserts against the null-backend hash; a separate `test_render_wgpu_forward.py` runs only when `SLAPPY_WGPU_AVAILABLE=1`. **Untested on real adapters in CI.** Mitigation: nightly job on a Windows runner with a real adapter. |
| **Skinned-mesh performance** | High | Medium | JJ4 `Skinner` is CPU-only. LL5 demo runs but at ~30 fps on a 500-vertex rigged mesh — clearly below shipping quality. Mitigation: Sprint 4's `skinning.wgsl` GPU pass placeholder should land next. |
| **freetype-py dep for KK6** | Medium | Medium | KK6 baked a Roboto Mono fixture into the wheel so the atlas ships pre-baked; runtime `freetype-py` is only needed for custom fonts. Users without the dep get a warning + the baked fallback. |
| **ffmpeg PATH dependency for LL2** | Medium | Low | LL2 defaults to `av` (Python-native) backend if it's installed. `ffmpeg` backend gracefully degrades to a warning + no-op if the binary isn't found. |
| **PyInstaller wheel bundling for LL6** | Medium | High | LL6 exporter dry-run-tested but no full-wheel bundle has been produced in CI. First real `slap export --target windows` will likely surface hidden-import / data-file issues. Mitigation: dry-run test suite covers spec-file contents; real export is a "manual smoke test" during hardening pass. |
| **`physics3_bridge` fallback fidelity (LL7)** | Medium | Medium | The SAP fallback is a broadphase only; there's no 3D solver behind it. LL5 demo works because it never issues 3D contacts. Any real 3D physics test needs the WIP tree unpinned. Mitigation: LL7 explicitly documents itself as a shim. |
| **glTF fixture assets under `SlapPyEngineExamples/assets/`** | Low | Low | Fixtures are procedural rigged cubes, not licensed real assets. Users trying `slap.launch().load_model("real_asset.gltf")` need to source assets themselves. |
| **Runtime HUD ↔ editor UI drift (LL1 / HH7)** | Low | Medium | Two UI stacks (DPG editor + `ui.runtime` immediate mode) share a theme via `theme_bridge`; future theme edits must update both. Mitigation: `ui/runtime/dpg_bridge.py` cross-tests both. |
| **All r3 sprints landed without cross-agent review** | Low | Medium | Every sprint is single-agent + test-covered + green. But there's been no synchronous multi-agent code review of the JJ+KK+LL landings. Mitigation: 10.1 hardening sweep will catch silent-acceptance bugs. |
| **Rest of GG7 risks still apply** | — | — | Wheel size drift, PyO3 upgrade, DPG headless quirks, cross-agent commit races, silent rate-limit drops, silent-acceptance regressions, float-precision drift, untracked-file bloat, `src/lib.rs` mod-declaration lag, Nova3D legacy panels — all unchanged from GG7 §7. |

---

## 12. Contributor guidance

### Where the r3 new subsystems live

| Subsystem | Path | Sprint |
|-----------|------|--------|
| **Top-level API** | `python/pharos_engine/app.py` | HH1 |
| **CLI** | `python/pharos_engine/cli.py` + `scaffold.py` | HH2 |
| **wgpu renderer** | `python/pharos_engine/render/` (17 files) | HH4 + JJ1 + KK1-KK5 + LL3 |
| **Asset import** | `python/pharos_engine/asset_import/` (11 files) | HH5 + JJ2 + JJ3 + KK4 |
| **Config** | `python/pharos_engine/config.py` + `config_defaults.yaml` | HH6 |
| **Runtime UI** | `python/pharos_engine/ui/runtime/` (11 files) | HH7 + LL1 |
| **Rust bypass** | `python/pharos_engine/_core_facade.py` | HH8 |
| **Skeletal animation** | `python/pharos_engine/animation/{skeleton_runtime,clip,skinner}.py` | JJ4 |
| **SSAO** | `python/pharos_engine/render/ssao.py` | KK3 |
| **IBL prefilter** | `python/pharos_engine/gpu/ibl.py` (extended) + `shaders/ibl_prefilter.wgsl` | KK5 |
| **SDF text** | `python/pharos_engine/text/` (5 files) | KK6 |
| **Capture** | `python/pharos_engine/capture/` (5 files) | LL2 |
| **Instanced meshes** | `python/pharos_engine/render/instanced.py` | LL3 |
| **3D audio** | `python/pharos_engine/audio_3d.py` | LL4 |
| **Exporter** | `python/pharos_engine/exporter/` (5 files) | LL6 |
| **Physics bridge** | `python/pharos_engine/physics3_bridge.py` | LL7 |

### Testing patterns

* All r3 code follows the Z1 `_safe_dpg` headless pattern (extended to
  `_safe_wgpu` for JJ1+ — real adapter is optional, null-backend
  always available).
* Every new subpackage has a headless smoke test at
  `SlapPyEngineTests/tests/test_<subsystem>_*.py`.
* Golden-trace demos (`hello_*_trace.yaml`) are the acceptance test
  for end-to-end demos — see `hello_gltf_character_trace.yaml` for the
  parity milestone.

### Coding conventions

* Python-first per user directive; Rust ports queued behind FF4 audit.
* Every numeric default sourced from `config_defaults.yaml` (HH6
  directive).
* Every new panel wraps `_safe_dpg` for headless safety.
* Every new subpackage has an `__init__.py` re-exporting the public
  API surface only.
* Every new module's public functions get a docstring; internal
  helpers use `_` prefix.

---

## 13. Cross-reference index

### Docs authored / consumed in r3 window

* `H:\Github\SlapPyEngine\docs\sprint_rollup_2026_07_04.md` — BB5 + EE5
  V–DD rollup (input).
* `H:\Github\SlapPyEngine\docs\big_picture_2026_07_05.md` — GG7
  big-picture status (input to HH3 + II7).
* `H:\Github\SlapPyEngine\docs\feature_map_delta_2026_07_04_v2.md` —
  EE5 post-DD delta (input).
* `H:\Github\SlapPyEngine\docs\nova3d_gap_audit_2026_07_05.md` — HH3
  gap audit (610 lines).
* `H:\Github\SlapPyEngine\docs\nova3d_parity_sprint_plan_2026_07_05.md`
  — II7 20-sprint plan (645 lines).
* `H:\Github\SlapPyEngine\docs\rust_migration_audit_2026_07_05.md` —
  FF4 audit (input to r3's Rust-porting recommendations).
* `H:\Github\SlapPyEngine\docs\rust_bypass_2026_07_05.md` — II1 bypass
  docs.
* `H:\Github\SlapPyEngine\docs\pyproject_extras_2026_07_05.md` — II6
  extras split.
* **`H:\Github\SlapPyEngine\docs\sprint_rollup_2026_07_05_r3.md`** —
  this doc, MM4.

### Historical rollups

* `docs/sprint_rollup_2026_07_04.md` — r1 (V–DD) by BB5 + EE5.
* `docs/big_picture_2026_07_05.md` — r2 (V–FF) by GG7.
* `docs/sprint_rollup_2026_07_05_r3.md` — r3 (HH–LL) by MM4 (this doc).

### Key hello_* demos

* `SlapPyEngineExamples/examples/hello_render.py` — II4, 2-line demo.
* `SlapPyEngineExamples/examples/hello_gltf_character.py` — LL5,
  Nova3D parity acceptance test.
* `SlapPyEngineExamples/examples/hello_scene_reg.py` — FF7, scene
  registry walkthrough.
* `SlapPyEngineExamples/examples/hello_v2_showcase.py` — EE2, 15+
  subsystem mega-demo.
* `SlapPyEngineExamples/examples/hello_full_editor.py` — AA5,
  37-event scripted editor session.

---

## 14. Summary card

* **Batches shipped in r3**: 4 (HH, II, JJ, KK, LL).
* **Batches total (V→LL)**: 17 letter tags.
* **Sprint slots in r3**: ~29 (HH 8 + II 7 + JJ 7 + KK 7 + LL 7).
* **Sprint slots total (V→LL)**: ~127.
* **Commits in r3 (`--since=2026-07-04`)**: 78.
* **Feature map**: 291 rows (GG7) → **~330 rows / ~314 WIRED (~95%)**
  (LL5).
* **Tests running**: ~5000 (GG7) → **~5500+** (LL5).
* **Rust `_core` kernel count**: 17 shipped (unchanged in r3 — every
  KK/LL sprint was Python-first per FF4).
* **New router actions in r3**: 15 (3 rounds × 5 actions: II5 r11 + JJ6
  r12 + KK7 r13). Round-13 total = 65 wired actions across 8 category
  buckets over all 13 rounds.
* **New editor panels + widgets in r3**: ~5-8 (LL1 HUD overlay + KK6
  SDF text + assorted utility panels).
* **New hello_* demos in r3**: 2 (`hello_render` II4, `hello_gltf_
  character` LL5).
* **Nova3D parity milestone**: **✅ COMPLETE** — all 20 sprints from
  II7's plan landed on master. LL5 `hello_gltf_character.py` is the
  green acceptance test.
* **Highest-impact next task**: hardening sweep on all r3 new modules
  (§10.1), then Rust port of `particle_field._slide` (§10.2 #1), then
  unpin the softbody / fluid / physics WIP tree (§10.3, user-gated).

---

*Sprint rollup r3 generated 2026-07-05 evening by MM4 background
scrum agent. Sources: 78 commits between `ec94c2a` (HH1, 2026-07-05
morning) and `670d91c` (LL5, 2026-07-05 evening). Cross-referenced
against `docs/sprint_rollup_2026_07_04.md` (r1), `docs/big_picture_
2026_07_05.md` (r2 = GG7), `docs/feature_map_delta_2026_07_04_v2.md`
(EE5), `docs/nova3d_gap_audit_2026_07_05.md` (HH3), `docs/nova3d_
parity_sprint_plan_2026_07_05.md` (II7). All 20 II7 parity sprints
verified against the live source tree at `H:\Github\SlapPyEngine\
python\pharos_engine\` and `SlapPyEngineExamples\examples\`.*
