# Engine Feature Map — Delta Report (2026-07-17 → post-ZZ4)

Compact delta covering the ZZ4 STUB-triage sprint tick (round 26 after
YY4's round-25 ``view.toggle_snap_indicator`` / ``edit.select_parent`` /
``spawn.at_selection_center`` / ``layer.lock`` / ``snap.reset_defaults``
batch).

## ZZ4 STUB-triage patch (2026-07-17, round 26)

Five more action ids landed in this tick, moving 5 rows from STUB
(implicit — the ids were not yet registered on the router) to WIRED:

| Action id | Fallback module (`pharos_editor.actions.*`) | Category |
|-----------|--------------------------------------------|----------|
| `view.toggle_safe_area`  | `view_toggle_safe_area_actions.toggle_safe_area`        | view  |
| `edit.select_root`       | `edit_select_root_actions.select_root`                  | edit  |
| `spawn.at_last_click`    | `spawn_at_last_click_actions.spawn_at_last_click`       | spawn |
| `layer.unlock_all`       | `layer_unlock_all_actions.unlock_all_layers`            | layer |
| `snap.cycle_grid_size`   | `snap_cycle_grid_size_actions.cycle_grid_size`          | snap  |

New action modules:

* `python/pharos_engine/actions/view_toggle_safe_area_actions.py`
* `python/pharos_engine/actions/edit_select_root_actions.py`
* `python/pharos_engine/actions/spawn_at_last_click_actions.py`
* `python/pharos_engine/actions/layer_unlock_all_actions.py`
* `python/pharos_engine/actions/snap_cycle_grid_size_actions.py`

Router entries and `_fb_*` shims live in
`python/pharos_engine/tool_router.py` under the
`# ── ZZ4 STUB-triage: view.toggle_safe_area, edit.select_root,
spawn.at_last_click, layer.unlock_all, snap.cycle_grid_size
(round 26) ──` block.

### Behavioural notes for ZZ4

* **`view.toggle_safe_area`** — Blender's Camera → Viewport Display →
  Safe Areas / Unity's Camera Preview safe-area gizmo / Nova3D's
  viewport safe-area lines. Toggles the 90% action-safe + 80%
  title-safe outline drawn over the camera-viewport frame — a
  cinematic-composition overlay. Sibling to CC1's ``view.toggle_grid``
  / ``view.toggle_gizmos``, QQ1's ``view.toggle_stats``, PP1's
  ``view.toggle_wireframe``, VV4's ``view.toggle_ruler``, WW4's
  ``view.toggle_axes`` / ``view.toggle_background``, and YY4's
  ``view.toggle_snap_indicator``. Default state is **hidden** —
  matching Blender / Unity / Maya factory-fresh; safe-area is a
  video-composition tool most authoring flows only enable when
  authoring cinematic captures. Stores state on
  ``shell._safe_area_visible``; fires the ``_on_view_toggle``
  overlay-refresh hook. Return contract: ``no_shell`` / ``toggled``
  (with ``target``, ``visible``, ``previous``).
* **`edit.select_root`** — Blender's ``]`` (select outermost parent) /
  Unity's Ctrl+Shift+Home (walk to root) / Nova3D's Outliner
  ``Shift+P`` shortcut. Sibling to YY4's ``edit.select_parent``
  (one-step walk); this verb walks *all the way up* to the outermost
  ancestor. Distinct from FF1's ``edit.select_children`` (walks
  *down*), PP2's ``edit.select_next`` / ``edit.select_previous``
  (walk *sideways*), and the flat-scene selectors (QQ1's
  ``selection.by_type`` / ``by_layer`` / ``same_material``, WW4's
  ``edit.select_by_tag``). Parent resolution matches YY4 —
  ``.parent`` → ``._parent`` → ``["parent"]``. Cycle-guarded via
  visited-id set; depth-capped at 64 to match Nova3D's SceneGraph
  guard. An entity that is already a root resolves to itself, so the
  only failure mode is "nothing selected". Modes: ``"replace"``
  (default) matches Blender's ``]``; ``"add"`` matches Unity's
  Ctrl+click walk. Return contract: ``no_selection`` / ``walked``
  (with ``roots``, ``count``, ``selection``).
