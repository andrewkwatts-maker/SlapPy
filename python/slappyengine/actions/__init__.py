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
]
