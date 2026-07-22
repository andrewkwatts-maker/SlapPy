# Engine Feature Map — Delta Report (2026-07-07 → post-OO1)

Compact delta covering the OO1 STUB-triage sprint tick (round 16 after
NN2's round-15 ``view.frame_selected`` / ``view.reset_view`` /
``panel.dock_left`` / ``panel.dock_right`` / ``theme.hot_swap`` batch).

## OO1 STUB-triage patch (2026-07-07, round 16)

Five more action ids landed in this tick, moving 5 rows from STUB
(implicit — the ids were not yet registered on the router) to WIRED:

| Action id | Fallback module (`pharos_engine.actions.*`) | Category |
|-----------|--------------------------------------------|----------|
| `layer.solo`              | `layer_solo_actions.solo_layer`               | layer |
| `layer.merge_down`        | `layer_merge_down_actions.merge_down`         | layer |
| `selection.grow`          | `selection_grow_actions.grow_selection`       | selection |
| `snap.increase_grid_size` | `snap_grid_size_actions.increase_grid_size`   | snap |
| `snap.decrease_grid_size` | `snap_grid_size_actions.decrease_grid_size`   | snap |

New action modules:

* `python/pharos_engine/actions/layer_solo_actions.py`
* `python/pharos_engine/actions/layer_merge_down_actions.py`
* `python/pharos_engine/actions/selection_grow_actions.py`
* `python/pharos_engine/actions/snap_grid_size_actions.py`

Router entries and `_fb_*` shims live in
`python/pharos_engine/tool_router.py` under the
`# ── OO1 STUB-triage: layer solo + merge-down + selection grow + snap
grid-size increment / decrement (round 16) ──` block.

### Behavioural notes for OO1

* **`layer.solo`** — Photoshop / Krita / Nova3D Layer-panel "solo this
  layer" gesture. Hides every layer except the target, snapshotting
  the pre-solo visibility on `shell._solo_snapshot` (+ `_solo_target`)
  so a second call with the same target restores the previous state
  (matches Krita's toggle behaviour). Target resolution: `ctx["layer"]`
  → `shell._active_layer` → `scene.z_layers[-1]`. Return contract:
  `no_scene` / `no_layer` / `no_layers` / `soloed` (with `target`,
  `hidden` list) / `restored`.
* **`layer.merge_down`** — Photoshop / Krita `Ctrl+E` merge-down. Moves
  every entity from the source layer onto the layer immediately below
  (by `z` order), then removes the now-empty source. `shell._active_layer`
  is repointed at the merged destination so the inspector rebinds.
  Return contract: `no_scene` / `no_layer` / `no_layer_below` /
  `merged` (with `source_name`, `dest_name`, `moved` count).
* **`selection.grow`** — Blender `Ctrl+Numpad+` grow-selection. Walks
  the scene's entity roster, computes each candidate's Euclidean
  distance to the closest already-selected entity, and adds every
  entity within `ctx["radius"]` (default `64.0` scene units,
  overridable, min `> 0`, max `1e9`). Positions read via the
  `(position | origin | pos)` fallback chain (same as
  `edit_snap_pixel_actions`). Return contract: `no_scene` /
  `no_selection` / `unchanged` (nothing in range) / `grown` (with
  `selection`, `added`, `previous_count`, `radius`).
* **`snap.increase_grid_size`** / **`snap.decrease_grid_size`** —
  Blender numpad `+` / `-` while snap is active. Steps up / down one
  rung of a canonical geometric ladder
  (`0.5, 1, 2, 4, 8, …, 4096`) bounded to `[0.5, 4096]`. Current grid
  resolves via `ctx["grid_size"]` → `shell._snap_grid_size` →
  `shell._grid_size` → `shell.grid_size` → default `8.0`. Return
  contract: `stepped` (with `previous`, `new`, `direction`) or
  `at_limit` (already at min/max).

Regression tests: `SlapPyEngineTests/tests/test_actions_stub_triage_r16.py`
(29 tests, all passing) — combined with the r15 suite (31 tests) the
r15+r16 dispatch surface is exercised across **60 tests**.

## STUB roster unchanged

The 5 new WIRED rows are all NEW router entries — no previously-listed
STUB row (from the 13-row roster tracked in
`feature_map_delta_2026_07_06.md`) is affected. The DPG-shell-dependent
STUBs (HUD toggle, diary "Open…" file picker, inspector help popups,
theming save-as-new / import / export modals) remain untouched by OO1.

---

*Delta generated 2026-07-07 by OO1 STUB-triage agent (parallel-sprint
lane). Sources: `9406546` (r15 salvage baseline) + OO1 commit.*