* **`spawn.at_last_click`** — Blender's ``Shift+S → Cursor to Last
  Click`` / Unity's Ctrl+Shift+F (position at last click) / Nova3D's
  viewport right-click "Drop at Last Click". Sibling to VV4's
  ``spawn.at_last_position`` (last *spawn drop*) — the two diverge
  when the user has clicked around the viewport but not yet dropped a
  prefab. Distinct from CC1's ``spawn.spawn_at_cursor`` which fires
  immediately at the *live* cursor (not the last recorded click).
  Position resolution probes ``ctx["last_click"]`` /
  ``ctx["click_position"]`` → ``shell._last_click_position`` (canonical)
  → ``shell._last_cursor_position`` (legacy — matches
  ``spawn.spawn_at_cursor``'s reader) → ``shell._input._last_click``
  (input-manager fallback). Optional ``offset`` matches VV4's
  micro-offset knob — the return dict flags ``"malformed_offset":
  True`` when the offset can't be parsed. Return contract:
  ``no_shell`` / ``no_click`` / ``armed`` (with ``position``,
  ``source``, ``offset``).
* **`layer.unlock_all`** — Photoshop's Layer → Unlock All Layers /
  Krita's Layer → Unlock All Layers / Affinity Photo's Layer →
  Unlock All / Nova3D's Layer-panel gear → Unlock All. Sweep
  counterpart of YY4's ``layer.lock`` — clears the *layer-wide* lock
  on every layer in one shot. Distinct from CC1's ``edit.unlock_all``
  (per-entity flag) — callers that want a full unlock invoke both.
  Distinct from other layer verbs: RR1's ``layer.hide_others`` /
  ``layer.isolate`` (visibility), NN1's ``layer.solo`` (exclusive
  visibility), WW4's ``layer.clear`` (contents), VV4's ``layer.delete``
  (entry). Storage on the layer object as ``.locked`` (matches YY4's
  ``layer.lock``). ``ctx["dry_run"]=True`` skips the write for
  preview flows. Refresh hook (``_on_layer_lock_toggled``, falls back
  to ``_refresh_layer_panel``) fires exactly once per non-empty write.
  Return contract: ``no_scene`` / ``no_layers`` / ``already_unlocked``
  / ``unlocked`` (with ``count``, ``targets``).
* **`snap.cycle_grid_size`** — Blender's numeric-1 through 5
  grid-preset cycle / Unity's ProGrids "Cycle Grid Snap" shortcut /
  Nova3D's grid-size cycle button. Complements the individual snap
  setters — OO1's ``snap.increase_grid_size`` /
  ``snap.decrease_grid_size`` (ladder-clamp), VV4's
  ``snap.set_grid_size`` (absolute write), YY4's
  ``snap.reset_defaults`` (canonical reset). Distinct from OO1's
  ``increase`` — that verb stops at the ladder ceiling
  (``at_limit`` return); this verb *wraps*. Ladder is the OO1
  geometric progression capped at ``256.0`` (matches Blender / Unity
  muscle memory for cyclical controls — the OO1 clamp ceiling of
  ``4096.0`` is only useful for absolute setters). Off-ladder values
  snap to the *nearest* rung before stepping — makes the cycle
  predictable after ``snap.set_grid_size`` writes an arbitrary float
  (e.g. ``3.14`` → nearest rung ``4.0`` → step up → ``8.0``).
  ``direction="down"`` walks the ladder downward and wraps at the
  floor; any other value defaults to ``"up"``. Return contract:
  ``no_shell`` / ``cycled`` (with ``previous``, ``new``,
  ``direction``, ``wrapped``).

Regression tests:
`SlapPyEngineTests/tests/test_actions_stub_triage_r26.py` — one
registration test per id (5 tests) plus a category assertion + a
singleton-check test + a `required_args=[]` guard sweep (8
registration tests total) plus behavioural coverage per module (~38
behavioural tests) plus a ctx-validation parametrised sweep (5
tests). Total: **51 tests**. Combined with r15…r25 the r15…r26
dispatch surface is exercised across ~433 tests.

## STUB roster unchanged

The 5 new WIRED rows are all NEW router entries — no previously-listed
STUB row (from the roster tracked in
`feature_map_delta_2026_07_06.md`) is affected. The DPG-shell-dependent
STUBs (HUD toggle, diary "Open…" file picker, inspector help popups,
theming save-as-new / import / export modals) remain untouched by ZZ4.

## Round rollup

r14…r26 have now wired **65 action ids** across 13 rounds (5 ids each):

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

---

*Delta generated 2026-07-17 by ZZ4 STUB-triage agent (parallel-sprint
lane). Sources: YY4 (r25) baseline + ZZ4 commit.*
