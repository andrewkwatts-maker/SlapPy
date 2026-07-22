"""Layer reorder actions — swap the active layer with its neighbour.

Backs two :class:`~pharos_engine.tool_router.ToolAction` rows added by
the UU4 STUB-triage sprint tick (round 22):

* ``layer.move_up`` — swap the active layer with the one *immediately
  above* it in the Z-stack.
* ``layer.move_down`` — swap the active layer with the one *immediately
  below*.

Distinct from OO1's ``layer.merge_down`` (which flattens two layers
into one and deletes the source), RR1's ``layer.hide_others`` /
``layer.isolate`` (visibility toggles that don't reorder), and TT2's
``layer.rename`` (which touches names, not the z-stack order).

Every layered DCC ships this reorder verb pair — Photoshop
``Ctrl+]`` / ``Ctrl+[`` on the Layers panel, Krita's ``[`` / ``]``,
Affinity Photo's up-arrow / down-arrow buttons, Nova3D's Layer panel
right-click ``Move Up`` / ``Move Down``.

Ordering model
--------------

Layers are ordered by their ``z`` attribute (ascending). "Up" means
*higher* z (toward the viewer / on top); "down" means *lower* z (away
from the viewer / underneath). The swap semantics keep every entity's
world position intact — only the ``z`` scalar on the two swapped
layers changes.

Scene resolution matches ``layer_rename_actions``:

* ``ctx["scene"]`` — explicit.
* ``ctx["shell"]._engine.scene`` / ``._engine._scene`` — canonical.
* ``ctx["shell"]._scene`` — legacy.

Target layer resolution:

* ``ctx["layer"]`` — explicit target.
* ``ctx["layer_name"]`` — name lookup against ``scene.z_layers``.
* ``ctx["shell"]._active_layer`` — fallback pointer.

Return contract
---------------

* ``{"status": "moved", "target": str, "direction": "up" | "down",
   "swapped_with": str, "new_z": float, "old_z": float}`` — success.
* ``{"status": "at_top", "target": str}`` — already at highest z
  (``move_up`` called on the top layer).
* ``{"status": "at_bottom", "target": str}`` — already at lowest z
  (``move_down`` on the bottom).
* ``{"status": "no_scene"}`` — no scene reachable.
* ``{"status": "no_layer"}`` — no target layer resolvable.
* ``{"status": "no_layers"}`` — the scene has zero registered layers.
* ``{"status": "single_layer"}`` — only one layer in the stack;
  nothing to swap with.
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


def _swap_z(a: Any, b: Any) -> tuple[float, float] | None:
    """Swap the ``z`` attribute on *a* and *b*. Returns (new_a, new_b) or None."""
    za = _layer_z(a)
    zb = _layer_z(b)
    try:
        setattr(a, "z", zb)
        setattr(b, "z", za)
    except Exception:  # noqa: BLE001
        return None
    return (zb, za)


def _refresh_hook(shell: Any) -> None:
    if shell is None:
        return
    for hook_name in ("_on_layer_reordered", "_refresh_layer_panel"):
        hook = getattr(shell, hook_name, None)
        if callable(hook):
            try:
                hook()
            except Exception:  # noqa: BLE001
                pass
            break


def _move(ctx: dict[str, Any], direction: str) -> dict[str, Any]:
    """Shared implementation — ``direction`` is ``"up"`` or ``"down"``."""
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}
    layers = _list_layers(scene)
    if not layers:
        return {"status": "no_layers"}
    if len(layers) < 2:
        return {"status": "single_layer"}
    target = _resolve_target(ctx, layers)
    if target is None:
        return {"status": "no_layer"}

    ordered = sorted(layers, key=_layer_z)
    try:
        idx = ordered.index(target)
    except ValueError:
        return {"status": "no_layer"}

    if direction == "up":
        if idx == len(ordered) - 1:
            return {"status": "at_top", "target": _layer_name(target)}
        neighbour = ordered[idx + 1]
    else:
        if idx == 0:
            return {"status": "at_bottom", "target": _layer_name(target)}
        neighbour = ordered[idx - 1]

    old_z = _layer_z(target)
    swapped = _swap_z(target, neighbour)
    if swapped is None:
        return {"status": "error", "message": "z attribute write refused"}
    new_z, _neighbour_new_z = swapped

    _refresh_hook(_get_shell(ctx))

    return {
        "status": "moved",
        "target": _layer_name(target),
        "direction": direction,
        "swapped_with": _layer_name(neighbour),
        "new_z": new_z,
        "old_z": old_z,
    }


def move_layer_up(ctx: dict[str, Any]) -> dict[str, Any]:
    """Swap the active layer with the one immediately above it (higher z).

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("move_layer_up", ctx)
    return _move(ctx, "up")


def move_layer_down(ctx: dict[str, Any]) -> dict[str, Any]:
    """Swap the active layer with the one immediately below it (lower z).

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("move_layer_down", ctx)
    return _move(ctx, "down")


__all__ = ["move_layer_up", "move_layer_down"]
