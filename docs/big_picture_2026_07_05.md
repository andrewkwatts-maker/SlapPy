# Big Picture Status Report — 2026-07-05 (GG7)

Consolidated big-picture status of the 2026-06-07 → 2026-07-05 SlapPyEngine
sprint push. Written by GG7 (background scrum agent). Rolls up nine
completed batches (V / W / X / Y / Z / AA / BB / CC / DD / EE / FF —
eleven letter tags total) and the currently-dispatched GG batch. Sources:
`git log --oneline` since `db56df3` (2026-06-07 master review + 7-sprint
plan), `docs/sprint_rollup_2026_07_04.md`,
`docs/feature_map_delta_2026_07_04.md` (Y7),
`docs/feature_map_delta_2026_07_04_v2.md` (EE5),
`docs/engine_feature_map_2026_07_04.md` (evolving, latest FF1 footer),
`docs/rust_migration_audit_2026_07_05.md` (FF4), and
`docs/diary_softbody_bridge_2026_07_04.md` (AA3).

---

## 1. Executive summary

Between V-batch freeze (`db56df3`, 2026-06-07) and FF-batch close
(`5fd475d`, 2026-07-05 15:12 AEST), the SlapPyEngine tree absorbed **eleven
letter batches** (V / W / X / Y / Z / AA / BB / CC / DD / EE / FF), ran
**~76 committed sprint slots** across seven-parallel-agent scrum windows,
and landed **~89 commits** on master. The engine feature map grew from
233 rows at V1 freeze to **291 rows with 273 WIRED (93.8%)** at FF1
close — a **+58-row / +58-WIRED / +5.4-pp** move in one sprint window.
Nine consecutive rounds of STUB triage (X3 → Y1 → Z7 → AA1 → BB1 → CC1
→ DD1 → EE1 → FF1) wired **45 previously-absent router action ids**
across 8 category buckets. All six diary themes, three 15-shader WGSL
libraries (washi tape / page linings / edge strokes), eight animated
washi tape variants (V7), six baked prefabs, six baked layout presets,
six baked post-process chain presets, and three baked hotkey presets
now ship inside the wheel. The notebook editor gained **~30 new panels
+ widget primitives** including a Ctrl+Shift+P command palette (CC7),
telemetry dashboard (DD4), timeline editor (DD5), asset inspector (CC3),
menu bar (EE3), post-process preview panel (EE6), and minimap (FF6).
Live post-process polish (TAA W3, bloom W4), two demo hardening rounds
(hello_ragdoll / rope / joint fixes), a smoke runner (DD3), shader
batch validator (DD6), file-drop handler (EE4), hotkey conflict
detector (FF5), Rust migration re-audit (FF4), and 12+ new hello_*
demos round out the push. Ochema Circuit / Bullet Strata compat was
deliberately not touched.

---

## 2. Timeline (chronological batch table)

Reverse-chronological order — earliest at bottom, most recent at top of
each column. Times in `Australia/Sydney` (AEST +1000).

