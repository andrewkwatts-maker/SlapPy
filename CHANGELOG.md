# Changelog

All notable changes to SlapPyEngine (`pharos-engine` on PyPI).

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [0.4.0] — YYYY-MM-DD (UNRELEASED)

v0.4 lands the **Nova3D parity milestone** — SlapPyEngine graduates from a
2D-first physics + post-process rig into a real forward 3D renderer with
skinned glTF, animation, CSM shadows, IBL, SSAO, skybox, SDF text, HUD,
capture, positional audio, instanced rendering, BVH culling, and a
cross-platform game exporter. On top of that: a diary-themed notebook
editor with 20+ panels, a `pharos_engine.actions` 20-action subpackage
plus router, six diary themes, three 15-shader WGSL libraries, six
baked prefabs, and an autosave / crash-recovery layer.

Status per [OO7 release-readiness audit](docs/v0_4_release_readiness_2026_07_06.md):
**YELLOW** — WIP subpackages (`softbody/`, `fluid/`, `physics/`,
`physics2/`) are frozen, 13-row STUB backlog needs a triage pass, and
the version bump is gated on the PP tag-prep sprints. Draft entry — the
version string in `pyproject.toml`, `Cargo.toml`, and
`python/pharos_engine/__init__.py` is **still `0.3.0b0`** and this
section is not yet tagged.

Ship-path decision recorded in
[VV7 v0.4 ship-decision doc](docs/v0_4_ship_decision_2026_07_07.md) —
**Option B** (ship-after-full-recovery) recommended; gate #12 game-compat
currently at **61.6%** F1 recovery post-VV1 (Ochema 681/1126 + Bullet
Strata 45/54); downstream games need v0.4.1 for full compat.

### Nova3D parity milestone

Twenty agent-scoped sprints (JJ1–LL7) translating the
[HH3 Nova3D gap audit](docs/nova3d_gap_audit_2026_07_05.md) and
[II7 sprint plan](docs/nova3d_parity_sprint_plan_2026_07_05.md) into
shipped surfaces:

- **JJ1** — real wgpu forward pipeline (`pharos_engine.render`).
- **JJ2** — MTL material resolution for the OBJ importer.
- **JJ3** — skinned-mesh support in the glTF importer.
- **JJ4** — skeleton runtime + `AnimationClip` + `Skinner`.
- **JJ5** — `SceneWalker` — Scene → drawcall traversal with frustum culling.
- **KK1** — 3D BVH broadphase for frustum culling.
- **KK2** — `DepthPrepass` + `MSAAResolvePass` + `PassChain`.
- **KK3** — SSAO screen-space ambient occlusion pass.
- **KK4** — skybox + cubemap import + procedural gradient sky.
- **KK5** — IBL prefilter chain (GGX importance-sampled cubemap mips).
- **KK6** — SDF text glyph atlas + WGSL renderer.
- **LL1** — runtime HUD overlay + registry + 3 widget primitives.
- **LL2** — video / GIF / frame capture subsystem (`_core.capture`).
- **LL3** — instanced rendering + factory helpers.
- **LL4** — 3D positional audio + Doppler + stereo panning
  (`_core.audio_3d`).
- **LL5** — `hello_gltf_character` — rigged glTF + skinning + CSM harness.
- **LL6** — cross-platform game exporter + `slap export` CLI.
- **LL7** — `physics3_bridge` — soft-import 3D physics with SAP fallback.

### Added

**New subpackages / top-level API:**

- `pharos_engine.render` — wgpu-based 2D + 3D forward renderer (HH4).
- `pharos_engine.projects` — multi-project management + registry +
  scaffolder + CLI (`pharos_engine.projects`, HH2 + M6 + F).
- `pharos_engine.actions` — 20-action subpackage + `ToolRouter` +
  `pharos_engine.tool_router` formal editor tool-routing contract.
- `pharos_engine.math` — Formula / `evaluate` / `compile_formula` backed
  by Arithma when `[math]` extra is installed, with locked-down Python
  eval sandbox fallback + `Vec2`/`Vec3`/`Vec4` + animation curves.
- `pharos_engine.visual_scripting` — Node + NodePort + `NodeRegistry` +
  `NodeGraph` + YAML round-trip + `graph_to_python` codegen +
  `BUILTIN_NODES` 20-prototype starter palette.
- `pharos_engine.scenes` — YAML scene serialization (FF3).
- `pharos_engine.diagnostics` aggregator + HUD widget (OO6).
- `pharos_engine.exporter` + `slap export` CLI with dry-run + manifest +
  exclude (LL6 + NN7).
