"""Layer-duplication action — clone the active ZLayer entry.

Backs the ``edit.duplicate_layer`` :class:`~slappyengine.tool_router.ToolAction`
row added by the DD1 STUB-triage sprint tick (round 7 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1).

The action duplicates whichever ZLayer the editor considers "active":

1. ``ctx["layer"]`` — explicit source override (tests use this).
2. ``ctx["shell"]._active_layer`` — the shell-owned pointer.
3. ``ctx["scene"].z_layers[-1]`` — fall back to the top-most layer when
   nothing is explicitly active (mirrors what the Layer panel picks up
   on first open).

The clone is added to the scene via ``scene.add_z_layer(new_layer)`` and
the shell's ``_active_layer`` slot is repointed at the clone so the next
inspector refresh binds to the fresh copy (matches Nova3D's editor UX
where a duplicated item becomes the new selection).

Return contract
---------------

* ``{"status": "duplicated", "source_name": str, "new_name": str,
   "z": float}`` on success.
* ``{"status": "no_scene"}`` — no scene reachable via ctx.
* ``{"status": "no_layer"}`` — no active layer and the scene has none
   to fall back on.
"""
from __future__ import annotations

import copy
from typing import Any

from ._ctx import ensure_ctx


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _get_scene(ctx: dict[str, Any]) -> Any:
    """Resolve a scene handle from *ctx* — mirrors edit_by_name_actions."""
    scene = ctx.get("scene")
    if scene is not None:
        return scene
    shell = _get_shell(ctx)
    if shell is None:
        return None
    engine = getattr(shell, "_engine", None)
    if engine is not None:
        scene = (
            getattr(engine, "scene", None)
            or getattr(engine, "_scene", None)
        )
        if scene is not None:
            return scene
    return getattr(shell, "_scene", None)


def _get_active_layer(ctx: dict[str, Any], scene: Any) -> Any:
    """Return the active layer to duplicate.

    Search order: explicit ``ctx["layer"]`` → ``shell._active_layer`` →
    last entry of ``scene.z_layers``.
    """
    override = ctx.get("layer")
    if override is not None:
        return override
    shell = _get_shell(ctx)
    if shell is not None:
        active = getattr(shell, "_active_layer", None)
        if active is not None:
            return active
    layers_attr = getattr(scene, "z_layers", None)
    if layers_attr is None:
        return None
    try:
        layers_list = list(layers_attr)
    except TypeError:
        return None
    if not layers_list:
        return None
    return layers_list[-1]


def _next_copy_name(base_name: str, existing_names: set[str]) -> str:
    """Return ``"{base_name} copy"`` (or ``" copy N"``) unused in *existing_names*."""
    candidate = f"{base_name} copy"
    if candidate not in existing_names:
        return candidate
    n = 2
    while f"{base_name} copy {n}" in existing_names:
        n += 1
    return f"{base_name} copy {n}"


def _clone_layer(source: Any, new_name: str) -> Any:
    """Return a deep-copy of *source* with ``name=new_name``.

    Uses :func:`copy.deepcopy` so nested lists / dataclasses on custom
    layer objects come along cleanly. Falls back to a shallow ``copy`` +
    ``__dict__`` rebuild when the source is not deep-copyable (mock
    objects with un-copiable slots).
    """
    try:
        clone = copy.deepcopy(source)
    except Exception:  # noqa: BLE001
        try:
            clone = copy.copy(source)
        except Exception:  # noqa: BLE001
            return None
    try:
        setattr(clone, "name", new_name)
    except Exception:  # noqa: BLE001
        pass
    return clone


def duplicate_layer(ctx: dict[str, Any]) -> dict[str, Any]:
    """Duplicate the active ZLayer.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``layer`` (optional): explicit source layer to clone.
        * ``shell`` (optional): editor shell — provides ``_active_layer``
          fallback and receives the ``_active_layer`` retarget on
          success.
        * ``scene`` (optional): scene handle — receives the clone via
          ``add_z_layer``. Falls back to
          ``shell._engine.scene`` / ``shell._scene``.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("duplicate_layer", ctx)
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}
    source = _get_active_layer(ctx, scene)
    if source is None:
        return {"status": "no_layer"}

    source_name = str(getattr(source, "name", ""))
    existing_names: set[str] = set()
    layers_attr = getattr(scene, "z_layers", None)
    try:
        for l in list(layers_attr or []):
            existing_names.add(str(getattr(l, "name", "")))
    except TypeError:
        pass
    new_name = _next_copy_name(source_name or "layer", existing_names)

    clone = _clone_layer(source, new_name)
    if clone is None:
        return {"status": "error", "message": "clone failed"}

    adder = getattr(scene, "add_z_layer", None)
    if callable(adder):
        try:
            adder(clone)
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}
    else:
        # No scene API — best-effort append.
        raw = getattr(scene, "_z_layers", None)
        if isinstance(raw, list):
            raw.append(clone)

    # Repoint the shell's active-layer slot so the inspector rebinds.
    shell = _get_shell(ctx)
    if shell is not None:
        try:
            setattr(shell, "_active_layer", clone)
        except Exception:  # noqa: BLE001
            pass

    return {
        "status": "duplicated",
        "source_name": source_name,
        "new_name": new_name,
        "z": float(getattr(clone, "z", 0.0)),
    }


__all__ = ["duplicate_layer"]
