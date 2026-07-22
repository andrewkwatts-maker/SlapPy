"""Screen-space contact shadows (Bouvier 2014, *The Order: 1886*).

Round-13 lighting polish adds a depth-buffer–based contact-shadow pass
that complements the existing Vogel-disk PCF (round 12, R2S3-D) and
PCSS branches in ``shaders/shadow_csm.wgsl``.

Algorithm (Bouvier 2014, GDC 2014 *Contact Shadows in The Order: 1886*):

    For each lit pixel:
      1. Reconstruct the world-space surface position from the depth buffer.
      2. Ray-march toward the light direction with N exponentially-decreasing
         steps that cover ``max_distance`` total in world units.
      3. At each sample reproject the world-space ray position to NDC and
         compare against the depth-buffer value at that screen coordinate.
      4. If any sample's reprojected depth is closer to the camera than the
         depth-buffer reads — by more than ``thickness_threshold`` — the
         pixel is occluded by some nearby geometry.

The output is composed with the main CSM/PCSS shadow term using one of
three modes selected by :attr:`ContactShadowsPass.compose_mode`:

``"min"`` (round-13 default, legacy multiplicative)::

    final_shadow = min(main_shadow, 1.0 - contact_strength * blend)

This guarantees the contact term *only* darkens, matching the Bouvier
2014 recommendation that contact shadows are an additive darkening, not
a replacement.

``"max"`` (round-14 preferred, never double-darkens)::

    contact_shadow = 1.0 - contact_strength * blend
    final_shadow   = max(main_shadow, contact_shadow)

In ``"max"`` mode the two shadow terms compete rather than multiply, so
a pixel already deep in PCF shadow is **not** darkened further by a
near-occluder contact term.  This is the round-14 fix for
double-shadowing in the cluster lighting path where PCF + contact were
silently multiplied together.

``"penumbra_gated"`` (round-14, contact only inside PCF penumbra)::

    if 0.1 < main_shadow < 0.9:
        final_shadow = min(main_shadow, 1.0 - contact_strength * blend)
    else:
        final_shadow = main_shadow

Contact shadows only fire where PCF says the pixel is on a soft edge —
fully-lit and fully-shadowed regions forward the PCF term unchanged.
This is the safest mode for cinematic scenes where contact darkening of
already-lit regions would look like a doubled drop shadow.

The Python helper :func:`ray_march_contact_shadow` mirrors the WGSL
arithmetic bit-for-bit so the algorithm can be regression-tested
headlessly (no wgpu adapter required).
"""
from __future__ import annotations

import math
from typing import Any, Tuple

from ._pass_base import PostProcessPassBase
from ._ubo import UboField
from ._validation import (
    validate_non_negative_float,
    validate_unit_interval,
)


_SHADER = "contact_shadows_depth.wgsl"
_ENTRY  = "main"

# ContactShadowsParams std140 layout (32 bytes).  ``samples`` packs into
# the trailing 4-byte slot of ``light_dir`` (the WGSL vec3 / scalar
# trick); compose_mode reuses the previously-padding u32 at offset 28.
#
# compose_mode encoding (u32):
#     0 = "min"             (legacy multiplicative — round-13 default)
#     1 = "max"             (round-14 preferred — never double-darkens)
#     2 = "penumbra_gated"  (contact only where 0.1 < pcf < 0.9)
_CONTACT_UBO_FIELDS = [
    UboField(name="light_dir",    dtype="vec3f", offset=0),
    UboField(name="samples",      dtype="u32",   offset=12),
    UboField(name="max_distance", dtype="f32",   offset=16),
    UboField(name="thickness",    dtype="f32",   offset=20),
    UboField(name="blend",        dtype="f32",   offset=24),
    UboField(name="compose_mode", dtype="u32",   offset=28),
]

_COMPOSE_MODES: dict[str, int] = {
    "min": 0,
    "max": 1,
    "penumbra_gated": 2,
}

