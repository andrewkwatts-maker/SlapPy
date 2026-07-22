"""Woodland-creature animation subsystem.

This subpackage owns the entire woodland-creature feature: the
declarative cast members, the keyframe-driven animation curves, the
slot policy that controls *where* a creature lives + *how often* it
may animate, the scheduler that drives the per-frame state machine,
and the event-bus integration that turns engine events into trigger
calls.

See:

* ``docs/idle_animation_system_2026_06_03.md`` — the subsystem spec.
* ``docs/woodland_creature_catalog_2026_06_03.md`` — the cast catalogue.

Public surface (alphabetised, matches ``__all__``):

* :data:`EVENT_TO_CREATURE_ANIMS` — the canonical event→creature
  binding table consumed by :class:`CreatureBusAdapter`.
* :class:`AnimationCurve` + :class:`Keyframe` — keyframe-driven scalar
  curves over a fixed wall-clock duration.
* :class:`Creature` — the declarative cast member (id, render fn,
  animation tables, personality colour, CPU budget hint).
* :class:`CreatureBusAdapter` — subscribes a scheduler to the engine
  event bus per :data:`EVENT_TO_CREATURE_ANIMS`.
* :class:`CreatureScheduler` — owns the active set, drives cooldowns
  and animation phases, dispatches to render fns.
* :class:`IdleEventEmitter` — fires ``engine.idle_60s`` /
  ``engine.idle_120s`` based on accumulated user-inactive time.
* :class:`SlotPolicy` + :class:`SlotRegion` — where a creature lives
  and how often it may animate.
* :func:`register_creature` / :func:`trigger` / :func:`tick` /
  :func:`set_enabled` / :func:`set_reduced_motion` — module-level
  wrappers for callers that want a singleton scheduler without owning
  an instance.

The subpackage carries **no DPG hard dependency** — render fns receive
an opaque ``draw_list`` parameter and the test suite passes a recording
mock. Production wiring lives in the editor host.
"""
from __future__ import annotations

from .animation_curve import AnimationCurve, Keyframe
from .bus_adapter import CreatureBusAdapter
from .creature_base import Creature, DrawList, RenderFn
from .event_bindings import EVENT_TO_CREATURE_ANIMS
from .idle_event_emitter import IdleEventEmitter
from .scheduler import CreatureScheduler
from .slot_policy import SlotPolicy, SlotRegion


# ---------------------------------------------------------------------------
# Module-level singleton wrappers
# ---------------------------------------------------------------------------
#
# The editor wires a single scheduler instance into its main loop. We
# expose module-level functions that operate on a lazily-created
# singleton so call-site code stays terse:
#
#     from pharos_editor.ui.theme.creatures import register_creature, trigger
#     register_creature(fox_01, fox_slot)
#     trigger("fox_01", "wake_up")
#
# Tests use ``CreatureScheduler`` directly (one per test) so the
# singleton stays untouched.


_DEFAULT_SCHEDULER: CreatureScheduler | None = None


def _get_default_scheduler() -> CreatureScheduler:
    global _DEFAULT_SCHEDULER
    if _DEFAULT_SCHEDULER is None:
        _DEFAULT_SCHEDULER = CreatureScheduler()
    return _DEFAULT_SCHEDULER


def register_creature(creature: Creature, slot: SlotPolicy) -> None:
    """Register *creature* on the module-level default scheduler."""
    _get_default_scheduler().register(creature, slot)


def trigger(creature_id: str, anim_name: str) -> bool:
    """Fire a trigger animation on the module-level default scheduler."""
    return _get_default_scheduler().trigger(creature_id, anim_name)


def tick(dt: float) -> None:
    """Advance the module-level default scheduler by *dt* seconds."""
    _get_default_scheduler().tick(dt)


def set_enabled(enabled: bool) -> None:
    """Toggle the master switch on the module-level default scheduler."""
    _get_default_scheduler().set_enabled(enabled)


def set_reduced_motion(reduced: bool) -> None:
    """Toggle reduced-motion mode on the module-level default scheduler."""
    _get_default_scheduler().set_reduced_motion(reduced)


def _reset_default_scheduler_for_tests() -> None:
    """Internal: drop the module-level singleton. Test-only escape hatch."""
    global _DEFAULT_SCHEDULER
    _DEFAULT_SCHEDULER = None


__all__ = [
    "AnimationCurve",
    "Creature",
    "CreatureBusAdapter",
    "CreatureScheduler",
    "DrawList",
    "EVENT_TO_CREATURE_ANIMS",
    "IdleEventEmitter",
    "Keyframe",
    "RenderFn",
    "SlotPolicy",
    "SlotRegion",
    "register_creature",
    "set_enabled",
    "set_reduced_motion",
    "tick",
    "trigger",
]
