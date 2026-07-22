"""CreatureScheduler — owns active creatures, slot cooldowns, animation state.

The scheduler is the only stateful piece of the creature subsystem.
Each tick it:

1. Decrements every slot's idle cooldown by ``dt``.
2. When a cooldown elapses on a slot, randomly picks one of the
   creature's idle animations and starts it (subject to the
   reduced-motion + master-enabled gates).
3. Advances any in-flight animation curves; retires curves whose
   :meth:`AnimationCurve.is_done` returns ``True``.
4. On :meth:`render` calls each active creature's ``render_fn`` with
   the slot's anchor coordinates and current animation phase.

The contract documented in
``docs/idle_animation_system_2026_06_03.md`` §3 is asserted by
``PharosEngineTests/tests/test_creature_scheduler.py``.

Design notes:

* The scheduler is **not** thread-safe — it is intended to be driven
  from the editor's main loop alongside DPG draw calls.
* :meth:`tick` must be allocation-free on the hot path (no anim active),
  which is why slot bookkeeping uses plain lists and an internal RNG
  rather than ``random.choice``.
* ``set_enabled(False)`` short-circuits ``tick`` after a single branch
  and turns ``render`` into a no-op so the editor pays nothing when the
  feature is off.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any

from pharos_engine._validation import (
    validate_bool,
    validate_finite_float,
    validate_non_empty_str,
)

from .animation_curve import AnimationCurve
from .creature_base import Creature
from .slot_policy import SlotPolicy


_LOG = logging.getLogger(__name__)


# Animation names whitelisted while reduced-motion mode is on. Per §5 of
# the design doc, idle blinks are the only motion that survives.
_REDUCED_MOTION_IDLE_WHITELIST = frozenset({"blink"})


# ---------------------------------------------------------------------------
# Internal active-animation record
# ---------------------------------------------------------------------------


@dataclass
class _ActiveAnim:
    """Single in-flight animation curve attached to a registered creature."""

    creature_id: str
    name: str
    curve: AnimationCurve
    elapsed: float = 0.0
    is_idle: bool = True

    def advance(self, dt: float) -> None:
        self.elapsed += dt

    @property
    def phase(self) -> float:
        """Normalised animation phase in ``[0, 1]``."""
        d = self.curve.duration_s
        if d <= 0.0:
            return 1.0
        e = self.elapsed
        if self.curve.loop:
            e = e % d
        if e <= 0.0:
            return 0.0
        if e >= d:
            return 1.0
        return e / d


# ---------------------------------------------------------------------------
# Internal slot record
# ---------------------------------------------------------------------------


@dataclass
class _SlotRecord:
    creature: Creature
    policy: SlotPolicy
    cooldown_remaining: float = 0.0
    # Live trigger animations only (idle anims live in their own list — they
    # do not count against `max_concurrent`).
    active_triggers: list[_ActiveAnim] = field(default_factory=list)
    active_idle: _ActiveAnim | None = None


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


class CreatureScheduler:
    """Owns the active set of creatures and their per-slot cooldowns.

    Parameters
    ----------
    rng_seed:
        Optional integer seed for the internal RNG. Tests pin this to
        get deterministic idle / cooldown picks.
    """

    def __init__(self, *, rng_seed: int | None = None) -> None:
        self._slots: dict[str, _SlotRecord] = {}
        self._enabled: bool = True
        self._reduced_motion: bool = False
        self._rng: random.Random = random.Random(rng_seed)
        # Counter for diagnostics + a dropped-trigger sink that tests can
        # snoop on without poking at the logger.
        self._dropped_triggers: int = 0
        # Whether trigger() should drop or queue when slot is full. The
        # design doc §3.3 mandates DROP, but we expose the knob for
        # easter-egg slot policies that want to queue (e.g. acorn confetti).
        self._policy_drop_on_full: bool = True

    # ---- Registration -----------------------------------------------------

    def register(self, creature: Creature, slot: SlotPolicy) -> None:
        """Register *creature* under its id with the given *slot* policy.

        Raises
        ------
        TypeError
            If *creature* or *slot* are the wrong type.
        ValueError
            If *creature.id* is already registered.
        """
        fn = "CreatureScheduler.register"
        if not isinstance(creature, Creature):
            raise TypeError(
                f"{fn}: creature must be a Creature; "
                f"got {type(creature).__name__}"
            )
        if not isinstance(slot, SlotPolicy):
            raise TypeError(
                f"{fn}: slot must be a SlotPolicy; got {type(slot).__name__}"
            )
        if creature.id in self._slots:
            raise ValueError(
                f"{fn}: creature {creature.id!r} is already registered"
            )
        rec = _SlotRecord(creature=creature, policy=slot)
        rec.cooldown_remaining = self._pick_cooldown(slot)
        self._slots[creature.id] = rec

    def unregister(self, creature_id: str) -> None:
        """Remove *creature_id* from the scheduler.

        Silently ignores unknown ids — the editor frequently re-applies
        themes and we do not want a transient ``LookupError`` in the
        middle of theme-swap teardown.
        """
        validate_non_empty_str(
            "creature_id", "CreatureScheduler.unregister", creature_id
        )
        self._slots.pop(creature_id, None)

    # ---- Lifecycle --------------------------------------------------------

    def tick(self, dt: float) -> None:
        """Advance scheduler state by *dt* seconds.

        When ``set_enabled(False)`` has been called this short-circuits
        after one branch + zero allocations.
        """
        if not self._enabled:
            return
        dt = validate_finite_float("dt", "CreatureScheduler.tick", dt)
        if dt < 0.0:
            raise ValueError(
                f"CreatureScheduler.tick: dt must be >= 0; got {dt}"
            )
        if dt == 0.0:
            return
        reduced = self._reduced_motion
        for rec in self._slots.values():
            self._tick_slot(rec, dt, reduced)

    def _tick_slot(
        self, rec: _SlotRecord, dt: float, reduced: bool
    ) -> None:
        # Advance active triggers, drop finished ones in-place.
        if rec.active_triggers:
            remaining: list[_ActiveAnim] = []
            for anim in rec.active_triggers:
                anim.advance(dt)
                if not anim.curve.is_done(anim.elapsed):
                    remaining.append(anim)
            rec.active_triggers = remaining
        # Advance active idle.
        if rec.active_idle is not None:
            rec.active_idle.advance(dt)
            if rec.active_idle.curve.is_done(rec.active_idle.elapsed):
                rec.active_idle = None
                rec.cooldown_remaining = self._pick_cooldown(rec.policy)
            return
        # Cooldown countdown — only when no idle is active.
        rec.cooldown_remaining -= dt
        if rec.cooldown_remaining > 0.0:
            return
        # Cooldown elapsed: pick + start an idle anim.
        name = self._pick_idle(rec.creature, reduced, rec.policy)
        if name is None:
            # Reduced motion suppressed every candidate; reset cooldown
            # so we sleep until the next window.
            rec.cooldown_remaining = self._pick_cooldown(rec.policy)
            return
        curve = rec.creature.idle_animations[name]
        rec.active_idle = _ActiveAnim(
            creature_id=rec.creature.id,
            name=name,
            curve=curve,
            elapsed=0.0,
            is_idle=True,
        )

    def trigger(self, creature_id: str, anim_name: str) -> bool:
        """Fire a trigger animation. Returns ``True`` iff the anim started.

        When the master switch is off or the slot's ``max_concurrent``
        is exceeded the call is a no-op and ``False`` is returned. A
        ``DEBUG`` log line records the drop.
        """
        fn = "CreatureScheduler.trigger"
        validate_non_empty_str("creature_id", fn, creature_id)
        validate_non_empty_str("anim_name", fn, anim_name)
        if not self._enabled:
            return False
        rec = self._slots.get(creature_id)
        if rec is None:
            raise LookupError(
                f"{fn}: creature_id {creature_id!r} not registered"
            )
        curve = rec.creature.trigger_animations.get(anim_name)
        if curve is None:
            raise LookupError(
                f"{fn}: trigger animation {anim_name!r} not declared on "
                f"{creature_id!r} (have: "
                f"{sorted(rec.creature.trigger_animations)})"
            )
        if len(rec.active_triggers) >= rec.policy.max_concurrent:
            self._dropped_triggers += 1
            _LOG.debug(
                "trigger dropped: %s/%s (slot full, %d active, max %d)",
                creature_id,
                anim_name,
                len(rec.active_triggers),
                rec.policy.max_concurrent,
            )
            return False
        if self._reduced_motion:
            # Reduced-motion §5: trigger anims still play but degenerate
            # to a static reveal — we record the curve so render gets a
            # phase, but we collapse phase to 1.0 immediately by setting
            # elapsed past the duration. is_done is checked next tick.
            anim = _ActiveAnim(
                creature_id=creature_id,
                name=anim_name,
                curve=curve,
                elapsed=curve.duration_s,
                is_idle=False,
            )
        else:
            anim = _ActiveAnim(
                creature_id=creature_id,
                name=anim_name,
                curve=curve,
                elapsed=0.0,
                is_idle=False,
            )
        rec.active_triggers.append(anim)
        return True

    def render(self, draw_list: Any) -> None:
        """Render every active creature into *draw_list*.

        ``draw_list`` is renderer-defined — production passes a Dear PyGui
        drawlist handle; tests pass a recording mock.
        """
        if not self._enabled:
            return
        for rec in self._slots.values():
            x = rec.policy.region.x
            y = rec.policy.region.y
            # Idle anims render at their current phase.
            if rec.active_idle is not None:
                rec.creature.render_fn(
                    draw_list, x, y, rec.active_idle.phase
                )
            elif rec.active_triggers:
                # If only triggers, render at the most recent trigger's
                # phase (one creature, one image at a time).
                rec.creature.render_fn(
                    draw_list, x, y, rec.active_triggers[-1].phase
                )
            else:
                # Dormant: emit a static frame at phase 0.
                rec.creature.render_fn(draw_list, x, y, 0.0)

    # ---- Master switches --------------------------------------------------

    def set_enabled(self, enabled: bool) -> None:
        """Toggle the master switch (default: ``True``).

        ``False`` makes :meth:`tick`, :meth:`trigger`, and :meth:`render`
        all no-ops — slot/creature registrations are preserved.
        """
        self._enabled = validate_bool(
            "enabled", "CreatureScheduler.set_enabled", enabled
        )

    def set_reduced_motion(self, reduced: bool) -> None:
        """Toggle reduced-motion mode (default: ``False``).

        When ``True``, only ``blink`` idle animations may fire and
        trigger animations degenerate to a static reveal (phase pinned
        at ``1.0``). See §5 of the design doc.
        """
        self._reduced_motion = validate_bool(
            "reduced", "CreatureScheduler.set_reduced_motion", reduced
        )

    # ---- Diagnostics ------------------------------------------------------

    @property
    def active_count(self) -> int:
        """Number of registered creatures currently mid-animation."""
        n = 0
        for rec in self._slots.values():
            if rec.active_idle is not None or rec.active_triggers:
                n += 1
        return n

    @property
    def total_budget_ms(self) -> float:
        """Sum of every registered creature's advisory CPU budget."""
        return sum(rec.creature.budget_ms for rec in self._slots.values())

    @property
    def registered_ids(self) -> list[str]:
        """Sorted list of registered creature ids."""
        return sorted(self._slots)

    @property
    def dropped_trigger_count(self) -> int:
        """Number of ``trigger`` calls dropped due to slot saturation."""
        return self._dropped_triggers

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def is_reduced_motion(self) -> bool:
        return self._reduced_motion

    # ---- Internal helpers -------------------------------------------------

    def _pick_cooldown(self, slot: SlotPolicy) -> float:
        lo, hi = slot.idle_cooldown_s
        if lo == hi:
            return lo
        return self._rng.uniform(lo, hi)

    def _pick_idle(
        self,
        creature: Creature,
        reduced: bool,
        slot: SlotPolicy,
    ) -> str | None:
        names = list(creature.idle_animations)
        if not names:
            return None
        if reduced:
            if not slot.reduced_motion_idle_ok:
                return None
            allowed = [n for n in names if n in _REDUCED_MOTION_IDLE_WHITELIST]
            if not allowed:
                return None
            return self._rng.choice(allowed)
        return self._rng.choice(names)


__all__ = ["CreatureScheduler"]
