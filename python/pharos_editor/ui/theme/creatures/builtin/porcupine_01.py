"""``porcupine_01`` — Baby Porcupine error-popup mascot.

Render strategy: shader noise for quill texture + SVG body outline +
tiny pink nose. Sits at the margin of error popups so the user sees a
calm friend when something blew up.

Animations:

* idle ``nibble`` — continuous mild head bob, 2.5 s loop.
* idle ``blink`` — every 5-8 s.
* trigger ``ball_up`` — fires on ``engine.error``; rolls into spiky
  ball briefly, 1.2 s.
"""
from __future__ import annotations

from typing import Any

from ...theme_spec import Color
from ..animation_curve import AnimationCurve, Keyframe
from ..creature_base import Creature
from ..slot_policy import SlotPolicy, SlotRegion


# Warm brown body + cream belly — design spec calls for #9C7B5A / #EAD7B9.
_PORC_BROWN = Color(r=0x9C, g=0x7B, b=0x5A, a=1.0)
_PORC_CREAM = Color(r=0xEA, g=0xD7, b=0xB9, a=1.0)
_PORC_NOSE = Color(r=0xF0, g=0x70, b=0x80, a=1.0)


# Inline SVG — round body with cream belly + nose dot, ~340B.
PORCUPINE_SVG = """\
<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 48 40'>
  <ellipse cx='24' cy='24' rx='22' ry='14' fill='#9c7b5a' />
  <ellipse cx='24' cy='28' rx='14' ry='8' fill='#ead7b9' />
  <circle cx='6' cy='24' r='4' fill='#9c7b5a' />
  <circle cx='4' cy='23' r='1' fill='#f07080' />
  <circle cx='9' cy='22' r='1' fill='#222' />
</svg>"""


def _porcupine_render_fn(draw_list: Any, x: int, y: int, anim_t: float) -> None:
    record = getattr(draw_list, "record", None)
    if record is None:
        return
    pulse = 1.0 - abs(anim_t * 2.0 - 1.0)
    bob = int(round(-2 * pulse))
    # Quill texture shader (denser when balled up).
    quill_density = 0.4 + 0.3 * pulse
    record(
        "shader_swatch",
        x=x,
        y=y + bob,
        size=(48, 40),
        name="noise_glitter",
        params={"density": quill_density, "seed": 23,
                "tint": _PORC_BROWN.as_rgba_tuple()},
    )
    record(
        "svg",
        x=x,
        y=y + bob,
        svg=PORCUPINE_SVG,
        size=(48, 40),
        color=_PORC_BROWN.as_rgba_tuple(),
    )
    # Pink nose tip — always rendered.
    record(
        "ellipse",
        cx=x + 4,
        cy=y + 23 + bob,
        rx=1,
        ry=1,
        color=_PORC_NOSE.as_rgba_tuple(),
    )
    # Belly visible when not balled up.
    if pulse < 0.6:
        record(
            "ellipse",
            cx=x + 24,
            cy=y + 28,
            rx=12,
            ry=6,
            color=_PORC_CREAM.as_rgba_tuple(),
        )


def porcupine_01() -> Creature:
    return Creature(
        id="porcupine_01",
        render_fn=_porcupine_render_fn,
        idle_animations={
            "nibble": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.5, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=2.5,
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
        },
        trigger_animations={
            "ball_up": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.35, value=1.0),
                    Keyframe(t=0.65, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=1.2,
            ),
        },
        personality_color=_PORC_BROWN,
        budget_ms=0.3,
        metadata={"season": "autumn", "render_strategy": "svg+shader",
                  "slot_hint": "error_popup_margin"},
    )


def porcupine_01_slot() -> SlotPolicy:
    """Error popup margin — 48x40 anchor."""
    return SlotPolicy(
        region=SlotRegion(x=8, y=8, w=48, h=40, parent_panel="error_popup"),
        idle_cooldown_s=(5.0, 10.0),
        max_concurrent=1,
        reduced_motion_idle_ok=True,
    )


__all__ = ["PORCUPINE_SVG", "porcupine_01", "porcupine_01_slot"]