# Penumbra-gate band for ``compose_mode="penumbra_gated"``.  The contact
# term only fires when the main PCF shadow is strictly inside this band
# — i.e. on a soft edge where PCF could not resolve the near-occluder.
# Fully-lit and fully-shadowed regions forward the PCF term unchanged.
_PENUMBRA_LO: float = 0.1
_PENUMBRA_HI: float = 0.9


# ---------------------------------------------------------------------------
# Pure-numpy / float mirror of the WGSL ray-march for headless regression
# tests.  Operates in 1-D camera space along the light direction so the
# algorithm can be exercised without a wgpu device.
# ---------------------------------------------------------------------------


def _exponential_step_distance(step_idx: int, samples: int, max_distance: float) -> float:
    """Return the world-space ray distance at sample ``step_idx``.

    The marcher uses an exponentially-increasing distance schedule so the
    first few samples cluster near the surface (where contact shadows are
    most visible) while the final sample still reaches ``max_distance``.

    Concretely, for sample i in ``[0, N)``::

        t_i = max_distance * (2^((i + 1) / N) - 1) / (2 - 1)
            = max_distance * (2^((i + 1) / N) - 1)

    so ``t_{N-1} == max_distance`` exactly and ``t_0`` is the smallest
    nonzero offset.  This matches the WGSL ``exp2`` ramp.
    """
    if samples <= 0:
        return 0.0
    return max_distance * (math.pow(2.0, (step_idx + 1) / float(samples)) - 1.0)


def ray_march_contact_shadow(
    surface_depth: float,
    occluder_depths: list[float],
    samples: int,
    max_distance: float,
    thickness_threshold: float,
) -> float:
    """Return the contact-shadow strength in ``[0, 1]`` for a single pixel.

    This is a 1-D headless mirror of the WGSL ``main`` ray-march along
    the dominant-light vector.

    Parameters
    ----------
    surface_depth
        Depth (world units) of the shaded pixel from the camera.
    occluder_depths
        Depth (world units) of the *first* opaque hit at each sample's
        reprojected screen coordinate.  Length must equal ``samples``.
    samples
        Number of ray-march steps.  ``0`` short-circuits to ``0.0``
        (the pass is a no-op, matching the back-compat opt-out).
    max_distance
        Total world-space march length.
    thickness_threshold
        Required gap (world units) between the marched ray's depth and
        the depth-buffer hit to register as a contact-shadow occlusion.

    Returns
    -------
    float
        Contact-shadow strength in ``[0, 1]``.  ``0.0`` means the pixel
        is *not* in contact shadow; ``1.0`` means fully occluded.  The
        consumer composes this with the main shadow term as
        ``min(main_shadow, 1.0 - strength * blend)``.
    """
    if samples <= 0:
        return 0.0
    if len(occluder_depths) != samples:
        raise ValueError(
            f"occluder_depths length ({len(occluder_depths)}) must equal "
            f"samples ({samples})"
        )

    occluded = False
    for i in range(samples):
        ray_depth = surface_depth + _exponential_step_distance(
            i, samples, max_distance,
        )
        # The reprojected depth must be *closer to the camera* than the
        # depth buffer by more than the thickness threshold for the ray
        # to register as occluded.  Bouvier 2014 §3.2.
        delta = ray_depth - occluder_depths[i]
        if delta > thickness_threshold:
            occluded = True
            break
    return 1.0 if occluded else 0.0


