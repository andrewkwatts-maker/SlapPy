"""Light dataclass + fixed-layout aggregator for the shader UBO.

The renderer defaults to *unlit* rendering (base_color × ambient) until at
least one non-ambient light is added — matches the user's spec:
    "defaults are unlit until a light is added".
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


_KINDS = {"directional": 0, "point": 1, "spot": 2, "ambient": 3}


@dataclass
class Light:
    kind: str = "directional"
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    direction: tuple[float, float, float] = (0.0, -1.0, 0.0)
    color: tuple[float, float, float] = (1.0, 1.0, 1.0)
    intensity: float = 1.0
    range: float = 20.0
    spot_angle: float = math.pi / 4.0

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(
                f"Light.kind must be one of {sorted(_KINDS)}, got {self.kind!r}"
            )

    @property
    def kind_id(self) -> int:
        return _KINDS[self.kind]


# ----------------------------------------------------------------------
# UBO packing — 4 lights + ambient
# ----------------------------------------------------------------------
MAX_LIGHTS = 4  # Blinn-Phong path packs up to 4 non-ambient lights.

# Per light: 4 vec4 = 64 B → 4 × 64 = 256 B; plus ambient vec4 = 16 B; totals 272 B.
LIGHT_UBO_FLOATS = MAX_LIGHTS * 16 + 4


def pack_lights_ubo(lights: list[Light]) -> np.ndarray:
    """Pack a list of lights into a flat float32 array for the shader.

    Layout (per non-ambient slot, 16 floats):
        [ pos.xyz , kind_id ,
          dir.xyz , range   ,
          color.xyz , intensity,
          spot_cos , enabled , pad, pad ]
    Followed by a single ambient vec4 ``(ambient_rgb, ambient_intensity)``.
    Unused slots have ``enabled = 0``.
    """
    arr = np.zeros(LIGHT_UBO_FLOATS, dtype=np.float32)
    ambient_rgb = np.zeros(3, dtype=np.float32)
    ambient_intensity = 0.0

    slot = 0
    for light in lights:
        if light.kind == "ambient":
            ambient_rgb += np.asarray(light.color, dtype=np.float32) * light.intensity
            ambient_intensity = max(ambient_intensity, float(light.intensity))
            continue
        if slot >= MAX_LIGHTS:
            continue
        base = slot * 16
        arr[base + 0:base + 3] = light.position
        arr[base + 3] = float(light.kind_id)
        arr[base + 4:base + 7] = _normalize(light.direction)
        arr[base + 7] = float(light.range)
        arr[base + 8:base + 11] = light.color
        arr[base + 11] = float(light.intensity)
        arr[base + 12] = math.cos(light.spot_angle)
        arr[base + 13] = 1.0
        slot += 1

    arr[MAX_LIGHTS * 16 + 0:MAX_LIGHTS * 16 + 3] = ambient_rgb
    arr[MAX_LIGHTS * 16 + 3] = ambient_intensity
    return arr


def _normalize(v: tuple[float, float, float]) -> tuple[float, float, float]:
    arr = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(arr))
    if n < 1e-8:
        return (0.0, -1.0, 0.0)
    return tuple((arr / n).tolist())


def is_unlit(lights: list[Light]) -> bool:
    """True when the scene has no non-ambient lights (per user's default)."""
    return not any(l.kind != "ambient" for l in lights)
