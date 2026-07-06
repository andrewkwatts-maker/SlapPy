# Engine Feature Map — Delta Report v3 (2026-07-06, post-MM6)

Compact delta against `docs/feature_map_delta_2026_07_04_v2.md` (EE5).
Covers every WIRED / STUB / BROKEN change between the DD1 close
(`7be6617`, 2026-07-05 nightly) and the MM6 STUB-triage round-14
salvage (`1e584e4`, 2026-07-07 morning Brisbane).

Baseline (v2 post-DD1): **281 rows, 263 WIRED (93.6%), 15 STUB (5.3%),
3 BROKEN (1.1%)**.

Post-NN2 tally (NN2 round 15 landed as `9406546` during the NN
dispatch window):
**340 rows, 323 WIRED (~95.0%), 13 STUB (~3.8%), 3 BROKEN (~0.9%)**.

Net delta v2 → v3: **+59 rows, +60 WIRED, −2 STUB, ±0 BROKEN**.

Authored by NN6 background scrum agent, 2026-07-06 evening. Reads as
"what did the EE + FF + GG + HH + II + JJ + KK + LL + MM batches
add to the feature map that v2 doesn't capture".

---

## Newly-WIRED rows since v2 (DD1 close)

Rows added or flipped during the EE / FF / GG / HH / II / JJ / KK /
LL / MM windows. Includes six triage rounds (r8 EE1, r9 FF1, r10 GG1,
r11 II5, r12 JJ6, r13 KK7, r14 MM6) plus the 19-row MM3 audit that
retroactively catalogued the JJ + KK + LL landings.

### Triage rounds 8-14 (35 rows across 7 rounds)

| Row(s) | Batch / Round | Action ids | Provenance | Commit |
|--------|--------------|------------|------------|--------|
| 282..286 | EE1 (round 8) | `theme.duplicate`, `theme.rename`, `edit.copy_transform`, `edit.paste_transform`, `spawn.repeat_last_with_offset` | `actions/theme_duplicate_actions.py`, `transform_clipboard_actions.py`, `spawn_offset_actions.py` | `77ac09b` |
| 287..291 | FF1 (round 9) | `file.import_scene`, `edit.split_selection`, `view.zoom_to_selection`, `theme.reset_to_default`, `tool.measure` | `actions/scene_import_actions.py`, `edit_split_actions.py`, `view_zoom_selection_actions.py`, `theme_reset_actions.py`, `tool_measure_actions.py` | `5fd475d` |
| 292..296 | GG1 (round 10) | `file.export_scene`, `edit.group_selection`, `edit.ungroup_selection`, `view.toggle_wireframe`, `panel.reset_panel_layout` | `actions/scene_export_actions.py`, `edit_group_actions.py`, `view_wireframe_actions.py`, `panel_reset_actions.py` | `1414e1d` |
| 297..301 | II5 (round 11) | `file.new_scene`, `edit.rename_selection`, `view.toggle_perf_hud`, `theme.snapshot_current`, `content.reveal_in_explorer` | `actions/scene_new_actions.py`, `edit_rename_actions.py`, `view_perf_hud_actions.py`, `theme_snapshot_actions.py`, `content_explorer_actions.py` | `f651d21` |
| 302..306 | JJ6 (round 12) | 5 more triage entries (see feature-map §JJ6) | `actions/*` | `0783e33` |
| 307..311 | KK7 (round 13) | 5 more triage entries (see feature-map §KK7) | `actions/*` | `2437bb1` |
| **331..335** | **MM6 (round 14)** | `capture.start_recording`, `capture.stop_recording`, `capture.screenshot`, `render.enable_ssao`, `render.enable_shadows` | `actions/capture_actions.py` (365 LoC), `actions/render_toggle_actions.py` (255 LoC) | `1e584e4` |
| **NN2 (round 15)** | see `docs/feature_map_delta_2026_07_05.md` for row numbers | `view.frame_selected`, `view.reset_view`, `panel.dock_left`, `panel.dock_right`, `theme.hot_swap` | `actions/{view_frame_selected,view_reset_view,panel_dock,theme_hot_swap}_actions.py` | NN2 landing (see delta) |

