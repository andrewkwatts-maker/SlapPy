"""``UndoStack`` — Python-fallback command history for the notebook editor.

The Rust ``slappyengine._core`` module doesn't publish a command buffer
yet (see the migration plan doc); until it does, the notebook editor
uses this Python implementation of the same shape:

* :meth:`push` records a completed action as a ``(action_id, forward,
  reverse)`` triple.
* :meth:`undo` pops the newest action, calls its reverse, and moves it
  to the redo stack.
* :meth:`redo` pops the newest redo entry, re-calls its forward, and
  pushes it back onto the main stack.

The class is intentionally protocol-compatible with the future Rust
buffer — when ``slappyengine._core.CommandBuffer`` lands we'll add a
thin adapter and delete the fallback body without touching call sites.

Design provenance: ``docs/sprint_plan_2026_06_03.md`` §6 (undo/redo).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from slappyengine._validation import (
    validate_callable,
    validate_int,
    validate_non_empty_str,
)


@dataclass
class UndoEntry:
    """One entry on the undo / redo stack.

    Both ``forward`` and ``reverse`` are zero-arg callables that mutate
    the world in opposite directions.
    """

    action_id: str
    forward: Callable[[], None]
    reverse: Callable[[], None]
    payload: Any = None
    label: str = ""


class UndoStack:
    """Bounded LIFO history of reversible editor commands.

    A ``push`` records a completed action; the caller has already applied
    the forward mutation, so ``push`` never re-runs it.

    ``undo`` calls the entry's ``reverse`` and moves the entry to the
    redo pile. A subsequent ``push`` clears the redo pile (standard
    Photoshop / VSCode behaviour).

    Parameters
    ----------
    capacity:
        Maximum number of entries kept in the undo pile. Older entries
        are silently dropped from the bottom (opposite end from
        ``pop``). Redo pile shares the same bound.
    """

    DEFAULT_CAPACITY: int = 256

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        validate_int("capacity", "UndoStack", capacity)
        if capacity < 1:
            raise ValueError(
                f"UndoStack: capacity must be >= 1; got {capacity}"
            )
        self._capacity: int = int(capacity)
        self._undo: list[UndoEntry] = []
        self._redo: list[UndoEntry] = []

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def undo_depth(self) -> int:
        return len(self._undo)

    @property
    def redo_depth(self) -> int:
        return len(self._redo)

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def peek_undo(self) -> UndoEntry | None:
        return self._undo[-1] if self._undo else None

    def peek_redo(self) -> UndoEntry | None:
        return self._redo[-1] if self._redo else None

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def push(
        self,
        action_id: str,
        forward: Callable[[], None],
        reverse: Callable[[], None],
        *,
        payload: Any = None,
        label: str = "",
    ) -> UndoEntry:
        """Record a completed action.

        The action's ``forward`` has already been applied by the caller;
        push does *not* re-run it. The entry lives at the top of the
        undo stack and clears the redo pile.
        """
        validate_non_empty_str("action_id", "UndoStack.push", action_id)
        validate_callable("forward", "UndoStack.push", forward)
        validate_callable("reverse", "UndoStack.push", reverse)

        entry = UndoEntry(
            action_id=action_id,
            forward=forward,
            reverse=reverse,
            payload=payload,
            label=label or action_id,
        )
        self._undo.append(entry)
        # Trim from the bottom when over capacity.
        while len(self._undo) > self._capacity:
            self._undo.pop(0)
        # A fresh action invalidates any pending redo.
        self._redo.clear()
        return entry

    def undo(self) -> UndoEntry | None:
        """Pop + reverse the newest entry — returns it, or ``None`` if empty."""
        if not self._undo:
            return None
        entry = self._undo.pop()
        try:
            entry.reverse()
        except Exception:
            # Reverse errors are swallowed so a bad callback can't lock
            # the editor into a broken state — the entry still moves to
            # redo so the user can try to reapply it.
            pass
        self._redo.append(entry)
        while len(self._redo) > self._capacity:
            self._redo.pop(0)
        return entry

    def redo(self) -> UndoEntry | None:
        """Pop + reapply the newest redo entry — returns it, or ``None``."""
        if not self._redo:
            return None
        entry = self._redo.pop()
        try:
            entry.forward()
        except Exception:
            pass
        self._undo.append(entry)
        while len(self._undo) > self._capacity:
            self._undo.pop(0)
        return entry


# ---------------------------------------------------------------------------
# Attempt to bind the Rust CommandBuffer if it exists — kept a soft import
# so the fallback path stays available in wheels built without it.
# ---------------------------------------------------------------------------


def resolve_undo_stack(capacity: int = UndoStack.DEFAULT_CAPACITY) -> Any:
    """Return the preferred undo-stack implementation.

    Prefers ``slappyengine._core.CommandBuffer`` when available; falls
    back to the pure-Python :class:`UndoStack` otherwise.
    """
    try:
        from slappyengine import _core  # type: ignore[import-not-found]
        cb_cls = getattr(_core, "CommandBuffer", None)
        if cb_cls is not None:
            try:
                return cb_cls(capacity)  # type: ignore[misc]
            except Exception:
                pass
    except Exception:
        pass
    return UndoStack(capacity=capacity)


__all__ = ["UndoEntry", "UndoStack", "resolve_undo_stack"]
