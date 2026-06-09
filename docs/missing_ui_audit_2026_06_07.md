# Missing UI Audit — SlapPyEngine (2026-06-07)

> Audit of every subpackage in :mod:`slappyengine` against the notebook
> editor surface.  Tracks which subsystems already have a dedicated
> editor panel, which lack one, and what the top-impact gaps look like.
>
> Source feeds:
>
> * [`feature_map_2026_06_03.md`](feature_map_2026_06_03.md) — current
>   30-subpackage map + §4.3 "Subsystems lacking editor surfaces".
> * [`ui_pattern_audit_2026_06_03.md`](ui_pattern_audit_2026_06_03.md)
>   — Nova3D → notebook translation contracts.
> * [`sprint_plan_2026_06_03.md`](sprint_plan_2026_06_03.md) —
>   Sprint 3 / 4 / 5 / 6 / 7 deliverables.
> * [`notebook_editor_manual_2026_06_03.md`](notebook_editor_manual_2026_06_03.md)
>   — end-user docs for the panel family.
>
> WIP-frozen perimeter (per memory note ``project_sprint_2026_05_29.md``):
> :mod:`slappyengine.softbody` and :mod:`slappyengine.fluid` are **not
> touched** by this audit — surfaces listed via ``__init__.py`` only.

---

## 1. Coverage status by subpackage

Legend:

* **COVERED** — a dedicated, notebook-themed editor panel ships today.
* **PARTIAL** — touched by an inspector reflection / generic widget but
  no purpose-built panel.
* **GAP** — declared in the roadmap or feature map but no editor surface
  on disk.
* **N/A** — runtime-only subsystem; no editor authoring is in scope.

| Subpackage | Coverage | Existing panel(s) | This-sprint action |
|---|---|---|---|
| `dynamics` | COVERED | `NotebookSpawnMenu` cards 1-4 (rope / ragdoll / humanoid / IK chain), `NotebookInspector` reflection for bodies + joints | — |
| `topology` | N/A | (internal substrate; no authoring surface in scope) | — |
| `numerics` | GAP | (none) | Defer — a CLI/REPL panel is in scope for the dynamics-debug HUD sprint |
| `zones` | PARTIAL | `NotebookSpawnMenu` cards 5-6 spawn zone specs but cannot paint zones on the viewport | Defer to dedicated zone-painter sprint |
| `thermal` | PARTIAL | `NotebookInspector` reflection on `HeatField` | Defer |
| `softbody` | N/A (WIP-frozen) | — | — |
| `fluid` | N/A (WIP-frozen) | — | — |
| `physics` (legacy) | PARTIAL | `LayerPanel` adjacency; no per-pixel sim authoring | Defer to Phase D strip |
| `gi` | GAP | (none) | Defer — a render-quality preset picker is the recommended design |
| `post_process` | **COVERED (NEW)** | `NotebookPostProcessPanel` — this sprint | Done |
| `material` | PARTIAL | `NotebookMaterialEditor` reflects fields but no node-graph canvas | Sprint 4 target |
| `gpu` | N/A | (internal; pipeline authoring not in scope) | — |
| `compute` | N/A | (internal substrate) | — |
| `residency` | N/A | (storage backend) | — |
| `studio` | COVERED | `NotebookWelcome` demo cards; the demos *are* the authoring surface | — |
| `iso` | GAP | (none) | Defer — a tile-painter + wave/encounter editor is recommended |
| `audio_runtime` | GAP | (none) | Defer — a backend / device chooser + sound preview is recommended |
| `telemetry` | **COVERED (NEW)** | `NotebookTelemetryPanel` — this sprint | Done |
| `testing` | N/A | (visual-regression harness; no editor authoring in scope) | — |
| `animation` | **COVERED (NEW)** | `NotebookAnimationPanel` — this sprint (timeline + keyframe editor) | Done |
| `ai` | PARTIAL | `NotebookCodePanel` (the only consumer) | Defer — a model / token-budget panel is recommended for Sprint 7 |
| `ext` | N/A | (re-export shim) | — |
| `net` | GAP | (none) | Defer to mid-term roadmap |
| `assets` | PARTIAL | `NotebookContentBrowser` lists assets but no per-asset import dialog | Defer |
| `modules` | N/A | (plugin contract) | — |
| `tools` | N/A | (CLI utilities) | — |
| `ui` family | COVERED | every panel under `ui.editor` | — |
| `ecs` (planned) | GAP | (subpackage absent) | Sprint 2 prereq |
| `vfx` (planned) | GAP | (subpackage absent) | Sprint 5 |
| `i18n` (planned) | GAP | (subpackage absent) | Sprint 7 |

