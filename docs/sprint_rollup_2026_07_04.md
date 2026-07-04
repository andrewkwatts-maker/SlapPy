# Sprint Rollup — 2026-07-04 (V / W / X / Y / Z / AA batches)

Consolidated retrospective of the six-batch scrum push that ran between
`db56df3` (V-batch start freeze, 2026-06-07 master review + 7-sprint
refactor plan) and `9997cdd` (AA5, hello_full_editor demo). Six batches,
approximately 42 sprint slots dispatched to parallel agents, ~55 commits
landed on master. The engine feature map moved from 233 rows at V1 freeze
to **266 rows with 248 WIRED (93.2%)** at AA1 close. All six diary themes,
three 15-shader WGSL libraries (washi tape, page linings, edge strokes),
and six baked prefabs shipped alongside a diary-shell workspace, prefab
library, autosave subsystem, and hotkey remap layer. Live viewport polish
(TAA / bloom / gizmo overlay), five hardening rounds, seven new hello_*
demos, and a 20-action `slappyengine.actions.*` subpackage round out the
push; downstream game compat (Ochema Circuit / Bullet Strata) was
deliberately not touched.

---

## Batch-by-batch table

| Batch | SHA range | Agent slots | Sprints landed | Notable landings |
|-------|-----------|-------------|----------------|------------------|
| **V** | `a714b3a`..`a714b3a` (single salvage commit rolling up 7 disjoint scopes) plus `8205368`..`1467f91` for the T/U theming pre-work that V1 audited | ~7 | V1 feature-map audit, V2 project registry, V3 inspector reflection, V4 snap overlay, V5 material nodes, V6 bidirectional codegen, V7 animated washi tape | Engine feature map v1 (233 rows). `slappyengine.project_registry` + startup-prompt panel. 18+ WGSL material graph nodes. Python↔Graph codegen. 8 animated washi tape shaders (heart pulse / sparkle shimmer / rainbow flow / marching dots / wave shift / dashed scroll / stars twinkle / music notes flow). Budget widened to 1000B. |
| **W** | `607bffe`..`f59a6f9` plus `b019bdb` router patch | ~6 | W1 hello_ragdoll fix, W2 four-panel hardening, W3 TAA polish, W4 bloom polish, W6 hello_integrated_notebook | TAA — YCoCg variance clip + Halton(2,3)-8 + velocity blend + rejection heuristics. Bloom — Karis 13-tap downsample + tent upsample + firefly filter. Four-panel silent-acceptance hardening (material / theming / spawn / diary) with 31 fixed bug-classes. `editor.toggle_panel_tag_painter` action registered. |
| **X** | `d339995`..`194a0c9` | ~7 | X2 hello_rope fix, X3 STUB triage round 1, X4 content browser project view, X5 chain manifest, X6 live reload watcher, X7 6 widget primitives | `slappyengine.actions.*` subpackage bootstrap (5 actions). Notebook content browser `set_project` with 6 asset-kind groups + fuzzy search + right-click ctx menu. Declarative post-process chain manifest via `apply_manifest`. `UserOverrideLoader.watch_dir` / `autoreload` with watchdog soft-import. 6 new widgets: GlitterProgressBar, RibbonTab, PaperClipAttachment, WashiTapeDivider, SketchButton, InkStampBadge. |
| **Y** | `48eb8ee`..`61d6b83` | ~7 | Y1 STUB triage round 2, Y2 hello_joint fix, Y3 prefab library, Y4 gizmo overlay, Y5 message log, Y6 autosave subsystem, Y7 re-audit | Feature-map delta doc (Y7). `slappyengine.prefabs` — Prefab dataclass + PrefabLibrary registry + 7 body kinds + `.prefab.yaml` round-trip. `slappyengine.autosave` — AutosaveManager threading.Timer + RecoveryPrompt / RecoveryOffer. NotebookGizmoOverlay hand-drawn move/rotate/scale handles. NotebookMessageLog + `_DiaryLogHandler` telemetry bridge. 5 more actions wired (`tool.select_all` / `deselect_all` / `editor.copy_selection` / `paste_selection` / `theme.cycle`). |
| **Z** | `fb073f4`..`39cad69` | ~7 | Z1 message-log headless fix, Z2 prefab spawn menu, Z3 baked chain presets, Z4 hello_prefab + hello_autosave, Z5 docs polish, Z6 editor autosave integration, Z7 STUB triage round 3 | NotebookPrefabMenu 96×96 card grid. 6 baked post-process chain presets (`default` / `crisp` / `dreamy` / `neon` / `retro_film` / `debug`) via ChainBaker. EditorAutosaveIntegration wiring Y6 into shell lifecycle. Fix for `NotebookMessageLog` real-DPG headless segfault. 5 more actions wired (`tool.snap_to_grid` / `view.zoom_in` / `zoom_out` / `zoom_reset` / `theme.export_current`). README + quickstart + onboarding polish. |
| **AA** | `f6bb3f0`..`9997cdd` | ~7 | AA1 STUB triage round 4, AA2 prefab/autosave polish, AA3 diary softbody bridge, AA4 material graph bridge, AA5 hello_full_editor, AA6 WGSL shader lint, AA7 hotkey remap | `slappyengine.ui.editor.diary_softbody_bridge` shim + 8-test suite (rows 80/223 preview-flip). MaterialGraphBridge round-trip between V5 material nodes and NotebookMaterialEditor. hello_full_editor end-to-end scripted demo (6 pages + prefabs + material + autosave + 6 themes + 37 events). `slappyengine.shader_lint` with 53-shader coverage. `slappyengine.ui.hotkey_remap` + 3 baked hotkey presets. 5 more actions wired (`edit.cut_selection` / `delete_selection` / `view.center_on_selection` / `frame_all` / `tool.pan`). PrefabLibrary API polish (spawn / entity_count / bake_and_load) + AutosaveManager.read_snapshot. |

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
  grid backed by `slappyengine.project_registry`.
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
  `slappyengine.telemetry`.
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
* **shader_lint** (AA6) — `slappyengine.shader_lint` covers all 53
  shaders across the three libraries. Checks: 1000-byte budget,
  `@fragment` + `fs_main` + `@location(0)` presence, uniform contract
  adherence against struct-field discovery, deprecated `[[block]]` /
  `[[binding]]` syntax warnings, ASCII hygiene, soft wgpu
  `create_shader_module` round-trip.

