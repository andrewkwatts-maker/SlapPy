<!-- handauthored: do not regenerate -->
# slappyengine.actions — API Reference

> Hand-written reference for the `actions` subpackage — headless-safe
> callbacks backing every ``ToolRouter`` menu / hotkey / toolbar
> action that mutates persistent state. Owns the ``_fb_*`` fallback
> handlers the router dispatches into when the DPG editor shell is
> either absent (headless tests) or bypassed. Does **not** own the
> action registry itself (see :mod:`slappyengine.tool_router` and
> [`../tool_routing_2026_06_07.md`](../tool_routing_2026_06_07.md))
> or the higher-level shell (:class:`slappyengine.ui.editor.EditorShell`,
> [`ui_editor.md`](ui_editor.md)).

## Overview

Every :class:`~slappyengine.tool_router.ToolAction` row in
:data:`slappyengine.tool_router.REGISTRY` that mutates persistent
state (project files, editor layout, entity clipboard, theme
selection, capture recordings, view / selection state, snap grid,
layer stack, spawn history, panel visibility) lives here as a small
pure-Python helper so the router can dispatch to it without spinning
up the DPG editor shell.

Design provenance:

- ``docs/engine_feature_map_2026_07_04.md`` §"Top 10 Broken/Stub
  Fixes" identified the initial five action ids with no Python
  fallback — this module is their landing site.
- ``docs/tool_routing_2026_06_07.md`` §5 recommends a per-action
  helper module so tests can invoke the callback with a synthetic
  ``ctx`` dict (no shell, no DPG required).
- Subsequent STUB-triage rounds (OO1 / NN2 / PP1 / QQ1 / RR1 / TT2 —
  rollup progression under
  ``docs/feature_map_delta_2026_07_*.md``) grew the file count into
  the ~75-file layout you see today.

Each helper takes a single ``ctx: dict`` argument matching the
router's Python-fallback signature, resolves whichever shell /
registry / clipboard / capture / theme handle it needs from that
dict (or falls back to a headless-safe default), and returns a
small result dict describing what happened. Return values feed
both the pytest suite and the editor status-bar toast strings; a
``None`` return means "no-op" (missing dependency / user
cancellation).

## Public surface

```python
from slappyengine.actions import (
    # Project lifecycle
    save_project, new_project, open_recent,
    # Layout + panel
    reset_layout, dock_left, dock_right,
    close_all_panels, restore_last_hidden_panel,
    save_layout_as, load_layout_from_file,
    # Selection
    select_all, deselect_all,
    copy_selection, paste_selection,
    cut_selection, delete_selection,
    duplicate_selection, duplicate_at_cursor,
    select_by_name, select_by_type,
    select_by_layer, select_same_material,
    select_similar, grow_selection,
    shrink_selection, invert_by_type,
    # Theme
    cycle_theme, cycle_theme_reverse,
    hot_swap_theme, reset_theme_to_default,
    import_theme_from_file, export_current_theme,
    reload_theme_from_disk,
    # Camera + view
    zoom_in, zoom_out, zoom_reset,
    center_on_selection, frame_all,
    frame_selected, reset_view,
    set_view_zoom,
    toggle_grid, toggle_gizmos,
    toggle_wireframe, toggle_stats,
    increase_pixel_scale, decrease_pixel_scale,
    # History
    undo_action, redo_action,
    # Tool mode
    activate_pan_tool, PAN_TOOL_ID,
    toggle_snap_to_grid, toggle_snap_incremental,
    increase_grid_size, decrease_grid_size,
    # Spawn
    repeat_last_spawn, record_last_spawn,
    repeat_last_batch, stamp_repeat_spawn,
    stamp_random_spawn, spawn_at_origin,
    spawn_at_view_center,
    # Capture + render
    start_recording, stop_recording, screenshot,
    enable_ssao, enable_shadows,
    # Layer
    solo_layer, merge_down_layer,
    duplicate_layer, hide_others_layers,
    isolate_selection, rename_layer,
    # Content browser
    copy_asset_path, reveal_asset_in_explorer,
    duplicate_content_folder,
    # Rename
    rename_entity,
)
```

The full ``__all__`` list has ~75 entries; the block above groups
them by role for readability. Any symbol exposed from
``slappyengine.actions`` is guaranteed to be a
``ctx: dict -> dict | None`` callable (except :data:`PAN_TOOL_ID`,
which is a constant string tool identifier).

