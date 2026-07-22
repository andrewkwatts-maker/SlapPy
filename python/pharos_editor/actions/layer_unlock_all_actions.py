"""Layer unlock-all action — clear the lock flag on every Z-layer.

Backs the ``layer.unlock_all``
:class:`~pharos_editor.tool_router.ToolAction` row added by the ZZ4
STUB-triage sprint tick (round 26 after YY4).

Distinct from the sibling lock verbs:

* CC1's ``edit.lock_selection`` locks the currently *selected*
  entities (per-entity flag). Its mirror CC1's ``edit.unlock_all``
  walks every entity and clears the per-entity lock.
* YY4's ``layer.lock`` toggles the *layer-wide* lock on *one* target
  layer. This verb clears the *layer-wide* lock on **every** layer
  in one shot — the sweep-counterpart of ``layer.lock``.

The two clear-lock verbs address disjoint scopes: CC1's
``edit.unlock_all`` scrubs the per-entity flag; this verb scrubs the
per-layer flag. Callers that want a full unlock invoke both.

Distinct from the other layer verbs:

* RR1's ``layer.hide_others`` / ``layer.isolate`` toggle *visibility*
  (drawn/not-drawn).
* NN1's ``layer.solo`` toggles the exclusive-visible flag.
* WW4's ``layer.clear`` wipes contents.
* VV4's ``layer.delete`` removes the layer entry.

Every layered DCC ships a global unlock: Photoshop's Layer → Unlock
All Layers, Krita's Layer → Unlock All Layers, Affinity Photo's
Layer → Unlock All, Nova3D's Layer-panel gear → Unlock All.

Storage contract
----------------

The lock flag lives on each layer object as ``.locked`` (matches
``layer.lock``). This verb writes ``.locked = False`` on every layer
regardless of its current value. Explicit ``ctx["dry_run"]=True``
skips the write (used by preview flows).

Return contract
---------------

* ``{"status": "unlocked", "count": N, "targets": [...]}`` —
  success. ``count`` = number of layers whose ``locked`` flag was
  flipped from True to False. ``targets`` = list of layer names that
  were unlocked (was-locked, now-unlocked).
* ``{"status": "no_scene"}`` — no scene reachable.
* ``{"status": "no_layers"}`` — scene reachable but has no z_layers.
* ``{"status": "already_unlocked", "count": 0, "targets": []}`` —
  every layer was already unlocked (idempotent no-op).
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_LOCK_ATTR = "locked"


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


def _read_lock(layer: Any) -> bool:
    val = getattr(layer, _LOCK_ATTR, False)
    try:
        return bool(val)
    except Exception:  # noqa: BLE001
        return False


def _clear_lock(layer: Any) -> bool:
    try:
        setattr(layer, _LOCK_ATTR, False)
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


def unlock_all_layers(ctx: dict[str, Any]) -> dict[str, Any]:
    """Clear the lock flag on every Z-layer.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``scene`` (optional): explicit scene handle.
        * ``shell`` (optional): editor shell — falls back to
          ``_engine.scene`` / ``_scene``.
        * ``dry_run`` (optional bool): when ``True`` the write is
          skipped; the count / targets reported reflect what *would*
          have been unlocked.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("unlock_all_layers", ctx)
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}
    layers = _list_layers(scene)
    if not layers:
        return {"status": "no_layers"}

    dry = bool(ctx.get("dry_run", False))
    unlocked_names: list[str] = []
    for layer in layers:
        if _read_lock(layer):
            if not dry:
                _clear_lock(layer)
            unlocked_names.append(_layer_name(layer))

    if not unlocked_names:
        return {
            "status": "already_unlocked",
            "count": 0,
            "targets": [],
        }

    if not dry:
        _refresh_hook(_get_shell(ctx))

    return {
        "status": "unlocked",
        "count": len(unlocked_names),
        "targets": unlocked_names,
    }


__all__ = ["unlock_all_layers", "_LOCK_ATTR"]
