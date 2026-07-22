"""Spawn-at-origin-offset action — drop the next spawn at ``origin + delta``.

Backs the ``spawn.at_origin_offset``
:class:`~pharos_editor.tool_router.ToolAction` row added by the UU4
STUB-triage sprint tick (round 22 after TT2's round-21 batch).

Sibling to QQ1's ``spawn.at_origin`` (drop at exact world zero), TT2's
``spawn.at_view_center`` (drop at the camera's focal point), and EE1's
``spawn.spawn_at_cursor`` (drop at mouse position). Every DCC that ships
a numeric-entry spawn dialog exposes an *offset-from-origin* mode too —
Blender's ``Shift+A`` after typing ``F6 → Offset`` in the redo panel,
Unity's "Instantiate at (x,y,z)" via the ``GameObject → Create Empty``
prompt, Nova3D's ``Spawn → Advanced → Offset from Origin``.

Distinct from ``spawn.at_origin``:

* ``spawn.at_origin`` forces the drop to *world zero*, no matter what.
* ``spawn.at_origin_offset`` accepts a ``ctx["offset"]`` 3-vec and drops
  the next spawn at ``(0, 0, 0) + offset``. When ``offset`` is missing
  or all zeros the resulting behaviour matches ``spawn.at_origin``, but
  the code path stays deliberately separate so a caller can still probe
  which verb fired by inspecting the return dict.

Offset resolution
-----------------

* ``ctx["offset"]`` — required 2- or 3-vec (2-vec pads Z with 0.0).
* Any non-numeric / malformed offset falls back to ``(0, 0, 0)`` and the
  return dict records ``"malformed_offset": True``.

Return contract
---------------

* ``{"status": "armed", "position": (x, y, z), "offset": (dx, dy, dz)}``
  — coordinate stashed on ``shell._pending_spawn_position``.
* ``{"status": "respawned", "card_id": str, "spec": dict,
   "position": (x, y, z), "offset": (dx, dy, dz)}`` —
   ``mode="repeat"`` fired ``_last_spawn`` at the offset.
* ``{"status": "no_shell"}`` — no shell reachable and no repeat history
  available for a headless dispatch.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from ._ctx import ensure_ctx
from .spawn_history_actions import _resolve_last_spawn, record_last_spawn


_POS_KEYS = ("position", "origin", "pos")
_ORIGIN: tuple[float, float, float] = (0.0, 0.0, 0.0)


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _to_xyz(raw: Any) -> tuple[float, float, float] | None:
    """Coerce *raw* to a 3-tuple (pads Z with 0.0). Returns None on failure."""
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


def _resolve_offset(ctx: dict[str, Any]) -> tuple[tuple[float, float, float], bool]:
    """Return ``(offset, malformed)`` — never raises."""
    raw = ctx.get("offset")
    if raw is None:
        return (_ORIGIN, False)
    got = _to_xyz(raw)
    if got is None:
        return (_ORIGIN, True)
    return (got, False)


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


def spawn_at_origin_offset(ctx: dict[str, Any]) -> dict[str, Any]:
    """Bind the next spawn to ``(0, 0, 0) + ctx["offset"]``.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell providing the spawn hook +
          the ``_pending_spawn_position`` slot.
        * ``offset`` (optional 2- or 3-vec): delta added to world origin.
          Default ``(0, 0, 0)``. Malformed values fall back to origin +
          set ``"malformed_offset": True`` on the return dict.
        * ``mode`` (optional str, default ``"arm"``): ``"arm"`` stashes
          the coordinate; ``"repeat"`` re-fires ``shell._last_spawn`` at
          the offset immediately.
        * ``last_spawn`` (optional ``(card_id, spec)``): headless
          override for the repeat path.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("spawn_at_origin_offset", ctx)
    shell = _get_shell(ctx)
    if shell is None and ctx.get("mode") != "repeat":
        return {"status": "no_shell"}

    offset, malformed = _resolve_offset(ctx)
    xyz = (
        _ORIGIN[0] + offset[0],
        _ORIGIN[1] + offset[1],
        _ORIGIN[2] + offset[2],
    )

    mode = ctx.get("mode", "arm")
    if mode == "repeat":
        record = _resolve_last_spawn(ctx)
        if record is not None:
            card_id, template = record
            result = _dispatch_at(shell, card_id, template, xyz)
            result["offset"] = offset
            if malformed:
                result["malformed_offset"] = True
            return result
        if shell is None:
            return {"status": "no_shell"}

    _arm_next_spawn(shell, xyz)
    result: dict[str, Any] = {
        "status": "armed",
        "position": xyz,
        "offset": offset,
    }
    if malformed:
        result["malformed_offset"] = True
    return result


__all__ = ["spawn_at_origin_offset"]
