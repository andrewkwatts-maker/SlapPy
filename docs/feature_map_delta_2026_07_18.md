# Engine Feature Map — Delta Report (2026-07-18 → post-AAA4)

Compact delta covering the AAA4 STUB-triage sprint tick (round 27 after
ZZ4's round-26 ``view.toggle_safe_area`` / ``edit.select_root`` /
``spawn.at_last_click`` / ``layer.unlock_all`` / ``snap.cycle_grid_size``
batch).

## AAA4 STUB-triage patch (2026-07-18, round 27)

Five more action ids landed in this tick, moving 5 rows from STUB
(implicit — the ids were not yet registered on the router) to WIRED:

| Action id | Fallback module (`slappyengine.actions.*`) | Category |
|-----------|--------------------------------------------|----------|
| `view.toggle_camera_bounds`   | `view_toggle_camera_bounds_actions.toggle_camera_bounds`   | view  |
| `edit.select_last_spawned`    | `edit_select_last_spawned_actions.select_last_spawned`     | edit  |
| `spawn.at_previous_click`     | `spawn_at_previous_click_actions.spawn_at_previous_click`  | spawn |
| `layer.sort_by_z`             | `layer_sort_by_z_actions.sort_by_z`                        | layer |
| `snap.toggle_pixel_perfect`   | `snap_toggle_pixel_perfect_actions.toggle_pixel_perfect`   | snap  |

New action modules:

* `python/slappyengine/actions/view_toggle_camera_bounds_actions.py`
* `python/slappyengine/actions/edit_select_last_spawned_actions.py`
* `python/slappyengine/actions/spawn_at_previous_click_actions.py`
* `python/slappyengine/actions/layer_sort_by_z_actions.py`
* `python/slappyengine/actions/snap_toggle_pixel_perfect_actions.py`

Router entries and `_fb_*` shims live in
`python/slappyengine/tool_router.py` under the
`# ── AAA4 STUB-triage: view.toggle_camera_bounds,
edit.select_last_spawned, spawn.at_previous_click, layer.sort_by_z,
snap.toggle_pixel_perfect (round 27) ──` block.

### Behavioural notes for AAA4

* **`view.toggle_camera_bounds`** — Blender's Camera → Viewport
  Display → Passepartout / Unity's Camera Preview outline / Nova3D's
  viewport camera-frame widget. Draws the *outer* rectangle marking
  the exact area the camera will render. Sibling to the other
  overlay toggles: CC1's ``view.toggle_grid`` / ``view.toggle_gizmos``,
  QQ1's ``view.toggle_stats``, PP1's ``view.toggle_wireframe``, VV4's
  ``view.toggle_ruler``, WW4's ``view.toggle_axes`` /
  ``view.toggle_background``, YY4's ``view.toggle_snap_indicator``,
  and ZZ4's ``view.toggle_safe_area``. Distinct from ZZ4's safe-area
  — the safe-area outlines are the *inner* 90 / 80 % composition
  guides; this verb draws the *outer* camera-frame rectangle. Default
  state is **hidden** — camera-frame is a composition-time cue most
  authoring flows only enable when framing cinematic shots. Stores
  state on ``shell._camera_bounds_visible``; fires the
  ``_on_view_toggle`` overlay-refresh hook. Return contract:
  ``no_shell`` / ``toggled`` (with ``target``, ``visible``,
  ``previous``).
