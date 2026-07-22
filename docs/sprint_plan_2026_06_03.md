# Sprint Plan — 7-Sprint Roadmap to v0.4 (2026-06-03)

> Read-only audit + planning doc. No source-code edits in this sprint cycle —
> only this markdown commit plus the
> [`docs/sprint_5_doc_inventory.md`](sprint_5_doc_inventory.md) index update.
> Each sprint maps one calendar week.
>
> Cross-links: [`docs/roadmap.md`](roadmap.md),
> [`docs/CONTRIBUTING.md`](CONTRIBUTING.md),
> [`docs/engine_surface_v030.md`](engine_surface_v030.md),
> [`docs/architecture_overview.md`](architecture_overview.md),
> [`docs/sprint_7_ship_checklist.md`](sprint_7_ship_checklist.md).

---

## Phase 1 — Functionality survey

### Subpackage classification

Status legend:
**SHIPPED** = production-ready, hardened, hand-authored docs, ≥1 demo,
exercised by test_hardening_*.py and a `docs/api/<name>.md` reference.
**WORKING** = functional, runnable, but lacks one of {hardening / docs /
demo / round-trip parity}.
**SKELETON** = stub or thin pass-through; surface exists but no real
implementation in places.
**GAP** = mentioned in the roadmap or the top-level docstring but
not actually implemented (or actively frozen via the WIP-commit reminder).

