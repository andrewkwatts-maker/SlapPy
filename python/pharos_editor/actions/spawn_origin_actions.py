"""Spawn-at-origin action — drop the next spawn (or replay) at (0, 0, 0).

Backs the ``spawn.at_origin`` :class:`~pharos_editor.tool_router.ToolAction`
row added by the QQ1 STUB-triage sprint tick (round 18 after PP1's
round-17 ``selection.shrink`` / ``selection.invert_by_type`` /
``view.toggle_wireframe`` / ``edit.rename`` / ``edit.duplicate_at_cursor``
batch).

Companion to EE1's :mod:`spawn_cursor_actions` (``spawn.spawn_at_cursor``)
— every DCC ships a "reset origin" gesture next to the cursor-drop
gesture. Blender's ``Shift+C`` recenters the 3D cursor to origin;
Unity's context menu ``Reset Position`` moves a spawned prefab back to
world zero. This helper is the analogue for the *next* spawn: it arms
``shell._pending_spawn_position`` with ``(0, 0, 0)`` so the next
spawn-menu card lands at world origin — or, when ``ctx["mode"] ==
"repeat"`` and the shell has a last-spawn record, immediately re-fires
the last spawn at origin.

Return contract
---------------

* ``{"status": "armed", "position": (0.0, 0.0, 0.0)}`` — coordinate
  stashed on ``shell._pending_spawn_position`` for the next spawn.
* ``{"status": "respawned", "card_id": str, "spec": dict,
   "position": (0.0, 0.0, 0.0)}`` — repeat-at-origin dispatched.
* ``{"status": "no_shell"}`` — no shell in ``ctx``; nothing to arm.
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


def _arm_next_spawn(shell: Any, xyz: tuple[float, float, float]) -> None:
    if shell is None:
        return
    try:
        setattr(shell, "_pending_spawn_position", list(xyz))
    except Exception:  # noqa: BLE001
        pass


def _dispatch_at_origin(
    shell: Any,
    card_id: str,
    template: dict[str, Any],
) -> dict[str, Any]:
    """Re-fire ``card_id`` with ``template`` centered at world origin."""
    spec = deepcopy(template)
    seeded = False
    for key in _POS_KEYS:
        if key in spec:
            spec[key] = [0.0, 0.0, 0.0]
            seeded = True
            break
    if not seeded:
        spec["position"] = [0.0, 0.0, 0.0]

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
        "position": _ORIGIN,
    }


def spawn_at_origin(ctx: dict[str, Any]) -> dict[str, Any]:
    """Bind the next spawn to world origin, or replay the last spawn there.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell providing the spawn hook +
          the ``_pending_spawn_position`` slot.
        * ``mode`` (optional str, default ``"arm"``): ``"arm"`` stashes
          the origin coordinate for the next spawn-menu click;
          ``"repeat"`` re-fires ``shell._last_spawn`` at origin
          immediately (falls back to arm when no history exists).
        * ``last_spawn`` (optional ``(card_id, spec)``): headless
          override for the repeat path.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("spawn_at_origin", ctx)
    shell = _get_shell(ctx)
    if shell is None and ctx.get("mode") != "repeat":
        # Pure-arm without a shell has nothing to stash — bail so the
        # caller can react. The repeat path still works headlessly when
        # ``ctx["last_spawn"]`` is supplied.
        return {"status": "no_shell"}

    mode = ctx.get("mode", "arm")
    if mode == "repeat":
        record = _resolve_last_spawn(ctx)
        if record is not None:
            card_id, template = record
            return _dispatch_at_origin(shell, card_id, template)
        # No history — fall through to arm so the click isn't wasted.
        if shell is None:
            return {"status": "no_shell"}

    _arm_next_spawn(shell, _ORIGIN)
    return {"status": "armed", "position": _ORIGIN}


__all__ = ["spawn_at_origin"]
