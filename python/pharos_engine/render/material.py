"""Material dataclass — base color, PBR-ish knobs, alpha, textures."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class TextureHandle:
    """Opaque texture handle. ``gpu_texture`` is populated when wgpu is live."""

    id: int
    width: int
    height: int
    format: str = "rgba8unorm"
    gpu_texture: Any | None = None


_ALPHA_MODES = frozenset({"opaque", "blend", "mask"})


@dataclass
class Material:
    name: str = "default"
    base_color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    metallic: float = 0.0
    roughness: float = 0.5
    emissive: tuple[float, float, float] = (0.0, 0.0, 0.0)
    alpha_mode: str = "opaque"
    alpha_cutoff: float = 0.5
    base_color_texture: TextureHandle | None = None
    normal_texture: TextureHandle | None = None
    double_sided: bool = False

    def __post_init__(self) -> None:
        if self.alpha_mode not in _ALPHA_MODES:
            raise ValueError(
                f"Material.alpha_mode must be one of {sorted(_ALPHA_MODES)}, got {self.alpha_mode!r}"
            )
        if not (0.0 <= self.metallic <= 1.0):
            raise ValueError(f"Material.metallic must be in [0, 1], got {self.metallic}")
        if not (0.0 <= self.roughness <= 1.0):
            raise ValueError(f"Material.roughness must be in [0, 1], got {self.roughness}")
        if len(self.base_color) != 4:
            raise ValueError("Material.base_color must be an RGBA 4-tuple")
        if len(self.emissive) != 3:
            raise ValueError("Material.emissive must be an RGB 3-tuple")

    # ------------------------------------------------------------------
    def uniform_bytes(self) -> bytes:
        """Pack the material into 48 bytes for the shader UBO.

        Layout (std140-compatible, all float32):
            base_color   vec4       (16 B)
            emissive.xyz metallic   vec4 (16 B)
            roughness cutoff pad pad vec4 (16 B)
        """
        arr = np.zeros(12, dtype=np.float32)
        arr[0:4] = self.base_color
        arr[4:7] = self.emissive
        arr[7] = self.metallic
        arr[8] = self.roughness
        arr[9] = self.alpha_cutoff
        # arr[10], arr[11] = pad
        return arr.tobytes()

    # ------------------------------------------------------------------
    def emit_wgsl(self) -> str:
        """Return the WGSL uniform struct declaration used by the shaders."""
        return (
            "struct MaterialUBO {\n"
            "    base_color: vec4<f32>,\n"
            "    emissive_metallic: vec4<f32>,\n"
            "    rough_cutoff_pad: vec4<f32>,\n"
            "};\n"
        )
