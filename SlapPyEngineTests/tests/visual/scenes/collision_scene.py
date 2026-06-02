"""A 3-body collision scene: steel ball + glass disk drop onto stone ground.

The bodies are placed so that within ~30 frames at default dt the steel ball
strikes the glass disk resting on the stone ground, producing a visible
post-impact change in cell state (heat, displacement, contact flash).
"""
from __future__ import annotations

from slappyengine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
    make_rect_silhouette,
)


def build_collision_world() -> PhysicsWorld:
    """Build a deterministic 3-body world for the visual collision test.

    Layout (world units, +y is down):
      - Stone ground:  fixed slab at (0, 200), 320 wide × 40 tall.
      - Glass disk:    64 px diameter at (0, 120), resting on the ground.
      - Steel ball:    64 px diameter at (-20, -60), falling onto the disk.

    The world view used by the test renderer is (-200, -100, 200, 250)
    so all three bodies are visible in-frame.
    """
    # World bounds give the renderer a closed arena; bodies bounce off walls
    # rather than escaping the screen.
    world = PhysicsWorld(world_bounds=(-200.0, -100.0, 200.0, 250.0))

    # Stone ground — fixed (won't move), wide rectangle just below mid-screen.
    ground_sil = make_rect_silhouette(width=320, height=40)
    world.create_body(
        silhouette=ground_sil,
        material="stone",
        position=(0.0, 200.0),
        fixed=True,
    )

    # Glass disk — sitting on top of the ground, awaiting impact.
    disk_sil = make_circle_silhouette(diameter=64)
    world.create_body(
        silhouette=disk_sil,
        material="glass",
        position=(0.0, 120.0),
        velocity=(0.0, 0.0),
    )

    # Steel ball — dropped from just above the disk with a meaningful
    # horizontal offset so the impact is off-centre (yields more
    # interesting heat/displacement field).  Starting velocity is high so
    # the impact happens within the 90-frame budget.
    ball_sil = make_circle_silhouette(diameter=64)
    world.create_body(
        silhouette=ball_sil,
        material="steel",
        position=(-20.0, 30.0),
        velocity=(40.0, 220.0),
    )

    return world
