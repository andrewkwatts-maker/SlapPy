"""``cat_01`` — Sleepy Tabby window-edge mascot.

Render strategy: SVG body outline + shader-noise stripe overlay. The
tabby curls up on a title-bar / panel edge; the slot policy anchors a
48x32 region at the active panel top. The noise overlay reuses the
``noise_glitter`` shader baked once by the theme apply step.

Animations:

* idle ``breathe`` — continuous 4 s loop, ±2 % scale ripple.
* idle ``blink`` — every 4-8 s; eyelid descent over 0.2 s.
* idle ``stretch`` — rare 60-90 s; full body elongation 1.5 s.
* idle ``tail_flick`` — rare 30-50 s; tail tip arcs in 0.8 s.
* trigger ``stretch_full`` — fires on mouse-hover near the sleeping
  spot. The host wires the hover event to ``trigger("cat_01",
  "stretch_full")``.
"""
from __future__ import annotations

from typing import Any

from ...theme_spec import Color
from ..animation_curve import AnimationCurve, Keyframe
from ..creature_base import Creature
from ..slot_policy import SlotPolicy, SlotRegion


# Warm orange-cream — design spec calls for #E8A87C.
_TABBY_BODY = Color(r=0xE8, g=0xA8, b=0x7C, a=1.0)
_TABBY_STRIPE = Color(r=0xA6, g=0x6F, b=0x4A, a=1.0)


# Inline SVG body outline (curled-up tabby), ~360 bytes.
CAT_SVG = """\
<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 48 32'>
  <ellipse cx='24' cy='22' rx='22' ry='9' fill='#e8a87c' />
  <circle cx='10' cy='18' r='7' fill='#e8a87c' />
  <polygon points='6,12 9,16 4,16' fill='#e8a87c' />
  <polygon points='14,12 17,16 12,16' fill='#e8a87c' />
  <path d='M44 22 Q50 16 46 14' stroke='#e8a87c' stroke-width='4' fill='none' />
</svg>"""


def _cat_render_fn(draw_list: Any, x: int, y: int, anim_t: float) -> None:
    record = getattr(draw_list, "record", None)
    if record is None:
        return
    # Symmetric pulse 0..1..0 drives breathe/stretch scale.
    pulse = 1.0 - abs(anim_t * 2.0 - 1.0)
    scale = 0.98 + 0.04 * pulse
    record(
        "svg",
        x=x,
        y=y,
        svg=CAT_SVG,
        size=(48, 32),
        color=_TABBY_BODY.as_rgba_tuple(),
        scale=scale,
    )
    # Stripe overlay — shader noise on top of body region.
    record(
        "shader_swatch",
        x=x,
        y=y,
        size=(48, 32),
        name="noise_glitter",
        params={"density": 0.18, "seed": 7, "tint": _TABBY_STRIPE.as_rgba_tuple()},
    )
    # Eye — closes during blink (anim_t around 0.5 in a 0.2 s curve).
    eye_h = max(1, int(round(3 * (1.0 - pulse))))
    record(
        "ellipse",
        cx=x + 9,
        cy=y + 17,
        rx=2,
        ry=eye_h,
        color=(20, 20, 20, 255),
    )


def cat_01() -> Creature:
    return Creature(
        id="cat_01",
        render_fn=_cat_render_fn,
        idle_animations={
            "breathe": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.5, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=4.0,
                loop=True,
            ),
            "blink": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.5, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=0.2,
            ),
            "stretch": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.4, value=1.0),
                    Keyframe(t=0.6, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=1.5,
            ),
            "tail_flick": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.5, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=0.8,
            ),
        },
        trigger_animations={
            "stretch_full": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.4, value=1.0),
                    Keyframe(t=0.7, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=1.8,
            ),
        },
        personality_color=_TABBY_BODY,
        budget_ms=0.3,
        metadata={"season": "all", "render_strategy": "svg+shader",
                  "slot_hint": "title_bar"},
    )


def cat_01_slot() -> SlotPolicy:
    """Sleeps curled up on the active panel's top title-bar edge."""
    return SlotPolicy(
        region=SlotRegion(x=12, y=0, w=48, h=32, parent_panel="title_bar"),
        idle_cooldown_s=(4.0, 8.0),
        max_concurrent=1,
        reduced_motion_idle_ok=True,
    )


__all__ = ["CAT_SVG", "cat_01", "cat_01_slot"]
