"""Creature dataclass — declarative cast member for the scheduler.

A :class:`Creature` is pure data: an id, a render callback, two
animation tables (idle vs trigger), a personality colour, and a
per-frame CPU budget hint. The scheduler holds the behavioural state;
the creature carries the declarative shape only.

The ``render_fn`` signature is::

    render_fn(draw_list, x, y, anim_t) -> None

where ``draw_list`` is any object (typically a DPG drawlist handle in
production, a recording mock in tests), ``x`` / ``y`` is the top-left
of the slot region in screen-space pixels, and ``anim_t`` is the
normalised animation phase in ``[0.0, 1.0]``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from slappyengine._validation import (
    validate_callable,
    validate_non_empty_str,
    validate_positive_float,
)

from ..theme_spec import Color
from .animation_curve import AnimationCurve


# A draw list is renderer-defined; we only require Python's "object" type.
# Tests pass a recording mock; production passes a DPG drawlist id (int).
DrawList = Any
RenderFn = Callable[[DrawList, int, int, float], None]


@dataclass
class Creature:
    """Declarative creature record.

    Pure data — no rendering state. Behaviour belongs to
    :class:`~slappyengine.ui.theme.creatures.scheduler.CreatureScheduler`.

    Parameters
    ----------
    id:
        Stable identifier (e.g. ``"fox_01"``). Used as the registry key.
    render_fn:
        ``(draw_list, x, y, anim_t) -> None`` callback. *anim_t* is the
        normalised animation time in ``[0.0, 1.0]``.
    idle_animations:
        Mapping of animation name → :class:`AnimationCurve`. The
        scheduler picks one of these uniformly at random whenever the
        slot cooldown elapses.
    trigger_animations:
        Mapping of animation name → :class:`AnimationCurve` fired by
        :meth:`CreatureScheduler.trigger`.
    personality_color:
        Tint hint surfaced to render-fn implementations through the
        creature object itself; the scheduler does not interpret it.
    budget_ms:
        Per-frame CPU budget hint in milliseconds. Purely advisory —
        the scheduler reports the aggregate via
        :attr:`CreatureScheduler.total_budget_ms`.
    metadata:
        Free-form string-keyed string-valued tag bag (season variant,
        atlas key, accessibility class, …).
    """

    id: str
    render_fn: RenderFn
    idle_animations: dict[str, AnimationCurve] = field(default_factory=dict)
    trigger_animations: dict[str, AnimationCurve] = field(default_factory=dict)
    personality_color: Color = field(default_factory=lambda: Color(255, 255, 255, 1.0))
    budget_ms: float = 1.0
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        fn = "Creature"
        self.id = validate_non_empty_str("id", fn, self.id)
        self.render_fn = validate_callable("render_fn", fn, self.render_fn)
        for bag_name, bag in (
            ("idle_animations", self.idle_animations),
            ("trigger_animations", self.trigger_animations),
        ):
            if not isinstance(bag, dict):
                raise TypeError(
                    f"{fn}: {bag_name} must be a dict; got {type(bag).__name__}"
                )
            for key, value in bag.items():
                validate_non_empty_str(f"{bag_name} key", fn, key)
                if not isinstance(value, AnimationCurve):
                    raise TypeError(
                        f"{fn}: {bag_name}[{key!r}] must be an AnimationCurve; "
                        f"got {type(value).__name__}"
                    )
        if not isinstance(self.personality_color, Color):
            raise TypeError(
                f"{fn}: personality_color must be a Color; "
                f"got {type(self.personality_color).__name__}"
            )
        self.budget_ms = validate_positive_float("budget_ms", fn, self.budget_ms)
        if not isinstance(self.metadata, dict):
            raise TypeError(
                f"{fn}: metadata must be a dict; "
                f"got {type(self.metadata).__name__}"
            )
        for key, value in self.metadata.items():
            validate_non_empty_str("metadata key", fn, key)
            if not isinstance(value, str):
                raise TypeError(
                    f"{fn}: metadata[{key!r}] must be a str; "
                    f"got {type(value).__name__}"
                )


__all__ = ["Creature", "DrawList", "RenderFn"]