| Subpackage | Status | Notes |
|---|---|---|
| `dynamics` | SHIPPED | XPBD substrate, 7 joint kinds, `World`/`SoftBodyWorld`, ragdoll/rope/IK/humanoid builders, JSON round-trip, hardening rounds 7-13. Auto-gen API ref. |
| `studio` | SHIPPED | `Stage` + 5 stage factories + `record()`. 6 flagship demos. Hand-authored API ref. |
| `topology` | SHIPPED | Connected-components / union-find. Hardened, doc'd. |
| `numerics` | SHIPPED | `vcycle_poisson` / `sor_smooth` / `compute_residual`. 2.45x V-cycle win, hardened. |
| `zones` | SHIPPED | `RectZone` / `ThresholdZone` / `ZoneManager` + spatial-hash backend (10.9x). |
| `thermal` | SHIPPED | `HeatField` + `exchange_two_regions`. Hardened. |
| `iso` | SHIPPED | Camera/Cell/Entity/Grid/Scene + `iso.combat` Stone Keep module. |
| `telemetry` | SHIPPED | 86 ns no-sub emit, 6.42x bucket-index dispatch. Hardened. |
| `testing` | SHIPPED | `assert_scene_matches` / `render_scene_to_png` / `diff_pngs`. |
| `gi` | SHIPPED | Radiance cascades, ReSTIR, SVGF (CPU path + reset_history). API ref present. |
| `post_process` | SHIPPED | 14 passes (bloom/GTAO/TAA/DoF/MB/SSR/volumetric/CSM/...), preset chains, UBO migration done. |
| `gpu` | SHIPPED | wgpu context, mesh+PBR+cluster pipelines, SDF renderer, IBL, adaptive quality. |
| `compute` | SHIPPED | ComputePass/Pipeline, readback, mutator, stats, spatial — hardening round open. |
| `residency` | SHIPPED | 3-tier GPU/RAM/DISK + `.slap` binary format. |
| `assets` | SHIPPED | `AssetDatabase` singleton + validation. |
| `audio_runtime` | WORKING | Soft-import shim works; backend path (resampling / mono-stereo / underrun) un-audited per [`docs/roadmap.md`](roadmap.md) mid-term. |
| `ui` | WORKING | `scene_ui`, `hud_widgets`, `debug_overlay`, `html_overlay`, `project_manager`, `widgets` all in place. No widget-level docs. |
| `ui.editor` | WORKING | 22-panel DearPyGui shell (Nova3D glassmorphism dark theme), spawn menu, gizmo overlay, code-mode, material editor, ollama setup. **No notebook theme variant.** |
| `animation` | WORKING | `AnimationGraph` (state machine), `AnimTransition`, `AnimUpdate`, `ProceduralRig` + `ControlPoint`, `video_import`. **No blend tree, no FBX/GLTF importer, no IK retargeting between skeletons.** |
| `material` | WORKING | `NodeMaterial` runtime + node factories (UV/PixelColor/Add/Multiply/Lerp/Clamp/GravityWarp/SampleTexture/FinalColor/Discard/PixelChannel) + `MaterialMap` color-range catalog. **No visual node editor for end users.** Editor has `MaterialEditor` panel but it's a reflection-based property inspector, not a true node-graph canvas. |
| `tools` | WORKING | `sprite_audit` (CPU), `audio_tools`, `texture_tools`, `track_tools`, `video`, `gen_placeholders`. |
| `ai` | WORKING | `llm_client`, `ollama_manager`, `code_sync`, `script_gen`. **No top-level surface entry, no `docs/api/ai.md`** (roadmap mid-term v0.4). |
| `ext` | WORKING | Back-compat shim namespace. |
| `softbody` | WORKING | XPBD lattice + beam, vehicle/body builders, render. **WIP-frozen until physics sprint reconciles** (`benchmarks/baseline_report.md` § 2026-06-01). |
| `fluid` | WORKING | PBF solver, buoyancy, surface, thermal_step, render. **WIP-frozen, same as softbody.** |
| `physics` | WORKING | Legacy per-pixel hierarchical-hull solver. Slated for Phase D strip (steps 6+). |
| `net` | SKELETON | `discovery.py`, `peer.py`, `room.py`, `session.py`, `sync.py` exist but **no `docs/api/network.md`**, no `hello_multiplayer.py` smoke demo, no hardening round (roadmap mid-term v0.4). |
| `modules` | SKELETON | `fluid_params`, `health`, `physics`, `pixel_physics` — game-side plugin scaffold. |
| **ECS layer (planned)** | GAP | Roadmap mid-term v0.4: formalise an ECS narrative over `Entity` / `Component` / `Scene` / lifecycle hooks. Today: protocol + ComponentBase, no system scheduler. |
| **Particle FX wrapper** | GAP | `particles.py` ships `ParticleEmitter` (CPU) + `GpuParticleSystem`. No emitter-shape / force-field / curve-driven authoring API; no editor preview pane. |
| **Profiler overlay** | GAP | `telemetry` ships events; `tools/perf_dashboard` produces tripwire markdown; no in-editor live flame graph / per-frame timeline / F3 toggle. |
| **Material/Shader visual graph** | GAP | `NodeMaterial` runtime exists; no drag-and-drop authoring canvas with live preview pane and `.material` file save/load. |
| **Localization (i18n)** | GAP | No string-table subsystem; menus and HUD widgets are English-literal. |
| **Input remapping UI** | GAP | `ActionMap` data class exists; no editor panel for end users to rebind. |
| **Save-game versioning** | GAP | `dynamics.save_world` carries `SCHEMA_VERSION`; engine-wide save format lacks a version migration helper. |
| **Build pipeline UI** | GAP | `build_gen.py` and `content_encrypt.py` exist as CLI helpers; no editor wizard. |

### Cross-reference checks

* Top-level surface (75 names) verified against
  [`docs/engine_surface_v030.md`](engine_surface_v030.md). Locked by
  `SlapPyEngineTests/tests/test_docs_engine_surface_complete.py`.
* Roadmap items pulled from [`docs/roadmap.md`](roadmap.md) near/mid/long-term
  bands.
* CHANGELOG v0.3.0 surface (subpackages + studio + tripwires) confirmed.
* WIP-freeze on `softbody` / `fluid` honoured — no sprint touches them
  until the physics reconcile sprint per `roadmap.md` near-term.

---

## Phase 2 — 7-sprint plan

### Ordering rationale

1. **Editor UI theme** ships visible value to authors first, and is fully
   self-contained (no engine semantics change).
2. **ECS formalisation** is the load-bearing refactor that the next four
   sprints all read from.
3. **Animation graph + IK retargeting** is the largest authoring surface
   gap; depends on the ECS scheduling story.
4. **Material/shader graph authoring** reuses the editor canvas pattern
   from Sprint 1's notebook overhaul and the ECS lifecycle.
5. **Particle FX** is a thin high-level wrapper over existing `particles`
   + `physics/particle_field` — runs in parallel to material graph and
   shares the editor preview-pane harness.
