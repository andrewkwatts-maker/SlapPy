# Engine Feature Map — Delta Report (2026-07-14 → post-VV4)

Compact delta covering the VV4 STUB-triage sprint tick (round 23 after
UU4's round-22 ``spawn.at_origin_offset`` / ``edit.flatten_selection``
/ ``snap.set_angle_snap`` / ``layer.move_up`` / ``layer.move_down``
batch).

## VV4 STUB-triage patch (2026-07-14, round 23)

Five more action ids landed in this tick, moving 5 rows from STUB
(implicit — the ids were not yet registered on the router) to WIRED:

| Action id | Fallback module (`pharos_editor.actions.*`) | Category |
|-----------|--------------------------------------------|----------|
| `layer.new`               | `layer_lifecycle_actions.create_layer`               | layer |
| `layer.delete`            | `layer_lifecycle_actions.delete_layer`               | layer |
| `snap.set_grid_size`      | `snap_set_grid_size_actions.set_grid_size`           | snap  |
| `view.toggle_ruler`       | `view_toggle_ruler_actions.toggle_ruler`             | view  |
| `spawn.at_last_position`  | `spawn_last_position_actions.spawn_at_last_position` | spawn |

New action modules:

* `python/pharos_engine/actions/layer_lifecycle_actions.py`
* `python/pharos_engine/actions/snap_set_grid_size_actions.py`
* `python/pharos_engine/actions/view_toggle_ruler_actions.py`
* `python/pharos_engine/actions/spawn_last_position_actions.py`

Router entries and `_fb_*` shims live in
`python/pharos_engine/tool_router.py` under the
`# ── VV4 STUB-triage: layer.new, layer.delete, snap.set_grid_size,
view.toggle_ruler, spawn.at_last_position (round 23) ──` block.

### Behavioural notes for VV4

* **`layer.new`** — Photoshop ``Ctrl+Shift+N`` / Krita ``Ins`` /
  Nova3D Layer-panel ``+`` button. Distinct from DD1's
  `edit.duplicate_layer` (which clones an existing layer) — this
  verb inserts a *fresh, empty* Z-layer. Name defaults to the
  first unused ``"Layer N"`` (matches Photoshop's "Layer 1 /
  Layer 2" pattern); explicit ``ctx["name"]`` overrides, and
  collisions get ``_2``, ``_3``… suffixes (matches the
  `layer_rename_actions._uniquify` convention). Z default is
  ``max(existing z) + 1.0`` so the new layer lands on top. Uses
  `scene.new_z_layer(name)` when the scene exposes a factory,
  else falls back to `scene.add_z_layer(layer)` with a
  ``SimpleNamespace`` stub so headless tests still see
  ``.name`` + ``.z``. Retargets `shell._active_layer` and fires
  ``_on_layer_added`` / ``_refresh_layer_panel``. Return contract:
  `no_scene` / `error` / `created` (with `name`, `z`, `collided`).
* **`layer.delete`** — Photoshop trash-can / Krita ``Del`` on the
  layer panel / Affinity Photo Layer → Delete Layer. Distinct from
  OO1's `layer.merge_down` (which collapses two layers into one and
  preserves both sets of entities). This verb **removes the layer
  entry** but leaves entities intact — mirrors Photoshop's
  "delete empty layer" flow. Refuses to remove the last remaining
  layer (`{"status": "last_layer"}`) so scenes never end up
  layer-less. Uses `scene.remove_z_layer(target)` when available
  else falls back to mutating `scene._z_layers` / `scene.z_layers`
  in place. Post-delete, `shell._active_layer` retargets to the
  immediate-below layer (or the new bottom when the deleted layer
  itself was the bottom). Return contract: `no_scene` /
  `no_layers` / `no_layer` / `last_layer` / `deleted` (with
  `target`, `z`, `next_active`).
