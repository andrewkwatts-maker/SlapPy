"""History actions — undo / redo via the active :class:`UndoStack`.

Backs two :class:`~slappyengine.tool_router.ToolAction` rows added by
the BB1 STUB-triage sprint tick:

* ``edit.undo`` — call the newest :class:`UndoStack` entry's ``reverse``.
* ``edit.redo`` — reapply the newest redo entry's ``forward``.

These are distinct from the legacy ``editor.undo`` / ``editor.redo``
router entries. The legacy pair routes through
``shell._undo`` / ``shell._engine._undo_manager.redo`` — a fragile
double-hop that silently no-ops when the shell doesn't expose an
undo-manager. This new pair resolves the process-wide undo stack via
:func:`slappyengine.ui.editor.editor_undo.resolve_undo_stack` (which
prefers the Rust ``CommandBuffer`` when the wheel exposes it) so
headless callers, tests, and diary-mode invocations all reach the same
history object as the interactive editor.

Return contract
---------------

* ``{"status": "undone", "action_id": str, "label": str,
  "undo_depth": int, "redo_depth": int}`` on success.
* ``{"status": "redone", "action_id": str, "label": str,
  "undo_depth": int, "redo_depth": int}`` on success.
* ``{"status": "empty"}`` when the stack has nothing to (un)do — this
  is a normal state, not an error, so callers can treat it as a soft
  no-op / disabled-button hint.
* ``{"status": "no_stack"}`` when no UndoStack could be resolved. Rare —
  only fires when the shell hides its stack under an unusual attribute
  and no ``ctx["stack"]`` override was supplied.
* ``{"status": "error", "message": str}`` when the reverse / forward
  callback raised outside the entry's own swallow guard.
"""
from __future__ import annotations

from typing import Any


def _resolve_stack(ctx: dict[str, Any]) -> Any:
    """Return the :class:`UndoStack`-ish object to operate on.

    Search order:

    1. ``ctx["stack"]`` — direct override (tests pass this).
    2. ``ctx["shell"]._undo_stack`` — the notebook shell's field.
    3. ``ctx["shell"]._engine._undo_manager`` — the legacy engine slot
       used by the ``editor.undo`` / ``editor.redo`` fallbacks. Kept so
       this action is a strict superset of the legacy behaviour.
    """
    override = ctx.get("stack")
    if override is not None:
        return override
    shell = ctx.get("shell")
    if shell is None:
        return None
    # Preferred: shell owns the stack directly.
    direct = getattr(shell, "_undo_stack", None)
    if direct is not None:
        return direct
    # Legacy: engine holds it.
    engine = getattr(shell, "_engine", None)
    if engine is None:
        return None
    return getattr(engine, "_undo_manager", None)


def _depths(stack: Any) -> tuple[int, int]:
    """Return ``(undo_depth, redo_depth)`` — 0/0 when the getters miss.

    ``UndoStack`` exposes these as properties; the Rust ``CommandBuffer``
    exposes them as methods. Probe both patterns so this action works
    against either implementation.
    """
    def _read(attr: str) -> int:
        val = getattr(stack, attr, None)
        if callable(val):
            try:
                val = val()
            except Exception:  # noqa: BLE001
                return 0
        try:
            return int(val or 0)
        except (TypeError, ValueError):
            return 0

    return _read("undo_depth"), _read("redo_depth")


def _entry_label(entry: Any) -> tuple[str, str]:
    """Return ``(action_id, label)`` for the popped entry.

    Falls back to empty strings when the entry doesn't expose the
    matching attributes (e.g. Rust returns a bare tuple or an opaque
    handle).
    """
    if entry is None:
        return "", ""
    action_id = getattr(entry, "action_id", "") or ""
    label = getattr(entry, "label", "") or action_id
    return str(action_id), str(label)


def undo(ctx: dict[str, Any]) -> dict[str, Any]:
    """Pop + reverse the newest :class:`UndoStack` entry.

    See the module docstring for the return contract.
    """
    stack = _resolve_stack(ctx)
    if stack is None:
        return {"status": "no_stack"}
    do_undo = getattr(stack, "undo", None)
    if not callable(do_undo):
        return {"status": "no_stack"}
    # Check "can_undo" if the stack exposes it — lets us return "empty"
    # without triggering a callback that might raise.
    can = getattr(stack, "can_undo", None)
    if callable(can):
        try:
            if not can():
                return {"status": "empty"}
        except Exception:  # noqa: BLE001
            # Fall through — the do_undo call will surface a saner error.
            pass
    try:
        entry = do_undo()
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}
    if entry is None:
        return {"status": "empty"}
    action_id, label = _entry_label(entry)
    undo_depth, redo_depth = _depths(stack)
    return {
        "status": "undone",
        "action_id": action_id,
        "label": label,
        "undo_depth": undo_depth,
        "redo_depth": redo_depth,
    }


def redo(ctx: dict[str, Any]) -> dict[str, Any]:
    """Pop + reapply the newest redo entry.

    See the module docstring for the return contract.
    """
    stack = _resolve_stack(ctx)
    if stack is None:
        return {"status": "no_stack"}
    do_redo = getattr(stack, "redo", None)
    if not callable(do_redo):
        return {"status": "no_stack"}
    can = getattr(stack, "can_redo", None)
    if callable(can):
        try:
            if not can():
                return {"status": "empty"}
        except Exception:  # noqa: BLE001
            pass
    try:
        entry = do_redo()
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}
    if entry is None:
        return {"status": "empty"}
    action_id, label = _entry_label(entry)
    undo_depth, redo_depth = _depths(stack)
    return {
        "status": "redone",
        "action_id": action_id,
        "label": label,
        "undo_depth": undo_depth,
        "redo_depth": redo_depth,
    }


__all__ = [
    "undo",
    "redo",
]