Round-14 total: **70 wired actions across 14 rounds**. NN2 round 15
adds 5 more (per its own dedicated delta doc), bringing the running
total to **75 wired actions across 15 rounds**.

### MM3 JJ + KK + LL landings audit (19 rows retroactively catalogued)

MM3's audit rolled every JJ / KK / LL sprint's user-invocable
capability into the row-numbered baseline. Rows 312–330 all landed on
master in r3 but were not previously tracked as feature-map rows.

| Row | Feature | Batch | Provenance | Commit |
|-----|---------|-------|------------|--------|
| 312 | Real wgpu forward pipeline | JJ1 | `render/renderer.py`, `render/pipeline.py`, `render/shader_stock.py` | `3ea1432` |
| 313 | MTL material resolver | JJ2 | `asset_import/mtl_resolver.py`, `asset_import/obj_importer.py` | `544317f` |
| 314 | Skinned-mesh glTF importer | JJ3 | `asset_import/gltf_importer.py`, `asset_import/skinned_mesh.py` | `8d10f91` |
| 315 | Skeleton runtime + AnimationClip + Skinner | JJ4 | `animation/skeleton_runtime.py`, `animation/clip.py`, `animation/skinner.py` | `9b457e6` |
| 316 | SceneWalker (Scene → drawcall + frustum cull) | JJ5 | `render/scene_walker.py` | `1867012` |
| 317 | Cascaded shadow maps | JJ7 | `render/shadows.py`, `lighting.py`, `shaders/csm.wgsl` | `9b457e6` (bundled with JJ4) |
| 318 | 3D BVH broadphase for frustum culling | KK1 | `render/bvh_3d.py` | `47950ba` |
| 319 | DepthPrepass + MSAAResolvePass + PassChain | KK2 | `render/passes.py`, `render/pipeline.py` | `d282c17` |
| 320 | SSAO pass | KK3 | `render/ssao.py`, `shaders/ssao.wgsl` | `0078382` |
| 321 | Skybox + cubemap import | KK4 | `asset_import/cubemap_importer.py`, `render/skybox.py` | `7f80f9e` |
| 322 | IBL prefilter chain | KK5 | `gpu/ibl.py`, `shaders/ibl_prefilter.wgsl` | `bb7392a` |
| 323 | SDF text glyph atlas | KK6 | `text/{atlas,sdf_generator,sdf_glyph,text_render}.py` | `27f9c88` |
| 324 | Instanced rendering | LL3 | `render/instanced.py`, `components.py` | `bdb9547` |
| 325 | Runtime HUD overlay | LL1 | `ui/runtime/{hud_overlay,hud_registry,hud_kit_extra}.py` | `6afa7d6` |
| 326 | Video / GIF / frame capture | LL2 | `capture/{video_capture,gif_capture,frame_dump,capture_manager}.py` | `47bc7f0` |
| 327 | 3D positional audio | LL4 | `audio_3d.py` | `8300cd8` |
| 328 | `hello_gltf_character` acceptance demo | LL5 | `examples/hello_gltf_character.py` | `670d91c` |
| 329 | Cross-platform game exporter + `slap export` | LL6 | `exporter/{__init__,manifest,binary_exporter,zip_bundler,platform_targets}.py` | `7f4f0f4` |
| 330 | `physics3_bridge` — soft-import 3D physics + SAP fallback | LL7 | `physics3_bridge.py` | `8376e7e` |

### Row-50 STUB → WIRED (MM3 audit)

Row 50 (`H` hotkey Toggle HUD) had been flagged in v2 as STUB
because the flag flip had no downstream consumer. LL1's `HUDOverlay`
now reads `shell._hud_visible` via the runtime overlay layer — MM3
audit officially flipped this row to WIRED.

### Non-triage WIRED rows added between v2 and r4 close

