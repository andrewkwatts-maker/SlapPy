"""Undo/redo command stack (Sprint 9 UI polish #7).

Nova3D shipped only a stub undo; every panel had its own ad-hoc
history that couldn't cross-reference. Pharos ships one process-wide
stack that panels push through — cross-panel undo works out of the
box, matching Blender/Godot expectations.

Design
------
- Commands are simple dataclass objects implementing ``do()`` and
  ``undo()``. They must be self-contained (own their diff snapshot).
- Bounded depth (default 128) so the stack can't leak arbitrary memory
  on a long editing session.
- Emits telemetry on push / undo / redo for editor telemetry pane.
- ``push_and_do(cmd)`` runs the command; do not call ``cmd.do()``
  yourself before pushing — the stack coordinates redo state.
"""
from __future__ import annotations

from collections import deque
from typing import Callable, Protocol, runtime_checkable


DEFAULT_MAX_DEPTH: int = 128


@runtime_checkable
class Command(Protocol):
    """Every push-able command implements this shape."""

    #: Short human-readable summary for the status bar / undo menu.
    label: str

    def do(self) -> None: ...
    def undo(self) -> None: ...


class CommandStack:
    """Process-wide undo/redo stack."""

    def __init__(self, max_depth: int = DEFAULT_MAX_DEPTH) -> None:
        self._undo: deque[Command] = deque(maxlen=max_depth)
        self._redo: list[Command] = []
        self._on_change: list[Callable[[], None]] = []

    # -- push + do --

    def push_and_do(self, cmd: Command) -> None:
        """Execute a command and push it onto the undo stack."""
        if not isinstance(cmd, Command):
            raise TypeError(f"{type(cmd).__name__} does not implement Command")
        cmd.do()
        self._undo.append(cmd)
        # Doing a new command invalidates the redo history.
        self._redo.clear()
        self._notify()
        self._emit("push", cmd.label)

    # -- undo / redo --

    def undo(self) -> str | None:
        if not self._undo:
            return None
        cmd = self._undo.pop()
        cmd.undo()
        self._redo.append(cmd)
        self._notify()
        self._emit("undo", cmd.label)
        return cmd.label

    def redo(self) -> str | None:
        if not self._redo:
            return None
        cmd = self._redo.pop()
        cmd.do()
        self._undo.append(cmd)
        self._notify()
        self._emit("redo", cmd.label)
        return cmd.label

    # -- query --

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def peek_undo(self) -> str | None:
        return self._undo[-1].label if self._undo else None

    def peek_redo(self) -> str | None:
        return self._redo[-1].label if self._redo else None

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
        self._notify()

    # -- observers --

    def on_change(self, cb: Callable[[], None]) -> None:
        """Register a callback fired after any state-change (push/undo/redo)."""
        self._on_change.append(cb)

    def _notify(self) -> None:
        for cb in list(self._on_change):
            try:
                cb()
            except Exception as exc:
                from pharos_editor.errors import route
                route(exc, "command_stack.on_change")

    def _emit(self, verb: str, label: str) -> None:
        try:
            from pharos_engine.telemetry import emit as _emit_t
            _emit_t(
                "pharos.editor.command",
                verb=verb, label=label, undo_depth=len(self._undo),
            )
        except Exception:
            pass  # noqa: pharos-errors-lint (telemetry best-effort)


__all__ = ["Command", "CommandStack", "DEFAULT_MAX_DEPTH"]
