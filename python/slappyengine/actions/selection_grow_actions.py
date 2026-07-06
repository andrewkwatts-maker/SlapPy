"""Selection-grow action — expand the selection to nearby entities.

Backs the ``selection.grow`` :class:`~slappyengine.tool_router.ToolAction`
row added by the OO1 STUB-triage sprint tick (round 16).

Blender ``Ctrl+Numpad+`` (grow selection to adjacent geometry),
Photoshop ``Select → Grow`` — every content-authoring tool exposes a
"pull neighbours into the selection" gesture. This helper walks the
scene's entity list, computes each candidate's distance to the closest
already-selected entity, and adds every entity within
``ctx["radius"]`` (default ``64.0`` scene units) to the selection.

Distance metric
---------------

Positions are read from the same ``(position | origin | pos)`` fallback
chain :mod:`edit_snap_pixel_actions` uses. Distances are Euclidean
across whichever axes both positions share (2D vs. 3D graceful).

Scene walk resolution
---------------------

* ``ctx["scene"]`` — explicit override (tests use this).
* ``shell._engine.scene`` — canonical shell hook.
* ``shell._scene`` — legacy attribute.

Return contract
---------------

* ``{"status": "grown", "selection": [...], "added": N,
   "previous_count": M, "radius": float}`` on success.
* ``{"status": "no_scene"}`` — no scene handle reachable.
* ``{"status": "no_selection"}`` — no seed selection to grow.
* ``{"status": "unchanged", "selection": [...]}`` — nothing new was
   within the radius.
"""
from __future__ import annotations

import math
from typing import Any

from ._ctx import ensure_ctx


_POS_KEYS = ("position", "origin", "pos")
_DEFAULT_RADIUS: float = 64.0
_MAX_RADIUS: float = 1e9


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


def _list_scene_entities(scene: Any) -> list[Any]:
    entities_attr = getattr(scene, "entities", None)
    if entities_attr is not None:
        try:
            return [e for e in list(entities_attr) if e is not None]
        except TypeError:
            pass
    getter = getattr(scene, "get_entities", None)
    if callable(getter):
        try:
            return [e for e in list(getter()) if e is not None]
        except Exception:  # noqa: BLE001
            return []
    return []


def _resolve_selection(ctx: dict[str, Any]) -> list[Any]:
    override = ctx.get("selection")
    if override is not None:
        if isinstance(override, (list, tuple, set)):
            return [x for x in override if x is not None]
        return [override]
    shell = _get_shell(ctx)
    if shell is None:
        return []
    for attr in ("_selected_entities", "selection", "_selection"):
        val = getattr(shell, attr, None)
        if val is None:
            continue
        if isinstance(val, (list, tuple, set)):
            return [x for x in val if x is not None]
    single = getattr(shell, "_selected_entity", None)
    if single is not None:
        return [single]
    return []


def _entity_position(entity: Any) -> tuple[float, ...] | None:
    if isinstance(entity, dict):
        for key in _POS_KEYS:
            val = entity.get(key)
            if val is None:
                continue
            try:
                return tuple(float(x) for x in val)
            except (TypeError, ValueError):
                continue
        return None
    for key in _POS_KEYS:
        val = getattr(entity, key, None)
        if val is None:
            continue
        try:
            return tuple(float(x) for x in val)
        except (TypeError, ValueError):
            continue
    return None


def _distance(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return math.inf
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(n)))


def _resolve_radius(ctx: dict[str, Any]) -> float:
    raw = ctx.get("radius")
    if raw is None:
        return _DEFAULT_RADIUS
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_RADIUS
    if val <= 0.0:
        return _DEFAULT_RADIUS
    return min(_MAX_RADIUS, val)


def _write_selection(shell: Any, selection: list[Any]) -> None:
    if shell is None:
        return
    for attr in ("_selected_entities", "selection", "_selection"):
        if hasattr(shell, attr):
            try:
                setattr(shell, attr, list(selection))
                break
            except Exception:  # noqa: BLE001
                continue
    else:
        # No known slot exists — write to the canonical one anyway so
        # downstream reads see the update.
        try:
            setattr(shell, "_selected_entities", list(selection))
        except Exception:  # noqa: BLE001
            pass


def grow_selection(ctx: dict[str, Any]) -> dict[str, Any]:
    """Add every entity within ``ctx["radius"]`` of the current selection.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``selection`` (optional): explicit seed selection.
        * ``shell`` (optional): editor shell — provides selection
          fallback + receives the updated selection.
        * ``scene`` (optional): scene handle.
        * ``radius`` (optional float, default ``64.0``): expansion
          radius in scene units.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("grow_selection", ctx)
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}
    seed = _resolve_selection(ctx)
    if not seed:
        return {"status": "no_selection"}

    radius = _resolve_radius(ctx)
    radius_sq = radius * radius

    seed_positions: list[tuple[float, ...]] = []
    for entity in seed:
        pos = _entity_position(entity)
        if pos is not None:
            seed_positions.append(pos)

    entities = _list_scene_entities(scene)
    selected_ids = {id(e) for e in seed}
    result = list(seed)
    added = 0
    for candidate in entities:
        if id(candidate) in selected_ids:
            continue
        cpos = _entity_position(candidate)
        if cpos is None:
            continue
        # Distance check against the nearest seed position.
        min_dist_sq = math.inf
        for spos in seed_positions:
            n = min(len(spos), len(cpos))
            if n == 0:
                continue
            d_sq = sum((spos[i] - cpos[i]) ** 2 for i in range(n))
            if d_sq < min_dist_sq:
                min_dist_sq = d_sq
        if min_dist_sq <= radius_sq:
            result.append(candidate)
            selected_ids.add(id(candidate))
            added += 1

    shell = _get_shell(ctx)
    _write_selection(shell, result)

    if added == 0:
        return {
            "status": "unchanged",
            "selection": result,
            "previous_count": len(seed),
            "radius": radius,
        }

    return {
        "status": "grown",
        "selection": result,
        "added": added,
        "previous_count": len(seed),
        "radius": radius,
    }


__all__ = ["grow_selection"]
