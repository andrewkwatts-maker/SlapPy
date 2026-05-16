"""Extension shim — re-exports from playslap.lighting.

This module's canonical home is playslap.ext.lighting.
Import via either path; both are supported.
"""
from playslap.lighting import (
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
