"""Spawn-at-last-position action — arm the next spawn at the previous drop.

Backs the ``spawn.at_last_position``
:class:`~pharos_engine.tool_router.ToolAction` row added by the VV4
STUB-triage sprint tick (round 23 after UU4).

Distinct from the other spawn-history verbs:

* CC1's ``spawn.repeat_last`` *fires* the last spawn immediately
  (re-invokes ``shell._on_spawn`` with the recorded ``(card_id,
  spec)`` tuple). This verb only *arms* the next-spawn coordinate —
  the next user gesture drops the fresh prefab there. Blender's
  "Snap Cursor to Last Position" + ``Shift+A`` pattern.
* QQ1's ``spawn.at_origin`` arms at world zero (ignores history).
* TT2's ``spawn.at_view_center`` arms at the camera focal point.
* UU4's ``spawn.at_origin_offset`` arms at ``(0, 0, 0) + offset``.
* DD1's ``spawn.repeat_last_batch`` re-fires a whole grid batch.

Position resolution
-------------------

Search order for the "last position" 3-vec:

1. ``ctx["last_position"]`` — explicit override (tests use this).
2. ``ctx["last_spawn"]`` — ``(card_id, spec)`` tuple; the spec's
   ``position`` / ``origin`` / ``pos`` key is read.
3. ``shell._last_spawn_position`` — cached slot.
4. ``shell._last_spawn`` — the spec-tuple slot maintained by CC1.
5. ``shell._spawn_menu._last_spawn`` — notebook menu fallback.

Optional offset
---------------

``ctx["offset"]`` may add a 2- or 3-vec delta to the resolved
position — matches the ``repeat_last`` micro-offset knob so
successive presses can build a chain (e.g. ``[1, 0, 0]`` steps the
new spawn one unit right of the last one). Malformed offset falls
back to ``(0, 0, 0)`` and the return dict marks
``"malformed_offset": True``.

Return contract
---------------

* ``{"status": "armed", "position": (x, y, z),
   "source": "override" | "history" | "shell_position" |
                 "shell_spawn" | "menu_spawn",
   "offset": (dx, dy, dz)}`` — success. ``offset`` is present even
   when zero for symmetry with ``spawn.at_origin_offset``.
* ``{"status": "no_shell"}`` — no shell reachable and no override.
* ``{"status": "no_history"}`` — shell reachable but no last-position
  or last-spawn tuple stashed anywhere.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_POS_KEYS = ("position", "origin", "pos")
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


def _extract_pos_from_spec(spec: Any) -> tuple[float, float, float] | None:
    if not isinstance(spec, dict):
        return None
    for key in _POS_KEYS:
        if key in spec:
            got = _to_xyz(spec[key])
            if got is not None:
                return got
    return None


def _extract_from_tuple(record: Any) -> tuple[float, float, float] | None:
    if not isinstance(record, tuple) or len(record) != 2:
        return None
    _card_id, spec = record
    return _extract_pos_from_spec(spec)


def _resolve_last_position(
    ctx: dict[str, Any],
) -> tuple[tuple[float, float, float], str] | None:
    """Return ``(position, source)`` or ``None`` when no history exists."""
    override = ctx.get("last_position")
    if override is not None:
        got = _to_xyz(override)
        if got is not None:
            return (got, "override")

    override_tuple = ctx.get("last_spawn")
    got = _extract_from_tuple(override_tuple)
    if got is not None:
        return (got, "history")

    shell = _get_shell(ctx)
    if shell is None:
        return None

    got = _to_xyz(getattr(shell, "_last_spawn_position", None))
    if got is not None:
        return (got, "shell_position")

    got = _extract_from_tuple(getattr(shell, "_last_spawn", None))
    if got is not None:
        return (got, "shell_spawn")

    menu = getattr(shell, "_spawn_menu", None)
    if menu is not None:
        got = _extract_from_tuple(getattr(menu, "_last_spawn", None))
        if got is not None:
            return (got, "menu_spawn")
    return None


def _arm(shell: Any, xyz: tuple[float, float, float]) -> None:
    if shell is None:
        return
    try:
        setattr(shell, "_pending_spawn_position", list(xyz))
    except Exception:  # noqa: BLE001
        pass


def spawn_at_last_position(ctx: dict[str, Any]) -> dict[str, Any]:
    """Bind the next spawn to the last-spawn's coordinate.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell providing history slots
          + the ``_pending_spawn_position`` slot.
        * ``last_position`` (optional 2- or 3-vec): explicit override,
          highest priority.
        * ``last_spawn`` (optional ``(card_id, spec)``): explicit
          history tuple (matches ``spawn.repeat_last`` convention).
        * ``offset`` (optional 2- or 3-vec): additive delta.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("spawn_at_last_position", ctx)
    shell = _get_shell(ctx)
    resolved = _resolve_last_position(ctx)

    if resolved is None:
        if shell is None:
            return {"status": "no_shell"}
        return {"status": "no_history"}

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


__all__ = ["spawn_at_last_position"]
