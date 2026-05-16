"""Extension shim — re-exports from playslap.angle_sprite.

This module's canonical home is playslap.ext.angle_sprite.
Import via either path; both are supported.
"""
from playslap.angle_sprite import (
    AngleEntry,
    AngleSpriteMap,
    make_angle_map_from_spritesheet,
)

__all__ = [
    "AngleEntry",
    "AngleSpriteMap",
    "make_angle_map_from_spritesheet",
]
