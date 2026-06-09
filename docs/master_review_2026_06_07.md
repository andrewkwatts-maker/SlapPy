# Master Review + Refactor Plan — SlapPyEngine (2026-06-07)

> Read-only review. No source edits accompany this document; the only
> companion change is the inventory entry under
> [`sprint_5_doc_inventory.md`](sprint_5_doc_inventory.md).
>
> This is the master roll-up of the 2026-06-03 feature map + sprint plan,
> reconciled with the in-flight Phase D physics WIP, the diary-themed
> editor reskin, the Nova3D-legacy retirement plan, and the new
> Arithma / Diary-Page-Script / Visual-Node directions decided at
> 2026-06-07.
>
> WIP-frozen perimeters (per memory note `project_sprint_2026_05_29.md`):
> `python/slappyengine/softbody/` and `python/slappyengine/fluid/` are not
> touched in any sprint defined below. References to those subpackages
> are read-only.

---

## 1. Executive summary

SlapPyEngine — June 2026 snapshot:

| Metric | Value | Source |
|---|---|---|
| Engine Python modules | 389 | `Get-ChildItem python/slappyengine -Filter *.py -Recurse` |
| Test modules | 228 | `Get-ChildItem SlapPyEngineTests/tests -Filter test_*.py -Recurse` |
| Subpackages mapped | 30 + 8 planned | [`feature_map_2026_06_03.md`](feature_map_2026_06_03.md) §1.1-1.5 |
| Top-level surface | 75 names across 19 subpackages | [`engine_surface_v030.md`](engine_surface_v030.md) |
| Docs (`docs/**/*.md`) | 70 markdown files | [`sprint_5_doc_inventory.md`](sprint_5_doc_inventory.md) |
| Notebook editor panels | 13 `notebook_*` modules | `Glob python/slappyengine/ui/editor/notebook_*.py` |
| Rust kernels landed | 18 (Tiers 1-10) | memory note `project_rust_migration_final_2026_05.md` |
| End-to-end perf | fluid 1176 fps / softbody 544 fps | memory note `project_rust_migration_final_2026_05.md` |
| Engine version | `0.3.0b0` (pre-v0.4) | `python/slappyengine/__init__.py` line 98 |

**State of play.** The engine has reached "engine-as-library" maturity:
all 12 ship-checklist milestones are complete; Rust migration delivered
the targeted 1000+ fps; the diary-themed editor reskin shipped 13
`notebook_*` panels; and three downstream games (Ochema Circuit / Bullet
Strata / Stone Keep) ride a locked 75-symbol top-level surface. Visible
gaps remain at three altitudes:

1. **Editor authoring surface** — 110+ widgets across the notebook panels
   but ~25 of them are still wired to no-op callbacks or stubbed
   handlers (counted from [`feature_map_2026_06_03.md`](feature_map_2026_06_03.md) §4.1).
   The biggest hole is the absence of a true visual node-graph canvas
   (material + script + shader).
2. **Symbolic math + script authoring** — `slappyengine.math` does not
   exist; animation curves, particle force fields, material node
   compilation, and IK target formulas each re-implement small
   arithmetic helpers in isolation. The sibling Rust-backed `arithma`
   package (`H:/Github/Arithma`, v2.0.3, PyO3 → `_arithma_core`)
   already ships the substrate to consolidate them.
3. **Long-tail consolidation** — `shell.py` has grown to 2689 lines
   (single largest non-Rust file in the engine); 12 editor modules
   are over 600 lines; Nova3D-legacy panels (`scene_outliner`,
   `property_inspector`, `material_editor`, `code_mode_panel`,
   `toolbar`, `gizmo_overlay`, `behavior_panel`, `anim_graph_panel`,
   `tag_painter`, `node_graph_panel`, `layer_panel`,
   `layer_lighting_panel`, `mesh_inspector`, `viewport_panel`,
   `spawn_menu`, `script_binding_panel`, `ollama_setup_modal`,
   `deform_panel`) sit alongside their notebook siblings ready for
   retirement once parity is signed off.

The remainder of this document specifies the architecture, ranks 20
concrete refactor targets, plans the Arithma integration, designs the
new Diary-Page Script Editor and Visual-Node scripting subsystem, and
sequences seven sprints to v0.4.

---

## 2. Architecture diagram

```
+--------------------------------------------------------------------+
|                     GAMES (downstream)                             |
|   Ochema Circuit  |  Bullet Strata  |  Stone Keep                  |
+--------------------------------------------------------------------+
                            |
                            | imports `slappyengine.*` (lazy __getattr__)
                            v
+--------------------------------------------------------------------+
|     PROJECT LIFECYCLE (slappyengine.projects + slappyengine.cli)   |
|       Project / SceneManifest / AssetManifest / ScriptBinding      |
|       first_run scaffold / docs_gen / build_gen / content_encrypt  |
+--------------------------------------------------------------------+
                            |
                            v
+--------------------------------------------------------------------+
|                       UI / AUTHORING (Python)                      |
|                                                                    |
|  +-----------------------------------+  +----------------------+   |
|  |       slappyengine.ui.editor      |  |  slappyengine.studio |   |
|  |  - EditorShell (2689 LOC -- big)  |  |  - Stage / record()  |   |
|  |  - 13 notebook_* panels           |  |  - softbody_stage    |   |
|  |  - 18 Nova3D-legacy panels        |  |  - fluid_stage       |   |
|  |  - DiaryPagePanel  (NEW Sprint 2) |  |  - humanoid_stage    |   |
|  |  - NodeGraphCanvas (NEW Sprint 3) |  +----------------------+   |
|  +-----------------------------------+                             |
|                                                                    |
|  +-----------------------------------+                             |
|  |       slappyengine.ui.theme       |  6 diary themes + creatures |
|  +-----------------------------------+                             |
|  +-----------------------------------+                             |
|  |       slappyengine.ui.widgets     |  29 notebook widgets         |
|  +-----------------------------------+                             |
+--------------------------------------------------------------------+
                            |
                            v
+--------------------------------------------------------------------+
|                    PYTHON SUBPACKAGES (engine surface)             |
|                                                                    |
|   Simulation     Rendering / GPU        Authoring / Integration    |
|   ----------     -----------------      ------------------------   |
|   dynamics       gpu                    studio                     |
|   topology       gi                     iso                        |
|   numerics       post_process           audio_runtime              |
|   zones          material               telemetry                  |
|   thermal        compute                testing                    |
|   softbody*      residency              animation                  |
|   fluid*                                ai                         |
|   physics                               ext                        |
|                                         net                        |
|                                         assets                     |
|                                         modules                    |
|                                         tools                      |
|                                                                    |
|   (NEW Sprint 1)                                                   |
|   math          <-- Arithma re-export + engine helpers              |
|                                                                    |
|   (NEW Sprint 3-5)                                                 |
|   scripting     <-- DiaryPage scripts (.diary.py) + node graph      |
|                     (.diary.nodes.yaml) + bidirectional codegen     |
|                                                                    |
|   * WIP-frozen until physics reconciliation sprint                 |
+--------------------------------------------------------------------+
                            |
                            v  (per-frame hot-path delegation)
+--------------------------------------------------------------------+
|                    RUST CORE (_core + arithma._arithma_core)       |
|                                                                    |
|   18 kernels under Tiers 1-10:                                     |
|   raster.rs   pbf_solver.rs    softbody_solver.rs   fluid_shader.rs |
|   _collide   _kinetic_relax   _thermal_step   _drill_through        |
|   _slide     _project_distance  ... (rust_port_audit_2026_06_02.md) |
|                                                                    |
|   (NEW Sprint 1) arithma._arithma_core                              |
|   Expression / Integer / Variable / simplify / evaluate             |
+--------------------------------------------------------------------+
                            |
                            v
+--------------------------------------------------------------------+
|                       PLATFORM (wgpu / OS)                         |
|        wgpu (Vulkan / Metal / DX12)   |   glfw   |   sounddevice    |
+--------------------------------------------------------------------+
```

