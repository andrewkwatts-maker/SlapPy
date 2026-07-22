"""Snap set-angle-snap action — set the rotation-gizmo snap step in degrees.

Backs the ``snap.set_angle_snap``
:class:`~pharos_engine.tool_router.ToolAction` row added by the UU4
STUB-triage sprint tick (round 22).

Every DCC that ships a rotate-gizmo also ships an angle-snap spinner:
Blender's transform panel "Angle" field, Unity's ProGrids rotation
snap, Nova3D's ``Snap → Rotation Angle`` dialog. Distinct from OO1's
``snap.increase_grid_size`` / ``snap.decrease_grid_size`` (which walk
*position* snap along a geometric ladder), RR1's
``snap.toggle_incremental`` (which flips a boolean gate), and
``tools.snap_to_grid`` (an on/off toggle for the whole snap system).

Angle resolution
----------------

* ``ctx["degrees"]`` — required numeric target in degrees. Clamped to
  ``[0.0, 180.0]`` — an angle > 180 would wrap and be equivalent to a
  smaller one; ``0.0`` explicitly means "no snap" (equivalent to
  disabling angle snap).
* Snapping to canonical angles: when the incoming value is within
  ``0.05°`` of one of the canonical DCC steps (``1, 5, 15, 22.5, 30, 45,
  60, 90, 180``), the canonical value is used verbatim — matches
  Blender's "snap the snap-step" behaviour.

Shell write path
----------------

* Primary: ``shell._snap_angle_deg`` (canonical, matches naming of
  ``_snap_grid_size``).
* Mirror: ``shell._snap_angle`` (legacy alias — earlier drafts used
  this).

Return contract
---------------

* ``{"status": "set", "previous": float, "new": float,
   "canonical": bool}`` — success. ``canonical=True`` when the value
   snapped to one of the DCC-standard angles.
* ``{"status": "missing_degrees"}`` — ``ctx["degrees"]`` absent or
  non-finite.
* ``{"status": "no_shell"}`` — no shell reachable to store the value.
* ``{"status": "unchanged", "value": float}`` — new value matches the
  existing value (within tolerance).
"""
from __future__ import annotations

import math
from typing import Any

from ._ctx import ensure_ctx


_MIN_ANGLE: float = 0.0
_MAX_ANGLE: float = 180.0
_CANONICAL: tuple[float, ...] = (
    1.0, 5.0, 15.0, 22.5, 30.0, 45.0, 60.0, 90.0, 180.0,
)
_CANONICAL_TOL: float = 0.05
_UNCHANGED_TOL: float = 1e-6


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _coerce_degrees(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if math.isnan(val) or math.isinf(val):
        return None
    return val


def _clamp(val: float) -> float:
    return max(_MIN_ANGLE, min(_MAX_ANGLE, val))


def _snap_to_canonical(val: float) -> tuple[float, bool]:
    for canon in _CANONICAL:
        if abs(val - canon) <= _CANONICAL_TOL:
            return (canon, True)
    return (val, False)


def _read_previous(shell: Any) -> float:
    if shell is None:
        return 0.0
    for attr in ("_snap_angle_deg", "_snap_angle"):
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
    for attr in ("_snap_angle_deg", "_snap_angle"):
        try:
            setattr(shell, attr, value)
            wrote = True
        except Exception:  # noqa: BLE001
            continue
    return wrote


def set_angle_snap(ctx: dict[str, Any]) -> dict[str, Any]:
    """Set the rotation-gizmo snap step to ``ctx["degrees"]``.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``degrees`` (required, numeric): snap step in degrees.
          Clamped to ``[0, 180]``.
        * ``shell`` (optional): editor shell — stores the value on
          ``_snap_angle_deg`` / ``_snap_angle``.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("set_angle_snap", ctx)
    raw = ctx.get("degrees")
    degrees = _coerce_degrees(raw)
    if degrees is None:
        return {"status": "missing_degrees"}

    clamped = _clamp(degrees)
    canonical_val, canonical = _snap_to_canonical(clamped)
    final = canonical_val

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


__all__ = ["set_angle_snap"]