6. **Profiler overlay** consumes `telemetry` (SHIPPED) and the editor
   panel pattern; needs ECS + animation + particle scheduling to be in
   place so it has something to profile.
7. **Ship polish** rolls localisation / input remap / audio backend
   hardening / save versioning / build UI into a v0.4 release. Sprint 7
   maps the v0.4 ship checklist (parallel of
   [`docs/sprint_7_ship_checklist.md`](sprint_7_ship_checklist.md)).

---

### Sprint 1 — Editor UI Theme Overhaul (TeenGirl Notebook)

**Goal:** ship a switchable "TeenGirl Notebook" theme for `slappyengine.ui.editor`
that achieves a hand-decorated-paper aesthetic via nine-slice / SVG /
shaders — zero per-asset PNG bloat in the wheel.

**Deliverables:**

* `python/slappyengine/ui/editor/theme_notebook.py` — pastel palette
  (paper cream, sticker pink, washi mint, highlighter yellow) +
  `apply_notebook_theme()` companion to the existing
  `apply_glass_theme()` in `theme.py`.
* Notebook-paper background as a procedural WGSL shader
  (`shaders/ui_notebook_paper.wgsl`) generating ruled lines + margin
  bar + faint grid at runtime — no PNG.
* Washi-tape nine-slice borders for window frames — single 64x64 RGBA
  PNG per tape colour, stretched by DPG's `border_image` plumbing or
  custom nine-slice draw helper if DPG doesn't expose it.
* Sticker icon set as inline SVG (toolbar, scene outliner, gizmo
  buttons) — DearPyGui can rasterise SVG via cairosvg fallback, or
  pre-bake to a small 256x256 sprite atlas at editor boot.
* Highlighter selection overlay — a translucent yellow rectangle pass
  rendered over selected items in the scene outliner and viewport.
* Handwritten font — Patrick Hand or Caveat (open-licensed) shipped as
  TTF in `python/slappyengine/ui/editor/assets/` (~50 KB).
* `ext/ui` shim entry so the theme is reachable as
  `slappyengine.ext.ui.NotebookTheme`.
* Wheel-size delta target: **≤ +200 KB** (font + 6 washi tapes +
  shader source). Per `docs/wheel_size_audit_2026_06_02.md` the
  current wheel is ~1.45 MB; budget is 50 MB.

**Dependencies:** none. Reads the v0.3 Nova3D glassmorphism theme
(`python/slappyengine/ui/editor/theme.py`) as the reference pattern.

**Test plan:**

* New `SlapPyEngineTests/tests/test_editor_theme_notebook.py` —
  asserts `apply_notebook_theme()` mutates DPG global theme tokens,
  shader compiles, nine-slice helper produces correct UVs.
* Extend `SlapPyEngineTests/tests/test_editor.py` with a headless
  smoke that boots `EditorShell` under both themes.
* New `SlapPyEngineTests/tests/test_wheel_size_budget.py` — asserts
  built wheel stays under 2 MB.

**Doc plan:**

* New `docs/editor_theme_notebook.md` — palette card, washi nine-slice
  recipe, sticker SVG library, font licensing notes, with concept-art
  reference screenshots from `UIConceptArt/`.
* Refresh `docs/api/ui_editor.md` — add `apply_notebook_theme`,
  `NotebookTheme` to the surface table.
* Cross-link from `docs/sprint_5_doc_inventory.md` (this commit).

**Estimated LOC delta:** +1100 LOC (~600 theme module, ~250 shader +
SVG helpers, ~250 tests).

**Risk callouts:**

* DPG SVG support is not first-class — fallback rasteriser path
  needs to be vetted on Windows / macOS / Linux DPG builds before
  going wide.
* Procedural paper shader must stay deterministic across drivers to
  keep `assert_scene_matches` baselines stable.
* Theme switching at runtime may leak DPG resources if not unbound
  cleanly — needs a `teardown_theme()` mirror.

---

### Sprint 2 — ECS Layer Formalisation

**Goal:** lift the existing `Entity` / `Component` / `Scene` /
lifecycle-hooks scaffold into a documented ECS with a system
scheduler, sparse-set component storage, and a `ComponentRegistry` —
without breaking the v0.3 surface or any of the 1124+54 game-compat
tripwires.

**Deliverables:**

