"""``butterfly_01`` — Save Butterfly status-bar mascot.

Render strategy: SVG wings + shader gradient. Two triangular wings live
in an inline SVG string (so the render fn can hand them to any SVG-
capable backend) and the body is a thin oval painted as a primitive
draw call. The wing flap angle is the only thing that varies per frame.

Animations:

* idle ``wing_idle`` — slow loop at 1 Hz; wings rock between -10° and
  +10°. Plays continuously when the butterfly is on-screen.
* trigger ``flutter`` — 2.5 s flight across the viewport on
  ``engine.save``.

The inline SVG is kept tiny (< 400 bytes) so the wheel cost is
negligible — see the parent design doc's 100 KB asset-budget rule.
"""
from __future__ import annotations

from typing import Any

from ...theme_spec import Color
from ..animation_curve import AnimationCurve, Keyframe
from ..creature_base import Creature
from ..slot_policy import SlotPolicy, SlotRegion


# Bubblegum pink — design spec calls for #FF6FB5.
_BUTTERFLY_PINK = Color(r=0xFF, g=0x6F, b=0xB5, a=1.0)
_BUTTERFLY_ACCENT = Color(r=0xFF, g=0xC8, b=0xE3, a=1.0)


# Inline SVG — two wings + body. The render fn substitutes the wing
# rotation via Python-side string format (the wings rotate around the
# body anchor at coordinates 32,32).
BUTTERFLY_SVG_TEMPLATE = """\
<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>
  <g transform='translate(32 32)'>
    <polygon points='0,0 -22,{wing_top} -18,{wing_bot} 0,4'
             fill='{fill}' />
    <polygon points='0,0 22,{wing_top} 18,{wing_bot} 0,4'
             fill='{fill}' />
    <ellipse cx='0' cy='0' rx='2' ry='10' fill='{body}' />
  </g>
</svg>"""


def _butterfly_svg(wing_angle_deg: float) -> str:
    """Compose the inline SVG for the current wing angle."""
    # Map -10..+10 deg onto the polygon vertex y-offsets.
    wing_top = int(round(-18 - wing_angle_deg))
    wing_bot = int(round(-4 - wing_angle_deg * 0.4))
    fill = "#%02x%02x%02x" % (
        _BUTTERFLY_PINK.r,
        _BUTTERFLY_PINK.g,
        _BUTTERFLY_PINK.b,
    )
    body = "#%02x%02x%02x" % (
        _BUTTERFLY_ACCENT.r,
        _BUTTERFLY_ACCENT.g,
        _BUTTERFLY_ACCENT.b,
    )
    return BUTTERFLY_SVG_TEMPLATE.format(
        wing_top=wing_top, wing_bot=wing_bot, fill=fill, body=body
    )


def _butterfly_render_fn(
    draw_list: Any, x: int, y: int, anim_t: float
) -> None:
    """Paint the butterfly via the draw_list ``record`` API.

    For ``wing_idle`` (looped) anim_t walks linearly 0..1 and the wing
    angle is a 10° sine ramp; the test harness records the call.

    For ``flutter``, anim_t advances 0..1 over 2.5 s, but the slot
    policy keeps the butterfly anchored — the cross-viewport flight is
    a host-side concern that overrides ``x`` / ``y`` before calling.
    """
    record = getattr(draw_list, "record", None)
    if record is None:
        return
    # Wing flap follows a triangle wave so the SVG vertex math stays linear.
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


def butterfly_01() -> Creature:
    """Build a fresh ``butterfly_01`` :class:`Creature` instance."""
    return Creature(
        id="butterfly_01",
        render_fn=_butterfly_render_fn,
        idle_animations={
            # 1 Hz wing flap, looping forever — the scheduler picks this
            # whenever the cooldown elapses; ``loop=True`` means the
            # curve never reports is_done, so the scheduler keeps the
            # animation alive until externally cancelled.
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
            "flutter": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.5, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=2.5,
            ),
            # The catalog notes a landing pose used by some events.
            "land": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=0.3,
            ),
        },
        personality_color=_BUTTERFLY_PINK,
        budget_ms=0.5,
        metadata={"season": "summer", "render_strategy": "svg+shader"},
    )


def butterfly_01_slot() -> SlotPolicy:
    """Build the default status-bar slot for the butterfly.

    64x64 px overlay region — the host may translate the render fn's
    ``x`` / ``y`` during a flutter to draw a flight path across the
    viewport.
    """
    return SlotPolicy(
        region=SlotRegion(x=200, y=600, w=64, h=64, parent_panel="status_bar"),
        idle_cooldown_s=(8.0, 16.0),
        max_concurrent=1,
        reduced_motion_idle_ok=True,
    )


__all__ = ["BUTTERFLY_SVG_TEMPLATE", "butterfly_01", "butterfly_01_slot"]
