"""Preset post-process chains — Sprint-3 lighting integration.

These factories compose existing chain helpers (no new pass internals) into
ready-to-use combinations that match the three Pharos Engine flagship games:

* :func:`cinematic_chain` — the "movie look" for cutscenes and showcase demos.
* :func:`arcade_chain`    — punchy, readable post-FX for top-down shooters
  such as Ochema Circuit and Bullet Strata.
* :func:`iso_strategy_chain` — bloom + tonemap with declared topo dependencies
  for tower-defence / isometric titles like Stone Keep.

Backward compatibility:
    Every preset only invokes existing chain helpers and never mutates global
    state, so opting out is as simple as building a bare :class:`PostProcessChain`
    instead.  Passes appended by these factories are otherwise indistinguishable
    from passes added by hand.

All round-9 DoF / round-7 auto-EV / round-6 CA falloff / round-5 outline /
round-4 vignette / round-3 bloom polish work is wired through the existing
helpers — this module only chooses the parameters and the order.
"""
from __future__ import annotations

from .chain import PostProcessChain


# ---------------------------------------------------------------------------
# Cinematic — full pipeline with DoF, auto-EV, CA, bloom, vignette, outline
# ---------------------------------------------------------------------------


def cinematic_chain() -> PostProcessChain:
    """Round-9 DoF + round-7 auto-EV + round-6 CA + round-3 bloom +
    round-4 vignette + round-8 outline. The 'movie look' preset.

    Order (front to back):

        1. ``dof``                 — round-9 ``focus_transition`` softens
                                     the focal edge for a cinema-stage look.
        2. ``bloom``               — Lottes smooth-knee glow, mild intensity.
        3. ``tonemap``             — round-7 ACES-style mapping; the caller
                                     can drive ``exposure_ev`` with an
                                     :class:`AutoExposurePass` per frame.
        4. ``chromatic_aberration``— round-6 polynomial radial falloff for
                                     subtle lens fringing on the periphery.
        5. ``vignette``            — round-4 smoothstep falloff for the
                                     classic cinema shoulder.
        6. ``outline``             — round-5 Sobel-based soft outline so
                                     the silhouette holds together after
                                     the DoF blur.
    """
    chain = PostProcessChain()

    # 1) DoF — soft focal edge (focus_transition > 1 -> smoothstep ramp).
    chain.add_dof(
        focal_distance=0.45,
        focal_range=0.25,
        max_coc_radius=10.0,
        bokeh_samples=16,
        focus_transition=1.5,
    )

    # 2) Bloom — mild Lottes smooth-knee glow that survives auto-EV.
    chain.add_bloom(threshold=1.0, knee=0.3, intensity=0.8)

    # 3) Tonemap — defaults to ACES mode 0; caller can pass an AutoExposurePass.
    chain.add_tonemap(exposure_ev=0.0, mode=0, saturation=1.05, contrast=1.05)

    # 4) Chromatic aberration — round-6 polynomial falloff.
    chain.add_chromatic_aberration(
        strength=0.004,
        center=(0.5, 0.5),
        falloff_power=2.0,
        falloff_amount=0.6,
    )

    # 5) Vignette — opt-in smoothstep shoulder (round-4 polish).
    chain.add_vignette(strength=1.1, inner_radius=0.35, feather=0.45)

    # 6) Outline — round-5 soft Sobel; runs last so DoF blur doesn't mush it.
    chain.add_outline(
        color=(0.0, 0.0, 0.0, 1.0),
        threshold=0.18,
        softness=0.05,
        use_sobel=True,
    )

    return chain


# ---------------------------------------------------------------------------
# Arcade — punchy bloom + outline + vignette, no DoF/CA
# ---------------------------------------------------------------------------


def arcade_chain() -> PostProcessChain:
    """Punchier bloom + outline + vignette, no DoF/CA — keeps gameplay
    readable. Suitable for top-down arcade games (Ochema, Bullet Strata).

    Order (front to back):

        1. ``bloom``    — higher intensity than the cinematic preset so neon
                          accents read at small sprite sizes.
        2. ``tonemap``  — round-7 contrast boost for arcade pop.
        3. ``outline``  — round-5 binary-cliff outline (use_sobel=False) so
                          enemies don't smear with motion.
        4. ``vignette`` — gentle frame, keeps the action centred.

    No DoF/CA: both blur the play-field, which is sub-optimal for top-down
    twitch gameplay where every pixel matters.
    """
    chain = PostProcessChain()

    # 1) Punchier bloom.
    chain.add_bloom(threshold=0.8, knee=0.2, intensity=1.4)

    # 2) Tonemap — contrast > 1 for the classic arcade pop.
    chain.add_tonemap(exposure_ev=0.5, mode=0, saturation=1.15, contrast=1.2)

    # 3) Crisp binary outline (legacy 4-cardinal path — pre-round-5 default).
    chain.add_outline(
        color=(0.0, 0.0, 0.0, 1.0),
        threshold=0.1,
        softness=0.0,
        use_sobel=False,
    )

    # 4) Gentle vignette — feather=0 keeps the legacy curve byte-for-byte.
    chain.add_vignette(strength=0.7, inner_radius=0.0, feather=0.0)

    return chain


# ---------------------------------------------------------------------------
# Iso strategy — bloom + tonemap with declared topo dependencies
# ---------------------------------------------------------------------------


def iso_strategy_chain() -> PostProcessChain:
    """Bloom + tonemap + render-channel-topo. No DoF (the iso camera
    has fixed depth). Suitable for tower-defence (Stone Keep).

    Order (front to back):

        1. ``bloom``    — moderate intensity to highlight unit emissives
                          (muzzle flashes, status auras) without saturating
                          the play-field.
        2. ``tonemap``  — declares ``depends_on=['bloom']`` so the round-8
                          topological sort guarantees the tonemap composites
                          *after* bloom even if a caller re-orders the chain
                          at runtime.
        3. ``vignette`` — declares ``depends_on=['tonemap']`` so the cinema
                          shoulder sees the tonemapped frame, not the raw
                          HDR pre-map.

    The dependency declarations mirror the round-8 ``RenderPass.depends_on``
    convention so a future executor with topological scheduling Just Works.
    """
    chain = PostProcessChain()

    # 1) Bloom — moderate glow for emissive units.
    bloom = chain.add_bloom(threshold=0.9, knee=0.25, intensity=1.0)

    # 2) Tonemap — must run after bloom (round-8 topo dependency).
    tonemap = chain.add_tonemap(
        exposure_ev=0.0, mode=0, saturation=1.0, contrast=1.05,
    )
    tonemap.depends_on = [bloom.label]

    # 3) Vignette — must run after tonemap so the shoulder is post-tonemap.
    vignette = chain.add_vignette(strength=0.6, inner_radius=0.2, feather=0.3)
    vignette.depends_on = [tonemap.label]

    return chain


__all__ = [
    "cinematic_chain",
    "arcade_chain",
    "iso_strategy_chain",
]
