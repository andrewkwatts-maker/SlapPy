"""Snap set-grid-size action — absolute grid-size setter.

Backs the ``snap.set_grid_size``
:class:`~pharos_engine.tool_router.ToolAction` row added by the VV4
STUB-triage sprint tick (round 23 after UU4).

Distinct from the sibling snap verbs:

* OO1's ``snap.increase_grid_size`` / ``snap.decrease_grid_size`` walk
  the geometric ladder ``0.5 → 1 → 2 → 4 → 8 …`` one rung at a time.
  This verb accepts an absolute target and snaps *once* — matching
  the "Grid Size" numeric spinner in Blender's N-panel, Unity's
  ProGrids "Snap Value" input, or Nova3D's Snap-panel spin box.
* UU4's ``snap.set_angle_snap`` sets the rotation-gizmo snap step; this
  one sets the positional grid.
* RR1's ``snap.toggle_incremental`` flips a boolean gate.
* ``tools.snap_to_grid`` is the master on/off toggle.

Value clamp
-----------

* Clamped to ``[0.5, 4096.0]`` — same bounds as
  ``snap_grid_size_actions`` so the two verbs never disagree on
  which values are legal.
* ``0`` is *not* legal ("no snap" is expressed via
  ``tools.snap_to_grid``, not by writing zero into the grid size).

Ladder-snap
-----------

When the incoming value is within ``0.01`` of one of the canonical
ladder rungs (``0.5, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024,
2048, 4096``), the canonical rung is used verbatim. Matches Blender's
"snap the snap step" behaviour and keeps the "coarser / finer" verbs
in sync — a subsequent step-up from a canonical rung lands on the
next rung, not on ``rung + epsilon``.

Return contract
---------------

* ``{"status": "set", "previous": float, "new": float,
   "canonical": bool}`` — success.
* ``{"status": "missing_size"}`` — ``ctx["size"]`` absent or
  non-numeric / non-finite.
* ``{"status": "invalid_size", "value": float}`` — value ≤ 0 or NaN /
  inf. Distinguished from ``missing_size`` so the caller can log the
  offending value.
* ``{"status": "no_shell"}`` — no shell reachable to store the value.
* ``{"status": "unchanged", "value": float}`` — new value matches the
  existing value (within tolerance).
"""
from __future__ import annotations

import math
from typing import Any

from ._ctx import ensure_ctx


_MIN_GRID: float = 0.5
_MAX_GRID: float = 4096.0
_LADDER: tuple[float, ...] = (
    0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0, 512.0,
    1024.0, 2048.0, 4096.0,
)
_LADDER_TOL: float = 0.01
_UNCHANGED_TOL: float = 1e-6


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _coerce_size(raw: Any) -> tuple[float | None, str]:
    """Return ``(value, status)`` — ``status`` is one of ``ok`` / ``missing`` / ``invalid``."""
    if raw is None:
        return (None, "missing")
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return (None, "missing")
    if math.isnan(val) or math.isinf(val):
        return (val, "invalid")
    if val <= 0.0:
        return (val, "invalid")
    return (val, "ok")


def _clamp(val: float) -> float:
    return max(_MIN_GRID, min(_MAX_GRID, val))


def _snap_to_ladder(val: float) -> tuple[float, bool]:
    for rung in _LADDER:
        if abs(val - rung) <= _LADDER_TOL:
            return (rung, True)
    return (val, False)


def _read_previous(shell: Any) -> float:
    if shell is None:
        return 0.0
    for attr in ("_snap_grid_size", "_grid_size", "grid_size"):
        raw = getattr(shell, attr, None)
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return 0.0


def _write(shell: Any, value: float) -> bool:
    if shell is None:
        return False
    wrote = False
    for attr in ("_snap_grid_size", "_grid_size", "grid_size"):
        try:
            setattr(shell, attr, value)
            wrote = True
        except Exception:  # noqa: BLE001
            continue
    return wrote


def set_grid_size(ctx: dict[str, Any]) -> dict[str, Any]:
    """Set the snap grid size to ``ctx["size"]``.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``size`` (required, positive numeric): grid size in scene
          units. Clamped to ``[0.5, 4096.0]``.
        * ``shell`` (optional): editor shell — stores the value on
          ``_snap_grid_size`` / ``_grid_size`` / ``grid_size``.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("set_grid_size", ctx)
    raw = ctx.get("size")
    value, status = _coerce_size(raw)
    if status == "missing":
        return {"status": "missing_size"}
    if status == "invalid":
        return {"status": "invalid_size", "value": value}
    assert value is not None  # narrow for the type checker

    clamped = _clamp(value)
    snapped, canonical = _snap_to_ladder(clamped)
    final = snapped

    shell = _get_shell(ctx)
    if shell is None:
        return {"status": "no_shell"}

    previous = _read_previous(shell)
    if abs(previous - final) <= _UNCHANGED_TOL:
        return {"status": "unchanged", "value": final}

    if not _write(shell, final):
        return {"status": "error", "message": "attribute write refused"}

    return {
        "status": "set",
        "previous": previous,
        "new": final,
        "canonical": canonical,
    }


__all__ = ["set_grid_size"]
