from __future__ import annotations
import struct
from .chain import PostProcessPass

_SHADER = "volumetric_fog.wgsl"
_ENTRY  = "main"

# VolumetricParams layout (132 bytes, std140):
#   inv_proj      : mat4x4<f32>   offset   0  (64 bytes)
#   fog_color     : vec3<f32>     offset  64  (12 bytes)
#   fog_density   : f32           offset  76
#   scatter_g     : f32           offset  80
#   fog_start     : f32           offset  84
#   fog_end       : f32           offset  88
#   sun_intensity : f32           offset  92
#   sun_dir       : vec3<f32>     offset  96  (12 bytes)
#   ambient       : f32           offset 108
#   num_steps     : u32           offset 112  — executor may override
#   width         : u32           offset 116  — executor fills
#   height        : u32           offset 120  — executor fills
#   time          : f32           offset 124
#   _pad          : f32           offset 128

_IDENTITY_MAT4 = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)
_DEFAULT_FOG_COLOR = (0.8, 0.85, 0.9)
_DEFAULT_SUN_DIR   = (0.0, -1.0, 0.0)


class VolumetricFog:
    label = "volumetric_fog"

    def __init__(
        self,
        density: float = 0.02,
        scatter: float = 0.5,
        absorption: float = 0.01,
        phase_g: float = 0.3,
        num_steps: int = 64,
        max_dist: float = 500.0,
        fog_start: float = 1.0,
        fog_color: tuple = _DEFAULT_FOG_COLOR,
        sun_dir: tuple = _DEFAULT_SUN_DIR,
        sun_intensity: float = 1.0,
        ambient: float = 0.1,
        time: float = 0.0,
        inv_proj: tuple = _IDENTITY_MAT4,
    ) -> None:
        self.density = density
        self.scatter = scatter
        self.absorption = absorption
        self.phase_g = phase_g
        self.num_steps = num_steps
        self.max_dist = max_dist
        self.fog_start = fog_start
        self.fog_color = fog_color
        self.sun_dir = sun_dir
        self.sun_intensity = sun_intensity
        self.ambient = ambient
        self.time = time
        self.inv_proj = inv_proj

    @classmethod
    def from_config(cls, cfg) -> "VolumetricFog":
        fog = cfg.rendering.volumetric_fog
        return cls(
            density=fog.density,
            scatter=fog.scatter,
            absorption=fog.absorption,
            phase_g=fog.phase_g,
            num_steps=fog.num_steps,
            max_dist=fog.max_dist,
        )

    def make_pass(self) -> PostProcessPass:
        fc = list(self.fog_color)[:3]
        sd = list(self.sun_dir)[:3]

        # Packs in exact field order from VolumetricParams (volumetric_fog.wgsl):
        #   inv_proj(16f) fog_color(3f) fog_density scatter_g fog_start fog_end
        #   sun_intensity sun_dir(3f) ambient(f) num_steps(I) width(I) height(I)
        #   time(_pad positions handled by executor splicing width/height)
        raw = struct.pack(
            "<16f3ffffff3ffIIIff",
            *self.inv_proj,     # inv_proj       offsets 0-63
            *fc,                # fog_color       offsets 64-75
            self.density,       # fog_density     offset 76
            self.phase_g,       # scatter_g       offset 80
            self.fog_start,     # fog_start       offset 84
            self.max_dist,      # fog_end         offset 88
            self.sun_intensity, # sun_intensity   offset 92
            *sd,                # sun_dir         offsets 96-107
            self.ambient,       # ambient         offset 108
            self.num_steps,     # num_steps u32   offset 112
            0,                  # width  u32      offset 116  — executor fills
            0,                  # height u32      offset 120  — executor fills
            self.time,          # time            offset 124
            0.0,                # _pad            offset 128
        )
        return PostProcessPass(
            shader_path=_SHADER,
            label=self.label,
            entry_point=_ENTRY,
            raw_params_bytes=raw,
        )
