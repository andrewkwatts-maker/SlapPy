"""A 2-body lighting scene: steel ball above stone ground, two coloured lights.

The renderer's point-light Lambert path tints the steel ball: a warm light
on the left should bias the body's left half red, a cool light on the right
should bias the right half blue.  This produces a deterministic visual
signature that the test asserts on.
"""
from __future__ import annotations

from pharos_engine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
    make_rect_silhouette,
)
from pharos_engine.physics.render import PointLight, RenderConfig


# Light positions and colours used by the test.  Exposed at module scope so
# the test can build a RenderConfig that matches the scene's intent.
LIGHT_A_POSITION = (-100.0, -50.0)
LIGHT_A_COLOR = (255.0, 200.0, 120.0)  # warm
LIGHT_B_POSITION = (150.0, -100.0)
LIGHT_B_COLOR = (120.0, 180.0, 255.0)  # cool


def build_lighting_world() -> PhysicsWorld:
    """Build a 2-body world for the lighting visual test.

    Layout (world units, +y is down):
      - Stone ground:  fixed slab at (0, 180), 320 wide × 40 tall.
      - Steel ball:    64 px diameter at (0, 0), falling under gravity.
    """
    world = PhysicsWorld(world_bounds=(-200.0, -100.0, 200.0, 250.0))

    # Ground — fixed slab below the falling ball.
    ground_sil = make_rect_silhouette(width=320, height=40)
    world.create_body(
        silhouette=ground_sil,
        material="stone",
        position=(0.0, 180.0),
        fixed=True,
    )

    # Steel ball — large enough that left-half vs right-half pixel counts
    # are meaningful for the lighting bias assertions.
    ball_sil = make_circle_silhouette(diameter=64)
    world.create_body(
        silhouette=ball_sil,
        material="steel",
        position=(0.0, 0.0),
        velocity=(0.0, 0.0),
    )

    return world


def build_lighting_config(width: int = 640, height: int = 360) -> RenderConfig:
    """Return a ``RenderConfig`` populated with the two coloured point lights.

    Curvature bias is bumped up from the default so the steel ball reads as
    a clearly shaded sphere (the test relies on left/right hemisphere
    colour bias being visible per-frame).
    """
    return RenderConfig(
        width=width,
        height=height,
        world_view=(-200.0, -100.0, 200.0, 250.0),
        lights=[
            PointLight(
                position=LIGHT_A_POSITION,
                color=LIGHT_A_COLOR,
                intensity=2.5,
                radius=180.0,
            ),
            PointLight(
                position=LIGHT_B_POSITION,
                color=LIGHT_B_COLOR,
                intensity=2.5,
                radius=180.0,
            ),
        ],
        ambient_intensity=0.15,
        enable_normal_map=True,
        normal_curvature_bias=1.2,
        # Keep heat-driven emission low: the steel ball isn't supposed to
        # be glowing, just lit.  Otherwise the contact-flash + glow swamp
        # the directional colour bias the test is measuring.
        heat_emission_gain=0.0,
        contact_flash=False,
    )