- `pharos_engine.residency` — GPU/RAM/DISK three-tier asset residency.
- `pharos_engine.ui.editor` — diary-themed notebook editor + 20+ panels
  (see below); `pharos_engine.ui.theme` primitive infrastructure
  (nine-slice / SVG / procedural shader); `pharos_engine.ui.widgets`
  Dear PyGui notebook primitives; `pharos_engine.ui.runtime`.
- `App` + `launch()` + `load_model()` ergonomic top-level API (HH1).

**Notebook editor + diary theme family (V, W, X, Y, Z, AA, BB, CC, DD,
EE, FF, GG batches):**

- `NotebookOutliner` / `NotebookInspector` / `NotebookGizmoOverlay` /
  `NotebookSpawnMenu` / `NotebookMaterialEditor` / `NotebookCodePanel`
  / `NotebookWelcome` / `NotebookMenuBar` / `NotebookCommandPalette` /
  `NotebookAssetInspector` / `NotebookToastManager` / `NotebookMinimap`
  / `NotebookMessageLog` / `NotebookTelemetryDashboard` /
  `NotebookAutosavePanel` / `NotebookHotkeyHelp` /
  `NotebookThemingEditor` / `NotebookPPPreviewPanel` /
  `NotebookNodeEditor` / `NotebookDiaryPage` /
  `NotebookContentBrowser` / `NotebookPrefabMenu` /
  `NotebookCurveEditor` / `DiaryShell` book-of-pages workspace.
- Six diary themes (`teengirl_notebook`, `scrapbook_summer`,
  `cozy_diary`, `bullet_journal`, `cottagecore_garden`,
  `kawaii_planner`) + `ThemeSwitcherPanel` live hot-swap +
  `DeclarativeTheme` CSS-like theme parser + `UserThemeStore`.
- Three 15-shader WGSL libraries: `washi_tape_shaders`,
  `page_lining_shaders`, `edge_stroke_shaders`.
- 12 cuddly-creature builtins on top of the woodland roster (cat,
  golden, red panda, raccoon, panda, porcupine, hedgehog, butterflies).
- Prefab library (`.prefab.yaml`) + preview icon baker + 6 baked
  prefabs + `PrefabLibrary.spawn`; autosave + crash-recovery subsystem;
  hotkey remap layer + 3 baked style presets; `LayoutBaker` + 6 baked
  layout presets; camera animation tweens; scene diff / apply / merge;
  plugin registry + sample plugin; shader hot-reload watcher; live-reload
  watcher on `UserOverrideLoader`; file-drop OS routing;
  `ProjectSceneBridge` bridging FF3 scenes with V2 projects.

**Demos & docs (52+ new):**

- `hello_render`, `hello_render_real`, `hello_render_real_hud`,
  `hello_full_editor`, `hello_v2_showcase`, `hello_showcase_v3`,
  `hello_gltf_character`, `hello_positional_audio`, `hello_hud`,
  `hello_integrated_notebook`, `hello_prefab`, `hello_autosave`,
  `hello_scene_reg`, `hello_material_graph`, `hello_toast_animation`,
  `hello_export_cli`.
- API references for `math`, `render`, `projects`, `visual_scripting`,
  `residency`, `compute`, `animation`, `ui_editor`, `ui_theme`,
  `ui_widgets`, `washi_tape_shaders`, `page_lining_shaders`,
  `edge_stroke_shaders`, `theme_declarative`.
- Design docs: Nova3D gap audit + parity sprint plan, big-picture
  status report, feature maps + deltas, sprint rollups, quickstart,
  pip-extras guide, rust-bypass docs, rust-migration audit,
  UI-nesting/pattern/lessons audits, diary theme docs, notebook editor
  manual, sprint-plan for v0.4.

**QQ+RR+SS+TT+UU+VV batch additions (post-PP6 draft):**

- `hello_diagnostics_hud` demo (QQ5 `03ac323`) — HUD-wired diagnostics
  aggregator smoke.
- `hello_full_lifecycle` flagship demo (RR5 `ba9cbd5`) — end-to-end App
  lifecycle harness combining diagnostics, HUD, capture, and export.
- `hello_downstream_pattern` demo (VV5 `55e99a3`) — reference downstream
  game-consumer pattern demonstrating the restored backcompat surface.
