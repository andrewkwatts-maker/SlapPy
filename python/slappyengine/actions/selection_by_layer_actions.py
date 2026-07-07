"""Selection-by-layer action — grab every scene entity on the seed layers.

Backs the ``selection.by_layer``
:class:`~slappyengine.tool_router.ToolAction` row added by the QQ1
STUB-triage sprint tick (round 18).

Photoshop's ``Cmd+Alt+Click`` on the layer panel selects every pixel /
shape on a layer; Blender's ``Select → Same Collection`` grabs every
object in the active seed's collection. This helper is the SlapPyEngine
analogue: read the layer id of every seed entity, walk the scene, and
add every entity whose layer matches. Seeds are preserved.

Layer resolution order (per entity):

1. ``entity.layer`` — canonical slot.
2. ``entity.layer_id`` — legacy slot.
3. ``entity.tags["layer"]`` — tag-painter shim.
4. Falls back to ``"default"`` when the entity carries no layer.

Scene walk resolution
---------------------

* ``ctx["scene"]`` — explicit override (tests use this).
* ``shell._engine.scene`` — canonical shell hook.
* ``shell._scene`` — legacy attribute.

Return contract
---------------

* ``{"status": "selected", "selection": [...], "layers": [...],
   "added": N, "previous_count": M, "total": T}`` on success.
* ``{"status": "no_scene"}`` — no scene handle reachable.
* ``{"status": "no_selection"}`` — no seed selection to derive layers
  from.
* ``{"status": "unchanged", "selection": [...], "layers": [...]}`` —
  every same-layer entity was already selected.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_DEFAULT_LAYER = "default"


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


def _entity_layer(entity: Any) -> str:
    """Return the entity's layer id string.

    Consults ``entity.layer`` → ``entity.layer_id`` → ``entity.tags["layer"]``
    in order; falls through to ``"default"``.
    """
    if isinstance(entity, dict):
        for key in ("layer", "layer_id"):
            val = entity.get(key)
            if val:
                return str(val)
        tags = entity.get("tags")
        if isinstance(tags, dict):
            val = tags.get("layer")
            if val:
                return str(val)
        return _DEFAULT_LAYER
    for attr in ("layer", "layer_id"):
        val = getattr(entity, attr, None)
        if val:
            return str(val)
    tags = getattr(entity, "tags", None)
    if isinstance(tags, dict):
        val = tags.get("layer")
        if val:
            return str(val)
    return _DEFAULT_LAYER


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


def select_by_layer(ctx: dict[str, Any]) -> dict[str, Any]:
    """Extend the selection to every scene entity on the seed's layers.

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
    ensure_ctx("select_by_layer", ctx)
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}
    seed = _resolve_selection(ctx)
    if not seed:
        return {"status": "no_selection"}

    layers: list[str] = []
    seen: set[str] = set()
    for entity in seed:
        L = _entity_layer(entity)
        if L not in seen:
            seen.add(L)
            layers.append(L)

    entities = _list_scene_entities(scene)
    seed_ids = {id(e) for e in seed}
    result: list[Any] = list(seed)
    result_ids = set(seed_ids)
    for candidate in entities:
        if id(candidate) in result_ids:
            continue
        if _entity_layer(candidate) in seen:
            result.append(candidate)
            result_ids.add(id(candidate))

    added = len(result) - len(seed)
    shell = _get_shell(ctx)
    _write_selection(shell, result)

    if added == 0:
        return {
            "status": "unchanged",
            "selection": result,
            "layers": layers,
            "previous_count": len(seed),
        }
    return {
        "status": "selected",
        "selection": result,
        "layers": layers,
        "added": added,
        "previous_count": len(seed),
        "total": len(result),
    }


__all__ = ["select_by_layer"]
