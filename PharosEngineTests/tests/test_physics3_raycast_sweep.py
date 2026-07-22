"""Tests for :meth:`World3D.raycast` and :meth:`World3D.sweep_aabb` — NN4.

Coverage:
* Ray missing an empty world returns ``None``.
* Ray hits an axis-aligned box at the expected distance and normal.
* Ray parallel to a slab (outside it) returns ``None``.
* Ray respects ``max_distance``.
* Sweep clearing all bodies returns an empty list.
* Sweep hits a static wall — single SweepHit with TOI at the expected fraction.
* Sweep already overlapping returns TOI 0.
* Input validation: ``None`` origin/direction, wrong shape, negative distance.
"""
from __future__ import annotations

import math

import pytest

from pharos_engine.physics3_bridge import (
    Body3D,
    RaycastHit,
    SweepHit,
    World3D,
)


# ---------------------------------------------------------------------------
# raycast
# ---------------------------------------------------------------------------


def _box_body(center: tuple[float, float, float], half: float = 0.5) -> Body3D:
    return Body3D(
        position=center,
        mass=0.0,
        shape_kind="box",
        shape_params={"half_extents": (half, half, half)},
    )


def test_raycast_empty_world_returns_none() -> None:
    world = World3D(backend="fallback")
    assert world.raycast((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)) is None


