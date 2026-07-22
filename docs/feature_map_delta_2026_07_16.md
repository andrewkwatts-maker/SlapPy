# Engine Feature Map — Delta Report (2026-07-16 → post-YY4)

Compact delta covering the YY4 STUB-triage sprint tick (round 25 after
WW4's round-24 ``view.toggle_axes`` / ``view.toggle_background`` /
``edit.select_by_tag`` / ``spawn.at_grid`` / ``layer.clear`` batch).

## YY4 STUB-triage patch (2026-07-16, round 25)

Five more action ids landed in this tick, moving 5 rows from STUB
(implicit — the ids were not yet registered on the router) to WIRED:

| Action id | Fallback module (`pharos_editor.actions.*`) | Category |
|-----------|--------------------------------------------|----------|
| `view.toggle_snap_indicator` | `view_toggle_snap_indicator_actions.toggle_snap_indicator` | view  |
| `edit.select_parent`         | `edit_select_parent_actions.select_parent`                | edit  |
| `spawn.at_selection_center`  | `spawn_at_selection_center_actions.spawn_at_selection_center` | spawn |
| `layer.lock`                 | `layer_lock_actions.toggle_layer_lock`                    | layer |
| `snap.reset_defaults`        | `snap_reset_defaults_actions.reset_snap_defaults`         | snap  |

New action modules:

* `python/pharos_engine/actions/view_toggle_snap_indicator_actions.py`
* `python/pharos_engine/actions/edit_select_parent_actions.py`
* `python/pharos_engine/actions/spawn_at_selection_center_actions.py`
* `python/pharos_engine/actions/layer_lock_actions.py`
* `python/pharos_engine/actions/snap_reset_defaults_actions.py`

Router entries and `_fb_*` shims live in
`python/pharos_engine/tool_router.py` under the
`# ── YY4 STUB-triage: view.toggle_snap_indicator, edit.select_parent,
spawn.at_selection_center, layer.lock, snap.reset_defaults (round 25) ──`
block.

### Behavioural notes for YY4

* **`view.toggle_snap_indicator`** — Blender's "Snap Element
  Indicator" / Unity's snap-marker dot / Nova3D's snap-hint chip.
  Distinct from ``tools.snap_to_grid`` (master on/off for snap
  *behaviour*); this verb only owns the *visual* feedback dot.
  Sibling to CC1's ``view.toggle_grid`` / ``view.toggle_gizmos``,
  QQ1's ``view.toggle_stats``, PP1's ``view.toggle_wireframe``,
  VV4's ``view.toggle_ruler``, and WW4's ``view.toggle_axes`` /
  ``view.toggle_background``. Default state is **visible** (matches
  Blender / Unity factory-fresh — snap-feedback is the always-on
  sibling of snap behaviour). Stores state on
  ``shell._snap_indicator_visible``; fires the ``_on_view_toggle``
  overlay-refresh hook. Return contract: ``no_shell`` / ``toggled``
  (with ``target``, ``visible``, ``previous``).
