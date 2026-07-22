# Engine Feature Map — Delta Report (2026-07-05 → post-NN2)

Compact delta covering the NN2 STUB-triage sprint tick (round 15 after
r14's `capture_actions` + `render_toggle_actions` landings).

## NN2 STUB-triage patch (2026-07-05, round 15)

Five more action ids landed in this tick, moving 5 rows from STUB
(implicit — the ids were not yet registered on the router) to WIRED:

| Action id | Fallback module (`pharos_editor.actions.*`) | Category |
|-----------|--------------------------------------------|----------|
| `view.frame_selected`  | `view_frame_selected_actions.frame_selected` | view |
| `view.reset_view`      | `view_reset_view_actions.reset_view`         | view |
| `panel.dock_left`      | `panel_dock_actions.dock_left`               | panel |
| `panel.dock_right`     | `panel_dock_actions.dock_right`              | panel |
| `theme.hot_swap`       | `theme_hot_swap_actions.hot_swap`            | theme |

New action modules:

* `python/pharos_engine/actions/view_frame_selected_actions.py`
* `python/pharos_engine/actions/view_reset_view_actions.py`
* `python/pharos_engine/actions/panel_dock_actions.py`
* `python/pharos_engine/actions/theme_hot_swap_actions.py`

Router entries and `_fb_*` shims live in `python/pharos_engine/tool_router.py`
under the `# ── NN2 STUB-triage: frame-selected + reset-view + panel dock
L/R + theme hot-swap (round 15) ──` block.

### Behavioural notes for NN2

* **`view.frame_selected`** — Blender `.` (numpad period), Maya / Unreal /
  Unity `F`. Pans **and** zooms so the current selection tightly fits
  the viewport. Distinct from the already-wired
  `view.center_on_selection` (AA1 — pan only) and `view.frame_all` (AA1
  — whole scene). Distance is computed from the selection AABB
  bounding-sphere radius with a default `1.15` margin (overridable via
  `ctx["margin"]`). Return contract: `no_camera` / `no_selection` /
  `no_positions` / success `framed` (with `target`, `distance`,
  `radius`, `count`, `margin`).
* **`view.reset_view`** — Blender `Home`, Unreal `End`. Restores the
  viewport camera to a canonical home pose: target `(0, 0, 0)`,
  distance `5.0`, yaw / pitch `0`, projection `"perspective"`. All
  overridable via `ctx["target"]` / `ctx["distance"]` /
  `ctx["projection"]`. Distinct from `view.zoom_reset` (Z7 — zoom
  only). Return contract: `no_camera` / success `reset` (with
  `target`, `distance`, `yaw`, `pitch`, `projection`).
* **`panel.dock_left`** / **`panel.dock_right`** — Unity Layout / Unreal
  docking. Snaps the panel named `ctx["panel_id"]` (required) to the
  left / right edge of the viewport. Dock width defaults to `0.25` of
  viewport width (overridable via `ctx["width_ratio"]` or absolute
  `ctx["width_px"]`); clamped to `[120px, 75% of viewport]`. Write
  path: `shell.set_panel_rect` → `_panel_windows[id]` attributes →
  `_panel_layout_state[id]` attributes. Also records
  `shell._last_dock_side` and `shell._last_docked_panel` so a future
  `panel.restore_last_dock` could reverse. Return contract:
  `no_shell` / `no_panel_id` / `unknown_panel` / success `docked` (with
  `side`, `panel_id`, `rect`, `viewport`, `path`).
* **`theme.hot_swap`** — Unity Preferences → Themes dropdown, Blender
  Preferences → load theme preset. Applies the theme named
  `ctx["theme"]` (required str) directly, without cycling. Resolves via
  `pharos_editor.ui.theme.list_registered_themes` (and `get_theme` when
  present); dispatches through `shell.apply_theme` when the shell
  exposes it, else `pharos_editor.ui.theme.apply_theme`. Mirrors the
  new active theme onto `shell._active_theme` /
  `shell._current_theme` / `shell._theme_cursor` so subsequent
  `theme.cycle` calls continue from the new anchor. Return contract:
  `no_theme` / `unknown_theme` (with `available` roster) / `error`
  (theme module import failure) / `unchanged` / success `swapped`
  (with `previous`, `path`).

Regression tests: `SlapPyEngineTests/tests/test_actions_stub_triage_r15.py`
(31 tests, all passing). Combined
X3+Y1+Z7+AA1+BB1+CC1+DD1+EE1+FF1+GG1+II5+JJ6+KK7+MM6+NN2 wiring now
covers 72 previously-absent router action ids across 8 category
buckets (`file`, `edit`, `tool`, `view`, `theme`, `panel`, `spawn`,
`content`).

## STUB roster unchanged

The 5 new WIRED rows are all NEW router entries — no previously-listed
STUB row (from the 15-row roster tracked in `feature_map_delta_2026_07_04_v2.md`)
is affected. The DPG-shell-dependent STUBs (HUD toggle, diary
"Open…" file picker, inspector help popups, theming save-as-new /
import / export modals) remain untouched by NN2.

---

*Delta generated 2026-07-05 by NN2 STUB-triage agent (parallel-sprint
lane). Sources: `1e584e4` (r14 salvage baseline) + NN2 commit.*
