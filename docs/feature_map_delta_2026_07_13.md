# Engine Feature Map — Delta Report (2026-07-13 → post-UU4)

Compact delta covering the UU4 STUB-triage sprint tick (round 22 after
TT2's round-21 ``view.set_zoom`` / ``spawn.at_view_center`` /
``spawn.stamp_random`` / ``theme.reload_from_disk`` / ``layer.rename``
batch).

## UU4 STUB-triage patch (2026-07-13, round 22)

Five more action ids landed in this tick, moving 5 rows from STUB
(implicit — the ids were not yet registered on the router) to WIRED:

| Action id | Fallback module (`slappyengine.actions.*`) | Category |
|-----------|--------------------------------------------|----------|
| `spawn.at_origin_offset`  | `spawn_origin_offset_actions.spawn_at_origin_offset`   | spawn |
| `edit.flatten_selection`  | `edit_flatten_selection_actions.flatten_selection`     | edit  |
| `snap.set_angle_snap`     | `snap_angle_snap_actions.set_angle_snap`               | snap  |
| `layer.move_up`           | `layer_reorder_actions.move_layer_up`                  | layer |
| `layer.move_down`         | `layer_reorder_actions.move_layer_down`                | layer |

New action modules:

* `python/slappyengine/actions/spawn_origin_offset_actions.py`
* `python/slappyengine/actions/edit_flatten_selection_actions.py`
* `python/slappyengine/actions/snap_angle_snap_actions.py`
* `python/slappyengine/actions/layer_reorder_actions.py`

Router entries and `_fb_*` shims live in
`python/slappyengine/tool_router.py` under the
`# ── UU4 STUB-triage: spawn.at_origin_offset, edit.flatten_selection,
snap.set_angle_snap, layer.move_up, layer.move_down (round 22) ──`
block.

### Behavioural notes for UU4

* **`spawn.at_origin_offset`** — Blender ``Shift+A`` followed by
  ``F6 → Offset`` on the redo panel / Unity's numeric-entry
  Instantiate / Nova3D's ``Spawn → Advanced → Offset from Origin``.
  Sibling to QQ1's `spawn.at_origin` (forced world zero) + TT2's
  `spawn.at_view_center` (camera focus). This verb accepts a
  ``ctx["offset"]`` 2- or 3-vec and drops the next spawn at
  ``(0, 0, 0) + offset``. Supports both ``mode="arm"`` (stashes on
  `shell._pending_spawn_position`) and ``mode="repeat"`` (re-fires
  `_last_spawn` at the offset). Malformed offsets fall back to origin
  and mark the return dict with ``"malformed_offset": True`` so the
  caller can distinguish "no offset supplied" from "offset supplied
  but rejected". Return contract: `no_shell` / `armed`
  (with `position`, `offset`) / `respawned` (with `card_id`, `spec`,
  `position`, `offset`).
* **`edit.flatten_selection`** — Adobe Illustrator "Object → Ungroup
  All" / Krita "Flatten Group Layer" / Blender ``Alt+P`` "Clear Parent
  Inverse". Distinct from EE1's `edit.ungroup_selection` (single-level
  peel) — this verb walks the *entire* selection tree so
  ``group(group(a, b), c)`` collapses to ``[a, b, c]`` in one gesture.
  Child positions cascade to their absolute world coordinates by
  summing ``group.position`` up the chain, matching the child-
  relative-to-centroid convention `edit_group_actions` uses when
  *building* a group. Selection is retargeted to the released leaves.
  Return contract: `no_selection` / `no_groups` / `no_scene` /
  `flattened` (with `released`, `count`, `groups_removed`).
* **`snap.set_angle_snap`** — Blender transform-panel "Angle" field /
  Unity ProGrids rotation snap / Nova3D ``Snap → Rotation Angle``.
  Distinct from OO1's `snap.increase_grid_size` /
  `snap.decrease_grid_size` (which walk *position* snap along a
  geometric ladder) + RR1's `snap.toggle_incremental` (boolean gate).
  Accepts a ``ctx["degrees"]`` numeric target clamped to ``[0, 180]``.
  Values within ``0.05°`` of a canonical DCC step (1, 5, 15, 22.5, 30,
  45, 60, 90, 180) are snapped to that step (matches Blender's
  "snap-the-snap" behaviour). Writes to both `_snap_angle_deg`
  (canonical) and `_snap_angle` (legacy alias) for compatibility.
  Return contract: `missing_degrees` / `no_shell` / `unchanged`
  (with `value`) / `set` (with `previous`, `new`, `canonical`).
* **`layer.move_up`** / **`layer.move_down`** — Photoshop
  ``Ctrl+]`` / ``Ctrl+[`` Layers-panel reorder / Krita ``[`` / ``]`` /
  Affinity Photo layer-panel arrow buttons / Nova3D Layer-panel
  right-click ``Move Up`` / ``Move Down``. Distinct from OO1's
  `layer.merge_down` (which collapses two layers into one and
  deletes the source) + TT2's `layer.rename` (which touches names,
  not the z-stack order) + RR1's `layer.hide_others` / `layer.isolate`
  (visibility toggles that don't reorder). "Up" means *higher* z
  (toward the viewer); "down" means *lower* z. Swap semantics keep
  every entity's world position intact — only the ``z`` scalar on
  the two swapped layers changes. Target resolution walks
  `ctx["layer"]` → `ctx["layer_name"]` → `shell._active_layer`.
  Fires the shell's `_on_layer_reordered` refresh hook so the layer
  panel repaints. Return contract: `no_scene` / `no_layers` /
  `single_layer` / `no_layer` / `at_top` / `at_bottom` (with
  `target`) / `moved` (with `target`, `direction`, `swapped_with`,
  `new_z`, `old_z`).

Regression tests:
`SlapPyEngineTests/tests/test_actions_stub_triage_r22.py` — one
registration test per id (5 tests) plus a category assertion + a
singleton-check test (7 registration tests total) plus behavioural
coverage per module (~38 behavioural tests). Combined with
r15+r16+r17+r18+r19+r20+r21, the r15…r22 dispatch surface is exercised
across ~240 tests.

## STUB roster unchanged

The 5 new WIRED rows are all NEW router entries — no previously-listed
STUB row (from the roster tracked in
`feature_map_delta_2026_07_06.md`) is affected. The DPG-shell-dependent
STUBs (HUD toggle, diary "Open…" file picker, inspector help popups,
theming save-as-new / import / export modals) remain untouched by UU4.

---

*Delta generated 2026-07-13 by UU4 STUB-triage agent (parallel-sprint
lane). Sources: TT2 (r21) baseline + UU4 commit.*