* **`edit.select_last_spawned`** — Blender's ``Ctrl+.`` (select last
  operator result) / Unity's Ctrl+Shift+Insert (select newly-created)
  / Nova3D's Outliner "Reselect Last Spawn" shortcut. The *temporal*
  selector — complement of the spawn family: those verbs *create*,
  this one *re-selects* whatever was created most recently. Distinct
  from all the DAG walkers (YY4's ``edit.select_parent``, ZZ4's
  ``edit.select_root``, FF1's ``edit.select_children``, PP2's
  ``edit.select_next`` / ``edit.select_previous``) and from the flat
  attribute selectors (QQ1's ``selection.by_type`` / ``by_layer`` /
  ``same_material``, WW4's ``edit.select_by_tag``, RR1's
  ``edit.select_similar``). Last-spawned resolution:
  ``ctx["entity"]`` → ``shell._last_spawned_entity`` →
  ``shell._spawn_history[-1]`` → ``scene._last_spawned``. Modes:
  ``"replace"`` (default) matches Blender's ``Ctrl+.``; ``"add"``
  matches Unity's Shift+Ctrl+Insert. Return contract:
  ``no_spawn_history`` / ``selected`` (with ``entity``,
  ``selection``).
* **`spawn.at_previous_click`** — Blender's Alt+Shift+S (Cursor to
  Previous Click) / Nova3D's viewport right-click "Drop at Previous
  Click" / Unity's Ctrl+Alt+Home (previous click hotkey). Walks
  *backwards* through the click history so successive presses cycle
  through past viewport clicks. Distinct from ZZ4's
  ``spawn.at_last_click`` — that verb picks the most-recent click;
  this one skips the most-recent and lands on the previous one
  (``depth=1``) — successive ``depth=2``, ``depth=3``… presses walk
  further back. Distinct from VV4's ``spawn.at_last_position``
  (last *spawn drop*, not click) and CC1's ``spawn.spawn_at_cursor``
  (immediate live-cursor fire). Position resolution probes
  ``ctx["click_history"]`` (override) → ``shell._click_history``
  (canonical) → ``shell._input._click_history`` (input-manager
  fallback). Optional ``offset`` matches ZZ4's / VV4's
  micro-offset knob — the return dict flags
  ``"malformed_offset": True`` when the offset can't be parsed.
  Return contract: ``no_shell`` / ``no_previous_click`` / ``armed``
  (with ``position``, ``depth``, ``source``, ``offset``).
* **`layer.sort_by_z`** — Photoshop's Layer → Arrange → Sort by Z /
  Krita's Layer → Sort Layers by Depth / Affinity Photo's Layer →
  Sort by Z / Nova3D's Layer-panel gear → Sort by Z. Bulk-reorder
  counterpart of UU4's ``layer.move_up`` / ``layer.move_down`` — the
  UU4 verbs shift a single layer one position; this verb sorts every
  layer at once by ``.z`` ascending (default) or descending. Distinct
  from other layer verbs: VV4's ``layer.new`` / ``layer.delete``
  (lifecycle), TT2's ``layer.rename`` (metadata), NN1's
  ``layer.solo`` / RR1's ``layer.hide_others`` / ``layer.isolate`` /
  YY4's ``layer.lock`` (per-layer flags), OO1's ``layer.merge_down``
  (topology), WW4's ``layer.clear`` (contents), ZZ4's
  ``layer.unlock_all`` (sweep unlock). Stable sort — layers with
  identical ``.z`` keep their relative order. Layers missing ``.z``
  are treated as ``0.0``. ``ctx["dry_run"]=True`` reports the
  intended ordering without writing. Refresh hook
  (``_on_layer_order_changed``, falls back to
  ``_refresh_layer_panel``) fires exactly once per non-empty write.
  Return contract: ``no_scene`` / ``no_layers`` / ``already_sorted``
  / ``sorted`` (with ``order``, ``count``, ``direction``, ``moved``).
