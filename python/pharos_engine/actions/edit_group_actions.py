"""Group / ungroup actions — wrap selected entities into a Group entity.

Backs two :class:`~pharos_engine.tool_router.ToolAction` rows added by
the EE1 STUB-triage sprint tick (round 8 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1):

* ``edit.group_selection`` — bundle every entity in the current selection
  into a new ``GroupEntity`` sitting at the selection's centroid. The
  original entities are re-parented under the group (each child's
  ``position`` is rewritten to be relative to the centroid so the visual
  result is unchanged) and the shell's selection is retargeted at the
  new group so subsequent operations act on the wrapper.
* ``edit.ungroup_selection`` — flatten a selected group. Each child is
  re-added to the scene at ``group.position + child.position`` and the
  group entity is removed. The shell's selection is retargeted at the
  released children so a subsequent operation can act on them.

The action deliberately owns a tiny :class:`_GroupEntity` local type
rather than pulling in ``pharos_engine.scene.GroupEntity`` — the scene
module doesn't ship a group primitive today. A dict-shaped fallback is
used when the scene refuses attribute-style entities so the CLI and
tests don't fall over.

Return contract
---------------

* ``group_selection``:
  - ``{"status": "grouped", "group": <entity>, "count": N,
     "centroid": (x, y, z)}`` on success.
  - ``{"status": "no_selection"}`` when the shell has nothing selected.
  - ``{"status": "no_scene"}`` when no scene is reachable.
* ``ungroup_selection``:
  - ``{"status": "ungrouped", "children": [...], "count": N}`` on success.
  - ``{"status": "no_selection"}`` when nothing is selected.
  - ``{"status": "not_a_group"}`` when the selection is not a group.
  - ``{"status": "no_scene"}`` when no scene is reachable.
"""
from __future__ import annotations

from typing import Any, Iterable

from ._ctx import ensure_ctx


# ---------------------------------------------------------------------------
# Shared resolution helpers (kept private — no cross-module reuse yet)
# ---------------------------------------------------------------------------


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _get_scene(ctx: dict[str, Any]) -> Any:
    """Resolve a scene handle — mirrors selection_actions._get_scene."""
    scene = ctx.get("scene")
    if scene is not None:
        return scene
    shell = _get_shell(ctx)
    if shell is None:
        return None
    engine = getattr(shell, "_engine", None)
    if engine is not None:
        scene = (
            getattr(engine, "scene", None)
            or getattr(engine, "_scene", None)
        )
        if scene is not None:
            return scene
    return getattr(shell, "_scene", None)