Layer contracts:

* **Games → Project lifecycle** — games import the top-level surface
  via PEP 562 lazy `__getattr__` ([`__init__.py`](../python/slappyengine/__init__.py) line 411).
  No game touches Rust kernels directly.
* **Project lifecycle → UI / Authoring** — `Engine.run_editor()` boots
  `EditorShell`. YAML manifests drive everything dynamic; no panel
  ever hard-codes a scene path.
* **UI / Authoring → Python subpackages** — every editor panel
  implements `build(parent_tag)` and reads engine state by direct
  attribute access (per [`ui_pattern_audit_2026_06_03.md`](ui_pattern_audit_2026_06_03.md) §8).
* **Python → Rust** — hot paths route through PyO3 functions on
  `slappyengine._core`. The `HAS_NATIVE` flag at module import time
  decides whether a kernel takes the Python fallback path.
* **Rust → Platform** — wgpu is reached through the Python `wgpu`
  bindings, not directly from Rust today (decision deferred per
  [`tier_11_gpu_compute_discussion.md`](tier_11_gpu_compute_discussion.md)).

---

## 3. Subpackage health table

Status legend: **S** SHIPPED · **W** WORKING · **K** SKELETON · **G** GAP.
Refactor priority: **H** ship-blocker for v0.4 · **M** important but
not blocking · **L** carry-over to v0.5 / v1.0.

| Subpackage | Status | Tests | Doc | Refactor priority | Notes |
|---|---|---|---|---|---|
| `dynamics` | S | 167 | hand-authored design + quickstart | L | Locked; freeze candidate for v1.0 |
| `topology` | S | 20 | api ref | L | Stable |
| `numerics` | S | 24 | design doc | L | Stable |
| `zones` | S | 18 | design doc | L | Stable |
| `thermal` | S | 25 | api ref | L | Stable |
| `softbody` | W (FROZEN) | — | design doc | — | Out of scope every sprint below |
| `fluid` | W (FROZEN) | — | design doc | — | Out of scope every sprint below |
| `physics` | W (legacy) | scattered | physics_module.md | M | Phase D strip steps 6+ |
| `gi` | S | 16 files | design doc | L | Stable |
| `post_process` | S | 28 | design doc + presets | L | Stable |
| `material` | W | 59 | design + catalog | **H** | Sprint 4 deliverable — visual graph canvas |
| `gpu` | S | 26 | api ref | L | Stable |
| `compute` | S | 47 | api ref | L | Stable |
| `residency` | S | 43 | api ref | L | Stable |
| `studio` | S | 6 | design + quickstart | L | Stable |
| `iso` | S | 24 | api ref | M | No notebook-themed iso panel yet (deferred) |
| `audio_runtime` | W | 4 | api ref | M | Backend hardening pending |
| `telemetry` | S | 25 | design doc | L | Stable |
| `testing` | S | 16 | api ref | L | Stable |
| `animation` | W | 36 | api ref only | M | Sprint 3 prior plan; punted to v0.5 in favour of script editor |
| `ai` | W | scattered | **MISSING** | **H** | Need `docs/api/ai.md` and clear surface entry |
| `ext` | W | scattered | api ref | L | Compat shim, leave alone |
| `net` | K | 0 | **MISSING** | M | Defer v0.5 |
| `assets` | S | 22 | minimal | L | Stable |
| `modules` | K | 0 | none | L | Defer |
| `tools` | W | 15 | recipes | M | `sprite_audit` is hardened, other tools casual |
| `ui` | W | scattered | none top-level | M | Sub-modules below are the real story |
| `ui.theme` | S | 56 | 2 design docs | L | Stable |
| `ui.theme.creatures` | S | 82 | design doc | L | Stable |
| `ui.theme.themes` | S | 56 | design doc | L | Stable |
| `ui.widgets` | S | 58 | api ref | L | Stable |
| `ui.editor` | W | 162 + others | manual + audits | **H** | Sprints 2-7 all land here |
| `math` (NEW) | G | — | — | **H** | Sprint 1 deliverable — Arithma re-export + helpers |
| `scripting` (NEW) | G | — | — | **H** | Sprint 3 deliverable — diary page + node graph |
| `vfx` (planned) | G | — | — | M | Defer to v0.5 (Sprint plan 2026-06-03 §S5 moves out) |
| `ecs/` formalisation (planned) | G | — | — | M | Defer to v0.5 |
| `i18n` (planned) | G | — | — | L | v0.5 |
| `save_version` (planned) | G | — | — | M | v0.5 |
| `scene/loader` (planned) | G | — | — | L | v0.5 |
| Profiler overlay (planned) | G | — | — | M | v0.5 (depends on telemetry shipped) |
| Build pipeline UI (planned) | G | — | — | L | v0.5 |
| Input-remap UI (planned) | G | — | — | L | v0.5 |

The v0.4 ship focus tightens around four **H**-priority items: `math`,
`scripting`, the visual material graph (`material`), and an `ai` doc /
surface pass. Five **M** items (animation graph, audio backend,
profiler, iso editor, sprite tools polish) carry over to v0.5.

---

## 4. Top-20 refactor targets

Concrete, file-anchored, ranked by ROI / blast-radius. Lines cited
against the 2026-06-07 working tree.

### Tier H — ship-blocker for v0.4