---

## 2. Gap analysis — recommended panel per gap

Each row below ranks an outstanding gap, sketches the proposed UI, lists
the smallest plausible MVP test footprint, and calls out the sprint
dependency.

### 2.1 `telemetry` — Live event stream viewer  **[SHIPPED — §3.1]**

* **User-facing impact.** Highest of the GAP list — every gameplay
  developer wants a "trace what the engine is doing" pane.  Bullet
  Strata's reactive HUD dirty flag is the canonical motivator.
* **Design.** Notebook-themed table fed by `telemetry.subscribe("*")`.
  Filter input (fnmatch OR substring), Pause / Resume, Clear, Pin
  drawer for quick navigation.  Newest event at the top.
* **MVP tests.** Construct, subscribe / unsubscribe lifecycle,
  pause-drops-events, filter, pin / unpin, clear, capacity trim,
  theme switch.
* **Dependency.** Stand-alone — no other sprint blocks it.

### 2.2 `post_process` — Chain editor  **[SHIPPED — §3.2]**

* **User-facing impact.** Tier-1 — visual polish controls are the
  showcase for the engine and were previously CLI-only.
* **Design.** Reorderable / toggleable list (`HeartCheckbox` per row +
  up / down / remove buttons), inline quick-tweak sliders for the 1-2
  most-important params per pass, preset chooser (cinematic / arcade /
  iso-strategy), add-pass modal.
* **MVP tests.** Construct, toggle pass, reorder (up / down at
  boundaries), remove, add, preset replace, param set, status counts,
  theme switch.
* **Dependency.** Stand-alone.

### 2.3 `animation` — Timeline + keyframe editor  **[SHIPPED — §3.3]**

* **User-facing impact.** Tier-1 — the engine has no other surface for
  authoring per-property animation today (`AnimationGraph` only edits
  state-machine wiring).
* **Design.** Hand-drawn ruler at the top, one row per `Track` with
  click-to-select keyframes + curve preview rendered via the cached
  `AnimationCurve`.  Transport (Play / Pause / Loop) + Save sticker
  writes `<scene_root>/<entity>.anim.yaml`.
* **MVP tests.** Construct, add / remove / move keyframe, seek,
  toggle play, loop, tick drives the playhead, save round-trip,
  curve preview length, theme switch.
* **Dependency.** Math `AnimationCurve` + `Keyframe` (already
  shipped).

### 2.4 `gi` — Render-quality preset picker (GAP, deferred)

* **User-facing impact.** Mid — GI defaults today come from
  `lighting_presets.md` and the rebuild-stack scenes.  A picker would
  surface the cascade / ReSTIR / SVGF dials behind 3-4 named presets
  (lo-fi diary, indie polish, AAAA showcase, debug).
* **Design.** Three sticker buttons (one per preset) + inline preview
  swatch.  A "Custom" drawer reveals the raw dataclass via a nested
  `NotebookInspector`.
* **MVP tests.** Construct, preset apply, custom override, theme switch.
* **Dependency.** Sprint 6 (profiler overlay) ships first so users
  can verify perf impact of each preset.

### 2.5 `zones` — Viewport painter (GAP, deferred)

* **User-facing impact.** Mid — `NotebookSpawnMenu` already adds zones
  by dataclass; a viewport painter would let users drag rectangles on
  the canvas directly.
