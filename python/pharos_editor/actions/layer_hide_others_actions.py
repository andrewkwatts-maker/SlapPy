"""Layer hide-others action — hide every layer except the active one.

Backs the ``layer.hide_others``
:class:`~pharos_editor.tool_router.ToolAction` row added by the RR1
STUB-triage sprint tick (round 19).

Distinct from OO1's ``layer.solo`` (which snapshots current visibility so
a follow-up call restores). This is the *one-shot* verb Photoshop's
``Alt+click`` on the eye-icon implements: hide every other layer and
leave the active one visible with no snapshot / restore promise. The
active layer stays whatever visibility it already had (do not force-show
— a follow-up "show all" gesture already exists for that path).

Scene walk resolution
---------------------

* ``ctx["scene"]`` — explicit override (used by the tests).
* ``shell._engine.scene`` — canonical shell hook.
* ``shell._scene`` — legacy attribute.

Target layer resolution:

* ``ctx["layer"]`` — explicit target.
* ``shell._active_layer`` — the shell-owned pointer.
* ``scene.z_layers[-1]`` — top-most layer fallback (matches most DCC
  behaviour when "hide others" is invoked from a menu without a
  selection).

Return contract
---------------

* ``{"status": "hidden", "target": str, "hidden": [names, ...],
   "count": N}`` — success.
* ``{"status": "already_hidden", "target": str, "hidden": []}`` — no
  other layer was visible to hide.
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


def hide_others(ctx: dict[str, Any]) -> dict[str, Any]:
    """Hide every layer except the active one (no snapshot / no toggle).

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``layer`` (optional): explicit target layer.
        * ``shell`` (optional): editor shell — provides
          ``_active_layer`` fallback. Not used for state snapshot (this
          verb is one-shot, unlike ``layer.solo``).
        * ``scene`` (optional): scene handle — resolves ``z_layers``.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("hide_others", ctx)
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
    hidden: list[str] = []
    for layer in layers:
        name = _layer_name(layer)
        if layer is target or name == target_name:
            continue
        if not _get_visible(layer):
            # Already invisible — no state change.
            continue
        if _set_visible(layer, False):
            hidden.append(name)

    if not hidden:
        return {
            "status": "already_hidden",
            "target": target_name,
            "hidden": [],
        }
    return {
        "status": "hidden",
        "target": target_name,
        "hidden": hidden,
        "count": len(hidden),
    }


__all__ = ["hide_others"]
