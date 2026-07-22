"""Selection-shrink action — the inverse of :func:`selection.grow`.

Backs the ``selection.shrink`` :class:`~pharos_editor.tool_router.ToolAction`
row added by the PP1 STUB-triage sprint tick (round 17 after
OO1's round-16 layer / selection / snap batch).

Blender ``Ctrl+Numpad-`` (shrink selection to interior geometry),
Photoshop ``Select → Contract`` — every content-authoring tool ships a
"peel the outermost pixels/entities off the selection" gesture. This
helper walks the currently-selected entities and drops every entity
that has at least one *non-selected* neighbour within
``ctx["radius"]`` (default ``64.0`` scene units) — the boundary layer
of the selection.

Distance metric
---------------

Positions are read from the same ``(position | origin | pos)`` fallback
chain the r16 :mod:`selection_grow_actions` uses. Distances are
Euclidean across whichever axes both positions share (2D vs. 3D
graceful).

Scene walk resolution
---------------------

* ``ctx["scene"]`` — explicit override (tests use this).
* ``shell._engine.scene`` — canonical shell hook.
* ``shell._scene`` — legacy attribute.

Return contract
---------------

* ``{"status": "shrunk", "selection": [...], "removed": N,
   "previous_count": M, "radius": float}`` on success.
* ``{"status": "no_scene"}`` — no scene handle reachable.
* ``{"status": "no_selection"}`` — no seed selection to shrink.
* ``{"status": "unchanged", "selection": [...]}`` — no entity was on
   the selection's boundary (every selected entity's neighbourhood is
   already fully inside the selection).
* ``{"status": "emptied", "previous_count": M, "radius": float}`` —
   every selected entity was on the boundary; the selection is now
   empty. Distinguished from ``unchanged`` so the caller can render
   "selection cleared" toast.
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
        try:
            setattr(shell, "_selected_entities", list(selection))
        except Exception:  # noqa: BLE001
            pass


def shrink_selection(ctx: dict[str, Any]) -> dict[str, Any]:
    """Drop every boundary entity from the current selection.

    An entity is considered to be on the *boundary* of the selection
    when it has at least one non-selected neighbour within
    ``ctx["radius"]`` (default ``64.0`` scene units). Interior entities
    — whose neighbourhood is fully covered by other selected entities —
    survive the shrink pass.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``selection`` (optional): explicit seed selection.
        * ``shell`` (optional): editor shell — provides selection
          fallback + receives the updated selection.
        * ``scene`` (optional): scene handle.
        * ``radius`` (optional float, default ``64.0``): boundary
          detection radius in scene units.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("shrink_selection", ctx)
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}
    seed = _resolve_selection(ctx)
    if not seed:
        return {"status": "no_selection"}

    radius = _resolve_radius(ctx)
    radius_sq = radius * radius

    entities = _list_scene_entities(scene)
    selected_ids = {id(e) for e in seed}

    # Precompute positions for all scene entities so we don't re-read
    # the (position | origin | pos) chain on every pairwise check.
    positions: dict[int, tuple[float, ...]] = {}
    for e in entities + seed:
        pos = _entity_position(e)
        if pos is not None:
            positions[id(e)] = pos

    # An entity survives shrink when *every* other entity within radius
    # is also selected. If any neighbour is *unselected*, it's on the
    # boundary and gets dropped.
    survivors: list[Any] = []
    removed = 0
    for candidate in seed:
        cpos = positions.get(id(candidate))
        if cpos is None:
            # No position — treat as boundary (can't prove it's interior).
            removed += 1
            continue
        on_boundary = False
        for other in entities:
            if id(other) in selected_ids:
                continue
            opos = positions.get(id(other))
            if opos is None:
                continue
            n = min(len(opos), len(cpos))
            if n == 0:
                continue
            d_sq = sum((opos[i] - cpos[i]) ** 2 for i in range(n))
            if d_sq <= radius_sq:
                on_boundary = True
                break
        if on_boundary:
            removed += 1
        else:
            survivors.append(candidate)

    shell = _get_shell(ctx)
    _write_selection(shell, survivors)

    if removed == 0:
        return {
            "status": "unchanged",
            "selection": survivors,
            "previous_count": len(seed),
            "radius": radius,
        }
    if not survivors:
        return {
            "status": "emptied",
            "previous_count": len(seed),
            "radius": radius,
        }
    return {
        "status": "shrunk",
        "selection": survivors,
        "removed": removed,
        "previous_count": len(seed),
        "radius": radius,
    }


__all__ = ["shrink_selection"]
