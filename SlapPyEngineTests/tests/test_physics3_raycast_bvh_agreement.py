"""Correctness parity: BVH raycast agrees with linear raycast — OO2.

For 100 random ``(origin, direction)`` pairs against a 200-body
:class:`~pharos_engine.physics3_bridge.World3D`, both raycast paths must
return the same body_id (or both ``None``) and the same ``distance``
within 1e-6. If the two disagree we'd have a functional regression
against NN4's linear implementation.

Bodies are spaced on a jittered grid so no two AABBs sit at identical
centroids — that keeps ``t_hit`` ties out of the ordering test, which
would otherwise be a legitimate ambiguity (both paths would return
*a* correct answer, just possibly a different one).
"""
from __future__ import annotations

import math
import random

import pytest

from pharos_engine.physics3_bridge import Body3D, RaycastHit, World3D

_SEED = 20260707
_BODY_COUNT = 200
_RAY_COUNT = 100
_SPACE_HALF = 40.0
_TOLERANCE = 1e-6


def _jittered_grid_box(
    rng: random.Random,
    slot_x: int,
    slot_y: int,
    slot_z: int,
) -> Body3D:
    """Return a Body3D snapped to a jittered grid cell.

    The grid keeps centroids distinct (no two boxes overlap perfectly),
    which prevents legitimate ``t_hit`` ties that would otherwise let
    the two paths pick different-but-both-correct winners.
    """
    step = 4.0
    cx = slot_x * step + rng.uniform(-0.5, 0.5)
    cy = slot_y * step + rng.uniform(-0.5, 0.5)
    cz = slot_z * step + rng.uniform(-0.5, 0.5)
    hx = rng.uniform(0.3, 0.8)
    hy = rng.uniform(0.3, 0.8)
    hz = rng.uniform(0.3, 0.8)
    return Body3D(
        position=(cx, cy, cz),
        mass=0.0,
        shape_kind="box",
        shape_params={"half_extents": (hx, hy, hz)},
    )


def _seeded_ray(rng: random.Random) -> tuple[
    tuple[float, float, float], tuple[float, float, float]
]:
    """Return a normalised (origin, direction) pair from outside the grid."""
    # Origins on a sphere of radius ~2*_SPACE_HALF so most rays start
    # outside every AABB — matches the typical picking use-case.
    r = _SPACE_HALF * 2.0
    theta = rng.uniform(0.0, 2.0 * math.pi)
    phi = rng.uniform(0.0, math.pi)
    ox = r * math.sin(phi) * math.cos(theta)
    oy = r * math.sin(phi) * math.sin(theta)
    oz = r * math.cos(phi)
    # Direction: aim roughly at the origin plus jitter.
    dx = -ox + rng.uniform(-_SPACE_HALF, _SPACE_HALF)
    dy = -oy + rng.uniform(-_SPACE_HALF, _SPACE_HALF)
    dz = -oz + rng.uniform(-_SPACE_HALF, _SPACE_HALF)
    n = math.sqrt(dx * dx + dy * dy + dz * dz)
    if n <= 1e-6:
        # Fallback direction — negligibly rare.
        dx, dy, dz, n = 1.0, 0.0, 0.0, 1.0
    return (ox, oy, oz), (dx / n, dy / n, dz / n)


def _build_world() -> tuple[World3D, list[tuple[
    tuple[float, float, float], tuple[float, float, float]
]]]:
    rng = random.Random(_SEED)
    world = World3D(backend="fallback")
    # Jittered 6x6x6 = 216 grid; take the first _BODY_COUNT.
    slots: list[tuple[int, int, int]] = []
    for x in range(-3, 3):
        for y in range(-3, 3):
            for z in range(-3, 3):
                slots.append((x, y, z))
    rng.shuffle(slots)
    for slot in slots[:_BODY_COUNT]:
        world.add_body(_jittered_grid_box(rng, *slot))
    rays = [_seeded_ray(rng) for _ in range(_RAY_COUNT)]
    return world, rays


def test_bvh_and_linear_raycast_agree_on_random_rays() -> None:
    world, rays = _build_world()
    world.build_bvh()

    hits_agree = 0
    both_miss = 0
    disagreements: list[str] = []
    for i, (origin, direction) in enumerate(rays):
        linear = world.raycast(origin, direction, use_bvh=False)
        bvh = world.raycast(origin, direction, use_bvh=True)
        if linear is None and bvh is None:
            both_miss += 1
            continue
        if linear is None or bvh is None:
            disagreements.append(
                f"ray {i}: linear={linear!r} vs bvh={bvh!r} (one is None)"
            )
            continue
        assert isinstance(linear, RaycastHit)
        assert isinstance(bvh, RaycastHit)
        if linear.body_id != bvh.body_id:
            disagreements.append(
                f"ray {i}: body_id linear={linear.body_id} bvh={bvh.body_id}"
                f" (linear t={linear.distance:.9f}, bvh t={bvh.distance:.9f})"
            )
            continue
        if abs(linear.distance - bvh.distance) > _TOLERANCE:
            disagreements.append(
                f"ray {i}: distance mismatch linear={linear.distance:.9f}"
                f" bvh={bvh.distance:.9f} (delta={linear.distance-bvh.distance:.3e})"
            )
            continue
        hits_agree += 1

    total = hits_agree + both_miss
    msg = (
        f"BVH/linear raycast disagreement on {len(disagreements)}"
        f" / {_RAY_COUNT} rays: {disagreements[:5]}"
    )
    assert not disagreements, msg
    assert total == _RAY_COUNT
    # Sanity: at least a handful of rays should actually hit — otherwise
    # the test degenerates to comparing None==None.
    assert hits_agree >= 10, (
        f"Only {hits_agree} rays hit anything — test scene is too sparse"
        f" to be meaningful"
    )
