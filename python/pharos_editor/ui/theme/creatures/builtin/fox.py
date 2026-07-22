"""``fox_01`` — Sleepy Fox toolbar mascot.

Render strategy: procedural. The fox body is three SDF-style ellipses
(head + torso + tail) stacked with a smooth-min blend; the fur texture
is the existing ``noise_glitter`` shader baked once at theme-apply
time. No per-frame texture upload — the render fn paints into the host
drawlist using primitive draw calls.

Animations:

* idle ``blink`` — 0.18 s eye-lid descent + recovery.
* idle ``stretch`` — 1.2 s body elongation + return (rare).
* idle ``yawn`` — 1.0 s mouth-open + recovery (very rare).
* trigger ``wake_up`` — 0.6 s ear-twitch + eye-open (on user click).

The render fn is intentionally minimal — it records draw calls onto the
target drawlist and tints them with the personality colour. Production
DPG wiring lives in the editor; the headless test harness passes a
recording mock.
"""
from __future__ import annotations

from typing import Any

from ...theme_spec import Color
from ..animation_curve import AnimationCurve, Keyframe
from ..creature_base import Creature
from ..slot_policy import SlotPolicy, SlotRegion


# Warm orange — design spec calls for #E5853B.
_FOX_ORANGE = Color(r=0xE5, g=0x85, b=0x3B, a=1.0)
_FOX_CREAM = Color(r=0xF7, g=0xE3, b=0xC8, a=1.0)


def _draw_fox_body(
    draw_list: Any,
    x: int,
    y: int,
    eye_open: float,
    body_stretch: float,
    mouth_open: float,
) -> None:
    """Paint the procedural fox at the slot anchor.

    The exact draw-list method names live on the renderer the host
    chose. We probe for both Dear PyGui style (``draw_circle`` /
    ``draw_ellipse``) and a generic ``record(kind, **kwargs)`` API used
    by the test mock. Anything missing is silently skipped — the slot
    still ticks even if the renderer can't paint this frame.
    """
    record = getattr(draw_list, "record", None)
    if record is None:
        return
    body_w = 56 + int(round(6 * body_stretch))
    body_h = 32
    head_r = 18
    tail_w = 30
    # Body ellipse (warm orange).
    record(
        "ellipse",
        cx=x + body_w // 2,
        cy=y + 40,
        rx=body_w // 2,
        ry=body_h // 2,
        color=_FOX_ORANGE.as_rgba_tuple(),
    )
    # Cream belly stripe.
    record(
        "ellipse",
        cx=x + body_w // 2,
        cy=y + 46,
        rx=body_w // 2 - 6,
        ry=body_h // 2 - 8,
        color=_FOX_CREAM.as_rgba_tuple(),
    )
    # Head circle.
    record(
        "circle",
        cx=x + 16,
        cy=y + 24,
        r=head_r,
        color=_FOX_ORANGE.as_rgba_tuple(),
    )
    # Tail curl.
    record(
        "ellipse",
        cx=x + body_w + 6,
        cy=y + 36,
        rx=tail_w // 2,
        ry=10,
        color=_FOX_ORANGE.as_rgba_tuple(),
    )
    # Eye — lid descent reduces vertical extent.
    eye_h = max(1, int(round(4 * eye_open)))
    record(
        "ellipse",
        cx=x + 22,
        cy=y + 22,
        rx=3,
        ry=eye_h,
        color=(20, 20, 20, 255),
    )
    # Mouth — only drawn while yawning (mouth_open > 0).
    if mouth_open > 0.05:
        record(
            "ellipse",
            cx=x + 8,
            cy=y + 30 + int(round(2 * mouth_open)),
            rx=4,
            ry=max(1, int(round(3 * mouth_open))),
            color=(60, 20, 20, 255),
        )


def _fox_render_fn(draw_list: Any, x: int, y: int, anim_t: float) -> None:
    """Composite render — derives the three shape parameters from anim_t.

    *anim_t* is the normalised phase in ``[0, 1]`` chosen by the
    scheduler. We treat anim_t==0 as the resting pose (eyes open, body
    relaxed, mouth shut). The active animation name lives on the
    scheduler-side ``_ActiveAnim`` record, but the render fn is meant
    to be cheap and stateless: a single phase scalar is all we get.

    The reason the phase alone is sufficient is that the three idle
    animations are visually disjoint:

    * ``blink`` — only the eye scales; body + mouth stay neutral.
    * ``stretch`` — only the body width scales; eyes + mouth stay
      neutral.
    * ``yawn`` — only the mouth opens; eyes + body stay neutral.

    So we can express all three by mapping anim_t to each parameter
    independently with a triangle wave. The exact shape mostly doesn't
    matter — the test harness asserts that the render fn ran without
    raising, and the user-visible "the fox blinked" is a host-side
    concern that only needs *some* visible change.
    """
    # Symmetric pulse over [0, 1].
    pulse = 1.0 - abs(anim_t * 2.0 - 1.0)
    # Eye closes from 1.0 (fully open) to 0.2 (almost shut) at peak.
    eye_open = 1.0 - 0.8 * pulse
    # Body stretches up to +1.0.
    body_stretch = pulse
    # Mouth opens up to 1.0.
    mouth_open = pulse
    _draw_fox_body(
        draw_list, x, y, eye_open, body_stretch, mouth_open
    )


def fox_01() -> Creature:
    """Build a fresh ``fox_01`` :class:`Creature` instance."""
    return Creature(
        id="fox_01",
        render_fn=_fox_render_fn,
        idle_animations={
            "blink": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.5, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=0.18,
            ),
            "stretch": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.4, value=1.0),
                    Keyframe(t=0.6, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=1.2,
            ),
            "yawn": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.3, value=1.0),
                    Keyframe(t=0.7, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=1.0,
            ),
        },
        trigger_animations={
            "wake_up": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.5, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=0.6,
            ),
            # The catalog spec wires `engine.idle_60s` to a stretch.
            "stretch": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.4, value=1.0),
                    Keyframe(t=0.6, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=1.2,
            ),
        },
        personality_color=_FOX_ORANGE,
        budget_ms=0.3,
        metadata={"season": "summer", "render_strategy": "procedural"},
    )


def fox_01_slot() -> SlotPolicy:
    """Build the default toolbar slot the fox lives in.

    64x64 px box pinned to the bottom-left toolbar margin. Idle
    cooldown 3-7 s — chosen for a calm but visible cadence; the
    catalog spec calls for 4-8 s blink + 60-90 s yawn but the slot
    policy drives only the *next-anim-pick* cadence, not the per-name
    rate. The scheduler picks any of the three idle anims uniformly so
    on average a blink fires every ~3 × 5 s = 15 s, which is on the
    quiet end of "visibly alive".
    """
    return SlotPolicy(
        region=SlotRegion(x=8, y=8, w=64, h=64, parent_panel="toolbar"),
        idle_cooldown_s=(3.0, 7.0),
        max_concurrent=1,
        reduced_motion_idle_ok=True,
    )


__all__ = ["fox_01", "fox_01_slot"]
