"""Selection-same-material action — grab every entity sharing the seed material.

Backs the ``selection.same_material``
:class:`~pharos_engine.tool_router.ToolAction` row added by the QQ1
STUB-triage sprint tick (round 18).

Blender's ``Select → Same Material``, Maya's ``Select → Same Shader``,
Painter's material droplet click — every DCC exposes a "select all
polygons / entities that reference this material" gesture. This helper
reads the material id of every seed entity, walks the scene, and adds
every entity whose material matches to the selection. Seeds are
preserved.

Material resolution order (per entity):

1. ``entity.material`` — canonical slot (string or object with ``.name``
   / ``.id``).
2. ``entity.material_id`` — legacy scalar slot.
3. ``entity.tags["material"]`` — tag-painter shim.

Scene walk resolution
---------------------

* ``ctx["scene"]`` — explicit override (tests use this).
* ``shell._engine.scene`` — canonical shell hook.
* ``shell._scene`` — legacy attribute.

Return contract
---------------

* ``{"status": "selected", "selection": [...], "materials": [...],
   "added": N, "previous_count": M, "total": T}`` on success.
* ``{"status": "no_scene"}`` — no scene handle reachable.
* ``{"status": "no_selection"}`` — no seed selection.
* ``{"status": "no_materials"}`` — none of the seed entities carry a
  resolvable material id; nothing to match against.
* ``{"status": "unchanged", "selection": [...], "materials": [...]}`` —
  every same-material entity was already selected.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _get_scene(ctx: dict[str, Any]) -> Any:
    scene = ctx.get("scene")
    if scene is not None:
        return scene
    shell = _get_shell(ctx)
    if shell is None:
        return None
    engine = getattr(shell, "_engine", None)
    if engine is not None:
        cand = getattr(engine, "scene", None) or getattr(engine, "_scene", None)
        if cand is not None:
            return cand
    return getattr(shell, "_scene", None)


def _list_scene_entities(scene: Any) -> list[Any]:
    entities_attr = getattr(scene, "entities", None)
    if entities_attr is not None:
        try:
            return [e for e in list(entities_attr) if e is not None]
        except TypeError:
            pass
    getter = getattr(scene, "get_entities", None)
    if callable(getter):
        try:
            return [e for e in list(getter()) if e is not None]
        except Exception:  # noqa: BLE001
            return []
    return []


def _resolve_selection(ctx: dict[str, Any]) -> list[Any]:
    override = ctx.get("selection")
    if override is not None:
        if isinstance(override, (list, tuple, set)):
            return [x for x in override if x is not None]
        return [override]
    shell = _get_shell(ctx)
    if shell is None:
        return []
    for attr in ("_selected_entities", "selection", "_selection"):
        val = getattr(shell, attr, None)
        if val is None:
            continue
        if isinstance(val, (list, tuple, set)):
            return [x for x in val if x is not None]
    single = getattr(shell, "_selected_entity", None)
    if single is not None:
        return [single]
    return []


def _material_key(raw: Any) -> str | None:
    """Coerce a material handle / id / object into a comparison key.

    Strings are returned trimmed. Objects consult ``.name`` / ``.id``
    then fall through to ``str(obj)``. Empty / whitespace-only keys
    return ``None`` so the caller can distinguish "no material" from
    "empty string".
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        s = raw.strip()
        return s or None
    for attr in ("name", "id"):
        val = getattr(raw, attr, None)
        if isinstance(val, str) and val.strip():
            return val.strip()
    try:
        s = str(raw).strip()
    except Exception:  # noqa: BLE001
        return None
    return s or None


def _entity_material(entity: Any) -> str | None:
    if isinstance(entity, dict):
        for key in ("material", "material_id"):
            got = _material_key(entity.get(key))
            if got is not None:
                return got
        tags = entity.get("tags")
        if isinstance(tags, dict):
            got = _material_key(tags.get("material"))
            if got is not None:
                return got
        return None
    for attr in ("material", "material_id"):
        got = _material_key(getattr(entity, attr, None))
        if got is not None:
            return got
    tags = getattr(entity, "tags", None)
    if isinstance(tags, dict):
        got = _material_key(tags.get("material"))
        if got is not None:
            return got
    return None


def _write_selection(shell: Any, selection: list[Any]) -> None:
    if shell is None:
        return
    for attr in ("_selected_entities", "selection", "_selection"):
        if hasattr(shell, attr):
            try:
                setattr(shell, attr, list(selection))
                break
            except Exception:  # noqa: BLE001
                continue
    else:
        try:
            setattr(shell, "_selected_entities", list(selection))
        except Exception:  # noqa: BLE001
            pass


def select_same_material(ctx: dict[str, Any]) -> dict[str, Any]:
    """Extend the selection to every scene entity sharing the seed material(s).

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``selection`` (optional): explicit seed selection.
        * ``shell`` (optional): editor shell — provides selection
          fallback + receives the updated selection.
        * ``scene`` (optional): scene handle.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("select_same_material", ctx)
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}
    seed = _resolve_selection(ctx)
    if not seed:
        return {"status": "no_selection"}

    materials: list[str] = []
    seen: set[str] = set()
    for entity in seed:
        mat = _entity_material(entity)
        if mat is None or mat in seen:
            continue
        seen.add(mat)
        materials.append(mat)

    if not materials:
        return {"status": "no_materials", "previous_count": len(seed)}

    entities = _list_scene_entities(scene)
    seed_ids = {id(e) for e in seed}
    result: list[Any] = list(seed)
    result_ids = set(seed_ids)
    for candidate in entities:
        if id(candidate) in result_ids:
            continue
        mat = _entity_material(candidate)
        if mat is not None and mat in seen:
            result.append(candidate)
            result_ids.add(id(candidate))

    added = len(result) - len(seed)
    shell = _get_shell(ctx)
    _write_selection(shell, result)

    if added == 0:
        return {
            "status": "unchanged",
            "selection": result,
            "materials": materials,
            "previous_count": len(seed),
        }
    return {
        "status": "selected",
        "selection": result,
        "materials": materials,
        "added": added,
        "previous_count": len(seed),
        "total": len(result),
    }


__all__ = ["select_same_material"]
