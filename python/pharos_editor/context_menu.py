"""Outliner right-click context menu (Sprint 9 UI polish #2).

Nova3D had no right-click on outliner rows; users needed the top menu
bar or hotkeys. Pharos ships the seven actions from the audit doc as
a data table so panels can render them consistently — the outliner,
the viewport gizmo, and future graph editors all render the same
menu on right-click.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class MenuAction:
    """One entry in a right-click menu."""

    action_id: str
    label: str
    shortcut: str = ""
    enabled: bool = True
    separator_after: bool = False


# Seven actions from docs/ui_nesting_audit_2026_06_07.md §4.2. The
# actual callables live in pharos_editor.actions; the panel wires
# menu -> action -> command_stack push.
OUTLINER_ACTIONS: list[MenuAction] = [
    MenuAction("outliner_rename",         "Rename",          "F2"),
    MenuAction("outliner_duplicate",      "Duplicate",       "Ctrl+D"),
    MenuAction("outliner_delete",         "Delete",          "Del", separator_after=True),
    MenuAction("outliner_group",          "Group",           "Ctrl+G"),
    MenuAction("outliner_isolate",        "Isolate",         "Alt+H", separator_after=True),
    MenuAction("outliner_copy_xform",     "Copy Transform"),
    MenuAction("outliner_paste_xform",    "Paste Transform"),
    MenuAction("outliner_frame",          "Frame in Viewport", "F"),
]


class ContextMenuBinder:
    """Bridges a static ``MenuAction`` table to callback functions.

    Panels create one instance, register callbacks for each
    ``action_id``, then hand the bound menu to the widget layer.
    """

    def __init__(self, actions: list[MenuAction]) -> None:
        self.actions = actions
        self._callbacks: dict[str, Callable[[str], None]] = {}

    def bind(self, action_id: str, callback: Callable[[str], None]) -> None:
        self._callbacks[action_id] = callback

    def invoke(self, action_id: str, entity_id: str) -> None:
        cb = self._callbacks.get(action_id)
        if cb is None:
            from pharos_editor.errors import route
            route(
                NotImplementedError(f"context menu {action_id} has no callback"),
                f"context_menu.invoke.{action_id}",
                level="warn",
            )
            return
        try:
            cb(entity_id)
        except Exception as exc:
            from pharos_editor.errors import route
            route(exc, f"context_menu.callback.{action_id}")


__all__ = ["MenuAction", "OUTLINER_ACTIONS", "ContextMenuBinder"]
