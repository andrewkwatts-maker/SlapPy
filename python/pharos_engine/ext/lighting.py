"""Extension shim — re-exports from pharos_engine.lighting.

This module's canonical home is Pharos Engine.ext.lighting.
Import via either path; both are supported.
"""
from pharos_engine.lighting import (
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
