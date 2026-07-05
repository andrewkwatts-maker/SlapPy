# Engine Feature Map — Delta Report v2 (2026-07-04 → post-DD)

Compact delta against `docs/feature_map_delta_2026_07_04.md` (Y7).
Covers the Z / AA / BB / CC / DD batch landings that shipped between
Y7's re-audit (2026-07-04 close) and the DD1 salvage commit
(`7be6617`, 2026-07-05 nightly).

Baseline (V1 post-Y7 delta): **248 rows, 226 WIRED (91.1%),
19 STUB (7.7%), 3 BROKEN (1.2%)**.

Post-DD tally per feature-map footer:
**281 rows, 263 WIRED (93.6%), 15 STUB (5.3%), 3 BROKEN (1.1%)**.

Net delta: **+33 rows, +37 WIRED, −4 STUB, ±0 BROKEN**.

---

## New WIRED rows since Y7

Rows added or flipped in the Z / AA / BB / CC / DD windows.

| Row | Feature | Batch | Provenance | Commit |
|-----|---------|-------|------------|--------|
| — | Baked post-process chain presets (6) | Z3 | `post_process/chain_baker.py`; `baked_chains/*.chain.yaml` | `8092f0c` |
| — | NotebookPrefabMenu | Z2 | `notebook_prefab_menu.py` | `9ec1ef3` |
| — | EditorAutosaveIntegration | Z6 | `editor_autosave.py` | `bf0a16b` |
| — | NotebookMessageLog headless-DPG fix | Z1 | `notebook_message_log.py` | `fb073f4` |
| 249..253 | 5 Z7 action wirings (`tool.snap_to_grid`, `view.zoom_in`, `view.zoom_out`, `view.zoom_reset`, `theme.export_current`) | Z7 | `actions/tool_settings_actions.py`, `camera_actions.py`, `theme_io_actions.py` | `39cad69` |
| — | diary_softbody_bridge shim | AA3 | `ui/editor/diary_softbody_bridge.py` | `d6fffaa` |
| — | MaterialGraphBridge | AA4 | `ui/editor/material_graph_bridge.py` | `eb6767c` |
| — | hello_full_editor demo | AA5 | `examples/hello_full_editor.py` | `9997cdd` |
| — | shader_lint (53-shader coverage) | AA6 | `shader_lint.py` | `b5f573a` |
| — | hotkey_remap + 3 baked presets | AA7 | `ui/hotkey_remap.py`, `ui/hotkeys/baked/` | `c51bf89` |
| 254..258 | 5 AA1 action wirings (`edit.cut_selection`, `delete_selection`, `view.center_on_selection`, `frame_all`, `tool.pan`) | AA1 | `actions/destructive_edit_actions.py`, `viewport_framing_actions.py`, `tool_mode_actions.py` | `f6bb3f0` |
| — | PrefabLibrary API polish (`spawn`, `entity_count`, `bake_and_load`) + `AutosaveManager.read_snapshot` | AA2 | `prefabs/`, `autosave.py` | `70b9913` |
| 267..271 | 5 BB1 action wirings (`theme.import_from_file`, `file.save_layout_as`, `file.load_layout_from_file`, `edit.undo`, `edit.redo`) | BB1 | `actions/theme_import_actions.py`, `layout_io_actions.py`, `history_actions.py` | `a360d56` |
| — | NotebookAutosavePanel | BB3 | `ui/editor/notebook_autosave_panel.py` | `f1eb450` |
| — | Shader hot-reload watcher | BB4 | `ui/theme/shader_hot_reload.py` | `121b1c3` |
| — | Prefab preview icon baker + 6 previews | BB6 | `prefabs/preview_baker.py`, baked PNGs | `e1371da` |
| — | NotebookHotkeyHelp | BB7 | `ui/editor/notebook_hotkey_help.py` | `8b6f8b1` |
| 272..276 | 5 CC1 action wirings (`edit.select_by_name`, `spawn.repeat_last`, `view.toggle_grid`, `view.toggle_gizmos`, `content.copy_asset_path`) | CC1 | `actions/edit_by_name_actions.py`, `spawn_history_actions.py`, `view_toggle_actions.py`, `content_shell_actions.py` | `06620e8` |
| — | hello_material_graph demo (4 WGSL graphs) | CC2 | `examples/hello_material_graph.py` + 4 `.wgsl` | `54b9104` |
| — | NotebookAssetInspector (7 asset kinds) | CC3 | `ui/editor/notebook_asset_inspector.py` | `039763e` |
| — | LayoutBaker + 6 baked layout presets | CC4 | `ui/editor/layout_baker.py`, `baked_layouts/*.layout.yaml` | `2b835c3` |
| — | NotebookToastManager | CC5 | `ui/editor/notebook_toast_manager.py` | `7b14ec7` |
| — | CameraAnimator + `view.focus_on_selection_animated` + `view.frame_all_animated` | CC6 | `actions/camera_animation_actions.py` | `78755c8` |
| — | NotebookCommandPalette (Ctrl+Shift+P) | CC7 | `ui/editor/notebook_command_palette.py` | `c923b82` |
| 277..281 | 5 DD1 action wirings (`layer.duplicate`, `panel.close_all`, `panel.restore_last_hidden`, `spawn.repeat_last_batch`, `theme.cycle_reverse`) — salvage | DD1 | `actions/layer_duplicate_actions.py`, `panel_visibility_actions.py`, `spawn_batch_actions.py`, `theme_cycle_reverse_actions.py` | `7be6617` |
| — | SmokeRunner subsystem — salvage | DD3 | `smoke_runner.py` | `7be6617` |
| — | NotebookTimelineEditor — salvage | DD5 | `ui/editor/notebook_timeline_editor.py` | `7be6617` |
| — | hello_toast_animation demo | DD2 | `examples/hello_toast_animation.py` | `324e8e6` |
| — | NotebookTelemetryDashboard | DD4 | `ui/editor/notebook_telemetry_dashboard.py` | `18b9618` |
| — | Shader batch validator + Markdown/YAML report | DD6 | `ui/theme/shader_batch_validator.py` | `8c55a43` |

