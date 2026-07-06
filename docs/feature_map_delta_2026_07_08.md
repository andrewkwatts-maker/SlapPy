# Engine Feature Map — Delta Report (2026-07-08 → post-PP1)

Compact delta covering the PP1 STUB-triage sprint tick (round 17 after
OO1's round-16 ``layer.solo`` / ``layer.merge_down`` / ``selection.grow``
/ ``snap.increase_grid_size`` / ``snap.decrease_grid_size`` batch).

## PP1 STUB-triage patch (2026-07-08, round 17)

Five more action ids landed in this tick, moving 5 rows from STUB
(implicit — the ids were not yet registered on the router) to WIRED:

| Action id | Fallback module (`slappyengine.actions.*`) | Category |
|-----------|--------------------------------------------|----------|
| `selection.shrink`          | `selection_shrink_actions.shrink_selection`               | selection |
| `selection.invert_by_type`  | `selection_invert_by_type_actions.invert_by_type`         | selection |
| `view.toggle_wireframe`     | `view_toggle_wireframe_actions.toggle_wireframe`          | view |
| `edit.rename`               | `edit_rename_actions.rename_entity`                       | edit |
| `edit.duplicate_at_cursor`  | `edit_duplicate_at_cursor_actions.duplicate_at_cursor`    | edit |

New action modules:

* `python/slappyengine/actions/selection_shrink_actions.py`
* `python/slappyengine/actions/selection_invert_by_type_actions.py`
* `python/slappyengine/actions/view_toggle_wireframe_actions.py`
* `python/slappyengine/actions/edit_rename_actions.py`
* `python/slappyengine/actions/edit_duplicate_at_cursor_actions.py`

Router entries and `_fb_*` shims live in
`python/slappyengine/tool_router.py` under the
`# ── PP1 STUB-triage: selection shrink / invert-by-type + view
wireframe + edit rename / duplicate-at-cursor (round 17) ──` block.

### Behavioural notes for PP1

* **`selection.shrink`** — Blender ``Ctrl+Numpad-`` / Photoshop
  ``Select → Contract``. Inverse of OO1's `selection.grow`: drops
  every *boundary* entity from the selection (an entity is on the
  boundary when any non-selected neighbour sits within
  `ctx["radius"]`, default `64.0` scene units, `1e9` max). Return
  contract: `no_scene` / `no_selection` / `unchanged` (every selected
  entity was interior) / `emptied` (every selected entity was on the
  boundary) / `shrunk` (with `selection`, `removed`, `previous_count`,
  `radius`).
* **`selection.invert_by_type`** — Blender ``Select → All by Type``.
  Reads the kind of every seed entity (via the
  `kind` → `prefab_kind` → `type` → `type(entity).__name__` fallback
  chain), then *replaces* the selection with every scene entity whose
  kind matches — excluding the seed entities so the result is a true
  "invert". Return contract: `no_scene` / `no_selection` /
  `no_matches` (with `kinds`, `previous_count`) / `inverted` (with
  `selection`, `kinds`, `added`, `previous_count`).
* **`view.toggle_wireframe`** — Blender ``Z → Wireframe``. Flips
  `shell._wireframe_visible` and best-effort fires
  `shell._on_view_toggle("_wireframe_visible", new_value)`. Same
  behaviour shape as CC1's `view.toggle_grid` / `view.toggle_gizmos`;
  defaults to `False` (overlay off) rather than `True` since
  wireframe is normally an opt-in mode. Return contract: `no_shell`
  (no shell + no `visible` seed) / `toggled` (with `target`,
  `visible`, `previous`).
* **`edit.rename`** — Unity / Blender ``F2`` rename-entity. Distinct
  from FF1's `content.rename_asset` (which renames files on disk).
  Renames the resolved target(s) — a single-entity resolve stamps
  the raw name; a multi-entity resolve appends a zero-padded numeric
  suffix (`row` → `row_01`, `row_02`, …) so sibling entities don't
  collide. Whitespace-only names and names containing path separators
  are rejected with `invalid_name` so a "rename" flow can't
  accidentally do a scene-graph re-parent. Return contract:
  `missing_name` / `no_selection` / `invalid_name` /
  `renamed` (with `renamed` old→new pairs, `count`).
* **`edit.duplicate_at_cursor`** — Blender ``Shift+D``. Distinct from
  JJ6's `edit.duplicate_selection` (which clones in-place with a
  ` (copy)` suffix). Clones the selection via `EntityClipboard`
  (identical snapshot path as `edit.duplicate_selection`) and then
  translates every clone so the *first* clone lands at the resolved
  cursor world-position; subsequent clones preserve their original
  offset relative to the first entity, so a multi-select maintains
  its shape. Cursor resolution reuses the r8
  `spawn_cursor_actions._resolve_cursor` chain
  (`ctx["cursor"]` → `shell.get_cursor_world_position()` →
  `shell._cursor_world_position` → `shell._last_cursor`). Return
  contract: `no_selection` / `no_cursor` / `error` /
  `duplicated_at_cursor` (with `count`, `clones`, `cursor`,
  `translated`, `added`).

Regression tests:
`SlapPyEngineTests/tests/test_actions_stub_triage_r17.py` — 34 tests,
all passing. Combined with r15 (31), r16 (29), the r15+r16+r17 dispatch
surface is exercised across ~94 tests.

## STUB roster unchanged

The 5 new WIRED rows are all NEW router entries — no previously-listed
STUB row (from the roster tracked in
`feature_map_delta_2026_07_06.md`) is affected. The DPG-shell-dependent
STUBs (HUD toggle, diary "Open…" file picker, inspector help popups,
theming save-as-new / import / export modals) remain untouched by PP1.

---

*Delta generated 2026-07-08 by PP1 STUB-triage agent (parallel-sprint
lane). Sources: `e27627d` (r16 baseline) + PP1 commit.*
