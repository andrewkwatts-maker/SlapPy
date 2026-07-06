"""Layer-solo action — hide every layer except the active one.

Backs the ``layer.solo`` :class:`~slappyengine.tool_router.ToolAction`
row added by the OO1 STUB-triage sprint tick (round 16 after
NN2's round-15 ``view.frame_selected`` / ``view.reset_view`` /
``panel.dock_left`` / ``panel.dock_right`` / ``theme.hot_swap`` batch).

Every DCC that ships a layer stack (Photoshop, Krita, Nova3D's Layer
panel) exposes a "solo this layer" gesture — the shortcut hides every
layer except the target so the user can focus on one plane. Distinct
from ``edit.hide_selection`` (JJ6 — hides *entities* in the current
selection) and from a raw ``layer.visible = False`` toggle: solo
remembers the previous visibility state on ``shell._solo_snapshot`` so
a follow-up ``layer.unsolo`` (out-of-scope for this tick) could
restore. Passing the same active layer twice while in solo mode also
restores from the snapshot — mirrors Krita's toggle behaviour.

Scene walk resolution
---------------------

* ``ctx["scene"]`` — explicit override (used by the tests).
* ``shell._engine.scene`` — canonical shell hook.
* ``shell._scene`` — legacy attribute.

Target layer resolution:

* ``ctx["layer"]`` — explicit target.
* ``shell._active_layer`` — the shell-owned pointer.
* ``scene.z_layers[-1]`` — top-most layer fallback.

Return contract
---------------

* ``{"status": "soloed", "target": str, "hidden": [names, ...],
   "restored": False}`` — first solo pass; ``hidden`` echoes which
   layers were flipped to ``visible=False``.
* ``{"status": "restored", "target": str, "restored": True}`` — a
   second call with the same target rewinds from the snapshot.
* ``{"status": "no_scene"}`` — no scene handle reachable.
* ``{"status": "no_layer"}`` — no active layer resolvable.
* ``{"status": "no_layers"}`` — the scene has zero registered layers.
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


def _get_visible(layer: Any) -> bool:
    val = getattr(layer, "visible", None)
    if val is None:
        return True
    return bool(val)


def _set_visible(layer: Any, value: bool) -> bool:
    try:
        setattr(layer, "visible", bool(value))
        return True
    except Exception:  # noqa: BLE001
        return False


def solo_layer(ctx: dict[str, Any]) -> dict[str, Any]:
    """Solo the active layer — hide every other layer in the scene.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``layer`` (optional): explicit target layer.
        * ``shell`` (optional): editor shell — provides
          ``_active_layer`` fallback and receives the solo snapshot.
        * ``scene`` (optional): scene handle — resolves ``z_layers``.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("solo_layer", ctx)
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}
    target = _get_active_layer(ctx, scene)
    if target is None:
        return {"status": "no_layer"}
    layers = _list_layers(scene)
    if not layers:
        return {"status": "no_layers"}

    target_name = _layer_name(target)
    shell = _get_shell(ctx)

    # Toggle path — if a snapshot exists for the same target, restore.
    snapshot = None
    snapshot_target: str | None = None
    if shell is not None:
        snapshot = getattr(shell, "_solo_snapshot", None)
        snapshot_target = getattr(shell, "_solo_target", None)

    if (
        snapshot is not None
        and snapshot_target == target_name
        and isinstance(snapshot, dict)
    ):
        for layer in layers:
            name = _layer_name(layer)
            if name in snapshot:
                _set_visible(layer, snapshot[name])
        try:
            setattr(shell, "_solo_snapshot", None)
            setattr(shell, "_solo_target", None)
        except Exception:  # noqa: BLE001
            pass
        return {
            "status": "restored",
            "target": target_name,
            "restored": True,
        }

    # First-solo pass — snapshot current visibility, then hide non-targets.
    snap: dict[str, bool] = {}
    hidden: list[str] = []
    for layer in layers:
        name = _layer_name(layer)
        snap[name] = _get_visible(layer)
        if layer is target or name == target_name:
            _set_visible(layer, True)
            continue
        if _set_visible(layer, False):
            hidden.append(name)

    if shell is not None:
        try:
            setattr(shell, "_solo_snapshot", snap)
            setattr(shell, "_solo_target", target_name)
        except Exception:  # noqa: BLE001
            pass

    return {
        "status": "soloed",
        "target": target_name,
        "hidden": hidden,
        "restored": False,
    }


__all__ = ["solo_layer"]