- `World3D.draw_debug` + `debug_stats` accessors (QQ7 `7b8fd2c`).
- App-lifecycle diagnostics wiring (QQ4 `6427a78`) —
  `DiagnosticsCollector` auto-installs on `App.__init__`.
- Diagnostics filter / aggregate / serialise surface (RR4 `65d49a0`).
- `DiagnosticsCollector.render_markdown_report` (SS6 `60bb55a`).
- Diagnostics `filter_by_message` + widget summary (TT6 `fc5d94f`).
- App lifecycle stress test suite (RR7 `7b85ded`).
- API refs: `topology` + `numerics` rewrites (SS7 `7c0da9f`);
  `ai` + `net` + `modules` (TT4 `e6cf530`);
  `iso` + `telemetry` + `gi` (UU6 `6849bb2`);
  `assets` + `input` (VV6 `d058e25`);
  `exporter` + `hud_overlay` + `diagnostics` (RR3 `60bbdf0`);
  and QQ3 `953e53f` MM/NN/OO landings (4 refs).
- API backcompat harness + `api_surface_snapshot.json` 338-symbol
  lockfile + `test_backcompat_api_surface.py` +
  `test_backcompat_subclass_patterns.py` +
  `scripts/refresh_api_surface_snapshot.py` (UU7 `1b494cf`); companion
  doc [`api_stability_2026_07_07.md`](docs/api_stability_2026_07_07.md).
- STUB triage rounds 18–23 — 30 new WIRED action ids across QQ1
  `336263c`, RR1 `085a14e`, TT2 `949a03e`, UU4 `8fe678a`, VV4 `23a5618`
  (round 20 salvaged via SS-batch `40695fb`).
- Demo test-smoke gap closure — 20 more tests unskipped across QQ2
  `9d57e81`, RR2 `7369070`, SS2 `796cbb2`, TT3 `41a6a31`, UU5
  `1192ea9`.
- Doc landings: [`v0_4_gate_reconciliation_2026_07_07.md`](docs/v0_4_gate_reconciliation_2026_07_07.md)
  (RR6 `f86def2`); [`sprint_rollup_2026_07_07_r6.md`](docs/sprint_rollup_2026_07_07_r6.md)
  (TT7 `7f4b93b`); [`skip_audit_2026_07_07.md`](docs/skip_audit_2026_07_07.md)
  + [`perf_baseline_2026_07_07.md`](docs/perf_baseline_2026_07_07.md)
  (SS3+SS4 salvaged `40695fb`); [`game_compat_2026_07_07.md`](docs/game_compat_2026_07_07.md)
  (TT1 `5c18eb0` + UU3 `844f4aa` + VV3 `b2126f0` re-run appends);
  [`v0_4_ship_decision_2026_07_07.md`](docs/v0_4_ship_decision_2026_07_07.md)
  (VV7 `647998e`); feature-map deltas 2026-07-09 through 2026-07-14.
