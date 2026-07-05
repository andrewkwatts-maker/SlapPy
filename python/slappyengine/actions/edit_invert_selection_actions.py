"""Selection-inversion action — select-all-except-current.

Backs the ``edit.invert_selection`` :class:`~slappyengine.tool_router.ToolAction`
row added by the GG1 STUB-triage sprint tick (round 10 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1 / EE1 / FF1).

Selects every scene entity that is *not* currently selected — the
"invert selection" flow every 2D/3D DCC ships (Photoshop's
``Shift+Ctrl+I``, Blender's ``Ctrl+I``, After Effects'
``Cmd+Shift+A`` after selecting). Locked / hidden entities are
respected by default so an "invert" doesn't quietly touch a locked
layer; the caller opts in to the raw sweep via
``ctx["include_locked"] = True`` / ``ctx["include_hidden"] = True``.

Scene walk resolution
---------------------

1. ``ctx["scene"]`` — explicit scene override.
2. ``shell._engine.scene`` — canonical shell hook.
3. ``shell.scene`` — direct attribute.
4. ``shell._scene`` — legacy attribute.

Entity iteration order:

* ``scene.entities`` (list / iterable) — the canonical roster.
* ``scene.get_entities()`` — accessor method.
* Fall through to ``scene.z_layers`` walk when the top-level roster is
  absent (matches the Ochema legacy layout).

Return contract
---------------

* ``{"status": "inverted", "selection": [...], "count": N,
   "previous_count": M}`` on success.
* ``{"status": "no_scene"}`` when no scene handle is reachable.
* ``{"status": "empty_scene"}`` when the scene has zero entities.
* ``{"status": "all_selected"}`` when every entity was already selected
  (so invert yields an empty set — distinguished from ``empty_scene``
  so callers can render "nothing to invert" instead of "empty scene").
"""
from __future__ import annotations

from typing import Any, Iterable

from ._ctx import ensure_ctx


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _get_scene(ctx: dict[str, Any]) -> Any:
    """Resolve the scene handle from *ctx*."""
    override = ctx.get("scene")
    if override is not None:
        return override
    shell = _get_shell(ctx)
    if shell is None:
        return None
    engine = getattr(shell, "_engine", None)
    if engine is not None:
        candidate = getattr(engine, "scene", None)
        if candidate is not None:
            return candidate
    for attr in ("scene", "_scene"):
        candidate = getattr(shell, attr, None)
        if candidate is not None:
            return candidate
    return None


def _resolve_selection(ctx: dict[str, Any]) -> list[Any]:
    """Return the current selection as a list."""
    override = ctx.get("selection")
    if override is not None:
        if isinstance(override, (list, tuple, set)):
            return [x for x in override if x is not None]
        return [override]
    shell = _get_shell(ctx)
    if shell is None:
        return []
    multi = getattr(shell, "_selected_entities", None)
    if isinstance(multi, (list, tuple, set)) and multi:
        return [x for x in multi if x is not None]
    single = getattr(shell, "_selected_entity", None)
    if single is not None:
        return [single]
    return []


def _walk_scene_entities(scene: Any) -> list[Any]:
    """Return every entity reachable from *scene* (best-effort order).

    Walk order:

    1. ``scene.entities`` — canonical iterable.
    2. ``scene.get_entities()`` — accessor.
    3. ``scene.z_layers`` — each layer's ``.entities``.
    """
    seen: list[Any] = []
    seen_ids: set[int] = set()

    def _push(entity: Any) -> None:
        if entity is None:
            return
        if id(entity) in seen_ids:
            return
        seen_ids.add(id(entity))
        seen.append(entity)

    def _extend(source: Iterable[Any]) -> None:
        for entity in source:
            _push(entity)

    entities = getattr(scene, "entities", None)
    if isinstance(entities, (list, tuple, set)):
        _extend(entities)
    elif callable(getattr(scene, "get_entities", None)):
        try:
            got = scene.get_entities()
        except Exception:  # noqa: BLE001
            got = None
        if isinstance(got, (list, tuple, set)):
            _extend(got)

    layers = getattr(scene, "z_layers", None)
    if isinstance(layers, (list, tuple)):
        for layer in layers:
            layer_entities = getattr(layer, "entities", None)
            if isinstance(layer_entities, (list, tuple, set)):
                _extend(layer_entities)
    return seen


def _is_locked(entity: Any) -> bool:
    return bool(
        getattr(entity, "locked", False)
        or getattr(entity, "_locked", False),
    )


def _is_hidden(entity: Any) -> bool:
    # Prefer explicit "visible" attribute; fall back to "hidden".
    visible = getattr(entity, "visible", None)
    if visible is not None:
        return not bool(visible)
    return bool(
        getattr(entity, "hidden", False)
        or getattr(entity, "_hidden", False),
    )


def invert_selection(ctx: dict[str, Any]) -> dict[str, Any]:
    """Select every scene entity that is not currently selected.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell exposing selection
          attributes. Retargeted on success.
        * ``scene`` (optional): scene override.
        * ``selection`` (optional): explicit current-selection override.
        * ``include_locked`` (optional bool): include locked entities.
          Defaults to ``False``.
        * ``include_hidden`` (optional bool): include hidden entities.
          Defaults to ``False``.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("invert_selection", ctx)
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}

    entities = _walk_scene_entities(scene)
    if not entities:
        return {"status": "empty_scene"}

    include_locked = bool(ctx.get("include_locked", False))
    include_hidden = bool(ctx.get("include_hidden", False))

    current = _resolve_selection(ctx)
    current_ids = {id(x) for x in current}

    inverted: list[Any] = []
    for entity in entities:
        if id(entity) in current_ids:
            continue
        if not include_locked and _is_locked(entity):
            continue
        if not include_hidden and _is_hidden(entity):
            continue
        inverted.append(entity)

    if not inverted:
        return {"status": "all_selected"}

    shell = _get_shell(ctx)
    if shell is not None:
        try:
            setattr(shell, "_selected_entities", list(inverted))
        except Exception:  # noqa: BLE001
            pass
        try:
            setattr(shell, "_selected_entity", inverted[0])
        except Exception:  # noqa: BLE001
            pass

    return {
        "status": "inverted",
        "selection": inverted,
        "count": len(inverted),
        "previous_count": len(current),
    }


__all__ = ["invert_selection"]
