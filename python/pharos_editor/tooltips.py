"""Tooltip registry (Sprint 9 UI polish #1).

Central lookup ``widget_id -> (tooltip, keyboard_shortcut)``. Panels
register their tooltips at build time; the shell renders them after a
500 ms hover delay. Nova3D shipped ad-hoc `dpg.tooltip(...)` calls
scattered through every panel; centralising the registry keeps
localisation + accessibility (screen reader hints, WCAG label text)
in one place.
"""
from __future__ import annotations

from dataclasses import dataclass


HOVER_DELAY_MS: int = 500


@dataclass(frozen=True)
class TooltipEntry:
    tip: str
    shortcut: str = ""

    def render(self) -> str:
        if self.shortcut:
            return f"{self.tip}   ({self.shortcut})"
        return self.tip


class TooltipRegistry:
    """One instance per editor shell. Populated at panel-build time."""

    def __init__(self) -> None:
        self._entries: dict[str, TooltipEntry] = {}

    def register(self, widget_id: str, tip: str, shortcut: str = "") -> None:
        self._entries[widget_id] = TooltipEntry(tip=tip, shortcut=shortcut)

    def lookup(self, widget_id: str) -> TooltipEntry | None:
        return self._entries.get(widget_id)

    def all(self) -> list[tuple[str, TooltipEntry]]:
        return sorted(self._entries.items())

    def bulk_register(self, table: dict[str, tuple[str, str]]) -> None:
        """Bulk-populate from a ``{widget_id: (tip, shortcut)}`` mapping."""
        for wid, (tip, shortcut) in table.items():
            self.register(wid, tip, shortcut)


# Curated defaults — the shell instantiates a registry and applies
# these before panels can override or extend.
DEFAULT_TOOLTIPS: dict[str, tuple[str, str]] = {
    # Toolbar
    "tool_select":    ("Select tool — drag to marquee", "V"),
    "tool_move":      ("Move / translate selected entities", "G"),
    "tool_rotate":    ("Rotate selected entities", "R"),
    "tool_scale":     ("Scale selected entities", "S"),
    "toggle_snap":    ("Toggle grid snap", "Shift+Tab"),
    "toggle_2d_3d":   ("Toggle 2D / 3D viewport mode", "5"),

    # File / project
    "file_new":       ("Create a new project", "Ctrl+N"),
    "file_open":      ("Open an existing project", "Ctrl+O"),
    "file_save":      ("Save current project", "Ctrl+S"),
    "file_save_as":   ("Save current project as...", "Ctrl+Shift+S"),

    # Edit
    "edit_undo":      ("Undo last action", "Ctrl+Z"),
    "edit_redo":      ("Redo last undone action", "Ctrl+Shift+Z"),
    "edit_copy":      ("Copy selected entities", "Ctrl+C"),
    "edit_paste":     ("Paste from clipboard", "Ctrl+V"),
    "edit_duplicate": ("Duplicate selected entities", "Ctrl+D"),
    "edit_delete":    ("Delete selected entities", "Del"),
    "edit_select_all": ("Select all entities", "Ctrl+A"),

    # Outliner right-click actions (Sprint 9 #2)
    "outliner_rename":      ("Rename entity", "F2"),
    "outliner_group":       ("Group selected entities under a parent", "Ctrl+G"),
    "outliner_isolate":     ("Hide everything else in the outliner", "Alt+H"),
    "outliner_copy_xform":  ("Copy transform to clipboard", ""),
    "outliner_paste_xform": ("Paste transform from clipboard", ""),
    "outliner_frame":       ("Frame in viewport", "F"),

    # Content browser (Sprint 9 #5)
    "content_back":     ("Back", "Alt+Left"),
    "content_forward":  ("Forward", "Alt+Right"),
    "content_up":       ("Parent folder", "Alt+Up"),
    "content_home":     ("Project root", "Alt+Home"),
    "content_search":   ("Search assets by name", "Ctrl+F"),
}


__all__ = [
    "HOVER_DELAY_MS",
    "TooltipEntry",
    "TooltipRegistry",
    "DEFAULT_TOOLTIPS",
]
