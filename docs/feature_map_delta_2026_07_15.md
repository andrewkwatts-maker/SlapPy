# Engine Feature Map — Delta Report (2026-07-15 → post-WW4)

Compact delta covering the WW4 STUB-triage sprint tick (round 24 after
VV4's round-23 ``layer.new`` / ``layer.delete`` /
``snap.set_grid_size`` / ``view.toggle_ruler`` /
``spawn.at_last_position`` batch).

## WW4 STUB-triage patch (2026-07-15, round 24)

Five more action ids landed in this tick, moving 5 rows from STUB
(implicit — the ids were not yet registered on the router) to WIRED:

| Action id | Fallback module (`pharos_editor.actions.*`) | Category |
|-----------|--------------------------------------------|----------|
| `view.toggle_axes`       | `view_toggle_axes_actions.toggle_axes`             | view  |
| `view.toggle_background` | `view_toggle_background_actions.toggle_background` | view  |
| `edit.select_by_tag`     | `selection_by_tag_actions.select_by_tag`           | edit  |
| `spawn.at_grid`          | `spawn_at_grid_actions.spawn_at_grid`              | spawn |
| `layer.clear`            | `layer_clear_actions.clear_layer`                  | layer |

New action modules:

* `python/pharos_engine/actions/view_toggle_axes_actions.py`
* `python/pharos_engine/actions/view_toggle_background_actions.py`
* `python/pharos_engine/actions/selection_by_tag_actions.py`
* `python/pharos_engine/actions/spawn_at_grid_actions.py`
* `python/pharos_engine/actions/layer_clear_actions.py`

Router entries and `_fb_*` shims live in
`python/pharos_engine/tool_router.py` under the
`# ── WW4 STUB-triage: view.toggle_axes, view.toggle_background,
edit.select_by_tag, spawn.at_grid, layer.clear (round 24) ──` block.

### Behavioural notes for WW4

* **`view.toggle_axes`** — Blender numpad axis widget / Unity scene
  view "Axes" toggle / Nova3D viewport-corner mini-axes. Distinct
  from CC1's `view.toggle_gizmos` (the *transform* gizmo — object-
  owned move / rotate / scale handles); this owns the *world*
  orientation cue rendered in the viewport corner. Default state
  is **visible** (matches Blender / Unity / Maya factory-fresh —
  the axis widget is the always-on sibling of the grid). Stores
  state on `shell._axes_visible`; fires the `_on_view_toggle`
  overlay-refresh hook. Return contract: `no_shell` / `toggled`
  (with `target`, `visible`, `previous`).
* **`view.toggle_background`** — Photoshop's checkerboard toggle /
  Aseprite's "Show Grid" for the transparency board / Blender image
  editor's "Show Background". Distinct from CC1's `view.toggle_grid`
  (grid *lines* drawn on top of the background). Default state is
  **visible** — the checkerboard is the always-on transparency
  indicator; toggling off swaps to a plain theme-tinted fill so the
  user can preview the scene against a solid background before
  export. Stores state on `shell._background_visible`; fires the
  `_on_view_toggle` overlay-refresh hook. Return contract:
  `no_shell` / `toggled` (with `target`, `visible`, `previous`).
* **`edit.select_by_tag`** — Unity's `GameObject.CompareTag` /
  Godot's `Node.is_in_group` / Blender's "Select All by Type"
  extended by tag membership. Distinct from QQ1's
  `selection.by_type` (matches on `kind` / `prefab_kind` /
  `type(entity).__name__`), `selection.by_layer` (Z-layer
  membership), and `selection.same_material`. Tag resolution
  probes `entity.tags` (canonical set / list / tuple) with a
  fallback to `_tags` so private-attribute conventions still
  match. Compare is **case-sensitive** to mirror Unity's
  contract. Requires `ctx["tag"]`; empty / non-string tags are
  rejected as `missing_tag`. Return contract: `missing_tag` /
  `no_scene` / `no_match` (with `tag`) / `selected` (with
  `selection`, `tag`, `matched`, `total`).
* **`spawn.at_grid`** — Blender's "Snap Cursor to Grid"
  (`Shift+S → 1`) + Unity's "V" vertex-snap toggle. Distinct from
  QQ1's `spawn.at_origin` (world zero, no snap), TT2's
  `spawn.at_view_center` (camera focal point), UU4's
  `spawn.at_origin_offset` (origin + delta), VV4's
  `spawn.at_last_position` (previous drop), and CC1's
  `spawn.spawn_at_cursor` (fires immediately, no snap).
  Complements OO1's `snap.increase_grid_size` / VV4's
  `snap.set_grid_size` — those verbs configure the ladder step;
  this verb applies it to a spawn target. Position resolution
  walks four sources in priority order: `ctx["position"]` →
  `ctx["cursor"]` → `shell._cursor_position` →
  `shell._last_spawn_position`, with an `origin_fallback` when
  nothing resolves. Grid-size resolution walks `ctx["grid_size"]`
  → `shell._snap_grid_size` / `_grid_size` / `grid_size` →
  default `1.0`. Zero / negative sizes fall through to `1.0`
  (matches the `snap_set_grid_size_actions._MIN_GRID` invariant).
  Snap uses Python's banker's rounding for deterministic
  chain-press behaviour. Return contract: `no_shell` / `armed`
  (with `position`, `source`, `grid_size`, `snapped_from`).
* **`layer.clear`** — Photoshop's "Delete Layer Contents" / Krita's
  Layer → Clear Layer / Affinity Photo's Layer → Clear Contents /
  Nova3D's Layer-panel right-click "Clear Layer". Distinct from
  VV4's `layer.delete` (removes the layer entry itself), OO1's
  `layer.merge_down` (moves entities into the neighbour), and
  DD1's `edit.duplicate_layer` (clones). This verb wipes entities
  on the target layer while preserving the layer entry so the user
  can re-populate it in place. Entity matching probes
  `entity.z_layer` / `layer` / `_layer` — identity check first,
  then a name-string fallback so scenes that store the layer as a
  string still get cleared. Removal walks
  `scene.remove_entity(entity)` first, then in-place list mutation
  on `scene.entities` / `_entities`. Return contract: `no_scene` /
  `no_layer` / `cleared` (with `target`, `z`, `removed`, `kept`) /
  `error` (with `message`) when the scene refuses removes.

Regression tests:
`SlapPyEngineTests/tests/test_actions_stub_triage_r24.py` — one
registration test per id (5 tests) plus a category assertion + a
singleton-check test + a `required_args` guard for the `tag`
parameter (8 registration tests total) plus behavioural coverage per
module (~34 behavioural tests) plus a ctx-validation parametrised
sweep (5 tests). Total: **47 tests**. Combined with r15…r23 the
r15…r24 dispatch surface is exercised across ~337 tests.

## STUB roster unchanged

The 5 new WIRED rows are all NEW router entries — no previously-listed
STUB row (from the roster tracked in
`feature_map_delta_2026_07_06.md`) is affected. The DPG-shell-dependent
STUBs (HUD toggle, diary "Open…" file picker, inspector help popups,
theming save-as-new / import / export modals) remain untouched by WW4.

---

*Delta generated 2026-07-15 by WW4 STUB-triage agent (parallel-sprint
lane). Sources: VV4 (r23) baseline + WW4 commit.*
