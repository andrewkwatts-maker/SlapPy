"""Layer-merge-down action — flatten the active layer into the one below.

Backs the ``layer.merge_down`` :class:`~pharos_editor.tool_router.ToolAction`
row added by the OO1 STUB-triage sprint tick (round 16).

Photoshop ``Ctrl+E`` merge-down, Krita ``Ctrl+E``, Blender node
group flatten — every layered authoring tool ships this gesture. The
active layer's entities get re-parented onto the layer *directly beneath*
it (by ``z`` order) and the now-empty source layer is removed from the
scene's ``z_layers`` roster. When the active layer is already the
bottom-most, the operation returns ``no_layer_below`` so the caller can
show "nothing to merge into" toast instead of silently dropping data.

Scene walk resolution
---------------------

* ``ctx["scene"]`` — explicit override.
* ``shell._engine.scene`` — canonical shell hook.
* ``shell._scene`` — legacy attribute.

Target layer resolution:

* ``ctx["layer"]`` — explicit target.
* ``shell._active_layer`` — the shell-owned pointer.
* ``scene.z_layers[-1]`` — top-most layer fallback (matches most
  DCC behaviour where "merge down" from menu without a selection
  operates on the topmost layer).

Entity roster (per-layer) is discovered via ``layer.entities`` — either
a list or an accessor method. When neither is available the helper
silently reassigns entities in the scene whose ``layer`` attribute
points at the target.

Return contract
---------------

* ``{"status": "merged", "source_name": str, "dest_name": str,
   "moved": int}`` — success.
* ``{"status": "no_scene"}`` — no scene handle reachable.
* ``{"status": "no_layer"}`` — no active layer resolvable.
* ``{"status": "no_layer_below", "name": str}`` — active layer is
   already at the bottom of the z-stack.
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


def _get_active_layer(ctx: dict[str, Any], scene: Any) -> Any:
    override = ctx.get("layer")
    if override is not None:
        return override
    shell = _get_shell(ctx)
    if shell is not None:
        active = getattr(shell, "_active_layer", None)
        if active is not None:
            return active
    layers = _list_layers(scene)
    if not layers:
        return None
    return layers[-1]


def _layer_name(layer: Any) -> str:
    return str(getattr(layer, "name", "") or "")


def _list_layer_entities(layer: Any) -> list[Any]:
    entities = getattr(layer, "entities", None)
    if entities is None:
        return []
    if callable(entities):
        try:
            return list(entities())
        except Exception:  # noqa: BLE001
            return []
    try:
        return list(entities)
    except TypeError:
        return []


def _rewrite_entity_layer(entity: Any, dest: Any) -> bool:
    try:
        setattr(entity, "layer", dest)
    except Exception:  # noqa: BLE001
        return False
    dest_z = getattr(dest, "z", None)
    if dest_z is not None:
        try:
            setattr(entity, "z", float(dest_z))
        except Exception:  # noqa: BLE001
            pass
    return True


def _append_to_layer(layer: Any, entity: Any) -> bool:
    entities = getattr(layer, "entities", None)
    if isinstance(entities, list):
        entities.append(entity)
        return True
    adder = getattr(layer, "add_entity", None)
    if callable(adder):
        try:
            adder(entity)
            return True
        except Exception:  # noqa: BLE001
            return False
    raw = getattr(layer, "_entities", None)
    if isinstance(raw, list):
        raw.append(entity)
        return True
    return False


def _remove_layer(scene: Any, layer: Any) -> None:
    remover = getattr(scene, "remove_z_layer", None)
    if callable(remover):
        try:
            remover(layer)
            return
        except Exception:  # noqa: BLE001
            pass
    layers_attr = getattr(scene, "z_layers", None)
    if isinstance(layers_attr, list):
        try:
            layers_attr.remove(layer)
        except ValueError:
            pass
        return
    raw = getattr(scene, "_z_layers", None)
    if isinstance(raw, list):
        try:
            raw.remove(layer)
        except ValueError:
            pass


def merge_down(ctx: dict[str, Any]) -> dict[str, Any]:
    """Merge the active layer's entities into the layer immediately below it.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``layer`` (optional): explicit source layer.
        * ``shell`` (optional): editor shell — provides fallback
          ``_active_layer`` and receives the ``_active_layer`` retarget
          onto the merged (dest) layer.
        * ``scene`` (optional): scene handle.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("merge_down", ctx)
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}
    source = _get_active_layer(ctx, scene)
    if source is None:
        return {"status": "no_layer"}
    layers = _list_layers(scene)
    if not layers:
        return {"status": "no_layer"}

    # Sort layers by z (ascending) so we can find the neighbour below.
    def _z(l: Any) -> float:
        try:
            return float(getattr(l, "z", 0.0))
        except Exception:  # noqa: BLE001
            return 0.0

    ordered = sorted(layers, key=_z)
    try:
        idx = ordered.index(source)
    except ValueError:
        # Source not registered on scene — treat as no layer below.
        return {
            "status": "no_layer_below",
            "name": _layer_name(source),
        }
    if idx == 0:
        return {
            "status": "no_layer_below",
            "name": _layer_name(source),
        }
    dest = ordered[idx - 1]

    entities = _list_layer_entities(source)
    moved = 0
    for entity in entities:
        if _rewrite_entity_layer(entity, dest) and _append_to_layer(dest, entity):
            moved += 1

    # Clear source layer entities before removing.
    src_entities = getattr(source, "entities", None)
    if isinstance(src_entities, list):
        src_entities.clear()
    else:
        raw = getattr(source, "_entities", None)
        if isinstance(raw, list):
            raw.clear()

    _remove_layer(scene, source)

    # Repoint active layer to the merged destination.
    shell = _get_shell(ctx)
    if shell is not None:
        try:
            setattr(shell, "_active_layer", dest)
        except Exception:  # noqa: BLE001
            pass

    return {
        "status": "merged",
        "source_name": _layer_name(source),
        "dest_name": _layer_name(dest),
        "moved": moved,
    }


__all__ = ["merge_down"]
