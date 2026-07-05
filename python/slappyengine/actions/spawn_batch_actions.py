"""Batch-spawn action — repeat the last spawn N times in a grid.

Backs the ``spawn.repeat_last_batch`` :class:`~slappyengine.tool_router.ToolAction`
row added by the DD1 STUB-triage sprint tick (round 7 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1).

Sibling to
:func:`slappyengine.actions.spawn_history_actions.repeat_last` — same
"last spawn" resolution (``shell._last_spawn`` / spawn-menu slot), but
instead of firing once it lays down an *NxM grid* of copies. Grid stride
is configurable via ``ctx["spacing"]`` (defaults to a 1.0-unit lattice
in each axis) so the copies do not overlap.

Ctx keys
--------

* ``shell`` (optional): editor shell — receives ``_on_spawn`` calls
  and the ``_last_spawn`` retarget on each dispatch. When absent the
  helper returns the spec list so headless callers can drive their own
  dispatch (matches ``paste_selection`` / ``repeat_last`` semantics).
* ``last_spawn`` (optional ``(card_id, spec)``): explicit source
  override — headless tests pass this to skip the shell probe.
* ``count`` (optional int, default ``4``): total copies to lay down.
  Values ``<= 0`` short-circuit with ``{"status": "no_history"}`` so
  the caller can distinguish "no history" from "nothing to do".
* ``columns`` (optional int, default ``ceil(sqrt(count))``): grid
  width. When absent the helper chooses a near-square layout.
* ``spacing`` (optional 2- or 3-tuple/list of floats, default
  ``(1.0, 1.0)``): per-axis step between grid cells. 2-vec applies to
  X/Y; 3-vec applies to X/Y/Z.

Return contract
---------------

* ``{"status": "batched", "card_id": str, "count": N, "specs":
   [dict, ...]}`` — the batch dispatched. When a shell was reachable
  each ``spec`` in the list already reflects the offset it was
  dispatched with.
* ``{"status": "no_history"}`` — no previous spawn recorded (or the
  requested ``count`` was ``<= 0``).
* ``{"status": "no_shell"}`` — no shell in ctx and no ``last_spawn``
  override. Same pattern as ``spawn.repeat_last``.
* ``{"status": "error", "message": str}`` — one of the ``_on_spawn``
  calls raised. Whatever landed before the error stays landed; the
  ``specs`` list reflects only the successful dispatches.
"""
from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from ._ctx import ensure_ctx
from .spawn_history_actions import _resolve_last_spawn, record_last_spawn


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _clamp_int(value: Any, default: int, *, minimum: int = 1) -> int:
    """Return *value* coerced to ``int`` and clamped to ``>= minimum``.

    Falls back to *default* when *value* cannot be interpreted.
    """
    if isinstance(value, bool):
        # Bool is-a int in Python — reject explicitly.
        return default
    if isinstance(value, int):
        return max(minimum, value)
    if isinstance(value, float) and math.isfinite(value):
        return max(minimum, int(value))
    return default


def _resolve_grid(count: int, columns: Any) -> tuple[int, int]:
    """Return ``(cols, rows)`` for a grid holding *count* cells.

    When *columns* is unset, chooses ``ceil(sqrt(count))`` so the grid
    is near-square.
    """
    if isinstance(columns, int) and columns >= 1:
        cols = columns
    else:
        cols = max(1, int(math.ceil(math.sqrt(max(1, count)))))
    rows = int(math.ceil(count / cols))
    return cols, rows


def _resolve_spacing(spacing: Any) -> tuple[float, float, float]:
    """Return a 3-tuple stride; pads a 2-vec with ``0.0`` for Z."""
    if isinstance(spacing, (list, tuple)) and len(spacing) in (2, 3):
        try:
            vals = [float(v) for v in spacing]
        except (TypeError, ValueError):
            vals = [1.0, 1.0]
        if len(vals) == 2:
            return (vals[0], vals[1], 0.0)
        return (vals[0], vals[1], vals[2])
    return (1.0, 1.0, 0.0)


_POS_KEYS = ("position", "origin", "pos")


def _get_pos(spec: dict[str, Any]) -> tuple[str | None, list[float] | None]:
    """Return ``(key, list_pos)`` for whichever position field *spec* uses."""
    for key in _POS_KEYS:
        pos = spec.get(key)
        if isinstance(pos, (list, tuple)) and pos:
            try:
                return key, [float(v) for v in pos]
            except (TypeError, ValueError):
                return None, None
    return None, None


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
            new_pos[i] = pos[i] + offset_xyz[i] if i < 3 else pos[i]
        spec[key] = new_pos
    else:
        # Spec had no positional field — seed one so the grid still
        # spreads. Prefer the historically-most-common "position" key.
        spec["position"] = [offset_xyz[0], offset_xyz[1], offset_xyz[2]]
    return spec


def repeat_last_batch(ctx: dict[str, Any]) -> dict[str, Any]:
    """Re-fire the most recent spawn *N* times in a grid.

    See module docstring for the full ctx / return contract.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("repeat_last_batch", ctx)
    shell = _get_shell(ctx)
    if shell is None and "last_spawn" not in ctx:
        return {"status": "no_shell"}

    # Reject non-positive counts up-front so callers get a stable
    # "no_history"-equivalent status. Zero copies means nothing to lay
    # down; the caller should short-circuit instead of dispatching.
    raw_count = ctx.get("count", 4)
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

    count = _clamp_int(raw_count, default=4, minimum=1)
    cols, _rows = _resolve_grid(count, ctx.get("columns"))
    dx, dy, dz = _resolve_spacing(ctx.get("spacing"))

    on_spawn = None
    if shell is not None:
        candidate = getattr(shell, "_on_spawn", None)
        if callable(candidate):
            on_spawn = candidate

    specs: list[dict[str, Any]] = []
    for i in range(count):
        col = i % cols
        row = i // cols
        offset = (dx * col, dy * row, dz * row)
        spec = _shifted_spec(template, offset)
        if on_spawn is not None:
            try:
                on_spawn(card_id, spec)
            except Exception as exc:  # noqa: BLE001
                # Preserve whatever landed; report the failure.
                return {
                    "status": "error",
                    "message": str(exc),
                    "card_id": card_id,
                    "count": len(specs),
                    "specs": specs,
                }
        specs.append(spec)

    # Update the shell's last-spawn slot to the *final* offset so a
    # subsequent single ``spawn.repeat_last`` continues the grid rather
    # than restarting at the template origin.
    if shell is not None and specs:
        record_last_spawn(shell, card_id, specs[-1])

    return {
        "status": "batched",
        "card_id": card_id,
        "count": len(specs),
        "columns": cols,
        "specs": specs,
    }


__all__ = ["repeat_last_batch"]
