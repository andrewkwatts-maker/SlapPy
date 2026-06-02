"""Cascaded Shadow Maps (CSM) post-process pass."""
from __future__ import annotations

from typing import Any

from ._pass_base import PostProcessPassBase
from ._ubo import UboField


_SHADER = "shadow_csm.wgsl"
_ENTRY  = "main"

_IDENTITY_MAT4 = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)
_DEFAULT_CASCADE_VPS = _IDENTITY_MAT4 * 4
_DEFAULT_SPLIT_DISTS = (10.0, 30.0, 90.0, 270.0)
_DEFAULT_LIGHT_DIR   = (0.0, -1.0, 0.0)


# CsmParams std140 layout (320 bytes).  The four 4×4 cascade view-projection
# matrices occupy the first 256 bytes; we encode each row as a vec4f so the
# packer can place them on 16-byte boundaries without bespoke mat4 support.
_CSM_UBO_FIELDS = [
    # cascade_vp[4] — 4 mats × 4 rows = 16 vec4f entries (256 bytes).
    *[
        UboField(name=f"cascade_vp_{m}_r{r}", dtype="vec4f", offset=m * 64 + r * 16)
        for m in range(4) for r in range(4)
    ],
    UboField(name="split_dists",  dtype="vec4f", offset=256),
    UboField(name="light_dir",    dtype="vec3f", offset=272),
    UboField(name="num_cascades", dtype="u32",   offset=284),
    UboField(name="depth_bias",   dtype="f32",   offset=288),
    UboField(name="pcf_radius",   dtype="f32",   offset=292),
    UboField(name="width",        dtype="u32",   offset=296),
    UboField(name="height",       dtype="u32",   offset=300),
    UboField(name="pcss_enabled", dtype="u32",   offset=304),
    UboField(name="light_size",   dtype="f32",   offset=308),
    UboField(name="near",         dtype="f32",   offset=312),
    UboField(name="pcf_samples",  dtype="u32",   offset=316),
]


class ShadowCSM(PostProcessPassBase):
    label = "shadow_csm"

    # ----- PostProcessPassBase declarative schema -----
    SHADER = _SHADER
    ENTRY = _ENTRY
    PARAMS_LAYOUT = _CSM_UBO_FIELDS
    BLOB_SIZE = 320

    def __init__(
        self,
        num_cascades: int = 4,
        pcss_enabled: bool = True,
        light_size: float = 0.05,
        near: float = 0.1,
        depth_bias: float = 0.005,
        pcf_radius: float = 1.5,
        pcf_samples: int = 16,
        split_dists: tuple = _DEFAULT_SPLIT_DISTS,
        light_dir: tuple = _DEFAULT_LIGHT_DIR,
        cascade_vps: tuple = _DEFAULT_CASCADE_VPS,
    ) -> None:
        if not isinstance(pcf_samples, int) or isinstance(pcf_samples, bool):
            raise TypeError(
                f"pcf_samples must be an int (Vogel-disk tap count), got "
                f"{type(pcf_samples).__name__}"
            )
        if pcf_samples < 0:
            raise ValueError(
                f"pcf_samples must be >= 0 (0 = legacy 3×3 grid), got "
                f"{pcf_samples}"
            )

        self.num_cascades = num_cascades
        self.pcss_enabled = pcss_enabled
        self.light_size = light_size
        self.near = near
        self.depth_bias = depth_bias
        self.pcf_radius = pcf_radius
        self.pcf_samples = pcf_samples
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
            pcf_samples=getattr(lighting, "pcf_samples", 16),
        )

    # ----- UBO field-value adapter -----
    def _field_values(self) -> dict[str, Any]:
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

        out: dict[str, Any] = {
            "split_dists":  (float(sd[0]), float(sd[1]), float(sd[2]), float(sd[3])),
            "light_dir":    (float(ld[0]), float(ld[1]), float(ld[2])),
            "num_cascades": int(self.num_cascades),
            "depth_bias":   float(self.depth_bias),
            "pcf_radius":   float(self.pcf_radius),
            # width/height filled by executor splice at dispatch time.
            "width":        0,
            "height":       0,
            "pcss_enabled": int(bool(self.pcss_enabled)),
            "light_size":   float(self.light_size),
            "near":         float(self.near),
            "pcf_samples":  int(self.pcf_samples),
        }
        # Four cascade view-projection matrices, each laid out as four rows.
        for m in range(4):
            base = m * 16
            for r in range(4):
                out[f"cascade_vp_{m}_r{r}"] = (
                    float(vps[base + r * 4 + 0]),
                    float(vps[base + r * 4 + 1]),
                    float(vps[base + r * 4 + 2]),
                    float(vps[base + r * 4 + 3]),
                )
        return out
