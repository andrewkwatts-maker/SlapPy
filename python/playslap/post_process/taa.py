from __future__ import annotations
import struct
from .chain import PostProcessPass

_SHADER = "taa_resolve.wgsl"
_ENTRY  = "taa_resolve_main"

# TaaParams layout (16 bytes):
#   blend_factor : f32   offset  0
#   sharpening   : f32   offset  4
#   width        : u32   offset  8  — executor splices actual resolution at runtime
#   height       : u32   offset 12


class TAAPass:
    label = "taa"

    def __init__(
        self,
        alpha: float = 0.1,
        variance_clip_gamma: float = 1.0,
        motion_weight: float = 1.0,
    ) -> None:
        # blend_factor = alpha (fraction of current frame blended in).
        # variance_clip_gamma and motion_weight are kept for API completeness;
        # the current shader encodes them implicitly via sharpening (gamma) and
        # the motion-vector weight is baked into the reprojection.
        self.alpha = alpha
        self.sharpening = max(0.0, variance_clip_gamma - 1.0)
        self.motion_weight = motion_weight

    @classmethod
    def from_config(cls, cfg) -> "TAAPass":
        taa = cfg.rendering.taa
        return cls(
            alpha=taa.alpha,
            variance_clip_gamma=taa.variance_clip_gamma,
            motion_weight=taa.motion_weight,
        )

    def make_pass(self, frame_tex, history_tex, motion_tex) -> PostProcessPass:
        raw = struct.pack(
            "<ffII",
            self.alpha,
            self.sharpening,
            0,   # width  — executor fills these in
            0,   # height
        )
        return PostProcessPass(
            shader_path=_SHADER,
            label=self.label,
            entry_point=_ENTRY,
            raw_params_bytes=raw,
            params={
                "frame_tex":   frame_tex,
                "history_tex": history_tex,
                "motion_tex":  motion_tex,
            },
        )
