"""``slappyengine.actions`` — headless-safe callbacks for editor menu actions.

Every ``ToolRouter`` action in :mod:`slappyengine.tool_router` that
mutates persistent state (project files, editor layout, entity clipboard)
lives here as a small pure Python helper so it can be unit-tested without
spinning up the DPG-backed editor shell.

Design provenance
-----------------

* ``docs/engine_feature_map_2026_07_04.md`` §"Top 10 Broken/Stub Fixes"
  identified five action ids that had no Python fallback wired in the
  router — this module is their landing site.
* ``docs/tool_routing_2026_06_07.md`` §5 recommends a per-action helper
  module so tests can invoke the callback with a synthetic ``ctx``
  dict (no shell, no DPG).

Each helper takes a single ``ctx: dict`` argument matching the router's
Python-fallback signature, resolves whichever shell / registry / clipboard
handle it needs from that dict (or falls back to a headless-safe default),
and returns a small result dict describing what happened. Return values
are used by the tests and by editor status-bar toast strings; a ``None``
return means "no-op" (missing dependency / cancelled by user).
"""
from __future__ import annotations

from .project_actions import (
    save_project as save_project,
    new_project as new_project,
    open_recent as open_recent,
)
from .view_actions import reset_layout as reset_layout
from .edit_actions import duplicate_selection as duplicate_selection
from .selection_actions import (
    select_all as select_all,
    deselect_all as deselect_all,
    copy_selection as copy_selection,
    paste_selection as paste_selection,
)
from .theme_actions import cycle_theme as cycle_theme
from .tool_settings_actions import (
    toggle_snap_to_grid as toggle_snap_to_grid,
)
from .camera_actions import (
    zoom_in as zoom_in,
    zoom_out as zoom_out,
    zoom_reset as zoom_reset,
)
from .theme_io_actions import (
    export_current_theme as export_current_theme,
)
from .destructive_edit_actions import (
    cut_selection as cut_selection,
    delete_selection as delete_selection,
)
from .viewport_framing_actions import (
    center_on_selection as center_on_selection,
    frame_all as frame_all,
)
from .tool_mode_actions import (
    activate_pan_tool as activate_pan_tool,
    PAN_TOOL_ID as PAN_TOOL_ID,
)
from .theme_import_actions import (
    import_from_file as import_theme_from_file,
)
from .layout_io_actions import (
    save_layout_as as save_layout_as,
    load_layout_from_file as load_layout_from_file,
)
from .history_actions import (
    undo as undo_action,
    redo as redo_action,
)
from .edit_by_name_actions import (
    select_by_name as select_by_name,
)
from .spawn_history_actions import (
    repeat_last as repeat_last_spawn,
    record_last_spawn as record_last_spawn,
)
from .view_toggle_actions import (
    toggle_grid as toggle_grid,
    toggle_gizmos as toggle_gizmos,
)
from .content_shell_actions import (
    copy_asset_path as copy_asset_path,
)
from .layer_duplicate_actions import (
    duplicate_layer as duplicate_layer,
)
from .theme_cycle_reverse_actions import (
    cycle_theme_reverse as cycle_theme_reverse,
)
from .panel_visibility_actions import (
    close_all_panels as close_all_panels,
    restore_last_hidden_panel as restore_last_hidden_panel,
)
from .spawn_batch_actions import (
    repeat_last_batch as repeat_last_batch,
)
from .capture_actions import (
    start_recording as start_recording,
    stop_recording as stop_recording,
    screenshot as screenshot,
)
from .render_toggle_actions import (
    enable_ssao as enable_ssao,
    enable_shadows as enable_shadows,
)
from .view_frame_selected_actions import (
    frame_selected as frame_selected,
)
from .view_reset_view_actions import (
    reset_view as reset_view,
)
from .panel_dock_actions import (
    dock_left as dock_left,
    dock_right as dock_right,
)
from .theme_hot_swap_actions import (
    hot_swap as hot_swap_theme,
)
from .layer_solo_actions import (
    solo_layer as solo_layer,
)
from .layer_merge_down_actions import (
    merge_down as merge_down_layer,
)
from .selection_grow_actions import (
    grow_selection as grow_selection,
)
from .snap_grid_size_actions import (
    increase_grid_size as increase_grid_size,
    decrease_grid_size as decrease_grid_size,
)
from .selection_shrink_actions import (
    shrink_selection as shrink_selection,
)
from .selection_invert_by_type_actions import (
    invert_by_type as invert_by_type,
)
from .view_toggle_wireframe_actions import (
    toggle_wireframe as toggle_wireframe,
)
from .edit_rename_actions import (
    rename_entity as rename_entity,
)
from .edit_duplicate_at_cursor_actions import (
    duplicate_at_cursor as duplicate_at_cursor,
)
from .spawn_origin_actions import (
    spawn_at_origin as spawn_at_origin,
)
from .selection_by_type_actions import (
    select_by_type as select_by_type,
)
from .selection_by_layer_actions import (
    select_by_layer as select_by_layer,
)
from .selection_same_material_actions import (
    select_same_material as select_same_material,
)
from .view_toggle_stats_actions import (
    toggle_stats as toggle_stats,
)
from .edit_select_similar_actions import (
    select_similar as select_similar,
)
from .theme_reset_default_actions import (
    reset_to_default as reset_theme_to_default,
)
from .layer_hide_others_actions import (
    hide_others as hide_others_layers,
)
from .layer_isolate_actions import (
    isolate as isolate_selection,
)
from .snap_toggle_incremental_actions import (
    toggle_incremental as toggle_snap_incremental,
)
from .content_reveal_explorer_actions import (
    reveal_in_explorer as reveal_asset_in_explorer,
)
from .content_duplicate_folder_actions import (
    duplicate_folder as duplicate_content_folder,
)
from .view_pixel_scale_actions import (
    increase_pixel_scale as increase_pixel_scale,
    decrease_pixel_scale as decrease_pixel_scale,
)
from .spawn_stamp_repeat_actions import (
    stamp_repeat as stamp_repeat_spawn,
)
from .view_set_zoom_actions import (
    set_zoom as set_view_zoom,
)
from .spawn_view_center_actions import (
    spawn_at_view_center as spawn_at_view_center,
)
from .spawn_stamp_random_actions import (
    stamp_random as stamp_random_spawn,
)
from .theme_reload_from_disk_actions import (
    reload_from_disk as reload_theme_from_disk,
)
from .layer_rename_actions import (
    rename_layer as rename_layer,
)
from .spawn_origin_offset_actions import (
    spawn_at_origin_offset as spawn_at_origin_offset,
)
from .edit_flatten_selection_actions import (
    flatten_selection as flatten_selection,
)
from .snap_angle_snap_actions import (
    set_angle_snap as set_angle_snap,
)
from .layer_reorder_actions import (
    move_layer_up as move_layer_up,
    move_layer_down as move_layer_down,
)


