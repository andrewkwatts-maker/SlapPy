"""Lock / unlock entity actions — Blender / Maya lock-layer semantics.

Backs the ``edit.lock_selection`` and ``edit.unlock_all``
:class:`~pharos_editor.tool_router.ToolAction` rows added by the JJ6
STUB-triage sprint tick (round 12 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1 / EE1 / FF1 / GG1 / II5).

Sibling helpers to
:mod:`pharos_editor.actions.edit_hide_show_actions` — lock/unlock is the
"is this entity clickable / selectable" toggle, hide/show is the "is
this entity rendered" toggle. Every DCC ships both pairs; Blender uses
padlock icons in the outliner, Maya uses layer-editor "R" toggles,
Photoshop's ``Lock all`` per-layer button.

The ``locked`` flag is read by
:mod:`pharos_editor.actions.edit_invert_selection_actions._is_locked`
(shared helper) and by the II5 ``edit.select_next`` / ``select_previous``
Tab-through helpers, so locking an entity also removes it from Tab
navigation, matching Blender.

Return contract
---------------

``lock_selection`` returns:

* ``{"status": "locked", "entities": [...], "count": N}`` on success.
* ``{"status": "no_selection"}`` when nothing is selected.
* ``{"status": "already_locked"}`` when every entry in the selection was
  already locked (so the caller can toast "already locked" instead of
  "nothing selected").

``unlock_all`` returns:

* ``{"status": "unlocked", "entities": [...], "count": N,
   "previous_locked_count": M}`` on success.
* ``{"status": "no_scene"}`` when no scene handle resolves.
* ``{"status": "empty_scene"}`` when the scene has zero entities.
* ``{"status": "all_unlocked"}`` when nothing was locked to begin with.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx
from .edit_invert_selection_actions import (
    _get_scene,
    _is_locked,
    _resolve_selection,
    _walk_scene_entities,
)


def _mark_locked(entity: Any) -> bool:
    """Set the locked flag on *entity*. Returns True on state change."""
    was_locked = _is_locked(entity)
    if was_locked:
        return False
    # Prefer the public attribute over the underscore-prefixed legacy
    # form; write both when present so downstream readers agree.
    changed = False
    try:
        setattr(entity, "locked", True)
        changed = True
    except Exception:  # noqa: BLE001
        pass
    if hasattr(entity, "_locked"):
        try:
            setattr(entity, "_locked", True)
            changed = True
        except Exception:  # noqa: BLE001
            pass
    return changed


def _mark_unlocked(entity: Any) -> bool:
    """Clear the locked flag on *entity*. Returns True on state change."""
    if not _is_locked(entity):
        return False
    changed = False
    if hasattr(entity, "locked"):
        try:
            setattr(entity, "locked", False)
            changed = True
        except Exception:  # noqa: BLE001
            pass
    if hasattr(entity, "_locked"):
        try:
            setattr(entity, "_locked", False)
            changed = True
        except Exception:  # noqa: BLE001
            pass
    return changed


def lock_selection(ctx: dict[str, Any]) -> dict[str, Any]:
    """Lock every currently-selected entity.

    A locked entity is skipped by
    :func:`pharos_editor.actions.edit_invert_selection_actions.invert_selection`
    and by the II5 Tab-through helpers, so locking effectively
    marks-as-uneditable across the editor.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell exposing
          ``_selected_entity`` / ``_selected_entities``.
        * ``selection`` (optional): explicit selection override
          (list / tuple / set / single entity).

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("lock_selection", ctx)
    selection = _resolve_selection(ctx)
    if not selection:
        return {"status": "no_selection"}

    locked: list[Any] = []
    for entity in selection:
        if _mark_locked(entity):
            locked.append(entity)

    if not locked:
        return {"status": "already_locked"}

    return {
        "status": "locked",
        "entities": locked,
        "count": len(locked),
    }


def unlock_all(ctx: dict[str, Any]) -> dict[str, Any]:
    """Unlock every entity in the current scene.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell used to resolve the scene.
        * ``scene`` (optional): scene override — bypasses shell
          resolution.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("unlock_all", ctx)
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}

    entities = _walk_scene_entities(scene)
    if not entities:
        return {"status": "empty_scene"}

    previously_locked = [e for e in entities if _is_locked(e)]
    if not previously_locked:
        return {"status": "all_unlocked"}

    unlocked: list[Any] = []
    for entity in previously_locked:
        if _mark_unlocked(entity):
            unlocked.append(entity)

    return {
        "status": "unlocked",
        "entities": unlocked,
        "count": len(unlocked),
        "previous_locked_count": len(previously_locked),
    }


__all__ = ["lock_selection", "unlock_all"]