* `python/slappyengine/ecs/registry.py` — `ComponentRegistry` (name
  → type, schema introspection, system-opt-in flag).
* `python/slappyengine/ecs/storage.py` — sparse-set component storage
  back-end, opt-in per registered component.
* `python/slappyengine/ecs/system.py` — `System` base + lifecycle
  hooks (`on_attach_scene`, `pre_tick`, `tick`, `post_tick`,
  `on_detach_scene`), plus `Scheduler` walking systems in declared
  order.
* Integration with existing `Engine.run` / `Scene.update(dt)` so
  that subsystem `step(dt)` calls (dynamics, fluid, zones, ...) plug
  into the scheduler as registered `System`s with a documented order.
* Migration shim: existing `Component` Protocol and `ComponentBase`
  continue to work; new components opt-in by calling
  `ComponentRegistry.register(MyComponent)` at module import.
* YAML scheduler manifest support — extend the existing
  `ScriptBinding` / `SceneManifest` pattern (per memory note
  `project_usability_sprint.md`) so games declare system order in
  `scene.yml` instead of code.

**Dependencies:** none on Sprint 1 directly. Reads the v0.3
`components.py` + `entity.py` + `scene.py` and the existing YAML
manifest plumbing.

**Test plan:**

* New `SlapPyEngineTests/tests/test_ecs_registry.py`,
  `test_ecs_storage.py`, `test_ecs_scheduler.py` — registry
  round-trip, sparse-set add/remove/iterate, scheduler ordering and
  pre/post hooks.
* New `SlapPyEngineTests/tests/test_ecs_back_compat.py` — every
  `ComponentBase` subclass in the engine still works without
  registering, and one example registers + uses sparse-set storage.
* Extend `SlapPyEngineTests/tests/test_engine_integration_scene.py`
  with a scheduler-driven scene.

**Doc plan:**

* New `docs/ecs_design.md` — ECS narrative, scheduler order, sparse-set
  motivation, migration recipe.
* New `docs/api/ecs.md` — hand-authored API reference following the
  `docs/api/_template.md` shape.
* Refresh `docs/architecture_overview.md` — add ECS as a layer between
  `Engine.tick` and per-subsystem `step(dt)`.
* Refresh `docs/engine_surface_v030.md` — surface map gets `ecs`
  subpackage (will roll into v0.4 surface doc).

**Estimated LOC delta:** +1400 LOC (~700 ecs subpackage, ~400 tests,
~300 docs + migration shims).

**Risk callouts:**

* Game-compat tripwire (54+1124 pinned imports) — must not regress
  any name; new sparse-set storage is purely additive.
* Scheduler ordering for the seven shipped sim subsystems
  (dynamics / fluid / softbody / thermal / zones / topology / numerics)
  is load-bearing for determinism; baseline must be captured by
  the visual-regression harness before refactor.
* YAML manifest extension is observable to downstream games — needs
  versioned schema.

---

### Sprint 3 — Animation Graph + IK Retargeting

**Goal:** promote `slappyengine.animation` from "graph + procedural
rig" to a full authoring surface — blend trees, keyframe interpolation,
FBX / GLTF import (via `[animation] extra`), and IK retargeting
between skeletons.

**Deliverables:**

* `python/slappyengine/animation/blend_tree.py` — `BlendNode`,
  `BlendNode1D`, `BlendNode2D` (Cartesian blend), `BlendTree`
  evaluator producing per-bone transforms.
* `python/slappyengine/animation/keyframe.py` — `Keyframe`,
  `KeyframeTrack`, `interpolate_linear`, `interpolate_hermite`,
  `interpolate_bezier`.
* `python/slappyengine/animation/import_gltf.py` — optional import of
  GLTF/GLB animation channels onto `ProceduralRig` skeletons
  (depends on `pygltflib`, gated by `[animation]` extra).
* `python/slappyengine/animation/import_fbx.py` — optional FBX import
  via `fbx-sdk-python` (gated by `[animation-fbx]` extra,
  large dependency).
* `python/slappyengine/animation/retarget.py` — `BoneMap` between
  source and target rigs, `retarget_clip(clip, bone_map)` producing
  a new clip aligned to the target's bind pose.
* Integration with the existing `dynamics.IKChainSpec` + `solve_ik`
  + `dynamics.humanoid.make_humanoid` so retargeted clips drive IK
  goals on the engine's humanoid factory.