def compose_with_main_shadow(
    main_shadow: float,
    contact_strength: float,
    blend: float,
    compose_mode: str = "min",
) -> float:
    """Compose the contact-shadow strength with the main CSM term.

    Parameters
    ----------
    main_shadow
        The round-12 Vogel-disk PCF (or PCSS) shadow term in ``[0, 1]``.
        ``1.0 = fully lit``, ``0.0 = fully shadowed``.
    contact_strength
        The round-13 ray-march occlusion strength in ``[0, 1]``.
    blend
        Compose-time strength multiplier in ``[0, 1]``.
    compose_mode
        One of:

        ``"min"`` (round-13 default, legacy)::

            final = min(main_shadow, 1.0 - contact_strength * blend)

        Multiplicative.  A pixel that the main shadow says is fully
        shadowed cannot be made brighter, but a pixel already in soft
        PCF shadow *will* be darkened further by contact.  This is the
        Round 14 double-shadow regression.

        ``"max"`` (round-14 preferred — never double-darkens)::

            contact = 1.0 - contact_strength * blend
            final   = max(main_shadow, contact)

        The two terms compete: whichever says the pixel is **brighter**
        wins.  This eliminates double-shadowing.

        ``"penumbra_gated"`` (contact only inside PCF penumbra)::

            if 0.1 < main_shadow < 0.9:
                final = min(main_shadow, 1.0 - contact_strength * blend)
            else:
                final = main_shadow

        Contact only fires on soft PCF edges; fully-lit and
        fully-shadowed regions forward PCF unchanged.

    Returns
    -------
    float
        Composed shadow term in ``[0, 1]``.
    """
    if compose_mode == "min":
        return min(main_shadow, 1.0 - contact_strength * blend)
    if compose_mode == "max":
        contact = 1.0 - contact_strength * blend
        return max(main_shadow, contact)
    if compose_mode == "penumbra_gated":
        if _PENUMBRA_LO < main_shadow < _PENUMBRA_HI:
            return min(main_shadow, 1.0 - contact_strength * blend)
        return main_shadow
    raise ValueError(
        f"compose_with_main_shadow: compose_mode must be one of "
        f"{sorted(_COMPOSE_MODES)!r}; got {compose_mode!r}"
    )


# ---------------------------------------------------------------------------
# Public pass object
# ---------------------------------------------------------------------------


