from __future__ import annotations
import math
import struct
from .chain import PostProcessPass
from ._validation import (
    validate_bool,
    validate_mat4_tuple,
    validate_non_negative_float,
    validate_positive_float,
    validate_positive_int,
    validate_unit_interval,
)

_SHADER = "ao_gtao.wgsl"
_ENTRY  = "ao_gtao_main"

# GtaoParams layout (112 bytes):
#   inv_proj          : mat4x4<f32>   offset   0  (64 bytes)
#   radius            : f32           offset  64
#   max_pixel_radius  : f32           offset  68
#   num_directions    : u32           offset  72
#   num_steps         : u32           offset  76
#   power             : f32           offset  80
#   bias              : f32           offset  84
#   width             : u32           offset  88  — executor splices actual resolution
#   height            : u32           offset  92
#   depth_falloff     : f32           offset  96  — Jimenez 2016 distance scale (m⁻¹)
#   min_radius_scale  : f32           offset 100  — lower bound on per-pixel scale (0..1)
#   multibounce       : u32           offset 104  — Jimenez 2016 §2.3 multibounce toggle
#   _pad0             : u32           offset 108

_IDENTITY_MAT4 = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)


def compute_adaptive_radius(
    world_radius: float,
    view_depth: float,
    depth_falloff: float,
    min_radius_scale: float = 0.25,
    max_radius_scale: float = 1.0,
) -> float:
    """Return a per-pixel adapted AO radius (Jimenez 2016, "Practical Realtime
    Strategies for Accurate Indirect Occlusion", SIGGRAPH 2016).

    The trick: at very close range we want a *small* radius so we capture fine
    crevices and contact shadows; at far range we want a *large* radius so we
    capture broad ambient occlusion without aliasing.  The scale follows

        scale = clamp(1 - exp(-depth_falloff * view_depth), min_scale, max_scale)

    so a falloff of 0 yields the legacy behaviour (`scale == max_scale`, with
    Python's `max(min_scale, max_scale)` collapsing the clamp to a no-op below).
    Practical falloff values are in the 0.05–0.5 m⁻¹ range — small numbers
    because the curve saturates exponentially.

    Parameters
    ----------
    world_radius : float
        Base GTAO world-space radius in metres (e.g. 0.5).
    view_depth : float
        View-space Z of the pixel (always non-negative, in metres).
    depth_falloff : float
        Adaptation strength (m⁻¹).  0 disables adaptation entirely.
    min_radius_scale : float
        Lower bound on the per-pixel scale, typically 0.25 to avoid degenerate
        radii on the near plane.
    max_radius_scale : float
        Upper bound on the per-pixel scale, typically 1.0.

    Returns
    -------
    float
        Adapted world-space radius (`world_radius * scale`).
    """
    if depth_falloff <= 0.0:
        # Legacy path: no per-pixel scaling.  Bypass the clamp so the result is
        # exactly `world_radius`, matching the pre-adaptive shader behaviour.
        return float(world_radius)

    z = max(0.0, float(view_depth))
    raw_scale = 1.0 - math.exp(-depth_falloff * z)
    scale = min(max_radius_scale, max(min_radius_scale, raw_scale))
    return float(world_radius) * scale


def multibounce_visibility(
    visibility: float,
    albedo: float,
) -> float:
    """Jiménez 2016 §2.3 multibounce AO approximation.

    Approximates indirect light bouncing off a coloured surface back into the
    occluded crevices.  Single-bounce GTAO only attenuates the *direct* ambient
    term; a white plaster wall and a black velvet wall would receive the same
    occlusion factor, which looks unrealistically dark on bright albedos.  The
    fit reconstructs the multi-bounce contribution as a cubic polynomial in the
    single-bounce visibility, modulated by albedo:

        f(v) = a·v² + b·v + c
        a    =  2.0404·albedo - 0.3324
        b    = -4.7951·albedo + 0.6417
        c    =  2.7552·albedo + 0.6903
        out  = max(v, lerp(v, v · f(v), albedo))

    Properties (also asserted by the regression suite):
      * at ``albedo = 0`` the lerp is a no-op → output equals ``v`` exactly;
      * at any albedo the ``max`` clamp keeps multibounce ≥ single-bounce;
      * at ``albedo = 1, v = 0.5`` the polynomial brightens crevices above 0.5.

    Parameters
    ----------
    visibility : float
        Single-bounce visibility in ``[0, 1]``  (1 = fully lit, 0 = occluded).
    albedo : float
        Per-channel albedo in ``[0, 1]``.  Call once per RGB channel.

    Returns
    -------
    float
        Multibounce visibility in ``[0, 1]``, always ≥ ``visibility``.
    """
    v = float(visibility)
    al = float(albedo)
    a = 2.0404 * al - 0.3324
    b = -4.7951 * al + 0.6417
    c = 2.7552 * al + 0.6903
    poly = (a * v + b) * v + c
    bounced = v * poly
    # lerp(v, bounced, albedo)
    blended = v + (bounced - v) * al
    return max(v, blended)


