"""Reusable scene builders for visual tests.

These helpers construct real ``PhysicsWorld`` instances with author-time
bodies so the visual test suite renders genuine physics state (positions,
velocities, heat, displacement) instead of the placeholder yellow-disk
synthetic frame baked into ``tests/visual/harness.HeadlessRenderer``.
"""
from __future__ import annotations

from tests.visual.scenes.collision_scene import build_collision_world
from tests.visual.scenes.lighting_scene import build_lighting_world

__all__ = ["build_collision_world", "build_lighting_world"]
