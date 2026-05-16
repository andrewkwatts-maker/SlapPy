"""Extension shim — re-exports from slappyengine.angle_sprite.

This module's canonical home is slappyengine.ext.angle_sprite.
Import via either path; both are supported.
"""
from slappyengine.angle_sprite import (
    AngleEntry,
    AngleSpriteMap,
    make_angle_map_from_spritesheet,
)

__all__ = [
    "AngleEntry",
    "AngleSpriteMap",
    "make_angle_map_from_spritesheet",
]
