"""Tab-through selection actions — select next / previous entity.

Backs the ``edit.select_next`` and ``edit.select_previous``
:class:`~slappyengine.tool_router.ToolAction` rows added by the II5
STUB-triage sprint tick (round 11 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1 / EE1 / FF1 / GG1).

Implements the "Tab / Shift+Tab through the scene" flow that every DCC
ships (Blender's ``[`` / ``]``, Maya's ``,`` / ``.``, After Effects'
``F2`` / ``Shift+F2``). Walks the same
:mod:`slappyengine.actions.edit_invert_selection_actions` scene-entity
iterator so ordering matches "select all" / "invert selection" — a Tab
cycle over N entities produces exactly the same N entities the
``select_all`` helper reports, in order.

Behavioural rules
-----------------

* **Cursor** — the "current" position in the roster is resolved from
  ``shell._selected_entity``. When no single entity is selected the
  cursor lands *before* the first entry so ``select_next`` picks entity
  ``0`` and ``select_previous`` picks entity ``N-1`` (matches Blender's
  behaviour on an empty selection).
* **Wrap** — the cursor wraps by default (``ctx["wrap"] = True``). Pass
  ``wrap=False`` to clamp; the helper then returns ``at_end`` /
  ``at_start`` when there's nowhere to move.
* **Locked / hidden** — locked (``entity.locked``) and hidden
  (``entity.visible = False``) entries are skipped by default so Tab
  never lands on an unclickable entry. ``ctx["include_locked"]`` /
  ``ctx["include_hidden"]`` opt back in.

Return contract
---------------

* ``{"status": "selected", "entity": <ent>, "index": i,
   "previous_index": p, "count": N}`` on success.
* ``{"status": "no_scene"}`` when no scene is reachable.
* ``{"status": "empty_scene"}`` when the walkable roster is empty
  (either no entities or all filtered out by locked/hidden).
* ``{"status": "at_end"}`` when ``wrap=False`` and the cursor is on the
  last entity for ``select_next``.
* ``{"status": "at_start"}`` when ``wrap=False`` and the cursor is on
  the first entity for ``select_previous``.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx
from .edit_invert_selection_actions import (
    _get_scene,
    _get_shell,
    _is_hidden,
    _is_locked,
    _walk_scene_entities,
)


def _current_entity(ctx: dict[str, Any]) -> Any:
    """Return the entity to treat as the cursor position (or None)."""
    override = ctx.get("current")
    if override is not None:
        return override
    shell = _get_shell(ctx)
    if shell is None:
        return None
    return getattr(shell, "_selected_entity", None)


def _filter_roster(
    entities: list[Any],
    *,
    include_locked: bool,
    include_hidden: bool,
) -> list[Any]:
    """Drop locked / hidden entries unless the flags opt them back in."""
    out: list[Any] = []
    for entity in entities:
        if not include_locked and _is_locked(entity):
            continue
        if not include_hidden and _is_hidden(entity):
            continue
        out.append(entity)
    return out


def _index_of(current: Any, roster: list[Any]) -> int:
    """Return the index of *current* in *roster* (identity match) or -1."""
    if current is None:
        return -1
    cur_id = id(current)
    for i, entity in enumerate(roster):
        if id(entity) == cur_id:
            return i
    return -1


def _apply_selection(shell: Any, entity: Any) -> None:
    """Best-effort assignment of the new selection to *shell*."""
    if shell is None:
        return
    try:
        setattr(shell, "_selected_entity", entity)
    except Exception:  # noqa: BLE001
        pass
    try:
        setattr(shell, "_selected_entities", [entity])
    except Exception:  # noqa: BLE001
        pass


def _step(ctx: dict[str, Any], *, direction: int, fn_name: str) -> dict[str, Any]:
    """Shared implementation for select_next / select_previous."""
    ensure_ctx(fn_name, ctx)
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}

    all_entities = _walk_scene_entities(scene)
    include_locked = bool(ctx.get("include_locked", False))
    include_hidden = bool(ctx.get("include_hidden", False))
    roster = _filter_roster(
        all_entities,
        include_locked=include_locked,
        include_hidden=include_hidden,
    )
    if not roster:
        return {"status": "empty_scene"}

    wrap = bool(ctx.get("wrap", True))
    current = _current_entity(ctx)
    idx = _index_of(current, roster)
    n = len(roster)

    # Empty-selection cursor: pretend we're just before roster[0] so
    # forward moves land on 0 and backward moves land on N-1.
    if idx == -1:
        target = 0 if direction > 0 else n - 1
    else:
        target = idx + direction
        if target < 0:
            if not wrap:
                return {"status": "at_start"}
            target = n - 1
        elif target >= n:
            if not wrap:
                return {"status": "at_end"}
            target = 0

    entity = roster[target]
    _apply_selection(_get_shell(ctx), entity)
    return {
        "status": "selected",
        "entity": entity,
        "index": target,
        "previous_index": idx,
        "count": n,
    }


def select_next(ctx: dict[str, Any]) -> dict[str, Any]:
    """Advance the selection to the next entity in the scene roster.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell; both
          ``_selected_entity`` (single) and ``_selected_entities`` (list)
          are retargeted on success.
        * ``scene`` (optional): scene override — bypasses the shell
          scene resolver.
        * ``current`` (optional): explicit current-cursor entity.
        * ``wrap`` (optional bool, default ``True``): wrap past the end.
        * ``include_locked`` / ``include_hidden`` (optional bool,
          default ``False``): opt in to locked / hidden entries.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    return _step(ctx, direction=+1, fn_name="select_next")


def select_previous(ctx: dict[str, Any]) -> dict[str, Any]:
    """Retreat the selection to the previous entity in the scene roster.

    Same ctx contract as :func:`select_next`; only the direction differs.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    return _step(ctx, direction=-1, fn_name="select_previous")


__all__ = ["select_next", "select_previous"]