* Editor spawn-menu entry — "Load animation (GLTF)" pops a file
  picker; resulting `AnimationGraph` lives on the entity inspector.

**Dependencies:** Sprint 2 (`System` scheduler so the
`AnimationSystem` lifecycle slot is documented).

**Test plan:**

* New `test_animation_blend_tree.py`, `test_animation_keyframe.py`,
  `test_animation_retarget.py`.
* New `test_animation_import_gltf.py` — golden GLTF clip
  (cube + bone) round-trip.
* Extend `SlapPyEngineTests/tests/test_animation.py` with a graph
  driving a `Humanoid` via IK.

**Doc plan:**

* Refresh `docs/api/animation.md` — add blend trees, keyframe
  interpolation, retarget API.
* New `docs/animation_design.md` — graph + tree + retarget mental
  model, IK retargeting algorithm walk-through.
* New `docs/animation_import_recipe.md` — GLTF / FBX import
  pre-conditions, dependency install, common pitfalls.

**Estimated LOC delta:** +1800 LOC (~900 blend tree + keyframe + retarget
runtime, ~400 importers, ~300 tests, ~200 docs).

**Risk callouts:**

* FBX SDK is platform-specific and large (~50 MB). Gate strictly
  behind an opt-in extra; keep the import wrapped in a soft-import
  shim like `audio_runtime`.
* GLTF skeleton conventions (Z-up vs Y-up, units in metres) — bone
  retargeting must normalise both sides or visual baselines will
  drift.
* IK retargeting is mathematically a hard problem at extremes —
  fall back to FK if hip-shoulder ratio differs by more than 2x.

---

### Sprint 4 — Material / Shader Graph Authoring

**Goal:** ship a true drag-and-drop visual editor for `NodeMaterial`
inside the editor's `MaterialEditor` panel, with live preview and
`.material` file save/load.

**Deliverables:**

* `python/slappyengine/ui/editor/material_graph_canvas.py` — graph
  canvas with draggable nodes, connection lines, context menu to
  add nodes from `KNOWN_NODE_TYPES`, click-to-edit param fields.
* `python/slappyengine/material/serialize.py` — `save_material`,
  `load_material` round-trip to `.material` YAML files (same envelope
  as `dynamics.save_world`).
* Live preview pane — a 256x256 swatch rendering the material onto a
  reference sphere / plane, refreshed at 30 fps under the editor's
  `tick` loop.
* Node library extension — add 5 commonly-requested nodes:
  `NoiseNode` (perlin), `RemapNode` (a→b range), `StepNode`,
  `SmoothstepNode`, `FresnelNode`.
* Editor integration — `MaterialEditor` panel switches between the
  v0.3 reflection-based property inspector and the new node canvas
  via a tab.
* "Save as material" action in the editor toolbar.

**Dependencies:** Sprint 1 (notebook theme — so the canvas frame /
node body shapes adopt the washi-tape / paper aesthetic), Sprint 2
(`System` scheduler so the preview-pane refresh is a documented
system, not an ad-hoc timer).

**Test plan:**

* New `test_material_serialize.py` — round-trip every shipped
  `NodeDef` factory through YAML.
* New `test_material_graph_canvas.py` — headless canvas instantiation,
  node add/connect/delete, undo/redo.
* New `test_material_preview_pane.py` — preview renders a known
  swatch within tolerance.
* Extend `SlapPyEngineTests/tests/test_editor_material_editor_kinds.py`
  with the new noise / remap / step / smoothstep / fresnel nodes.

**Doc plan:**

* New `docs/material_graph_editor.md` — recipe for building a
  material in the editor, save/load, common patterns
  (UV→Noise→Remap→FinalColor chain).
* Refresh `docs/api/material.md` — add `save_material` / `load_material`
  + the five new node factories.
* Refresh `docs/material_catalog.md` — note that catalog entries can
  now be authored visually.

**Estimated LOC delta:** +1600 LOC (~800 canvas + serializer, ~300
new nodes + preview, ~350 tests, ~150 docs).

**Risk callouts:**

* DearPyGui has no first-class node-graph widget — we either use
  `dearpygui-imnodes` (separate dep) or hand-roll canvas drawing.
  Hand-roll is more code but zero new deps; default plan.
