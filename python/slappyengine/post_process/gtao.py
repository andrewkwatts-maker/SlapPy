from __future__ import annotations
import struct
from .chain import PostProcessPass

_SHADER = "ao_gtao.wgsl"
_ENTRY  = "ao_gtao_main"

# GtaoParams layout (96 bytes):
#   inv_proj         : mat4x4<f32>   offset  0  (64 bytes)
#   radius           : f32           offset 64
#   max_pixel_radius : f32           offset 68
#   num_directions   : u32           offset 72
#   num_steps        : u32           offset 76
#   power            : f32           offset 80
#   bias             : f32           offset 84
#   width            : u32           offset 88  — executor splices actual resolution
#   height           : u32           offset 92

_IDENTITY_MAT4 = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)


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

    @classmethod
    def from_config(cls, cfg) -> "GTAOPass":
        ao = cfg.rendering.gtao
        return cls(
            num_directions=ao.num_directions,
            num_steps=ao.num_steps,
            radius=ao.radius,
            intensity=ao.intensity,
            bias=ao.bias,
        )

    def make_pass(self, depth_tex, normal_tex) -> PostProcessPass:
        raw = struct.pack(
            "<16fffIIffII",
            *self.inv_proj,
            self.radius,
            self.max_pixel_radius,
            self.num_directions,
            self.num_steps,
            self.power,
            self.bias,
            0,   # width  — executor fills these in
            0,   # height
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
