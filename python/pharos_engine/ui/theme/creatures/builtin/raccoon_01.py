"""``raccoon_01`` — Trash Panda property-inspector mascot.

Render strategy: shader fur (grey gradient body) + SVG mask + striped
tail (5 alternating bands).

Animations:

* idle ``ear_perk`` — every 10-20 s; 0.3 s flick.
* idle ``paw_clean`` — every 60-90 s; pretends to wash hands, 1.2 s.
* trigger ``peek_behind`` — fires on property-inspector open; peeks
  from behind the panel over 0.9 s.
"""
from __future__ import annotations

from typing import Any

from ...theme_spec import Color
from ..animation_curve import AnimationCurve, Keyframe
from ..creature_base import Creature
from ..slot_policy import SlotPolicy, SlotRegion


# Grey body + black mask — design spec calls for #A0A8B5.
_RACCOON_GREY = Color(r=0xA0, g=0xA8, b=0xB5, a=1.0)
_RACCOON_DARK = Color(r=0x2A, g=0x2A, b=0x2A, a=1.0)
_RACCOON_CREAM = Color(r=0xE0, g=0xE0, b=0xDC, a=1.0)


# Inline SVG mask — round body + black bandit mask, ~360B.
RACCOON_SVG = """\
<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 48'>
  <ellipse cx='32' cy='30' rx='22' ry='14' fill='#a0a8b5' />
  <circle cx='32' cy='18' r='12' fill='#a0a8b5' />
  <polygon points='22,6 26,14 18,14' fill='#a0a8b5' />
  <polygon points='42,6 38,14 46,14' fill='#a0a8b5' />
  <ellipse cx='26' cy='20' rx='5' ry='3' fill='#2a2a2a' />
  <ellipse cx='38' cy='20' rx='5' ry='3' fill='#2a2a2a' />
  <ellipse cx='32' cy='24' rx='2' ry='1.5' fill='#2a2a2a' />
</svg>"""


def _raccoon_render_fn(draw_list: Any, x: int, y: int, anim_t: float) -> None:
    record = getattr(draw_list, "record", None)
    if record is None:
        return
    pulse = 1.0 - abs(anim_t * 2.0 - 1.0)
    # Fur shader behind SVG.
    record(
        "shader_swatch",
        x=x,
        y=y,
        size=(64, 48),
        name="noise_glitter",
        params={"density": 0.22, "seed": 19,
                "tint": _RACCOON_GREY.as_rgba_tuple()},
    )
    record(
        "svg",
        x=x,
        y=y,
        svg=RACCOON_SVG,
        size=(64, 48),
        color=_RACCOON_GREY.as_rgba_tuple(),
    )
    # Paw clean — small ellipses near the head during peak.
    if pulse > 0.3:
        paw_y = y + 28 - int(round(4 * pulse))
        record(
            "ellipse",
            cx=x + 26,
            cy=paw_y,
            rx=3,
            ry=3,
            color=_RACCOON_GREY.as_rgba_tuple(),
        )
        record(
            "ellipse",
            cx=x + 38,
            cy=paw_y,
            rx=3,
            ry=3,
            color=_RACCOON_GREY.as_rgba_tuple(),
        )
    # Striped tail — 5 alternating bands.
    for i in range(5):
        record(
            "ellipse",
            cx=x + 54 + i * 2,
            cy=y + 36,
            rx=4,
            ry=3,
            color=(_RACCOON_DARK if i % 2 == 0 else _RACCOON_CREAM).as_rgba_tuple(),
        )


def raccoon_01() -> Creature:
    return Creature(
        id="raccoon_01",
        render_fn=_raccoon_render_fn,
        idle_animations={
            "ear_perk": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.5, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=0.3,
            ),
            "paw_clean": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.25, value=1.0),
                    Keyframe(t=0.5, value=0.0),
                    Keyframe(t=0.75, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=1.2,
            ),
        },
        trigger_animations={
            "peek_behind": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.4, value=1.0),
                    Keyframe(t=0.7, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=0.9,
            ),
        },
        personality_color=_RACCOON_GREY,
        budget_ms=0.35,
        metadata={"season": "all", "render_strategy": "svg+shader",
                  "slot_hint": "property_inspector_corner"},
    )


def raccoon_01_slot() -> SlotPolicy:
    """Property inspector corner — 64x48 anchor."""
    return SlotPolicy(
        region=SlotRegion(x=4, y=4, w=64, h=48, parent_panel="property_inspector"),
        idle_cooldown_s=(10.0, 20.0),
        max_concurrent=1,
        reduced_motion_idle_ok=True,
    )


__all__ = ["RACCOON_SVG", "raccoon_01", "raccoon_01_slot"]