* Live preview pane has to share the GPU context with the main
  viewport — needs a dedicated render target and a re-entrant guard
  so it does not stall the editor on shader compile.
* `.material` YAML must keep the v0.3 `NodeMaterial` runtime untouched
  — round-trip is purely additive.

---

### Sprint 5 — Particle FX + VFX System

**Goal:** ship a high-level VFX authoring API over the existing
`particles.py` (`ParticleEmitter` + `GpuParticleSystem`) and the
`physics/particle_field` substrate — emitter shapes, force fields,
curves over life, one-shot vs looping cues, editor preview.

**Deliverables:**

* `python/slappyengine/vfx/emitter.py` — `Emitter`, `EmitterShape`
  (Point / Line / Disc / Box / Mesh), `EmitterRate` (per-second /
  burst / curve), `EmitterCue` (one-shot / looping / trigger-on-event).
* `python/slappyengine/vfx/force_field.py` — `Gravity`,
  `Drag`, `Vortex`, `Turbulence`, `Attractor` force-field classes
  composed into an `EffectStack`.
* `python/slappyengine/vfx/curves.py` — `Curve` (key-value spline)
  driving color-over-life, size-over-life, alpha-over-life,
  rotation-over-life.
* `python/slappyengine/vfx/effect.py` — top-level `Effect` bundling
  emitter + force-field stack + curves; `Effect.play()`,
  `Effect.stop()`, `Effect.is_playing`.
* `.effect` YAML file format for save/load (same envelope as
  `.material` from Sprint 4).
* Editor `VFXPreviewPanel` — black/checker background, scrubbable
  timeline, play/stop, save/load.
* Integration with the existing `particles.GpuParticleSystem` —
  emitters allocate from a shared pool keyed by `Effect`.

**Dependencies:** Sprint 1 (theme), Sprint 2 (ECS scheduler — `VFXSystem`
lifecycle), Sprint 4 (preview-pane harness reuse).

**Test plan:**

* New `test_vfx_emitter.py` — every shape spawns the right particle
  count and positions match analytical bounds.
* New `test_vfx_force_field.py` — gravity / drag / vortex /
  turbulence produce expected velocity deltas.
* New `test_vfx_curves.py` — color/size/alpha curves evaluate at
  known timestamps.
* New `test_vfx_effect_serialize.py` — `.effect` round-trip on every
  shipped shape × force-field combination.
* New `test_vfx_editor_preview.py` — preview panel boot + scrub +
  play.

**Doc plan:**

* New `docs/vfx_design.md` — emitter / force-field / curve model,
  one-shot vs looping cue semantics, performance budget.
* New `docs/api/vfx.md` — hand-authored API reference.
* New `docs/vfx_recipes.md` — 5 worked examples (muzzle flash /
  smoke / sparks / waterfall / explosion).

**Estimated LOC delta:** +1700 LOC (~1000 vfx subpackage, ~250
preview panel, ~300 tests, ~150 docs).

**Risk callouts:**

* Sharing the `GpuParticleSystem` pool between effects requires
  per-effect particle range bookkeeping; an effect leaking range
  starves siblings — needs a unit test that exercises eviction.
* `physics/particle_field` is part of the frozen-WIP perimeter for
  fluid; Sprint 5 must not edit that path, only consume it.
* `Curve` evaluation is in the hot path — keep it allocation-free
  in `__call__`.

---

### Sprint 6 — Profiler + Debug HUD overlay

**Goal:** ship an in-editor + in-game live profiler overlay consuming
`slappyengine.telemetry` events: per-frame timeline, allocation rate,
GPU vs CPU split, hot-path flame graph. Toggle with F3.

**Deliverables:**

* `python/slappyengine/telemetry/profiler.py` —
  `FrameProfiler.begin(name)` / `.end(name)` context-manager pair
  emitting bracketed `telemetry.emit` events; thread-safe.
* `python/slappyengine/ui/debug_overlay.py` (extend the existing
  module) — `ProfilerOverlay` widget drawing:
  * Per-frame timeline (last 240 frames, ~4 s @ 60 fps).
  * CPU vs GPU split bar (uses wgpu timestamp queries when
    available, falls back to CPU-side `time.perf_counter()`).
  * Allocation rate sparkline (sample `tracemalloc.get_traced_memory`
    every N frames).
  * Hot-path flame graph from the last frame's emit tree.