## Functions

Every action helper follows the same signature and return contract:

```python
def <action_helper>(ctx: dict) -> dict | None:
    ...
```

- `ctx` is a mapping (`dict` or `collections.ChainMap`) resolved by
  :func:`slappyengine.actions._ctx.ensure_ctx` — passing `None` or a
  non-mapping raises `TypeError` naming the caller.
- The return dict carries a `"status"` key describing the outcome
  (`"saved"` / `"created"` / `"no_project"` / `"missing_path"` /
  `"error"` / …). Return `None` means the helper detected a soft
  no-op (missing dependency / user cancellation) rather than an
  error condition.
- Filesystem / registry exceptions are swallowed and surfaced as
  `{"status": "error", "message": "..."}` so a failed action never
  crashes the router or the editor status bar.

### Representative helpers

Full surface is in the `Public surface` block; the four groups below
illustrate the standard shapes. See each ``*_actions.py`` file for
the exhaustive per-helper contract.

#### `save_project(ctx: dict) -> dict`

_defined in `slappyengine.actions.project_actions`_

Save the currently-loaded :class:`slappyengine.projects.Project`.
Search order: `ctx["project"]` → `ctx["shell"]._project` →
`ctx["shell"]._engine._project_manager._project`.

- `{"status": "saved", "path": "..."}` on success.
- `{"status": "no_project"}` when nothing is loaded.
- `{"status": "error", "message": "..."}` on filesystem failure.

#### `copy_selection(ctx: dict) -> dict`

_defined in `slappyengine.actions.selection_actions`_

Copy the current selection onto the entity clipboard read from
`ctx["clipboard"]` (falling back to a shell-owned clipboard). The
router hands the reversed operation to
:func:`paste_selection`.

#### `cycle_theme(ctx: dict) -> dict`

_defined in `slappyengine.actions.theme_actions`_

Advance the ThemeSpec registry cursor one slot forward, wrapping at
the end. `cycle_theme_reverse` walks backwards; `hot_swap_theme`
takes a `ctx["theme_name"]` override; `reset_theme_to_default`
resets to the shipping default; `reload_theme_from_disk` reloads
without changing which theme is active.

#### `undo_action(ctx: dict) -> dict`

_defined in `slappyengine.actions.history_actions`_

Pop one entry off the editor undo stack. `redo_action` is the
inverse. Both are no-ops if the stack is empty.

## Constants

### `PAN_TOOL_ID`

_`str` — defined in `slappyengine.actions.tool_mode_actions`_

Value: the canonical tool identifier the router passes to
:func:`activate_pan_tool` when the user picks the pan tool. Exposed
so tests can drive the tool-mode switch without knowing the
underlying string.

## Inner modules

Grouped by responsibility. Every file matches the pattern
`slappyengine.actions.<topic>_actions` and lands one topic-scoped
set of helpers.

- **Project lifecycle** — `project_actions`.
- **Layout + panel** — `layout_io_actions`, `panel_dock_actions`,
  `panel_visibility_actions`, `panel_close_others_actions`,
  `panel_layout_actions`.
- **Selection** — `selection_actions`, `selection_by_type_actions`,
  `selection_by_layer_actions`, `selection_same_material_actions`,
  `selection_grow_actions`, `selection_shrink_actions`,
  `selection_invert_by_type_actions`, `edit_select_similar_actions`,
  `edit_select_children_actions`, `edit_select_next_actions`,
  `edit_select_by_kind_actions`, `edit_by_name_actions`.
- **Edit + destructive** — `edit_actions`, `destructive_edit_actions`,
  `edit_duplicate_at_cursor_actions`, `edit_rename_actions`,
  `edit_group_actions`, `edit_hide_show_actions`,
  `edit_lock_unlock_actions`, `edit_mirror_actions`,
  `edit_paste_original_actions`, `edit_snap_pixel_actions`.
- **Theme** — `theme_actions`, `theme_cycle_reverse_actions`,
  `theme_hot_swap_actions`, `theme_import_actions`,
  `theme_io_actions`, `theme_random_actions`,
  `theme_reload_actions`, `theme_reload_from_disk_actions`,
  `theme_reset_default_actions`.
- **View + camera** — `view_actions`, `view_frame_selected_actions`,
  `view_reset_view_actions`, `view_set_zoom_actions`,
  `view_toggle_actions`, `view_toggle_stats_actions`,
  `view_toggle_wireframe_actions`, `view_pixel_scale_actions`,
  `view_fullscreen_actions`, `view_orbit_actions`,
  `view_snap_actions`, `viewport_framing_actions`,
  `camera_actions`, `camera_animation_actions`.