__all__ = [
    "save_project",
    "new_project",
    "open_recent",
    "reset_layout",
    "duplicate_selection",
    "select_all",
    "deselect_all",
    "copy_selection",
    "paste_selection",
    "cycle_theme",
    "toggle_snap_to_grid",
    "zoom_in",
    "zoom_out",
    "zoom_reset",
    "export_current_theme",
    "cut_selection",
    "delete_selection",
    "center_on_selection",
    "frame_all",
    "activate_pan_tool",
    "PAN_TOOL_ID",
    "import_theme_from_file",
    "save_layout_as",
    "load_layout_from_file",
    "undo_action",
    "redo_action",
    "select_by_name",
    "repeat_last_spawn",
    "record_last_spawn",
    "toggle_grid",
    "toggle_gizmos",
    "copy_asset_path",
    "duplicate_layer",
    "cycle_theme_reverse",
    "close_all_panels",
    "restore_last_hidden_panel",
    "repeat_last_batch",
    "start_recording",
    "stop_recording",
    "screenshot",
    "enable_ssao",
    "enable_shadows",
    "frame_selected",
    "reset_view",
    "dock_left",
    "dock_right",
    "hot_swap_theme",
    "solo_layer",
    "merge_down_layer",
    "grow_selection",
    "increase_grid_size",
    "decrease_grid_size",
    "shrink_selection",
    "invert_by_type",
    "toggle_wireframe",
    "rename_entity",
    "duplicate_at_cursor",
    "spawn_at_origin",
    "select_by_type",
    "select_by_layer",
    "select_same_material",
    "toggle_stats",
    "select_similar",
    "reset_theme_to_default",
    "hide_others_layers",
    "isolate_selection",
    "toggle_snap_incremental",
    "reveal_asset_in_explorer",
    "duplicate_content_folder",
    "increase_pixel_scale",
    "decrease_pixel_scale",
    "stamp_repeat_spawn",
    "set_view_zoom",
    "spawn_at_view_center",
    "stamp_random_spawn",
    "reload_theme_from_disk",
    "rename_layer",
    "spawn_at_origin_offset",
    "flatten_selection",
    "set_angle_snap",
    "move_layer_up",
    "move_layer_down",
]
