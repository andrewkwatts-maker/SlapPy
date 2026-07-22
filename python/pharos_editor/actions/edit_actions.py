"""Edit-lifecycle actions — duplicate selection.

Backs the ``edit.duplicate_selection`` :class:`ToolAction` row. Uses
:class:`~pharos_editor.ui.editor.entity_clipboard.EntityClipboard` to
snapshot the current selection and immediately produce a paste-side
clone, so the user gets a "duplicate this thing" one-click UX without
having to walk through the copy → paste dance.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _resolve_selection(ctx: dict[str, Any]) -> list[Any]:
    """Return the entities to duplicate as a list.

    Search order:

    1. ``ctx["selection"]`` — explicit override (tests pass this).
    2. ``ctx["shell"]._selected_entity`` — single-select case.
    3. ``ctx["shell"]._selected_entities`` — multi-select case
       (some panels track this separately).
    """
    override = ctx.get("selection")
    if override is not None:
        if isinstance(override, (list, tuple)):
            return [x for x in override if x is not None]
        return [override]
    shell = _get_shell(ctx)
    if shell is None:
        return []
    multi = getattr(shell, "_selected_entities", None)
    if isinstance(multi, (list, tuple)) and multi:
        return [x for x in multi if x is not None]
    single = getattr(shell, "_selected_entity", None)
    if single is not None:
        return [single]
    return []


def duplicate_selection(ctx: dict[str, Any]) -> dict[str, Any]:
    """Clone the current selection via :class:`EntityClipboard`.

    Resolves the active selection (see :func:`_resolve_selection`),
    snapshots it into the process-wide clipboard, and immediately calls
    :meth:`EntityClipboard.paste` to produce a fresh copy suffixed with
    ``" (copy)"``. The paste result is returned so the caller can add
    the clones to the world.

    When ``ctx["shell"]`` exposes ``_duplicate_selected()`` (matches the
    legacy shell hook), that method is preferred so the shell can route
    into whichever scene-add path it owns.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("duplicate_selection", ctx)
    shell = _get_shell(ctx)

    # Legacy shell hook takes precedence — matches the existing
    # ``editor.duplicate`` router action so the two ids stay in sync.
    if shell is not None:
        dup = getattr(shell, "_duplicate_selected", None)
        if callable(dup):
            try:
                result = dup()
            except Exception as exc:  # noqa: BLE001
                return {"status": "error", "message": str(exc)}
            return {"status": "duplicated", "path": "shell", "result": result}

    entities = _resolve_selection(ctx)
    if not entities:
        return {"status": "no_selection"}

    try:
        from pharos_editor.ui.editor.entity_clipboard import (
            get_active_clipboard,
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}
    clipboard = ctx.get("clipboard") or get_active_clipboard()

    # Snapshot into the clipboard so ``Ctrl+V`` still works after the
    # duplicate lands (and so tests can assert on the buffer state).
    try:
        n = clipboard.copy(entities)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}
    suffix = ctx.get("name_suffix", " (copy)")
    try:
        clones = clipboard.paste(name_suffix=suffix)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}

    # Best-effort: if the shell exposes a scene, add the clones so the
    # outliner reflects the duplication immediately. Silently no-ops when
    # any hook is missing so headless callers stay lightweight.
    added = 0
    if shell is not None:
        scene = getattr(getattr(shell, "_engine", None), "scene", None)
        if scene is not None:
            add = getattr(scene, "add_entity", None)
            if callable(add):
                for clone in clones:
                    try:
                        add(clone)
                        added += 1
                    except Exception:  # noqa: BLE001
                        pass

    return {
        "status": "duplicated",
        "count": n,
        "clones": clones,
        "added": added,
    }


__all__ = ["duplicate_selection"]
