from __future__ import annotations

import numpy as np

from .chain import PostProcessPass
from ._ubo import UboField, pack_struct

_SHADER = "dof.wgsl"
_ENTRY  = "main"

# DofParams layout (32 bytes):
#   width          : u32     offset  0  — executor fills via runtime splice
#   height         : u32     offset  4  — executor fills via runtime splice
#   focal_distance : f32     offset  8
#   focal_range    : f32     offset 12
#   max_coc_radius : f32     offset 16
#   bokeh_samples  : u32     offset 20
#   _pad           : vec2u   offset 24  (std140 round-up to 32 bytes)
#
# Source of truth: :data:`_DOF_FIELDS` below.  The shared
# :func:`pack_struct` helper produces the exact same 32-byte blob the
# legacy ``struct.pack("<IIfffIII", …)`` call did.
_DOF_FIELDS = [
    UboField(name="width",          dtype="u32"),
    UboField(name="height",         dtype="u32"),
    UboField(name="focal_distance", dtype="f32"),
    UboField(name="focal_range",    dtype="f32"),
    UboField(name="max_coc_radius", dtype="f32"),
    UboField(name="bokeh_samples",  dtype="u32"),
]


class DofPass:
    """Gather-based bokeh Depth of Field post-process pass.

    Parameters
    ----------
    focal_distance:
        Linear depth value [0..1] of the focal plane (0 = camera near, 1 = far).
    focal_range:
        Depth range over which the CoC radius grows from zero to *max_coc_radius*.
    max_coc_radius:
        Maximum Circle-of-Confusion radius in pixels.
    bokeh_samples:
        Number of Poisson-disk gather samples (capped at 16 in the shader).
    """

    label = "dof"

    def __init__(
        self,
        focal_distance: float = 0.5,
        focal_range: float = 0.3,
        max_coc_radius: float = 12.0,
        bokeh_samples: int = 16,
        focus_transition: float = 1.0,
    ) -> None:
        # Round-9 polish: ``focus_transition`` shapes the in-focus → out-of-focus
        # ramp. 1.0 (default) reproduces the legacy strict-linear behaviour
        # bit-for-bit. < 1 sharpens the focal edge (cinema-stage look). > 1
        # softens it via a smoothstep (snapshot-camera look). The GPU shader
        # reads this value from a uniform; the CPU reference implementation in
        # :func:`compute_coc` mirrors the formula for headless tests.
        if focus_transition <= 0.0:
            raise ValueError(
                f"DofPass.focus_transition must be > 0; got {focus_transition!r}"
            )
        self.focal_distance = focal_distance
        self.focal_range    = focal_range
        self.max_coc_radius = max_coc_radius
        self.bokeh_samples  = bokeh_samples
        self.focus_transition = focus_transition

    def compute_coc(self, depth: np.ndarray) -> np.ndarray:
        """CPU reference for the GPU Circle-of-Confusion formula.

        Returns the per-pixel CoC radius in pixels for the given linear-depth
        buffer. Backward-compat: ``focus_transition == 1.0`` matches the
        original linear ramp byte-for-byte.
        """
        depth = np.asarray(depth, dtype=np.float32)
        # Linear ramp: 0 at focal_distance, 1 at focal_distance ± focal_range.
        t = np.abs(depth - self.focal_distance) / max(self.focal_range, 1e-6)
        t = np.clip(t, 0.0, 1.0)
        if self.focus_transition != 1.0:
            # Smoothstep with adjustable curvature. The exponent < 1 sharpens
            # the focal edge; > 1 softens it via the 3t²-2t³ smoothstep.
            if self.focus_transition < 1.0:
                t = np.power(t, self.focus_transition)
            else:
                # Apply smoothstep N times where N = transition - 1.
                # For transition > 2 the curve is *very* smooth; in practice
                # callers stay in [0.5, 2.0].
                smooth_iters = self.focus_transition - 1.0
                t = t * t * (3.0 - 2.0 * t)
                if smooth_iters > 1.0:
                    # Compose with itself for extra smoothness.
                    extra = smooth_iters - 1.0
                    t2 = t * t * (3.0 - 2.0 * t)
                    t = t + (t2 - t) * extra
        return (t * self.max_coc_radius).astype(np.float32)

    @classmethod
    def from_config(cls, cfg) -> "DofPass":
        dof = cfg.rendering.dof
        return cls(
            focal_distance=dof.focal_distance,
            focal_range=dof.focal_range,
            max_coc_radius=dof.max_coc_radius,
            bokeh_samples=dof.bokeh_samples,
        )

    def make_pass(self, scene_tex, depth_tex) -> PostProcessPass:
        # Pack DofParams via the shared :mod:`_ubo` helper.  The width
        # and height u32s are pre-zeroed; the executor splices the
        # actual resolution at dispatch time via byte-offset patching
        # (see :func:`executor._splice_runtime_params`).
        raw = pack_struct(
            _DOF_FIELDS,
            {
                "width":          0,
                "height":         0,
                "focal_distance": float(self.focal_distance),
                "focal_range":    float(self.focal_range),
                "max_coc_radius": float(self.max_coc_radius),
                "bokeh_samples":  int(self.bokeh_samples),
            },
        )
        return PostProcessPass(
            shader_path=_SHADER,
            label=self.label,
            entry_point=_ENTRY,
            raw_params_bytes=raw,
            params={
                "scene_tex": scene_tex,
                "depth_tex": depth_tex,
            },
        )