### Content

* **slappyengine.projects** + **project_registry** (pre-V + V2) — full
  Nova3D-style multi-project management with persistent
  `~/.slappyengine/projects.yaml` recents.
* **slappyengine.prefabs** (Y3) — Prefab dataclass (name, category,
  body_spec dict, joint_specs, child_prefabs, metadata); YAML round-trip;
  `spawn(world, position, rotation)` materialises into a
  `slappyengine.dynamics.World`. Seven body kinds: point / circle / box /
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
  `SlapPyEngineTests/goldens/visual_scripting/` (arithmetic, assignment
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
| `hello_ragdoll` (fix) | W1 | `SlapPyEngineExamples/examples/hello_ragdoll.py` | Damping regression + tests. |
| `hello_integrated_notebook` | W6 | `SlapPyEngineExamples/examples/hello_integrated_notebook.py` | DiaryShell + panels end-to-end. |
| `hello_rope` (fix) | X2 | `SlapPyEngineExamples/examples/hello_rope.py` | Damping regression + tests. |
| `hello_joint` (fix) | Y2 | `SlapPyEngineExamples/examples/hello_joint.py` | Damping fix + iters × damping metric. |
| `hello_prefab` | Z4 | `SlapPyEngineExamples/examples/hello_prefab.py` | 4 baked prefabs (crate + ball + windmill + chain), 120 frames at 1/60 s, PIL rasterise. 12 entities. |
| `hello_autosave` | Z4 | `SlapPyEngineExamples/examples/hello_autosave.py` | ~6 s of editor activity, AutosaveManager every 1 s + crash + RecoveryPrompt restore. |
| `hello_full_editor` | AA5 | `SlapPyEngineExamples/examples/hello_full_editor.py` | Full scripted session: 6 pages, 5 outliner selects, 3-node NodeGraph (math.constant → math.mul → render.material_out), MaterialGraphBridge, `dreamy` chain preset, `sin(x)*a + b` math eval, autosave × 3 force_saves, 6 themes cycled. 37 events → `hello_full_editor_trace.yaml`. |

### Actions subpackage

`slappyengine.actions.*` bootstrapped in X3 and grew across five sprints
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
* **AA7 slappyengine.ui.hotkey_remap** — HotkeyBinding dataclass
  (canonical combo, action_id, enabled, source) + HotkeyMap with
  add/remove/resolve/list_all/merge/to_yaml/from_yaml/validate.
  `load_user_hotkeys` reads `~/.slappyengine/ui/hotkeys/*.yaml`;
  `apply_remap` does user-wins merge with disabled bindings stripping
  defaults; `bake_defaults` is idempotent first-launch copy from
  wheel-baked presets. Ships 3 baked presets at
  `python/slappyengine/ui/hotkeys/baked/`: `default.yaml` (mirror of
  `NotebookHotkeys.BINDINGS`) plus two style variants.
* **UserThemeStore** — user-side theme override + bake pipeline.
  `save_as_new` wired through W2's `NotebookThemingEditor.save_as_new`.
* **User overrides directory** — `~/.slappyengine/ui/` panel / hotkey /
  spawn card / shader override folders (documented in
  `docs/user_customization_2026_06_07.md`).

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

Aggregate order-of-magnitude: **~4000+ tests running** across
`SlapPyEngineTests/tests/` at AA5 close. No batch reported a red
suite. The five Rounds of STUB triage (X3 / Y1 / Z7 / AA1 plus the
pre-V post-V1 tag_painter registration) collectively land 20 new
router-action wirings + ~124 regression tests.

---

## What's next

Concrete follow-ups the six batches deferred:

1. **Uncommitted physics WIP dirs need tracking.** `git status` at
   AA-close shows uncommitted trees for `python/slappyengine/softbody/`,
   `python/slappyengine/fluid/`, `python/slappyengine/physics/`,
   `python/slappyengine/physics2/`, `src/fluid_shader.rs`,
   `src/pbf_solver.rs`, `src/raster.rs`, `src/softbody_solver.rs`, plus
   ~40 physics module files (`body.py`, `broadphase.py`, `ccd.py`,
   `cell.py`, `constraints.py`, `hull.py`, `particles.py`,
   `pressure_multigrid.py`, `world.py`, and more). AA3's bridge shim was
   built specifically so these can land without breaking the diary
   runner; a follow-up sprint should stage + review + commit these.
2. **Diary softbody import STUB (rows 80 / 223) still BROKEN.** AA3
   shipped `diary_softbody_bridge.py` + 8 tests but did NOT rewire the
   two callsites at `notebook_diary_page.py:539` (stage construction)
   and `notebook_diary_page.py:610` (per-tick step) because that file is
   pinned read-only by the AA-batch sprint plan. Un-pin the diary panel
   and swap in `bridge.step_stage(stage)` to flip both rows to WIRED on
   the next feature-map delta.
3. **Remaining STUBs after AA1 (15 total).**
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
   `~/.slappyengine/postprocess_chains/` instead of the hardcoded
   preset registry.

---

## Key file paths

Docs:

* `H:\Github\SlapPyEngine\docs\engine_feature_map_2026_07_04.md` — the
  266-row feature-map with per-action WIRED / STUB / BROKEN status +
  X3 / Y1 / Z7 / AA1 patch sections at the tail.
* `H:\Github\SlapPyEngine\docs\feature_map_delta_2026_07_04.md` — Y7
  delta re-audit (V/W/X features + 5 STUB→WIRED flips + drift risks).
* `H:\Github\SlapPyEngine\docs\diary_softbody_bridge_2026_07_04.md` —
  AA3 investigation + shim documentation.
* `H:\Github\SlapPyEngine\docs\master_review_2026_06_07.md` — the
  master review + 7-sprint refactor plan the V-batch was drawn from.
* `H:\Github\SlapPyEngine\docs\consolidation_2026_06_07.md` — Nova3D
  legacy inventory + deletion blockers.
* `H:\Github\SlapPyEngine\docs\user_customization_2026_06_07.md` —
  `~/.slappyengine/ui/` override folder guide (X6 landing).
* `H:\Github\SlapPyEngine\docs\sprint_5_doc_inventory.md` — this rollup
  is indexed here.

Code hubs:

* `H:\Github\SlapPyEngine\python\slappyengine\actions\` — the 20-action
  subpackage (X3 / Y1 / Z7 / AA1).
* `H:\Github\SlapPyEngine\python\slappyengine\prefabs\` — Y3 prefab
  library + AA2 API polish. Baked `.prefab.yaml` under
  `python/slappyengine/prefabs/baked/`.
* `H:\Github\SlapPyEngine\python\slappyengine\autosave.py` — Y6
  AutosaveManager + RecoveryPrompt.
* `H:\Github\SlapPyEngine\python\slappyengine\project_registry.py` —
  V2 multi-project management.
* `H:\Github\SlapPyEngine\python\slappyengine\visual_scripting\material_nodes.py`
  — V5 WGSL material graph nodes.
* `H:\Github\SlapPyEngine\python\slappyengine\visual_scripting\codegen.py`
  — V6 Python ↔ Graph bidirectional codegen.
* `H:\Github\SlapPyEngine\python\slappyengine\ui\editor\` — the notebook
  editor panels. V/W/X/Y/Z/AA new panels: `notebook_startup_prompt.py`,
  `notebook_project_registry.py`, `notebook_snap_overlay.py`,
  `notebook_gizmo_overlay.py`, `notebook_message_log.py`,
  `notebook_prefab_menu.py`, `editor_autosave.py`,
  `diary_softbody_bridge.py`, plus AA4 `material_graph_bridge.py`.
* `H:\Github\SlapPyEngine\python\slappyengine\ui\theme\washi_tape\library.py`
  — T2 (15) + V7 (8) shaders.
* `H:\Github\SlapPyEngine\python\slappyengine\ui\hotkeys\baked\` — AA7
  baked hotkey presets.
* `H:\Github\SlapPyEngine\python\slappyengine\post_process\chain_manifest.py`
  — X5 declarative chain manifest.
* `H:\Github\SlapPyEngine\python\slappyengine\shader_lint.py` — AA6
  WGSL lint suite (53 shaders).
* `H:\Github\SlapPyEngine\SlapPyEngineExamples\examples\hello_full_editor.py`
  — AA5 full-stack editor demo.

---

*Rollup generated 2026-07-05 by BB5 scrum agent. Sources: 55 commits
between `db56df3` (2026-06-07) and `9997cdd` (2026-07-05). Baselines:
`docs/engine_feature_map_2026_07_04.md` (V1 → AA1 tail),
`docs/feature_map_delta_2026_07_04.md` (Y7), and
`docs/diary_softbody_bridge_2026_07_04.md` (AA3). Cross-referenced
against `git log --oneline -60` + per-commit `git show --stat` for
V/W/X/Y/Z/AA landings.*
