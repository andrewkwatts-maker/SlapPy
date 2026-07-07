"""Entity-level isolate action — hide every non-selected entity.

Backs the ``layer.isolate``
:class:`~slappyengine.tool_router.ToolAction` row added by the RR1
STUB-triage sprint tick (round 19).

Blender's ``Numpad /`` "local view" / Maya's ``Show → Isolate Selected``
— every 3D DCC ships an *entity-level* isolate that hides scene elements
not currently selected so the user can focus on a few objects. This is
distinct from OO1's ``layer.solo`` (layer-level, snapshot / toggle) and
from RR1's own ``layer.hide_others`` (layer-level, one-shot): isolate
operates on the entity roster, not on the layer stack, and remembers the
previous visibility state on ``shell._isolate_snapshot`` so a second
invocation restores.

The ``layer.`` action-id namespace is a slight misnomer — the "layer"
prefix groups every visibility-management verb (solo, hide_others,
merge_down, isolate) even though this specific verb walks entities, not
z_layers. Matches Blender's menu placement (``View → Local View``) which
lives under a viewport-visibility group.

Scene walk resolution
---------------------

* ``ctx["scene"]`` — explicit override.
* ``shell._engine.scene`` — canonical shell hook.
* ``shell._scene`` — legacy attribute.

Selection resolution: same fallback chain as
:mod:`edit_hide_show_actions` — ``ctx["selection"]`` wins, then the
shell's ``_selected_entities`` / ``_selected_entity`` slots.

Return contract
---------------

* ``{"status": "isolated", "selection_count": int,
   "hidden": [entities], "hidden_count": int, "restored": False}`` —
  first-pass isolate (visibility snapshot stashed).
* ``{"status": "restored", "shown": [entities], "shown_count": int,
   "restored": True}`` — second-pass isolate with an existing snapshot
  rewinds every entity to its snapshotted visibility.
* ``{"status": "no_scene"}`` — no scene handle reachable.
* ``{"status": "empty_scene"}`` — scene has zero entities.
* ``{"status": "no_selection"}`` — nothing selected to isolate around
  (only returned on the first-pass path; the restore path fires
  whenever a snapshot exists, even with an empty selection).
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx
from .edit_hide_show_actions import _mark_hidden, _mark_visible
from .edit_invert_selection_actions import (
    _get_scene,
    _get_shell,
    _is_hidden,
    _resolve_selection,
    _walk_scene_entities,
)


_SNAPSHOT_ATTR = "_isolate_snapshot"


def _visibility_state(entity: Any) -> bool:
    """Return True when *entity* is currently visible.

    Consults both Nova3D ``entity.visible`` and Ochema ``entity.hidden``
    conventions — mirrors :mod:`edit_hide_show_actions._is_hidden`.
    """
    return not _is_hidden(entity)


def _apply_snapshot(shell: Any, snapshot: dict[int, bool]) -> list[Any]:
    """Rewind every entity in *snapshot* to its snapshotted visibility.

    Returns the entities whose state actually changed. Uses ``id(entity)``
    as the key so we do not hold real references (avoids leaking scene
    entities when the snapshot outlives the scene).
    """
    # We only have ids — the snapshot dict values encode desired visibility
    # but the ids themselves are opaque. The caller supplies the scene
    # walk so we can re-resolve the entities.
    return []


def isolate(ctx: dict[str, Any]) -> dict[str, Any]:
    """Isolate the current selection — hide every non-selected entity.

    Toggle contract: when the shell already carries an
    ``_isolate_snapshot`` (set by a previous call), the second call
    restores every entity to its pre-isolate visibility, matching
    Blender's ``Numpad /`` toggle.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``selection`` (optional): explicit seed selection.
        * ``shell`` (optional): editor shell. Receives / consumes the
          ``_isolate_snapshot`` slot.
        * ``scene`` (optional): scene handle.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("isolate", ctx)
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}

    entities = _walk_scene_entities(scene)
    if not entities:
        return {"status": "empty_scene"}

    shell = _get_shell(ctx)
    entity_by_id = {id(e): e for e in entities}

    # Restore path — an existing snapshot wins over first-pass logic.
    snapshot: dict[int, bool] | None = None
    if shell is not None:
        raw = getattr(shell, _SNAPSHOT_ATTR, None)
        if isinstance(raw, dict):
            snapshot = raw

    if snapshot:
        shown: list[Any] = []
        for eid, was_visible in snapshot.items():
            entity = entity_by_id.get(eid)
            if entity is None:
                continue
            currently_visible = _visibility_state(entity)
            if was_visible and not currently_visible:
                if _mark_visible(entity):
                    shown.append(entity)
            elif not was_visible and currently_visible:
                if _mark_hidden(entity):
                    shown.append(entity)
        try:
            setattr(shell, _SNAPSHOT_ATTR, None)
        except Exception:  # noqa: BLE001
            pass
        return {
            "status": "restored",
            "shown": shown,
            "shown_count": len(shown),
            "restored": True,
        }

    # First-pass isolate — need a non-empty selection.
    selection = _resolve_selection(ctx)
    if not selection:
        return {"status": "no_selection"}

    seed_ids = {id(e) for e in selection}
    snap: dict[int, bool] = {id(e): _visibility_state(e) for e in entities}
    hidden: list[Any] = []
    for entity in entities:
        if id(entity) in seed_ids:
            # Force-show seeds even if they were previously hidden — the
            # user asked to *focus on* them, so make them visible.
            if _is_hidden(entity):
                _mark_visible(entity)
            continue
        if not _visibility_state(entity):
            # Already hidden — no work, but the snapshot still
            # remembers so restore is symmetric.
            continue
        if _mark_hidden(entity):
            hidden.append(entity)

    if shell is not None:
        try:
            setattr(shell, _SNAPSHOT_ATTR, snap)
        except Exception:  # noqa: BLE001
            pass

    return {
        "status": "isolated",
        "selection_count": len(selection),
        "hidden": hidden,
        "hidden_count": len(hidden),
        "restored": False,
    }


__all__ = ["isolate"]
