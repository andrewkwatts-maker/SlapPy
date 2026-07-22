# Sprint Rollup — 2026-07-04 (V / W / X / Y / Z / AA / BB / CC / DD batches)

Consolidated retrospective of the nine-batch scrum push that ran between
`db56df3` (V-batch start freeze, 2026-06-07 master review + 7-sprint
refactor plan) and `7be6617` (DD1/DD3/DD5 salvage, 2026-07-05 nightly).
Nine batches, approximately 63 sprint slots dispatched to parallel
agents, ~76 commits landed on master. The engine feature map moved from
233 rows at V1 freeze to **281 rows with 263 WIRED (93.6%)** at DD1
close. All six diary themes, three 15-shader WGSL libraries (washi tape,
page linings, edge strokes), six baked prefabs, and six baked layout
presets shipped alongside a diary-shell workspace, prefab library,
autosave subsystem, hotkey remap layer, toast notification system,
camera-tween animator, VS-Code-style command palette, telemetry
dashboard, timeline editor, smoke runner, and shader batch validator.
Live viewport polish (TAA / bloom / gizmo overlay), seven hardening
rounds, nine new hello_* demos, and a 35-action `pharos_editor.actions.*`
subpackage round out the push; downstream game compat (Ochema Circuit /
Bullet Strata) was deliberately not touched.

---

## Batch-by-batch table

| Batch | SHA range | Agent slots | Sprints landed | Notable landings |
|-------|-----------|-------------|----------------|------------------|
| **V** | `a714b3a`..`a714b3a` (single salvage commit rolling up 7 disjoint scopes) plus `8205368`..`1467f91` for the T/U theming pre-work that V1 audited | ~7 | V1 feature-map audit, V2 project registry, V3 inspector reflection, V4 snap overlay, V5 material nodes, V6 bidirectional codegen, V7 animated washi tape | Engine feature map v1 (233 rows). `pharos_engine.project_registry` + startup-prompt panel. 18+ WGSL material graph nodes. Python↔Graph codegen. 8 animated washi tape shaders (heart pulse / sparkle shimmer / rainbow flow / marching dots / wave shift / dashed scroll / stars twinkle / music notes flow). Budget widened to 1000B. |
| **W** | `607bffe`..`f59a6f9` plus `b019bdb` router patch | ~6 | W1 hello_ragdoll fix, W2 four-panel hardening, W3 TAA polish, W4 bloom polish, W6 hello_integrated_notebook | TAA — YCoCg variance clip + Halton(2,3)-8 + velocity blend + rejection heuristics. Bloom — Karis 13-tap downsample + tent upsample + firefly filter. Four-panel silent-acceptance hardening (material / theming / spawn / diary) with 31 fixed bug-classes. `editor.toggle_panel_tag_painter` action registered. |
| **X** | `d339995`..`194a0c9` | ~7 | X2 hello_rope fix, X3 STUB triage round 1, X4 content browser project view, X5 chain manifest, X6 live reload watcher, X7 6 widget primitives | `pharos_editor.actions.*` subpackage bootstrap (5 actions). Notebook content browser `set_project` with 6 asset-kind groups + fuzzy search + right-click ctx menu. Declarative post-process chain manifest via `apply_manifest`. `UserOverrideLoader.watch_dir` / `autoreload` with watchdog soft-import. 6 new widgets: GlitterProgressBar, RibbonTab, PaperClipAttachment, WashiTapeDivider, SketchButton, InkStampBadge. |
| **Y** | `48eb8ee`..`61d6b83` | ~7 | Y1 STUB triage round 2, Y2 hello_joint fix, Y3 prefab library, Y4 gizmo overlay, Y5 message log, Y6 autosave subsystem, Y7 re-audit | Feature-map delta doc (Y7). `pharos_engine.prefabs` — Prefab dataclass + PrefabLibrary registry + 7 body kinds + `.prefab.yaml` round-trip. `pharos_engine.autosave` — AutosaveManager threading.Timer + RecoveryPrompt / RecoveryOffer. NotebookGizmoOverlay hand-drawn move/rotate/scale handles. NotebookMessageLog + `_DiaryLogHandler` telemetry bridge. 5 more actions wired (`tool.select_all` / `deselect_all` / `editor.copy_selection` / `paste_selection` / `theme.cycle`). |
| **Z** | `fb073f4`..`39cad69` | ~7 | Z1 message-log headless fix, Z2 prefab spawn menu, Z3 baked chain presets, Z4 hello_prefab + hello_autosave, Z5 docs polish, Z6 editor autosave integration, Z7 STUB triage round 3 | NotebookPrefabMenu 96×96 card grid. 6 baked post-process chain presets (`default` / `crisp` / `dreamy` / `neon` / `retro_film` / `debug`) via ChainBaker. EditorAutosaveIntegration wiring Y6 into shell lifecycle. Fix for `NotebookMessageLog` real-DPG headless segfault. 5 more actions wired (`tool.snap_to_grid` / `view.zoom_in` / `zoom_out` / `zoom_reset` / `theme.export_current`). README + quickstart + onboarding polish. |
| **AA** | `f6bb3f0`..`9997cdd` | ~7 | AA1 STUB triage round 4, AA2 prefab/autosave polish, AA3 diary softbody bridge, AA4 material graph bridge, AA5 hello_full_editor, AA6 WGSL shader lint, AA7 hotkey remap | `pharos_editor.ui.editor.diary_softbody_bridge` shim + 8-test suite (rows 80/223 preview-flip). MaterialGraphBridge round-trip between V5 material nodes and NotebookMaterialEditor. hello_full_editor end-to-end scripted demo (6 pages + prefabs + material + autosave + 6 themes + 37 events). `pharos_engine.shader_lint` with 53-shader coverage. `pharos_editor.ui.hotkey_remap` + 3 baked hotkey presets. 5 more actions wired (`edit.cut_selection` / `delete_selection` / `view.center_on_selection` / `frame_all` / `tool.pan`). PrefabLibrary API polish (spawn / entity_count / bake_and_load) + AutosaveManager.read_snapshot. |
| **BB** | `a360d56`..`8b6f8b1` | ~7 | BB1 STUB triage round 5, BB3 autosave panel, BB4 shader hot-reload watcher, BB5 sprint rollup, BB6 prefab preview baker, BB7 hotkey help panel | 5 more actions wired (`theme.import_from_file` / `file.save_layout_as` / `file.load_layout_from_file` / `edit.undo` / `edit.redo`). NotebookAutosavePanel snapshot restore. Shader hot-reload watcher (auto-lint WGSL edits). Prefab preview icon baker + 6 baked previews. NotebookHotkeyHelp diary-themed rebind panel. Rollup doc for V-AA batches. |
| **CC** | `2b835c3`..`06620e8` | ~7 | CC1 STUB triage round 6, CC2 hello_material_graph, CC3 asset inspector, CC4 baked layout presets, CC5 toast manager, CC6 camera tweens, CC7 command palette | 5 more actions wired (`edit.select_by_name` / `spawn.repeat_last` / `view.toggle_grid` / `view.toggle_gizmos` / `content.copy_asset_path`). hello_material_graph demo (4 WGSL graphs via V5+AA4 bridge). NotebookAssetInspector (7 asset kinds — script/scene/texture/material/shader/prefab/other). 6 baked layout presets (default/triple_pane/wide_code/focus_mode/debugging/presentation) via LayoutBaker. NotebookToastManager (4 levels + 20 sticker glyphs + logging subscriber). Camera animation tweens (`view.focus_on_selection_animated` + `view.frame_all_animated`) with 6 easing curves. NotebookCommandPalette (Ctrl+Shift+P VS-Code-style fuzzy finder). |
| **DD** | `324e8e6`..`7be6617` | ~6 (DD7 lost) | DD1+DD3+DD5 salvage, DD2 hello_toast_animation, DD4 telemetry dashboard, DD6 shader batch validator | 5 more actions wired via DD1 salvage (`layer.duplicate` / `panel.close_all` / `panel.restore_last_hidden` / `spawn.repeat_last_batch` / `theme.cycle_reverse`). SmokeRunner (DD3 salvage — discover/run_one/run_all_parallel + format_summary + write_report). NotebookTimelineEditor (DD5 salvage — keyframe curves, cubic/linear/step interpolation, YAML round-trip). hello_toast_animation demo (6-second CC5+CC6 walkthrough at 60 FPS). NotebookTelemetryDashboard (4 view kinds — counters/gauges/histograms/perf timers, CSV export). Shader batch validator (walks 3 libraries + all `*.wgsl` roots, Markdown report + YAML manifest for CI). DD7 not committed. |

