"""Spawn-at-view-center action — drop the next spawn at the camera focus.

Backs the ``spawn.at_view_center``
:class:`~pharos_engine.tool_router.ToolAction` row added by the TT2
STUB-triage sprint tick (round 21).

Sibling to EE1's ``spawn.spawn_at_cursor`` (drop at the mouse cursor's
world position) and QQ1's ``spawn.at_origin`` (drop at world zero). This
verb picks the *view centre* — the point the current viewport camera is
looking at. Every DCC ships this gesture too — Blender's ``Shift+A →
Add at 3D-cursor`` after ``Shift+S → Cursor to World Origin`` collapses
to the equivalent, Unity's ``GameObject → Align with View``, Nova3D's
``Spawn at Camera Focus``.

View-centre resolution
----------------------

1. ``ctx["view_center"]`` — explicit override (tests pass this).
2. ``ctx["shell"].get_view_center_world_position()`` — canonical shell
   hook when the viewport panel exposes one.
3. ``ctx["shell"]._view_center_world_position`` — pre-computed slot.
4. ``ctx["shell"]._viewport_panel._cam_target`` — the orbit-camera
   target vector (matches ViewportPanel's stored focus point).
5. ``(0.0, 0.0, 0.0)`` — final fallback so a bare shell still gets
   *some* deterministic drop point instead of silently no-op'ing.

Distinct from ``spawn.spawn_at_cursor`` (mouse position — moves with
the pointer between spawns) and ``spawn.at_origin`` (always world zero,
never follows the camera).

Return contract
---------------

* ``{"status": "armed", "position": (x, y, z)}`` — coordinate stashed on
  ``shell._pending_spawn_position``; next spawn-menu click lands there.
* ``{"status": "respawned", "card_id": str, "spec": dict,
   "position": (x, y, z)}`` — ``mode="repeat"`` fired ``_last_spawn``
   at the view centre.
* ``{"status": "no_shell"}`` — no shell and no explicit
   ``view_center`` override.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from ._ctx import ensure_ctx
from .spawn_history_actions import _resolve_last_spawn, record_last_spawn


_POS_KEYS = ("position", "origin", "pos")
_FALLBACK: tuple[float, float, float] = (0.0, 0.0, 0.0)


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _to_xyz(raw: Any) -> tuple[float, float, float] | None:
    """Coerce *raw* to a 3-tuple (pads Z with 0.0). Returns None on failure."""
    if not isinstance(raw, (list, tuple)) or not raw:
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


def _resolve_view_center(
    ctx: dict[str, Any],
) -> tuple[float, float, float]:
    """Return the viewport's focal-point world coordinate."""
    override = ctx.get("view_center")
    if override is not None:
        got = _to_xyz(override)
        if got is not None:
            return got
    shell = _get_shell(ctx)
    if shell is None:
        return _FALLBACK
    getter = getattr(shell, "get_view_center_world_position", None)
    if callable(getter):
        try:
            raw = getter()
        except Exception:  # noqa: BLE001
            raw = None
        got = _to_xyz(raw) if raw is not None else None
        if got is not None:
            return got
    for slot in ("_view_center_world_position",):
        raw = getattr(shell, slot, None)
        got = _to_xyz(raw) if raw is not None else None
        if got is not None:
            return got
    panel = getattr(shell, "_viewport_panel", None)
    if panel is not None:
        raw = getattr(panel, "_cam_target", None)
        got = _to_xyz(raw) if raw is not None else None
        if got is not None:
            return got
    return _FALLBACK


def _arm_next_spawn(shell: Any, xyz: tuple[float, float, float]) -> None:
    if shell is None:
        return
    try:
        setattr(shell, "_pending_spawn_position", list(xyz))
    except Exception:  # noqa: BLE001
        pass


def _dispatch_at(
    shell: Any,
    card_id: str,
    template: dict[str, Any],
    xyz: tuple[float, float, float],
) -> dict[str, Any]:
    """Re-fire ``card_id`` with ``template`` at *xyz*."""
    spec = deepcopy(template)
    seeded = False
    for key in _POS_KEYS:
        if key in spec:
            spec[key] = [xyz[0], xyz[1], xyz[2]]
            seeded = True
            break
    if not seeded:
        spec["position"] = [xyz[0], xyz[1], xyz[2]]
    if shell is not None:
        on_spawn = getattr(shell, "_on_spawn", None)
        if callable(on_spawn):
            try:
                on_spawn(card_id, spec)
            except Exception as exc:  # noqa: BLE001
                return {"status": "error", "message": str(exc)}
            record_last_spawn(shell, card_id, spec)
    return {
        "status": "respawned",
        "card_id": card_id,
        "spec": spec,
        "position": xyz,
    }


def spawn_at_view_center(ctx: dict[str, Any]) -> dict[str, Any]:
    """Bind the next spawn to the viewport's focal point.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell providing the viewport /
          spawn hooks + the ``_pending_spawn_position`` slot.
        * ``view_center`` (optional 2- or 3-vec): explicit override.
        * ``mode`` (optional str, default ``"arm"``): ``"arm"`` stashes
          the coordinate; ``"repeat"`` re-fires ``shell._last_spawn`` at
          the view centre immediately.
        * ``last_spawn`` (optional ``(card_id, spec)``): headless
          override for the repeat path.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("spawn_at_view_center", ctx)
    shell = _get_shell(ctx)
    if shell is None and "view_center" not in ctx:
        return {"status": "no_shell"}

    xyz = _resolve_view_center(ctx)
    mode = ctx.get("mode", "arm")
    if mode == "repeat":
        record = _resolve_last_spawn(ctx)
        if record is not None:
            card_id, template = record
            return _dispatch_at(shell, card_id, template, xyz)
        # No history — fall through to arm.

    _arm_next_spawn(shell, xyz)
    return {"status": "armed", "position": xyz}


__all__ = ["spawn_at_view_center"]