* **`edit.select_parent`** — Blender's ``[`` (select parent) /
  Unity's Ctrl+Shift+Up (walk to parent in hierarchy) / Nova3D's
  Outliner ``P`` shortcut. Sibling to FF1's ``edit.select_children``
  (walks *down* through descendants) and PP2's ``edit.select_next`` /
  ``edit.select_previous`` (walk *sideways* through siblings).
  Distinct from the flat-scene selectors (WW4's ``edit.select_by_tag``,
  QQ1's ``selection.by_type`` / ``by_layer`` / ``same_material``) —
  those walk the flat entity list; this walks the parent-child DAG.
  Parent resolution probes ``.parent`` → ``._parent`` → ``["parent"]``
  so both scene-graph and dict-shaped entities resolve. Modes:
  ``"replace"`` (default) matches Blender's ``[``; ``"add"`` matches
  Unity's Ctrl+click walk. Return contract: ``no_selection`` /
  ``no_parent`` / ``walked`` (with ``parents``, ``count``,
  ``selection``).
* **`spawn.at_selection_center`** — Blender's ``Shift+S → Cursor to
  Selected`` / Nova3D's Outliner right-click "Focus on Selection
  Center". Sibling to QQ1's ``spawn.at_origin`` (world zero), TT2's
  ``spawn.at_view_center`` (camera focal), UU4's
  ``spawn.at_origin_offset`` (origin + delta), VV4's
  ``spawn.at_last_position`` (previous drop), WW4's ``spawn.at_grid``
  (grid-snapped), and CC1's ``spawn.spawn_at_cursor`` (immediate).
  Position resolution probes each selected entity's ``.position`` →
  ``._position`` → ``.transform.position`` → ``["position"]`` and
  averages the resolved samples. Entities without a resolvable
  position contribute nothing to the centroid but the return
  ``count`` still reports the *input* selection size and ``samples``
  the *contributed* count so telemetry callers can spot mixed
  selections. Return contract: ``no_selection`` / ``no_position`` /
  ``armed`` (with ``position``, ``count``, ``samples``).
* **`layer.lock`** — Photoshop's layer-panel padlock icon / Krita's
  padlock column / Affinity Photo's Layer → Lock / Nova3D's
  Layer-panel lock column. Distinct from CC1's ``edit.lock_selection``
  (per-entity flag) — this verb toggles the *layer-wide* lock so the
  scene walker treats every entity on the layer as locked without
  touching per-entity state. Distinct from RR1's ``layer.hide_others``
  / ``layer.isolate`` (visibility) and NN1's ``layer.solo`` (exclusive
  visible). Distinct from WW4's ``layer.clear`` (wipes contents) and
  VV4's ``layer.delete`` (removes entry). Target resolution mirrors
  ``layer.clear`` — ``ctx["layer"]`` → ``ctx["layer_name"]`` →
  ``shell._active_layer``. Storage on the layer object as ``.locked``
  (canonical). Fires the ``_on_layer_lock_toggled`` refresh hook
  (falls back to ``_refresh_layer_panel``). Return contract:
  ``no_scene`` / ``no_layer`` / ``toggled`` (with ``target``, ``z``,
  ``locked``, ``previous``).
* **`snap.reset_defaults`** — Blender Prefs → Snap → Reset / Unity
  ProGrids "Restore Defaults" / Nova3D Snap-panel gear menu → Reset.
  Complements the individual snap setters — OO1's
  ``snap.increase_grid_size`` / ``snap.decrease_grid_size``, VV4's
  ``snap.set_grid_size``, UU4's ``snap.set_angle_snap``, RR1's
  ``snap.toggle_incremental``. Deliberately does NOT touch
  ``tools.snap_to_grid`` (master on/off) — matches Photoshop's
  "Reset Snapping" contract which preserves the master enable.
  Defaults are the canonical DCC values: ``grid_size=1.0`` (matches
  ``spawn_at_grid_actions._DEFAULT_GRID``), ``angle_deg=15.0``
  (matches Blender's default rotation snap and canonical rung in
  ``snap_angle_snap_actions._CANONICAL``), ``incremental=False``.
  Writes every mirror alias (``_snap_grid_size`` / ``_grid_size`` /
  ``grid_size``; ``_snap_angle_deg`` / ``_snap_angle``;
  ``_snap_incremental`` / ``_incremental_snap`` / ``snap_incremental``)
  so every read path stays in sync. Return contract: ``no_shell`` /
  ``reset`` (with ``previous``, ``new``, ``changed``).

Regression tests:
`SlapPyEngineTests/tests/test_actions_stub_triage_r25.py` — one
registration test per id (5 tests) plus a category assertion + a
singleton-check test + a `required_args=[]` guard sweep (8
registration tests total) plus behavioural coverage per module (~32
behavioural tests) plus a ctx-validation parametrised sweep (5
tests). Total: **45 tests**. Combined with r15…r24 the r15…r25
dispatch surface is exercised across ~382 tests.

## STUB roster unchanged

The 5 new WIRED rows are all NEW router entries — no previously-listed
STUB row (from the roster tracked in
`feature_map_delta_2026_07_06.md`) is affected. The DPG-shell-dependent
STUBs (HUD toggle, diary "Open…" file picker, inspector help popups,
theming save-as-new / import / export modals) remain untouched by YY4.

## Round rollup

r14…r25 have now wired **60 action ids** across 12 rounds (5 ids each):

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

---

*Delta generated 2026-07-16 by YY4 STUB-triage agent (parallel-sprint
lane, re-dispatch of XX4). Sources: WW4 (r24) baseline + YY4 commit.*