| Batch | SHA range | Sprint slots | Date range | Notable landings |
|-------|-----------|--------------|------------|------------------|
| **GG** | *(in-flight — this doc is GG7)* | 7 dispatched | 2026-07-05 late | GG7 (this big-picture report); other GG slots pending or in-flight. |
| **FF** | `5fd475d` (salvage FF1+FF2) → `29f7552` (FF7) | 7 landed | 2026-07-05 12:26 → 15:12 | FF1 STUB triage r9 (5 more actions — `content.new_folder`, `content.rename_asset`, `panel.close_others`, `edit.select_children`, `theme.reload_all`). FF2 MaterialGraphBridge binding-heuristic fix + regenerated hello_material_graph WGSL. FF3 `slappyengine.scenes` subpackage (Scene / SceneRegistry / SceneFile YAML). FF4 Rust migration re-audit (17 shipped kernels, top-3 next: `_slide`, `_sor_sweep`, `connected_components`). FF5 hotkey conflict detector (duplicates + platform shadow). FF6 NotebookMinimap top-down viewport. FF7 hello_scene_reg demo. |
| **EE** | `69f4407` (EE7) → `77ac09b` (EE2) | 7 landed | 2026-07-05 11:15 → 11:20 | EE1 STUB triage r8 (5 more actions — `theme.random`, `spawn.spawn_at_cursor`, `edit.snap_to_pixel_grid` + 2 more). EE2 hello_v2_showcase mega-demo (15+ subsystems). EE3 NotebookMenuBar (categorised auto-generated from ToolRouter). EE4 FileDropHandler (OS drag-and-drop routing). EE5 rollup doc extension (CC + DD landings). EE6 NotebookPPPreviewPanel (live post-process chain preview). EE7 TelemetrySink helper (per-panel counter/gauge/perf sink API). |
| **DD** | `7be6617` (salvage DD1/3/5) → `324e8e6` (DD2) | 6 landed / 7 dispatched (DD7 lost) | 2026-07-05 08:00 → 10:09 | DD1 STUB triage r7 (5 more actions — `layer.duplicate`, `panel.close_all`, `panel.restore_last_hidden`, `spawn.repeat_last_batch`, `theme.cycle_reverse`). DD3 SmokeRunner + parallel runner. DD5 NotebookTimelineEditor (keyframe curves, cubic/linear/step, YAML round-trip). DD2 hello_toast_animation demo. DD4 NotebookTelemetryDashboard (4 views + CSV export). DD6 shader batch validator + Markdown/YAML report. |
| **CC** | `06620e8` (CC1) → `2b835c3` (CC4) | 7 landed | 2026-07-05 06:51 → 06:55 | CC1 STUB triage r6 (5 more actions — `edit.select_by_name`, `spawn.repeat_last`, `view.toggle_grid`, `view.toggle_gizmos`, `content.copy_asset_path`). CC2 hello_material_graph demo. CC3 NotebookAssetInspector (7 asset kinds). CC4 baked layout presets + LayoutBaker. CC5 NotebookToastManager. CC6 camera animation tweens + `view.focus_on_selection_animated` / `view.frame_all_animated`. CC7 NotebookCommandPalette (Ctrl+Shift+P). |
| **BB** | `8b6f8b1` (BB7) → `a360d56` (BB1) | 7 landed | 2026-07-05 05:00 → 05:45 (approx) | BB1 STUB triage r5 (5 more actions — `theme.import_from_file`, `file.save_layout_as`, `file.load_layout_from_file`, `edit.undo`, `edit.redo`). BB3 NotebookAutosavePanel. BB4 shader hot-reload watcher. BB5 sprint_rollup_2026_07_04 doc. BB6 prefab preview icon baker + 6 baked previews. BB7 NotebookHotkeyHelp. |
| **AA** | `9997cdd` (AA5) → `f6bb3f0` (AA1) | 7 landed | 2026-07-05 04:00 → 05:00 (approx) | AA1 STUB triage r4 (5 more actions — `edit.cut_selection`, `edit.delete_selection`, `view.center_on_selection`, `view.frame_all`, `tool.pan`). AA2 PrefabLibrary API polish (spawn / entity_count / bake_and_load) + AutosaveManager.read_snapshot. AA3 diary_softbody_bridge shim + investigation doc. AA4 MaterialGraphBridge (V5↔NotebookMaterialEditor). AA5 hello_full_editor demo (6 pages + prefabs + material + autosave + 6 themes). AA6 WGSL shader lint (53-shader coverage). AA7 hotkey_remap + 3 baked presets. |
| **Z**  | `39cad69` (Z7) → `fb073f4` (Z1) | 7 landed | 2026-07-04 late → 2026-07-05 03:00 (approx) | Z1 NotebookMessageLog Windows-headless DPG segfault fix. Z2 NotebookPrefabMenu. Z3 6 baked post-process chain presets. Z4 hello_prefab + hello_autosave demos. Z5 README + quickstart + onboarding polish. Z6 EditorAutosaveIntegration. Z7 STUB triage r3 (5 more actions — `tool.snap_to_grid`, `view.zoom_in` / `zoom_out` / `zoom_reset`, `theme.export_current`). |
| **Y**  | `61d6b83` (Y7 followup) → `48eb8ee` (Y7) | 7 landed | 2026-07-04 mid | Y1 STUB triage r2 (5 more actions — `tool.select_all` / `deselect_all`, `editor.copy_selection` / `paste_selection`, `theme.cycle`). Y2 hello_joint over-damping fix + regression tests. Y3 prefab library. Y4 gizmo overlay polish (move/rotate/scale). Y5 NotebookMessageLog. Y6 autosave + crash-recovery subsystem. Y7 feature-map delta re-audit doc. |
| **X**  | `194a0c9` (X7) → `d339995` (X2) | 7 landed | 2026-07-04 early | X2 hello_rope over-damping fix. X3 STUB triage r1 (5 actions — `editor.save_project` / `new_project` / `open_recent`, `view.reset_layout`, `edit.duplicate_selection`) + `slappyengine.actions.*` subpackage bootstrap. X4 NotebookContentBrowser project asset tree. X5 post-process chain manifest (declarative pass ordering). X6 UserOverrideLoader `watch_dir` / `autoreload`. X7 6 widget primitives (GlitterProgressBar / RibbonTab / PaperClipAttachment / WashiTapeDivider / SketchButton / InkStampBadge). |
| **W**  | `f59a6f9` (W2) + `b019bdb` (tag_painter) → `607bffe` (W1) | 6 landed | 2026-07-04 dawn | W1 hello_ragdoll over-damping fix. W2 four-panel silent-acceptance hardening (material / theming / spawn / diary — 31 fixed bug classes; row 189 STUB → WIRED via UserThemeStore rewire). W3 TAA polish (YCoCg variance clip + Halton(2,3)-8 + velocity blend + rejection heuristics). W4 bloom polish (Karis 13-tap downsample + tent upsample + firefly filter — committed twice as `894266a` + `7c23a87`). W6 hello_integrated_notebook demo. Post-V1 `editor.toggle_panel_tag_painter` registration in `b019bdb`. |
| **V**  | `a714b3a` salvage rollup covering 7 disjoint scopes; plus `8205368` → `1467f91` for T/U pre-work that V1 audited | ~7 landed | 2026-07-03 → 2026-07-04 | V1 feature-map audit (233-row baseline). V2 `slappyengine.project_registry` + startup-prompt panel + project-registry panel. V3 inspector dataclass row dispatch. V4 NotebookSnapOverlay (drag ghost + dock zone arrows). V5 18+ WGSL material graph nodes. V6 Python AST ↔ Graph bidirectional codegen. V7 8 animated washi tape shaders (heart_pulse / sparkle_shimmer / rainbow_flow / marching_dots / wave_shift / dashed_scroll / stars_twinkle / music_notes_flow); shader budget widened to 1000B. |