1. **`python/slappyengine/ui/editor/shell.py` (2689 LOC) — split into
   four focused modules.**
   `EditorShell` mixes layout orchestration, hotkey dispatch, project
   lifecycle, theme management, and creature scheduler glue. Proposed
   split:
   * `shell.py` — class skeleton + `setup` / `run` (~700 LOC).
   * `shell_panels.py` — panel registry + dock zone wiring (~600 LOC).
   * `shell_hotkeys.py` — `_dispatch_editor_command` + hotkey routing
     ([shell.py:214-280](../python/slappyengine/ui/editor/shell.py#L214)) (~500 LOC).
   * `shell_lifecycle.py` — project pick / save / undo / play
     toggle (~700 LOC).
   No public API change; the import line is `from slappyengine.ui.editor.shell import EditorShell`.

2. **`shell._dispatch_editor_command` ([shell.py:214-280](../python/slappyengine/ui/editor/shell.py#L214))**
   — bare `except Exception: pass` on lines 228-229, 244-246, 261-263,
   268-270, 278-279. Each swallow leaves the user with no signal that
   a command failed. Replace with `_log_dispatch_error(cmd, exc)` that
   writes to a rolling diagnostic ring buffer surfaced in the status
   bar.

3. **`python/slappyengine/ui/editor/notebook_spawn_menu.py` (813 LOC) —
   wire the four dead cards.**
   Per [`feature_map_2026_06_03.md`](feature_map_2026_06_03.md) §4.1,
   the Point Light / Sun / Material / Particle Emitter cards fire
   `on_spawn(card_id, spec_dict)` into a shell with no handler.
   Add handlers in `shell.py` (or `shell_lifecycle.py` after split)
   that consume the spec dict and call the appropriate factory
   (`LightingSystem.add_point_light`, `Material.create_from_spec`, etc.).

4. **`python/slappyengine/material/node_material.py` — promote
   `NodeMaterial` from "runtime + factories" to "round-trippable graph".**
   Today's surface (20 names per
   [`feature_map_2026_06_03.md`](feature_map_2026_06_03.md) §1.2)
   has no `save_material` / `load_material`. Add YAML round-trip
   following the `dynamics.save_world` envelope, then the Sprint 4
   canvas can save its work.

5. **`python/slappyengine/animation/` — extract curve evaluation into
   `slappyengine.math.curves`.**
   `AnimationGraph.tick` / `ProceduralRig.tick` each implement small
   easing helpers. Once Sprint 1 lands, replace local easings with
   `slappyengine.math.curves.evaluate(curve, t)` so the same Arithma-
   backed evaluator drives animation, particle force fields,
   material node compilation, and IK target formulas.

### Tier M — important, not blocking v0.4

6. **`python/slappyengine/ui/editor/notebook_inspector.py` (843 LOC) —
   extract per-type field renderers.**
   `_render_field` dispatches on Python type. Each branch
   ([lines 530-770](../python/slappyengine/ui/editor/notebook_inspector.py#L530))
   is 20-50 LOC; the file is unreadable because of it. Move each
   branch to `field_renderers/{bool,int,float,str,path,color,list}.py`
   with a `FieldRenderer` protocol.

7. **`python/slappyengine/ui/editor/notebook_inspector.py` —
   replace the "[clip]" path picker stub
   ([line 644-669](../python/slappyengine/ui/editor/notebook_inspector.py#L644))
   with a real OS file dialog.** A single shared helper
   (`slappyengine.ui.editor.file_picker.pick_file(filters, parent)`)
   covers the Inspector path field AND the `ctrl+o` hotkey
   (item §8 of feature map 4.4).

8. **`python/slappyengine/ui/editor/notebook_hotkeys.py` BINDINGS
   ([lines 70-81](../python/slappyengine/ui/editor/notebook_hotkeys.py#L70))
   — route the 10 dead bindings.**
   `ctrl+y` / `ctrl+n` / `ctrl+o` / `f1` / `f3` / `f11` /
   `s` / `t` / `r` / `c` / `h` all dead-end into "cmd: …" status
   messages today. Wire each to a real shell handler (file dialog,
   help panel toggle, fullscreen toggle, profiler overlay toggle,
   tool selection, HUD toggle). Item §3 of feature map 4.4.

9. **`python/slappyengine/ui/editor/notebook_status_bar.py` —
   plumb `tick(dt)` / `set_world_cursor(x,y)` / `set_fps(fps)` from
   shell render loop.**
   Three setters exist on the bar
   ([lines 289-302](../python/slappyengine/ui/editor/notebook_status_bar.py#L289))
   but the shell doesn't pump them. Trivial fix; lights up the
   marginalia row. Item §2 of feature map 4.4.

10. **`python/slappyengine/ui/editor/notebook_code_panel.py` (769 LOC)
    — wire the `+ New` tab
    ([lines 521-545](../python/slappyengine/ui/editor/notebook_code_panel.py#L521))
    and the "Saved" footer
    ([lines 745-751](../python/slappyengine/ui/editor/notebook_code_panel.py#L745))
    to engine actions.** Both are local-bookkeeping stubs today.

11. **`python/slappyengine/ui/editor/notebook_gizmos.py` (731 LOC) —
    extract 3D-mode triad behind feature flag.**
    `set_mode("3D")` currently records the state and is ignored
    ([lines 422-452](../python/slappyengine/ui/editor/notebook_gizmos.py#L422)).
    Either implement (Sprint 7 polish) or document the gap in
    [`ui_pattern_audit_2026_06_03.md`](ui_pattern_audit_2026_06_03.md).

12. **`python/slappyengine/ui/editor/notebook_project_picker.py` (794 LOC)
    — split UI from project registry.**
    The picker mixes DPG layout with `~/.slappyengine/projects.yaml`
    registry IO. Extract `slappyengine.projects.registry` as a pure
    data module so the picker becomes presentation-only.

13. **`python/slappyengine/ui/editor/resize_handles.py` (744 LOC) +
    `dock_zones.py` (417 LOC) + `snap_manager.py` (283 LOC) +
    `movable_panel.py` (412 LOC) — consolidate as
    `slappyengine.ui.editor.docking/`.**
    Five files implement one feature (movable / dockable panels with
    snap + resize); they import each other in a brittle cycle. Move
    each to `docking/handles.py`, `docking/zones.py`, etc., with a
    single `docking/__init__.py` re-export.

14. **`python/slappyengine/ui/editor/layout_persistence.py` (619 LOC) —
    20 silent `pass` swallows
    ([lines 546-711](../python/slappyengine/ui/editor/layout_persistence.py#L546)).**
    Layout reads from `~/.slappyengine/layout.yaml`; every IO failure
    silently drops the layout. Replace with `logger.warning(...)`
    against `slappyengine.telemetry` so the user can see why their
    layout reverted.

15. **`python/slappyengine/ui/editor/notebook_material_editor.py` (642 LOC) —
    real radial-gradient preview
    ([lines 544-555](../python/slappyengine/ui/editor/notebook_material_editor.py#L544)).**
    Placeholder text token today. Use `dpg.draw_image` against a
    256×256 PIL render of the material onto a reference sphere — same
    pattern Sprint 4 needs for the visual graph preview pane.

### Tier L — carry-over to v0.5 / cleanup hygiene

16. **`python/slappyengine/_compat.py` — strip eight zero-caller
    aliases.** Per [`dead_code_audit_2026_06_02.md`](dead_code_audit_2026_06_02.md)
    `MaterialPreset` / `CrackMode` / `SimState` /
    `SimFrequencyBudget` / `DeformController` / `ZoneMap` /
    `CellMaterial` / `cell_material_for` resolve through `_LAZY_MAP` →
    `_compat.py` purely to satisfy the game-compat tripwire test. No
    direct `from slappyengine import` callers exist on master today.
    Migrate the tripwire to import from canonical homes; drop the
    aliases.

17. **`python/slappyengine/__init__.py` line 287
    ([_LAZY_MAP duplicate `CacheMode`](../python/slappyengine/__init__.py#L287))**
    — the duplicate key dates from a 2026-05 merge. Already flagged
    in [`dead_code_audit_2026_06_02.md`](dead_code_audit_2026_06_02.md).
    One-line fix.

18. **Nova3D-legacy panel retirement.**
    Eight notebook panels now ship with proven parity:
    `notebook_toolbar` / `notebook_outliner` / `notebook_inspector` /
    `notebook_gizmos` / `notebook_code_panel` / `notebook_spawn_menu` /
    `notebook_material_editor` / `notebook_content_browser`. Once
    Sprint 6 lands the visual-regression baselines, retire
    `toolbar.py` / `scene_outliner.py` / `property_inspector.py` /
    `gizmo_overlay.py` / `code_mode_panel.py` / `spawn_menu.py` /
    `material_editor.py` / `content_browser.py`.

19. **`python/slappyengine/physics/` — 36 modules under Phase D
    strip plan.** Per
    [`phase_d_strip_plan_2026_05_31.md`](phase_d_strip_plan_2026_05_31.md)
    steps 6+, gated on Ochema Circuit CI greenness. Sprint 6
    consolidation sweep will walk the remaining cuts.

20. **`python/slappyengine/ai/` (6 modules) — add
    `docs/api/ai.md` + top-level surface entry for `ScriptGenerator`.**
    Per [`feature_map_2026_06_03.md`](feature_map_2026_06_03.md) §1.3
    the `ai` subpackage works but has no doc and no surface entry.
    Hand-author per `docs/api/_template.md`.

---

## 5. Consolidation candidates

### 5.1 Duplicate validators

`python/slappyengine/compute/_validation.py` exists alongside scattered
validation helpers in `dynamics/_validation.py`, `assets/_validation.py`,
and `post_process/_validation.py`. Each validates similar shapes
(positive int, range, dtype). Consolidate as
`slappyengine._common/validation.py` with `require_positive`,
`require_range`, `require_dtype`, `require_shape`. Each subpackage's
shim re-exports for back-compat.

### 5.2 Duplicate widget patterns

The notebook panels each open with the same boilerplate:

```
import dearpygui.dearpygui as dpg
from slappyengine.ui.theme import get_active_theme
from slappyengine.ui.widgets import StickerButton, WashiPanel
...
def __init__(...):
    self._panel_tag = f"{cls_name}_panel_{id(self)}"
    self._theme_handle = None
    self._call_log: list = []
```

Extract a `NotebookPanelBase` mixin under
`slappyengine.ui.editor.notebook_panel_base.py`. Eight panels would
shed ~40 LOC each (~320 LOC saved).

### 5.3 Spec-modal pattern

`NotebookSpawnMenu` opens a modal containing a `NotebookInspector`
bound to a spawn-spec dataclass. The same pattern would serve:

* New "Save material as…" modal (Sprint 4).
* New "Save effect as…" modal (Sprint 5 deferred to v0.5).
* New "Create script…" modal (Sprint 2 — DiaryPagePanel new-script).

Extract `slappyengine.ui.editor.spec_modal.open_spec_modal(spec, on_ok)`.

### 5.4 Dead Nova3D fallbacks ready for retirement

| Module | Notebook replacement | Retire when |
|---|---|---|
| `toolbar.py` | `notebook_toolbar.py` | Sprint 6 |
| `scene_outliner.py` | `notebook_outliner.py` | Sprint 6 |
| `property_inspector.py` | `notebook_inspector.py` | Sprint 6 |
| `gizmo_overlay.py` | `notebook_gizmos.py` | Sprint 6 |
| `code_mode_panel.py` | `notebook_code_panel.py` | Sprint 6 |
| `spawn_menu.py` | `notebook_spawn_menu.py` | Sprint 6 |
| `material_editor.py` | `notebook_material_editor.py` | Sprint 6 |
| `content_browser.py` | `notebook_content_browser.py` | Sprint 6 |
| `deform_panel.py` | (already raises `ImportError`) | Sprint 6 — file deletion |
| `behavior_panel.py` | (none yet — defer) | v0.5 |
| `anim_graph_panel.py` | (none yet — defer) | v0.5 |
| `tag_painter.py` | (none yet — defer) | v0.5 |
| `node_graph_panel.py` | replaced by Sprint 3 backbone | Sprint 5 |
| `layer_panel.py`, `layer_lighting_panel.py`, `mesh_inspector.py`, `viewport_panel.py`, `script_binding_panel.py`, `ollama_setup_modal.py` | wrapped in `MovablePanelWindow` per commit `1681014` — keep as wrappers | — |

### 5.5 Duplicate `pass` clusters in editor

Survey: 50+ bare `pass` statements across editor modules (count via
`Grep "^\s*pass\s*$" python/slappyengine/ui/editor/`). The biggest
clusters are `layout_persistence.py` (20), `movable_panel.py` (8),
`dock_zones.py` (5), `notebook_gizmos.py` (4),
`layer_lighting_panel.py` (5), `code_mode_panel.py` (5). Each is a
silent exception swallow on a try/except wrapping a DPG call. Sprint 6
sweep: replace every `try ... except: pass` with
`try ... except Exception as exc: _swallow(exc, where=__name__)` so
diagnostics land in the telemetry bus.

---

## 6. Arithma integration plan

### 6.1 Sibling-project context

`H:/Github/Arithma` (package name `arithma`, version `2.0.3`,
distribution `arithma` on PyPI) is a Rust-backed symbolic mathematics
engine with the following surface (per
[`H:/Github/Arithma/python/arithma/__init__.py`](file://H:/Github/Arithma/python/arithma/__init__.py)):

* `Expression` — symbolic expression tree node.
* `Integer` — exact integer literal wrapper.
* `Variable` — free variable bound at evaluation time.
* `is_rust_backend()` — `True` iff `_arithma_core` (PyO3 extension)
  imported.
* `version_rust()` — Rust crate version string.

Build backend: maturin; PyO3 extension `arithma._arithma_core`; same
soft-import shim pattern SlapPyEngine uses for `_core`. Wheel publishes
to PyPI under `arithma`.

### 6.2 pyproject.toml change

Add the math extra to `[project.optional-dependencies]`:

```toml
math = [
    "arithma>=2.0.2,<3.0",
]
```

The extra is opt-in; the engine never hard-imports `arithma`, so
existing installs and headless CI runs keep their existing footprint.

### 6.3 New `slappyengine.math` subpackage

Layout:

```
python/slappyengine/math/
    __init__.py        # public surface; soft-imports arithma
    formula.py         # high-level formula evaluator (vectors / matrices)
    curves.py          # curve evaluation backed by Expression
    vector.py          # numpy-friendly vector helpers (no arithma needed)
    matrix.py          # numpy-friendly matrix helpers (no arithma needed)
    arithma_compat.py  # graceful-degrade shims when arithma absent
```

Surface (`__all__`):

```
"HAS_ARITHMA",
"Expression",     # re-exported from arithma when available
"Integer",        # re-exported from arithma when available
"Variable",       # re-exported from arithma when available
"Curve",          # engine-specific wrapper over Expression for time t
"Formula",        # engine-specific wrapper bundling vars + expression
"evaluate",       # evaluate(Curve | Formula, t=...) -> float
"vector_dot", "vector_cross", "vector_norm",   # numpy helpers
"matrix_mul", "matrix_inverse", "matrix_det",  # numpy helpers
"parse_formula",  # parse_formula("a*x + b") -> Formula
```

### 6.4 Engine consumers

Replace local arithmetic with `slappyengine.math` calls:

| Caller | What it does today | After Sprint 1 |
|---|---|---|
| `animation.AnimationGraph._eval_curve` | Inline easing helper | `slappyengine.math.curves.evaluate(curve, t)` |
| `animation.ProceduralRig.tick` | Local sin / lerp | `slappyengine.math.curves` |
| `particles.GpuParticleSystem.apply_force_field` | Hard-coded gravity / drag formulas | `Formula` parsed once at load |
| `material.node_material._compile_node_graph` | Manual arithmetic on `Add` / `Multiply` / `Lerp` / `Clamp` nodes | `Expression` simplification + codegen |
| `dynamics.solve_ik` target formulas | Hand-coded targeting | `Formula("...")` per-target |

### 6.5 Soft-import contract

Same pattern as `audio_runtime`:

```python
# python/slappyengine/math/__init__.py
try:
    from arithma import Expression, Integer, Variable, is_rust_backend
    HAS_ARITHMA = is_rust_backend()
except ImportError:
    HAS_ARITHMA = False
    class _MissingArithma:
        def __init__(self, *_a, **_kw):
            raise ImportError(
                "slappyengine.math advanced features require the [math] extra: "
                "pip install slap-py-engine[math]"
            )
    class Expression(_MissingArithma): ...
    class Integer(_MissingArithma): ...
    class Variable(_MissingArithma): ...
```

Engine consumers must accept the missing case — `Curve` falls back to
`numpy.interp`, `Formula` falls back to Python `eval` against a
namespace-restricted globals dict.

### 6.6 Tests + docs

* `SlapPyEngineTests/tests/test_math_arithma_integration.py` — soft-import
  test, `HAS_ARITHMA` invariant, formula round-trip when extra
  installed, fallback behaviour when absent.
* `SlapPyEngineTests/tests/test_math_curves.py` — `Curve` round-trip,
  evaluation parity vs numpy.
* `docs/math_design.md` — design doc.
* `docs/api/math.md` — hand-authored API ref.
* CHANGELOG entry under v0.4 — "Added `slappyengine.math` (optional
  Arithma backend)".

---

## 7. Diary Page Script Editor design

### 7.1 Pitch

The diary metaphor extends from "the editor IS a diary" to "every
script IS a diary page". Open a script and you get a two-page spread:
the LEFT page is a live viewport rendering whatever the script
produces (an entity, a particle effect, a procedural shader, a UI
widget); the RIGHT page is the script source (Python OR a visual node
graph; toggle button at the spine of the spread).

### 7.2 Layout

```
+-----------------------------------------+-----------------------------------------+
|  WASHI TAPE HEADER STRIP  ~  script_name.diary.py                                |
|  (sticker corner)                       (spine: toggle "Code / Nodes" button)    |
+-----------------------------------------+-----------------------------------------+
|                                         |                                         |
|         LIVE VIEWPORT                   |         CODE  /  NODE GRAPH             |
|         (paper background)              |         (dot-grid paper)                |
|                                         |                                         |
|   * renders the script's output         |   * code mode:                          |
|     in real time                        |     - syntax-highlighted Python         |
|   * reload on save (Ctrl+S)             |     - handwritten-font comments         |
|   * 60 fps target                       |     - inline render hints               |
|                                         |   * node mode:                          |
|                                         |     - washi-tape node graph             |
|                                         |     - drag-and-drop                     |
|                                         |                                         |
+-----------------------------------------+-----------------------------------------+
|  STATUS RIBBON  ~  Saved 12:34   |   Reloaded in 87 ms   |   3 nodes   |   <3    |
+-----------------------------------------+-----------------------------------------+
```

### 7.3 Style

* **Washi-tape header strip** — 64×64 nine-slice (already shipped under
  `ui.theme`); decorated with the script's filename and a sticker
  corner (`add_sticker_corner` from `ui.widgets`).
* **Paper background** — `ruled_paper(...)` for the live viewport;
  `dot_grid(...)` for the code / node side. Both are already shipped
  procedural shader effects under `slappyengine.ui.theme`.
* **Handwritten font** — already shipped via `theme_teengirl_notebook`
  (Patrick Hand / Caveat).
* **Status ribbon** — reuses `NotebookStatusBar` pattern; per-script
  scope.

### 7.4 File format

* `.diary.py` — plain Python script with a small header comment
  carrying viewport hints:
  ```python
  # diary: viewport=2d, target=particles, fps=60
  from slappyengine import GpuParticleSystem
  ...
  ```
* `.diary.nodes.yaml` — companion file authored from the node graph
  panel. When both exist, the editor opens with the node graph
  active; Python toggle re-generates the `.py` from the YAML.

### 7.5 Hot-reload contract

* On `Ctrl+S` (or auto-save 1 s after edit), the engine reloads the
  script through `importlib.reload` and re-binds the viewport target.
* If the reload raises, the previous frame stays on the viewport and
  the status ribbon shows the exception in italics.
* The editor uses `slappyengine.ai.CodeSyncWatcher` (already shipped)
  for the watcher infrastructure.

### 7.6 Lifecycle hooks

The diary script can implement any of:

```python
def setup(engine): ...        # called once at load
def tick(engine, dt): ...     # called every frame
def render(viewport): ...     # called for the LHS viewport pane
def shutdown(engine): ...     # called at script unload
```

All four are optional; the engine probes via `hasattr` at load time.

### 7.7 Implementation surface (Sprint 2 deliverable)

```
python/slappyengine/ui/editor/diary_page_panel.py    # ~600 LOC
python/slappyengine/scripting/diary_loader.py        # ~250 LOC
python/slappyengine/scripting/diary_viewport.py      # ~200 LOC
python/slappyengine/scripting/__init__.py            # ~50 LOC surface
```

Tests:

* `test_diary_loader.py` — round-trip `.diary.py`; reload semantics;
  failure-mode display.
* `test_diary_viewport.py` — viewport binding; lifecycle hooks called.
* `test_diary_page_panel.py` — headless panel boot + tab toggle +
  Ctrl+S save + reload.

Sprint 2 ships Code-side only; node graph integration lands in
Sprint 3.

---

## 8. Visual node scripting design

### 8.1 Pitch

Every node maps 1:1 to a Python statement OR a HLSL/WGSL line. There
is no "node engine" beneath the graph — the graph IS the
representation, and Python / HLSL are the serialisation formats. This
makes round-tripping (Sprint 4 deliverable) tractable.

### 8.2 Visual style

* Nodes are **sticker cards** (`StickerButton` 96×64 nine-slice from
  `ui.widgets`).
* Connections are **washi-tape ribbons** drawn between port circles.
* Node categories use category-coloured washi tape:
  * Math (pink) — backed by Arithma when extra installed.
  * Logic (yellow) — pure Python boolean ops.
  * Flow (mint) — if / for / while; Python only.
  * IO (cream) — file / network / engine state read/write.
  * Render (violet) — HLSL / WGSL emit nodes.
  * Audio (peach) — `audio_runtime` integration.
* Drag-and-drop with snap-to-grid (re-use `dock_zones` snap math).

### 8.3 Backend data model

```python
@dataclass
class Node:
    id: str
    kind: str                       # "math.add", "render.uv", etc.
    position: tuple[float, float]   # canvas coords
    params: dict[str, Any]          # static values
    inputs: dict[str, PortRef]      # port name -> upstream NodeRef.port
    title: str = ""                 # display override

@dataclass
class PortRef:
    node_id: str
    port_name: str

@dataclass
class NodeGraph:
    nodes: dict[str, Node]
    output_node: str                # which node's outputs drive the result
    target: str                     # "python" | "wgsl" | "hlsl"
```

YAML envelope (one `.diary.nodes.yaml` per graph):

```yaml
schema_version: 1
target: python
nodes:
  uv_0:
    kind: render.uv
    position: [100, 200]
    params: {}
    inputs: {}
  add_0:
    kind: math.add
    position: [300, 200]
    params: {}
    inputs:
      a: {node_id: uv_0, port_name: u}
      b: {node_id: uv_0, port_name: v}
output_node: add_0
```

### 8.4 Node palette (Sprint 3 — 20 starter kinds)

| Category | Kinds (20 total) |
|---|---|
| Math (5) | `math.add`, `math.multiply`, `math.lerp`, `math.clamp`, `math.formula` (Arithma) |
| Logic (3) | `logic.and`, `logic.or`, `logic.not` |
| Flow (3) | `flow.if`, `flow.for`, `flow.while` |
| IO (3) | `io.read_attr`, `io.write_attr`, `io.event_emit` |
| Render (4) | `render.uv`, `render.pixel_color`, `render.sample_texture`, `render.final_color` |
| Audio (2) | `audio.play`, `audio.stop` |

Each kind exposes:

```python
class NodeKind:
    name: str                                  # "math.add"
    inputs: list[Port]                         # name + type
    outputs: list[Port]
    params: list[Param]
    def to_python(self, node: Node, ctx) -> str: ...
    def to_wgsl(self, node: Node, ctx) -> str | None: ...
    def to_hlsl(self, node: Node, ctx) -> str | None: ...
```

### 8.5 Bidirectional codegen

**Graph → Python** (Sprint 4 — single direction):

* Walk nodes in topological order.
* Each node emits its `to_python(...)` string.
* Wrap in a `.diary.py` with the diary header comment.

**Python → Graph** (Sprint 4 — best-effort):

* Parse the `.diary.py` via `ast`.
* For each statement, attempt to match against the inverse of the
  emit table. Two outcomes per statement:
  * **roundtrippable** — produces a `Node`.
  * **opaque** — produces a single `python.opaque` node containing
    the source text as a param; preserved verbatim on next emit.

The `python.opaque` escape hatch is load-bearing: it preserves
comments, custom imports, and unsupported syntax without losing data.
Tests cover the round-trip parity for the 20 supported kinds; opaque
nodes are tested for verbatim preservation.

### 8.6 Material graph reuse (Sprint 5)

The Sprint 5 visual material graph extends the Sprint 3 backbone:

* New target string `"wgsl"` and `"hlsl"`.
* New nodes under Render: `render.noise`, `render.remap`,
  `render.step`, `render.smoothstep`, `render.fresnel` (the five
  Sprint 4 deliverables from the prior sprint plan).
* Output node implements `to_wgsl()` to emit a complete shader.
* Live preview pane reuses the Sprint 4 preview pane (item §15 of
  refactor target table).

### 8.7 Test plan

* `test_node_graph_serialize.py` — YAML round-trip every kind in the
  20-node palette.
* `test_node_graph_topological.py` — DAG validation; cycle detection.
* `test_node_graph_to_python.py` — codegen produces parseable Python.
* `test_node_graph_from_python.py` — round-trip parity for the 20
  kinds + verbatim preservation of `python.opaque`.
* `test_node_graph_to_wgsl.py` — codegen for `render.*` nodes
  produces compilable WGSL.

---

## 9. Seven-sprint execution plan

One sprint per calendar week, mapping to v0.4.

### Sprint 1 — Arithma integration + `slappyengine.math` subpackage

**Goal:** ship the math substrate that subsequent sprints all read.

**Deliverables.**
* `python/slappyengine/math/` subpackage per §6.3.
* `pyproject.toml` `[math]` extra per §6.2.
* Top-level `__init__.py` lazy entry for `math` subpackage.
* `docs/math_design.md`, `docs/api/math.md`.
* Test suite per §6.6.
* Refactor target #5: migrate `animation` curves onto
  `slappyengine.math.curves`.

**Dependencies.** None on prior sprints. Reads Arithma 2.0.2+.

**Estimated LOC:** +1100 (~500 math subpackage, ~250 migration,
~250 tests, ~100 docs).

**Risk.** Arithma soft-import contract must work without the extra
installed (engine cannot hard-require `arithma`). Mitigation: every
public name in `slappyengine.math` has a fallback path tested without
arithma installed.

### Sprint 2 — Diary Page Script Editor (code-only)

**Goal:** ship the Diary Page Panel with LHS viewport + RHS code (no
node graph yet); hot-reload on save.

**Deliverables.**
* `python/slappyengine/ui/editor/diary_page_panel.py` per §7.7.
* `python/slappyengine/scripting/` new subpackage.
* `.diary.py` file format + `setup` / `tick` / `render` / `shutdown`
  lifecycle.
* `Ctrl+S` reload through `CodeSyncWatcher`.
* Refactor target #1: split `shell.py` into four focused modules.
* Refactor target #9: status bar `tick(dt)` + `set_world_cursor` +
  `set_fps` plumbing (the Diary Page status ribbon reuses the same
  pump).

**Dependencies.** Sprint 1 (`slappyengine.math` for any in-script
formula); refactor target #1 must land first to make shell space for
the new panel.

**Estimated LOC:** +1800 (~1100 panel + scripting + shell split,
~400 tests, ~300 docs).

**Risk.** Hot-reload of a script that has bound to GPU resources can
leak; mitigation is mandatory `shutdown` hook + ref-counted resource
manager (already exists in `slappyengine.residency`).

### Sprint 3 — Node graph backbone

**Goal:** ship the visual node graph data model, YAML serialization,
canvas, and a minimal 20-node palette. No bidirectional codegen yet.

**Deliverables.**
* `python/slappyengine/scripting/nodes/` package — `Node`, `NodeGraph`,
  `NodeKind`, `Port`, 20 starter kinds per §8.4.
* `python/slappyengine/ui/editor/node_graph_canvas.py` — drag-and-drop
  canvas, washi-tape connections, sticker-card nodes, snap-to-grid.
* `.diary.nodes.yaml` round-trip.
* Refactor target #13: consolidate docking helpers (the canvas reuses
  snap math).
* Refactor target #6: extract notebook_inspector field renderers
  (node param editing reuses the renderer pattern).

**Dependencies.** Sprint 2 (Diary Page Panel hosts the canvas in the
"Nodes" tab); Sprint 1 (`math.formula` Arithma node).

**Estimated LOC:** +2000 (~1200 nodes + canvas, ~500 tests, ~300 docs).

**Risk.** DearPyGui has no first-class node-graph widget. Decision per
[`sprint_plan_2026_06_03.md`](sprint_plan_2026_06_03.md) S4 risk
callout: hand-roll over `drawlist` rather than add `dearpygui-imnodes`.
Re-use the gizmo-overlay drawlist pattern.

### Sprint 4 — Python ↔ Node bidirectional codegen

**Goal:** ship the graph→Python and Python→graph round-trip.

**Deliverables.**
* `to_python()` for every node kind per §8.5.
* `python_to_graph()` parser with `python.opaque` escape hatch.
* "Switch to Python" / "Switch to Nodes" buttons in the Diary Page
  Panel spine.
* Refactor target #4: `NodeMaterial` YAML round-trip (uses the same
  YAML envelope as the node graph for consistency).
* Refactor target #7 + #10: file picker + code panel actions.

**Dependencies.** Sprint 3 (node graph backbone).

**Estimated LOC:** +1600 (~900 codegen + parser, ~500 tests,
~200 docs).

**Risk.** Round-trip parity for non-trivial Python is the hard problem.
Mitigation: the 20 starter kinds are deliberately scoped to a
straight-line subset of Python; anything else routes through
`python.opaque` and round-trips verbatim. Tests pin the parity
contract.

### Sprint 5 — HLSL / WGSL visual nodes (material graph editor)

**Goal:** extend the Sprint 3 backbone with shader-emitting nodes;
ship the visual material editor as a `NodeGraph(target="wgsl")`
specialisation.

**Deliverables.**
* New Render nodes: `render.noise` (perlin), `render.remap`,
  `render.step`, `render.smoothstep`, `render.fresnel` per §8.6.
* `to_wgsl()` codegen per `NodeKind`.
* Live preview pane in `NotebookMaterialEditor` — 256×256 render of
  the compiled shader against a reference sphere/plane.
* "Save as material" toolbar action → `.material.diary.nodes.yaml`.
* Refactor target #15: real radial-gradient preview.

**Dependencies.** Sprint 3 (backbone), Sprint 4 (codegen pattern).

**Estimated LOC:** +1500 (~700 shader nodes + WGSL emit, ~400 preview,
~250 tests, ~150 docs).

**Risk.** Preview pane shares GPU context with the main viewport;
re-entrant guard needed. Pattern already proven in `slappyengine.gpu`.

### Sprint 6 — Consolidation sweep

**Goal:** retire Nova3D-legacy panels; consolidate validators / widget
boilerplate; sweep `pass` swallows.

**Deliverables.**
* Retire 8 Nova3D legacy panels per §5.4.
* `NotebookPanelBase` mixin per §5.2.
* `slappyengine._common/validation.py` per §5.1.
* Replace 50+ bare `pass` swallows with `_swallow(exc, where=...)`
  per §5.5.
* Refactor targets #2 (silent exception handlers), #8 (hotkey
  routing), #11 (gizmo 3D mode docs), #12 (project picker split),
  #14 (layout_persistence warnings), #16-19 (dead code, duplicate
  `CacheMode`, `_compat` strip, Phase D physics).

**Dependencies.** Sprints 2-5 (visual parity required before
retirement).

**Estimated LOC:** -2500 (net negative — retirements outweigh new
mixin / validator surface).

**Risk.** Game-compat tripwire breakage. Mitigation: extend
`test_game_compat_tripwire.py` per retired symbol before deletion;
keep the v0.3 surface a strict subset of v0.4.

### Sprint 7 — Missing-UI audit completion + polish + release

**Goal:** close every dead button identified in
[`feature_map_2026_06_03.md`](feature_map_2026_06_03.md) §4.1 that
wasn't picked up by sprints 1-6; ship v0.4.

**Deliverables.**
* Refactor targets #3 (spawn menu light / material / emitter
  handlers), #20 (`docs/api/ai.md`).
* Bump `__version__` to `0.4.0b0`.
* `docs/api/_template.md` conformance for every new doc.
* CHANGELOG `0.4.0` entry.
* Refresh `docs/engine_surface_v030.md` → `engine_surface_v040.md`.
* New ship checklist `docs/sprint_7_ship_checklist_v04.md`.

**Dependencies.** All prior sprints.

**Estimated LOC:** +1000 (~400 missing-UI wiring, ~300 docs,
~300 tests).

**Risk.** Doc inventory tripwire breakage. Mitigation:
`docs/sprint_5_doc_inventory.md` gets a deliberate sweep at end of
each sprint, not deferred to Sprint 7.

### Aggregate

| Sprint | LOC delta | New docs | New tests |
|---|---|---|---|
| 1 — Arithma + math | +1100 | 2 | 3 |
| 2 — Diary Page (code) | +1800 | 2 | 4 |
| 3 — Node graph backbone | +2000 | 2 | 5 |
| 4 — Python ↔ Node | +1600 | 1 | 5 |
| 5 — Material graph | +1500 | 1 | 4 |
| 6 — Consolidation | -2500 | 1 | 6 |
| 7 — Ship | +1000 | 3 | 5 |
| **Total** | **+6500** | **12** | **32** |

---

## 10. Risk callouts + dependencies

### 10.1 Sprint dependency graph

```
   Sprint 1 (math)
        |
        +--> Sprint 2 (diary code)
        |        |
        |        +--> Sprint 3 (node backbone)
        |               |
        |               +--> Sprint 4 (codegen)
        |                       |
        |                       +--> Sprint 5 (shader nodes)
        |                               |
        |                               +--> Sprint 6 (sweep)
        |                                       |
        |                                       +--> Sprint 7 (ship)
        +-------------------------------------------+
                       (math used by all)
```

Hard ordering: 1 → 2 → 3 → 4 → 5 → 6 → 7. Sprint 6 can soft-overlap
Sprint 7 (different file sets).

### 10.2 Top-5 risks (rolled up)

1. **Soft-import discipline.** Arithma is opt-in; any consumer that
   forgets to handle the missing case breaks headless CI. Mitigation:
   every `slappyengine.math` consumer has a fallback path; CI runs
   without `[math]` extra installed on at least one matrix entry.

2. **Hot-reload resource leaks.** Diary scripts may bind GPU
   resources. Sprint 2 mandates a `shutdown` lifecycle hook + ref-
   counted resource manager.

3. **Round-trip parity (Python ↔ Node).** Anything beyond the 20
   starter kinds risks data loss. Mitigation: the `python.opaque`
   escape hatch + a parity test that round-trips a corpus of real
   `.diary.py` files.

4. **Game-compat tripwire breakage during Sprint 6 retirement.** The
   54 + 1124 + Stone Keep pinned imports must stay green at every
   commit. Mitigation: each retirement lands as one commit per
   panel, tripwire-extended-then-deleted in that single commit.

5. **DearPyGui ceiling.** Sprint 3's node canvas is hand-rolled over
   drawlists because DPG has no node-graph widget. If hit-testing
   or repaint cost becomes the bottleneck on large graphs (>200
   nodes), fall back to viewport coalescing per the
   `WoodlandScheduler` budget pattern from
   [`ui_pattern_audit_2026_06_03.md`](ui_pattern_audit_2026_06_03.md) §2.

### 10.3 Out-of-scope perimeters

These items appear in the prior 2026-06-03 sprint plan but are
deliberately deferred to v0.5 to make room for the math /
script / node work:

* **ECS formalisation.** Existing `Component` Protocol + `ComponentBase`
  remain; no scheduler / sparse-set storage. Re-evaluate after Sprint 7.
* **Animation blend tree + IK retargeting + GLTF / FBX import.**
  `animation` subpackage stays at "graph + procedural rig" surface;
  `slappyengine.math.curves` consolidates the easing helpers but no
  new evaluators land.
* **VFX system (`slappyengine.vfx`).** `particles.py` continues
  serving; no `Effect` / `Emitter` / `ForceField` / `Curve`
  high-level API.
* **Profiler overlay.** `telemetry` ships events; no F3 flame graph.
* **i18n, save versioning, scene loader, build pipeline UI,
  input-remap UI.** All v0.5.
* **Network subpackage hardening.** `net` stays SKELETON.

These deferrals are deliberate; the v0.4 ship focuses on the
visual authoring story (Diary Page + node graph + Arithma) so the
later sprints land on a richer foundation.

---

## 11. Cross-links

* [`feature_map_2026_06_03.md`](feature_map_2026_06_03.md) — 30-subpackage
  map + 110-widget audit (source for §3, §4).
* [`sprint_plan_2026_06_03.md`](sprint_plan_2026_06_03.md) — earlier
  7-sprint plan (this doc supersedes for v0.4 prioritisation).
* [`roadmap.md`](roadmap.md) — near / mid / long-term roadmap.
* [`ui_pattern_audit_2026_06_03.md`](ui_pattern_audit_2026_06_03.md) —
  per-panel Nova3D → woodland contract.
* [`notebook_editor_manual_2026_06_03.md`](notebook_editor_manual_2026_06_03.md)
  — user-facing notebook editor manual.
* [`theme_diary_family_2026_06_03.md`](theme_diary_family_2026_06_03.md)
  + [`theme_teengirl_notebook_2026_06_03.md`](theme_teengirl_notebook_2026_06_03.md)
  — diary theme family design.
* [`dead_code_audit_2026_06_02.md`](dead_code_audit_2026_06_02.md) —
  source for §5.4 retirement candidates + refactor targets #16-#17.
* [`core_engine_audit_2026_06_02.md`](core_engine_audit_2026_06_02.md) —
  source for the `_compat`-routed symbol map.
* [`phase_d_strip_plan_2026_05_31.md`](phase_d_strip_plan_2026_05_31.md)
  — source for refactor target #19.
* [`engine_surface_v030.md`](engine_surface_v030.md) — locked v0.3
  top-level surface (75 names).
* [`sprint_5_doc_inventory.md`](sprint_5_doc_inventory.md) — this doc
  is indexed there.
* `H:/Github/Arithma/pyproject.toml` + `H:/Github/Arithma/python/arithma/__init__.py`
  — Arithma surface for §6.
