"""Spawn stamp-random action — hold-to-stamp with random card selection.

Backs the ``spawn.stamp_random``
:class:`~slappyengine.tool_router.ToolAction` row added by the TT2
STUB-triage sprint tick (round 21).

Third variant in the spawn-stamp family, distinct from every sibling:

* ``spawn.repeat_last`` (CC1) — fires the *last* spawn once at its
  original slot.
* ``spawn.spawn_batch_row`` (II5) — N deterministic copies along a
  straight line, always the same card.
* ``spawn.stamp_repeat`` (SS1) — N copies of the *last* card along a
  stride with optional jitter.
* ``spawn.stamp_random`` (TT2 — this module) — N copies where each
  copy's *card_id + spec* is drawn uniformly at random from the shell's
  ``_stamp_history`` (or a caller-supplied ``palette``). Retro
  tile-editors and DCC scatter tools ship this variant so a single
  drag paints a mixed cluster (Aseprite's palette scatter, Blender's
  Object → Scatter, Nova3D's Terrain → Randomised Prop Brush).

Palette resolution
------------------

1. ``ctx["palette"]`` — explicit list of ``(card_id, spec)`` tuples.
   Highest priority; tests use this.
2. ``shell._stamp_history`` — each entry contributes
   ``[(entry["card_id"], spec) for spec in entry["specs"]]``, matching
   the format ``spawn.stamp_repeat`` writes.
3. ``shell._last_spawn`` — degenerate 1-item palette (identical to
   ``spawn.stamp_repeat`` fired against the same seed).

Every draw is a fresh :class:`random.Random` roll — pass ``ctx["seed"]``
for reproducibility. When the palette contains a single entry, the
result is behaviourally identical to ``spawn.stamp_repeat``.

Ctx keys
--------

* ``shell`` (optional): editor shell providing ``_on_spawn`` +
  ``_stamp_history`` fallback + last-spawn fallback.
* ``palette`` (optional list[(card_id, spec)]): explicit selection pool.
* ``count`` (optional int, default ``3``): number of stamps to lay.
* ``stride`` (optional 2/3-vec): per-stamp offset, default
  ``(1.0, 0.0, 0.0)``.
* ``seed`` (optional int): PRNG seed for reproducible random draws.

Return contract
---------------

* ``{"status": "stamped", "count": N, "stride": (dx, dy, dz),
   "picks": [(card_id, spec_dict), ...]}`` on success.
* ``{"status": "no_history"}`` — no palette resolvable (empty
   ``_stamp_history`` and no ``_last_spawn``).
* ``{"status": "no_shell"}`` — no shell in ``ctx`` and no ``palette``
   override.
* ``{"status": "error", "message": str}`` — one of the ``_on_spawn``
   calls raised.
"""
from __future__ import annotations

import math
import random
from copy import deepcopy
from typing import Any

from ._ctx import ensure_ctx
from .spawn_batch_actions import _clamp_int
from .spawn_batch_row_actions import _shifted_spec
from .spawn_history_actions import _resolve_last_spawn


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _resolve_stride(ctx: dict[str, Any]) -> tuple[float, float, float]:
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


def _resolve_rng(ctx: dict[str, Any]) -> random.Random:
    seed = ctx.get("seed")
    if isinstance(seed, (int, float)) and not isinstance(seed, bool):
        try:
            if math.isfinite(float(seed)):
                return random.Random(int(seed))
        except (TypeError, ValueError):
            pass
    return random.Random()


def _coerce_palette_entry(entry: Any) -> tuple[str, dict[str, Any]] | None:
    """Return a normalised ``(card_id, spec)`` tuple, or None on failure."""
    if not isinstance(entry, tuple) or len(entry) != 2:
        return None
    card_id, spec = entry
    if not isinstance(card_id, str) or not card_id:
        return None
    if not isinstance(spec, dict):
        return None
    return (card_id, dict(spec))


def _resolve_palette(
    ctx: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    """Return the ordered palette of ``(card_id, spec)`` candidates.

    Empty when no source is reachable — the caller returns
    ``no_history`` in that case.
    """
    palette: list[tuple[str, dict[str, Any]]] = []
    override = ctx.get("palette")
    if isinstance(override, (list, tuple)):
        for entry in override:
            got = _coerce_palette_entry(tuple(entry) if isinstance(entry, list) else entry)
            if got is not None:
                palette.append(got)
        if palette:
            return palette

    shell = _get_shell(ctx)
    if shell is not None:
        history = getattr(shell, "_stamp_history", None)
        if isinstance(history, list):
            for entry in history:
                if not isinstance(entry, dict):
                    continue
                card_id = entry.get("card_id")
                specs = entry.get("specs")
                if not isinstance(card_id, str) or not card_id:
                    continue
                if not isinstance(specs, list):
                    continue
                for spec in specs:
                    if isinstance(spec, dict):
                        palette.append((card_id, dict(spec)))
        if palette:
            return palette

    record = _resolve_last_spawn(ctx)
    if record is not None:
        card_id, spec = record
        palette.append((card_id, spec))
    return palette


def stamp_random(ctx: dict[str, Any]) -> dict[str, Any]:
    """Fire N copies with card / spec drawn uniformly from the palette.

    See module docstring for the full ctx / return contract.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("stamp_random", ctx)
    shell = _get_shell(ctx)
    if shell is None and "palette" not in ctx and "last_spawn" not in ctx:
        return {"status": "no_shell"}

    raw_count = ctx.get("count", 3)
    if isinstance(raw_count, (int, float)) and not isinstance(raw_count, bool):
        try:
            if int(raw_count) <= 0:
                return {"status": "no_history"}
        except (TypeError, ValueError):
            pass

    palette = _resolve_palette(ctx)
    if not palette:
        return {"status": "no_history"}

    count = _clamp_int(raw_count, default=3, minimum=1)
    stride = _resolve_stride(ctx)
    rng = _resolve_rng(ctx)

    on_spawn = None
    if shell is not None:
        candidate = getattr(shell, "_on_spawn", None)
        if callable(candidate):
            on_spawn = candidate

    picks: list[tuple[str, dict[str, Any]]] = []
    for i in range(count):
        card_id, template = rng.choice(palette)
        offset = (stride[0] * i, stride[1] * i, stride[2] * i)
        spec = _shifted_spec(template, offset)
        if on_spawn is not None:
            try:
                on_spawn(card_id, spec)
            except Exception as exc:  # noqa: BLE001
                return {
                    "status": "error",
                    "message": str(exc),
                    "count": len(picks),
                    "stride": stride,
                    "picks": picks,
                }
        picks.append((card_id, spec))

    return {
        "status": "stamped",
        "count": len(picks),
        "stride": stride,
        "picks": picks,
    }


__all__ = ["stamp_random"]