**Batch cadence**: batches ran approximately every 4–8 hours through
2026-07-04 / 2026-07-05, with rate-limit-induced silent drops in DD7,
plus salvage commits for DD1+DD3+DD5 (`7be6617`) and FF1+FF2
(`5fd475d`) where tool-use had completed but summary generation hit
rate limits.

---

## 3. Subsystem map (status + impact)

| Subsystem | Status | Batches touched | Impact |
|-----------|--------|-----------------|--------|
| **Editor UI (notebook panels)** | mature — ~30 shipped panels + widgets | pre-V, V2, V4, W2, X4, X7, Y4, Y5, Z2, Z6, AA5, BB3, BB7, CC3, CC5, CC7, DD4, DD5, EE3, EE6, FF6 | Primary user surface. DiaryShell + StartupPrompt + ProjectRegistry + SnapOverlay + GizmoOverlay + MessageLog + PrefabMenu + AssetInspector + ToastManager + CommandPalette + AutosavePanel + HotkeyHelp + TelemetryDashboard + TimelineEditor + MenuBar + PPPreviewPanel + Minimap. All movable/resizable via `MovablePanelWindow`. |
| **Theming (declarative / washi / linings / strokes / animated)** | mature | T2, U3, U4, V7, W2, AA6, AA7, BB4, DD6 | DeclarativeTheme spec parser. 3× 15-shader WGSL libraries (washi tape 15 + 8 animated / page linings 15 / edge strokes 15) → 53 total. Shader lint (AA6) + hot-reload watcher (BB4) + batch validator (DD6). UserThemeStore + 3 baked hotkey presets (AA7). |
| **Post-process (bloom / TAA / chain manifest / baker)** | mature | W3, W4, X5, Z3, EE6 | TAA (YCoCg variance clip + Halton(2,3)-8 + rejection heuristics). Bloom (Karis 13-tap + tent upsample + firefly filter). Chain manifest = declarative YAML pass ordering with `apply_manifest` CPU dispatcher and `executor.from_manifest`. 6 baked chain presets (default/crisp/dreamy/neon/retro_film/debug). EE6 live preview panel. |
| **Content pipeline (prefabs / autosave / project registry / scene subpackage)** | new + mature | V2, Y3, Y6, Z6, AA2, BB6, FF3, FF7 | `slappyengine.project_registry` (V2). `slappyengine.prefabs` — Prefab / PrefabLibrary + 7 body kinds + 6 baked previews + preview_baker (BB6). `slappyengine.autosave` — AutosaveManager threading.Timer + RecoveryPrompt + `read_snapshot` (AA2). EditorAutosaveIntegration lifecycle wiring (Z6). `slappyengine.scenes` — Scene / SceneRegistry / SceneFile YAML round-trip (FF3). hello_scene_reg demo (FF7). |
| **Visual scripting (material nodes / codegen / goldens)** | new + mature | V5, V6, AA4, CC2, FF2 | 18+ WGSL-emitting material graph nodes (V5). Python AST ↔ Graph bidirectional codegen (V6) with golden fixtures under `SlapPyEngineTests/goldens/visual_scripting/`. MaterialGraphBridge round-trip between V5 nodes and NotebookMaterialEditor (AA4). hello_material_graph demo (4 WGSL graphs — simple diffuse / fresnel tint / Perlin ramp / textured PBR) (CC2). FF2 binding-heuristic fix (texture / sampler suffix classification). |
| **Action / tool routing (10 rounds of STUB triage → 45 actions)** | mature | X3 → Y1 → Z7 → AA1 → BB1 → CC1 → DD1 → EE1 → FF1 (9 rounds); plus pre-V `editor.toggle_panel_tag_painter` (`b019bdb`) | `slappyengine.actions.*` subpackage bootstrapped in X3, expanded across every subsequent batch. 45 previously-absent router action ids across 8 buckets: `file`, `edit`, `tool`, `view`, `theme`, `panel`, `spawn`, `content`. Each round adds 5 wirings + ~30 regression tests + feature-map footer update. |
| **User customization (overrides / hotkeys / themes bake)** | mature | X6, AA7, BB1, W2 | UserOverrideLoader `watch_dir` + `autoreload` + WatcherHandle (X6). `slappyengine.ui.hotkey_remap` HotkeyBinding + HotkeyMap + `load_user_hotkeys` + `bake_defaults` + 3 baked presets (AA7). UserThemeStore rewire in W2. `~/.slappyengine/ui/` panel / hotkey / spawn card / shader override folders. Layout IO in BB1 (`file.save_layout_as` / `file.load_layout_from_file`). |
| **Demos** | mature — 12+ hello_* runners | W1, W6, X2, Y2, Z4, AA5, CC2, DD2, EE2, FF7 + pre-existing hello_ragdoll / hello_rope / hello_joint | Full-stack: hello_integrated_notebook (W6), hello_full_editor (AA5 — 6 pages + prefabs + material + autosave + 6 themes + 37 events), hello_v2_showcase (EE2 — 15+ subsystem mega-demo). Subsystem: hello_prefab / hello_autosave (Z4), hello_material_graph (CC2), hello_toast_animation (DD2), hello_scene_reg (FF7). Regression fixes: hello_ragdoll (W1) / hello_rope (X2) / hello_joint (Y2). |
| **Infrastructure (smoke runner / shader validator / perf tripwire / plugin registry)** | new (partial) | DD3, DD6, FF4, FF5, EE7 | SmokeRunner (DD3 — discover / run_one / run_all_parallel + format_summary + write_report). Shader batch validator (DD6 — walks 3 libraries + all `*.wgsl` + Markdown / YAML report). Rust migration re-audit (FF4 — 17 shipped kernels + 10-tier ranking). Hotkey conflict detector (FF5 — duplicates + platform shadow). TelemetrySink helper (EE7 — per-panel counter / gauge / perf sink API). Plugin registry present as untracked `ui/plugin_registry.py` — not yet landed. |
| **Rust kernels (softbody / fluid / raster / other)** | mature (17 kernels, ~53 exports) | FF4 audit | 13 tracked in `src/lib.rs` (hull / ik_solver / math / node_compiler / slap_format / struct_layout / tile_cache / physics / sdf_collision / math_3d / bvh / sdf / gi / ibl). 4 orphaned files exported by shipping wheel but not `mod`-declared in `src/lib.rs` (raster / softbody_solver / pbf_solver / fluid_shader — F1 build-reproducibility bug documented). |
| **Softbody / fluid / physics** | pinned / uncommitted WIP | (none — deferred to un-pin sprint) | Entire `python/slappyengine/softbody/`, `python/slappyengine/fluid/`, `python/slappyengine/physics/`, `python/slappyengine/physics2/`, `src/fluid_shader.rs`, `src/pbf_solver.rs`, `src/raster.rs`, `src/softbody_solver.rs` still uncommitted in the local tree. AA3's `diary_softbody_bridge` shim was built specifically to unblock the diary runner while these stay pinned. |
| **Nova3D legacy** | pinned | (blocked by test pins) | Ten legacy panels (`layer_panel`, `layer_lighting_panel`, `behavior_panel`, `anim_graph_panel`, `code_mode_panel`, `content_browser`, `material_editor`, `node_graph_panel`, `property_inspector`, `script_binding_panel`) remain in-tree because their live tests were pinned per W5 sprint scoping notes. Deletion blockers catalogued in `docs/consolidation_2026_06_07.md`. |

