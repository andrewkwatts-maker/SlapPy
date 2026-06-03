"""``sparkle`` — corner decoration motif.

Not really a creature — sparkle is a decorative motif that rides the
same scheduler so themes get a single integration seam. The render fn
paints a 4-point star centred on the slot anchor and modulates scale +
rotation via the ``twinkle`` idle curve.

There are no trigger animations — sparkle is decoration only. The
scheduler still handles registration and the per-frame render call;
the only difference is that calls to ``trigger("sparkle", ...)`` raise
:class:`LookupError` (no trigger anims declared).
"""
from __future__ import annotations

from typing import Any

from ...theme_spec import Color
from ..animation_curve import AnimationCurve, Keyframe
from ..creature_base import Creature
from ..slot_policy import SlotPolicy, SlotRegion


# Lemon-cream for the star body — matches the existing noise_glitter
# default colour so themes can re-use the shader bake.
_SPARKLE_GOLD = Color(r=0xFF, g=0xF0, b=0xC8, a=1.0)


# Inline SVG — 4-point star centred on (16, 16). The rotation is
# applied by the host via the `transform` field on the recorded
# draw-call dict; we keep the SVG itself static so the SVG cache key
# does not change per-frame.
SPARKLE_SVG = """\
<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>
  <polygon points='16,0 18,14 32,16 18,18 16,32 14,18 0,16 14,14'
           fill='#fff0c8' />
</svg>"""


def _sparkle_render_fn(
    draw_list: Any, x: int, y: int, anim_t: float
) -> None:
    """Paint the star + rotation transform onto the draw_list."""
    record = getattr(draw_list, "record", None)
    if record is None:
        return
    # Triangle wave 0..1..0 — same shape as fox + butterfly so the
    # render-fn test can assert it ran without raising.
    pulse = 1.0 - abs(anim_t * 2.0 - 1.0)
    scale = 0.85 + 0.3 * pulse
    angle_deg = anim_t * 360.0
    record(
        "svg",
        x=x,
        y=y,
        svg=SPARKLE_SVG,
        size=(32, 32),
        color=_SPARKLE_GOLD.as_rgba_tuple(),
        scale=scale,
        angle_deg=angle_deg,
    )
    # Also record a sparkle-shader hint so the host can overlay a
    # noise_glitter swatch behind the star (the design spec uses the
    # existing shader_effects.noise_glitter as the fur texture for
    # several creatures; sparkle re-uses it as a halo).
    record(
        "shader_swatch",
        x=x - 4,
        y=y - 4,
        size=(40, 40),
        name="noise_glitter",
        params={"density": 0.08, "seed": 11},
    )


def sparkle() -> Creature:
    """Build a fresh ``sparkle`` :class:`Creature` instance."""
    return Creature(
        id="sparkle",
        render_fn=_sparkle_render_fn,
        idle_animations={
            # Always-on twinkle — `loop=True` so the scheduler keeps it
            # alive without any cooldown gating.
            "twinkle": AnimationCurve(
                keyframes=[
                    Keyframe(t=0.0, value=0.0),
                    Keyframe(t=0.5, value=1.0),
                    Keyframe(t=1.0, value=0.0),
                ],
                duration_s=2.4,
                loop=True,
            ),
        },
        trigger_animations={},  # decoration only — no triggers
        personality_color=_SPARKLE_GOLD,
        budget_ms=0.1,
        metadata={"season": "summer", "render_strategy": "svg+shader"},
    )


def sparkle_slot() -> SlotPolicy:
    """Build a default panel-corner slot for the sparkle motif.

    The 32x32 anchor is what the host's ``sticker_corner`` widget
    expects — themes that want a different corner pass a custom
    :class:`SlotPolicy`.
    """
    return SlotPolicy(
        region=SlotRegion(x=4, y=4, w=32, h=32, parent_panel="panel_corner"),
        # Long cooldown — sparkle's twinkle is a looping curve, so the
        # cooldown is only relevant if the host cancels the idle anim
        # and we need to restart it.
        idle_cooldown_s=(30.0, 60.0),
        max_concurrent=1,
        reduced_motion_idle_ok=True,
    )


__all__ = ["SPARKLE_SVG", "sparkle", "sparkle_slot"]
