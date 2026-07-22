"""Row-batch spawn action — spawn N copies in a single row.

Backs the ``spawn.spawn_batch_row``
:class:`~pharos_editor.tool_router.ToolAction` row added by the II5
STUB-triage sprint tick (round 11 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1 / EE1 / FF1 / GG1).

Sibling to
:func:`pharos_editor.actions.spawn_batch_actions.repeat_last_batch` — but
where ``repeat_last_batch`` lays down a near-square NxM *grid*, this
variant lays down a straight-line *row*. Useful for "generate a wave of
7 enemies" / "line up a rack of pickups" flows where the grid layout
would leave dangling last-row cells and make the level author eyeball
alignment manually.

Direction is 2D: ``horizontal`` (default; increments X) or ``vertical``
(increments Y). 3D scenes can pass a full ``ctx["stride"]`` 3-vec to
walk any diagonal.

Ctx keys
--------

* ``shell`` (optional): editor shell — receives ``_on_spawn`` calls
  and the ``_last_spawn`` retarget on each dispatch. When absent the
  helper returns the spec list so headless callers can drive their own
  dispatch (matches ``repeat_last_batch`` semantics).
* ``last_spawn`` (optional ``(card_id, spec)``): explicit source
  override — headless tests pass this to skip the shell probe.
* ``count`` (optional int, default ``5``): total copies to lay down.
  Values ``<= 0`` short-circuit with ``{"status": "no_history"}``.
* ``direction`` (optional str, default ``"horizontal"``): one of
  ``"horizontal"`` / ``"vertical"``. Ignored when ``stride`` is set.
* ``spacing`` (optional float, default ``1.0``): per-cell step along
  the chosen axis. Ignored when ``stride`` is set.
* ``stride`` (optional 2- or 3-tuple/list of floats): per-cell offset
  vector — overrides ``direction`` + ``spacing`` when supplied.

Return contract
---------------

* ``{"status": "batched_row", "card_id": str, "count": N,
   "stride": (dx, dy, dz), "specs": [dict, ...]}`` on success.
* ``{"status": "no_history"}`` — no previous spawn recorded, or
  ``count <= 0``.
* ``{"status": "no_shell"}`` — no shell in ctx and no ``last_spawn``
  override.
* ``{"status": "error", "message": str}`` — one of the ``_on_spawn``
  calls raised. Whatever landed before the error stays landed; the
  ``specs`` list reflects only the successful dispatches.
"""
from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from ._ctx import ensure_ctx
from .spawn_batch_actions import _clamp_int, _get_pos
from .spawn_history_actions import _resolve_last_spawn, record_last_spawn


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


_DIRECTION_UNITS: dict[str, tuple[float, float, float]] = {
    "horizontal": (1.0, 0.0, 0.0),
    "vertical": (0.0, 1.0, 0.0),
}


def _resolve_stride(ctx: dict[str, Any]) -> tuple[float, float, float]:
    """Return the per-cell offset vector.

    ``ctx["stride"]`` wins outright when supplied (2-vec pads Z=0).
    Otherwise derives from ``direction`` + ``spacing``.
    """
    raw = ctx.get("stride")
    if isinstance(raw, (list, tuple)) and len(raw) in (2, 3):
        try:
            vals = [float(v) for v in raw]
        except (TypeError, ValueError):
            vals = None
        if vals is not None:
            if len(vals) == 2:
                return (vals[0], vals[1], 0.0)
            return (vals[0], vals[1], vals[2])

    direction = ctx.get("direction", "horizontal")
    if not isinstance(direction, str):
        direction = "horizontal"
    unit = _DIRECTION_UNITS.get(direction.lower())
    if unit is None:
        unit = _DIRECTION_UNITS["horizontal"]

    spacing_raw = ctx.get("spacing", 1.0)
    if isinstance(spacing_raw, bool):
        spacing = 1.0
    elif isinstance(spacing_raw, (int, float)) and math.isfinite(spacing_raw):
        spacing = float(spacing_raw)
    else:
        spacing = 1.0
    return (unit[0] * spacing, unit[1] * spacing, unit[2] * spacing)


def _shifted_spec(
    template: dict[str, Any],
    offset_xyz: tuple[float, float, float],
) -> dict[str, Any]:
    """Return a deep-copy of *template* with its position shifted."""
    spec = deepcopy(template)
    key, pos = _get_pos(spec)
    if key is not None and pos is not None:
        new_pos = list(pos)
        for i in range(len(new_pos)):
            if i < 3:
                new_pos[i] = pos[i] + offset_xyz[i]
        spec[key] = new_pos
    else:
        spec["position"] = [offset_xyz[0], offset_xyz[1], offset_xyz[2]]
    return spec


def spawn_batch_row(ctx: dict[str, Any]) -> dict[str, Any]:
    """Re-fire the most recent spawn *N* times in a straight row.

    See module docstring for the full ctx / return contract.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("spawn_batch_row", ctx)
    shell = _get_shell(ctx)
    if shell is None and "last_spawn" not in ctx:
        return {"status": "no_shell"}

    raw_count = ctx.get("count", 5)
    if isinstance(raw_count, (int, float)) and raw_count is not None:
        if raw_count is not True and raw_count is not False:
            try:
                if int(raw_count) <= 0:
                    return {"status": "no_history"}
            except (TypeError, ValueError):
                pass

    record = _resolve_last_spawn(ctx)
    if record is None:
        return {"status": "no_history"}
    card_id, template = record

    count = _clamp_int(raw_count, default=5, minimum=1)
    stride = _resolve_stride(ctx)

    on_spawn = None
    if shell is not None:
        candidate = getattr(shell, "_on_spawn", None)
        if callable(candidate):
            on_spawn = candidate

    specs: list[dict[str, Any]] = []
    for i in range(count):
        offset = (stride[0] * i, stride[1] * i, stride[2] * i)
        spec = _shifted_spec(template, offset)
        if on_spawn is not None:
            try:
                on_spawn(card_id, spec)
            except Exception as exc:  # noqa: BLE001
                return {
                    "status": "error",
                    "message": str(exc),
                    "card_id": card_id,
                    "count": len(specs),
                    "stride": stride,
                    "specs": specs,
                }
        specs.append(spec)

    # Update the last-spawn slot to the *final* cell so a subsequent
    # single ``spawn.repeat_last`` continues the row.
    if shell is not None and specs:
        record_last_spawn(shell, card_id, specs[-1])

    return {
        "status": "batched_row",
        "card_id": card_id,
        "count": len(specs),
        "stride": stride,
        "specs": specs,
    }


__all__ = ["spawn_batch_row"]