* **`snap.set_grid_size`** — Blender N-panel numeric grid-size
  spinner / Unity ProGrids "Snap Value" input / Nova3D Snap-panel
  spin box. Distinct from OO1's `snap.increase_grid_size` /
  `snap.decrease_grid_size` (which walk the geometric ladder rung
  by rung) and UU4's `snap.set_angle_snap` (which sets the
  rotation-gizmo step, not the positional grid). Accepts
  ``ctx["size"]`` as a positive number clamped to ``[0.5, 4096.0]``
  — the same bounds as `snap_grid_size_actions` so the two verbs
  never disagree. Values within ``0.01`` of a canonical ladder rung
  (``0.5, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048,
  4096``) snap to the rung verbatim, matching Blender's "snap the
  snap-step" behaviour so a subsequent step-up lands cleanly. Zero
  and negatives are explicitly rejected as `invalid_size` (rather
  than silently clamped) so the caller can distinguish "no snap"
  (owned by `tools.snap_to_grid`) from a bogus write. Writes
  through `_snap_grid_size` / `_grid_size` / `grid_size`. Return
  contract: `missing_size` / `invalid_size` (with `value`) /
  `no_shell` / `unchanged` (with `value`) / `set` (with
  `previous`, `new`, `canonical`).
* **`view.toggle_ruler`** — Photoshop ``Ctrl+R`` / Illustrator
  ``Ctrl+R`` / Krita ``Ctrl+R`` / Affinity Photo ``Ctrl+R``. Sibling
  to CC1's `view.toggle_grid` / `view.toggle_gizmos`, QQ1's
  `view.toggle_stats`, PP1's `view.toggle_wireframe` — this owns
  the horizontal + vertical measurement bar overlay. Default state
  is **hidden** (matches Photoshop's factory-fresh state; users
  toggle it on demand — differs from `toggle_grid`/`toggle_gizmos`
  which default *on*). Stores state on `shell._ruler_visible`;
  fires the `_on_view_toggle` overlay-refresh hook. Return
  contract: `no_shell` / `toggled` (with `target`, `visible`,
  `previous`).
* **`spawn.at_last_position`** — Blender's "Snap Cursor to Last
  Position" + ``Shift+A`` compound gesture. Distinct from CC1's
  `spawn.repeat_last` (which *fires* the same spawn immediately by
  re-invoking `shell._on_spawn`) — this verb only *arms* the next
  drop coordinate on `shell._pending_spawn_position`, letting the
  user pick which prefab to place there. Also distinct from QQ1's
  `spawn.at_origin` (forced world zero), TT2's
  `spawn.at_view_center` (camera focus), UU4's
  `spawn.at_origin_offset` (origin + explicit delta). Position
  resolution walks five sources in priority order: override →
  `ctx["last_spawn"]` tuple → `shell._last_spawn_position` cache →
  `shell._last_spawn` tuple (CC1's slot) → menu tuple; every
  source is reported on the return dict as `"source"` so callers
  can distinguish which lane fired. Optional `ctx["offset"]` adds
  a delta — matches the `repeat_last` micro-offset knob so
  successive presses can build a chain. Return contract:
  `no_shell` / `no_history` / `armed` (with `position`, `source`,
  `offset`; `malformed_offset` when the offset was rejected).

Regression tests:
`SlapPyEngineTests/tests/test_actions_stub_triage_r23.py` — one
registration test per id (5 tests) plus a category assertion + a
singleton-check test (7 registration tests total) plus behavioural
coverage per module (~42 behavioural tests) plus a
ctx-validation parametrised sweep (5 tests). Total: 54 tests.
Combined with r15…r22 the r15…r23 dispatch surface is exercised
across ~290 tests.

## STUB roster unchanged

The 5 new WIRED rows are all NEW router entries — no previously-listed
STUB row (from the roster tracked in
`feature_map_delta_2026_07_06.md`) is affected. The DPG-shell-dependent
STUBs (HUD toggle, diary "Open…" file picker, inspector help popups,
theming save-as-new / import / export modals) remain untouched by VV4.

---

*Delta generated 2026-07-14 by VV4 STUB-triage agent (parallel-sprint
lane). Sources: UU4 (r22) baseline + VV4 commit.*
