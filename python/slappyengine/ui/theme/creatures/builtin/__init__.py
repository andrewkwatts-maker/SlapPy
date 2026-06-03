"""Built-in creature definitions + a one-call registration helper.

Each creature in this subpackage is a pure-data factory function
returning a fresh :class:`Creature` instance plus a matching
:class:`SlotPolicy`. The :func:`register_builtins` helper wires the
initial roster (fox / butterfly / sparkle) onto a scheduler in one call.

The roster is intentionally small at first — the design doc catalogues
14 creatures but only three are needed to validate the subsystem end
to end. Additional creatures will land as sibling modules without
touching the scheduler core.
"""
from __future__ import annotations

from ..scheduler import CreatureScheduler
from .butterfly import butterfly_01, butterfly_01_slot
from .fox import fox_01, fox_01_slot
from .sparkle import sparkle, sparkle_slot


def register_builtins(scheduler: CreatureScheduler) -> None:
    """Register fox / butterfly / sparkle on *scheduler*.

    Each factory is called fresh so multiple schedulers can be wired up
    without sharing animation state.
    """
    if not isinstance(scheduler, CreatureScheduler):
        raise TypeError(
            "register_builtins: scheduler must be a CreatureScheduler; "
            f"got {type(scheduler).__name__}"
        )
    scheduler.register(fox_01(), fox_01_slot())
    scheduler.register(butterfly_01(), butterfly_01_slot())
    scheduler.register(sparkle(), sparkle_slot())


__all__ = [
    "butterfly_01",
    "butterfly_01_slot",
    "fox_01",
    "fox_01_slot",
    "register_builtins",
    "sparkle",
    "sparkle_slot",
]