* F3 toggle wiring — `Engine` consumes a keyboard event and toggles
  the overlay; also reachable via `Engine.toggle_profiler_overlay()`.
* Snapshot-to-disk — `Engine.profile_snapshot("snap.json")` writes
  the last N frames in a portable schema for offline analysis.
* Offline viewer — `slappy profile view snap.json` CLI prints
  per-frame breakdown.
* Engine instrumentation — annotate the hot paths the v0.3 perf
  dashboard already tracks (dynamics / numerics / thermal / topology /
  telemetry / zones) with `FrameProfiler.begin/.end` brackets.

**Dependencies:** Sprint 2 (`System` lifecycle so the profiler
brackets are placed at canonical hooks, not ad-hoc), Sprint 5
(particle / vfx instrumentation gets the same treatment).

**Test plan:**

* New `test_profiler_frame.py` — begin/end bracketing produces the
  expected event tree.
* New `test_profiler_snapshot.py` — round-trip JSON snapshot.
* New `test_profiler_overlay_render.py` — overlay renders a known
  frame snapshot to PNG within tolerance.
* Extend `SlapPyEngineTests/tests/test_telemetry_*.py` — assert the
  profiler does not exceed the 5% frame-budget overhead bar that the
  hardening audit set.

**Doc plan:**

* New `docs/profiler_overlay.md` — F3 toggle, snapshot format,
  offline viewer recipe.
* Refresh `docs/api/telemetry.md` — add the `profiler` submodule.
* Refresh `docs/perf_dashboard.md` — note that per-frame breakdown
  is now reachable from a snapshot.

**Estimated LOC delta:** +1100 LOC (~600 profiler + overlay,
~150 CLI viewer, ~250 tests, ~100 docs).

**Risk callouts:**

* Tracemalloc costs ~30% on a fully-traced run — gate it behind an
  explicit `--trace-allocs` flag and default to **off**.
* wgpu timestamp queries are not uniformly supported across drivers
  (Vulkan / Metal / DX12 differ on resolution + availability). Fall
  back to a CPU-only split label.
* Overlay rendering must not allocate per frame; pre-build a fixed
  buffer of geometry for the timeline.

---

### Sprint 7 — Ship Polish + v0.4 Release

**Goal:** tighten the v0.4 release: localisation, input remapping UI,
audio backend hardening, scene-load progress, save-game versioning,
build pipeline UI, profiler integration, docs sweep, full CHANGELOG.

**Deliverables:**

* `python/slappyengine/i18n.py` — `StringTable`, `set_locale`,
  `tr(key, **kwargs)`, YAML loader for `strings.<locale>.yml`.
* Editor + HUD widget pass — wrap every literal in `tr(...)`. Ship
  English baseline + Spanish + Japanese sample translations.
* `python/slappyengine/ui/editor/input_remap_panel.py` — UI to
  rebind `ActionMap` keys, with conflict detection. YAML round-trip
  into the existing `ActionMap` data class.
* Audio backend hardening round — close the un-audited boundary path
  from `docs/roadmap.md` mid-term (sample-rate conversion,
  mono/stereo, ring-buffer underrun). Adds
  `test_hardening_audio_backend.py`.
* `python/slappyengine/scene/loader.py` — `SceneLoader` with
  progress callback (`on_progress(fraction, message)`), integrated
  with the editor's scene-load action and exposed via
  `Engine.load_scene_async`.
* `python/slappyengine/save_version.py` — `SAVE_SCHEMA_VERSION`,
  `migrate_save(blob)` chain so old `save_world` blobs round-trip
  forward without raising.
* `python/slappyengine/ui/editor/build_panel.py` — visual wrapper
  over `build_gen.py` + `content_encrypt.py`: select platforms,
  toggle 3D extra, encrypt content, hit Build, see output.
* Profiler integration into the editor — Sprint 6's overlay is
  toggleable inside the editor (not just at runtime).
* Docs sweep — refresh `docs/getting_started.md`,
  `docs/tutorial_build_a_game.md`, every `docs/api/*.md` for v0.4
  surface deltas. Run `scripts/gen_engine_surface_doc.py`.