---

## Feature-by-feature detail

### Editor UX

The notebook editor's public surface expanded by ~25 panels + widgets
across the push:

* **DiaryShell** (pre-V) — book-of-pages workspace with right-edge index
  tabs. 6 default pages (Scene / Code / Material / Animation / FX /
  Settings). Extended by hello_full_editor (AA5) to script an end-to-end
  session with all pages visited.
* **NotebookStartupPrompt** (V2) — first-run modal with three buttons
  (row-open / new / skip), gates access to the editor until a project is
  chosen.
* **NotebookProjectRegistryPanel** (V2) — Nova3D-style recent-projects
  grid backed by `pharos_engine.project_registry`.
* **NotebookSnapOverlay** (V4) — dashed-rect drag ghost + dock-zone arrow
  indicators for panel repositioning.
* **NotebookGizmoOverlay** (Y4) — hand-drawn move / rotate / scale
  handles with TOOL_MOVE / TOOL_ROTATE / TOOL_SCALE handle sets,
  `set_selection_bbox` auto-hide, drag lifecycle publishing (dx, dy) /
  (d_radians,) / (sx, sy). Deterministic FNV-1a-seeded 1.4 px wobble.
* **NotebookMessageLog** (Y5) — scrolling log panel with per-level filter
  chips (DEBUG / INFO / WARN / ERROR), search box, clear, save-to-file,
  pause/resume. Bounded ring buffer (default 500). `_DiaryLogHandler`
  installs on any logger; `subscribe_to_telemetry` binds to
  `pharos_engine.telemetry`.
* **NotebookPrefabMenu** (Z2) — 96×96 card grid presenting a
  `PrefabLibrary` as spawn cards; category filter combo + substring
  search + right-click Spawn / Spawn N / Copy Name / View YAML ctx menu.
* **EditorAutosaveIntegration** (Z6) — wires Y6 into shell lifecycle so
  snapshots fire on the editor's timer tick.

