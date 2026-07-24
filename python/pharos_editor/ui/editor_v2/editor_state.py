"""Shared editor state passed to every v2 panel.

One instance per editor process. Owns cross-panel state that would
otherwise be threaded through constructor arguments:

- **selection** — via :class:`pharos_editor.multiselect.MultiSelectModel`
  so Ctrl/Shift click works across Hierarchy + Viewport.
- **command stack** — undo/redo shared across every panel that mutates
  the scene.
- **clipboard** — Ctrl+C / Ctrl+V, matches v1's
  :class:`pharos_editor.clipboard.Clipboard`.
- **theme** — swap at runtime; every panel observing the state reacts.
- **engine** — the pharos_engine.Engine instance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class EditorState:
    """One-stop shop for cross-panel editor state."""

    engine: Any
    selection: Any = None            # MultiSelectModel
    command_stack: Any = None        # CommandStack
    clipboard: Any = None            # Clipboard (class-level singleton anyway)
    active_theme: str = ""
    _theme_observers: list[Callable[[str], None]] = field(default_factory=list)
    _selection_observers: list[Callable[[Any], None]] = field(default_factory=list)

    @classmethod
    def build(cls, engine: Any, initial_theme: str | None = None) -> "EditorState":
        """Construct with the Sprint 9 primitives wired up."""
        try:
            from pharos_editor.multiselect import MultiSelectModel

            sel = MultiSelectModel()
        except Exception:
            sel = None
        try:
            from pharos_editor.command_stack import CommandStack

            cs = CommandStack()
        except Exception:
            cs = None
        try:
            from pharos_editor.clipboard import Clipboard

            cb = Clipboard  # class-level singleton
        except Exception:
            cb = None

        return cls(
            engine=engine,
            selection=sel,
            command_stack=cs,
            clipboard=cb,
            active_theme=initial_theme or "",
        )

    # ── selection ──────────────────────────────────────────────────────
    def selected_ids(self) -> list[str]:
        try:
            return list(self.selection.selection.order) if self.selection else []
        except Exception:
            return []

    def primary_selected_id(self) -> str | None:
        ids = self.selected_ids()
        return ids[-1] if ids else None

    def selected_entities(self) -> list[Any]:
        try:
            scene = getattr(self.engine, "scene", None)
            if scene is None:
                return []
            ids = set(self.selected_ids())
            return [e for e in scene.entities if getattr(e, "id", None) in ids]
        except Exception:
            return []

    def observe_selection(self, cb: Callable[[Any], None]) -> None:
        self._selection_observers.append(cb)

    def notify_selection_changed(self) -> None:
        for cb in list(self._selection_observers):
            try:
                cb(self.selection)
            except Exception:
                pass

    # ── theme ──────────────────────────────────────────────────────────
    def observe_theme(self, cb: Callable[[str], None]) -> None:
        self._theme_observers.append(cb)

    def set_theme(self, name: str) -> None:
        if name == self.active_theme:
            return
        self.active_theme = name
        for cb in list(self._theme_observers):
            try:
                cb(name)
            except Exception:
                pass