- **History** — `history_actions`.
- **Tool mode + snap** — `tool_mode_actions`, `tool_settings_actions`,
  `snap_grid_size_actions`, `snap_toggle_incremental_actions`.
- **Spawn** — `spawn_batch_actions`, `spawn_batch_row_actions`,
  `spawn_cursor_actions`, `spawn_history_actions`,
  `spawn_origin_actions`, `spawn_stamp_random_actions`,
  `spawn_stamp_repeat_actions`, `spawn_view_center_actions`.
- **Capture + render** — `capture_actions`, `render_toggle_actions`.
- **Layer** — `layer_duplicate_actions`, `layer_hide_others_actions`,
  `layer_isolate_actions`, `layer_merge_down_actions`,
  `layer_rename_actions`, `layer_solo_actions`.
- **Content browser** — `content_delete_actions`,
  `content_duplicate_asset_actions`,
  `content_duplicate_folder_actions`, `content_folder_actions`,
  `content_rename_actions`, `content_reveal_explorer_actions`,
  `content_shell_actions`.
- **Shared** — `_ctx` (owns :func:`_ctx.ensure_ctx` — the single
  canonical `ctx: dict` rejection point that raises `TypeError` on
  `None` / non-mapping input).

## Usage

```python
from slappyengine.actions import (
    save_project, cycle_theme, copy_selection, paste_selection,
)

# Headless test — no shell, no DPG.
ctx = {"project": my_project}
result = save_project(ctx)
assert result["status"] == "saved"

# Clipboard round-trip.
buf: list = []
ctx = {"shell": my_shell, "clipboard": buf}
copy_selection(ctx)
paste_selection(ctx)

# Theme advance driven from a hotkey handler.
cycle_theme({"shell": my_shell})
```

## Skip the wrapper

`slappyengine.actions` is pure Python — no runtime work lives in
Rust. Grep of `slappyengine._core_facade.RUST_MODULE_MAP` shows
**no** `actions` entry.

The router that dispatches into these helpers
(:mod:`slappyengine.tool_router`) is *also* pure Python and by
design allows a Python fallback to shadow any Rust-backed action —
the design intent is to let the editor / games monkeypatch a helper
without needing a rebuilt wheel. Callers who want to invoke an
action from a game / test without going through
:class:`~slappyengine.tool_router.ToolRouter` can import the helper
directly from `slappyengine.actions` and pass a synthetic `ctx`
dict — this is the officially supported bypass path.

## Conventions

- **`ctx: dict` contract.** Every helper accepts a single mapping
  argument; :func:`_ctx.ensure_ctx` raises `TypeError` on `None` or
  non-mapping input so a broken caller can't silently no-op forever
  (BB2 silent-acceptance hardening).
- **Return dicts, not exceptions.** Filesystem / registry failures
  are caught and returned as
  `{"status": "error", "message": "..."}`. The router surfaces the
  message in the status bar.
- **`None` return means "soft no-op".** A missing shell / registry
  / capture handle returns `None`; only structural bugs raise.
- **One topic per file.** New action ids land in a new
  `<topic>_actions.py` file rather than growing an existing one — a
  70-file layout is intentional so `git blame` scoping stays clean
  across the STUB-triage rounds.

## See also

- [`ui_editor.md`](ui_editor.md) — the notebook-editor shell that
  hosts most callers of these helpers.
- [`../tool_routing_2026_06_07.md`](../tool_routing_2026_06_07.md) —
  the audit that motivated the per-action-helper split.
- [`../engine_feature_map_2026_07_04.md`](../engine_feature_map_2026_07_04.md)
  — the wired-vs-stub row for each action id.
- [`../feature_map_delta_2026_07_07.md`](../feature_map_delta_2026_07_07.md),
  [`../feature_map_delta_2026_07_08.md`](../feature_map_delta_2026_07_08.md),
  [`../feature_map_delta_2026_07_09.md`](../feature_map_delta_2026_07_09.md),
  [`../feature_map_delta_2026_07_10.md`](../feature_map_delta_2026_07_10.md),
  [`../feature_map_delta_2026_07_12.md`](../feature_map_delta_2026_07_12.md)
  — successive STUB-triage rollups that added the newer action ids.