Every EE + FF + GG batch also added user-invocable capabilities that
went into the feature map without a row number (uncatalogued at the
time). These are all still WIRED at r4 close but not row-numbered
because the MM3 audit focused on JJ / KK / LL sprints. Notable
additions (no row assignment, tracked in
`engine_feature_map_2026_07_04.md` batch sections):

* `hello_v2_showcase` mega-demo (EE2), `NotebookMenuBar` (EE3),
  `FileDropHandler` (EE4), `NotebookPPPreviewPanel` (EE6),
  `TelemetrySink` (EE7).
* `slappyengine.scenes` subpackage (FF3), hotkey conflict detector
  (FF5), `NotebookMinimap` (FF6), `hello_scene_reg` demo (FF7).
* `ProjectSceneBridge` (GG2), `PluginRegistry` (GG3), perf tripwire
  (GG4), `NotebookCurveEditor` (GG5), `scene_diff` (GG6),
  `big_picture_2026_07_05` status report (GG7).
* MM2 `hud_bridge.py` + `App.enable_hud()` + `hello_hud` demo +
  golden trace.
* MM5 `hello_showcase_v3.py` (25+ subsystem end-to-end).
* MM7 `hello_render_real.py` + procedural bunny asset.

### MM1 hardening additions (13 files with input validation + logging)

MM1 (salvaged in `1e584e4`) hardened every JJ / KK / LL public entry
point per r3 §10.1's recommendation. None of these are new feature-
map rows — they're input-validation additions on top of existing
rows — but they are worth catalogueing here as the "state" of the
r3 rows changed materially (silent-acceptance → raise).

| Row(s) affected | File | Hardening added |
|-----------------|------|-----------------|
| 320 | `render/ssao.py` | `SSAOPass.execute` renderer / depth / normal `None`-checks. |
| 324 | `render/instanced.py` | `render_instanced` renderer + mesh type-checks. |
| 321 | `render/skybox.py` | `Skybox.render` renderer `None`-check + warn-once fallback. |
| 323 | `text/sdf_generator.py` | Font path / glyph list input validation. |
| 323 | `text/text_render.py` | `TextRenderer.draw_text` layout + atlas checks. |
| 327 | `audio_3d.py` | `SoundBank.load` logs manager `OSError` + silent-bank fallback. |
| 326 | `capture/capture_manager.py` | `record` + `capture_screenshot` input checks. |
| 326 | `capture/gif_capture.py` | `write_frame` pixels + output path guards. |
| 326 | `capture/video_capture.py` | `write_frame` pixels + output path guards. |
| 329 | `exporter/zip_bundler.py` | `bundle` project_dir + output_zip validation. |
| 330 | `physics3_bridge.py` | `World3D.query_aabb` aabb `None`-check. |
| 321 | `asset_import/cubemap_importer.py` | `import_cubemap` + `import_hdr_cubemap` path type/empty checks. |
| 313 | `asset_import/mtl_resolver.py` | `parse_mtl` + `import_obj_with_materials` path validation with logger warnings. |

Net effect: rows 313, 320, 321, 323, 324, 326, 327, 329, 330 all now
carry explicit `TypeError` / `ValueError` semantics rather than
propagating an `AttributeError` deep in the call graph. This is the
silent-acceptance sweep r3 §10.1 recommended.

---

## STUB roster after MM6

Feature-map footer reports **13 STUB rows** at r4 close (down from
15 at DD1 close, and down from 14 at KK7 close):

* Row 78 / 79 / 80 / 223 — diary softbody import + `open_diary_
  picker` fallback. Un-pinning `notebook_diary_page.py` and rewiring
  through `diary_softbody_bridge` (AA3) + `codegen.graph_to_python`
  would flip 4 rows in one commit.
* Row 94 / 95 — theming editor "Load/Save layout" (BB1 landed
  Import/Export; Load-from-file still uses a hardcoded path).
