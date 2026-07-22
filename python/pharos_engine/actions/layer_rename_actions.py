"""Layer-rename action — rename a Z-layer without touching entities.

Backs the ``layer.rename``
:class:`~pharos_engine.tool_router.ToolAction` row added by the TT2
STUB-triage sprint tick (round 21).

Distinct from three neighbouring rename verbs:

* PP1's ``edit.rename`` — renames the selected *entity* (F2 gesture in
  Blender / Unity).
* FF1's ``content.rename_asset`` — renames an asset file / folder on
  disk in the content browser.
* This verb — renames a *layer* in the scene's Z-layer stack (Photoshop
  Layers panel double-click, Krita's "Rename Layer" menu item).

Every DCC that ships a layer stack ships this verb alongside solo /
merge / duplicate — Nova3D's Layer panel already exposes it as a right-
click item but the router row was previously wired to a no-op.

Layer resolution
----------------

1. ``ctx["layer"]`` — explicit target (tests use this).
2. ``ctx["layer_name"]`` — name-only lookup against
   ``scene.z_layers``.
3. ``shell._active_layer`` — the notebook's active-layer pointer.

Name validation mirrors PP1's ``edit.rename``: whitespace-only names
and names containing path separators are rejected so a "rename" flow
can't accidentally do a scene-graph re-parent.

Collision policy: when the incoming name already belongs to another
layer, the helper suffixes ``_2``, ``_3``... to disambiguate (matches
:mod:`content_duplicate_folder_actions`'s ``_uniquify`` step).

Return contract
---------------

* ``{"status": "renamed", "target": "<old>", "new": "<new>",
   "collided": bool}`` — success. ``collided`` is ``True`` when the
   final name had a numeric suffix appended.
* ``{"status": "no_scene"}`` — no scene handle reachable.
* ``{"status": "no_layer"}`` — no target layer resolvable.
* ``{"status": "no_layers"}`` — the scene has zero registered layers.
* ``{"status": "missing_name"}`` — ``ctx["new_name"]`` is absent /
  empty.
* ``{"status": "invalid_name", "name": str}`` — new name failed
  validation.
* ``{"status": "unchanged", "target": "<name>"}`` — the resolved name
  matched the current name after cleaning.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_INVALID_CHARS = ("/", "\\")


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


def _validate_name(name: str) -> tuple[bool, str]:
    cleaned = str(name).strip()
    if not cleaned:
        return (False, cleaned)
    for ch in _INVALID_CHARS:
        if ch in cleaned:
            return (False, cleaned)
    return (True, cleaned)


def _uniquify(base: str, taken: set[str]) -> tuple[str, bool]:
    """Return ``(unique_name, collided)`` — appends ``_2``, ``_3``…"""
    if base not in taken:
        return (base, False)
    counter = 2
    while True:
        candidate = f"{base}_{counter}"
        if candidate not in taken:
            return (candidate, True)
        counter += 1


def _set_layer_name(layer: Any, value: str) -> bool:
    try:
        setattr(layer, "name", value)
        return True
    except Exception:  # noqa: BLE001
        return False


def rename_layer(ctx: dict[str, Any]) -> dict[str, Any]:
    """Rename a Z-layer to ``ctx["new_name"]``.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``new_name`` (required, non-empty str): the target name.
        * ``layer`` (optional): explicit layer target.
        * ``layer_name`` (optional): name-based lookup against
          ``scene.z_layers``.
        * ``scene`` (optional): explicit scene handle.
        * ``shell`` (optional): editor shell (fallback for ``_scene`` +
          ``_active_layer`` + best-effort refresh hook).

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("rename_layer", ctx)
    raw_name = ctx.get("new_name")
    if raw_name is None or str(raw_name) == "":
        return {"status": "missing_name"}
    ok, cleaned = _validate_name(str(raw_name))
    if not ok:
        return {"status": "invalid_name", "name": cleaned}

    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}
    layers = _list_layers(scene)
    if not layers:
        return {"status": "no_layers"}
    target = _resolve_target(ctx, layers)
    if target is None:
        return {"status": "no_layer"}

    old = _layer_name(target)
    if old == cleaned:
        return {"status": "unchanged", "target": old}

    # Collision guard — every other layer's name is in the taken set.
    taken = {_layer_name(l) for l in layers if l is not target}
    final, collided = _uniquify(cleaned, taken)
    if not _set_layer_name(target, final):
        return {"status": "error", "message": "attribute write refused"}

    # Best-effort — nudge the shell's outliner / layer panel to redraw.
    shell = _get_shell(ctx)
    if shell is not None:
        for hook_name in ("_on_layer_renamed", "_refresh_layer_panel"):
            hook = getattr(shell, hook_name, None)
            if callable(hook):
                try:
                    hook()
                except Exception:  # noqa: BLE001
                    pass
                break

    return {
        "status": "renamed",
        "target": old,
        "new": final,
        "collided": collided,
    }


__all__ = ["rename_layer"]
