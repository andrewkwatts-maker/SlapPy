"""``golden_01`` — Goofy Golden Retriever toolbar mascot.

Render strategy: shader-soft-fur body via ``noise_glitter`` for the
fluffy texture + SVG outline + tongue detail. Lives in the empty
bottom-right toolbar pocket.

Animations:

* idle ``tail_wag`` — continuous 0.5 s loop (fast, joyful wag).
* idle ``ear_flop`` — rare 30-60 s; ears bounce.
* idle ``pant`` — every 20-40 s; tongue out + jaw cycle, 0.6 s.
* trigger ``tail_celebrate`` — on ``engine.build_success``; the wag
  doubles speed and the body gives a tiny upward hop, 1.6 s.
"""
from __future__ import annotations

from typing import Any

from ...theme_spec import Color
from ..animation_curve import AnimationCurve, Keyframe
from ..creature_base import Creature
from ..slot_policy import SlotPolicy, SlotRegion


# Honey-yellow — design spec calls for #E8C16F.
_GOLDEN_BODY = Color(r=0xE8, g=0xC1, b=0x6F, a=1.0)
_GOLDEN_TONGUE = Color(r=0xF0, g=0x70, b=0x80, a=1.0)


# Inline SVG body outline — sitting golden retriever silhouette, ~340B.
GOLDEN_SVG = """\
<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>
  <ellipse cx='32' cy='44' rx='22' ry='14' fill='#e8c16f' />
  <circle cx='44' cy='28' r='14' fill='#e8c16f' />
  <ellipse cx='38' cy='20' rx='5' ry='9' fill='#c89a55' />
  <ellipse cx='50' cy='20' rx='5' ry='9' fill='#c89a55' />
  <ellipse cx='46' cy='34' rx='2' ry='2' fill='#222' />
</svg>"""


def _golden_render_fn(draw_list: Any, x: int, y: int, anim_t: float) -> None:
    record = getattr(draw_list, "record", None)
    if record is None:
        return
    pulse = 1.0 - abs(anim_t * 2.0 - 1.0)
    # Body bobs slightly with hop trigger / tail wag.
    bob = int(round(-2 * pulse))
    # Fluffy soft-fur shader behind the SVG.
    record(
        "shader_swatch",
        x=x,
        y=y + bob,
        size=(64, 64),
        name="noise_glitter",
        params={"density": 0.32, "seed": 14,
                "tint": _GOLDEN_BODY.as_rgba_tuple()},
    )
    record(
        "svg",
        x=x,
        y=y + bob,
        svg=GOLDEN_SVG,
        size=(64, 64),
        color=_GOLDEN_BODY.as_rgba_tuple(),
    )
    # Wagging tail — ellipse whose cx swings.
    tail_dx = int(round(6 * (anim_t * 2.0 - 1.0)))
    record(
        "ellipse",
        cx=x + 10 + tail_dx,
        cy=y + 36,
        rx=8,
        ry=4,
        color=_GOLDEN_BODY.as_rgba_tuple(),
    )
    # Tongue — visible during pant peak.
    if pulse > 0.4:
        record(
            "ellipse",
            cx=x + 46,
            cy=y + 38,
            rx=3,
            ry=max(1, int(round(4 * pulse))),
            color=_GOLDEN_TONGUE.as_rgba_tuple(),
        )


def golden_01() -> Creature:
    return Creature(
        id="golden_01",
        render_fn=_golden_render_fn,
        idle_animations={
            "tail_wag": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.5, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=0.5,
                loop=True,
            ),
            "ear_flop": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.4, value=1.0),
                    Keyframe(t=0.6, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=0.7,
            ),
            "pant": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.5, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=0.6,
            ),
        },
        trigger_animations={
            "tail_celebrate": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.25, value=1.0),
                    Keyframe(t=0.5, value=0.0),
                    Keyframe(t=0.75, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=1.6,
            ),
        },
        personality_color=_GOLDEN_BODY,
        budget_ms=0.4,
        metadata={"season": "all", "render_strategy": "svg+shader",
                  "slot_hint": "toolbar_pocket"},
    )


def golden_01_slot() -> SlotPolicy:
    """Bottom-right toolbar pocket — 64x64 anchor."""
    return SlotPolicy(
        region=SlotRegion(x=900, y=8, w=64, h=64, parent_panel="toolbar"),
        idle_cooldown_s=(20.0, 40.0),
        max_concurrent=1,
        reduced_motion_idle_ok=True,
    )


__all__ = ["GOLDEN_SVG", "golden_01", "golden_01_slot"]
