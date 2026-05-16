"""Z-Height system — pseudo-3D depth for parallax, shadow casting, and Z-AABB collision."""
from __future__ import annotations
from dataclasses import dataclass, field
from slappyengine.struct_registry import StructModule


@dataclass
class ZLayer:
    """A named depth layer. Entities assigned to it scroll at parallax_x/y rates."""
    name: str
    z: float = 0.0                    # world-space height above ground
    parallax_x: float = 1.0           # horizontal scroll factor vs camera (< 1 = background)
    parallax_y: float = 1.0           # vertical scroll factor
    is_shadow_receiver: bool = True   # receives directional light shadows from above

    def __hash__(self):
        return id(self)


@dataclass
class ZAABBShape:
    """3D AABB: XY bounding box (screen space) + Z range for height collision."""
    width: float
    height: float
    z_min: float = 0.0
    z_max: float = 0.0
    offset_x: float = 0.0
    offset_y: float = 0.0


class ZHeightModule(StructModule):
    """Per-pixel Z height. Used by lighting shader to cast directional shadows."""
    name = "z_height"
    channels = [
        ("z_min", "f32"),   # bottom of column in world units
        ("z_max", "f32"),   # top of column — shadow length = (z_max - z_min) / tan(elevation)
    ]


def check_z_aabb(a, b) -> bool:
    """
    Return False if both entities have ZAABBShape and their Z ranges do NOT overlap.
    If either entity has no z_collision_shape, returns True (no Z filtering applied).
    """
    sa = getattr(a, 'z_collision_shape', None)
    sb = getattr(b, 'z_collision_shape', None)
    if sa is None or sb is None:
        return True  # no Z filtering — let XY collision decide

    za_min = sa.z_min + getattr(a, 'z_height', 0.0)
    za_max = sa.z_max + getattr(a, 'z_height', 0.0)
    zb_min = sb.z_min + getattr(b, 'z_height', 0.0)
    zb_max = sb.z_max + getattr(b, 'z_height', 0.0)

    # Overlap if ranges intersect
    return za_max >= zb_min and zb_max >= za_min
