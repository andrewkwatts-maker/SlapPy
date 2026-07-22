"""Volumetric fog post-process pass."""
from __future__ import annotations

from typing import Any

from ._pass_base import PostProcessPassBase
from ._ubo import UboField


_SHADER = "volumetric_fog.wgsl"
_ENTRY  = "main"

_IDENTITY_MAT4 = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)
_DEFAULT_FOG_COLOR = (0.8, 0.85, 0.9)
_DEFAULT_SUN_DIR   = (0.0, -1.0, 0.0)


# VolumetricParams std140 layout — 132 bytes (matches the WGSL struct
# byte-for-byte; the trailing _pad : f32 leaves the total at 132,
# *not* rounded up to 144, to preserve legacy byte parity).
_VFOG_UBO_FIELDS = [
    UboField(name="inv_proj_r0",   dtype="vec4f", offset=0),
    UboField(name="inv_proj_r1",   dtype="vec4f", offset=16),
    UboField(name="inv_proj_r2",   dtype="vec4f", offset=32),
    UboField(name="inv_proj_r3",   dtype="vec4f", offset=48),
    UboField(name="fog_color",     dtype="vec3f", offset=64),
    UboField(name="fog_density",   dtype="f32",   offset=76),
    UboField(name="scatter_g",     dtype="f32",   offset=80),
    UboField(name="fog_start",     dtype="f32",   offset=84),
    UboField(name="fog_end",       dtype="f32",   offset=88),
    UboField(name="sun_intensity", dtype="f32",   offset=92),
    UboField(name="sun_dir",       dtype="vec3f", offset=96),
    UboField(name="ambient",       dtype="f32",   offset=108),
    UboField(name="num_steps",     dtype="u32",   offset=112),
    UboField(name="width",         dtype="u32",   offset=116),
    UboField(name="height",        dtype="u32",   offset=120),
    UboField(name="time",          dtype="f32",   offset=124),
    UboField(name="_pad",          dtype="f32",   offset=128),
]


class VolumetricFog(PostProcessPassBase):
    label = "volumetric_fog"

    # ----- PostProcessPassBase declarative schema -----
    SHADER = _SHADER
    ENTRY = _ENTRY
    PARAMS_LAYOUT = _VFOG_UBO_FIELDS
    # 132-byte legacy layout — BLOB_SIZE trims the helper's std140
    # round-up (which would otherwise push the buffer to 144 bytes).
    BLOB_SIZE = 132

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

    # ----- UBO field-value adapter -----
    def _field_values(self) -> dict[str, Any]:
        m = self.inv_proj
        fc = list(self.fog_color)[:3]
        while len(fc) < 3:
            fc.append(0.0)
        sd = list(self.sun_dir)[:3]
        while len(sd) < 3:
            sd.append(0.0)
        return {
            "inv_proj_r0":   (float(m[0]),  float(m[1]),  float(m[2]),  float(m[3])),
            "inv_proj_r1":   (float(m[4]),  float(m[5]),  float(m[6]),  float(m[7])),
            "inv_proj_r2":   (float(m[8]),  float(m[9]),  float(m[10]), float(m[11])),
            "inv_proj_r3":   (float(m[12]), float(m[13]), float(m[14]), float(m[15])),
            "fog_color":     (float(fc[0]), float(fc[1]), float(fc[2])),
            "fog_density":   float(self.density),
            "scatter_g":     float(self.phase_g),
            "fog_start":     float(self.fog_start),
            "fog_end":       float(self.max_dist),
            "sun_intensity": float(self.sun_intensity),
            "sun_dir":       (float(sd[0]), float(sd[1]), float(sd[2])),
            "ambient":       float(self.ambient),
            "num_steps":     int(self.num_steps),
            # width/height filled by executor splice at dispatch time.
            "width":         0,
            "height":        0,
            "time":          float(self.time),
            "_pad":          0,
        }
