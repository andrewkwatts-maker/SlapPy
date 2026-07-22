# Engine Feature Map — Delta Report (2026-07-09 → post-QQ1)

Compact delta covering the QQ1 STUB-triage sprint tick (round 18 after
PP1's round-17 ``selection.shrink`` / ``selection.invert_by_type`` /
``view.toggle_wireframe`` / ``edit.rename`` / ``edit.duplicate_at_cursor``
batch).

## QQ1 STUB-triage patch (2026-07-09, round 18)

Five more action ids landed in this tick, moving 5 rows from STUB
(implicit — the ids were not yet registered on the router) to WIRED:

| Action id | Fallback module (`pharos_editor.actions.*`) | Category |
|-----------|--------------------------------------------|----------|
| `spawn.at_origin`          | `spawn_origin_actions.spawn_at_origin`              | spawn |
| `selection.by_type`        | `selection_by_type_actions.select_by_type`          | selection |
| `selection.by_layer`       | `selection_by_layer_actions.select_by_layer`        | selection |
| `selection.same_material`  | `selection_same_material_actions.select_same_material` | selection |
| `view.toggle_stats`        | `view_toggle_stats_actions.toggle_stats`            | view |

New action modules:

* `python/pharos_engine/actions/spawn_origin_actions.py`
* `python/pharos_engine/actions/selection_by_type_actions.py`
* `python/pharos_engine/actions/selection_by_layer_actions.py`
* `python/pharos_engine/actions/selection_same_material_actions.py`
* `python/pharos_engine/actions/view_toggle_stats_actions.py`

Router entries and `_fb_*` shims live in
`python/pharos_engine/tool_router.py` under the
`# ── QQ1 STUB-triage: spawn-at-origin, selection by type / layer /
material, view toggle-stats overlay (round 18) ──` block.

### Behavioural notes for QQ1

* **`spawn.at_origin`** — Blender ``Shift+C``-style "reset to origin".
  Companion to EE1's `spawn.spawn_at_cursor`: arms
  `shell._pending_spawn_position` with `(0, 0, 0)` so the next
  spawn-menu card lands at world zero. `mode="repeat"` immediately
  re-fires `shell._last_spawn` at origin (matches the EE1 repeat
  branch). Return contract: `no_shell` / `armed` (with `position`) /
  `respawned` (with `card_id`, `spec`, `position`).
* **`selection.by_type`** — Blender ``Shift+G → Type`` inclusive
  variant. Companion to PP1's `selection.invert_by_type`: instead of
  *replacing* the selection with only the non-seed matches, this
  helper *extends* the selection by every same-kind entity. Seeds are
  preserved. Return contract: `no_scene` / `no_selection` /
  `unchanged` (nothing new was added) / `selected` (with `selection`,
  `kinds`, `added`, `previous_count`, `total`).
* **`selection.by_layer`** — Blender ``Select → Same Collection``,
  Photoshop layer-panel ``Cmd+Alt+Click``. Reads the layer of every
  seed entity (`entity.layer` → `entity.layer_id` → `entity.tags["layer"]`,
  falling through to `"default"`) and pulls every same-layer scene
  entity into the selection. Return contract: `no_scene` /
  `no_selection` / `unchanged` / `selected` (with `layers`).
* **`selection.same_material`** — Blender ``Select → Same Material``,
  Maya ``Select → Same Shader``. Reads the material of every seed
  (`entity.material` → `entity.material_id` → `entity.tags["material"]`,
  coerced through `.name` / `.id` for material objects) and grabs
  every scene entity referencing the same material. Return contract:
  `no_scene` / `no_selection` / `no_materials` (seed carries no
  resolvable material) / `unchanged` / `selected` (with `materials`).
* **`view.toggle_stats`** — Unity `Stats`, Unreal `stat unit`, Blender
  `Overlays → Statistics`. Distinct from CC1's `view.toggle_grid` /
  `view.toggle_gizmos` (visual guide layers), from
  `view.toggle_wireframe` (shading mode), and from
  `editor.toggle_hud` (editor chrome). Flips `shell._stats_visible`
  and fires `shell._on_view_toggle("_stats_visible", new_value)` for
  downstream refresh. Return contract: `no_shell` / `toggled` (with
  `target`, `visible`, `previous`).

Regression tests:
`SlapPyEngineTests/tests/test_actions_stub_triage_r18.py` — one
registration test per id plus behavioural coverage per module. Combined
with r15 (31), r16 (29), r17 (34), the r15+r16+r17+r18 dispatch surface
is exercised across ~125+ tests.

## STUB roster unchanged

The 5 new WIRED rows are all NEW router entries — no previously-listed
STUB row (from the roster tracked in
`feature_map_delta_2026_07_06.md`) is affected. The DPG-shell-dependent
STUBs (HUD toggle, diary "Open…" file picker, inspector help popups,
theming save-as-new / import / export modals) remain untouched by QQ1.

---

*Delta generated 2026-07-09 by QQ1 STUB-triage agent (parallel-sprint
lane). Sources: `26e29ca` (r17 baseline) + QQ1 commit.*
