"""Spawn-at-grid action — arm the next spawn at the nearest grid cell.

Backs the ``spawn.at_grid``
:class:`~pharos_editor.tool_router.ToolAction` row added by the WW4
STUB-triage sprint tick (round 24 after VV4).

Distinct from the sibling spawn-position verbs:

* QQ1's ``spawn.at_origin`` arms at world zero.
* TT2's ``spawn.at_view_center`` arms at the camera focal point.
* UU4's ``spawn.at_origin_offset`` arms at ``(0, 0, 0) + offset``.
* VV4's ``spawn.at_last_position`` arms at the previous drop.
* CC1's ``spawn.spawn_at_cursor`` fires immediately at the cursor.
* CC1's ``spawn.repeat_last`` re-fires the last spawn.

This verb *snaps* an incoming position (cursor / seed / stored last-
position) onto the grid ladder before arming. Complements OO1's
``snap.increase_grid_size`` / VV4's ``snap.set_grid_size`` — those
verbs configure the ladder step; this verb applies it to a spawn
target. Blender's "Snap Cursor to Grid" (``Shift+S → 1``) + Unity's
"V" vertex-snap toggle.

Position resolution
-------------------

Search order for the position to snap:

1. ``ctx["position"]`` — explicit override (tests use this).
2. ``ctx["cursor"]`` — the current cursor 3-vec.
3. ``shell._cursor_position`` — cached cursor slot.
4. ``shell._last_spawn_position`` — last-spawn cache.

When none of the above resolve, the origin ``(0, 0, 0)`` is used and
the return dict marks ``"source": "origin_fallback"``.

Grid-size resolution
--------------------

Search order for the snap grid size:

1. ``ctx["grid_size"]`` — explicit override.
2. ``shell._snap_grid_size`` / ``_grid_size`` / ``grid_size``.
3. Default ``1.0`` when nothing is configured.

Zero / negative sizes fall through to ``1.0`` (matches
``snap_set_grid_size_actions._MIN_GRID`` invariant that no snap
target may be non-positive).

Snap formula
------------

For each axis: ``snapped = round(coord / step) * step``. Round-half-
to-even matches Python's built-in :func:`round` (banker's rounding)
so ``1.5`` steps to ``2`` on an even step and ``0`` on the ``-1``
sibling — deterministic and free of drift under repeated presses.

Return contract
---------------

* ``{"status": "armed", "position": (x, y, z), "source": str,
   "grid_size": float, "snapped_from": (x, y, z)}`` — success.
* ``{"status": "no_shell"}`` — no shell reachable and no explicit
  position seed.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_DEFAULT_GRID: float = 1.0
_ORIGIN: tuple[float, float, float] = (0.0, 0.0, 0.0)


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _to_xyz(raw: Any) -> tuple[float, float, float] | None:
    if not isinstance(raw, (list, tuple)):
        return None
    if not raw:
        return None
    try:
        vals = [float(v) for v in raw]
    except (TypeError, ValueError):
        return None
    if len(vals) == 2:
        return (vals[0], vals[1], 0.0)
    if len(vals) >= 3:
        return (vals[0], vals[1], vals[2])
    return None


def _resolve_position(
    ctx: dict[str, Any],
) -> tuple[tuple[float, float, float], str]:
    override = ctx.get("position")
    got = _to_xyz(override)
    if got is not None:
        return (got, "override")

    cursor = ctx.get("cursor")
    got = _to_xyz(cursor)
    if got is not None:
        return (got, "cursor")

    shell = _get_shell(ctx)
    if shell is not None:
        got = _to_xyz(getattr(shell, "_cursor_position", None))
        if got is not None:
            return (got, "shell_cursor")
        got = _to_xyz(getattr(shell, "_last_spawn_position", None))
        if got is not None:
            return (got, "shell_last")
    return (_ORIGIN, "origin_fallback")


def _resolve_grid_size(ctx: dict[str, Any]) -> float:
    override = ctx.get("grid_size")
    if override is not None:
        try:
            val = float(override)
        except (TypeError, ValueError):
            val = _DEFAULT_GRID
        else:
            if val > 0.0:
                return val
    shell = _get_shell(ctx)
    if shell is not None:
        for attr in ("_snap_grid_size", "_grid_size", "grid_size"):
            raw = getattr(shell, attr, None)
            if raw is None:
                continue
            try:
                val = float(raw)
            except (TypeError, ValueError):
                continue
            if val > 0.0:
                return val
    return _DEFAULT_GRID


def _snap(pos: tuple[float, float, float], step: float) -> tuple[float, float, float]:
    return (
        round(pos[0] / step) * step,
        round(pos[1] / step) * step,
        round(pos[2] / step) * step,
    )


def _arm(shell: Any, xyz: tuple[float, float, float]) -> None:
    if shell is None:
        return
    try:
        setattr(shell, "_pending_spawn_position", list(xyz))
    except Exception:  # noqa: BLE001
        pass


def spawn_at_grid(ctx: dict[str, Any]) -> dict[str, Any]:
    """Snap a target position to the grid and arm the next spawn there.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell providing cursor /
          last-position slots + the ``_pending_spawn_position`` slot.
        * ``position`` (optional 2- or 3-vec): explicit override.
        * ``cursor`` (optional 2- or 3-vec): cursor override.
        * ``grid_size`` (optional positive float): snap step override.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("spawn_at_grid", ctx)
    shell = _get_shell(ctx)
    if shell is None and "position" not in ctx and "cursor" not in ctx:
        return {"status": "no_shell"}

    raw_pos, source = _resolve_position(ctx)
    step = _resolve_grid_size(ctx)
    snapped = _snap(raw_pos, step)
    _arm(shell, snapped)
    return {
        "status": "armed",
        "position": snapped,
        "source": source,
        "grid_size": step,
        "snapped_from": raw_pos,
    }


__all__ = ["spawn_at_grid"]