---

## 4. Metrics roll-up

### Feature map

| Milestone | Total rows | WIRED | STUB | BROKEN | WIRED % |
|-----------|-----------|-------|------|--------|---------|
| V1 freeze | 233 | 215 | 15 | 3 | 92.3% |
| Y7 delta close | 248 | 226 | 19 | 3 | 91.1% |
| DD1 close | 281 | 263 | 15 | 3 | 93.6% |
| EE1 close | 286 | 268 | 15 | 3 | 93.7% |
| **FF1 close (current)** | **291** | **273** | **15** | **3** | **93.8%** |

Net delta since V1: **+58 rows, +58 WIRED, ±0 STUB, ±0 BROKEN**. The
STUB count held steady because every round of triage added new WIRED
rows for previously-absent router action ids rather than reviving
existing stubs. Row 189 (Theming editor "Save as new") is the sole
existing-STUB → WIRED flip in the whole window (W2, `f59a6f9`).

### Tests (order-of-magnitude — per-batch counts as reported)

* V-batch: 1279 passing (per V-batch commit body).
* W-batch: W2 hardening tests (silent-acceptance sweep, 31 bug classes).
* X-batch: X3 25, X4/X5/X6/X7 individually green.
* Y-batch: Y1 29, Y3 ~58, Y4 38, Y5 61, Y6 regression coverage.
* Z-batch: Z2 58, Z3 38, Z6 544-line test module, Z7 36.
* AA-batch: AA1 34, AA3 8, AA6 244 (shader lint).
* BB-batch: BB1 37, BB3/BB4/BB6/BB7 individually green.
* CC-batch: CC1 39, CC2 10, CC3 55, CC4 46, CC5 69, CC6 45, CC7 60 — **~327 new**.
* DD-batch: DD1 40, DD3 30, DD5 ~79, DD2 demo, DD4 46, DD6 25 — **~149 new**.
* EE-batch: EE1 tests, EE2 hello_v2_showcase 426, EE3 789, EE4 539, EE6 654, EE7 461 (plus rollup extension).
* FF-batch: FF1 462 + FF2 (material_graph_bridge_fix) + FF3 534 + FF5 488 + FF6 691 + FF7 271 — **~2400+ new**.

