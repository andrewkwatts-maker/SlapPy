"""Selection navigation action — walk up to the scene root.

Backs the ``edit.select_root``
:class:`~pharos_editor.tool_router.ToolAction` row added by the ZZ4
STUB-triage sprint tick (round 26 after YY4).

Distinct from the sibling selection-navigation verbs:

* YY4's ``edit.select_parent`` walks *one step* up the parent-child
  DAG. This verb walks *all the way up* — repeatedly follows the
  parent pointer until it hits a root (an entity with no parent).
  Matches Blender's ``]`` shortcut (select outermost parent) and
  Unity's Ctrl+Shift+Home (walk to hierarchy root).
* FF1's ``edit.select_children`` walks *down* the hierarchy
  expanding the selection to include every descendant.
* PP2's ``edit.select_next`` / ``edit.select_previous`` walk
  *sideways* through sibling entities.
* QQ1's ``selection.by_type`` / ``selection.by_layer`` /
  ``selection.same_material`` and WW4's ``edit.select_by_tag`` walk
  the *flat* scene entity list by attribute.
* NN1's ``selection.grow`` / ``selection.shrink`` walk spatial /
  topological neighbours, not the parent-child DAG.

Parent resolution
-----------------

Every entity is probed for its parent in priority order (matches
``edit.select_parent`` — keeps the two verbs on the same walker):

1. ``entity.parent`` — canonical scene-graph attribute.
2. ``entity._parent`` — private/legacy alias.
3. ``entity["parent"]`` — dict-shaped entities.

An entity is a **root** when the resolved parent is ``None`` OR when
walking any further would revisit an already-seen entity (cycle
guard — prevents infinite loops from corrupt hierarchies).

Modes
-----

* ``mode="replace"`` (default) — replace the selection with the
  roots. Matches Blender's ``]``.
* ``mode="add"`` — append roots to the existing selection so both the
  original picks and their roots stay selected. Matches Unity's
  Ctrl+click walk.

Return contract
---------------

* ``{"status": "walked", "roots": [...], "count": N,
   "selection": [...]}`` on success.
* ``{"status": "no_selection"}`` — nothing selected.

Every selection member always resolves to *itself* if it's already a
root, so the only failure mode is "nothing selected". Compare with
``edit.select_parent`` which returns ``no_parent`` when every pick is
a root — this verb *targets* the root, so a selection of roots simply
returns the same set.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


# Hard cap on parent-walk depth — matches Nova3D's SceneGraph guard.
_MAX_DEPTH: int = 64


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _resolve_selection(ctx: dict[str, Any]) -> list[Any]:
    """Return the current selection as a list.

    Mirrors :func:`edit_select_parent_actions._resolve_selection`.
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


def _walk_to_root(entity: Any) -> Any:
    """Walk up until a root is reached (cycle-guarded, depth-capped).

    Returns *entity* itself when the entity is already a root.
    """
    seen: set[int] = {id(entity)}
    current = entity
    for _ in range(_MAX_DEPTH):
        parent = _get_parent(current)
        if parent is None:
            return current
        if id(parent) in seen:
            # Cycle — treat current as effective root.
            return current
        seen.add(id(parent))
        current = parent
    return current


def _dedupe_by_identity(items: list[Any]) -> list[Any]:
    seen: set[int] = set()
    out: list[Any] = []
    for item in items:
        if id(item) in seen:
            continue
        seen.add(id(item))
        out.append(item)
    return out


def select_root(ctx: dict[str, Any]) -> dict[str, Any]:
    """Replace / extend the selection with the roots of the current picks.

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
    ensure_ctx("select_root", ctx)
    picks = _resolve_selection(ctx)
    if not picks:
        return {"status": "no_selection"}

    roots: list[Any] = []
    for pick in picks:
        roots.append(_walk_to_root(pick))
    roots = _dedupe_by_identity(roots)

    mode = ctx.get("mode", "replace")
    if mode == "add":
        new_selection = _dedupe_by_identity(list(picks) + roots)
    else:  # "replace" and any other value default to replace semantics.
        new_selection = list(roots)

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
        "roots": roots,
        "count": len(roots),
        "selection": new_selection,
    }


__all__ = ["select_root", "_MAX_DEPTH"]