- Engine surface v0.3 doc regenerated to 91-symbol tally (TT5 `b4fc933`,
  gate #2 verify).

### Changed

- **MM1 hardening** — input validation added across 13 files (salvaged
  from rate-limited agents in `1e584e4`), extending the v0.3 hardening
  campaign into the new v0.4 surface.
- **Lighting polish rounds 3–4 (W-batch):** TAA YCoCg variance clip +
  Halton(2,3)-8 + velocity blend + rejection heuristics; Bloom Karis
  13-tap downsample + tent upsample + firefly filter.
- **W2** hardening across notebook material / theming / spawn / diary
  panels.
- Editor promoted from Nova3D-legacy DPG to exclusive notebook UI
  (`759a2fd`, `1d785bf`); legacy Nova3D panels wrapped in
  `MovablePanelWindow` for the transition period.
- Snap / dock / resize / status-bar subsystems wired into the live
  editor; layout presets + window-management hotkeys.
- `_core` PyO3 surface grown to 55 symbols (see
  [rust_bypass_2026_07_05.md](docs/rust_bypass_2026_07_05.md)).
- Notebook editor usability polish — tooltips, right-click menus,
  breadcrumbs, multi-select.
- `pharos_engine.residency` / `pharos_engine.exporter` / `pharos_engine.render`
  wired into HH1 App → HH4 Renderer → HH5 asset-importer end-to-end.
- 13 rounds of STUB action triage across the ToolRouter (65+ new WIRED
  action ids across rounds 2–16: X3, Y1, Z7, AA1, BB1, CC1, GG1, II5,
  JJ6, KK7, MM6, NN2, OO1).
- **UU1 `Observable.__init__`** — now issues a cooperative
  `super().__init__()` call so downstream subclasses that also inherit
  from other mixin bases initialise cleanly; unblocks the Ochema
  Circuit `RenderTarget` MRO chain (`ee732fd`).
- **UU2 `EventBus.unsubscribe`** — 1-arg form
  `unsubscribe(callback)` restored alongside the current 2-arg
  `unsubscribe(topic, callback)`; downstream unsubscribe(None)
  sentinel-semantics kept as a follow-up for v0.4.1 (`b29e601`).
- **VV1 `CacheMode`** — enum shape restored to include
  `OFFSCREEN_SERIALIZE`, `ALWAYS_CACHED`, and `USER_DRIVEN` members
  after PP's Phase-D flip inadvertently pruned them (`82feed0`).

### Deprecated

- Nova3D-legacy editor panel family (still wrapped in
  `MovablePanelWindow` shims but scheduled for removal alongside the
  Phase D strip once downstream games (Ochema Circuit, Bullet Strata,
  Stone Keep) land the notebook-panel migration.

### Removed

- Legacy Nova3D banner from the notebook editor (`38e455c`).
- Consolidated notebook editor path (`38e455c` — inspector + spawn menu
  split into notebook-native panels; old paths removed).

### Fixed

- **OO4** — 2 upstream bugs in `hello_showcase_v3` + test unskipped.
- **X2** — `hello_rope` over-damping + regression tests.
- **Y2** — `hello_joint` over-damping + regression tests.
- **W1** — `hello_ragdoll` over-damping + regression tests.
- **Z1** — `NotebookMessageLog` Windows-headless DPG segfault.
- **AA3** — diary softbody import shim
  (`pharos_engine.softbody` → `pharos_engine.dynamics.SoftBodyWorld`
  fallback path).
- Editor DPG lifecycle: dock-on-release actually resizes / repositions,
  status-bar tick gated on `_running` to avoid `get_delta_time`
  segfault, `toggle_panel` / `toggle_fullscreen` gated on `_running`.
- `NotebookCodePanel` legacy-contract compatibility (`load_script`
  alias + per-frame `update()`).
- DPG callback lambdas accept extra positional args.
- **UU1** — `RenderTarget` MRO regression (Ochema Circuit downstream
  crash): `Observable.__init__` now cooperates with sibling bases via a
  `super().__init__()` call (`ee732fd`).
- **VV2** — 3–5 more backcompat symbols restored end-to-end so the
  downstream stack loads cleanly: `event_bus.EventDetails` type alias,
  `config.DeformConfig` dataclass + parser, `DeformableLayerComponent`
  legacy kwargs (`stiffness_x`/`stiffness_y`/`initial_temperature`),
  and `collision_pixel.PixelCollisionPass.test(a, b)` class-level
  dispatch that forwards to the instance overload (`8cdd2b0`).

### Backwards-compatibility notes

The UU + VV rounds restore public symbols that the PP + earlier
Phase-D flips inadvertently pruned. All entries below are load-bearing
for at least one of Ochema Circuit / Bullet Strata / Stone Keep and
remain part of the public API for v0.4:

- `Observable.__init__` cooperative `super().__init__()` call — UU1
  `ee732fd`; restores mixin composability for downstream `RenderTarget`
  subclasses.
- `event_bus.global_bus` module-level singleton — UU2 `b29e601`;
  restores the pre-v0.4 zero-arg publish/subscribe convenience.
- `EventBus.unsubscribe(callback)` 1-arg form — UU2 `b29e601`;
  overload alongside the current 2-arg `unsubscribe(topic, callback)`.
- `CacheMode.OFFSCREEN_SERIALIZE` / `CacheMode.ALWAYS_CACHED` /
  `CacheMode.USER_DRIVEN` — VV1 `82feed0`; three enum members
  reinstated after a Phase-D over-prune.
- `event_bus.EventDetails` type alias — VV2 `8cdd2b0`; downstream type
  hints resolve without `# type: ignore`.
- `config.DeformConfig` dataclass + parser — VV2 `8cdd2b0`; downstream
  config loaders re-mount without adapter shims.
- `components.DeformableLayerComponent` legacy kwargs — VV2 `8cdd2b0`;
  accepts `stiffness_x` / `stiffness_y` / `initial_temperature`
  alongside the current kwargs.
- `collision_pixel.PixelCollisionPass.test(a, b)` class-level dispatch
  — VV2 `8cdd2b0`; forwards to the instance overload so downstream
  callers using the class-level form load cleanly.

Coverage tracked by
[`api_stability_2026_07_07.md`](docs/api_stability_2026_07_07.md) —
UU7's 338-symbol pinned surface snapshot
(`SlapPyEngineTests/tests/data/api_surface_snapshot.json`) plus the
`test_backcompat_api_surface.py` + `test_backcompat_subclass_patterns.py`
tripwires now guard the restored surface.

### Known issues

- **Gate #12 (game-compat)** — currently **FAILING** at 61.6% F1
  recovery post-VV1+VV2:
  [`game_compat_2026_07_07.md`](docs/game_compat_2026_07_07.md) § 10
  records Ochema Circuit **681/1126 (60.6%)** and Bullet Strata
  **45/54 (83.3%)** against baselines of 1124/1126 and 54/54; the top
  residual class is **228 sites of `unsubscribe(None)`
  sentinel-semantics violation** in the downstream games. Downstream
  games will need v0.4.1 for full compat; per VV7 the recommended
  ship path is **Option B — ship-after-full-recovery**.
- **WIP subpackages** — `softbody/`, `fluid/`, `physics/`, `physics2/`
  remain frozen for this release; the 2D physics substrate ships
  through `pharos_engine.dynamics` (which the studio stages and Rust
  `_core` kernels back).
- **Version strings** — `pyproject.toml`, `Cargo.toml`, and
  `python/pharos_engine/__init__.py` still read `0.3.0b0` /
  `0.3.0-beta.0`; see the
  [PP6 version-bump audit](docs/version_bump_audit_2026_07_07.md) for
  the 8-step atomic tag sequence deferred to the release commit.

### Security

- No known security-relevant changes in this window. `path-traversal`
  guard in `assert_scene_matches` (from v0.3 hardening) continues to
  apply.

## [0.3.0] — 2026-05-31

v0.3 widens the public engine surface from physics + render kernels to a full
set of game-side primitives: dynamics, zones, topology, numerics, thermal,
iso, telemetry, and a visual-regression testing harness. Every new subpackage
ships as a top-level lazy export so games can `import pharos_engine as sle`
and reach the contract without knowing the on-disk layout. Beta-tested vs
Ochema Circuit (1124/1126) and Bullet Strata (54/54).

The full v0.3 surface is auto-generated at
[`docs/engine_surface_v030.md`](docs/engine_surface_v030.md) — 75 top-level
symbols across 19 declared subpackages.

### Added

**New subpackages (top-level lazy exports):**

- `pharos_engine.dynamics` — unified XPBD primitives: `Body`, `Material`,
  `JointSpec` (7 kinds), `RopeSpec`, `RagdollSpec`, `IKChainSpec`, `World`,
  `SoftBodyWorld`, plus authoring helpers `build_rope`, `build_ragdoll`,
  `make_spring`, `make_motor`, `solve_ik`, `resolve_joint`. JSON round-trip
  via `save_world` / `load_world` (byte-identical 0.0 step error, 20/20
  green). Reference: [`docs/dynamics_design.md`](docs/dynamics_design.md).
- `pharos_engine.dynamics.humanoid` — humanoid skeleton (`make_humanoid`,
  `Humanoid` dataclass), flesh-wrap (`wrap_in_flesh`, layer constants
  `LAYER_BONE` / `LAYER_MUSCLE` / `LAYER_SKIN`), and foot-IK terrain
  placement (`place_feet_on_terrain`). Sprint 2A.
- `pharos_engine.dynamics` joint authoring — `make_distance` factory for
  distance constraints and `resolve_joint_specs` batch resolver round
  out the Sprint 7A joint surface alongside `resolve_joint`.
- `pharos_engine.zones` — generic zone primitives (`RectZone`,
  `ThresholdZone`, `ZoneManager`, enter/exit + threshold callbacks).
  Optional spatial-hash backend for 10.9x speedup at 1000 entities.
- `pharos_engine.topology` — connected-components / union-find primitives
  lifted from the bond solver.
- `pharos_engine.numerics` — generic numerical kernels: `vcycle_poisson`,
  `sor_smooth`, `compute_residual`.
- `pharos_engine.thermal` — `HeatField` plus `exchange_two_regions`
  pairwise boundary exchange.
- `pharos_engine.iso` — isometric 2D-grid-with-Z rendering: `IsoCamera`,
  `IsoCell`, `IsoEntity`, `IsoGrid`, `IsoScene`, `IsoTileDef`,
  `IsoViewpoint`, plus an `iso.combat` module (Phase C3 / Stone Keep).
- `pharos_engine.telemetry` — low-overhead event emission (86 ns when no
  subscriber is attached; 6.42x dispatch speedup with subscribers via
  first-segment bucket index). Design:
  [`docs/telemetry_design.md`](docs/telemetry_design.md).
- `pharos_engine.testing` — visual regression harness:
  `assert_scene_matches`, `render_scene_to_png`, `diff_pngs`,
  baseline/diff directory constants.
- `pharos_engine.tools.sprite_audit` — sprite-anchor / atlas audit utility
  (CPU-only). Recipe: [`docs/sprite_audit_recipe.md`](docs/sprite_audit_recipe.md).
- `pharos_engine.audio_runtime` — soft-import with silent-stub fallback so
  headless test environments load cleanly.

**Ochema engine-surface registration (Phase C):**

- Race-scene names added to the top-level `_LAZY_MAP`:
  `CatmullRomSpline`, `SplineTrack`, `PlayerInputProvider`, `CacheMode`,
  `PixelCollisionPass`.
- Phase C close-out: `TriggerSystem`, `ZoneMap`, `GpuParticleSystem`,
  `Observable`, module-level `event_bus.publish` / `subscribe`,
  `StrataWorld` / `StrataLayer`, `RigidBody`, `DeformableLayer`,
  `InputDriven` components.

**Cross-subsystem serialization:**

- Unified JSON + YAML round-trip for `thermal`, `zones`, `iso.combat`,
  `telemetry`, and `SaveGame` (15/15 green).
- `WaveSchedule` round-trip fix (uses `_waves` attribute, not `specs`).
- `SetVersion.bat` helper for version-string consistency.

**Studio / demo authoring (Sprint 7G):**

- `pharos_engine.studio.dynamics_stage` — turn-key Stage wrapper around a
  `dynamics.World` with a default PIL renderer, joining the existing
  `softbody_stage` / `fluid_stage` / `humanoid_stage` set so demos can
  record dynamics scenes with the same 3-line recipe.

**Game-compat shims (Sprint 5B + R2S1-B):**

- `pharos_engine._compat` surfaces back-compat names lifted from retired
  Ochema / Bullet Strata subsystems so downstream games keep importing
  cleanly: `MaterialPreset` and `CrackMode` enums, `SimState` and
  `SimFrequencyBudget` minimal stubs, `DeformController` no-op shim,
  `ZoneMap` alias of `zones.ZoneManager`, `CellMaterial` dataclass +
  `cell_material_for` lookup ported verbatim from the legacy
  `deform_modes` module.

**Engine + tooling:**

- `Engine.run(max_frames=N)` — CI-driveable bounded run for demo smoke
  (Sprint 2C).
- Perf dashboard (`tools/perf_dashboard`) — 6 subsystems, regression
  tripwire on Sprint 6 baselines.
- All-demos integration smoke harness (29 demos discovered, 13 hello_*
  demos in the gallery grid).
- Auto-generated subpackage API reference (9 docs, 30/30 green).
- Editor `spawn_menu` gains rope / ragdoll / IK chain / humanoid
  (Sprint 2F) actions; property inspector reflects dynamics dataclasses
  via runtime introspection (Sprint 3G); material editor extended via
  reflection.

**Demos & docs:**

- `examples/hello_rope.py` — XPBD rope droop reference (2.02 m baseline).
- `examples/hello_ragdoll.py` — humanoid ragdoll demo.
- `examples/hello_ik_chain.py` — CCD IK over a 5-link chain.
- `examples/hello_motor.py` — `MotorSpec` driving a wheel hub + 2 rims
  (ω error 0.05%).
- `examples/hello_spring.py` — 1D Hookean oscillator (2.06% period error).
- `examples/hello_joint.py` — distance / weld / ball / hinge in one scene.
- `examples/hello_thermal.py` — two `HeatField` grids with edge contact.
- `examples/hello_zone.py` — three `RectZone`s + `ThresholdZone` tracking.
- `examples/hello_iso.py` — 10×10 iso arena with wave schedule + combat.
- `examples/hello_telemetry.py` — 60-frame timeline + 100k-emit bench.
- `examples/hello_topology.py` — union-find on 8×8 grid, 64→1 components.
- `examples/hello_numerics.py` — 64×64 Poisson V-cycle solve.
- `examples/hello_audio.py` — `audio_runtime` + sounddevice fallback.
- `examples/hello_composite.py` — iso combat + rope + zones + thermal in
  one scene, telemetry-wired.
- `examples/hello_dynamics_serialize.py` — byte-identical round-trip
  (0.0 delta, 4.4 KB on disk for 16-node rope).
- [`docs/dynamics_quickstart.md`](docs/dynamics_quickstart.md) — 10-minute
  hands-on guide with 6 runnable snippets.
- [`docs/tutorial_build_a_game.md`](docs/tutorial_build_a_game.md) — full
  game tutorial (10 sections, 10 verified-runnable snippets).
- [`docs/getting_started.md`](docs/getting_started.md) — game-dev
  tutorial (8 verified-runnable snippets).
- [`docs/examples_smoke_2026_05_31.md`](docs/examples_smoke_2026_05_31.md)
  — read-only audit of every example on master.
- [`docs/sprint_7_ship_checklist.md`](docs/sprint_7_ship_checklist.md),
  [`docs/perf_dashboard.md`](docs/perf_dashboard.md),
  [`docs/strip_pass_v2_audit.md`](docs/strip_pass_v2_audit.md),
  [`docs/rust_port_plan_dynamics.md`](docs/rust_port_plan_dynamics.md).

### Changed

**Lighting / post-process rounds 2–9:**

- Round 2 (GTAO) — depth-adaptive sample radius (Jimenez 2016) plus
  Sprint 4C `multibounce` toggle on `GTAOPass` (Jimenez 2016 §2.3
  multibounce-visibility approximation, default on).
- Round 3 (Bloom) — Lottes 2017 smooth threshold replaces the binary
  cutoff (14/14 green); Sprint 3D adds 13-tap Mitchell-Netravali
  downsample + 9-tap tent upsample (`upsample_tent9`) for a smoother
  Gaussian-shaped bloom lobe with no extra ringing.
- Round 3 (TAA) — Karis luminance-inverse weighted blend cuts ghosting
  on motion-heavy scenes by 41.3%.
- Round 4 (Vignette) — smoothstep falloff with `inner_radius` + `feather`
  (-23% banding vs legacy quadratic).
- Round 4 (TAA) — variance-based AABB tightening (Salvi 2016).
- Round 4 (TAA) — `tight_variance_clip` now defaults to `True`
  (`variance_clip_gamma=1.0`, Salvi's canonical 1-sigma envelope) after
  Sprint 4D confirmed off-path baselines stay bit-identical. The new
  default delivers Sprint 3D's headline win on disocclusion bands:
  -19.5% ghost residual and +1 dB PSNR vs the legacy min/max envelope,
  with no measurable cost on converged frames. Pass
  `tight_variance_clip=False` to restore the round-3 behaviour.
- Round 5 (TAA, Sprint 5C + R2S1-F) — motion-vector-aware disocclusion
  rejection adds `reject_on_depth_disocclusion` (Andersson INSIDE 2015)
  and `reject_on_normal_disocclusion` (Karis Siggraph 2014) fields on
  `TAAPass`; defaults on, opt out per field to restore Round 4 behaviour.
- Round 5 (Outline) — Sobel + smoothstep edge detection (-84% temporal
  flicker, 13/13 green).
- Round 6 (Chromatic aberration) — Lottes 2014 polynomial falloff (+47%
  corner fringing, 6/6 green).
- Round 7 (Tonemap) — auto-EV via log-luminance + smoothing (95%
  convergence in ~58 frames).
- Round 8 (Render channels) — Kahn topological sort with `depends_on` +
  insertion-order tie-break.
- Round 9 (DoF) — `focus_transition` shape parameter with smoothstep
  softening / sharpening (backward-compat at `transition=1.0`).
- Preset chains — `cinematic` / `arcade` / `iso-strategy`; `add_dof` and
  `add_bloom` helpers; `PostProcessPass.depends_on` field.

**Perf:**

- `numerics.vcycle_poisson` — 2.45x speedup at 256×256 (dropped redundant
  mask multiplies + strided restrict; hot path now ~73% raw numpy).
- `zones` — spatial-hash backend, 10.9x speedup at 1000 entities (parity
  preserved, opt-out via `enable_spatial_hash(False)`).
- `telemetry` — first-segment bucket index, 6.42x dispatch speedup at
  1000 subscribers.
- `EventBus.publish` — inline fast-path validation (218 ns → ~140 ns).
- Sprint 6 perf tripwire — numerics -43%, dynamics 100-node lattice -59%
  steady-state, 80 demo tests green.

**Hardening — input validation at public boundaries.** Six rounds caught
**46+ silent-acceptance bugs** across the v0.3 surface:

- Round 1 (dynamics) — `Body`, `Material`, `JointSpec` family, `RopeSpec`,
  `RagdollSpec`, `IKChainSpec`, and `build_*` / `make_*` helpers raise on
  invalid input at construction. **8 silent-bug classes** (89 tests green).
- Round 2 (zones / topology / numerics / thermal / iso) — `_validation`
  modules on all five Phase-B subpackages. **24 silent-acceptance bugs**
  (111 tests green); worst offender was `WaveSpec(spawn_points=[])`
  raising `ZeroDivisionError` deep inside `tick()`.
- Round 3 (post_process / telemetry / testing / sprite_audit) — 73
  negative tests, 14 silent-acceptance bugs, plus a path-traversal fix in
  `assert_scene_matches`.
- Round 4 (camera / event_bus / action_map) — 41 tests, caught `zoom=0`
  div-by-zero + NaN position + bytes `event_type` silent mismatch.
- Round 5 (AssetDatabase / ResidencyManager) — 45 tests, caught
  `register_handler` ext-without-dot silent dead handler + NaN position
  cascade data-loss.
- Round 6 (animation graph) — 22 tests, caught empty-name + NaN fps +
  non-callable condition + negative-dt silent path.
- Dynamics over-damp warning — fires once process-wide at
  `1 - (1 - damping)^iters > 0.5`, no longer spams the test suite.

**Visual harness baselines** — `pharos_engine.testing` underpins demo
baselines for `hello_rope`, `hello_ragdoll`, `hello_ik_chain`,
`hello_motor`, `hello_spring`, `hello_joint`, `hello_thermal`,
`hello_zone`, `hello_iso`, `hello_telemetry`, `hello_topology`,
`hello_numerics`, `hello_audio`, `hello_composite`, and
`hello_dynamics_serialize`, plus the lighting round-4 side-by-side
baselines.

**Internal:**

- Phase B repackages — `topology`, `numerics`, `thermal`, `zones` lifted
  from legacy locations into first-class subpackages with stable surfaces.
- Phase C1 — Ochema race-scene engine-surface tripwire + completed
  `_LAZY_MAP`.
- Phase C2/C3 — `audio_runtime` shim, `iso.combat` for Stone Keep.
- Phase D dry-run audit — strip-pass v2 deletion candidates enumerated at
  [`docs/strip_pass_v2_audit.md`](docs/strip_pass_v2_audit.md); no files
  deleted, gated on downstream-game CI. Step 1 marked BLOCKED — `world.py`
  is a live frontier consumer.
- Cross-package integration scene — `iso/zones/thermal/dynamics`
  exercised together as one 6/6 regression test (v2 of the harness).
- Game-compat tripwire — 54 names across Ochema / Bullet Strata / Stone
  Keep, 39 pass + 15 xfail tracking Phase C gaps (now closed in Phase C).
- Sprint 7 ship-readiness — version-consistency tripwire
  (`tests/test_version_consistency.py`), `_KNOWN_BROKEN` ratchet
  (20-entry ceiling tracking uncommitted-WIP module gaps).

### Fixed

- `TAA` executor — splice width / height into pre-packed `TaaParams` UBO
  (previously stale).
- `SVGFDenoiser` — restored CPU `denoise_numpy` path + `reset_history()`
  API (Sprint 2B).
- `Layer3D.lighting_mode` + `gbuffer_target` setter — wires through to
  `defer_2d` (4 tests recovered).
- `IKChainSpec.node_indices` validator — rejects non-int (float was
  silently truncated to 1; docstring-validator mismatch surfaced by API
  reference auto-gen).
- `WaveSchedule` round-trip — uses `_waves` attribute, not `specs`.
- `collision.stamp_entity` / `stamp_all_entities` — implemented.
- `NodeMaterial` — restored sim-field / math / output node factories.

### Removed

- Stale `pharos_engine.compose` reference in the previous README.
- Legacy `mud_pool` demo (replaced by `ParticleField` polish series).
- Phase D `Unreleased` placeholder section (work landed under this
  version).

## [0.2.0a0] — 2026-05-25

Pre-Rust-migration alpha. Pure-Python physics + numpy renderers. See git
history for incremental changes.

## [0.1.0a0]

Initial alpha pre-release.
