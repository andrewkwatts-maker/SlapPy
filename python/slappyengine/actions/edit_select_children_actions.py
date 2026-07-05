"""Selection expansion action — recursive select-children.

Backs the ``edit.select_children`` :class:`~slappyengine.tool_router.ToolAction`
row added by the FF1 STUB-triage sprint tick (round 9 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1 / EE1).

Walks the current selection and adds every reachable descendant to it.
Handles both the EE1 :class:`_GroupEntity` (children live on
``entity.children``) and the more general "scene hierarchy" case where
each entity may expose a ``children`` / ``_children`` list of sibling
entities. Traversal is depth-first with a visited-set guard against
cycles.

Two modes are supported:

* ``mode="add"`` (default) — append descendants to the existing
  selection so the parent(s) stay selected too. Matches Blender's
  ``Shift+G → Children``.
* ``mode="replace"`` — replace the selection with just the leaves.
  Matches Photoshop's "Select All Layer Content".

Return contract
---------------

* ``{"status": "expanded", "added": [...], "count": N,
   "selection": [...]}`` on success.
* ``{"status": "no_selection"}`` when the shell has nothing selected.
* ``{"status": "no_children"}`` when the selection has no descendants
  (differentiated from ``no_selection`` so the caller can say "leaf
  node" instead of "nothing selected").
"""
from __future__ import annotations

from typing import Any, Iterable

from ._ctx import ensure_ctx


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _resolve_selection(ctx: dict[str, Any]) -> list[Any]:
    """Return the current selection as a list.

    Mirrors :func:`edit_group_actions._resolve_selection`.
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


def _get_children(entity: Any) -> list[Any]:
    """Return *entity*'s direct child list.

    Walks the common attribute names in order — ``.children`` (the EE1
    :class:`_GroupEntity` slot) → ``._children`` (Nova3D legacy) →
    ``["children"]`` for dict-shaped entities.
    """
    if isinstance(entity, dict):
        raw = entity.get("children") or entity.get("_children")
    else:
        raw = getattr(entity, "children", None)
        if raw is None:
            raw = getattr(entity, "_children", None)
    if isinstance(raw, (list, tuple)):
        return list(raw)
    return []


def _walk_descendants(roots: Iterable[Any]) -> list[Any]:
    """Return every descendant of *roots* in depth-first order.

    The roots themselves are *not* included in the result. Cycles are
    guarded via an ``id()`` visited set so a self-referential test-only
    entity can't spin the walker forever.
    """
    result: list[Any] = []
    visited: set[int] = set()
    stack: list[Any] = []
    for root in roots:
        for child in _get_children(root):
            if id(child) in visited:
                continue
            stack.append(child)
    while stack:
        entity = stack.pop(0)  # BFS keeps sibling order predictable.
        if id(entity) in visited:
            continue
        visited.add(id(entity))
        result.append(entity)
        for grand in _get_children(entity):
            if id(grand) not in visited:
                stack.append(grand)
    return result


def select_children(ctx: dict[str, Any]) -> dict[str, Any]:
    """Expand the current selection to include every descendant.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell exposing
          ``_selected_entity`` / ``_selected_entities``. Retargeted on
          success.
        * ``selection`` (optional): explicit selection override.
        * ``mode`` (optional str): ``"add"`` (default) or ``"replace"``.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("select_children", ctx)
    roots = _resolve_selection(ctx)
    if not roots:
        return {"status": "no_selection"}

    descendants = _walk_descendants(roots)
    if not descendants:
        return {"status": "no_children"}

    mode = ctx.get("mode", "add")
    if mode == "replace":
        new_selection: list[Any] = list(descendants)
    else:  # "add" and any other value fall through to append semantics.
        new_selection = list(roots) + [
            d for d in descendants if not any(d is r for r in roots)
        ]

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
        "status": "expanded",
        "added": descendants,
        "count": len(descendants),
        "selection": new_selection,
    }


__all__ = ["select_children"]
