"""``hedgehog_01`` — Tiny Hedgehog spawn-menu mascot.

Render strategy: SVG body + shader noise for quill texture. Sits in
the spawn menu modal so the user has a friendly face when picking
chassis options.

Animations:

* idle ``sniff`` — every 4-7 s; nose twitch, 0.3 s.
* idle ``bristle`` — every 20-30 s; quills briefly raise, 0.4 s.
* trigger ``bristle_full`` — fires on toolbar hover; quills puff up
  over 0.9 s.
"""
from __future__ import annotations

from typing import Any

from ...theme_spec import Color
from ..animation_curve import AnimationCurve, Keyframe
from ..creature_base import Creature
from ..slot_policy import SlotPolicy, SlotRegion


# Brown body + cream belly — design spec calls for #8C6F4A / #EAD7B9.
_HEDGE_BROWN = Color(r=0x8C, g=0x6F, b=0x4A, a=1.0)
_HEDGE_CREAM = Color(r=0xEA, g=0xD7, b=0xB9, a=1.0)
_HEDGE_NOSE = Color(r=0x55, g=0x33, b=0x22, a=1.0)


# Inline SVG — tear-drop body + face area + tiny nose, ~340B.
HEDGEHOG_SVG = """\
<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 48 36'>
  <ellipse cx='28' cy='20' rx='18' ry='14' fill='#8c6f4a' />
  <ellipse cx='10' cy='22' rx='8' ry='8' fill='#ead7b9' />
  <circle cx='4' cy='22' r='1.5' fill='#553322' />
  <circle cx='8' cy='20' r='1' fill='#222' />
</svg>"""


def _hedgehog_render_fn(draw_list: Any, x: int, y: int, anim_t: float) -> None:
    record = getattr(draw_list, "record", None)
    if record is None:
        return
    pulse = 1.0 - abs(anim_t * 2.0 - 1.0)
    record(
        "svg",
        x=x,
        y=y,
        svg=HEDGEHOG_SVG,
        size=(48, 36),
        color=_HEDGE_BROWN.as_rgba_tuple(),
    )
    # Quill texture — denser/larger when bristling.
    quill_density = 0.3 + 0.4 * pulse
    record(
        "shader_swatch",
        x=x + 12,
        y=y + 2,
        size=(34, 30),
        name="noise_glitter",
        params={"density": quill_density, "seed": 31,
                "tint": _HEDGE_BROWN.as_rgba_tuple()},
    )
    # Belly highlight — round face.
    record(
        "ellipse",
        cx=x + 10,
        cy=y + 22,
        rx=8,
        ry=8,
        color=_HEDGE_CREAM.as_rgba_tuple(),
    )
    # Nose dot pulses with sniff.
    nose_dx = int(round(-1 * pulse))
    record(
        "ellipse",
        cx=x + 4 + nose_dx,
        cy=y + 22,
        rx=1,
        ry=1,
        color=_HEDGE_NOSE.as_rgba_tuple(),
    )


def hedgehog_01() -> Creature:
    return Creature(
        id="hedgehog_01",
        render_fn=_hedgehog_render_fn,
        idle_animations={
            "sniff": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.5, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=0.3,
            ),
            "bristle": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.4, value=1.0),
                    Keyframe(t=0.6, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=0.4,
            ),
        },
        trigger_animations={
            "bristle_full": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.35, value=1.0),
                    Keyframe(t=0.7, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=0.9,
            ),
        },
        personality_color=_HEDGE_BROWN,
        budget_ms=0.3,
        metadata={"season": "autumn", "render_strategy": "svg+shader",
                  "slot_hint": "spawn_menu_modal"},
    )


def hedgehog_01_slot() -> SlotPolicy:
    """Spawn menu modal corner — 48x36 anchor."""
    return SlotPolicy(
        region=SlotRegion(x=8, y=8, w=48, h=36, parent_panel="spawn_menu"),
        idle_cooldown_s=(4.0, 7.0),
        max_concurrent=1,
        reduced_motion_idle_ok=True,
    )


__all__ = ["HEDGEHOG_SVG", "hedgehog_01", "hedgehog_01_slot"]
