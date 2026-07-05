"""Hide / show entity actions — Blender ``H`` / ``Alt+H`` semantics.

Backs the ``edit.hide_selection`` and ``edit.show_all``
:class:`~slappyengine.tool_router.ToolAction` rows added by the JJ6
STUB-triage sprint tick (round 12 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1 / EE1 / FF1 / GG1 / II5).

Every DCC ships a "hide selected" / "show all" pair — Blender's ``H`` /
``Alt+H``, Maya's ``Ctrl+H`` / ``Ctrl+Shift+H``, Photoshop's
per-layer eye toggle. The ``hide_selection`` helper marks every
currently-selected entity as invisible; the ``show_all`` helper
un-hides every entity in the scene.

Two attribute conventions ship in the codebase:

* Nova3D-style entities carry ``entity.visible: bool``.
* Ochema Circuit legacy entities carry ``entity.hidden: bool``.

Both are updated when present. When neither exists we set
``entity.hidden`` so the flag round-trips (a subsequent ``show_all`` will
find and clear it).

Return contract
---------------

``hide_selection`` returns:

* ``{"status": "hidden", "entities": [...], "count": N}`` on success.
* ``{"status": "no_selection"}`` when nothing is selected.
* ``{"status": "already_hidden"}`` when every entry in the selection was
  already hidden (distinguished from ``no_selection`` so the caller can
  toast "already hidden" instead of "nothing selected").

``show_all`` returns:

* ``{"status": "shown", "entities": [...], "count": N,
   "previous_hidden_count": M}`` on success.
* ``{"status": "no_scene"}`` when no scene handle resolves.
* ``{"status": "empty_scene"}`` when the scene has zero entities.
* ``{"status": "all_visible"}`` when nothing was hidden to begin with.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx
from .edit_invert_selection_actions import (
    _get_scene,
    _get_shell,
    _is_hidden,
    _resolve_selection,
    _walk_scene_entities,
)


def _mark_hidden(entity: Any) -> bool:
    """Set the hidden flag on *entity*. Returns True on state change."""
    has_visible = hasattr(entity, "visible")
    has_hidden = hasattr(entity, "hidden")
    changed = False
    # Nova3D convention.
    if has_visible:
        try:
            if getattr(entity, "visible", True):
                setattr(entity, "visible", False)
                changed = True
        except Exception:  # noqa: BLE001
            pass
    # Ochema / legacy convention.
    if has_hidden:
        try:
            if not getattr(entity, "hidden", False):
                setattr(entity, "hidden", True)
                changed = True
        except Exception:  # noqa: BLE001
            pass
    elif not has_visible:
        # Neither convention present — install ``hidden`` so a later
        # show_all can find and clear it.
        try:
            setattr(entity, "hidden", True)
            changed = True
        except Exception:  # noqa: BLE001
            pass
    return changed


def _mark_visible(entity: Any) -> bool:
    """Clear the hidden flag on *entity*. Returns True on state change."""
    changed = False
    if hasattr(entity, "visible"):
        try:
            if not getattr(entity, "visible", True):
                setattr(entity, "visible", True)
                changed = True
        except Exception:  # noqa: BLE001
            pass
    if hasattr(entity, "hidden"):
        try:
            if getattr(entity, "hidden", False):
                setattr(entity, "hidden", False)
                changed = True
        except Exception:  # noqa: BLE001
            pass
    return changed


def hide_selection(ctx: dict[str, Any]) -> dict[str, Any]:
    """Hide every currently-selected entity.

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
    ensure_ctx("hide_selection", ctx)
    selection = _resolve_selection(ctx)
    if not selection:
        return {"status": "no_selection"}

    hidden: list[Any] = []
    for entity in selection:
        if _mark_hidden(entity):
            hidden.append(entity)

    if not hidden:
        return {"status": "already_hidden"}

    return {
        "status": "hidden",
        "entities": hidden,
        "count": len(hidden),
    }


def show_all(ctx: dict[str, Any]) -> dict[str, Any]:
    """Un-hide every entity in the current scene.

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
    ensure_ctx("show_all", ctx)
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}

    entities = _walk_scene_entities(scene)
    if not entities:
        return {"status": "empty_scene"}

    previously_hidden = [e for e in entities if _is_hidden(e)]
    if not previously_hidden:
        return {"status": "all_visible"}

    shown: list[Any] = []
    for entity in previously_hidden:
        if _mark_visible(entity):
            shown.append(entity)

    return {
        "status": "shown",
        "entities": shown,
        "count": len(shown),
        "previous_hidden_count": len(previously_hidden),
    }


__all__ = ["hide_selection", "show_all"]
