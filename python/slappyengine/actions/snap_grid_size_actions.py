"""Snap grid-size increment / decrement actions.

Backs the ``snap.increase_grid_size`` and ``snap.decrease_grid_size``
:class:`~slappyengine.tool_router.ToolAction` rows added by the OO1
STUB-triage sprint tick (round 16).

Every 2D/3D content-authoring tool that ships a snap-to-grid toggle
also ships a "coarser / finer grid" pair of gestures — Blender numpad
``+`` / ``-`` while snap is active, Unity's ``ProGrids`` gear, Krita's
grid-spacing spinner. These helpers walk a canonical geometric
progression (``1, 2, 4, 8, 16, 32, 64, 128, 256, 512``) so a single
tap doubles / halves the current grid size within safe bounds.

Current-grid resolution
-----------------------

* ``ctx["grid_size"]`` — explicit override (tests use this).
* ``shell._snap_grid_size`` — canonical shell attribute.
* ``shell._grid_size`` — legacy fallback.
* Otherwise starts from the default of ``8.0`` scene units.

Bounds
------

* Minimum grid size: ``0.5``.
* Maximum grid size: ``4096.0``.

A tap that would push the grid out of bounds returns
``{"status": "at_limit", ...}`` and leaves the shell attribute
unchanged.

Return contract (both actions)
------------------------------

* ``{"status": "stepped", "previous": float, "new": float,
   "direction": "up" | "down"}`` — success (grid changed).
* ``{"status": "at_limit", "previous": float, "new": float,
   "direction": ...}`` — already at min / max.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_MIN_GRID: float = 0.5
_MAX_GRID: float = 4096.0
_DEFAULT_GRID: float = 8.0

# Geometric ladder used to step. Each tap moves one rung.
_LADDER: tuple[float, ...] = (
    0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0, 512.0,
    1024.0, 2048.0, 4096.0,
)


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _current_grid(ctx: dict[str, Any]) -> float:
    override = ctx.get("grid_size")
    if override is not None:
        try:
            val = float(override)
        except (TypeError, ValueError):
            val = _DEFAULT_GRID
        return max(_MIN_GRID, min(_MAX_GRID, val))
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
            return max(_MIN_GRID, min(_MAX_GRID, val))
    return _DEFAULT_GRID


def _next_up(current: float) -> float:
    for rung in _LADDER:
        if rung > current + 1e-9:
            return rung
    return _MAX_GRID


def _next_down(current: float) -> float:
    for rung in reversed(_LADDER):
        if rung < current - 1e-9:
            return rung
    return _MIN_GRID


def _write_grid(shell: Any, size: float) -> None:
    if shell is None:
        return
    for attr in ("_snap_grid_size", "_grid_size", "grid_size"):
        if hasattr(shell, attr):
            try:
                setattr(shell, attr, size)
            except Exception:  # noqa: BLE001
                continue
            return
    # No known slot exists — write the canonical one so downstream reads
    # observe the update.
    try:
        setattr(shell, "_snap_grid_size", size)
    except Exception:  # noqa: BLE001
        pass


def increase_grid_size(ctx: dict[str, Any]) -> dict[str, Any]:
    """Step the snap grid size up one rung of the geometric ladder.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``grid_size`` (optional float): explicit current-grid
          override. Wins over the shell's stored value.
        * ``shell`` (optional): editor shell — receives the updated
          grid size.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("increase_grid_size", ctx)
    current = _current_grid(ctx)
    new = _next_up(current)
    shell = _get_shell(ctx)
    if abs(new - current) < 1e-9:
        return {
            "status": "at_limit",
            "previous": current,
            "new": current,
            "direction": "up",
        }
    _write_grid(shell, new)
    return {
        "status": "stepped",
        "previous": current,
        "new": new,
        "direction": "up",
    }


def decrease_grid_size(ctx: dict[str, Any]) -> dict[str, Any]:
    """Step the snap grid size down one rung of the geometric ladder.

    Parameters
    ----------
    ctx:
        Router context. Same keys as :func:`increase_grid_size`.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("decrease_grid_size", ctx)
    current = _current_grid(ctx)
    new = _next_down(current)
    shell = _get_shell(ctx)
    if abs(new - current) < 1e-9:
        return {
            "status": "at_limit",
            "previous": current,
            "new": current,
            "direction": "down",
        }
    _write_grid(shell, new)
    return {
        "status": "stepped",
        "previous": current,
        "new": new,
        "direction": "down",
    }


__all__ = ["increase_grid_size", "decrease_grid_size"]