* **`snap.toggle_pixel_perfect`** — Aseprite's Edit → Preferences →
  Snap to Pixel / Krita's Snap to Pixel Grid toggle / Blender's Snap
  → "Pixel" absolute mode / Nova3D's snap-mode toolbar pixel-perfect
  button. Persistent mode flag — every subsequent position write is
  rounded to the nearest integer pixel while enabled. Distinct from
  RR1's ``snap.toggle_incremental`` — that verb toggles *incremental*
  snap (grid-cell stepping while dragging); this one toggles
  *absolute* pixel snap (integer round-off on every write). The two
  are complementary and independently toggleable. Distinct from the
  one-shot snap verbs (CC1's ``edit.snap_to_grid`` /
  ``edit.snap_to_pixel_grid``) which perform a single snap action.
  Distinct from the grid-size verbs (OO1's increase / decrease, VV4's
  ``snap.set_grid_size``, ZZ4's ``snap.cycle_grid_size``) which set
  the grid rung rather than the mode. Stores state on
  ``shell._pixel_perfect_snap``; fires the ``_on_snap_mode_changed``
  hook. Return contract: ``no_shell`` / ``toggled`` (with ``target``,
  ``enabled``, ``previous``).

Regression tests:
`SlapPyEngineTests/tests/test_actions_stub_triage_r27.py` — one
registration test per id (5 tests) plus a category assertion + a
singleton-check test + a `required_args=[]` guard sweep (8
registration tests total) plus behavioural coverage per module (~40
behavioural tests) plus a ctx-validation parametrised sweep (5
tests). Total: **53 tests**. Combined with r15…r26 the r15…r27
dispatch surface is exercised across ~486 tests.

## STUB roster unchanged

The 5 new WIRED rows are all NEW router entries — no previously-listed
STUB row (from the roster tracked in
`feature_map_delta_2026_07_06.md`) is affected. The DPG-shell-dependent
STUBs (HUD toggle, diary "Open…" file picker, inspector help popups,
theming save-as-new / import / export modals) remain untouched by AAA4.

## Round rollup

r14…r27 have now wired **70 action ids** across 14 rounds (5 ids each):

* r14 (MM6) — capture/render batch
* r15 (NN2) — ``view.frame_selected`` / ``view.reset_view`` / ``panel.dock_left`` / ``panel.dock_right`` / ``theme.hot_swap``
* r16 (OO1) — ``layer.solo`` / ``layer.merge_down`` / …
* r17 (PP1) — ``selection.shrink`` / ``selection.invert_by_type`` / ``view.toggle_wireframe`` / ``edit.rename`` / ``edit.duplicate_at_cursor``
* r18 (QQ1) — ``spawn.at_origin`` / ``selection.by_type`` / ``selection.by_layer`` / ``selection.same_material`` / ``view.toggle_stats``
* r19 (RR1) — ``edit.select_similar`` / ``theme.reset_to_default`` / ``layer.hide_others`` / ``layer.isolate`` / ``snap.toggle_incremental``
* r20 (SS…) — content batch
* r21 (TT2) — ``view.set_zoom`` / ``spawn.at_view_center`` / ``spawn.stamp_random`` / ``theme.reload_from_disk`` / ``layer.rename``
* r22 (UU4) — ``spawn.at_origin_offset`` / ``edit.flatten_selection`` / ``snap.set_angle_snap`` / ``layer.move_up`` / ``layer.move_down``
* r23 (VV4) — ``layer.new`` / ``layer.delete`` / ``snap.set_grid_size`` / ``view.toggle_ruler`` / ``spawn.at_last_position``
* r24 (WW4) — ``view.toggle_axes`` / ``view.toggle_background`` / ``edit.select_by_tag`` / ``spawn.at_grid`` / ``layer.clear``
* r25 (YY4) — ``view.toggle_snap_indicator`` / ``edit.select_parent`` / ``spawn.at_selection_center`` / ``layer.lock`` / ``snap.reset_defaults``
* r26 (ZZ4) — ``view.toggle_safe_area`` / ``edit.select_root`` / ``spawn.at_last_click`` / ``layer.unlock_all`` / ``snap.cycle_grid_size``
* r27 (AAA4) — ``view.toggle_camera_bounds`` / ``edit.select_last_spawned`` / ``spawn.at_previous_click`` / ``layer.sort_by_z`` / ``snap.toggle_pixel_perfect``

---

*Delta generated 2026-07-18 by AAA4 STUB-triage agent (parallel-sprint
lane). Sources: ZZ4 (r26) baseline + AAA4 commit.*
