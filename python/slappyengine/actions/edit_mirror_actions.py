"""Mirror-selection actions — reflect entity positions across an axis.

Backs the ``edit.mirror_selection_x`` / ``edit.mirror_selection_y`` /
``edit.mirror_selection_z`` :class:`~slappyengine.tool_router.ToolAction`
rows added by the KK7 STUB-triage sprint tick (round 13 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1 / EE1 / FF1 / GG1 / II5 / JJ6).

Every 2D / 3D DCC ships a "mirror selection" trio — Blender's
``Ctrl+M X/Y/Z``, Maya's *Mesh → Mirror*, After Effects' *Layer →
Transform → Flip Horizontal / Flip Vertical*. The three helpers reflect
each selected entity's position across a chosen pivot on the requested
axis; when the entity carries a scale slot the corresponding axis is
negated so the *shape* also mirrors (a triangle pointing right now points
left). Pure position-only entities (bare dicts, legacy 2D sprites)
still round-trip cleanly — only the position moves.

Pivot resolution
----------------

Callers may pass ``ctx["pivot"]`` as:

* ``float`` / ``int`` — the axis coordinate to reflect through.
* 2- or 3-tuple / list — the whole pivot point (only the relevant axis
  is consumed).
* ``None`` (default) — the pivot defaults to the *centroid* of the
  current selection so a self-mirror produces a stable "flip in place"
  result (no drift).

Attribute conventions
---------------------

* :class:`slappyengine.entity.Entity` — 2D ``position`` tuple (``(x, y)``)
  + optional ``z_height`` scalar. Both are updated.
* Ochema-style dicts — ``entity["position"]`` list / tuple.
* Duck-typed 3D objects with ``position`` iterable of length ≥ 3.
* Scale is honoured whenever an ``entity.scale`` iterable is present;
  the corresponding component is negated so the mesh flips visually.
  A scalar ``scale`` attribute is left untouched (it doesn't encode axis
  handedness).

Return contract
---------------

Each helper returns:

* ``{"status": "mirrored", "axis": "x"|"y"|"z", "pivot": float,
   "entities": [...], "count": N}`` on success.
* ``{"status": "no_selection"}`` when nothing is selected.
* ``{"status": "no_positions"}`` when the resolved selection has no
  position-carrying entries (all mirror candidates rejected).
"""
from __future__ import annotations

from typing import Any, Sequence

from ._ctx import ensure_ctx


_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _resolve_selection(ctx: dict[str, Any]) -> list[Any]:
    """Return the current selection as a list.

    Search order mirrors :mod:`edit_actions`:

    1. ``ctx["selection"]`` — explicit override.
    2. ``shell._selected_entities`` — multi-select case.
    3. ``shell._selected_entity`` — single-select case.
    """
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


def _entity_position(entity: Any) -> tuple[float, float, float] | None:
    """Return ``(x, y, z)`` for *entity* (or ``None`` when unavailable).

    Coerces 2D positions (length 2) to 3D via a ``z_height`` fallback.
    """
    if entity is None:
        return None
    if isinstance(entity, dict):
        pos = entity.get("position")
        z_fallback = entity.get("z_height", 0.0)
    else:
        pos = getattr(entity, "position", None)
        z_fallback = getattr(entity, "z_height", 0.0)
    if pos is None:
        return None
    try:
        seq = tuple(pos)
    except TypeError:
        return None
    if len(seq) < 2:
        return None
    try:
        x = float(seq[0])
        y = float(seq[1])
    except (TypeError, ValueError):
        return None
    if len(seq) >= 3:
        try:
            z = float(seq[2])
        except (TypeError, ValueError):
            z = 0.0
    else:
        try:
            z = float(z_fallback) if z_fallback is not None else 0.0
        except (TypeError, ValueError):
            z = 0.0
    return (x, y, z)


def _write_position(
    entity: Any, new_pos: tuple[float, float, float],
) -> bool:
    """Write *new_pos* back onto *entity*. Returns True on success.

    Preserves the original tuple / list length — a bare 2D position
    stays 2D (with the mirrored ``z`` folded into ``z_height`` when
    present) so downstream renderers that unpack ``x, y = position``
    don't blow up.
    """
    if isinstance(entity, dict):
        prev = entity.get("position")
        if isinstance(prev, list):
            new_list = list(prev)
            new_list[0] = new_pos[0]
            new_list[1] = new_pos[1]
            if len(new_list) >= 3:
                new_list[2] = new_pos[2]
            entity["position"] = new_list
        else:
            length = 2 if prev is None else len(tuple(prev))
            if length >= 3:
                entity["position"] = (new_pos[0], new_pos[1], new_pos[2])
            else:
                entity["position"] = (new_pos[0], new_pos[1])
                if "z_height" in entity:
                    entity["z_height"] = new_pos[2]
        return True
    prev = getattr(entity, "position", None)
    if prev is None:
        return False
    try:
        if isinstance(prev, list):
            prev[0] = new_pos[0]
            prev[1] = new_pos[1]
            if len(prev) >= 3:
                prev[2] = new_pos[2]
            else:
                # 2D shape — fold z into z_height when the slot exists.
                if hasattr(entity, "z_height"):
                    setattr(entity, "z_height", new_pos[2])
            return True
        length = len(tuple(prev))
        if length >= 3:
            setattr(entity, "position", (new_pos[0], new_pos[1], new_pos[2]))
        else:
            setattr(entity, "position", (new_pos[0], new_pos[1]))
            if hasattr(entity, "z_height"):
                setattr(entity, "z_height", new_pos[2])
        return True
    except Exception:  # noqa: BLE001
        return False


