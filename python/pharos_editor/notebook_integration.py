"""Sprint 8: notebook shell wiring for the Sprint 9 UI primitives.

Ties the seven usability primitives (tooltips, context menu, clipboard,
multiselect, breadcrumbs, recently_used, command_stack) into the
notebook panels through a single install-once entry point.

Panels stay slim — they just import ``install_all(shell)`` and let the
integration decide which primitives to bind and how. Downstream tests
mock ``shell`` + panel objects and assert on the resulting bindings.

Usage — call once at shell boot::

    from pharos_editor.notebook_integration import install_all
    install_all(shell)

Individual installers (``install_outliner``, ``install_content_browser``,
``install_spawn_menu``, ``install_inspector``, ``install_hotkeys``) can
also be called separately when only one panel needs wiring.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-panel installers
# ---------------------------------------------------------------------------


def install_outliner(shell: Any) -> dict[str, Any]:
    """Wire ContextMenuBinder, MultiSelectModel, TooltipRegistry into the
    active NotebookOutliner (or any object exposing the same duck-type).
    """
    outliner = _resolve_panel(shell, "outliner", "_outliner", "notebook_outliner")
    if outliner is None:
        return {}
    from pharos_editor.context_menu import ContextMenuBinder, OUTLINER_ACTIONS
    from pharos_editor.multiselect import MultiSelectModel
    from pharos_editor.tooltips import TooltipRegistry

    if getattr(outliner, "_context_menu", None) is None:
        outliner._context_menu = ContextMenuBinder(OUTLINER_ACTIONS)
    if getattr(outliner, "_multiselect", None) is None:
        outliner._multiselect = MultiSelectModel()
    if getattr(outliner, "_tooltips", None) is None:
        outliner._tooltips = TooltipRegistry()
    return {
        "context_menu": outliner._context_menu,
        "multiselect": outliner._multiselect,
        "tooltips": outliner._tooltips,
    }


def install_content_browser(shell: Any, project_root: Any = None) -> Any:
    """Wire BreadcrumbHistory into the content browser panel."""
    panel = _resolve_panel(shell, "content_browser", "_content_browser",
                           "notebook_content_browser")
    if panel is None:
        return None
    from pharos_editor.breadcrumbs import BreadcrumbHistory
    if getattr(panel, "_breadcrumbs", None) is None:
        panel._breadcrumbs = BreadcrumbHistory(root=project_root)
    return panel._breadcrumbs


def install_spawn_menu(shell: Any, project: Any = None) -> Any:
    """Wire RecentSpawns as the "top section" of the spawn menu.

    Attaches the RecentSpawns instance on `panel._recent` and pins the
    ``project`` id under `panel._recent_project` so downstream code can
    call ``panel._recent.get(panel._recent_project)`` for the MRU list.
    """
    panel = _resolve_panel(shell, "spawn_menu", "_spawn_menu",
                           "notebook_spawn_menu")
    if panel is None:
        return None
    from pharos_editor.recently_used import RecentSpawns
    if getattr(panel, "_recent", None) is None:
        panel._recent = RecentSpawns()
        panel._recent_project = str(project) if project is not None else ""
    return panel._recent


def install_inspector(shell: Any) -> Any:
    """Wire the module-level ``Clipboard`` onto the inspector so Ctrl+C
    of the transform section copies a ``ClipboardPayload``.
    """
    panel = _resolve_panel(shell, "inspector", "_inspector",
                           "notebook_inspector")
    if panel is None:
        return None
    from pharos_editor.clipboard import Clipboard
    # Panel exposes a `copy_transform` method that packages the current
    # selection into a payload; the integration binds the actual copy
    # call to Clipboard.copy.
    if getattr(panel, "_clipboard", None) is None:
        panel._clipboard = Clipboard
    return Clipboard


def install_hotkeys(shell: Any) -> dict[str, str]:
    """Wire Ctrl+Z / Ctrl+Shift+Z / Ctrl+C / Ctrl+V into the shell.

    Returns the effective keymap so tests can assert on it.
    """
    from pharos_editor.command_stack import CommandStack

    if getattr(shell, "_command_stack", None) is None:
        shell._command_stack = CommandStack()

    # Observers refresh the Edit menu's undo / redo label state.
    def _on_stack_change() -> None:
        edit_menu = getattr(shell, "_edit_menu", None)
        if edit_menu is None:
            return
        try:
            edit_menu.refresh_undo_state(shell._command_stack)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("edit_menu refresh raised %s", exc)
    shell._command_stack.on_change(_on_stack_change)

    keymap = {
        "Ctrl+Z":       "commandstack.undo",
        "Ctrl+Shift+Z": "commandstack.redo",
        "Ctrl+C":       "clipboard.copy",
        "Ctrl+V":       "clipboard.paste",
    }
    existing = getattr(shell, "_hotkeys", None)
    if existing is None:
        shell._hotkeys = dict(keymap)
    else:
        for k, v in keymap.items():
            existing.setdefault(k, v)
    return shell._hotkeys


def install_all(shell: Any, *, project: Any = None, project_root: Any = None
                ) -> dict[str, Any]:
    """One-shot: wire every primitive available on the given shell."""
    return {
        "outliner":        install_outliner(shell),
        "content_browser": install_content_browser(shell, project_root=project_root),
        "spawn_menu":      install_spawn_menu(shell, project=project),
        "inspector":       install_inspector(shell),
        "hotkeys":         install_hotkeys(shell),
    }


# ---------------------------------------------------------------------------
# Panel resolution — tolerant of the multiple attribute-name conventions
# the shell uses across its DPG panels.
# ---------------------------------------------------------------------------


def _resolve_panel(shell: Any, *candidates: str) -> Any:
    for name in candidates:
        panel = getattr(shell, name, None)
        if panel is not None:
            return panel
    panels = getattr(shell, "_panels", None)
    if isinstance(panels, dict):
        for name in candidates:
            if name in panels:
                return panels[name]
    return None


__all__ = [
    "install_all",
    "install_outliner",
    "install_content_browser",
    "install_spawn_menu",
    "install_inspector",
    "install_hotkeys",
]