class GTAOPass:
    label = "gtao"

    def __init__(
        self,
        num_directions: int = 8,
        num_steps: int = 4,
        radius: float = 2.0,
        intensity: float = 1.0,
        bias: float = 0.05,
        max_pixel_radius: float = 64.0,
        inv_proj: tuple = _IDENTITY_MAT4,
        depth_falloff: float = 0.0,
        min_radius_scale: float = 0.25,
        multibounce: bool = True,
    ) -> None:
        """Construct a GTAO ambient-occlusion pass.

        Raises
        ------
        TypeError
            If any numeric kwarg is the wrong type (bools/strings refused).
        ValueError
            If any positive-only kwarg (``num_directions``, ``num_steps``,
            ``radius``, ``intensity``, ``max_pixel_radius``) is ≤ 0;
            if ``bias`` / ``depth_falloff`` are negative or NaN/inf; if
            ``min_radius_scale`` is outside ``[0, 1]``; if ``inv_proj``
            is not a 16-element matrix of finite floats.
        """
        validate_positive_int(
            "num_directions", "GTAOPass", num_directions,
        )
        validate_positive_int("num_steps", "GTAOPass", num_steps)
        validate_positive_float("radius", "GTAOPass", radius)
        validate_positive_float("intensity", "GTAOPass", intensity)
        validate_non_negative_float("bias", "GTAOPass", bias)
        validate_positive_float(
            "max_pixel_radius", "GTAOPass", max_pixel_radius,
        )
        validate_mat4_tuple("inv_proj", "GTAOPass", inv_proj)
        validate_non_negative_float(
            "depth_falloff", "GTAOPass", depth_falloff,
        )
        validate_unit_interval(
            "min_radius_scale", "GTAOPass", min_radius_scale,
        )
        validate_bool("multibounce", "GTAOPass", multibounce)

        self.num_directions = num_directions
        self.num_steps = num_steps
        self.radius = radius
        # intensity maps to the power curve: higher intensity → lower power exponent
        # so the AO darkens faster.  power=1/intensity keeps full-lit at 1.0.
        self.power = 1.0 / max(intensity, 1e-6)
        self.bias = bias
        self.max_pixel_radius = max_pixel_radius
        self.inv_proj = inv_proj
        # Distance-aware AO knobs (Jimenez 2016).  depth_falloff=0 → off.
        self.depth_falloff = float(depth_falloff)
        self.min_radius_scale = float(min_radius_scale)
        # Jimenez 2016 §2.3 multibounce approximation toggle.  When True (the
        # default) the shader reads albedo from the G-buffer and brightens
        # crevice visibility per channel to model indirect bounce light.
        self.multibounce = bool(multibounce)

    @classmethod
    def from_config(cls, cfg) -> "GTAOPass":
        ao = cfg.rendering.gtao
        return cls(
            num_directions=ao.num_directions,
            num_steps=ao.num_steps,
            radius=ao.radius,
            intensity=ao.intensity,
            bias=ao.bias,
            depth_falloff=getattr(ao, "depth_falloff", 0.0),
            min_radius_scale=getattr(ao, "min_radius_scale", 0.25),
            multibounce=bool(getattr(ao, "multibounce", True)),
        )

    def adaptive_radius(self, view_depth: float) -> float:
        """Return the per-pixel world-space radius at a given view-space depth.

        Thin wrapper around :func:`compute_adaptive_radius` that fills in the
        pass's current parameters.  Mirrors the WGSL implementation byte-for-byte.
        """
        return compute_adaptive_radius(
            self.radius,
            view_depth,
            self.depth_falloff,
            self.min_radius_scale,
        )

    def make_pass(self, depth_tex, normal_tex, albedo_tex=None) -> PostProcessPass:
        """Build a :class:`PostProcessPass` for the GTAO resolve.

        ``albedo_tex`` is optional: callers that don't yet expose a G-buffer
        albedo target may pass ``None`` and the shader will fall back to a
        neutral albedo (vec3(1.0)) for the multibounce term, which still
        bounds correctly against the single-bounce visibility.
        """
        raw = struct.pack(
            "<16fffIIffIIffII",
            *self.inv_proj,
            self.radius,
            self.max_pixel_radius,
            self.num_directions,
            self.num_steps,
            self.power,
            self.bias,
            0,   # width  — executor fills these in
            0,   # height
            self.depth_falloff,
            self.min_radius_scale,
            1 if self.multibounce else 0,  # multibounce toggle (u32)
            0,                              # _pad0
        )
        return PostProcessPass(
            shader_path=_SHADER,
            label=self.label,
            entry_point=_ENTRY,
            raw_params_bytes=raw,
            params={
                "depth_tex":  depth_tex,
                "normal_tex": normal_tex,
                "albedo_tex": albedo_tex,
            },
        )
