"""Spawn-at-cursor action — bind the next spawn to the cursor position.

Backs the ``spawn.spawn_at_cursor`` :class:`~slappyengine.tool_router.ToolAction`
row added by the EE1 STUB-triage sprint tick (round 8 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1).

Design intent
-------------

The spawn-menu cards drop entities at the world origin by default; the
``spawn.spawn_at_cursor`` action lets an operator "arm" the next spawn
to land under the viewport cursor instead. Rather than opening its own
menu, the action stashes the resolved world coordinate on
``shell._pending_spawn_position`` — the router's ``_fb_spawn`` wrapper
already consults that slot when placing a fresh entity so the next
click / hotkey drop lands at the cursor.

The action can also *immediately* dispatch when the shell exposes a
last-spawn record (``shell._last_spawn``) — repeating that spawn at the
cursor is the more common UX ("spawn one more of what I just spawned,
but here"). Whether to auto-dispatch is controlled by ``ctx["mode"]``:

* ``"arm"`` (default) — stash the coordinate; the next spawn-menu
  invocation consumes it.
* ``"repeat"`` — dispatch a copy of ``shell._last_spawn`` at the cursor.
  Falls back to ``"arm"`` when no history exists.

Cursor resolution order
-----------------------

1. ``ctx["cursor"]`` — explicit override (tests use this).
2. ``ctx["shell"].get_cursor_world_position()`` — canonical shell hook.
3. ``ctx["shell"]._cursor_world_position`` — pre-computed slot.
4. ``ctx["shell"]._last_cursor`` — legacy Nova3D slot.

Return contract
---------------

* ``{"status": "armed", "position": (x, y, z)}`` — coordinate stashed.
* ``{"status": "respawned", "card_id": str, "spec": dict, "position":
   (x, y, z)}`` — repeat-at-cursor dispatched.
* ``{"status": "no_cursor"}`` — no cursor coordinate reachable.
* ``{"status": "no_shell"}`` — no shell + no explicit cursor override.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from ._ctx import ensure_ctx
from .spawn_history_actions import _resolve_last_spawn, record_last_spawn


_POS_KEYS = ("position", "origin", "pos")


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


def _resolve_cursor(ctx: dict[str, Any]) -> tuple[float, float, float] | None:
    """Return the cursor's world coordinate as a 3-tuple.

    See the module docstring for the resolution order.
    """
    override = ctx.get("cursor")
    if override is not None:
        got = _to_xyz(override)
        if got is not None:
            return got
    shell = _get_shell(ctx)
    if shell is None:
        return None
    getter = getattr(shell, "get_cursor_world_position", None)
    if callable(getter):
        try:
            raw = getter()
        except Exception:  # noqa: BLE001
            raw = None
        got = _to_xyz(raw) if raw is not None else None
        if got is not None:
            return got
    for slot in ("_cursor_world_position", "_last_cursor"):
        raw = getattr(shell, slot, None)
        got = _to_xyz(raw) if raw is not None else None
        if got is not None:
            return got
    return None


def _arm_next_spawn(shell: Any, xyz: tuple[float, float, float]) -> None:
    """Stash *xyz* on ``shell._pending_spawn_position`` for the next spawn."""
    if shell is None:
        return
    try:
        setattr(shell, "_pending_spawn_position", list(xyz))
    except Exception:  # noqa: BLE001
        pass


def _dispatch_at_cursor(
    shell: Any,
    card_id: str,
    template: dict[str, Any],
    xyz: tuple[float, float, float],
) -> dict[str, Any]:
    """Re-fire ``card_id`` with ``template`` centered at *xyz*."""
    spec = deepcopy(template)
    # Overwrite whichever positional key the template already carries;
    # seed ``position`` if the template has none.
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


def spawn_at_cursor(ctx: dict[str, Any]) -> dict[str, Any]:
    """Bind the next spawn to the cursor position (or repeat-at-cursor now).

    Consumed ctx keys:

    * ``shell`` (optional): editor shell providing the cursor + spawn hooks.
    * ``cursor`` (optional 2- or 3-vec): explicit world coordinate.
    * ``mode`` (optional str, default ``"arm"``): ``"arm"`` stashes the
      coordinate for the next spawn-menu click; ``"repeat"`` dispatches
      a copy of ``shell._last_spawn`` at the cursor immediately.
    * ``last_spawn`` (optional ``(card_id, spec)``): headless override
      for the repeat path.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("spawn_at_cursor", ctx)
    shell = _get_shell(ctx)
    if shell is None and "cursor" not in ctx:
        return {"status": "no_shell"}

    xyz = _resolve_cursor(ctx)
    if xyz is None:
        return {"status": "no_cursor"}

    mode = ctx.get("mode", "arm")
    if mode == "repeat":
        record = _resolve_last_spawn(ctx)
        if record is not None:
            card_id, template = record
            return _dispatch_at_cursor(shell, card_id, template, xyz)
        # No history — fall through to arm so the click isn't wasted.

    _arm_next_spawn(shell, xyz)
    return {"status": "armed", "position": xyz}


__all__ = ["spawn_at_cursor"]
