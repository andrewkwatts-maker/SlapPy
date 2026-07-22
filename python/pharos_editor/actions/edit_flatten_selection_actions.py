"""Edit-flatten-selection action — recursively unpack every group in the selection.

Backs the ``edit.flatten_selection``
:class:`~pharos_editor.tool_router.ToolAction` row added by the UU4
STUB-triage sprint tick (round 22).

Distinct from EE1's ``edit.ungroup_selection`` — that verb only peels
one nesting level (``group → children`` back to the scene root). This
verb walks the *entire* selection tree, so ``group(group(a, b), c)``
collapses to ``[a, b, c]`` in one gesture. Every DCC ships this: Blender
``Alt+P`` "Clear Parent Inverse", Krita's "Flatten Group Layer", Adobe
Illustrator's "Object → Ungroup All", Nova3D's ``Selection → Flatten
Groups (Deep)``.

Child positions are re-computed to their absolute world coordinates by
summing ``group.position`` up the chain — matches ``edit_group_actions``'
"child-relative-to-centroid" convention when *building* a group.

Selection resolution matches ``edit_group_actions``:

* ``ctx["selection"]`` — explicit override.
* ``ctx["shell"]._selected_entities`` — canonical multi-select.
* ``ctx["shell"]._selected_entity`` — legacy single-select.

Return contract
---------------

* ``{"status": "flattened", "released": [...], "count": N,
   "groups_removed": G}`` — success. ``N`` is the total number of leaf
   entities re-added to the scene; ``G`` is the count of group entities
   that got removed.
* ``{"status": "no_selection"}`` — nothing selected.
* ``{"status": "no_groups"}`` — selection contained no group entities
  (nothing to flatten — matches Adobe Illustrator's toast).
* ``{"status": "no_scene"}`` — no scene reachable.
"""
from __future__ import annotations

from typing import Any

from . import edit_group_actions as _eg
from ._ctx import ensure_ctx


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _resolve_selection(ctx: dict[str, Any]) -> list[Any]:
    return _eg._resolve_selection(ctx)


def _flatten_walk(
    entity: Any,
    offset: tuple[float, float, float],
) -> tuple[list[Any], int]:
    """Recursively unpack *entity* offset by *offset*.

    Returns ``(leaves, groups_seen)`` — leaves are entities whose
    ``position`` has been rewritten to world space; groups_seen is the
    count of group entities the walk *entered* (so callers can report
    how many wrappers vanished).
    """
    if not _eg._is_group(entity):
        # Leaf — shift into world space by the accumulated offset.
        pos = _eg._entity_position(entity)
        world = [pos[0] + offset[0], pos[1] + offset[1], pos[2] + offset[2]]
        _eg._write_entity_position(entity, world)
        return ([entity], 0)

    # Group — accumulate offset and recurse.
    grp_pos = _eg._entity_position(entity)
    new_offset = (
        offset[0] + grp_pos[0],
        offset[1] + grp_pos[1],
        offset[2] + grp_pos[2],
    )
    children = _eg._group_children(entity)
    leaves: list[Any] = []
    groups_seen = 1
    for child in children:
        sub_leaves, sub_groups = _flatten_walk(child, new_offset)
        leaves.extend(sub_leaves)
        groups_seen += sub_groups
    return (leaves, groups_seen)


def _write_selection(shell: Any, entities: list[Any]) -> None:
    if shell is None:
        return
    try:
        setattr(shell, "_selected_entities", list(entities))
    except Exception:  # noqa: BLE001
        pass
    # Legacy single-select mirror.
    try:
        setattr(shell, "_selected_entity", entities[0] if entities else None)
    except Exception:  # noqa: BLE001
        pass


def flatten_selection(ctx: dict[str, Any]) -> dict[str, Any]:
    """Recursively unpack every group entity in the current selection.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``selection`` (optional): explicit selection override.
        * ``shell`` (optional): editor shell (fallback selection source
          + selection retarget).
        * ``scene`` (optional): explicit scene handle.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("flatten_selection", ctx)
    selection = _resolve_selection(ctx)
    if not selection:
        return {"status": "no_selection"}

    # If nothing in the selection is a group, there's nothing to flatten.
    if not any(_eg._is_group(e) for e in selection):
        return {"status": "no_groups"}

    scene = _eg._get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}

    released: list[Any] = []
    groups_removed = 0
    for entity in selection:
        leaves, groups_seen = _flatten_walk(entity, (0.0, 0.0, 0.0))
        released.extend(leaves)
        if _eg._is_group(entity):
            groups_removed += groups_seen
            _eg._scene_remove(scene, entity)
            for leaf in leaves:
                _eg._scene_add(scene, leaf)
        # Non-group leaves stay where they were — already in the scene.

    shell = _get_shell(ctx)
    _write_selection(shell, released)

    return {
        "status": "flattened",
        "released": released,
        "count": len(released),
        "groups_removed": groups_removed,
    }


__all__ = ["flatten_selection"]
