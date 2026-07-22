"""Layer-lock action — toggle the lock flag on a Z-layer.

Backs the ``layer.lock``
:class:`~pharos_editor.tool_router.ToolAction` row added by the YY4
STUB-triage sprint tick (round 25 after WW4).

Distinct from the sibling lock verbs:

* CC1's ``edit.lock_selection`` locks the currently *selected*
  entities (per-entity flag). This verb toggles the *layer-wide*
  lock — every entity on the layer is treated as locked at the
  scene walker level regardless of its own per-entity flag.
* CC1's ``edit.unlock_all`` walks every entity and clears the
  per-entity lock; this verb only touches one layer's flag.

Distinct from the other layer-toggle verbs:

* RR1's ``layer.hide_others`` / ``layer.isolate`` toggle
  *visibility* (drawn/not-drawn).
* NN1's ``layer.solo`` toggles the exclusive-visible flag.
* WW4's ``layer.clear`` wipes contents.
* VV4's ``layer.delete`` removes the layer entry.

Every layered DCC ships a per-layer lock: Photoshop's layer-panel
padlock icon, Krita's layer-panel padlock column, Affinity Photo's
Layer → Lock, Nova3D's Layer-panel lock column. The lock prevents
picking / mutation of every entity assigned to the layer while
preserving visibility.

Target resolution
-----------------

* ``ctx["layer"]`` — explicit override (tests use this).
* ``ctx["layer_name"]`` — string name lookup against
  ``scene.z_layers``.
* ``shell._active_layer`` — the shell-owned pointer.
* No fallback — when nothing resolves, returns ``no_layer``.

Storage contract
----------------

The lock flag is stored on the layer object itself as ``.locked``
(canonical, matches Photoshop / Krita / Nova3D naming). The verb
reads the current value, negates it, and writes it back. Explicit
``ctx["locked"]`` seed bypasses the read for tests / redo stacks.

Return contract
---------------

* ``{"status": "toggled", "target": str, "z": float,
   "locked": bool, "previous": bool}`` — success.
* ``{"status": "no_scene"}`` — no scene reachable.
* ``{"status": "no_layer"}`` — no target layer resolvable.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_LOCK_ATTR = "locked"
_DEFAULT_LOCKED = False


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


def _read_lock(layer: Any) -> bool:
    val = getattr(layer, _LOCK_ATTR, _DEFAULT_LOCKED)
    try:
        return bool(val)
    except Exception:  # noqa: BLE001
        return _DEFAULT_LOCKED


def _write_lock(layer: Any, value: bool) -> bool:
    try:
        setattr(layer, _LOCK_ATTR, value)
    except Exception:  # noqa: BLE001
        return False
    return True


def _refresh_hook(shell: Any) -> None:
    if shell is None:
        return
    hook = getattr(shell, "_on_layer_lock_toggled", None)
    if callable(hook):
        try:
            hook()
        except Exception:  # noqa: BLE001
            return
        return
    hook = getattr(shell, "_refresh_layer_panel", None)
    if callable(hook):
        try:
            hook()
        except Exception:  # noqa: BLE001
            pass


def toggle_layer_lock(ctx: dict[str, Any]) -> dict[str, Any]:
    """Toggle the lock flag on a Z-layer.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``layer`` (optional): explicit target.
        * ``layer_name`` (optional str): name lookup.
        * ``locked`` (optional bool): explicit seed value; the toggle
          negates *this* rather than reading the layer attribute.
        * ``scene`` (optional): explicit scene handle.
        * ``shell`` (optional): editor shell — provides
          ``_active_layer`` fallback.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("toggle_layer_lock", ctx)
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}
    layers = _list_layers(scene)
    target = _resolve_target(ctx, layers)
    if target is None:
        return {"status": "no_layer"}

    seed = ctx.get("locked")
    if isinstance(seed, bool):
        current = seed
    else:
        current = _read_lock(target)
    new_val = not current
    _write_lock(target, new_val)
    _refresh_hook(_get_shell(ctx))

    return {
        "status": "toggled",
        "target": _layer_name(target),
        "z": _layer_z(target),
        "locked": bool(new_val),
        "previous": bool(current),
    }


__all__ = ["toggle_layer_lock", "_LOCK_ATTR"]
