"""``panda_01`` — Bamboo Panda scene-outliner mascot.

Render strategy: SVG body shape (rounded) + black ear / eye / limb
patches. White + black palette only.

Animations:

* idle ``chew`` — every 8-12 s; jaw moves over 0.6 s.
* idle ``sit_swap`` — rare 60-120 s; weight-shift, 1.4 s.
* trigger ``bamboo_drop`` — fires on user-requested events; creates a
  decorative leaf on the active panel border, 1.0 s.
"""
from __future__ import annotations

from typing import Any

from ...theme_spec import Color
from ..animation_curve import AnimationCurve, Keyframe
from ..creature_base import Creature
from ..slot_policy import SlotPolicy, SlotRegion


# White body + black patches — design spec calls for #FAFAFA / #1F1F1F.
_PANDA_WHITE = Color(r=0xFA, g=0xFA, b=0xFA, a=1.0)
_PANDA_BLACK = Color(r=0x1F, g=0x1F, b=0x1F, a=1.0)
_LEAF_GREEN = Color(r=0x6F, g=0xB4, b=0x55, a=1.0)


# Inline SVG — rounded body + ear/eye/limb patches; W=#fafafa B=#1f1f1f.
PANDA_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
    "<ellipse cx='32' cy='44' rx='22' ry='16' fill='#fafafa'/>"
    "<circle cx='32' cy='22' r='16' fill='#fafafa'/>"
    "<circle cx='20' cy='10' r='6' fill='#1f1f1f'/>"
    "<circle cx='44' cy='10' r='6' fill='#1f1f1f'/>"
    "<ellipse cx='26' cy='22' rx='3' ry='5' fill='#1f1f1f'/>"
    "<ellipse cx='38' cy='22' rx='3' ry='5' fill='#1f1f1f'/>"
    "<ellipse cx='14' cy='52' rx='6' ry='8' fill='#1f1f1f'/>"
    "<ellipse cx='50' cy='52' rx='6' ry='8' fill='#1f1f1f'/>"
    "</svg>"
)


def _panda_render_fn(draw_list: Any, x: int, y: int, anim_t: float) -> None:
    record = getattr(draw_list, "record", None)
    if record is None:
        return
    pulse = 1.0 - abs(anim_t * 2.0 - 1.0)
    record(
        "svg",
        x=x,
        y=y,
        svg=PANDA_SVG,
        size=(64, 64),
        color=_PANDA_WHITE.as_rgba_tuple(),
    )
    # Chew — jaw shape opens.
    jaw_h = max(1, int(round(3 * pulse)))
    record(
        "ellipse",
        cx=x + 32,
        cy=y + 34,
        rx=4,
        ry=jaw_h,
        color=_PANDA_BLACK.as_rgba_tuple(),
    )
    # Bamboo leaf drop — visible during trigger peak.
    if pulse > 0.5:
        record(
            "ellipse",
            cx=x + 56,
            cy=y + 8,
            rx=5,
            ry=2,
            color=_LEAF_GREEN.as_rgba_tuple(),
        )


def panda_01() -> Creature:
    return Creature(
        id="panda_01",
        render_fn=_panda_render_fn,
        idle_animations={
            "chew": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.25, value=1.0),
                    Keyframe(t=0.5, value=0.0),
                    Keyframe(t=0.75, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=0.6,
            ),
            "sit_swap": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.5, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=1.4,
            ),
        },
        trigger_animations={
            "bamboo_drop": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.4, value=1.0),
                    Keyframe(t=0.7, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=1.0,
            ),
        },
        personality_color=_PANDA_WHITE,
        budget_ms=0.3,
        metadata={"season": "all", "render_strategy": "svg",
                  "slot_hint": "scene_outliner_header"},
    )


def panda_01_slot() -> SlotPolicy:
    """Scene outliner header — 64x64 anchor."""
    return SlotPolicy(
        region=SlotRegion(x=8, y=4, w=64, h=64, parent_panel="scene_outliner"),
        idle_cooldown_s=(8.0, 14.0),
        max_concurrent=1,
        reduced_motion_idle_ok=True,
    )


__all__ = ["PANDA_SVG", "panda_01", "panda_01_slot"]