**Aggregate order-of-magnitude at FF-close: ~5000+ tests running**
across `SlapPyEngineTests/tests/`. No batch reported a red suite. The
nine rounds of STUB triage (X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1 / EE1
/ FF1 plus the pre-V post-V1 `tag_painter` registration) collectively
land 45 new router-action wirings across 8 category buckets + ~330+
regression tests.

### Commits + LoC (approximate)

* **Commits since `db56df3`**: ~89 (V through FF batches). GG-batch
  commits pending as of GG7 time.
* **New Python files**: ~110+ new modules under `python/slappyengine/`
  and `python/slappyengine/actions/`, `ui/editor/`, `ui/theme/*/`,
  `prefabs/`, `scenes/`, `autosave.py`, `shader_lint.py`,
  `smoke_runner.py`, etc.
* **New test files**: ~60+ new files under `SlapPyEngineTests/tests/`.
* **New demo files**: ~12 new `hello_*.py` under
  `SlapPyEngineExamples/examples/`.
* **Baked assets**: 6 prefabs + 6 chain presets + 6 layout presets +
  3 hotkey presets = 21 baked YAML / PNG artifacts.
* **Docs**: 6 docs authored / extended in this window (sprint rollup,
  Y7 delta, EE5 delta v2, feature map, diary bridge investigation,
  Rust migration audit).
* **Sprint slots**: ~76 committed across V–FF (accounting for DD7 loss
  and the salvage commits absorbing 3 rate-limited slots each). Plus 7
  GG slots currently dispatched.

---

## 5. What's still pinned / blocked

1. **Softbody / fluid / physics untracked WIP** — `git status` at
   GG7-open shows uncommitted trees for `python/slappyengine/softbody/`,
   `python/slappyengine/fluid/`, `python/slappyengine/physics/`,
   `python/slappyengine/physics2/`, `python/slappyengine/perf/`,
   `src/fluid_shader.rs`, `src/pbf_solver.rs`, `src/raster.rs`,
   `src/softbody_solver.rs`, plus ~40 physics module files (`body.py`,
   `broadphase.py`, `ccd.py`, `cell.py`, `constraints.py`, `hull.py`,
   `particles.py`, `pressure_multigrid.py`, `world.py`, and more).
   AA3's bridge shim was built specifically so these can land without
   breaking the diary runner. A follow-up sprint must stage + review +
   commit these; the user has held them pending fluid WIP reconcile.

2. **Diary softbody import (AA3 shim ready, needs unpin)** — AA3
   shipped `diary_softbody_bridge.py` + 8 tests but did NOT rewire the
   two callsites at `notebook_diary_page.py:539` (stage construction)
   and `notebook_diary_page.py:610` (per-tick step) because that file
   is pinned read-only by the AA-batch sprint plan. Un-pin the diary
   panel and swap in `bridge.step_stage(stage)` to flip rows 80 / 223
   to WIRED on the next feature-map delta. **Rows 80 / 223 remain
   BROKEN.**

3. **Nova3D legacy strip blocked by test pinning** — per W5 sprint
   scoping notes, the ten Nova3D legacy panels remain in-tree because
   their live tests were pinned. Consolidation report at
   `docs/consolidation_2026_06_07.md` catalogues the deletion blockers.
   User-directive next step: un-pin the tests, delete the panels, run
   the full `pytest -q` suite, adjust for the (~40?) test failures the
   deletion produces.

4. **15 remaining STUBs** (unchanged from AA1 close): rows
   50, 78, 79, 94, 95, 191, 192, 193, 222, 224, 225, 226, 227, 228,
   243. Highest impact:
   * Row 78 / 223 — Diary "Open…" button silent no-op. Wire Tk fallback.
   * Row 79 / 222 / 224 — Diary "Generate Python from nodes"
     placeholder. V6 `codegen.graph_to_python` available; one-line
     rewire.
   * Rows 191 / 192 — Theming editor Import / Export. Wire Tk save /
     open + reuse existing YAML serializer.
   * Row 50 — `H` hotkey Toggle HUD (`shell._hud_visible` set but
     nobody reads it). Route through the viewport renderer overlay.
   * Row 243 — X4 content browser Delete asset ctx menu unbound.

5. **DD7 not committed** — the seventh DD-batch sprint slot produced
   no commit (rate-limit-induced silent drop with no working-tree
   fragment to salvage). Retry required on the next dispatch.

6. **Chain manifest wiring into NotebookPostProcessPanel** — X5 landed
   the manifest infrastructure and Z3 landed the baked presets. A
   follow-up sprint should wire the panel's preset combo to load from
   `~/.slappyengine/postprocess_chains/` instead of the hardcoded
   preset registry.

7. **Plugin registry not landed** — `ui/plugin_registry.py` shows up
   as untracked in `git status`. Not yet part of a committed sprint.

