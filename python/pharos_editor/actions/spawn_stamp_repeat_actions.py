"""Spawn stamp-repeat action — hold-to-stamp spawn with N repeats.

Backs the ``spawn.stamp_repeat``
:class:`~pharos_editor.tool_router.ToolAction` row added by the SS1
STUB-triage sprint tick (round 20).

Distinct from II5's ``spawn.spawn_batch_row`` (straight-line row of N
copies) and CC1's ``spawn.repeat_last`` (single one-shot repeat):

* ``spawn.repeat_last`` fires the most-recent spawn **once** at the
  same slot.
* ``spawn.spawn_batch_row`` fires N copies along a straight line with a
  constant per-cell stride.
* ``spawn.stamp_repeat`` is the "hold-and-stamp" variant every
  tile-editor ships — user holds the mouse button while dragging, and
  each Nth pixel a new copy of the last spawn is stamped. This helper
  emulates the *headless* equivalent: given a start point and an end
  point (or a stride + count), lay down copies at every step.

The difference from ``spawn_batch_row`` is *interactivity intent*: the
stamp variant honours an optional ``jitter`` per-axis (mimicking mouse
tremor), and the copies are recorded on ``shell._stamp_history`` (a
separate slot from ``_last_spawn`` so a subsequent Undo can rewind the
whole stamp sequence as one atomic operation).

Ctx keys
--------

* ``shell`` (optional): editor shell.
* ``last_spawn`` (optional ``(card_id, spec)``): explicit source.
* ``count`` (optional int, default ``3``): number of stamps to lay.
* ``stride`` (optional 2- or 3-tuple/list of floats): per-stamp offset.
  Defaults to ``(1.0, 0.0, 0.0)``.
* ``jitter`` (optional 2- or 3-tuple of floats): per-stamp uniform
  jitter magnitude added to each axis (defaults to zero). Uses a
  deterministic PRNG seeded on ``ctx["seed"]`` when supplied so tests
  can pin the outcome.
* ``seed`` (optional int): PRNG seed for jitter reproducibility.

Return contract
---------------

* ``{"status": "stamped", "card_id": str, "count": N,
   "stride": (dx, dy, dz), "specs": [dict, ...]}`` on success.
* ``{"status": "no_history"}`` — no previous spawn recorded (or
  ``count <= 0``).
* ``{"status": "no_shell"}`` — no shell in ``ctx`` and no
  ``last_spawn`` override.
* ``{"status": "error", "message": str}`` — one of the ``_on_spawn``
  calls raised.
"""
from __future__ import annotations

import math
import random
from copy import deepcopy
from typing import Any

from ._ctx import ensure_ctx
from .spawn_batch_actions import _clamp_int, _get_pos
from .spawn_batch_row_actions import _shifted_spec
from .spawn_history_actions import _resolve_last_spawn


_STAMP_HISTORY_ATTR = "_stamp_history"


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _resolve_stride(ctx: dict[str, Any]) -> tuple[float, float, float]:
    """Return the per-stamp offset vector.

    Falls back to ``(1.0, 0.0, 0.0)`` when nothing usable is supplied.
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
    return (1.0, 0.0, 0.0)


def _resolve_jitter(ctx: dict[str, Any]) -> tuple[float, float, float]:
    raw = ctx.get("jitter")
    if not isinstance(raw, (list, tuple)) or len(raw) not in (2, 3):
        return (0.0, 0.0, 0.0)
    try:
        vals = [float(v) for v in raw]
    except (TypeError, ValueError):
        return (0.0, 0.0, 0.0)
    if len(vals) == 2:
        return (vals[0], vals[1], 0.0)
    return (vals[0], vals[1], vals[2])


def _resolve_rng(ctx: dict[str, Any]) -> random.Random:
    """Return a :class:`~random.Random` instance.

    When ``ctx["seed"]`` is a finite number a deterministic PRNG is
    returned; otherwise a fresh :class:`random.Random()` with system
    entropy is used.
    """
    seed = ctx.get("seed")
    if isinstance(seed, (int, float)) and not isinstance(seed, bool):
        try:
            if math.isfinite(float(seed)):
                return random.Random(int(seed))
        except (TypeError, ValueError):
            pass
    return random.Random()


def stamp_repeat(ctx: dict[str, Any]) -> dict[str, Any]:
    """Fire N copies of the most recent spawn along ``stride``.

    See module docstring for the full ctx / return contract.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("stamp_repeat", ctx)
    shell = _get_shell(ctx)
    if shell is None and "last_spawn" not in ctx:
        return {"status": "no_shell"}

    raw_count = ctx.get("count", 3)
    if isinstance(raw_count, (int, float)) and not isinstance(raw_count, bool):
        try:
            if int(raw_count) <= 0:
                return {"status": "no_history"}
        except (TypeError, ValueError):
            pass

    record = _resolve_last_spawn(ctx)
    if record is None:
        return {"status": "no_history"}
    card_id, template = record

    count = _clamp_int(raw_count, default=3, minimum=1)
    stride = _resolve_stride(ctx)
    jitter = _resolve_jitter(ctx)
    rng = _resolve_rng(ctx)

    on_spawn = None
    if shell is not None:
        candidate = getattr(shell, "_on_spawn", None)
        if callable(candidate):
            on_spawn = candidate

    specs: list[dict[str, Any]] = []
    for i in range(count):
        offset = (
            stride[0] * i + (rng.uniform(-jitter[0], jitter[0]) if jitter[0] else 0.0),
            stride[1] * i + (rng.uniform(-jitter[1], jitter[1]) if jitter[1] else 0.0),
            stride[2] * i + (rng.uniform(-jitter[2], jitter[2]) if jitter[2] else 0.0),
        )
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

    if shell is not None and specs:
        try:
            existing = getattr(shell, _STAMP_HISTORY_ATTR, None)
            if not isinstance(existing, list):
                existing = []
            existing.append({
                "card_id": card_id,
                "count": len(specs),
                "specs": list(specs),
            })
            setattr(shell, _STAMP_HISTORY_ATTR, existing)
        except Exception:  # noqa: BLE001
            pass

    return {
        "status": "stamped",
        "card_id": card_id,
        "count": len(specs),
        "stride": stride,
        "specs": specs,
    }


__all__ = ["stamp_repeat"]
