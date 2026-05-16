"""Extension shim — re-exports from slappyengine.lighting.

This module's canonical home is slappyengine.ext.lighting.
Import via either path; both are supported.
"""
from slappyengine.lighting import (
    LightingSystem,
    DirectionalLight,
    PointLight,
    ConeLight,
    ShapeLight,
    FlashLight,
    GravityWarpSource,
    RadianceCascadeConfig,
)

__all__ = [
    "LightingSystem",
    "DirectionalLight",
    "PointLight",
    "ConeLight",
    "ShapeLight",
    "FlashLight",
    "GravityWarpSource",
    "RadianceCascadeConfig",
]
