"""``butterfly_02`` — Save Butterfly variant with bubblegum + neon-purple gradient.

Render strategy: SVG wings + shader gradient. Same wing topology as
``butterfly_01`` but with a pink → purple gradient fill so the save
overlay reads as a *different* event from idle status-bar flits.

Animations:

* idle ``wing_idle`` — slow flap, infinite loop.
* trigger ``flutter_full`` — fires on ``engine.save``; flies across
  viewport with sparkle trail over 3 s.
"""
from __future__ import annotations

from typing import Any

from ...theme_spec import Color
from ..animation_curve import AnimationCurve, Keyframe
from ..creature_base import Creature
from ..slot_policy import SlotPolicy, SlotRegion


# Bubblegum-pink + neon-purple gradient.
_BUTTERFLY_PINK = Color(r=0xFF, g=0x6F, b=0xB5, a=1.0)
_BUTTERFLY_PURPLE = Color(r=0x9A, g=0x3F, b=0xE8, a=1.0)


# Inline SVG — two wings + body with gradient placeholder, ~470B.
BUTTERFLY_GRADIENT_SVG_TEMPLATE = """\
<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>
  <defs>
    <linearGradient id='wg' x1='0' y1='0' x2='1' y2='1'>
      <stop offset='0' stop-color='{c1}' />
      <stop offset='1' stop-color='{c2}' />
    </linearGradient>
  </defs>
  <g transform='translate(32 32)'>
    <polygon points='0,0 -22,{wt} -18,{wb} 0,4' fill='url(#wg)' />
    <polygon points='0,0 22,{wt} 18,{wb} 0,4' fill='url(#wg)' />
    <ellipse cx='0' cy='0' rx='2' ry='10' fill='{c2}' />
  </g>
</svg>"""


def _butterfly_svg(wing_angle_deg: float) -> str:
    wt = int(round(-18 - wing_angle_deg))
    wb = int(round(-4 - wing_angle_deg * 0.4))
    c1 = "#%02x%02x%02x" % (
        _BUTTERFLY_PINK.r, _BUTTERFLY_PINK.g, _BUTTERFLY_PINK.b
    )
    c2 = "#%02x%02x%02x" % (
        _BUTTERFLY_PURPLE.r, _BUTTERFLY_PURPLE.g, _BUTTERFLY_PURPLE.b
    )
    return BUTTERFLY_GRADIENT_SVG_TEMPLATE.format(wt=wt, wb=wb, c1=c1, c2=c2)


def _butterfly_render_fn(draw_list: Any, x: int, y: int, anim_t: float) -> None:
    record = getattr(draw_list, "record", None)
    if record is None:
        return
    flap = 1.0 - abs(anim_t * 2.0 - 1.0)
    wing_angle_deg = -10.0 + 20.0 * flap
    svg = _butterfly_svg(wing_angle_deg)
    record(
        "svg",
        x=x,
        y=y,
        svg=svg,
        size=(64, 64),
        color=_BUTTERFLY_PINK.as_rgba_tuple(),
    )
    # Sparkle trail during flutter_full (anim_t > 0).
    if anim_t > 0.1:
        record(
            "shader_swatch",
            x=x - 8,
            y=y - 8,
            size=(80, 80),
            name="noise_glitter",
            params={"density": 0.16, "seed": 5,
                    "tint": _BUTTERFLY_PURPLE.as_rgba_tuple()},
        )


def butterfly_02() -> Creature:
    return Creature(
        id="butterfly_02",
        render_fn=_butterfly_render_fn,
        idle_animations={
            "wing_idle": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.5, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=1.0,
                loop=True,
            ),
        },
        trigger_animations={
            "flutter_full": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.5, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=3.0,
            ),
        },
        personality_color=_BUTTERFLY_PINK,
        budget_ms=0.5,
        metadata={"season": "spring", "render_strategy": "svg+shader",
                  "slot_hint": "viewport_overlay"},
    )


def butterfly_02_slot() -> SlotPolicy:
    """Viewport overlay — 64x64 anchor; host overrides x/y during flutter."""
    return SlotPolicy(
        region=SlotRegion(x=400, y=300, w=64, h=64, parent_panel="viewport_overlay"),
        idle_cooldown_s=(12.0, 24.0),
        max_concurrent=1,
        reduced_motion_idle_ok=True,
    )


__all__ = [
    "BUTTERFLY_GRADIENT_SVG_TEMPLATE",
    "butterfly_02",
    "butterfly_02_slot",
]