### Theming

* **DeclarativeTheme** (pre-V) — CSS-like theme spec parser. Baseline
  for all six diary themes.
* **Washi tape shaders** — T2 library (15) + V7 animated additions (8):
  heart_pulse, sparkle_shimmer, rainbow_flow, marching_dots, wave_shift,
  dashed_scroll, stars_twinkle, music_notes_flow. Budget widened to
  1000B for animated variants.
* **Page linings shaders** (U3) — 15 paper-stock backgrounds.
* **Edge stroke shaders** (U4) — 15 pen/pencil/marker/chalk shaders.
* **UserThemeStore** (pre-V) — baked-YAML theme subsystem; W2 wired
  `NotebookThemingEditor.save_as_new` through it (row 189 STUB → WIRED).
* **shader_lint** (AA6) — `pharos_engine.shader_lint` covers all 53
  shaders across the three libraries. Checks: 1000-byte budget,
  `@fragment` + `fs_main` + `@location(0)` presence, uniform contract
  adherence against struct-field discovery, deprecated `[[block]]` /
  `[[binding]]` syntax warnings, ASCII hygiene, soft wgpu
  `create_shader_module` round-trip.

### Content

* **pharos_engine.projects** + **project_registry** (pre-V + V2) — full
  Nova3D-style multi-project management with persistent
  `~/.pharos_engine/projects.yaml` recents.
* **pharos_engine.prefabs** (Y3) — Prefab dataclass (name, category,
  body_spec dict, joint_specs, child_prefabs, metadata); YAML round-trip;
  `spawn(world, position, rotation)` materialises into a
  `pharos_engine.dynamics.World`. Seven body kinds: point / circle / box /
  rope / ragdoll / chain / composite. PrefabLibrary with
  register/get/list_all/list_by_category + `bake_defaults` mirroring the
  UserThemeStore pattern.
* **Six baked prefabs** — crate, ball, chain, windmill (+ two more in
  the library). Load via `PrefabLibrary.bake_defaults()`.
* **AA2 API polish** — `PrefabLibrary.spawn`, `entity_count`,
  `bake_and_load` sugar. `Prefab.spawn` on the dataclass directly.
* **NotebookContentBrowser project view** (X4) — when a `Project` is
  loaded via `set_project`, walks `assets/` and groups into 6 kinds
  (Scripts / Scenes / Textures / Materials / Shaders / Other). Each
  group is a DPG collapsing header; rows are click-through with
  `on_asset_selected(path, kind)` callback and right-click Open / Reveal
  / Copy Path / Delete ctx menu. Fuzzy search box filters visible rows
  (substring first, then per-char subsequence).

### Post-process

* **TAA polish** (W3) — YCoCg variance clip + Halton(2,3)-8 sequence +
  velocity blend + rejection heuristics.
* **Bloom polish** (W4) — Karis 13-tap downsample + tent upsample +
  firefly filter (committed twice as `894266a` + `7c23a87`; identical
  content).
* **Chain manifest** (X5) — declarative YAML pass ordering via
  `post_process/chain_manifest.py` + `executor.from_manifest`.
  `apply_manifest` CPU dispatcher carries manifests through the
  executor.
* **Baked chain presets** (Z3) — six preset chains shipped via
  `ChainBaker` and `baked_chains/*.chain.yaml`:
  * `default` — production baseline
  * `crisp` — high-detail preset
  * `dreamy` — soft-focus (used by hello_full_editor AA5)
  * `neon` — chromatic aberration + grain
  * `retro_film` — chromatic aberration + grain
  * `debug` — pass-through with per-pass overlays
  Custom pass kinds (chromatic_aberration, grain) are backed by
  pass-through CPU stubs via `ChainBaker.register_stub_handlers`.

### Visual scripting

* **Material nodes** (V5) — 18+ WGSL-emitting graph nodes on
  `visual_scripting.material_nodes`. Palette-visible from the Notebook
  Node Editor.
* **Bidirectional codegen** (V6) — Python AST ↔ Graph, on
  `visual_scripting.codegen`. Golden fixtures under
  `PharosEngineTests/goldens/visual_scripting/` (arithmetic, assignment
  reuse, boolean logic, comparison chain, for range, function call
  chain, nested if, while countdown). The Diary "Generate Python from
  nodes" button (row 79) still emits placeholder — planned one-line
  rewire to `codegen.graph_to_python`.
* **MaterialGraphBridge** (AA4) — round-trip integration between V5
  material nodes and NotebookMaterialEditor. `to_material` walks a
  NodeGraph via `topological_order` and concatenates each node's
  `emit_wgsl` fragment; `used_uniforms` bubble up through a shared
  `_BridgeEmitContext`. `from_material` inflates a material dict into a
  NodeGraph, collapsing the compiled WGSL body into a single `raw_wgsl`
  node so mixed graphs still round-trip.

### Hardening

* **W1 hello_ragdoll fix** (`607bffe`) — over-damping regression + tests.
* **W2 four-panel silent-acceptance sweep** (`f59a6f9`) — 31 fixed bug
  classes across material (6) / theming (8) / spawn (9) / diary (8)
  panels. Every save / apply / set_* / _on_* / commit / dispatch / bind
  / refresh method now validates inputs, warns on missing dependencies,
  returns bool status, and exposes `_validate_state()` for tests.
