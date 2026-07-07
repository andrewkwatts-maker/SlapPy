"""Spawn-at-last-click action — arm next spawn at the last recorded click.

Backs the ``spawn.at_last_click``
:class:`~slappyengine.tool_router.ToolAction` row added by the ZZ4
STUB-triage sprint tick (round 26 after YY4).

Distinct from the sibling spawn-position verbs:

* QQ1's ``spawn.at_origin`` arms at world zero.
* TT2's ``spawn.at_view_center`` arms at the camera focal point.
* UU4's ``spawn.at_origin_offset`` arms at ``(0, 0, 0) + offset``.
* VV4's ``spawn.at_last_position`` arms at the last *spawn* drop.
  This verb targets the last *cursor click* — the two diverge when the
  user has clicked around the viewport but not yet dropped a prefab.
* WW4's ``spawn.at_grid`` snaps a target onto the grid before arming.
* YY4's ``spawn.at_selection_center`` arms at the selection centroid.
* CC1's ``spawn.spawn_at_cursor`` fires immediately at the *live*
  cursor (not the last recorded click).

Matches Blender's ``Shift+S → Cursor to Last Click`` /
Unity's Ctrl+Shift+F (position at last click) /
Nova3D's viewport right-click "Drop at Last Click".

Position resolution
-------------------

Search order for the "last click" 2- or 3-vec:

1. ``ctx["last_click"]`` — explicit override (tests use this).
2. ``ctx["click_position"]`` — alias override.
3. ``shell._last_click_position`` — canonical shell slot.
4. ``shell._last_cursor_position`` — legacy alias (matches
   ``spawn.spawn_at_cursor``'s reader).
5. ``shell._input._last_click`` — input-manager fallback.

Optional offset
---------------

``ctx["offset"]`` may add a 2- or 3-vec delta to the resolved
position — matches the ``spawn.at_last_position`` micro-offset knob so
successive presses can build a chain (e.g. ``[1, 0, 0]`` steps the
new spawn one unit right of the last click). Malformed offset falls
back to ``(0, 0, 0)`` and the return dict marks
``"malformed_offset": True``.

Return contract
---------------

* ``{"status": "armed", "position": (x, y, z),
   "source": "override" | "shell_click" | "shell_cursor" |
                 "input_click",
   "offset": (dx, dy, dz)}`` — success. ``offset`` is present even
   when zero for symmetry with ``spawn.at_last_position``.
* ``{"status": "no_shell"}`` — no shell reachable and no override.
* ``{"status": "no_click"}`` — shell reachable but no click coordinate
  stashed anywhere.
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


def _resolve_offset(ctx: dict[str, Any]) -> tuple[tuple[float, float, float], bool]:
    raw = ctx.get("offset")
    if raw is None:
        return (_ORIGIN, False)
    got = _to_xyz(raw)
    if got is None:
        return (_ORIGIN, True)
    return (got, False)


def _resolve_last_click(
    ctx: dict[str, Any],
) -> tuple[tuple[float, float, float], str] | None:
    """Return ``(position, source)`` or ``None`` when no click is stashed."""
    override = ctx.get("last_click")
    if override is not None:
        got = _to_xyz(override)
        if got is not None:
            return (got, "override")
    override = ctx.get("click_position")
    if override is not None:
        got = _to_xyz(override)
        if got is not None:
            return (got, "override")

    shell = _get_shell(ctx)
    if shell is None:
        return None

    got = _to_xyz(getattr(shell, "_last_click_position", None))
    if got is not None:
        return (got, "shell_click")

    got = _to_xyz(getattr(shell, "_last_cursor_position", None))
    if got is not None:
        return (got, "shell_cursor")

    input_mgr = getattr(shell, "_input", None)
    if input_mgr is not None:
        got = _to_xyz(getattr(input_mgr, "_last_click", None))
        if got is not None:
            return (got, "input_click")
    return None


def _arm(shell: Any, xyz: tuple[float, float, float]) -> None:
    if shell is None:
        return
    try:
        setattr(shell, "_pending_spawn_position", list(xyz))
    except Exception:  # noqa: BLE001
        pass


def spawn_at_last_click(ctx: dict[str, Any]) -> dict[str, Any]:
    """Arm the next spawn at the last recorded viewport click.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell providing click slots +
          the ``_pending_spawn_position`` slot.
        * ``last_click`` (optional 2- or 3-vec): explicit override,
          highest priority.
        * ``click_position`` (optional 2- or 3-vec): alias override.
        * ``offset`` (optional 2- or 3-vec): additive delta.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("spawn_at_last_click", ctx)
    shell = _get_shell(ctx)
    resolved = _resolve_last_click(ctx)

    if resolved is None:
        if shell is None:
            return {"status": "no_shell"}
        return {"status": "no_click"}

    position, source = resolved
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
        "source": source,
        "offset": offset,
    }
    if malformed:
        result["malformed_offset"] = True
    return result


__all__ = ["spawn_at_last_click"]