* Row 191 / 192 / 193 — DPG shell-dependent panel toggles (documented
  by II5 as "the remaining 14 named STUBs are DPG-shell-dependent
  and cannot be safely wired until the shell exposes a stable
  toggle API").
* Row 222 / 224 / 225 / 226 / 227 / 228 — DPG shell-dependent (per
  II5).
* Row 243 — chain-manifest wiring in `NotebookPostProcessPanel`
  (still uses hardcoded preset registry; see v2 §"What did NOT
  ship").

**Row 189** (Theming editor "Save as new") remains the only "STUB →
WIRED" flip through a real code path (landed in W2). Every other
STUB → WIRED transition in this v2 → v3 window came from row-50's
LL1 HUD-flag wiring flip catalogued by MM3.

## BROKEN roster after MM6

Unchanged from v2: rows 80, 223 (diary softbody import; two
callsites at `notebook_diary_page.py:539` + `:610`), and the row-80
duplicate via `run_script`. Dedupes to **2 real code paths**. AA3
shipped the `diary_softbody_bridge` shim; the diary panel is still
pinned read-only for the pending un-pin sprint.

---

## What did NOT ship (v2 → v3)

* **MM1 hardening** hit rate-limit in the MM batch; salvaged in the
  NN batch via `1e584e4`. No production drift.
* **MM6 STUB triage r14** — same story: dispatched in MM, salvaged
  in NN. No production drift.
* **NN1-NN5** — mostly rate-limited without working-tree drift.
  NN6 (docs consolidation r4) landed. NN1-NN5 dispatched scopes
  need re-dispatch in the next batch (see NN todo list under
  `.claude/`).
* **Golden traces for MM5 + MM7** — both demos ship without
  `test_demo_*` guards. Follow-up (r4 §7.4).
* **Softbody / fluid / physics WIP dirs** — still uncommitted in
  the local tree per `git status` at MM6 close. Follow-up sprint
  required (r4 §7.3, user-gated).
* **Nova3D legacy strip** — pinned tests still block the deletion
  of the ten legacy panels catalogued in
  `docs/consolidation_2026_06_07.md`.

---

## Overall roll-up (post-NN2, r4 close)

* **Total rows: 340** (v2 baseline 281 + 59 net new rows).
* **WIRED: 323** (v2 baseline 263 + 60 net; +1 from row-50 flip).
* **STUB: 13** (v2 baseline 15 − 2 through the row-50 flip and
  round-11 II5 dedup).
* **BROKEN: 3** (unchanged; dedupes to 2 real code paths).

Percentages: **WIRED ~95.0%**, **STUB ~3.8%**, **BROKEN ~0.9%**.

Highest-impact remaining STUB: still **row 80 / 223** — diary
softbody import. Un-pinning would flip 4 rows in one commit.

---

## Roll-up progression across three deltas

| Delta | Cumulative window | Total | WIRED | STUB | BROKEN | WIRED % |
|-------|-------------------|-------|-------|------|--------|---------|
| v1 (Y7 baseline) | X + Y batches | 248 | 226 | 19 | 3 | 91.1% |
| v2 (DD1 close) | Z + AA + BB + CC + DD | 281 | 263 | 15 | 3 | 93.6% |
| **v3 (r4 close, this doc)** | **EE + FF + GG + HH + II + JJ + KK + LL + MM + NN** | **340** | **323** | **13** | **3** | **~95.0%** |

r4 net delta over the 10-batch (EE→NN) window: **+59 rows, +60
WIRED, −2 STUB, ±0 BROKEN**.

---

*Delta v3 generated 2026-07-06 by NN6 scrum agent. Sources: v2 delta
baseline + `docs/engine_feature_map_2026_07_04.md` batch sections
for EE1 through MM6 rounds 8-14 + MM3 audit + MM1 hardening file
list from `1e584e4`. Cross-referenced against `git log --oneline
-40` and the live source tree at `python/slappyengine/actions/*`,
`python/slappyengine/render/*`, `python/slappyengine/asset_import/*`,
`python/slappyengine/capture/*`, `python/slappyengine/text/*`,
`python/slappyengine/exporter/*`.*