def _resolve_selection(ctx: dict[str, Any]) -> list[Any]:
    """Return the entities backing the current selection as a list.

    Matches the search order used by
    :mod:`pharos_engine.actions.selection_actions`.
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


# ---------------------------------------------------------------------------
# Position + centroid helpers — tolerate list / tuple / attr / dict entities
# ---------------------------------------------------------------------------


def _entity_position(entity: Any) -> list[float]:
    """Return the entity's position as a 3-list (pads Z with 0.0).

    Consumes ``entity.position`` / ``entity["position"]`` /
    ``entity.origin`` / ``entity["origin"]`` in that order. Silently
    returns ``[0.0, 0.0, 0.0]`` when no positional field is found.
    """
    for key in ("position", "origin", "pos"):
        raw = None
        if isinstance(entity, dict):
            raw = entity.get(key)
        else:
            raw = getattr(entity, key, None)
        if isinstance(raw, (list, tuple)) and raw:
            try:
                vals = [float(v) for v in raw]
            except (TypeError, ValueError):
                continue
            while len(vals) < 3:
                vals.append(0.0)
            return vals[:3]
    return [0.0, 0.0, 0.0]


def _write_entity_position(entity: Any, xyz: list[float]) -> None:
    """Write *xyz* onto whichever position field *entity* already exposes.

    Prefers the existing key. If none is present, seeds ``position``.
    """
    # Prefer to overwrite an existing key so we don't spuriously create
    # ``entity.position`` on an entity that only speaks ``origin``.
    for key in ("position", "origin", "pos"):
        if isinstance(entity, dict):
            if key in entity:
                entity[key] = list(xyz)
                return
        else:
            if getattr(entity, key, None) is not None:
                try:
                    setattr(entity, key, list(xyz))
                    return
                except Exception:  # noqa: BLE001
                    pass
    # No existing field — default to ``position``.
    if isinstance(entity, dict):
        entity["position"] = list(xyz)
    else:
        try:
            setattr(entity, "position", list(xyz))
        except Exception:  # noqa: BLE001
            pass


def _centroid(entities: Iterable[Any]) -> list[float]:
    """Return the mean position of *entities* as a 3-list."""
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for e in entities:
        pos = _entity_position(e)
        xs.append(pos[0])
        ys.append(pos[1])
        zs.append(pos[2])
    if not xs:
        return [0.0, 0.0, 0.0]
    return [sum(xs) / len(xs), sum(ys) / len(ys), sum(zs) / len(zs)]


# ---------------------------------------------------------------------------
# Group entity — attribute-style stub with a ``.children`` list
# ---------------------------------------------------------------------------


class _GroupEntity:
    """Local ``GroupEntity`` stand-in.

    Groups are a purely-editor concept today — the scene module does not
    ship a dedicated primitive. Rather than gate the whole action behind
    a phantom import, we expose a tiny attribute-holding class that walks
    like a duck-typed scene entity: ``position`` + ``children`` + optional
    ``name``.
    """

    def __init__(
        self,
        position: list[float] | None = None,
        children: list[Any] | None = None,
        name: str = "Group",
    ) -> None:
        self.position: list[float] = list(position or [0.0, 0.0, 0.0])
        self.children: list[Any] = list(children or [])
        self.name: str = name
        self.is_group: bool = True

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"_GroupEntity(name={self.name!r}, "
            f"position={self.position!r}, "
            f"children=[{len(self.children)}])"
        )


def _is_group(entity: Any) -> bool:
    """Return True iff *entity* looks like a group.

    Duck-types on ``.is_group == True`` (our own stub) plus the
    ``children`` list. Also accepts dict-shaped entities with
    ``{"kind": "group", "children": [...]}``.
    """
    if isinstance(entity, _GroupEntity):
        return True
    if isinstance(entity, dict):
        if entity.get("kind") == "group" or entity.get("is_group") is True:
            children = entity.get("children")
            return isinstance(children, list)
        return False
    if getattr(entity, "is_group", False) is True:
        return isinstance(getattr(entity, "children", None), list)
    return False


def _group_children(entity: Any) -> list[Any]:
    """Return ``entity.children`` as a list (empty when absent)."""
    if isinstance(entity, dict):
        raw = entity.get("children")
    else:
        raw = getattr(entity, "children", None)
    return list(raw) if isinstance(raw, (list, tuple)) else []


# ---------------------------------------------------------------------------
# Scene-add / scene-remove helpers — mirror selection_actions.paste
# ---------------------------------------------------------------------------


def _scene_add(scene: Any, entity: Any) -> bool:
    """Best-effort add of *entity* to *scene*. Returns True on success."""
    for name in ("add_entity", "add", "_add_entity"):
        adder = getattr(scene, name, None)
        if callable(adder):
            try:
                adder(entity)
                return True
            except Exception:  # noqa: BLE001
                pass
    raw = getattr(scene, "_entities", None)
    if isinstance(raw, list):
        raw.append(entity)
        return True
    if isinstance(raw, dict):
        raw[id(entity)] = entity
        return True
    return False


def _scene_remove(scene: Any, entity: Any) -> bool:
    """Best-effort remove of *entity* from *scene*. Returns True on success."""
    for name in ("remove_entity", "remove", "_remove_entity"):
        remover = getattr(scene, name, None)
        if callable(remover):
            try:
                remover(entity)
                return True
            except Exception:  # noqa: BLE001
                pass
    raw = getattr(scene, "_entities", None)
    if isinstance(raw, list):
        try:
            raw.remove(entity)
            return True
        except ValueError:
            return False
    if isinstance(raw, dict):
        for key, val in list(raw.items()):
            if val is entity:
                del raw[key]
                return True
    return False


# ---------------------------------------------------------------------------
# Public API — group_selection + ungroup_selection
# ---------------------------------------------------------------------------


def group_selection(ctx: dict[str, Any]) -> dict[str, Any]:
    """Wrap the current selection into a fresh :class:`_GroupEntity`.

    Consumed ctx keys:

    * ``shell`` (optional): editor shell providing ``_selected_entity`` /
      ``_selected_entities``. Retargeted at the new group on success.
    * ``scene`` (optional): scene handle receiving the new group and
      losing the original entities.
    * ``selection`` (optional): explicit list of entities to group.
      Overrides the shell probe.
    * ``name`` (optional str): group name (default ``"Group"``).

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("group_selection", ctx)
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}
    entities = _resolve_selection(ctx)
    if not entities:
        return {"status": "no_selection"}
    centroid = _centroid(entities)

    # Re-parent each entity relative to the centroid so the visible
    # position stays the same when the group carries the offset.
    children: list[Any] = []
    for e in entities:
        pos = _entity_position(e)
        rel = [pos[0] - centroid[0], pos[1] - centroid[1], pos[2] - centroid[2]]
        _write_entity_position(e, rel)
        children.append(e)
        # Remove from scene so the group is the sole top-level owner.
        _scene_remove(scene, e)

    name = ctx.get("name") if isinstance(ctx.get("name"), str) else "Group"
    group = _GroupEntity(position=centroid, children=children, name=name)
    _scene_add(scene, group)

    # Retarget selection at the fresh group.
    shell = _get_shell(ctx)
    if shell is not None:
        try:
            setattr(shell, "_selected_entity", group)
        except Exception:  # noqa: BLE001
            pass
        try:
            setattr(shell, "_selected_entities", [group])
        except Exception:  # noqa: BLE001
            pass

    return {
        "status": "grouped",
        "group": group,
        "count": len(children),
        "centroid": tuple(centroid),
    }