def _flip_scale_axis(entity: Any, axis_idx: int) -> bool:
    """Negate the *axis_idx* component of ``entity.scale`` if iterable.

    Returns True when the write succeeded (test hook — lets the caller
    assert on scale-flip behaviour). Silently no-ops for scalar scales
    (they don't encode handedness).
    """
    if isinstance(entity, dict):
        scale = entity.get("scale")
    else:
        scale = getattr(entity, "scale", None)
    if scale is None:
        return False
    try:
        seq = tuple(scale)
    except TypeError:
        return False
    if len(seq) <= axis_idx:
        return False
    try:
        new_seq = list(seq)
        new_seq[axis_idx] = -float(new_seq[axis_idx])
    except (TypeError, ValueError):
        return False
    if isinstance(entity, dict):
        if isinstance(scale, list):
            scale[:] = new_seq
        else:
            entity["scale"] = tuple(new_seq) if isinstance(scale, tuple) else new_seq
        return True
    try:
        if isinstance(scale, list):
            scale[:] = new_seq
        else:
            setattr(
                entity,
                "scale",
                tuple(new_seq) if isinstance(scale, tuple) else new_seq,
            )
        return True
    except Exception:  # noqa: BLE001
        return False


def _resolve_pivot(
    ctx: dict[str, Any],
    axis_idx: int,
    points: list[tuple[float, float, float]],
) -> float:
    """Return the axis coordinate to reflect through.

    Priority:

    1. ``ctx["pivot"]`` scalar → used directly.
    2. ``ctx["pivot"]`` iterable → axis_idx-th element.
    3. Selection centroid on the mirror axis.
    4. ``0.0`` when no points supplied.
    """
    raw = ctx.get("pivot")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        try:
            if len(raw) > axis_idx:
                return float(raw[axis_idx])
        except (TypeError, ValueError):
            pass
    if not points:
        return 0.0
    return sum(p[axis_idx] for p in points) / len(points)


def _mirror_axis(ctx: dict[str, Any], axis: str) -> dict[str, Any]:
    """Reflect the current selection across a single axis.

    Shared implementation for :func:`mirror_selection_x` /
    :func:`mirror_selection_y` / :func:`mirror_selection_z`.
    """
    axis_idx = _AXIS_INDEX[axis]
    selection = _resolve_selection(ctx)
    if not selection:
        return {"status": "no_selection"}

    points: list[tuple[float, float, float]] = []
    kept: list[Any] = []
    for entity in selection:
        pos = _entity_position(entity)
        if pos is None:
            continue
        points.append(pos)
        kept.append(entity)

    if not kept:
        return {"status": "no_positions"}

    pivot = _resolve_pivot(ctx, axis_idx, points)
    flip_scale = ctx.get("flip_scale", True)

    mirrored: list[Any] = []
    for entity, pos in zip(kept, points):
        new_axis_value = 2.0 * pivot - pos[axis_idx]
        new_pos = list(pos)
        new_pos[axis_idx] = new_axis_value
        ok = _write_position(entity, (new_pos[0], new_pos[1], new_pos[2]))
        if not ok:
            continue
        if flip_scale:
            _flip_scale_axis(entity, axis_idx)
        mirrored.append(entity)

    return {
        "status": "mirrored",
        "axis": axis,
        "pivot": pivot,
        "entities": mirrored,
        "count": len(mirrored),
    }


def mirror_selection_x(ctx: dict[str, Any]) -> dict[str, Any]:
    """Reflect the current selection across the X axis.

    Blender ``Ctrl+M X``. Each entity's ``position.x`` becomes
    ``2 * pivot.x - position.x``; scale.x (if present) is negated so the
    mesh flips visually.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("mirror_selection_x", ctx)
    return _mirror_axis(ctx, "x")


def mirror_selection_y(ctx: dict[str, Any]) -> dict[str, Any]:
    """Reflect the current selection across the Y axis.

    Blender ``Ctrl+M Y``. Mirror of :func:`mirror_selection_x` — swaps
    ``position.y`` and negates ``scale.y``.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("mirror_selection_y", ctx)
    return _mirror_axis(ctx, "y")


def mirror_selection_z(ctx: dict[str, Any]) -> dict[str, Any]:
    """Reflect the current selection across the Z axis (3D scenes).

    Blender ``Ctrl+M Z``. For 2D shells the ``z_height`` slot is
    mirrored when present — otherwise the mirror still writes a synthetic
    ``z`` and the caller can pick it up via ``entity.position[2]``.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("mirror_selection_z", ctx)
    return _mirror_axis(ctx, "z")


__all__ = [
    "mirror_selection_x",
    "mirror_selection_y",
    "mirror_selection_z",
]
