"""Spawn-at-previous-click action — arm next spawn at N-th previous click.

Backs the ``spawn.at_previous_click``
:class:`~pharos_engine.tool_router.ToolAction` row added by the AAA4
STUB-triage sprint tick (round 27 after ZZ4).

Distinct from the sibling spawn-position verbs:

* QQ1's ``spawn.at_origin`` arms at world zero.
* TT2's ``spawn.at_view_center`` arms at the camera focal point.
* UU4's ``spawn.at_origin_offset`` arms at ``(0, 0, 0) + offset``.
* VV4's ``spawn.at_last_position`` arms at the last *spawn* drop.
* WW4's ``spawn.at_grid`` snaps a target onto the grid.
* YY4's ``spawn.at_selection_center`` arms at the selection centroid.
* CC1's ``spawn.spawn_at_cursor`` fires immediately at the *live*
  cursor.
* ZZ4's ``spawn.at_last_click`` arms at the *most recent* click.

This verb walks *backwards* through the click history so successive
presses cycle through past viewport clicks. Matches Blender's
Alt+Shift+S (Cursor to Previous Click) / Nova3D's viewport
right-click "Drop at Previous Click" / Unity's Ctrl+Alt+Home
(previous click hotkey).

Position resolution
-------------------

Click history sources (in priority order):

1. ``ctx["click_history"]`` — explicit override list (last item is
   the most recent click; index -1 = last, -2 = previous, ...).
2. ``shell._click_history`` — canonical shell slot.
3. ``shell._input._click_history`` — input-manager fallback.

Index selection
---------------

* ``ctx["depth"]`` (int ≥ 1, default = 1) — how many clicks *back*
  to walk. ``depth=1`` targets the previous click (skip the most
  recent one). ``depth=2`` targets two clicks back, etc.
* Depth is clamped to the history length; if depth exceeds the
  count of stored clicks the verb returns ``no_previous_click``.

Optional offset
---------------

``ctx["offset"]`` may add a 2- or 3-vec delta to the resolved
position — matches the ``spawn.at_last_click`` / ``at_last_position``
micro-offset knob. Malformed offset falls back to ``(0, 0, 0)`` and
the return dict marks ``"malformed_offset": True``.

Return contract
---------------

* ``{"status": "armed", "position": (x, y, z), "depth": N,
   "source": "override" | "shell" | "input_manager",
   "offset": (dx, dy, dz)}`` — success.
* ``{"status": "no_shell"}`` — no shell reachable and no override.
* ``{"status": "no_previous_click"}`` — history is empty or depth
  exceeds history length.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


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


def _resolve_offset(
    ctx: dict[str, Any],
) -> tuple[tuple[float, float, float], bool]:
    raw = ctx.get("offset")
    if raw is None:
        return (_ORIGIN, False)
    got = _to_xyz(raw)
    if got is None:
        return (_ORIGIN, True)
    return (got, False)


def _resolve_depth(ctx: dict[str, Any]) -> int:
    raw = ctx.get("depth", 1)
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return 1
    if val < 1:
        return 1
    return val


def _resolve_history(
    ctx: dict[str, Any],
) -> tuple[list[Any], str] | None:
    """Return ``(history, source)`` or ``None`` when no history is stashed."""
    override = ctx.get("click_history")
    if isinstance(override, (list, tuple)) and override:
        return (list(override), "override")

    shell = _get_shell(ctx)
    if shell is None:
        return None

    hist = getattr(shell, "_click_history", None)
    if isinstance(hist, (list, tuple)) and hist:
        return (list(hist), "shell")

    input_mgr = getattr(shell, "_input", None)
    if input_mgr is not None:
        hist = getattr(input_mgr, "_click_history", None)
        if isinstance(hist, (list, tuple)) and hist:
            return (list(hist), "input_manager")
    return None


def _arm(shell: Any, xyz: tuple[float, float, float]) -> None:
    if shell is None:
        return
    try:
        setattr(shell, "_pending_spawn_position", list(xyz))
    except Exception:  # noqa: BLE001
        pass


def spawn_at_previous_click(ctx: dict[str, Any]) -> dict[str, Any]:
    """Arm the next spawn at the N-th previous viewport click.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell providing
          ``_click_history`` and the ``_pending_spawn_position`` slot.
        * ``click_history`` (optional list): explicit history
          override — last item is the most recent click.
        * ``depth`` (optional int ≥ 1): how many clicks back to walk
          (default 1 = previous click, i.e. skip the most recent).
        * ``offset`` (optional 2- or 3-vec): additive delta.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("spawn_at_previous_click", ctx)
    shell = _get_shell(ctx)
    resolved = _resolve_history(ctx)

    if resolved is None:
        if shell is None and "click_history" not in ctx:
            return {"status": "no_shell"}
        return {"status": "no_previous_click"}

    history, source = resolved
    depth = _resolve_depth(ctx)
    # depth=1 → previous click = history[-2]; depth=2 → history[-3], ...
    index = -(depth + 1)
    if -index > len(history):
        return {"status": "no_previous_click"}

    raw = history[index]
    position = _to_xyz(raw)
    if position is None:
        return {"status": "no_previous_click"}

    offset, malformed = _resolve_offset(ctx)
    xyz = (
        position[0] + offset[0],
        position[1] + offset[1],
        position[2] + offset[2],
    )
    _arm(shell, xyz)
    result: dict[str, Any] = {
        "status": "armed",
        "position": xyz,
        "depth": depth,
        "source": source,
        "offset": offset,
    }
    if malformed:
        result["malformed_offset"] = True
    return result


__all__ = ["spawn_at_previous_click"]
