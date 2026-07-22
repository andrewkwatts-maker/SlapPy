"""Layer-clear action — remove every entity on a Z-layer, preserving the layer.

Backs the ``layer.clear``
:class:`~pharos_engine.tool_router.ToolAction` row added by the WW4
STUB-triage sprint tick (round 24 after VV4).

Distinct from the sibling layer verbs:

* VV4's ``layer.delete`` removes the layer *entry* from the scene
  (refuses the last-remaining-layer). This verb keeps the entry
  but wipes its contents.
* OO1's ``layer.merge_down`` moves entities into another layer.
* DD1's ``edit.duplicate_layer`` clones an existing layer.
* TT2's ``layer.rename`` touches the name only.
* UU4's ``layer.move_up`` / ``layer.move_down`` reorders.
* RR1's ``layer.hide_others`` / ``layer.isolate`` toggle visibility.

Every layered DCC ships this verb: Photoshop's Layers-panel
"Delete Layer Contents" / Krita's Layer → Clear Layer / Affinity
Photo's Layer → Clear Contents. Nova3D exposes it via the
Layer-panel right-click menu.

Target resolution
-----------------

* ``ctx["layer"]`` — explicit override (tests use this).
* ``ctx["layer_name"]`` — string name lookup against
  ``scene.z_layers``.
* ``shell._active_layer`` — the shell-owned pointer.
* No fallback — when nothing resolves, returns ``no_layer``.

Entity walk
-----------

Entities are matched to the target layer by inspecting each
entity's ``z_layer`` (canonical) / ``layer`` / ``_layer`` attribute.
The compare is *by identity* first (``entity.layer is target``),
then by *layer name* fallback so scenes that store the layer by
name string still get their contents wiped.

The removal itself walks in priority order:

1. ``scene.remove_entity(entity)`` — canonical scene API.
2. ``scene.entities.remove(entity)`` — direct list mutation.
3. ``scene._entities.remove(entity)`` — legacy list.

Return contract
---------------

* ``{"status": "cleared", "target": str, "z": float,
   "removed": N, "kept": M}`` on success (``removed`` may be zero).
* ``{"status": "no_scene"}`` — no scene reachable.
* ``{"status": "no_layer"}`` — no target layer resolvable.
* ``{"status": "error", "message": str}`` — scene refused the remove.
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


def _list_layers(scene: Any) -> list[Any]:
    layers_attr = getattr(scene, "z_layers", None)
    if layers_attr is None:
        return []
    try:
        return [l for l in list(layers_attr) if l is not None]
    except TypeError:
        return []


def _layer_name(layer: Any) -> str:
    return str(getattr(layer, "name", "") or "")


def _layer_z(layer: Any) -> float:
    try:
        return float(getattr(layer, "z", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _find_by_name(layers: list[Any], name: str) -> Any:
    for layer in layers:
        if _layer_name(layer) == name:
            return layer
    return None


def _resolve_target(ctx: dict[str, Any], layers: list[Any]) -> Any:
    override = ctx.get("layer")
    if override is not None:
        return override
    name = ctx.get("layer_name")
    if isinstance(name, str) and name:
        got = _find_by_name(layers, name)
        if got is not None:
            return got
    shell = _get_shell(ctx)
    if shell is not None:
        active = getattr(shell, "_active_layer", None)
        if active is not None:
            return active
    return None


def _list_scene_entities(scene: Any) -> list[Any]:
    for attr in ("entities", "_entities"):
        raw = getattr(scene, attr, None)
        if raw is None:
            continue
        try:
            return [e for e in list(raw) if e is not None]
        except TypeError:
            continue
    return []


def _entity_layer(entity: Any) -> Any:
    for attr in ("z_layer", "layer", "_layer"):
        val = getattr(entity, attr, None)
        if val is not None:
            return val
    return None


def _entity_matches(entity: Any, target: Any, target_name: str) -> bool:
    got = _entity_layer(entity)
    if got is None:
        return False
    if got is target:
        return True
    # Name fallback — the entity may store the layer *name* string.
    if isinstance(got, str) and target_name:
        return got == target_name
    if _layer_name(got) and _layer_name(got) == target_name:
        return True
    return False


def _remove_entity(scene: Any, entity: Any) -> bool:
    remover = getattr(scene, "remove_entity", None)
    if callable(remover):
        try:
            remover(entity)
            return True
        except Exception:  # noqa: BLE001
            return False
    for attr in ("entities", "_entities"):
        raw = getattr(scene, attr, None)
        if isinstance(raw, list):
            try:
                raw.remove(entity)
                return True
            except ValueError:
                continue
    return False


def clear_layer(ctx: dict[str, Any]) -> dict[str, Any]:
    """Remove every entity assigned to the target Z-layer.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``layer`` (optional): explicit target.
        * ``layer_name`` (optional str): name lookup.
        * ``scene`` (optional): explicit scene handle.
        * ``shell`` (optional): editor shell — provides
          ``_active_layer`` fallback.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("clear_layer", ctx)
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}
    layers = _list_layers(scene)
    target = _resolve_target(ctx, layers)
    if target is None:
        return {"status": "no_layer"}

    target_name = _layer_name(target)
    target_z = _layer_z(target)

    entities = _list_scene_entities(scene)
    victims: list[Any] = []
    kept = 0
    for entity in entities:
        if _entity_matches(entity, target, target_name):
            victims.append(entity)
        else:
            kept += 1

    removed = 0
    for entity in victims:
        if _remove_entity(scene, entity):
            removed += 1
    if removed < len(victims):
        # Some scene refused the remove — surface for the caller.
        return {
            "status": "error",
            "message": (
                f"scene remove refused {len(victims) - removed} of "
                f"{len(victims)} entities on layer {target_name!r}"
            ),
        }

    return {
        "status": "cleared",
        "target": target_name,
        "z": target_z,
        "removed": removed,
        "kept": kept,
    }


__all__ = ["clear_layer"]
