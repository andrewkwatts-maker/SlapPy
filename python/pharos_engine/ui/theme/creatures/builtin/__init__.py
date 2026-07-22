"""Built-in creature definitions + a one-call registration helper.

Each creature in this subpackage is a pure-data factory function
returning a fresh :class:`Creature` instance plus a matching
:class:`SlotPolicy`. The :func:`register_builtins` helper wires the
full roster onto a scheduler in one call.

The roster now covers the U3 seed trio (fox / butterfly / sparkle)
plus 8 cuddly species from the theme-diary family catalog: tabby cat,
golden retriever, red panda, raccoon, panda, porcupine, hedgehog, and
a Save Butterfly variant. Additional creatures land as sibling modules
without touching the scheduler core.
"""
from __future__ import annotations

from ..scheduler import CreatureScheduler
from .butterfly import butterfly_01, butterfly_01_slot
from .butterfly_02 import butterfly_02, butterfly_02_slot
from .cat_01 import cat_01, cat_01_slot
from .fox import fox_01, fox_01_slot
from .golden_01 import golden_01, golden_01_slot
from .hedgehog_01 import hedgehog_01, hedgehog_01_slot
from .panda_01 import panda_01, panda_01_slot
from .porcupine_01 import porcupine_01, porcupine_01_slot
from .raccoon_01 import raccoon_01, raccoon_01_slot
from .red_panda_01 import red_panda_01, red_panda_01_slot
from .sparkle import sparkle, sparkle_slot


def register_builtins(scheduler: CreatureScheduler) -> None:
    """Register the full built-in creature roster on *scheduler*.

    Each factory is called fresh so multiple schedulers can be wired up
    without sharing animation state. The order below is the order the
    creatures land in the scheduler's registry — stable for tests.
    """
    if not isinstance(scheduler, CreatureScheduler):
        raise TypeError(
            "register_builtins: scheduler must be a CreatureScheduler; "
            f"got {type(scheduler).__name__}"
        )
    scheduler.register(fox_01(), fox_01_slot())
    scheduler.register(butterfly_01(), butterfly_01_slot())
    scheduler.register(sparkle(), sparkle_slot())
    scheduler.register(cat_01(), cat_01_slot())
    scheduler.register(golden_01(), golden_01_slot())
    scheduler.register(red_panda_01(), red_panda_01_slot())
    scheduler.register(raccoon_01(), raccoon_01_slot())
    scheduler.register(panda_01(), panda_01_slot())
    scheduler.register(porcupine_01(), porcupine_01_slot())
    scheduler.register(hedgehog_01(), hedgehog_01_slot())
    scheduler.register(butterfly_02(), butterfly_02_slot())


__all__ = [
    "butterfly_01",
    "butterfly_01_slot",
    "butterfly_02",
    "butterfly_02_slot",
    "cat_01",
    "cat_01_slot",
    "fox_01",
    "fox_01_slot",
    "golden_01",
    "golden_01_slot",
    "hedgehog_01",
    "hedgehog_01_slot",
    "panda_01",
    "panda_01_slot",
    "porcupine_01",
    "porcupine_01_slot",
    "raccoon_01",
    "raccoon_01_slot",
    "red_panda_01",
    "red_panda_01_slot",
    "register_builtins",
    "sparkle",
    "sparkle_slot",
]
