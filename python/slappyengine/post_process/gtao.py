from __future__ import annotations
import math
import struct
from .chain import PostProcessPass

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
#   _pad0             : u32           offset 104
#   _pad1             : u32           offset 108

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
    ) -> None:
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

    def make_pass(self, depth_tex, normal_tex) -> PostProcessPass:
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
            0,   # _pad0
            0,   # _pad1
        )
        return PostProcessPass(
            shader_path=_SHADER,
            label=self.label,
            entry_point=_ENTRY,
            raw_params_bytes=raw,
            params={
                "depth_tex":  depth_tex,
                "normal_tex": normal_tex,
            },
        )