* **X2 hello_rope fix** (`d339995`) — matching over-damping pattern.
* **Y2 hello_joint fix** (`8e0ec54`) — drops RIGID/BALL/HINGE damping
  from 0.05 to 0.018 so `solver_iterations (16) * damping = 0.288` sits
  inside the recommended 0.3 throttle band. Adds `DAMPING` module
  constant + `summary["iters_x_damping"]` for future regression
  visibility. 7 new pytest cases (14 total).
* **Z1 message-log real-DPG segfault fix** (`fb073f4`) — under
  `SLAPPY_HEADLESS=1` on Windows, calling `dpg.group(...)` without a DPG
  context access-violates inside the C runtime (unrecoverable via
  try/except). `_safe_dpg` now returns None when the imported dpg
  module is real AND `SLAPPY_HEADLESS` is set.
* **AA2 API polish** — PrefabLibrary + AutosaveManager surface polish
  (spawn / entity_count / bake_and_load / read_snapshot).

### Demos

Seven new hello_* demos landed (or fixed):

| Demo | Batch | File | Notes |
|------|-------|------|-------|
| `hello_ragdoll` (fix) | W1 | `PharosEngineExamples/examples/hello_ragdoll.py` | Damping regression + tests. |
| `hello_integrated_notebook` | W6 | `PharosEngineExamples/examples/hello_integrated_notebook.py` | DiaryShell + panels end-to-end. |
| `hello_rope` (fix) | X2 | `PharosEngineExamples/examples/hello_rope.py` | Damping regression + tests. |
| `hello_joint` (fix) | Y2 | `PharosEngineExamples/examples/hello_joint.py` | Damping fix + iters × damping metric. |
| `hello_prefab` | Z4 | `PharosEngineExamples/examples/hello_prefab.py` | 4 baked prefabs (crate + ball + windmill + chain), 120 frames at 1/60 s, PIL rasterise. 12 entities. |
| `hello_autosave` | Z4 | `PharosEngineExamples/examples/hello_autosave.py` | ~6 s of editor activity, AutosaveManager every 1 s + crash + RecoveryPrompt restore. |
| `hello_full_editor` | AA5 | `PharosEngineExamples/examples/hello_full_editor.py` | Full scripted session: 6 pages, 5 outliner selects, 3-node NodeGraph (math.constant → math.mul → render.material_out), MaterialGraphBridge, `dreamy` chain preset, `sin(x)*a + b` math eval, autosave × 3 force_saves, 6 themes cycled. 37 events → `hello_full_editor_trace.yaml`. |

### Actions subpackage

`pharos_editor.actions.*` bootstrapped in X3 and grew across five sprints
to cover **20 previously-absent router action ids** spanning 5 category
buckets (`file` / `edit` / `tool` / `view` / `theme`):

* **X3 (5)** — `editor.save_project`, `editor.new_project`,
  `editor.open_recent`, `view.reset_layout`, `edit.duplicate_selection`.
  Backing files: `actions/project_actions.py`, `view_actions.py`,
  `edit_actions.py`. Test file: `test_stub_triage_x3.py` (25 tests).
* **Y1 (5)** — `tool.select_all`, `tool.deselect_all`,
  `editor.copy_selection`, `editor.paste_selection`, `theme.cycle`.
  Backing files: `actions/selection_actions.py`, `theme_actions.py`.
  Test file: `test_stub_triage_y1.py` (29 tests).
* **Z7 (5)** — `tool.snap_to_grid`, `view.zoom_in`, `view.zoom_out`,
  `view.zoom_reset`, `theme.export_current`. Backing files:
  `actions/tool_settings_actions.py`, `camera_actions.py`,
  `theme_io_actions.py`. Test file: `test_stub_triage_z7.py`
  (36 tests). Zoom step defaults to 1.2× multiplicative; clamped to
  `[0.05, 10000]` for `_cam_distance` and `[0.01, 100]` for
  `_zoom_level`. Theme export YAML-round-trippable via
  `ThemeSpec.from_yaml`; reuses `UserThemeStore._atomic_write_text`.
* **AA1 (5)** — `edit.cut_selection`, `edit.delete_selection`,
  `view.center_on_selection`, `view.frame_all`, `tool.pan`. Backing
  files: `actions/destructive_edit_actions.py`,
  `viewport_framing_actions.py`, `tool_mode_actions.py`. Test file:
  `test_stub_triage_aa1.py` (34 tests). `frame_all` writes
  `_cam_distance = max(radius * 2 * 1.15, 5.0)` with clamps; `tool.pan`
  deliberately bypasses `NotebookToolbar.set_active` (pan isn't a
  sticker tool).
* Plus the pre-V post-V1 `editor.toggle_panel_tag_painter` registration
  in commit `b019bdb`.

Combined roll-up per the feature-map footer: **266 total rows, 248
WIRED (93.2%), 15 STUB (5.6%), 3 BROKEN (1.1%)**.

### User customization

* **X6 UserOverrideLoader.watch_dir / autoreload** — watchdog
  soft-imported (dev extra); missing install yields `NullWatcherHandle`
  and one-time warning. 100 ms debounce + `.` / `_` prefix filter +
  atomic swap + WatcherHandle context manager.
