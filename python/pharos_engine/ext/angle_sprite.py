"""Extension shim — re-exports from pharos_engine.angle_sprite.

This module's canonical home is SlapPyEngine.ext.angle_sprite.
Import via either path; both are supported.
"""
from pharos_engine.angle_sprite import (
    AngleEntry,
    AngleSpriteMap,
    make_angle_map_from_spritesheet,
)

__all__ = [
    "AngleEntry",
    "AngleSpriteMap",
    "make_angle_map_from_spritesheet",
]
