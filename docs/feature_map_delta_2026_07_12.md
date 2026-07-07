# Engine Feature Map — Delta Report (2026-07-12 → post-TT2)

Compact delta covering the TT2 STUB-triage sprint tick (round 21 after
SS1's round-20 ``content.reveal_in_explorer`` /
``content.duplicate_folder`` / ``view.increase_pixel_scale`` /
``view.decrease_pixel_scale`` / ``spawn.stamp_repeat`` batch).

## TT2 STUB-triage patch (2026-07-12, round 21)

Five more action ids landed in this tick, moving 5 rows from STUB
(implicit — the ids were not yet registered on the router) to WIRED:

| Action id | Fallback module (`slappyengine.actions.*`) | Category |
|-----------|--------------------------------------------|----------|
| `view.set_zoom`            | `view_set_zoom_actions.set_zoom`                          | view |
| `spawn.at_view_center`     | `spawn_view_center_actions.spawn_at_view_center`          | spawn |
| `spawn.stamp_random`       | `spawn_stamp_random_actions.stamp_random`                 | spawn |
| `theme.reload_from_disk`   | `theme_reload_from_disk_actions.reload_from_disk`         | theme |
| `layer.rename`             | `layer_rename_actions.rename_layer`                       | layer |

New action modules:

* `python/slappyengine/actions/view_set_zoom_actions.py`
* `python/slappyengine/actions/spawn_view_center_actions.py`
* `python/slappyengine/actions/spawn_stamp_random_actions.py`
* `python/slappyengine/actions/theme_reload_from_disk_actions.py`
* `python/slappyengine/actions/layer_rename_actions.py`

Router entries and `_fb_*` shims live in
`python/slappyengine/tool_router.py` under the
`# ── TT2 STUB-triage: view.set_zoom, spawn.at_view_center,
spawn.stamp_random, theme.reload_from_disk, layer.rename (round 21) ──`
block.

### Behavioural notes for TT2

* **`view.set_zoom`** — Blender ``N``-panel numeric zoom field / Unity
  Scene camera "size" input / Nova3D's ``Camera → Zoom…`` dialog.
  Distinct from Z7's `view.zoom_in` / `view.zoom_out` (multiplicative
  step) + Z7's `view.zoom_reset` (snap to hard-coded default) — this
  verb jumps the continuous camera zoom to a caller-supplied *absolute*
  distance. Distinct from SS1's `view.increase_pixel_scale` /
  `view.decrease_pixel_scale` (which target the integer framebuffer
  pixel-scale factor, not the camera zoom). Shares the
  `_cam_distance` / `_zoom_level` walk + safety clamp with Z7 so the
  headless camera-fixture pattern carries over. Return contract:
  `missing_distance` / `no_camera` / `set` (with `distance`, `previous`,
  `path`).
* **`spawn.at_view_center`** — Blender ``Shift+A`` after
  ``Shift+S → Cursor to World Origin`` / Unity `GameObject → Align
  with View` / Nova3D `Spawn at Camera Focus`. Distinct from EE1's
  `spawn.spawn_at_cursor` (mouse-cursor position — moves with the
  pointer) + QQ1's `spawn.at_origin` (always world zero, never follows
  the camera). Resolves the focal point from
  `shell.get_view_center_world_position()` →
  `shell._view_center_world_position` →
  `shell._viewport_panel._cam_target` → world origin fallback.
  Supports both ``mode="arm"`` (default — stashes on
  `shell._pending_spawn_position`) and ``mode="repeat"`` (re-fires
  `_last_spawn` at the focus). Return contract: `no_shell` /
  `armed` (with `position`) / `respawned` (with `card_id`, `spec`,
  `position`).
* **`spawn.stamp_random`** — Aseprite palette scatter / Blender's
  `Object → Scatter` / Nova3D `Terrain → Randomised Prop Brush`.
  Distinct from CC1's `spawn.repeat_last` (single one-shot last card),
  II5's `spawn.spawn_batch_row` (deterministic straight line, same
  card), and SS1's `spawn.stamp_repeat` (deterministic stride, same
  card). This variant draws each of N stamps uniformly at random from
  a palette resolved via `ctx["palette"]` → `shell._stamp_history`
  entries → `shell._last_spawn` (degenerate 1-item palette).
  ``ctx["seed"]`` pins the PRNG for reproducibility. Return contract:
  `no_shell` / `no_history` / `stamped` (with `count`, `stride`,
  `picks`) / `error` (with `message`, plus partial `picks`).
* **`theme.reload_from_disk`** — Blender's per-addon "Reload Scripts",
  Godot's `Editor → Theme → Reload From Disk`, Substance Painter's
  `Refresh Shelf`. Distinct from FF1's `theme.reload_all` (which
  flushes the *whole* registry and rebakes builtins) + RR1's
  `theme.reset_to_default` (which never touches disk). This verb is
  the *targeted* single-theme hot-reload — re-parses one
  `*.theme.yaml`, registers the fresh spec, and in-place re-applies
  it when the reloaded theme is the current active one. Path
  resolution walks `ctx["path"]` → `ctx["theme_name"]` looked up
  against `shell._theme_paths` / `shell._user_theme_store.path_of()` →
  active theme's `source_path`. Return contract: `no_path` /
  `missing` (with `path`) / `error` (with `message`) / `reloaded`
  (with `theme`, `path`, `reactivated`).
* **`layer.rename`** — Photoshop Layers panel double-click / Krita's
  "Rename Layer" / Nova3D Layer panel right-click "Rename". Distinct
  from PP1's `edit.rename` (which renames selected *entities*) + FF1's
  `content.rename_asset` (which renames a *file / folder on disk*).
  This verb targets the scene's Z-layer stack — renames a layer in
  place, honouring the same name-validation guards as PP1
  (rejects whitespace-only names + names containing path separators)
  and uniquifies with a `_2`, `_3`, … suffix on collision (matches
  content_duplicate_folder's uniquify). Target resolution walks
  `ctx["layer"]` → `ctx["layer_name"]` looked up against
  `scene.z_layers` → `shell._active_layer`. Return contract:
  `no_scene` / `no_layer` / `no_layers` / `missing_name` /
  `invalid_name` / `unchanged` / `renamed` (with `target`, `new`,
  `collided`).

Regression tests:
`SlapPyEngineTests/tests/test_actions_stub_triage_r21.py` — one
registration test per id (5 tests) plus a category assertion + a
singleton-check test (7 registration tests total) plus behavioural
coverage per module (~37 behavioural tests, one theme-reload YAML
round-trip auto-skipped when the DPG-free environment can't register
themes). Combined with r15+r16+r17+r18+r19+r20, the r15…r21 dispatch
surface is exercised across ~200 tests.

## STUB roster unchanged

The 5 new WIRED rows are all NEW router entries — no previously-listed
STUB row (from the roster tracked in
`feature_map_delta_2026_07_06.md`) is affected. The DPG-shell-dependent
STUBs (HUD toggle, diary "Open…" file picker, inspector help popups,
theming save-as-new / import / export modals) remain untouched by TT2.

---

*Delta generated 2026-07-12 by TT2 STUB-triage agent (parallel-sprint
lane). Sources: SS1 (r20) baseline + TT2 commit.*