class ContactShadowsPass(PostProcessPassBase):
    """Bouvier 2014 depth-buffer contact-shadow post-process pass.

    Parameters
    ----------
    samples
        Number of ray-march steps per pixel.  Default ``6`` matches the
        Bouvier 2014 *Order: 1886* recommendation.  ``0`` makes the
        pass a no-op (back-compat opt-out).
    max_distance
        Total world-space march length in metres.  Default ``1.0``.
    thickness_threshold
        Required gap (world units) between the marched ray and the
        depth-buffer hit to count as an occlusion.  Default ``0.1``.
    blend
        Compose-time strength multiplier in ``[0, 1]``.  Default ``0.7``
        — strong enough to read on indoor scenes without dominating
        soft penumbras.
    light_dir
        Direction *toward* the dominant light, world space.  Stored
        normalised so the shader can skip the per-pixel normalize.
        Default points straight down (matches the shadow_csm default).
    compose_mode
        How the contact term composes with the main PCF/PCSS shadow:

        * ``"min"`` — legacy multiplicative (Round 13 default; kept for
          back-compat — can double-darken when PCF is in penumbra).
        * ``"max"`` — Round 14 preferred — the two terms compete via
          ``max``, so a pixel already in soft PCF shadow is **not**
          darkened further.  This is the fix for the cluster-lighting
          double-shadow regression.
        * ``"penumbra_gated"`` — contact only fires when the PCF term
          is strictly inside ``(0.1, 0.9)``.  Fully-lit and fully-
          shadowed regions forward PCF unchanged.

        Default ``"max"`` — the documented Round 14 fix.  Existing
        scenes that need the Round 13 multiplicative behaviour can opt
        in with ``compose_mode="min"``.
    """

    label = "contact_shadows"

    # ----- PostProcessPassBase declarative schema -----
    SHADER = _SHADER
    ENTRY = _ENTRY
    PARAMS_LAYOUT = _CONTACT_UBO_FIELDS
    DEPENDS_ON = ("shadow_csm",)
    BLOB_SIZE = 32

    def __init__(
        self,
        samples: int = 6,
        max_distance: float = 1.0,
        thickness_threshold: float = 0.1,
        blend: float = 0.7,
        light_dir: Tuple[float, float, float] = (0.0, -1.0, 0.0),
        compose_mode: str = "max",
    ) -> None:
        # ── Validation — refuse silently-wrong configs at boundary. ───────
        if isinstance(samples, bool) or not isinstance(samples, int):
            raise TypeError(
                f"ContactShadowsPass: samples must be an int (0 = no-op); "
                f"got {type(samples).__name__}"
            )
        if samples < 0:
            raise ValueError(
                f"ContactShadowsPass: samples must be >= 0 (0 = no-op); "
                f"got {samples}"
            )
        validate_non_negative_float(
            "max_distance", "ContactShadowsPass", max_distance,
        )
        validate_non_negative_float(
            "thickness_threshold", "ContactShadowsPass", thickness_threshold,
        )
        validate_unit_interval("blend", "ContactShadowsPass", blend)

        if (
            isinstance(light_dir, (str, bytes))
            or not hasattr(light_dir, "__len__")
            or len(light_dir) != 3
        ):
            raise ValueError(
                "ContactShadowsPass: light_dir must be a 3-tuple "
                f"(x, y, z); got {light_dir!r}"
            )
        ld = [float(c) for c in light_dir]
        if not all(math.isfinite(c) for c in ld):
            raise ValueError(
                f"ContactShadowsPass: light_dir must be finite; got {light_dir!r}"
            )
        # Normalise once at construction time — the shader skips the
        # per-pixel normalize since the direction is uniform.
        nrm = math.sqrt(ld[0] * ld[0] + ld[1] * ld[1] + ld[2] * ld[2])
        if nrm > 0.0:
            ld = [c / nrm for c in ld]

        if not isinstance(compose_mode, str):
            raise TypeError(
                "ContactShadowsPass: compose_mode must be a str (one of "
                f"{sorted(_COMPOSE_MODES)!r}); "
                f"got {type(compose_mode).__name__}"
            )
        if compose_mode not in _COMPOSE_MODES:
            raise ValueError(
                "ContactShadowsPass: compose_mode must be one of "
                f"{sorted(_COMPOSE_MODES)!r}; got {compose_mode!r}"
            )

        self.samples = int(samples)
        self.max_distance = float(max_distance)
        self.thickness_threshold = float(thickness_threshold)
        self.blend = float(blend)
        self.light_dir = (ld[0], ld[1], ld[2])
        self.compose_mode = compose_mode

    @classmethod
    def from_config(cls, cfg) -> "ContactShadowsPass":
        """Build from the standard ``cfg.lighting.contact_shadows`` block.

        All fields are optional — missing fields fall back to the
        dataclass defaults, which is also the back-compat path for
        configs created before round 13.
        """
        cs = getattr(cfg.lighting, "contact_shadows", None)
        if cs is None:
            return cls()
        return cls(
            samples=int(getattr(cs, "samples", 6)),
            max_distance=float(getattr(cs, "max_distance", 1.0)),
            thickness_threshold=float(
                getattr(cs, "thickness_threshold", 0.1),
            ),
            blend=float(getattr(cs, "blend", 0.7)),
            compose_mode=str(getattr(cs, "compose_mode", "max")),
        )

    def is_noop(self) -> bool:
        """``True`` when the pass should be skipped at composition time.

        ``samples == 0`` is the documented back-compat opt-out — when
        set, the executor skips the dispatch entirely and the main
        shadow term is forwarded unchanged.
        """
        return self.samples == 0

    # ----- UBO field-value adapter -----
    def _field_values(self) -> dict[str, Any]:
        return {
            "light_dir":    (self.light_dir[0], self.light_dir[1], self.light_dir[2]),
            "samples":      int(self.samples),
            "max_distance": float(self.max_distance),
            "thickness":    float(self.thickness_threshold),
            "blend":        float(self.blend),
            "compose_mode": _COMPOSE_MODES[self.compose_mode],
        }

    # NOTE: ``make_pass`` is inherited from :class:`PostProcessPassBase`
    # (no extra texture bindings beyond the standard ping/pong pair —
    # the depth buffer is sourced from the executor's shared G-buffer).
    # Contact shadows must run after the main CSM shadow pass; the
    # dependency is declared via ``DEPENDS_ON`` above.


__all__ = [
    "ContactShadowsPass",
    "compose_with_main_shadow",
    "ray_march_contact_shadow",
]
