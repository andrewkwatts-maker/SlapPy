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

The output is composed with the main CSM/PCSS shadow term using

    final_shadow = min(main_shadow, 1.0 - contact_shadow_strength * blend)

so the contact term *only* darkens — it can never make a pixel brighter
than the main shadow already says it should be.  This matches the
Bouvier 2014 recommendation that contact shadows are an additive
darkening, not a replacement, and keeps the round-12 Vogel-PCF
penumbra response intact in regions where there is no nearby contact.

The Python helper :func:`ray_march_contact_shadow` mirrors the WGSL
arithmetic bit-for-bit so the algorithm can be regression-tested
headlessly (no wgpu adapter required).
"""
from __future__ import annotations

import math
import struct
from typing import Tuple

from .chain import PostProcessPass
from ._validation import (
    validate_non_negative_float,
    validate_unit_interval,
)


_SHADER = "contact_shadows_depth.wgsl"
_ENTRY  = "main"

# ContactShadowsParams layout (32 bytes, std140-compatible):
#   light_dir        : vec3<f32>    offset  0   (12 bytes)
#   samples          : u32          offset 12   ( 4 bytes)
#   max_distance     : f32          offset 16   ( 4 bytes)
#   thickness        : f32          offset 20   ( 4 bytes)
#   blend            : f32          offset 24   ( 4 bytes)
#   _pad             : u32          offset 28   ( 4 bytes)
_PARAMS_FMT = "<3fIfffI"


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
) -> float:
    """Compose the contact-shadow strength with the main CSM term.

    The composition rule is::

        final = min(main_shadow, 1.0 - contact_strength * blend)

    which guarantees the contact term *only* darkens — a pixel that the
    main shadow says is fully lit can be partly darkened by contact, but
    a pixel that the main shadow says is fully shadowed cannot be made
    brighter.
    """
    return min(main_shadow, 1.0 - contact_strength * blend)


# ---------------------------------------------------------------------------
# Public pass object
# ---------------------------------------------------------------------------


class ContactShadowsPass:
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
    """

    label = "contact_shadows"

    def __init__(
        self,
        samples: int = 6,
        max_distance: float = 1.0,
        thickness_threshold: float = 0.1,
        blend: float = 0.7,
        light_dir: Tuple[float, float, float] = (0.0, -1.0, 0.0),
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

        self.samples = int(samples)
        self.max_distance = float(max_distance)
        self.thickness_threshold = float(thickness_threshold)
        self.blend = float(blend)
        self.light_dir = (ld[0], ld[1], ld[2])

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
        )

    def is_noop(self) -> bool:
        """``True`` when the pass should be skipped at composition time.

        ``samples == 0`` is the documented back-compat opt-out — when
        set, the executor skips the dispatch entirely and the main
        shadow term is forwarded unchanged.
        """
        return self.samples == 0

    def make_pass(self) -> PostProcessPass:
        """Return a :class:`PostProcessPass` ready for the chain."""
        raw = struct.pack(
            _PARAMS_FMT,
            self.light_dir[0],
            self.light_dir[1],
            self.light_dir[2],
            int(self.samples),
            float(self.max_distance),
            float(self.thickness_threshold),
            float(self.blend),
            0,  # _pad
        )
        return PostProcessPass(
            shader_path=_SHADER,
            label=self.label,
            entry_point=_ENTRY,
            raw_params_bytes=raw,
            # Contact shadows must run after the main CSM shadow pass
            # so the composition step can read the up-to-date shadow
            # mask.  The dependency name matches the ShadowCSM label.
            depends_on=["shadow_csm"],
        )


__all__ = [
    "ContactShadowsPass",
    "compose_with_main_shadow",
    "ray_march_contact_shadow",
]