---

## STUB roster after DD1

Feature-map footer reports **15 STUB rows** unchanged from AA1 close:
50, 78, 79, 94, 95, 191, 192, 193, 222, 224, 225, 226, 227, 228, 243.

None of the six DD1 flips or five CC1 flips touched an existing STUB
row — each round of triage added new WIRED rows for previously-absent
router actions rather than reviving stubs. Row 189 (Theming editor
"Save as new") remains the only STUB → WIRED flip in this whole
window (landed in W2 back in July).

## BROKEN roster after DD1

Unchanged: rows 80, 223 (diary softbody import; two callsites at
`notebook_diary_page.py:539` + `:610`), and the row-80 duplicate via
`run_script`. Dedupes to **2 real code paths**. AA3 shipped the shim
(`diary_softbody_bridge`) but the diary panel is still pinned
read-only for the pending un-pin sprint.

---

## What did NOT ship

* **DD7** — no commit reached master. Rate-limit-induced silent drop
  with no working-tree fragment to salvage. Retry required.
* **Softbody / fluid / physics WIP dirs** — still uncommitted in the
  local tree per `git status` at DD-close. Follow-up sprint required
  to stage + review + commit.
* **Nova3D legacy strip** — pinned tests still block the deletion of
  the ten legacy panels catalogued in `docs/consolidation_2026_06_07.md`.
* **Chain manifest wiring in NotebookPostProcessPanel** — X5 + Z3
  landed the infrastructure and presets; the panel still uses the
  hardcoded preset registry rather than loading from
  `~/.slappyengine/postprocess_chains/`.

---

## Overall roll-up (post-DD)

* **Total rows: 281** (Y7 baseline 248 + 33 net new rows).
* **WIRED: 263** (Y7 baseline 226 + 37 net).
* **STUB: 15** (Y7 baseline 19 − 4 rewire/dedup during Z7 audit
  normalisation).
* **BROKEN: 3** (unchanged; dedupes to 2 real code paths).

Percentages: **WIRED 93.6%**, **STUB 5.3%**, **BROKEN 1.1%**.

Highest-impact remaining STUB (unchanged since Y7): **row 80 / 223**
— diary softbody import + `open_diary_picker` fallback. Un-pinning
`notebook_diary_page.py` and rewiring through `diary_softbody_bridge`
+ `codegen.graph_to_python` would flip **4 feature-map rows**
(78 / 79 / 80 / 223) in one commit.

---

*Delta v2 generated 2026-07-05 by EE5 scrum agent. Sources: Y7 delta
baseline + 21 commits between `fb073f4` (Z1) and `7be6617` (DD1
salvage). Cross-referenced against `git log --oneline -40` and
`docs/engine_feature_map_2026_07_04.md` footer + per-batch STUB-triage
patch sections.*