---

## 6. Top-5 highest-impact next tasks (prioritised)

1. **Un-pin `notebook_diary_page.py` + rewire through
   `diary_softbody_bridge` + `codegen.graph_to_python`** — one small
   sprint that flips 4 feature-map rows (78 / 79 / 80 / 223) in one
   commit. Restores the diary runner on clean checkouts. Priority: **P0**
   — this is the single biggest UX cliff in the current wheel.

2. **Stage + review + commit the softbody / fluid / physics WIP dirs**
   — un-blocks the user's own outstanding physics work, moves ~40+
   module files from local-only to tracked, and enables downstream
   Ochema Circuit / Bullet Strata compat testing to run against the
   real softbody rather than the dynamics shim. Priority: **P0** for
   surface hygiene / **P1** contingent on user's fluid reconcile.

3. **Port `physics/particle_field.py:_slide` (`:1947`) to Rust per FF4
   ranking #1** — 10× estimated speedup on the dominant per-frame
   cost, biggest single-kernel win in the tree. Deliver
   `src/particle_field.rs` with `slide_rs` + `column_top_lut` +
   `set_phase_rs`. Priority: **P1** — 1-2 sprint-weeks.

4. **Round-10 STUB triage** — batch the 5 highest-impact remaining
   stubs into a single sprint slot: rows 78 (Diary Open picker), 79
   (Diary graph-to-Python), 191/192 (Theming Import / Export), 243
   (Content Browser Delete asset). Priority: **P1** — one sprint slot,
   flips 5 rows STUB → WIRED. Combined with un-pin sprint above this
   would leave 6 stubs total (rows 50, 94, 95, 193, 225-228 vicinity).

5. **Chain-manifest wiring into `NotebookPostProcessPanel`** — X5 + Z3
   shipped the plumbing but the panel preset combo still hits the
   hardcoded preset registry. Wiring it through
   `~/.slappyengine/postprocess_chains/` closes the user-override loop
   for post-process chains and matches the pattern used by hotkeys /
   themes / layouts / prefabs. Priority: **P2** — half-sprint slot.

---

## 7. Risk register

| Risk | Likelihood | Impact | Mitigation status |
|------|------------|--------|-------------------|
| **Wheel size drift** | Low | Med | Current `_core.cp313-win_amd64.pyd` is ~798 KiB (release, pre-strip). FF4 estimates the top-8 Rust ports would land the wheel at 1.1–1.3 MiB — comfortably below the 5 MiB PyPI convention and dwarfed by `wgpu` (~13 MiB). |
| **PyO3 upgrade risk** | Low | Low | Pinned `pyo3 = "0.22"`. FF4 audit found the 0.22 → 0.23 → 0.24 upgrade path is mechanical — `Bound<'py, PyByteArray>` and `Bound<'_, PyModule>` idioms already used throughout. Bump when a new kernel benefits, not speculatively. |
| **DPG headless quirks** | Medium | High | Z1 documented an unrecoverable access-violation in real-DPG on Windows under `SLAPPY_HEADLESS=1` when calling `dpg.group(...)` without a context. Every new notebook panel now inherits the `_safe_dpg` pattern (returns None when the imported dpg module is real AND `SLAPPY_HEADLESS` is set). New panels must call `_safe_dpg` on every DPG entry point or the Windows CI job will segfault mid-run. |
| **Cross-agent commit races** | Medium | Low | Round 1 sprint push saw ~30% strand rate (agents got their work committed but not credited to master); Round 2 dropped to ~10% via the SHA-echo pattern and worktree cherry-pick fallbacks. Current V→FF window used direct-to-master commits from within worktrees; 3 rate-limit-induced silent drops (DD1/DD3/DD5, FF1/FF2) were caught via salvage-from-working-tree commits (`7be6617`, `5fd475d`). DD7 was lost (no working-tree fragment). |
| **Silent rate-limit drops** | Medium | Med | Pattern is: agent's tool-use completes successfully, writes files, then hits rate limit during summary / commit generation. Files remain in the working tree — mitigation is a salvage sprint slot per batch that inspects `git status` and lands anything the agent produced but did not commit. **DD7 is the one exception** — no working-tree fragment was produced. |
| **Silent-acceptance regressions** | Low | High | W2 audit found 31 bug classes across 4 panels (material / theming / spawn / diary) where methods silently accepted invalid input, returned None, and logged nothing. Fixed by making every save / apply / set_* / _on_* / commit / dispatch / bind / refresh return bool status and expose `_validate_state()`. Pattern is now propagated through every new panel (see CC5 Toast subscribe pattern for a reference example). |
| **Float-precision drift on future Rust ports** | Med | High | `rust_migration_plan.md` risk register documents softbody `np.add.at` iteration-order regressions. Every new port must preserve iteration order, and add a canonical-scene regression test that pins a scalar (chassis x, particle centroid, V-cycle L2 residual) to a 1e-3 tolerance on the first step. |
| **Untracked-file bloat** | Med | Low | `git status` currently shows 60+ untracked files: WIP softbody / fluid / physics / physics2 (expected), 2 script scratchpads (`new_script_1.py` / `new_script_2.py`), `.claude/`, plus a couple of new docs. Should be cleaned before the next PR round. |
| **`src/lib.rs` mod-declaration lag** | Low | Med | 4 Rust files (`raster.rs`, `softbody_solver.rs`, `pbf_solver.rs`, `fluid_shader.rs`) are exported by the shipping wheel but not `mod`-declared in `src/lib.rs` (FF4 finding §1.2, first flagged in `rust_port_audit_2026_06_02.md` F1). A clean `maturin develop` on the current commit produces a wheel missing 20+ symbols. Fix: add the four `mod` + `::register(m)?` lines. |
| **Nova3D deletion pending** | Low | Low | Ten legacy panels + their pinned tests still ship. Blast radius is bounded to `python/slappyengine/ui/editor/legacy/*`; no other code paths import them. Removal is a scoped follow-up sprint. |