* **AA7 pharos_editor.ui.hotkey_remap** — HotkeyBinding dataclass
  (canonical combo, action_id, enabled, source) + HotkeyMap with
  add/remove/resolve/list_all/merge/to_yaml/from_yaml/validate.
  `load_user_hotkeys` reads `~/.pharos_engine/ui/hotkeys/*.yaml`;
  `apply_remap` does user-wins merge with disabled bindings stripping
  defaults; `bake_defaults` is idempotent first-launch copy from
  wheel-baked presets. Ships 3 baked presets at
  `python/pharos_engine/ui/hotkeys/baked/`: `default.yaml` (mirror of
  `NotebookHotkeys.BINDINGS`) plus two style variants.
* **UserThemeStore** — user-side theme override + bake pipeline.
  `save_as_new` wired through W2's `NotebookThemingEditor.save_as_new`.
* **User overrides directory** — `~/.pharos_engine/ui/` panel / hotkey /
  spawn card / shader override folders (documented in
  `docs/user_customization_2026_06_07.md`).

---

## CC batch (2026-07-04 late)

Seven CC-batch sprints landed between `2b835c3` and `06620e8` on
2026-07-05 (~06:51–06:55 window). The batch focused on polish surfaces:
a second demo pass through the V5/AA4 material graph, a specialist
asset inspector, baked layout presets to mirror the ChainBaker /
PrefabLibrary / UserThemeStore baking pattern, and three UX
subsystems (toast notifications, camera tweens, command palette).

* **CC1** (`06620e8`) — Round 6 STUB triage. Five action ids wired:
  `edit.select_by_name` / `spawn.repeat_last` / `view.toggle_grid` /
  `view.toggle_gizmos` / `content.copy_asset_path`. Backing modules:
  `edit_by_name_actions.py`, `spawn_history_actions.py`,
  `view_toggle_actions.py`, `content_shell_actions.py`. Every helper
  raises `TypeError` on `None`/non-mapping ctx (BB2 hardening pattern).
  39 regression tests.
* **CC2** (`54b9104`) — `hello_material_graph` demo. Compiles four
  material graphs (simple diffuse, fresnel-tinted, Perlin noise ramp,
  textured PBR) via the V5 palette + AA4 `MaterialGraphBridge.emit_full_shader`.
  Emits `hello_material_graph_<name>.wgsl` next to the module plus an
  18-event trace. Declares two demo-local `MaterialNode` subclasses
  (`ConstantVec3`, `ConstantFloat`) to plug the constant-leaf gap.
  10 tests.
* **CC3** (`039763e`) — `NotebookAssetInspector`. `MovablePanelWindow`-wrapped
  diary-themed inspector that swaps its body layout on the currently-selected
  asset's kind: script (line-capped source w/ syntax hints), scene (YAML
  summary), texture (128×128 PIL preview + metadata), material (WGSL
  summary + "Open in Material Editor" callback), shader (WGSL + byte
  count + AA6 lint WARN/ERROR), prefab (node/joint count + bbox +
  optional BB6 preview bake), other (size + mtime + hex dump). 55 tests.
* **CC4** (`2b835c3`) — Baked layout presets. Mirrors the ChainBaker /
  PrefabLibrary / UserThemeStore baking pattern for editor layout
  snapshots. Six shipping presets under
  `python/pharos_engine/ui/editor/baked_layouts/*.layout.yaml`:
  `default`, `triple_pane`, `wide_code`, `focus_mode`, `debugging`,
  `presentation`. `LayoutBaker` exposes
  `bake_defaults` / `list_baked` / `list_user` / `load` /
  `is_edited` / `revert` with user-wins-over-baked precedence.
  `LayoutPersistence.load_baked_preset()` classmethod delegates
  lazily. `pyproject.toml` maturin include glob picks up
  `*.layout.yaml`. 46 tests.
* **CC5** (`7b14ec7`) — `NotebookToastManager`. `ToastLevel` enum
  (INFO / SUCCESS / WARN / ERROR) with diary-page-palette border colours.
  `Toast` dataclass with `progress()` reporting slide-in (300 ms) /
  hold / fade-out (500 ms) / expired phases and alpha.
  `show`/`dismiss`/`dismiss_all`/`tick` transport + `on_toast_shown`
  / `on_toast_dismissed` subscribers. Newest-first stacking with
  `max_visible` cap (default 5). `subscribe_to_logging(threshold=WARNING)`
  installs a stdlib logging handler so any warning-level record becomes
  a toast automatically. 20-glyph `STICKER_OPTIONS`. 69 tests.
* **CC6** (`78755c8`) — Camera animation tweens. New
  `camera_animation_actions.py` with `CameraAnimator` (non-blocking
  pan/zoom/focus/frame-all tweens), `CameraTweenState` dataclass,
  six easing curves (`linear`, `ease_in`, `ease_out`, `ease_in_out`,
  `bounce`, `back`), and `_fb_tween_to_position` +
  `_fb_focus_on_entity` router fallbacks. Wires
  `view.focus_on_selection_animated` (800 ms `ease_in_out`) and
  `view.frame_all_animated` (1200 ms) into `tool_router.REGISTRY`.
  45 tests.
