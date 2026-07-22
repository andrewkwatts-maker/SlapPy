from __future__ import annotations

from .chain import PostProcessPass
from ._ubo import UboField, pack_struct

_SHADER = "motion_blur.wgsl"
_ENTRY  = "main"

# MotionBlurParams layout (32 bytes):
#   width        : u32     offset  0  — executor fills via runtime splice
#   height       : u32     offset  4  — executor fills via runtime splice
#   sample_count : u32     offset  8
#   strength     : f32     offset 12
#   _pad         : vec4u   offset 16  (16 bytes — std140 round-up to 32)
#
# Source of truth: :data:`_MOTION_BLUR_FIELDS` below.  The shared
# :func:`pack_struct` helper produces the exact same 32-byte blob the
# legacy ``struct.pack("<IIIfIIII", …)`` call did.  The trailing
# ``_pad`` vec4u is declared explicitly because the WGSL struct
# (``shaders/motion_blur.wgsl``) declares it — the std140 round-up
# alone would only pad to 16 bytes, but the shader expects 32.
_MOTION_BLUR_FIELDS = [
    UboField(name="width",        dtype="u32"),
    UboField(name="height",       dtype="u32"),
    UboField(name="sample_count", dtype="u32"),
    UboField(name="strength",     dtype="f32"),
    UboField(name="_pad",         dtype="vec4f"),
]


class MotionBlurPass:
    """Velocity-buffer multi-sample motion blur post-process pass.

    Parameters
    ----------
    sample_count:
        Number of samples marched along the velocity vector (default 8).
        Higher values produce smoother blur at the cost of GPU time.
    strength:
        Velocity scale factor.  1.0 = physically correct; >1.0 exaggerates blur.
    """

    label = "motion_blur"

    def __init__(
        self,
        sample_count: int = 8,
        strength: float = 1.0,
    ) -> None:
        self.sample_count = sample_count
        self.strength     = strength

    @classmethod
    def from_config(cls, cfg) -> "MotionBlurPass":
        mb = cfg.rendering.motion_blur
        return cls(
            sample_count=mb.sample_count,
            strength=mb.strength,
        )

    def make_pass(self, scene_tex, velocity_tex) -> PostProcessPass:
        # Pack MotionBlurParams via the shared :mod:`_ubo` helper.  The
        # width/height u32s are pre-zeroed; the executor splices the
        # actual resolution at dispatch time via byte-offset patching
        # (see :func:`executor._splice_runtime_params`).
        raw = pack_struct(
            _MOTION_BLUR_FIELDS,
            {
                "width":        0,
                "height":       0,
                "sample_count": int(self.sample_count),
                "strength":     float(self.strength),
                "_pad":         (0.0, 0.0, 0.0, 0.0),
            },
        )
        return PostProcessPass(
            shader_path=_SHADER,
            label=self.label,
            entry_point=_ENTRY,
            raw_params_bytes=raw,
            params={
                "scene_tex":    scene_tex,
                "velocity_tex": velocity_tex,
            },
        )