* CHANGELOG `0.4.0` entry — list every new surface from Sprints 1-7
  with cross-links.
* New ship checklist `docs/sprint_7_ship_checklist_v04.md` — same
  shape as the v0.3 file, gated on game-compat tripwires + perf
  dashboard + docs link resolution + version consistency.

**Dependencies:** all prior sprints. Audio hardening is independent
but rolls in cleanly here.

**Test plan:**

* New `test_i18n.py`, `test_input_remap_panel.py`,
  `test_hardening_audio_backend.py`, `test_scene_loader_progress.py`,
  `test_save_version_migrate.py`, `test_build_panel.py`.
* Refresh `test_docs_engine_surface_complete.py` — pin the v0.4
  surface.
* New game-compat tripwire entries for any new top-level lazy
  exports.

**Doc plan:**

* New `docs/i18n.md`, `docs/input_remap.md`, `docs/build_pipeline_ui.md`,
  `docs/save_versioning.md`.
* Refresh `docs/api/audio_runtime.md` with the hardening notes.
* Refresh `docs/architecture_overview.md` to reflect v0.4 changes.
* Bump `__version__` to `0.4.0b0`.

**Estimated LOC delta:** +2200 LOC (~700 i18n + scene loader + save
versioning, ~600 panels, ~500 tests, ~400 docs sweep).

**Risk callouts:**

* `tr(...)` wrapping is a large mechanical change — needs a lint
  rule (`tools/check_no_literal_strings.py`) to keep the v0.3
  English baseline from regressing.
* Save migration chain must be exhaustively tested against the
  game-compat tripwire's pinned save blobs (54 + 1124).
* CHANGELOG sweep must not drop any v0.3 entry — append-only.

---

## Aggregate

| Sprint | LOC delta | New docs | New tests |
|---|---|---|---|
| 1 — Editor theme | +1100 | 1 | 3 |
| 2 — ECS | +1400 | 2 | 4 |
| 3 — Animation | +1800 | 2 | 4 |
| 4 — Material graph | +1600 | 1 | 4 |
| 5 — VFX | +1700 | 3 | 5 |
| 6 — Profiler | +1100 | 1 | 4 |
| 7 — Ship | +2200 | 4 | 6 |
| **Total** | **+10900** | **14** | **30** |

## Top-3 risk callouts (rolled up)

1. **Game-compat tripwire breakage** — Sprints 2 + 7 touch the
   import surface and save format. The 54 + 1124 pinned downstream
   imports must stay green at every commit. Mitigation: every sprint
   keeps the v0.3 surface as a strict subset of v0.4 + extends
   `test_game_compat_tripwire.py` before deleting any lazy entry.
2. **WIP-frozen physics edits** — `softbody` and `fluid` are frozen
   per `roadmap.md` near-term and `benchmarks/baseline_report.md`.
   Sprints 5 and 6 must consume but not modify those subpackages.
   Mitigation: the VFX wrapper sits over the `particles` /
   `physics/particle_field` surface, not over the frozen fluid
   solver.
3. **Editor dependency surface (DPG / cairosvg / pygltflib /
   fbx-sdk)** — Sprints 1, 3, 4 add or stress optional deps. Each
   must be gated by an install extra and soft-imported (same
   pattern as `audio_runtime`), with a stub fallback that keeps
   the headless test suite green.

---

## Cross-links

* [`docs/roadmap.md`](roadmap.md) — graduates ECS / audio / animation /
  network items from mid-term v0.4 once each sprint lands.
* [`docs/CONTRIBUTING.md`](CONTRIBUTING.md) — hardening pattern, doc
  markers, naming. Sprints 1-7 follow the established
  `make_*` / `build_*` distinction.
* [`docs/api/_template.md`](api/_template.md) — every new
  `docs/api/<name>.md` follows the template.
* [`docs/engine_surface_v030.md`](engine_surface_v030.md) — v0.4
  re-emits the auto-generated surface map after Sprint 7.
* [`docs/sprint_7_ship_checklist.md`](sprint_7_ship_checklist.md) —
  template for the v0.4 ship checklist (Sprint 7 deliverable).
* [`docs/sprint_5_doc_inventory.md`](sprint_5_doc_inventory.md) —
  this document is indexed there.
