"""Spawn-at-selection-center action — arm next spawn at the selection centroid.

Backs the ``spawn.at_selection_center``
:class:`~slappyengine.tool_router.ToolAction` row added by the YY4
STUB-triage sprint tick (round 25 after WW4).

Distinct from the sibling spawn-position verbs:

* QQ1's ``spawn.at_origin`` arms at world zero.
* TT2's ``spawn.at_view_center`` arms at the camera focal point.
* UU4's ``spawn.at_origin_offset`` arms at ``(0, 0, 0) + offset``.
* VV4's ``spawn.at_last_position`` arms at the previous drop.
* WW4's ``spawn.at_grid`` snaps a target onto the grid before arming.
* CC1's ``spawn.spawn_at_cursor`` fires immediately at the cursor.
* CC1's ``spawn.repeat_last`` re-fires the last spawn.

This verb aggregates the *positions* of the currently selected
entities and arms the next spawn at their arithmetic centroid.
Matches Blender's ``Shift+S → Cursor to Selected`` and Nova3D's
Outliner right-click "Focus on Selection Center".

Position resolution
-------------------

Every selected entity is probed for a 3-vec position in priority
order:

1. ``entity.position`` — canonical scene-graph attribute.
2. ``entity._position`` — private/legacy alias.
3. ``entity.transform.position`` — one-level indirection through a
   transform component.
4. ``entity["position"]`` — dict-shaped entities.

Entities with no reachable position contribute nothing to the
centroid. When *every* selected entity is position-less, the return
status is ``no_position``.

Selection resolution
--------------------

Same as the other selection-driven verbs — ``ctx["selection"]``
override or ``shell._selected_entities`` / ``_selected_entity``.

Return contract
---------------

* ``{"status": "armed", "position": (x, y, z), "count": N,
   "samples": N}`` — success. ``count`` = selection size (input),
   ``samples`` = number of entities that contributed a position
   (may be fewer than ``count`` when some had no position).
* ``{"status": "no_selection"}`` — nothing selected.
* ``{"status": "no_position"}`` — selection has entities but none
  carry a resolvable position.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _resolve_selection(ctx: dict[str, Any]) -> list[Any]:
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


def _to_xyz(raw: Any) -> tuple[float, float, float] | None:
    if not isinstance(raw, (list, tuple)):
        return None
    if not raw:
        return None
    try:
        vals = [float(v) for v in raw]
    except (TypeError, ValueError):
        return None
    if len(vals) == 2:
        return (vals[0], vals[1], 0.0)
    if len(vals) >= 3:
        return (vals[0], vals[1], vals[2])
    return None


def _entity_position(entity: Any) -> tuple[float, float, float] | None:
    if isinstance(entity, dict):
        got = _to_xyz(entity.get("position"))
        if got is not None:
            return got
        return _to_xyz(entity.get("_position"))
    raw = getattr(entity, "position", None)
    got = _to_xyz(raw)
    if got is not None:
        return got
    raw = getattr(entity, "_position", None)
    got = _to_xyz(raw)
    if got is not None:
        return got
    transform = getattr(entity, "transform", None)
    if transform is not None:
        return _to_xyz(getattr(transform, "position", None))
    return None


def _arm(shell: Any, xyz: tuple[float, float, float]) -> None:
    if shell is None:
        return
    try:
        setattr(shell, "_pending_spawn_position", list(xyz))
    except Exception:  # noqa: BLE001
        pass


def spawn_at_selection_center(ctx: dict[str, Any]) -> dict[str, Any]:
    """Arm the next spawn at the centroid of the current selection.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell exposing selection slots
          + receives ``_pending_spawn_position``.
        * ``selection`` (optional): explicit selection override.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("spawn_at_selection_center", ctx)
    selection = _resolve_selection(ctx)
    if not selection:
        return {"status": "no_selection"}

    positions: list[tuple[float, float, float]] = []
    for entity in selection:
        pos = _entity_position(entity)
        if pos is not None:
            positions.append(pos)

    if not positions:
        return {"status": "no_position"}

    n = len(positions)
    centroid = (
        sum(p[0] for p in positions) / n,
        sum(p[1] for p in positions) / n,
        sum(p[2] for p in positions) / n,
    )
    shell = _get_shell(ctx)
    _arm(shell, centroid)

    return {
        "status": "armed",
        "position": centroid,
        "count": len(selection),
        "samples": n,
    }


__all__ = ["spawn_at_selection_center"]