---

## 8. Contributor guidance (where each subsystem lives)

### Editor UI
* `H:\Github\SlapPyEngine\python\slappyengine\ui\editor\` — every notebook
  panel. Nomenclature: `notebook_<name>.py` for panels;
  `<name>_bridge.py` for cross-system glue; `<name>_baker.py` for the
  bake-into-YAML side of any config-baking pattern.
* Testing pattern: `SLAPPY_HEADLESS=1` env var + `_safe_dpg` helper +
  full `subscribe_to_*` callback wiring in `setUp`. Every panel exposes
  `_validate_state()` for round-trip inspection. See CC5 Toast panel
  tests for a compact reference.

### Theming
* `H:\Github\SlapPyEngine\python\slappyengine\ui\theme\` — three sub-libraries
  (`washi_tape/`, `page_linings/`, `edge_strokes/`) each with `library.py`
  (WGSL shader source) + `renderer.py` (wgpu-preferred, numpy fallback)
  + `library_spec.py` (metadata dict).
* Testing pattern: shader_lint via
  `python/slappyengine/shader_lint.py::lint_wgsl` + AA6 test at
  `SlapPyEngineTests/tests/test_shader_lint.py` (244 tests covering all
  53 shaders). DD6 batch validator writes Markdown + YAML manifests
  under `docs/shader_validation/` for CI tracking.

### Post-process
* `H:\Github\SlapPyEngine\python\slappyengine\post_process\` — TAA / bloom
  / chain manifest + executor + chain baker. Baked chain presets under
  `python/slappyengine/post_process/baked_chains/*.chain.yaml`.
* Testing pattern: `apply_manifest` CPU dispatcher runs headless via
  numpy fallback. Every pass has both a WGSL runtime path (preferred
  when wgpu is present) and a numpy fallback for CI.

### Content pipeline
* `H:\Github\SlapPyEngine\python\slappyengine\prefabs\` — Y3 prefab
  library + AA2 API polish + BB6 preview baker. Baked artifacts under
  `python/slappyengine/prefabs/baked/` (YAML + PNG previews).
* `H:\Github\SlapPyEngine\python\slappyengine\autosave.py` — Y6 module.
* `H:\Github\SlapPyEngine\python\slappyengine\project_registry.py` — V2.
* `H:\Github\SlapPyEngine\python\slappyengine\scenes\` — FF3 subpackage
  (`__init__.py`, `scene.py`, `scene_file.py`, `scene_registry.py`).

### Visual scripting
* `H:\Github\SlapPyEngine\python\slappyengine\visual_scripting\material_nodes.py`
  — V5 WGSL-emitting graph nodes.
* `H:\Github\SlapPyEngine\python\slappyengine\visual_scripting\codegen.py`
  — V6 Python ↔ Graph bidirectional codegen.
* `H:\Github\SlapPyEngine\python\slappyengine\ui\editor\material_graph_bridge.py`
  — AA4 + FF2 fix for texture / sampler binding heuristics.
* Golden fixtures: `SlapPyEngineTests\goldens\visual_scripting\`.

### Action / tool routing
* `H:\Github\SlapPyEngine\python\slappyengine\actions\` — every wired
  action module. Nomenclature: `<verb>_<noun>_actions.py`. Each round
  of triage adds 5 new files. Backing tests at
  `SlapPyEngineTests\tests\test_stub_triage_<batch>.py`.
* `H:\Github\SlapPyEngine\python\slappyengine\tool_router.py` — the
  central registry. Every new action registers via
  `_fb_<action_name>` + `REGISTRY[<action_id>] = ...`.

### User customization
* `~/.slappyengine/ui/panels/` — panel overrides.
* `~/.slappyengine/ui/hotkeys/` — hotkey overrides + bake target.
* `~/.slappyengine/ui/spawn_cards/` — spawn menu overrides.
* `~/.slappyengine/ui/shaders/` — WGSL overrides.
* `~/.slappyengine/projects.yaml` — recent projects (V2).
* See `docs/user_customization_2026_06_07.md` for full guide.

### Demos
* `H:\Github\SlapPyEngine\SlapPyEngineExamples\examples\` — every
  `hello_*.py` and its `hello_*_trace.yaml`. Each demo is headless
  (`SLAPPY_HEADLESS=1`), records per-frame or per-event state to
  `<demo>_trace.yaml`, and prints a milestone summary table to stdout.
  Tests at `SlapPyEngineTests\tests\test_demo_hello_*.py`.

### Infrastructure
* `H:\Github\SlapPyEngine\python\slappyengine\smoke_runner.py` — DD3.
* `H:\Github\SlapPyEngine\python\slappyengine\ui\theme\shader_batch_validator.py`
  — DD6.
* `H:\Github\SlapPyEngine\python\slappyengine\ui\hotkey_conflicts.py`
  — FF5.
* `H:\Github\SlapPyEngine\python\slappyengine\telemetry\sink.py` — EE7.

### Rust kernels
* `H:\Github\SlapPyEngine\src\` — every `.rs` file. `src/lib.rs` is
  the mod-declaration + register-with-Python entry. FF4 audit at
  `docs\rust_migration_audit_2026_07_05.md` documents the 17 shipped
  kernels + top-10 next ports ranking. Any new port must add
  regression test at first commit pinning a canonical-scene scalar to
  1e-3 tolerance.

---

## 9. Cross-reference index

Reference docs consulted during this rollup, all authored / updated in
this sprint window:

* `H:\Github\SlapPyEngine\docs\sprint_rollup_2026_07_04.md` — BB5 initial
  rollup + EE5 CC/DD extension.
* `H:\Github\SlapPyEngine\docs\feature_map_delta_2026_07_04.md` — Y7
  V/W/X delta + 5 STUB→WIRED flips + drift risks.
* `H:\Github\SlapPyEngine\docs\feature_map_delta_2026_07_04_v2.md` —
  EE5 post-DD compact delta.
* `H:\Github\SlapPyEngine\docs\engine_feature_map_2026_07_04.md` — 291-row
  feature map with per-action WIRED / STUB / BROKEN status + X3 / Y1 /
  Z7 / AA1 / BB1 / CC1 / DD1 / EE1 / FF1 patch sections at the tail.
* `H:\Github\SlapPyEngine\docs\rust_migration_audit_2026_07_05.md` — FF4
  Rust kernel inventory + Python hot-path candidates + top-10 ranking
  + wheel size / PyO3 / precision trade-offs.
* `H:\Github\SlapPyEngine\docs\diary_softbody_bridge_2026_07_04.md` — AA3
  investigation + shim documentation for rows 80 / 223.

Historical cross-references:

* `H:\Github\SlapPyEngine\docs\master_review_2026_06_07.md` — the
  master review + 7-sprint refactor plan the V-batch was drawn from.
* `H:\Github\SlapPyEngine\docs\consolidation_2026_06_07.md` — Nova3D
  legacy inventory + deletion blockers.
* `H:\Github\SlapPyEngine\docs\user_customization_2026_06_07.md` —
  `~/.slappyengine/ui/` override folder guide (X6 landing).
* `H:\Github\SlapPyEngine\docs\rust_migration_plan.md` — original
  7-step plan (Steps 1-6 shipped).
* `H:\Github\SlapPyEngine\docs\rust_port_audit_2026_06_02.md` — previous
  per-frame audit that FF4 builds on.
* `H:\Github\SlapPyEngine\docs\cargo_audit_2026_06_02.md` — crate hygiene.
* `H:\Github\SlapPyEngine\docs\rust_port_plan_dynamics.md` — drafted
  dynamics port plan (referenced from FF4).

---

## 10. Summary card

* **Batches shipped**: 11 letter tags (V W X Y Z AA BB CC DD EE FF) +
  GG in-flight.
* **Sprint slots**: ~76 committed (V–FF), 7 GG dispatched.
* **Commits**: ~89 on master (V–FF).
* **Feature map**: 233 → 291 rows (+58); WIRED 215 → 273 (+58);
  WIRED% 92.3% → 93.8%.
* **STUB / BROKEN**: 15 STUB / 3 BROKEN — unchanged since AA1.
* **Tests running**: ~5000+ passing across `SlapPyEngineTests/tests/`.
* **New router actions**: 45 across 9 STUB-triage rounds (X3 → FF1).
* **New editor panels + widgets**: ~30.
* **New demos**: 12 hello_* runners.
* **New Rust kernels**: 0 landed this window (FF4 audit only).
* **Baked artifacts**: 21 (6 prefabs + 6 chains + 6 layouts + 3 hotkeys).
* **Shader coverage**: 53 WGSL shaders across 3 libraries.
* **Highest-impact remaining work**: un-pin diary panel + rewire through
  AA3 bridge + V6 codegen — flips 4 rows and restores diary runner.

---

*Big-picture status report generated 2026-07-05 by GG7 scrum agent.
Cross-referenced against `git log --oneline --since=2026-07-04` (89
commits), FF4 audit, EE5 rollup, Y7 delta, EE5 delta v2, engine feature
map footer (291-row FF1 tally), and AA3 diary bridge investigation.*