def test_raycast_hits_box_at_expected_distance() -> None:
    world = World3D(backend="fallback")
    # Box's radius() for a half-extent (0.5,0.5,0.5) is sqrt(0.75) ≈ 0.866,
    # so the AABB spans roughly [4.134, 5.866] on x when centered at x=5.
    handle = world.add_body(_box_body((5.0, 0.0, 0.0), half=0.5))
    hit = world.raycast((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    assert isinstance(hit, RaycastHit)
    assert hit.body_id == handle
    # Ray enters at x = 5 - sqrt(0.75) ≈ 4.1339745962
    expected = 5.0 - math.sqrt(0.75)
    assert hit.distance == pytest.approx(expected, rel=1e-6)
    # Hit point is on the -x face of the AABB → normal is (-1, 0, 0).
    assert hit.normal == pytest.approx((-1.0, 0.0, 0.0), abs=1e-9)
    assert hit.point[0] == pytest.approx(expected, rel=1e-6)


def test_raycast_returns_nearest_of_multiple_hits() -> None:
    world = World3D(backend="fallback")
    _far = world.add_body(_box_body((10.0, 0.0, 0.0)))
    near = world.add_body(_box_body((3.0, 0.0, 0.0)))
    hit = world.raycast((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    assert hit is not None
    assert hit.body_id == near


def test_raycast_parallel_slab_misses() -> None:
    world = World3D(backend="fallback")
    # Box on x-axis with AABB spanning roughly y in [-0.866, 0.866].
    world.add_body(_box_body((5.0, 0.0, 0.0)))
    # Ray fired along x but well above the box on y.
    hit = world.raycast((0.0, 10.0, 0.0), (1.0, 0.0, 0.0))
    assert hit is None


def test_raycast_respects_max_distance() -> None:
    world = World3D(backend="fallback")
    world.add_body(_box_body((5.0, 0.0, 0.0)))
    # Box entry is at ~4.13; a max_distance of 3.0 is too short.
    hit = world.raycast((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), max_distance=3.0)
    assert hit is None
    # A max_distance of 10 is enough.
    hit_ok = world.raycast((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), max_distance=10.0)
    assert hit_ok is not None


def test_raycast_none_origin_raises() -> None:
    world = World3D(backend="fallback")
    with pytest.raises(TypeError):
        world.raycast(None, (1.0, 0.0, 0.0))  # type: ignore[arg-type]


def test_raycast_none_direction_raises() -> None:
    world = World3D(backend="fallback")
    with pytest.raises(TypeError):
        world.raycast((0.0, 0.0, 0.0), None)  # type: ignore[arg-type]


def test_raycast_wrong_shape_origin_raises() -> None:
    world = World3D(backend="fallback")
    with pytest.raises(TypeError):
        world.raycast((0.0, 0.0), (1.0, 0.0, 0.0))  # type: ignore[arg-type]


def test_raycast_negative_max_distance_raises() -> None:
    world = World3D(backend="fallback")
    with pytest.raises(ValueError):
        world.raycast((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), max_distance=-1.0)


def test_raycast_zero_direction_raises() -> None:
    world = World3D(backend="fallback")
    with pytest.raises(ValueError):
        world.raycast((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))


# ---------------------------------------------------------------------------
# sweep_aabb
# ---------------------------------------------------------------------------


def test_sweep_aabb_clear_path_returns_empty() -> None:
    world = World3D(backend="fallback")
    world.add_body(_box_body((10.0, 10.0, 10.0)))
    hits = world.sweep_aabb(
        aabb_min=(-0.5, -0.5, -0.5),
        aabb_max=(0.5, 0.5, 0.5),
        direction=(1.0, 0.0, 0.0),
        distance=1.0,
    )
    assert hits == []


def test_sweep_aabb_hits_static_wall_at_expected_toi() -> None:
    world = World3D(backend="fallback")
    # Wall centered at x=5, half-extent 0.5 → AABB radius sqrt(0.75) ≈ 0.866.
    # Wall AABB min on x: 5 - sqrt(0.75) ≈ 4.134.
    handle = world.add_body(_box_body((5.0, 0.0, 0.0), half=0.5))
    # Mover starts at [-0.5, 0.5], center (0,0,0). Distance from mover
    # max-x (0.5) to wall min-x (4.134) is ~3.634. Sweep 10 units → TOI ~0.3634.
    hits = world.sweep_aabb(
        aabb_min=(-0.5, -0.5, -0.5),
        aabb_max=(0.5, 0.5, 0.5),
        direction=(1.0, 0.0, 0.0),
        distance=10.0,
    )
    assert len(hits) == 1
    hit = hits[0]
    assert isinstance(hit, SweepHit)
    assert hit.body_id == handle
    expected_toi = (5.0 - math.sqrt(0.75) - 0.5) / 10.0
    assert hit.time_of_impact == pytest.approx(expected_toi, rel=1e-6)
    # Wall's contacted face is -x (the mover hit the wall's low-x face).
    assert hit.contact_normal == pytest.approx((-1.0, 0.0, 0.0), abs=1e-9)


def test_sweep_aabb_already_overlapping_returns_toi_zero() -> None:
    world = World3D(backend="fallback")
    handle = world.add_body(_box_body((0.0, 0.0, 0.0), half=0.5))
    # Mover initial AABB fully overlaps the static box.
    hits = world.sweep_aabb(
        aabb_min=(-0.5, -0.5, -0.5),
        aabb_max=(0.5, 0.5, 0.5),
        direction=(1.0, 0.0, 0.0),
        distance=1.0,
    )
    assert len(hits) == 1
    assert hits[0].body_id == handle
    assert hits[0].time_of_impact == pytest.approx(0.0, abs=1e-9)


def test_sweep_aabb_zero_distance_overlap_returns_toi_zero() -> None:
    world = World3D(backend="fallback")
    handle = world.add_body(_box_body((0.0, 0.0, 0.0), half=0.5))
    hits = world.sweep_aabb(
        aabb_min=(-0.5, -0.5, -0.5),
        aabb_max=(0.5, 0.5, 0.5),
        direction=(1.0, 0.0, 0.0),
        distance=0.0,
    )
    assert len(hits) == 1
    assert hits[0].body_id == handle
    assert hits[0].time_of_impact == pytest.approx(0.0, abs=1e-9)


def test_sweep_aabb_zero_distance_no_overlap_returns_empty() -> None:
    world = World3D(backend="fallback")
    world.add_body(_box_body((10.0, 0.0, 0.0)))
    hits = world.sweep_aabb(
        aabb_min=(-0.5, -0.5, -0.5),
        aabb_max=(0.5, 0.5, 0.5),
        direction=(1.0, 0.0, 0.0),
        distance=0.0,
    )
    assert hits == []


def test_sweep_aabb_returns_hits_sorted_by_toi() -> None:
    world = World3D(backend="fallback")
    far = world.add_body(_box_body((10.0, 0.0, 0.0)))
    near = world.add_body(_box_body((3.0, 0.0, 0.0)))
    hits = world.sweep_aabb(
        aabb_min=(-0.5, -0.5, -0.5),
        aabb_max=(0.5, 0.5, 0.5),
        direction=(1.0, 0.0, 0.0),
        distance=20.0,
    )
    assert len(hits) == 2
    assert hits[0].body_id == near
    assert hits[1].body_id == far
    assert hits[0].time_of_impact <= hits[1].time_of_impact


def test_sweep_aabb_none_min_raises() -> None:
    world = World3D(backend="fallback")
    with pytest.raises(TypeError):
        world.sweep_aabb(None, (1.0, 1.0, 1.0), (1.0, 0.0, 0.0), 1.0)  # type: ignore[arg-type]


def test_sweep_aabb_none_max_raises() -> None:
    world = World3D(backend="fallback")
    with pytest.raises(TypeError):
        world.sweep_aabb((0.0, 0.0, 0.0), None, (1.0, 0.0, 0.0), 1.0)  # type: ignore[arg-type]


def test_sweep_aabb_none_direction_raises() -> None:
    world = World3D(backend="fallback")
    with pytest.raises(TypeError):
        world.sweep_aabb((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), None, 1.0)  # type: ignore[arg-type]


def test_sweep_aabb_wrong_shape_raises() -> None:
    world = World3D(backend="fallback")
    with pytest.raises(TypeError):
        world.sweep_aabb(
            (0.0, 0.0),  # type: ignore[arg-type]
            (1.0, 1.0, 1.0),
            (1.0, 0.0, 0.0),
            1.0,
        )


def test_sweep_aabb_negative_distance_raises() -> None:
    world = World3D(backend="fallback")
    with pytest.raises(ValueError):
        world.sweep_aabb(
            (0.0, 0.0, 0.0),
            (1.0, 1.0, 1.0),
            (1.0, 0.0, 0.0),
            -1.0,
        )


def test_sweep_aabb_min_greater_than_max_raises() -> None:
    world = World3D(backend="fallback")
    with pytest.raises(ValueError):
        world.sweep_aabb(
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 1.0),  # x-min > x-max
            (1.0, 0.0, 0.0),
            1.0,
        )
