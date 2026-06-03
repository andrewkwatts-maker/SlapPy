"""``red_panda_01`` — Red Panda Naphour, toolbar draft-excluder mascot.

Render strategy: shader-soft-fur for the russet body + SVG mask for the
cream face and bandit eye markings. Lies across the toolbar baseline.

Animations:

* idle ``deep_breath`` — continuous 5 s loop, ±3 % scale.
* idle ``tail_swish`` — rare 60-120 s; 1.2 s arc.
* idle ``ear_twitch`` — rare 40-80 s; 0.25 s flick.
* trigger ``lift_head`` — fires on ``engine.error``; looks up briefly,
  1.0 s.
"""
from __future__ import annotations

from typing import Any

from ...theme_spec import Color
from ..animation_curve import AnimationCurve, Keyframe
from ..creature_base import Creature
from ..slot_policy import SlotPolicy, SlotRegion


# Russet body + cream face — design spec calls for #B4651C / #F5E9D8.
_RUSSET = Color(r=0xB4, g=0x65, b=0x1C, a=1.0)
_CREAM = Color(r=0xF5, g=0xE9, b=0xD8, a=1.0)
_MASK = Color(r=0x55, g=0x33, b=0x18, a=1.0)


# Inline SVG mask — cream face + bandit eye markings, ~360B.
RED_PANDA_SVG = """\
<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 80 32'>
  <ellipse cx='40' cy='20' rx='38' ry='10' fill='#b4651c' />
  <circle cx='14' cy='14' r='10' fill='#b4651c' />
  <polygon points='6,4 12,12 4,12' fill='#b4651c' />
  <ellipse cx='14' cy='15' rx='6' ry='5' fill='#f5e9d8' />
  <ellipse cx='11' cy='14' rx='1.5' ry='2' fill='#553318' />
  <ellipse cx='17' cy='14' rx='1.5' ry='2' fill='#553318' />
</svg>"""


def _red_panda_render_fn(draw_list: Any, x: int, y: int, anim_t: float) -> None:
    record = getattr(draw_list, "record", None)
    if record is None:
        return
    pulse = 1.0 - abs(anim_t * 2.0 - 1.0)
    scale = 0.97 + 0.06 * pulse
    # Soft-fur shader behind the SVG.
    record(
        "shader_swatch",
        x=x,
        y=y,
        size=(80, 32),
        name="noise_glitter",
        params={"density": 0.28, "seed": 9,
                "tint": _RUSSET.as_rgba_tuple()},
    )
    record(
        "svg",
        x=x,
        y=y,
        svg=RED_PANDA_SVG,
        size=(80, 32),
        color=_RUSSET.as_rgba_tuple(),
        scale=scale,
    )
    # Striped tail bands — 5 alternating russet/cream segments.
    for i in range(5):
        record(
            "ellipse",
            cx=x + 60 + i * 4,
            cy=y + 22,
            rx=3,
            ry=4,
            color=(_RUSSET if i % 2 == 0 else _CREAM).as_rgba_tuple(),
        )
    # Lifted head — bigger ellipse when trigger active (pulse high).
    if pulse > 0.6:
        record(
            "circle",
            cx=x + 14,
            cy=y + 8,
            r=10,
            color=_MASK.as_rgba_tuple(),
        )


def red_panda_01() -> Creature:
    return Creature(
        id="red_panda_01",
        render_fn=_red_panda_render_fn,
        idle_animations={
            "deep_breath": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.5, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=5.0,
                loop=True,
            ),
            "tail_swish": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.5, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=1.2,
            ),
            "ear_twitch": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.5, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=0.25,
            ),
        },
        trigger_animations={
            "lift_head": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.3, value=1.0),
                    Keyframe(t=0.7, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=1.0,
            ),
        },
        personality_color=_RUSSET,
        budget_ms=0.4,
        metadata={"season": "autumn", "render_strategy": "svg+shader",
                  "slot_hint": "toolbar_baseline"},
    )


def red_panda_01_slot() -> SlotPolicy:
    """Lies across the toolbar baseline like a draft excluder."""
    return SlotPolicy(
        region=SlotRegion(x=100, y=48, w=80, h=32, parent_panel="toolbar"),
        idle_cooldown_s=(8.0, 16.0),
        max_concurrent=1,
        reduced_motion_idle_ok=True,
    )


__all__ = ["RED_PANDA_SVG", "red_panda_01", "red_panda_01_slot"]
