# Consolidation Sweep — 2026-06-07

Cleanup + structural-split pass across the editor UI subtree. No behavioural
changes; every public symbol still resolves; baseline notebook editor tests
(83 in the focused 3-file suite, 270 in the broader `editor_notebook` filter,
345 across notebook+spawn+material+button, 200 across theme+project+creature)
remain green.

## Scope

* **Phase 1 — survey:** Nova3D legacy callers, validation-shim re-exports,
  long-module audit, xfail audit.
* **Phase 2 — execute:** safe deletes are out (every Nova3D legacy file
  retains at least one test caller in tracked code), so we banner survivors
  and focus on structural splits of the two over-long notebook modules.
* **Constraint:** `softbody/` and `fluid/` left untouched per directive.

## Phase 1 findings

### Nova3D legacy retirement candidates

Every candidate module has at least one caller still in tracked code
(either production `engine.py` / `shell.py`, the legacy notebook siblings
which import them as compat shims, or the test suite). None are
delete-safe under the "no test pass-count regression" constraint:

| File | Production caller? | Test callers | Status |
| --- | --- | --- | --- |
| `toolbar.py` | no | 26 imports in `test_editor_panels_misc.py` | banner (already had) |
| `scene_outliner.py` | no | `test_editor_scene_outliner_dynamics.py`, `test_editor_selection_flow.py` | banner (already had) |
| `gizmo_overlay.py` | no | `test_editor_gizmo_viewport.py` | banner (already had) |
| `property_inspector.py` | yes (`notebook_inspector.py`, `notebook_material_editor.py`, `spawn_menu.py`) | many | banner (already had) |
| `theme.py` | indirect via `scene_outliner`/`toolbar` | several | banner (already had) |
| `material_editor.py` | yes (`notebook_material_editor.py` imports `MaterialPropertyAdapter`) | yes | **banner added** |
| `spawn_menu.py` | yes (`EditorShell` imports `SPAWN_ACTIONS`; `notebook_spawn_menu` lazy-imports spec dataclasses) | yes | **banner added** |
| `code_mode_panel.py` | yes (`EditorShell` line 1276) | yes | not legacy — live |
| `deform_panel.py` | no — already `raise ImportError` stub | — | already retired |

All survivors carry a `Legacy Nova3D reference. The shipping editor uses
notebook_* siblings — see docs/ui_pattern_audit_2026_06_03.md.` banner so a
future contributor doesn't accidentally extend them.

### Validation shim audit

The 24 `_*_validation.py` modules total 2002 LOC. The three smallest
(`zones/_validation.py` 19 LOC, `telemetry/_validation.py` 23 LOC,
`iso/_validation.py` 24 LOC) are already pure re-exports of
`pharos_engine._validation` with a module docstring + `__all__`. Collapsing
them to 1-line redirects would break the public re-export surface (each is
imported by `<subsystem>/__init__.py` for the names it lists in `__all__`).
The remaining 21 carry domain-specific validators (e.g. `validate_omega` in
`numerics`, `validate_diffusivity` in `thermal`, `validate_mat4_tuple` in
`post_process`) and are not slim-able further without behaviour loss.

**Action: no change.** The shim layer is already at its sustainable
minimum.

### Long-module audit (`>20k` bytes)

Top 10 by file size:

| LOC | File |
| --- | --- |
| 2982 | `physics/world.py` |
| 2199 | `ui/editor/shell.py` (before other agents landed +133) |
| 1955 | `physics/particle_gpu.py` |
| 1920 | `physics/particle_field.py` |
| 1391 | `softbody/render.py` (off-limits) |
| 1135 | `fluid/render.py` (off-limits) |
| 1119 | `engine.py` |
| 936 | `deform_modes.py` |
| 905 | `physics/hull.py` |
| 800 | `lighting.py` |

Notebook editor modules also above 800 LOC: `notebook_spawn_menu.py` (951)
and `notebook_inspector.py` (959) — picked as Phase 2 split targets per
the directive.

### Dead xfail tests

The collection step shows pre-existing `ERROR` entries in
`SlapPyEngineTests/python_tests/` (8 modules) and one
`SlapPyEngineTests/tests/test_all_demos_smoke.py` that fail to collect on
this branch — not a regression from this sweep. No xfail conversions
identified in the editor / theme / project / creature subset that was
tested green.

## Phase 2 — changes landed

### 1. Reference-only banners

Added `Legacy Nova3D reference. The shipping editor uses notebook_*
siblings — see docs/ui_pattern_audit_2026_06_03.md.` headers to:

* `python/pharos_engine/ui/editor/material_editor.py`
* `python/pharos_engine/ui/editor/spawn_menu.py`

The other six candidates already carried the banner from previous sweeps.

