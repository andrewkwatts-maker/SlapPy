"""Edit duplicate-at-cursor action.

Backs the ``edit.duplicate_at_cursor``
:class:`~pharos_editor.tool_router.ToolAction` row added by the PP1
STUB-triage sprint tick (round 17).

Blender's ``Shift+D`` (duplicate to cursor), Illustrator's
``Alt+drag`` — every 2D/3D DCC ships a "clone this and drop it under
the cursor" gesture. Distinct from JJ6's ``edit.duplicate_selection``
(which clones in-place with a ``" (copy)"`` name suffix) — this helper
adds a ``translate`` step that moves every clone so its origin lines up
with the resolved cursor world-position.

Cursor resolution
-----------------

Delegates to the same three-slot chain the r8
:mod:`spawn_cursor_actions` uses:

1. ``ctx["cursor"]`` — explicit override (tests use this).
2. ``shell.get_cursor_world_position()`` — canonical shell hook.
3. ``shell._cursor_world_position`` — pre-computed slot.
4. ``shell._last_cursor`` — legacy Nova3D slot.

Selection resolution
--------------------

Same as :mod:`edit_actions` (``edit.duplicate_selection``):
``ctx["selection"]`` → ``shell._selected_entities`` →
``shell._selected_entity``.

Position translation
--------------------

Each clone's position is set to ``cursor + (clone.pos - anchor)`` where
``anchor`` is the *first* clone's original position. This preserves the
relative offset between multi-select clones so a rectangle of 4 entities
stays rectangular after the duplicate-and-move.

Return contract
---------------

* ``{"status": "duplicated_at_cursor", "count": N, "clones": [...],
   "cursor": (x, y, z), "translated": N}`` on success.
* ``{"status": "no_selection"}`` — nothing to duplicate.
* ``{"status": "no_cursor"}`` — cursor coordinate not resolvable.
* ``{"status": "error", "message": str}`` — clipboard / paste failure.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx
from .spawn_cursor_actions import _resolve_cursor


_POS_KEYS = ("position", "origin", "pos")


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _resolve_selection(ctx: dict[str, Any]) -> list[Any]:
    override = ctx.get("selection")
    if override is not None:
        if isinstance(override, (list, tuple, set)):
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


def _entity_position(entity: Any) -> tuple[float, ...] | None:
    if isinstance(entity, dict):
        for key in _POS_KEYS:
            val = entity.get(key)
            if val is None:
                continue
            try:
                return tuple(float(x) for x in val)
            except (TypeError, ValueError):
                continue
        return None
    for key in _POS_KEYS:
        val = getattr(entity, key, None)
        if val is None:
            continue
        try:
            return tuple(float(x) for x in val)
        except (TypeError, ValueError):
            continue
    return None


def _apply_position(entity: Any, pos: tuple[float, float, float]) -> bool:
    """Set the entity's position, using whichever attr it already tracks."""
    if isinstance(entity, dict):
        for key in _POS_KEYS:
            if key in entity:
                try:
                    entity[key] = [pos[0], pos[1], pos[2]]
                    return True
                except Exception:  # noqa: BLE001
                    continue
        try:
            entity["position"] = [pos[0], pos[1], pos[2]]
            return True
        except Exception:  # noqa: BLE001
            return False
    for key in _POS_KEYS:
        if hasattr(entity, key):
            try:
                setattr(entity, key, [pos[0], pos[1], pos[2]])
                return True
            except Exception:  # noqa: BLE001
                continue
    try:
        setattr(entity, "position", [pos[0], pos[1], pos[2]])
        return True
    except Exception:  # noqa: BLE001
        return False


def duplicate_at_cursor(ctx: dict[str, Any]) -> dict[str, Any]:
    """Clone the current selection and place the clones at the cursor.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``selection`` (optional): explicit selection override.
        * ``shell`` (optional): editor shell — provides selection +
          cursor fallback + best-effort scene-add integration.
        * ``cursor`` (optional 2/3-tuple): explicit cursor world
          position (tests use this).

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("duplicate_at_cursor", ctx)
    entities = _resolve_selection(ctx)
    if not entities:
        return {"status": "no_selection"}
    cursor = _resolve_cursor(ctx)
    if cursor is None:
        return {"status": "no_cursor"}

    # Snapshot into the clipboard (same path edit.duplicate_selection
    # uses) so a subsequent Ctrl+V still works.
    try:
        from pharos_editor.ui.editor.entity_clipboard import (
            get_active_clipboard,
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}
    clipboard = ctx.get("clipboard") or get_active_clipboard()
    try:
        n = clipboard.copy(entities)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}
    suffix = ctx.get("name_suffix", " (copy)")
    try:
        clones = clipboard.paste(name_suffix=suffix)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}

    # Compute the anchor — first entity's original position — so the
    # multi-select case preserves relative offsets.
    anchor: tuple[float, ...] | None = None
    for e in entities:
        anchor = _entity_position(e)
        if anchor is not None:
            break
    if anchor is None:
        anchor = (0.0, 0.0, 0.0)

    # Pad anchor + cursor to length 3 so mismatched 2D/3D positions
    # don't crash the offset math.
    def _pad3(p: tuple[float, ...]) -> tuple[float, float, float]:
        vals = list(p) + [0.0, 0.0, 0.0]
        return (vals[0], vals[1], vals[2])

    anchor3 = _pad3(anchor)
    cursor3 = _pad3(cursor)

    translated = 0
    for clone in clones:
        cpos = _entity_position(clone)
        if cpos is None:
            new_pos = cursor3
        else:
            cpos3 = _pad3(cpos)
            new_pos = (
                cursor3[0] + (cpos3[0] - anchor3[0]),
                cursor3[1] + (cpos3[1] - anchor3[1]),
                cursor3[2] + (cpos3[2] - anchor3[2]),
            )
        if _apply_position(clone, new_pos):
            translated += 1

    # Best-effort: register clones with the scene.
    shell = _get_shell(ctx)
    added = 0
    if shell is not None:
        scene = getattr(getattr(shell, "_engine", None), "scene", None)
        if scene is None:
            scene = getattr(shell, "_scene", None)
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
        "status": "duplicated_at_cursor",
        "count": n,
        "clones": clones,
        "cursor": cursor3,
        "translated": translated,
        "added": added,
    }


__all__ = ["duplicate_at_cursor"]
