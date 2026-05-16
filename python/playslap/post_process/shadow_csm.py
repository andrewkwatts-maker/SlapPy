from __future__ import annotations
import struct
from .chain import PostProcessPass

_SHADER = "shadow_csm.wgsl"
_ENTRY  = "main"

# CsmParams layout (320 bytes, std140):
#   cascade_vp   : array<mat4x4<f32>, 4>   offset   0  (256 bytes)
#   split_dists  : vec4<f32>               offset 256  ( 16 bytes)
#   light_dir    : vec3<f32>               offset 272  ( 12 bytes)
#   num_cascades : u32                     offset 284  (  4 bytes)
#   depth_bias   : f32                     offset 288  (  4 bytes)
#   pcf_radius   : f32                     offset 292  (  4 bytes)
#   width        : u32                     offset 296  (  4 bytes)  — executor fills
#   height       : u32                     offset 300  (  4 bytes)  — executor fills
#   pcss_enabled : u32                     offset 304  (  4 bytes)
#   light_size   : f32                     offset 308  (  4 bytes)
#   near         : f32                     offset 312  (  4 bytes)
#   _pad         : u32                     offset 316  (  4 bytes)

_IDENTITY_MAT4 = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)
_DEFAULT_CASCADE_VPS = _IDENTITY_MAT4 * 4
_DEFAULT_SPLIT_DISTS = (10.0, 30.0, 90.0, 270.0)
_DEFAULT_LIGHT_DIR   = (0.0, -1.0, 0.0)


class ShadowCSM:
    label = "shadow_csm"

    def __init__(
        self,
        num_cascades: int = 4,
        pcss_enabled: bool = True,
        light_size: float = 0.05,
        near: float = 0.1,
        depth_bias: float = 0.005,
        pcf_radius: float = 1.5,
        split_dists: tuple = _DEFAULT_SPLIT_DISTS,
        light_dir: tuple = _DEFAULT_LIGHT_DIR,
        cascade_vps: tuple = _DEFAULT_CASCADE_VPS,
    ) -> None:
        self.num_cascades = num_cascades
        self.pcss_enabled = pcss_enabled
        self.light_size = light_size
        self.near = near
        self.depth_bias = depth_bias
        self.pcf_radius = pcf_radius
        self.split_dists = split_dists
        self.light_dir = light_dir
        self.cascade_vps = cascade_vps

    @classmethod
    def from_config(cls, cfg) -> "ShadowCSM":
        lighting = cfg.lighting
        return cls(
            num_cascades=lighting.num_shadow_cascades,
            pcss_enabled=bool(lighting.pcss_enabled),
            light_size=lighting.shadow_softness,
            near=lighting.shadow_near,
            depth_bias=lighting.shadow_depth_bias,
            pcf_radius=lighting.pcf_radius,
        )

    def make_pass(self) -> PostProcessPass:
        # Pad cascade_vps to exactly 4 matrices (64 floats) regardless of num_cascades.
        vps = list(self.cascade_vps)
        while len(vps) < 64:
            vps.extend(_IDENTITY_MAT4)
        vps = vps[:64]

        sd = list(self.split_dists)
        while len(sd) < 4:
            sd.append(0.0)
        sd = sd[:4]

        ld = list(self.light_dir)
        while len(ld) < 3:
            ld.append(0.0)
        ld = ld[:3]

        raw = struct.pack(
            "<64f4f3fIffIIIffI",
            *vps,           # cascade_vp   (256 bytes)
            *sd,            # split_dists  ( 16 bytes)
            *ld,            # light_dir    ( 12 bytes)
            self.num_cascades,       # u32
            self.depth_bias,         # f32
            self.pcf_radius,         # f32
            0,              # width        — executor fills
            0,              # height       — executor fills
            int(self.pcss_enabled),  # pcss_enabled u32
            self.light_size,         # f32
            self.near,               # f32
            0,              # _pad         u32
        )
        return PostProcessPass(
            shader_path=_SHADER,
            label=self.label,
            entry_point=_ENTRY,
            raw_params_bytes=raw,
        )