### 2. `notebook_spawn_menu.py` split

Extracted the 10 inline SVG portrait constants + the 500-byte budget
guard into a sibling module so the menu module focuses on
dispatch + lifecycle:

* New: `python/pharos_engine/ui/editor/notebook_spawn_menu_svgs.py` (146 LOC)
* `notebook_spawn_menu.py`: 951 → 844 LOC (−107)

The 10 portraits are re-imported with their original names so every
existing reference (`SPAWN_CARDS`, the byte-budget guard, the
`test_each_card_has_portrait_under_500_bytes` test) still works.

### 3. `notebook_inspector.py` split

Extracted:

* the 9 per-type `_render_<type>` methods (`_render_bool`, `_render_int`,
  `_render_float`, `_render_str`, `_render_path`, `_render_color`,
  `_render_float_tuple`, `_render_list_str`, `_render_list_int`,
  `_render_help_row`)
* the top-level `_render_field` dispatcher
* the helpers `_safe_dpg`, `_slider_range_for`, `_is_path_value`
* the slider-range table constants (`_SLIDER_RANGES`,
  `_DEFAULT_FLOAT_RANGE`)

into a sibling module exposing an `InspectorDispatchMixin` that
`NotebookInspector` now inherits:

* New: `python/pharos_engine/ui/editor/notebook_inspector_dispatch.py` (421 LOC)
* `notebook_inspector.py`: 959 → 624 LOC (−335)

The mixin attribute contract is documented at the top of the dispatch
module so subclassers know the required hooks (`_panel_tag`,
`_widget_map`, `_widgets`, `call_log`, `_make_callback`, `_write_back`,
`_add_help_button`).

## Metrics

| Metric | Before | After | Δ |
| --- | --- | --- | --- |
| `notebook_inspector.py` LOC | 959 | 624 | **−335** |
| `notebook_spawn_menu.py` LOC | 951 | 844 | **−107** |
| New dispatch module LOC | 0 | 421 | +421 |
| New svgs module LOC | 0 | 146 | +146 |
| Banner additions LOC | 0 | +15 | +15 |
| **Net editor-subtree LOC** (just my edits) | — | — | **+140** |
| Mega-module count (≥900 LOC) | 6 in editor dir | 4 in editor dir | **−2** |
| Files banner-marked legacy | 6 | 8 | +2 |
| `editor_notebook` test pass (baseline → post) | 270 | 270 | **0** |
| `notebook+spawn+material+button` pass (post) | — | 345 | — |
| `theme+project+creature` pass (post) | — | 200 | — |

The split adds ~140 LOC of file overhead (imports / docstrings /
`__all__`) but reduces the largest notebook module from 959 to 624 LOC,
breaks the two notebook mega-modules into 4 focused files, and brings
the per-type renderer surface (321 LOC of dispatch) into a single
module that future contributors can extend without reading
`notebook_inspector.py` end-to-end.

## Why no actual deletions

The strict deletion criterion ("any remaining import in tracked code"
counts tests as callers) means every Nova3D candidate has at least one
test sub-suite pinning it to disk. Deleting would drop the test pass
count, which the constraint forbids. The Reference-only banner approach
satisfies the "do not extend" intent without paying the test-suite cost.

A follow-up sweep that prunes the test suites pinned to each legacy file
would unlock ~3000 LOC of deletes (`toolbar.py` 217, `scene_outliner.py`
560, `gizmo_overlay.py` 693, `material_editor.py` 408, `theme.py` 270,
`spawn_menu.py` 470, `property_inspector.py` 609 minus the helpers that
`notebook_inspector` re-uses). That sweep is out of scope for this
ticket since the directive forbids a test pass-count drop.

## Files touched

```
M python/pharos_engine/ui/editor/notebook_inspector.py            (-335)
M python/pharos_engine/ui/editor/notebook_spawn_menu.py           (-107)
M python/pharos_engine/ui/editor/material_editor.py               (+8 banner)
M python/pharos_engine/ui/editor/spawn_menu.py                    (+7 banner)
A python/pharos_engine/ui/editor/notebook_inspector_dispatch.py   (+421)
A python/pharos_engine/ui/editor/notebook_spawn_menu_svgs.py      (+146)
A docs/consolidation_2026_06_07.md                               (this)
```

## Test verification

```
$ PYTHONPATH=python python -m pytest SlapPyEngineTests/tests/ \
    -k "editor_notebook or editor_material_editor or editor_spawn_menu or editor_button" -q
345 passed, 3923 deselected in 18.36s

$ PYTHONPATH=python python -m pytest SlapPyEngineTests/tests/ \
    -k "theme_switcher or theme_spec or project_picker or creature" -q
200 passed, 4090 deselected in 8.71s
```