def ungroup_selection(ctx: dict[str, Any]) -> dict[str, Any]:
    """Flatten a selected group back to its constituent children.

    Each child gets ``group.position + child.position`` written back so
    the visible layout is preserved. The group entity itself is removed
    from the scene and the shell selection is retargeted at the
    released children.

    When the selection contains multiple groups, every group is
    flattened in-order. Non-group entries in the selection are left
    alone. When no group is present the helper returns
    ``{"status": "not_a_group"}``.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("ungroup_selection", ctx)
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}
    entities = _resolve_selection(ctx)
    if not entities:
        return {"status": "no_selection"}

    groups = [e for e in entities if _is_group(e)]
    if not groups:
        return {"status": "not_a_group"}

    released: list[Any] = []
    for group in groups:
        group_pos = _entity_position(group)
        for child in _group_children(group):
            child_pos = _entity_position(child)
            _write_entity_position(
                child,
                [
                    child_pos[0] + group_pos[0],
                    child_pos[1] + group_pos[1],
                    child_pos[2] + group_pos[2],
                ],
            )
            _scene_add(scene, child)
            released.append(child)
        _scene_remove(scene, group)

    shell = _get_shell(ctx)
    if shell is not None:
        try:
            setattr(shell, "_selected_entities", list(released))
        except Exception:  # noqa: BLE001
            pass
        try:
            setattr(
                shell,
                "_selected_entity",
                released[0] if released else None,
            )
        except Exception:  # noqa: BLE001
            pass

    return {
        "status": "ungrouped",
        "children": released,
        "count": len(released),
    }


__all__ = [
    "group_selection",
    "ungroup_selection",
    "_GroupEntity",
]
