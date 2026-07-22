"""Snap cycle-grid-size action — step through canonical grid rungs.

Backs the ``snap.cycle_grid_size``
:class:`~pharos_engine.tool_router.ToolAction` row added by the ZZ4
STUB-triage sprint tick (round 26 after YY4).

Complements the sibling snap-grid-size verbs. Each one owns a
different gesture:

* OO1's ``snap.increase_grid_size`` — walks the ladder *up* one rung
  and stops at the ceiling.
* OO1's ``snap.decrease_grid_size`` — walks *down* one rung and stops
  at the floor.
* VV4's ``snap.set_grid_size`` — writes an absolute value (any float).
* YY4's ``snap.reset_defaults`` — resets to the canonical default.

This verb is the **cyclical** step — walks up through the canonical
rungs and wraps around at the top back to the smallest rung. Matches
Blender's numeric-1 through 5 grid-preset cycle, Unity's ProGrids
"Cycle Grid Snap" shortcut, and Nova3D's grid-size cycle button.

Distinct from OO1's ``snap.increase_grid_size`` — the OO1 verb stops
at the ladder ceiling (``at_limit`` return); this verb wraps.

The default direction is ``"up"``. ``ctx["direction"]="down"`` walks
the ladder downward and wraps at the floor.

Ladder
------

Uses the same canonical geometric progression as the OO1 rungs
(``0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0``). We stop
the cyclical ladder one rung short of the ``4096.0`` ceiling that
``snap_grid_size_actions._LADDER`` reaches — the top of a *cyclical*
control is normally the "usable maximum" rather than the "clamp
maximum" (Blender / Unity cycles top out at 256.0).

Current-grid resolution
-----------------------

Mirrors OO1's resolver — ``ctx["grid_size"]`` → shell attribute chain
(``_snap_grid_size`` / ``_grid_size`` / ``grid_size``) → default rung
1.0.

Snapping to the ladder
----------------------

If the current value is *between* rungs the walker rounds to the
**nearest** rung first, then advances. This keeps the walker
predictable after ``snap.set_grid_size`` writes an arbitrary float
(e.g. 3.14) — the first cycle press lands on ``4.0`` (nearest rung).

Return contract
---------------

* ``{"status": "cycled", "previous": float, "new": float,
   "direction": "up" | "down", "wrapped": bool}`` — success.
   ``wrapped`` is ``True`` when the cycle wrapped around the ladder
   (top→bottom for "up", bottom→top for "down").
* ``{"status": "no_shell"}`` — no shell reachable and no
  ``grid_size`` override to cycle against.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_MIN_GRID: float = 0.5
_MAX_GRID: float = 4096.0
_DEFAULT_GRID: float = 1.0

# Cyclical ladder — subset of the OO1 clamp ladder. Ends at 256 so
# that "top" of the cycle matches Blender / Unity muscle memory.
_CYCLE_LADDER: tuple[float, ...] = (
    0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0,
)
_TOL: float = 1e-6

_GRID_ATTRS: tuple[str, ...] = ("_snap_grid_size", "_grid_size", "grid_size")


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _current_grid(ctx: dict[str, Any]) -> float | None:
    """Return the current grid size or ``None`` when nothing is reachable."""
    override = ctx.get("grid_size")
    if override is not None:
        try:
            val = float(override)
        except (TypeError, ValueError):
            return _DEFAULT_GRID
        return max(_MIN_GRID, min(_MAX_GRID, val))
    shell = _get_shell(ctx)
    if shell is None:
        return None
    for attr in _GRID_ATTRS:
        raw = getattr(shell, attr, None)
        if raw is None:
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        return max(_MIN_GRID, min(_MAX_GRID, val))
    return _DEFAULT_GRID


def _snap_to_ladder(current: float) -> tuple[float, int]:
    """Return the ``(rung, index)`` of the *nearest* rung to *current*."""
    best_idx = 0
    best_delta = abs(_CYCLE_LADDER[0] - current)
    for i, rung in enumerate(_CYCLE_LADDER):
        delta = abs(rung - current)
        if delta < best_delta:
            best_delta = delta
            best_idx = i
    return (_CYCLE_LADDER[best_idx], best_idx)


def _step(index: int, direction: str) -> tuple[int, bool]:
    """Return ``(next_index, wrapped)`` for one step in *direction*."""
    n = len(_CYCLE_LADDER)
    if direction == "down":
        nxt = index - 1
        if nxt < 0:
            return (n - 1, True)
        return (nxt, False)
    nxt = index + 1
    if nxt >= n:
        return (0, True)
    return (nxt, False)


def _write_grid(shell: Any, size: float) -> None:
    if shell is None:
        return
    for attr in _GRID_ATTRS:
        if hasattr(shell, attr):
            try:
                setattr(shell, attr, size)
            except Exception:  # noqa: BLE001
                continue
            return
    try:
        setattr(shell, "_snap_grid_size", size)
    except Exception:  # noqa: BLE001
        pass


def cycle_grid_size(ctx: dict[str, Any]) -> dict[str, Any]:
    """Step the snap grid size to the next canonical rung, wrapping at the top.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``grid_size`` (optional float): explicit current-grid
          override.
        * ``shell`` (optional): editor shell — receives the updated
          grid size.
        * ``direction`` (optional str): ``"up"`` (default) walks the
          ladder up and wraps at the top; ``"down"`` walks down and
          wraps at the bottom.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("cycle_grid_size", ctx)
    current = _current_grid(ctx)
    if current is None:
        return {"status": "no_shell"}

    direction = ctx.get("direction", "up")
    if direction not in ("up", "down"):
        direction = "up"

    _snapped, idx = _snap_to_ladder(current)
    nxt_idx, wrapped = _step(idx, direction)
    new = _CYCLE_LADDER[nxt_idx]
    _write_grid(_get_shell(ctx), new)

    return {
        "status": "cycled",
        "previous": current,
        "new": new,
        "direction": direction,
        "wrapped": wrapped,
    }


__all__ = ["cycle_grid_size", "_CYCLE_LADDER"]
