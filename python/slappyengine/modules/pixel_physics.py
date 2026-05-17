"""PixelPhysicsModule — per-pixel velocity, mass, friction, elasticity, temperature, state."""
from __future__ import annotations
from slappyengine.struct_registry import StructModule


class PixelPhysicsModule(StructModule):
    """
    Per-pixel physical properties for compute-shader driven simulation.

    Fields (packed to 8-float / 32-byte struct for GPU alignment):
      vel_x, vel_y   — pixel velocity in pixels/second
      mass           — 0 = static (infinite mass), >0 = dynamic
      friction       — surface friction coefficient [0, 1]
      elasticity     — bounce restitution coefficient [0, 1]
      temperature    — temperature in Kelvin (drives state transitions + emission)
      state          — material phase: 0=solid, 1=liquid, 2=gas, 3=plasma
      _pad           — alignment padding
    """
    name = "pixel_physics"
    channels = [
        ("vel_x",       "f32"),
        ("vel_y",       "f32"),
        ("mass",        "f32"),
        ("friction",    "f32"),
        ("elasticity",  "f32"),
        ("temperature", "f32"),
        ("state",       "u32"),
        ("_pad",        "u32"),
    ]
    compute_passes = ["pixel_physics"]
    default_values = {
        "vel_x":       0.0,
        "vel_y":       0.0,
        "mass":        1.0,
        "friction":    0.5,
        "elasticity":  0.3,
        "temperature": 293.0,   # room temperature in Kelvin
        "state":       0,       # solid
        "_pad":        0,
    }
