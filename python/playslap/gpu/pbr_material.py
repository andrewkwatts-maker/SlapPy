"""PBR metallic-roughness material for 3D-mode layers."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PbrMaterial:
    metallic: float = 0.0          # 0=dielectric, 1=metal
    roughness: float = 0.5         # 0=mirror, 1=rough
    albedo_color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    albedo_texture: Path | None = None    # path to PNG/JPG
    normal_map: Path | None = None        # tangent-space normal map
    emissive_color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    emissive_strength: float = 0.0
    ior: float = 1.5               # index of refraction (for Fresnel)

    def to_gpu_bytes(self) -> bytes:
        """Pack into a 48-byte std430 struct for GPU upload.

        Layout (12 × f32 = 48 bytes):
          vec4  albedo_color        (16 bytes)
          f32   metallic            ( 4 bytes)
          f32   roughness           ( 4 bytes)
          f32   ior                 ( 4 bytes)
          f32   _pad0               ( 4 bytes)
          vec3  emissive_color      (12 bytes)
          f32   emissive_strength   ( 4 bytes)
        """
        import struct
        return struct.pack(
            "4f2f2f3ff",
            *self.albedo_color,
            self.metallic, self.roughness,
            self.ior, 0.0,          # _pad0 to reach 12-float boundary
            *self.emissive_color,
            self.emissive_strength,
        )