* **Design.** Three-state tool (rect / threshold / select); drag in the
  viewport spawns a `RectZone` / `ThresholdZone`; the inspector binds
  to the live zone for fine-tuning.
* **MVP tests.** Construct, drag-spawn (rect), drag-spawn (threshold),
  select-drag, undo / redo.
* **Dependency.** Viewport panel needs cursor-coordinate plumbing
  (gap #2 in the feature map).

### 2.6 `dynamics` — Physics debug HUD (GAP, deferred)

* **User-facing impact.** Mid — `Sprint 6 profiler overlay (F3)` is
  the canonical home for this.  Joint count, total energy, broadphase
  pair count, contact count per frame.
* **Design.** Floating HUD strip docked to the bottom of the viewport.
* **MVP tests.** Sample every frame; assert non-NaN.
* **Dependency.** Sprint 6 (profiler overlay).

### 2.7 `iso` — Wave / encounter editor (GAP, deferred)

* **User-facing impact.** Low (game-specific) — Stone-Keep-style games
  need a wave timeline + enemy roster; the rest of the engine doesn't.
* **Design.** Per-wave row with sticker buttons for known enemy
  prefabs + slider for spawn count.
* **MVP tests.** Construct, add wave, reorder waves, JSON round-trip.
* **Dependency.** Stand-alone but low-priority.

### 2.8 `audio_runtime` — Backend / device chooser + sound preview (GAP, deferred)

* **User-facing impact.** Low — only matters when the user is
  authoring audio assets.
* **Design.** Backend dropdown (real / stub), device dropdown, sample
  list with a Play sticker per row.
* **MVP tests.** Construct, switch backend, list devices, play stub.
* **Dependency.** Stand-alone.

### 2.9 `numerics` — Solver-settings REPL (GAP, deferred)

* **User-facing impact.** Low — power-user surface.
* **Design.** Small inline shell with autocomplete for the V-cycle
  knobs (smoother count, omega, tolerance).
* **MVP tests.** Construct, run a sample command, theme switch.
* **Dependency.** Stand-alone.

---

## 3. This-sprint deliverables — design notes

### 3.1 `NotebookTelemetryPanel`

File: `python/slappyengine/ui/editor/notebook_telemetry_panel.py`

* Subscribes to `telemetry.subscribe("*", self._on_event)` at
  `build()` time; unsubscribes in `destroy()`.  Idempotent across
  multiple `subscribe()` calls so an editor restart never accumulates
  duplicate handles.
* Stores events newest-first up to `DEFAULT_CAPACITY = 500`.
* Filter dispatch: substring (case-insensitive) when the pattern has no
  fnmatch metachar, otherwise `fnmatch.fnmatchcase`.  Helper
  `matches_filter` is exported as the canonical contract.
* Controls: `Pause` / `Clear` / `Pin top` sticker buttons; per-row
  `pin` button; per-pinned-row `unpin`.  All actions push a
  `(name, payload)` tuple onto `self.call_log` so tests verify routing
  without DPG.
* Theme integration: registers a listener that calls `refresh()`
  on switch; resolves `ink` / `accent` / `washi` from the active
  theme.

### 3.2 `NotebookPostProcessPanel`

File: `python/slappyengine/ui/editor/notebook_post_process_panel.py`

* Binds to a `PostProcessChain` (creates an empty one if `None`).
* Per-pass row: `HeartCheckbox` for `enabled`, `up` / `down` /
  `x` buttons, inline quick-tweak sliders from `QUICK_TWEAK_PARAMS`
  for the 9 supported labels.
* Add-pass modal lists every entry in `AVAILABLE_PASSES` (9 entries:
  bloom / tonemap / vignette / outline / blur / pixelate /
  chromatic_aberration / gravity_warp / night_vision).
* Preset row: three sticker buttons calling `cinematic_chain` /
  `arcade_chain` / `iso_strategy_chain`.
* `on_chain_changed` callback fires after every mutation so the
  editor shell can re-bake the GPU pipeline.

### 3.3 `NotebookAnimationPanel`

File: `python/slappyengine/ui/editor/notebook_animation_panel.py`

* Owns a list of `Track`s; each `Track` wraps a list of `Keyframe`s
  and a cached `AnimationCurve` (rebuilt on every mutation).
* Public API: `add_track` / `remove_track` / `add_keyframe` /
  `remove_keyframe` / `move_keyframe` / `select` / `seek` /
  `play` / `pause` / `toggle_play` / `set_loop` / `tick` /
  `bind_entity` / `save`.
* Curve preview: `curve_preview(track_index, samples=32)` returns
  the sampled values.  The DPG renderer maps them to a 16-bin ASCII
  ramp (`"_.-^*"`) so the panel reads "scribbled across the page".
* Save: writes the tracks to `<scene_root>/<entity>.anim.yaml` with
  a minimal YAML emitter (no PyYAML dependency); fires `on_save(path)`.
* Tick contract: `tick(dt)` advances the playhead and respects
  `loop`; the editor shell calls it from the main loop.

---

## 4. EditorShell integration

`EditorShell.compose_default_panel_layout` registers the three new
panels as floating, hidden-by-default `MovablePanelWindow`s:

| Slot | Default size | Default pos | Visible default |
|---|---|---|---|
| `telemetry_panel` | 400×320 | right-edge, under toolbar | hidden |
| `post_process_panel` | 360×360 | right-edge, slightly lower | hidden |
| `animation_panel` | 520×320 | bottom-centre | hidden |

The panels are constructed in `setup_notebook_panels` so a caller can
inject a pre-built panel before `setup` runs (matches the pattern used
by `_toolbar` / `_scene_outliner` / `_inspector`).  Each construction is
wrapped in `try / except` so a missing dependency degrades to "panel
slot empty" instead of failing the editor boot.

Toggling: the panels expose a stable id (`telemetry_panel` /
`post_process_panel` / `animation_panel`) so a future View-menu entry
or hotkey can call `MovablePanelWindow.show()` / `.hide()` directly.

---

## 5. Test plan

| File | Test count | Covers |
|---|---|---|
| `test_editor_telemetry_panel.py` | 14 | Construct, subscribe / unsubscribe lifecycle, pause-drops, clear, filter (substring + fnmatch), pin / unpin, capacity trim, theme switch, build under stub DPG, status formatting |
| `test_editor_post_process_panel.py` | 13 | Construct, toggle pass, reorder up / down at boundaries, remove, add (factory + unknown name), preset replace, param set, status counts, theme switch, build under stub DPG |
| `test_editor_animation_panel.py` | 16 | Construct, add / remove / move keyframe, seek (clamp), play / pause toggle, loop, tick drives playhead, save round-trip, curve preview length, ruler glyphs, theme switch, bind_entity, build under stub DPG |

Tests stub `dearpygui.dearpygui` via the same `_StubDPG` pattern used by
`test_editor_notebook_welcome.py` (see the shared fixture in
`SlapPyEngineTests/tests/test_editor_notebook_welcome.py`).

---

## 6. Cross-links

* Sprint planning: [`sprint_plan_2026_06_03.md`](sprint_plan_2026_06_03.md)
* Feature map (per-subpackage status): [`feature_map_2026_06_03.md`](feature_map_2026_06_03.md)
* Nova3D → notebook pattern audit: [`ui_pattern_audit_2026_06_03.md`](ui_pattern_audit_2026_06_03.md)
* Editor user manual: [`notebook_editor_manual_2026_06_03.md`](notebook_editor_manual_2026_06_03.md)
* Post-process design: [`post_process_design.md`](post_process_design.md)
* Telemetry design: [`telemetry_design.md`](telemetry_design.md)
* Doc inventory tripwire: [`sprint_5_doc_inventory.md`](sprint_5_doc_inventory.md)
