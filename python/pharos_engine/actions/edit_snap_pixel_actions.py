"""Snap-to-pixel-grid action — round positions to the nearest pixel.

Backs the ``edit.snap_to_pixel_grid`` :class:`~pharos_engine.tool_router.ToolAction`
row added by the EE1 STUB-triage sprint tick (round 8 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1).

Design intent
-------------

2D-first workflows (sprite editing, tile-map authoring, pixel-art)
benefit from an explicit "snap everything selected to integer pixels"
action rather than the freeform snap-to-grid tool toggle Z7 wired up.
This action:

1. Walks the current selection (falls back to *every entity in the
   scene* when ``ctx["all"]`` is truthy — matches the "Edit → Snap All
   to Pixel Grid" menu variant).
2. Rounds each entity's positional field (``position`` / ``origin`` /
   ``pos``) to the nearest integer.
3. Optionally scales by a caller-supplied ``pixel_size`` before rounding
   so a 32-px tilemap can snap to 32-unit boundaries by passing
   ``ctx["pixel_size"]=32``.

Positions are read + written with the same tolerance layer used by
:mod:`pharos_engine.actions.edit_group_actions` so the two actions agree
on what "position" means across attribute-holding entities, dict
entities, and 2-vec / 3-vec / 4-vec positional fields.

Return contract
---------------

* ``{"status": "snapped", "count": N, "moved": M, "deltas": [...]}`` —
  ``count`` is the number of entities inspected; ``moved`` is how many
  actually shifted (integer positions are left alone). ``deltas`` is a
  list of ``(entity, before, after)`` tuples so the caller can wire an
  undo hook.
* ``{"status": "no_selection"}`` — no selection and ``ctx["all"]`` was
  falsy.
* ``{"status": "no_scene"}`` — ``ctx["all"]`` was truthy but no scene
  is reachable.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_POS_KEYS = ("position", "origin", "pos")


# ---------------------------------------------------------------------------
# Selection + scene resolution (mirrors selection_actions / edit_group_actions)
# ---------------------------------------------------------------------------


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
        scene = (
            getattr(engine, "scene", None)
            or getattr(engine, "_scene", None)
        )
        if scene is not None:
            return scene
    return getattr(shell, "_scene", None)


def _list_scene_entities(scene: Any) -> list[Any]:
    entities_attr = getattr(scene, "entities", None)
    if entities_attr is None:
        raw = getattr(scene, "_entities", None)
        if isinstance(raw, dict):
            return list(raw.values())
        if isinstance(raw, (list, tuple)):
            return list(raw)
        return []
    if callable(entities_attr):
        try:
            got = entities_attr()
        except Exception:  # noqa: BLE001
            return []
        return list(got) if got is not None else []
    try:
        return list(entities_attr)
    except TypeError:
        return []


def _resolve_selection(ctx: dict[str, Any]) -> list[Any]:
    override = ctx.get("selection")
    if override is not None:
        if isinstance(override, (list, tuple)):
            return [x for x in override if x is not None]
        return [override]
    shell = _get_shell(ctx)
    if shell is None:
        return []
    multi = getattr(shell, "_selected_entities", None)
    if isinstance(multi, (list, tuple)) and multi:
        return [x for x in multi if x is not None]
    single = getattr(shell, "_selected_entity", None)
    if single is not None:
        return [single]
    return []


# ---------------------------------------------------------------------------
# Positional read/write — tolerant of dict + attribute entities
# ---------------------------------------------------------------------------


def _read_pos(entity: Any) -> tuple[str, list[float]] | None:
    """Return ``(key, coord_list)`` for the first positional field found."""
    for key in _POS_KEYS:
        if isinstance(entity, dict):
            raw = entity.get(key)
        else:
            raw = getattr(entity, key, None)
        if isinstance(raw, (list, tuple)) and raw:
            try:
                vals = [float(v) for v in raw]
            except (TypeError, ValueError):
                continue
            return key, vals
    return None


def _write_pos(entity: Any, key: str, vals: list[float]) -> None:
    """Write *vals* back to ``entity.<key>``."""
    if isinstance(entity, dict):
        entity[key] = list(vals)
        return
    try:
        setattr(entity, key, list(vals))
    except Exception:  # noqa: BLE001
        pass


def _pixel_size(ctx: dict[str, Any]) -> float:
    """Return the pixel size to snap to (default 1.0)."""
    raw = ctx.get("pixel_size", 1.0)
    if isinstance(raw, bool):
        return 1.0
    if isinstance(raw, (int, float)):
        val = float(raw)
        if val > 0.0:
            return val
    return 1.0


def _snap_axes(ctx: dict[str, Any]) -> tuple[bool, bool, bool]:
    """Return ``(snap_x, snap_y, snap_z)`` — default xy only.

    Pixel-art workflows are typically 2D; snapping the Z axis to integer
    layers would collapse depth values that intentionally use fractional
    ordering. Pass ``ctx["axes"] = "xyz"`` to include Z.
    """
    axes = ctx.get("axes", "xy")
    if isinstance(axes, str):
        return ("x" in axes, "y" in axes, "z" in axes)
    if isinstance(axes, (list, tuple)):
        vals = set(axes)
        return ("x" in vals, "y" in vals, "z" in vals)
    return (True, True, False)


def _snap_value(v: float, size: float) -> float:
    """Round *v* to the nearest multiple of *size*."""
    if size <= 0.0:
        return v
    return round(v / size) * size


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def snap_to_pixel_grid(ctx: dict[str, Any]) -> dict[str, Any]:
    """Round selected entity positions to the nearest pixel boundary.

    Consumed ctx keys:

    * ``shell`` (optional): editor shell providing the selection slots.
    * ``scene`` (optional): scene handle — used when ``ctx["all"]``
      is truthy.
    * ``selection`` (optional): explicit list of entities to snap.
    * ``all`` (optional bool, default ``False``): snap every entity in
      the scene instead of just the selection.
    * ``pixel_size`` (optional float, default ``1.0``): grid spacing.
    * ``axes`` (optional str/list, default ``"xy"``): which axes to
      snap. Pass ``"xyz"`` to snap Z as well.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("snap_to_pixel_grid", ctx)

    if ctx.get("all"):
        scene = _get_scene(ctx)
        if scene is None:
            return {"status": "no_scene"}
        entities = _list_scene_entities(scene)
    else:
        entities = _resolve_selection(ctx)
    if not entities:
        return {"status": "no_selection"}

    size = _pixel_size(ctx)
    snap_x, snap_y, snap_z = _snap_axes(ctx)

    deltas: list[tuple[Any, tuple[float, ...], tuple[float, ...]]] = []
    moved = 0
    for entity in entities:
        record = _read_pos(entity)
        if record is None:
            continue
        key, vals = record
        before = tuple(vals)
        after = list(vals)
        if snap_x and len(after) >= 1:
            after[0] = _snap_value(after[0], size)
        if snap_y and len(after) >= 2:
            after[1] = _snap_value(after[1], size)
        if snap_z and len(after) >= 3:
            after[2] = _snap_value(after[2], size)
        after_tup = tuple(after)
        if after_tup != before:
            _write_pos(entity, key, after)
            moved += 1
        deltas.append((entity, before, after_tup))

    return {
        "status": "snapped",
        "count": len(entities),
        "moved": moved,
        "deltas": deltas,
        "pixel_size": size,
    }


__all__ = ["snap_to_pixel_grid"]