* **CC7** (`c923b82`) — `NotebookCommandPalette`. Ctrl+Shift+P overlay
  that fuzzy-searches every `ToolRouter` action. Substring on
  label/action_id first, then acronym match; ties broken by category
  priority (`file > edit > tool > view > panel > theme > spawn > other`).
  Recent-actions ring buffer (max 8, MRU/dedup) surfaces on top when
  the search is empty. Diary-themed washi-tape overlay with hand-drawn
  separator. `open`/`close`/`toggle` bound to Ctrl+Shift+P; arrow keys
  move highlight, Enter dispatches + closes, Escape closes without
  dispatch. Stale recent action_ids filtered on router mutation. 60 tests.

**CC batch total**: 7 landings, ~327 new tests, 5 STUB → WIRED flips
(feature map jumps 271 → 276 rows).

---

## DD batch (2026-07-04 nightly)

Six DD-batch sprints landed (DD7 lost — no commit reached master)
between `324e8e6` and `7be6617` on 2026-07-05 (~08:00–10:09 window).
Three of the seven agents (DD1 STUB triage r7, DD3 smoke runner,
DD5 timeline editor) hit rate limit during summary generation but
had already dropped complete files in the working tree; those three
were salvaged as a single commit.

* **DD1 + DD3 + DD5 salvage** (`7be6617`) — three-in-one salvage
  commit. **DD1** (round 7 STUB triage): 5 more actions wired
  (`layer.duplicate` / `panel.close_all` / `panel.restore_last_hidden`
  / `spawn.repeat_last_batch` / `theme.cycle_reverse`); backing
  modules `layer_duplicate_actions.py`, `panel_visibility_actions.py`,
  `spawn_batch_actions.py`, `theme_cycle_reverse_actions.py`.
  40 tests. **DD3** (`smoke_runner.py`): `SmokeRunner` + `SmokeResult`
  + `discover` / `run_one` / `run_all_parallel` + `format_summary` +
  `write_report`; 30 tests. **DD5** (`NotebookTimelineEditor`):
  keyframe curve editing, cubic/linear/step interpolation, YAML
  round-trip; ~79 tests. All 149 tests pass.
* **DD2** (`324e8e6`) — `hello_toast_animation` demo. Scripted
  6-second timeline driving `NotebookToastManager` + `CameraAnimator`
  together at 60 FPS with a `MockCamera` and origin-beacon
  `MockEntity`. Records per-frame camera state, active-tween count,
  and toast counts into `hello_toast_animation_trace.yaml`, then
  prints a milestone table to stdout. Fully headless.
* **DD4** (`18b9618`) — `NotebookTelemetryDashboard`.
  `MovablePanelWindow`-wrappable panel that buckets `telemetry.emit`
  events into four synthetic views: counters (with per-poll delta),
  gauges (60-sample sparklines rendered as pencil-jittered polylines),
  histograms (hand-drawn ASCII bar charts), perf timers (sorted by
  mean, showing count / p50 / p95 / p99 / max). Header exposes
  Pause/Resume + Clear + Auto-scroll + Export CSV + poll-interval
  slider (100..5000 ms). Diary-themed via `DoodleSeparator` +
  washi tape underline. 46 tests.
* **DD6** (`8c55a43`) — Shader batch validator. Walks the three
  notebook theme libraries plus any `*.wgsl` files under `ui/theme/`,
  `gi/`, `post_process/`, `hello_examples/` and (optionally) the
  `post_process/baked_chains` subtree. Every source is routed through
  the AA6 `lint_wgsl` (piggybacks on wgpu when available), aggregated
  into a `ValidationSummary`, and emitted as a Markdown report plus a
  YAML manifest for CI tracking. 25 tests.
* **DD7** — Lost. No commit reached master. Retry needed on the next
  batch.

**DD batch total**: 6 landings (7 dispatched), ~149 new tests, 5 STUB
→ WIRED flips via the DD1 salvage (feature map jumps 276 → 281 rows).

---

## Test coverage summary

