"""Selection navigation action — walk up to the parent entity.

Backs the ``edit.select_parent``
:class:`~pharos_engine.tool_router.ToolAction` row added by the YY4
STUB-triage sprint tick (round 25 after WW4).

Distinct from the sibling selection-navigation verbs:

* FF1's ``edit.select_children`` walks *down* the hierarchy expanding
  the selection to include every descendant.
* PP2's ``edit.select_next`` / ``edit.select_previous`` walk *sideways*
  through sibling entities.
* QQ1's ``selection.by_type`` / ``selection.by_layer`` /
  ``selection.same_material`` and WW4's ``edit.select_by_tag`` walk
  the *flat* scene entity list by attribute.
* NN1's ``selection.grow`` / ``selection.shrink`` walk spatial /
  topological neighbours, not the parent-child DAG.

This verb walks *one step up* from every selected entity to its
parent. Matches Blender's ``[`` (select parent), Unity's ``Ctrl+Shift+↑``
(walk to parent object in hierarchy), and Nova3D's Outliner ``P``
shortcut.

Parent resolution
-----------------

Every entity is probed for its parent in priority order:

1. ``entity.parent`` — canonical scene-graph attribute.
2. ``entity._parent`` — private/legacy alias.
3. ``entity["parent"]`` — dict-shaped entities.

Entities with no reachable parent are silently skipped; when *every*
selected entity is a root the return status is ``no_parent``.

Modes
-----

* ``mode="replace"`` (default) — replace the selection with the
  parents. Matches Blender's ``[``.
* ``mode="add"`` — append parents to the existing selection so both
  parent and child stay selected. Matches Unity's Ctrl+click walk.

Return contract
---------------

* ``{"status": "walked", "parents": [...], "count": N,
   "selection": [...]}`` on success.
* ``{"status": "no_selection"}`` — nothing selected.
* ``{"status": "no_parent"}`` — every selection member is a root.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _resolve_selection(ctx: dict[str, Any]) -> list[Any]:
    """Return the current selection as a list.

    Mirrors :func:`edit_select_children_actions._resolve_selection`.
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


def _get_parent(entity: Any) -> Any:
    """Return *entity*'s parent handle (or ``None`` when it is a root).

    Walks the common attribute names in order — ``.parent`` (canonical)
    → ``._parent`` (legacy) → ``["parent"]`` for dict-shaped entities.
    """
    if isinstance(entity, dict):
        return entity.get("parent") or entity.get("_parent")
    raw = getattr(entity, "parent", None)
    if raw is not None:
        return raw
    return getattr(entity, "_parent", None)


def _dedupe_by_identity(items: list[Any]) -> list[Any]:
    seen: set[int] = set()
    out: list[Any] = []
    for item in items:
        if id(item) in seen:
            continue
        seen.add(id(item))
        out.append(item)
    return out


def select_parent(ctx: dict[str, Any]) -> dict[str, Any]:
    """Replace / extend the selection with the parents of the current picks.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell exposing
          ``_selected_entity`` / ``_selected_entities``. Retargeted on
          success.
        * ``selection`` (optional): explicit selection override.
        * ``mode`` (optional str): ``"replace"`` (default) or ``"add"``.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("select_parent", ctx)
    children = _resolve_selection(ctx)
    if not children:
        return {"status": "no_selection"}

    parents: list[Any] = []
    for child in children:
        parent = _get_parent(child)
        if parent is not None:
            parents.append(parent)
    parents = _dedupe_by_identity(parents)

    if not parents:
        return {"status": "no_parent"}

    mode = ctx.get("mode", "replace")
    if mode == "add":
        new_selection = _dedupe_by_identity(list(children) + parents)
    else:  # "replace" and any other value default to replace semantics.
        new_selection = list(parents)

    shell = _get_shell(ctx)
    if shell is not None:
        try:
            setattr(shell, "_selected_entities", list(new_selection))
        except Exception:  # noqa: BLE001
            pass
        try:
            setattr(
                shell,
                "_selected_entity",
                new_selection[0] if new_selection else None,
            )
        except Exception:  # noqa: BLE001
            pass

    return {
        "status": "walked",
        "parents": parents,
        "count": len(parents),
        "selection": new_selection,
    }


__all__ = ["select_parent"]
