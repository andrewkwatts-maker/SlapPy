"""Destructive edit actions — cut / delete selection.

Backs two action ids added by the AA1 STUB-triage sprint tick
(round 4 after X3/Y1/Z7):

* ``edit.cut_selection`` — snapshot the current selection into the
  process-wide :class:`~pharos_engine.ui.editor.entity_clipboard.EntityClipboard`
  via :meth:`EntityClipboard.cut` **and** remove each original from the
  active scene. Matches the standard Ctrl+X UX.
* ``edit.delete_selection`` — remove each selected entity from the scene
  without touching the clipboard. Matches the ``Del`` hotkey behaviour.

Both helpers return a small result dict so tests and the status-bar
readout can assert on what happened. When the scene has no reachable
``remove_entity`` hook the "deletion" degrades to a no-op count so the
clipboard state is still recorded (cut) — the caller may then flash
"nothing to delete" toasts.

Design provenance
-----------------

* ``docs/engine_feature_map_2026_07_04.md`` §"Top 10 Broken/Stub Fixes"
  called out ``edit.cut_selection`` / ``edit.delete_selection`` as
  missing router action ids — the two most natural companions to
  ``editor.copy_selection`` / ``editor.paste_selection`` from Y1.
* ``python/pharos_engine/ui/editor/shell.py::_delete_selected`` — the
  existing single-select shell path this action generalises.
* ``python/pharos_engine/actions/edit_actions.py`` — sibling module
  hosting :func:`duplicate_selection`; the two share the
  ``_resolve_selection`` shape used across the actions subpackage.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _get_scene(ctx: dict[str, Any]) -> Any:
    """Resolve a Scene handle from *ctx* (mirrors selection_actions)."""
    scene = ctx.get("scene")
    if scene is not None:
        return scene
    shell = _get_shell(ctx)
    if shell is None:
        return None
    engine = getattr(shell, "_engine", None)
    if engine is not None:
        scene = getattr(engine, "scene", None) or getattr(engine, "_scene", None)
        if scene is not None:
            return scene
    return getattr(shell, "_scene", None)


def _resolve_selection(ctx: dict[str, Any]) -> list[Any]:
    """Return the entities to act on as a list.

    Search order:

    1. ``ctx["selection"]`` — explicit override (tests pass this).
    2. ``ctx["shell"]._selected_entities`` — multi-select case.
    3. ``ctx["shell"]._selected_entity`` — single-select case.
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


def _get_clipboard(ctx: dict[str, Any]) -> Any:
    """Resolve an :class:`EntityClipboard` from *ctx* (lazy import)."""
    clipboard = ctx.get("clipboard")
    if clipboard is not None:
        return clipboard
    try:
        from pharos_engine.ui.editor.entity_clipboard import (
            get_active_clipboard,
        )
    except Exception:  # noqa: BLE001
        return None
    return get_active_clipboard()


def _remove_from_scene(scene: Any, entities: list[Any]) -> int:
    """Best-effort delete each entity from *scene*. Return removed count."""
    if scene is None:
        return 0
    remover = (
        getattr(scene, "remove_entity", None)
        or getattr(scene, "remove", None)
    )
    if not callable(remover):
        return 0
    removed = 0
    for ent in entities:
        try:
            remover(ent)
            removed += 1
        except Exception:  # noqa: BLE001
            # Silently swallow — a stale selection entry that no longer
            # exists in the scene is not a fatal error for cut/delete.
            pass
    return removed


def _clear_selection(shell: Any) -> None:
    """Reset the shell's selection slots after a destructive edit."""
    if shell is None:
        return
    try:
        setattr(shell, "_selected_entity", None)
    except Exception:  # noqa: BLE001
        pass
    try:
        setattr(shell, "_selected_entities", [])
    except Exception:  # noqa: BLE001
        pass


def cut_selection(ctx: dict[str, Any]) -> dict[str, Any]:
    """Cut — copy the current selection to the clipboard + delete originals.

    * Snapshots into :class:`EntityClipboard` via :meth:`cut` so the
      clipboard's ``last_action`` reads ``"cut"`` (paste still works).
    * Removes each snapshotted entity from the active scene via
      ``scene.remove_entity(entity)`` (best-effort — missing hook is
      allowed for headless tests).
    * Clears the shell's selection slots so the outliner refreshes empty.

    Returns
    -------
    dict
        ``{"status": "cut", "count": copied, "removed": removed}`` on
        success. ``{"status": "no_selection"}`` when nothing was selected.
        ``{"status": "error", "message": str}`` when the clipboard raised.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("cut_selection", ctx)
    entities = _resolve_selection(ctx)
    if not entities:
        return {"status": "no_selection"}

    clipboard = _get_clipboard(ctx)
    if clipboard is None:
        return {"status": "error", "message": "clipboard unavailable"}

    try:
        copied = clipboard.cut(entities)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}

    scene = _get_scene(ctx)
    removed = _remove_from_scene(scene, entities)
    _clear_selection(_get_shell(ctx))

    return {
        "status": "cut",
        "count": copied,
        "removed": removed,
    }


def delete_selection(ctx: dict[str, Any]) -> dict[str, Any]:
    """Delete — remove each selected entity from the scene.

    Differs from ``editor.delete`` (which routes through the legacy
    single-select ``shell._delete_selected`` hook) in three ways:

    * Handles multi-select — walks ``_selected_entities`` when present.
    * Fully headless — accepts ``ctx["selection"]`` / ``ctx["scene"]``.
    * Does **not** touch the clipboard. Callers that want a copy-and-
      delete flow should use :func:`cut_selection` instead.

    Returns
    -------
    dict
        ``{"status": "deleted", "count": N}`` on success (N = number of
        entities actually removed). ``{"status": "no_selection"}`` when
        nothing was selected. ``{"status": "no_scene"}`` when the shell
        has no reachable scene.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("delete_selection", ctx)
    entities = _resolve_selection(ctx)
    if not entities:
        return {"status": "no_selection"}

    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene", "requested": len(entities)}

    removed = _remove_from_scene(scene, entities)
    _clear_selection(_get_shell(ctx))
    return {
        "status": "deleted",
        "count": removed,
        "requested": len(entities),
    }


__all__ = [
    "cut_selection",
    "delete_selection",
]