At sprint end the test suite passes (individual per-batch counts as
reported by each sprint's commit message):

* V-batch: 1279 passing (per V-batch commit body).
* W2: four-panel hardening rewire, tests included in W2 commit.
* X3: 25 tests. X4-X7: each individually green.
* Y1: 29 tests. Y3 prefab library: ~58 tests. Y4 gizmo overlay: 38.
  Y5 message log: 61. Y6 autosave: individual regression coverage.
  Y7: no test changes (docs-only).
* Z-batch: Z2 notebook prefab menu 58, Z3 chain baker 38, Z6 editor
  autosave 544-line test module, Z7 36.
* AA-batch: AA1 34, AA2 API polish tests in
  `test_api_polish_aa2.py`, AA3 diary softbody bridge 8, AA6 shader
  lint 244.
* BB-batch: BB1 37, BB3 autosave panel, BB4 shader hot-reload,
  BB6 preview baker, BB7 hotkey help.
* CC-batch: CC1 39, CC2 10, CC3 55, CC4 46, CC5 69, CC6 45, CC7 60
  — **~327 new tests**.
* DD-batch (salvage-inclusive): DD1 40, DD3 30, DD5 ~79, DD2 demo
  coverage, DD4 46, DD6 25 — **~149 new tests** (DD1+DD3+DD5 salvage
  commit reports 149 combined for the three rate-limited sprints).

Aggregate order-of-magnitude: **~4476+ tests running** across
`PharosEngineTests/tests/` at DD-close (roughly ~4000 at AA5 + 327 CC
+ 149 DD). No batch reported a red suite. The seven rounds of STUB
triage (X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1 plus the pre-V post-V1
tag_painter registration) collectively land 35 new router-action
wirings across 8 category buckets (`file`, `edit`, `tool`, `view`,
`theme`, `panel`, `spawn`, `content`) + ~250+ regression tests.

---

## What's next

Concrete follow-ups the nine batches deferred:

0. **DD7 retry.** The seventh DD-batch sprint slot produced no commit
   (rate-limit-induced silent drop with no working-tree fragment to
   salvage). Re-dispatch on the next batch; scope should be reconfirmed
   against the DD sprint plan.
1. **Uncommitted physics WIP dirs need tracking.** `git status` at
   AA-close shows uncommitted trees for `python/pharos_engine/softbody/`,
   `python/pharos_engine/fluid/`, `python/pharos_engine/physics/`,
   `python/pharos_engine/physics2/`, `src/fluid_shader.rs`,
   `src/pbf_solver.rs`, `src/raster.rs`, `src/softbody_solver.rs`, plus
   ~40 physics module files (`body.py`, `broadphase.py`, `ccd.py`,
   `cell.py`, `constraints.py`, `hull.py`, `particles.py`,
   `pressure_multigrid.py`, `world.py`, and more). AA3's bridge shim was
   built specifically so these can land without breaking the diary
   runner; a follow-up sprint should stage + review + commit these.
2. **Softbody / diary panel un-pinning still pending.** AA3
   shipped `diary_softbody_bridge.py` + 8 tests but did NOT rewire the
   two callsites at `notebook_diary_page.py:539` (stage construction)
   and `notebook_diary_page.py:610` (per-tick step) because that file is
   pinned read-only by the AA-batch sprint plan. Un-pin the diary panel
   and swap in `bridge.step_stage(stage)` to flip both rows to WIRED on
   the next feature-map delta. Rows 80 / 223 still BROKEN.
3. **Remaining STUBs after DD1 (15 total, unchanged from AA1 tally).**
   Seven rounds of triage (X3 + Y1 + Z7 + AA1 + BB1 + CC1 + DD1) landed
   35 new router wirings + 1 flip (row 189 W2), but the 15 canonical
   STUB rows below all persist:
   * Row 50 — `H` hotkey Toggle HUD: only flips `shell._hud_visible`;
     nothing reads it. Route through the viewport renderer's overlay
     layer.
   * Row 78 / 223 — Diary "Open…" button silent no-op (paired with
     `open_diary_picker` engine hook that doesn't exist). Wire a Tk
     fallback directly in the panel (same pattern `menu_open_scene`
     uses).
   * Row 79 / 222 / 224 — Diary "Generate Python from nodes" placeholder.
     V6 `codegen.graph_to_python` is now available; one-line rewire.
   * Rows 94 / 95 — Inspector `?` popups (call_log-only stubs). Bake
     docstring text into the DPG popup.
   * Rows 191 / 192 — Theming editor Import / Export. Wire Tk save /
     open + reuse existing YAML serializer.
   * Row 193 — Notebook status bar theme indicator click. Shell override
     hook missing.
   * Rows 225 / 226 / 227 — Registered panel-toggle actions with no
     menu / hotkey binding path. Add to View menu or extend
     `_BINDINGS_FROZEN`.
   * Row 228 — Editor sticker "creature slot" click; passive slot only.
   * Row 243 — X4 content browser Delete asset ctx menu handler unbound.
4. **Nova3D legacy strip blocked by test pinning.** Per W5 sprint
   scoping notes the Nova3D legacy panels (`layer_panel`,
   `layer_lighting_panel`, `behavior_panel`, `anim_graph_panel`,
   `code_mode_panel`, `content_browser`, `material_editor`,
   `node_graph_panel`, `property_inspector`, `script_binding_panel`)
   remain in-tree because their live tests were pinned. Consolidation
   report at `docs/consolidation_2026_06_07.md` catalogues the deletion
   blockers.
5. **Diary panel un-pin sprint** — a single sprint that un-pins
   `notebook_diary_page.py` and rewires it through
   `diary_softbody_bridge` + `codegen.graph_to_python` would flip 4
   feature-map rows (78 / 79 / 80 / 223) in one commit.
6. **Chain manifest wiring** — X5 landed the manifest infrastructure
   and Z3 landed the baked presets. A follow-up sprint should wire the
   `NotebookPostProcessPanel` preset combo to load from
   `~/.pharos_engine/postprocess_chains/` instead of the hardcoded
   preset registry.

---

## Key file paths

Docs:

* `H:\Github\Pharos Engine\docs\engine_feature_map_2026_07_04.md` — the
  266-row feature-map with per-action WIRED / STUB / BROKEN status +
  X3 / Y1 / Z7 / AA1 patch sections at the tail.
* `H:\Github\Pharos Engine\docs\feature_map_delta_2026_07_04.md` — Y7
  delta re-audit (V/W/X features + 5 STUB→WIRED flips + drift risks).
* `H:\Github\Pharos Engine\docs\diary_softbody_bridge_2026_07_04.md` —
  AA3 investigation + shim documentation.
* `H:\Github\Pharos Engine\docs\master_review_2026_06_07.md` — the
  master review + 7-sprint refactor plan the V-batch was drawn from.
* `H:\Github\Pharos Engine\docs\consolidation_2026_06_07.md` — Nova3D
  legacy inventory + deletion blockers.
* `H:\Github\Pharos Engine\docs\user_customization_2026_06_07.md` —
  `~/.pharos_engine/ui/` override folder guide (X6 landing).
* `H:\Github\Pharos Engine\docs\sprint_5_doc_inventory.md` — this rollup
  is indexed here.

Code hubs:

* `H:\Github\Pharos Engine\python\pharos_engine\actions\` — the 20-action
  subpackage (X3 / Y1 / Z7 / AA1).
* `H:\Github\Pharos Engine\python\pharos_engine\prefabs\` — Y3 prefab
  library + AA2 API polish. Baked `.prefab.yaml` under
  `python/pharos_engine/prefabs/baked/`.
* `H:\Github\Pharos Engine\python\pharos_engine\autosave.py` — Y6
  AutosaveManager + RecoveryPrompt.
* `H:\Github\Pharos Engine\python\pharos_engine\project_registry.py` —
  V2 multi-project management.
* `H:\Github\Pharos Engine\python\pharos_engine\visual_scripting\material_nodes.py`
  — V5 WGSL material graph nodes.
* `H:\Github\Pharos Engine\python\pharos_engine\visual_scripting\codegen.py`
  — V6 Python ↔ Graph bidirectional codegen.
* `H:\Github\Pharos Engine\python\pharos_engine\ui\editor\` — the notebook
  editor panels. V/W/X/Y/Z/AA new panels: `notebook_startup_prompt.py`,
  `notebook_project_registry.py`, `notebook_snap_overlay.py`,
  `notebook_gizmo_overlay.py`, `notebook_message_log.py`,
  `notebook_prefab_menu.py`, `editor_autosave.py`,
  `diary_softbody_bridge.py`, plus AA4 `material_graph_bridge.py`.
* `H:\Github\Pharos Engine\python\pharos_engine\ui\theme\washi_tape\library.py`
  — T2 (15) + V7 (8) shaders.
* `H:\Github\Pharos Engine\python\pharos_engine\ui\hotkeys\baked\` — AA7
  baked hotkey presets.
* `H:\Github\Pharos Engine\python\pharos_engine\post_process\chain_manifest.py`
  — X5 declarative chain manifest.
* `H:\Github\Pharos Engine\python\pharos_engine\shader_lint.py` — AA6
  WGSL lint suite (53 shaders).
* `H:\Github\Pharos Engine\PharosEngineExamples\examples\hello_full_editor.py`
  — AA5 full-stack editor demo.
* `H:\Github\Pharos Engine\PharosEngineExamples\examples\hello_material_graph.py`
  — CC2 four-graph WGSL demo via V5+AA4 bridge.
* `H:\Github\Pharos Engine\PharosEngineExamples\examples\hello_toast_animation.py`
  — DD2 6-second CC5+CC6 walkthrough.
* `H:\Github\Pharos Engine\python\pharos_engine\ui\editor\baked_layouts\`
  — CC4 6 baked layout presets.
* `H:\Github\Pharos Engine\python\pharos_engine\ui\editor\layout_baker.py`
  — CC4 LayoutBaker.
* `H:\Github\Pharos Engine\python\pharos_engine\ui\editor\notebook_asset_inspector.py`
  — CC3 7-kind asset inspector.
* `H:\Github\Pharos Engine\python\pharos_engine\ui\editor\notebook_toast_manager.py`
  — CC5 toast subsystem.
* `H:\Github\Pharos Engine\python\pharos_engine\ui\editor\notebook_command_palette.py`
  — CC7 Ctrl+Shift+P fuzzy finder.
* `H:\Github\Pharos Engine\python\pharos_engine\ui\editor\notebook_telemetry_dashboard.py`
  — DD4 4-view telemetry panel.
* `H:\Github\Pharos Engine\python\pharos_engine\ui\editor\notebook_timeline_editor.py`
  — DD5 keyframe curve editor (salvage).
* `H:\Github\Pharos Engine\python\pharos_engine\actions\camera_animation_actions.py`
  — CC6 CameraAnimator + 6 easing curves.
* `H:\Github\Pharos Engine\python\pharos_engine\smoke_runner.py`
  — DD3 SmokeRunner + parallel runner (salvage).
* `H:\Github\Pharos Engine\python\pharos_engine\ui\theme\shader_batch_validator.py`
  — DD6 WGSL batch validator + Markdown/YAML report.

---

*Rollup regenerated 2026-07-05 by EE5 scrum agent (originally BB5,
extended with CC + DD landings). Sources: 76 commits between `db56df3`
(2026-06-07) and `7be6617` (2026-07-05 nightly). Baselines:
`docs/engine_feature_map_2026_07_04.md` (V1 → DD1 tail),
`docs/feature_map_delta_2026_07_04.md` (Y7),
`docs/feature_map_delta_2026_07_04_v2.md` (post-DD delta), and
`docs/diary_softbody_bridge_2026_07_04.md` (AA3). Cross-referenced
against `git log --oneline -40` + per-commit `git show --stat` for
V/W/X/Y/Z/AA/BB/CC/DD landings.*
