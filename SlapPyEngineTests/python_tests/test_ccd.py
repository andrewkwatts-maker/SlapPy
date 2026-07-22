"""Continuous Collision Detection tests.

These exercise the standalone ``swept_aabb_overlap``,
``predict_contact_pairs`` and ``position_at_toi`` helpers added in
``pharos_engine.physics.ccd``. They deliberately do *not* call
``PhysicsWorld.step`` — the CCD module is a pure helper; integration is
left for another sprint.
"""
from __future__ import annotations

import pytest

from pharos_engine.physics import HullTree
from pharos_engine.physics.ccd import (
    position_at_toi,
    predict_contact_pairs,
    swept_aabb_overlap,
)


# ---------------------------------------------------------------------------
# swept_aabb_overlap
# ---------------------------------------------------------------------------


def test_swept_aabb_no_overlap() -> None:
    """Two AABBs that never touch — neither at endpoints nor swept."""
    # A stays well to the left of B; both translate vertically a little.
    a0 = (0.0, 0.0, 1.0, 1.0)
    a1 = (0.0, 0.5, 1.0, 1.5)
    b0 = (10.0, 0.0, 11.0, 1.0)
    b1 = (10.0, -0.5, 11.0, 0.5)
    collided, toi = swept_aabb_overlap(a0, a1, b0, b1)
    assert collided is False
    assert toi == pytest.approx(1.0)


def test_swept_aabb_endpoint_overlap() -> None:
    """AABBs separated at t=0 but touching at t=1.

    ``toi`` must be inside (0, 1] and match the static-overlap check at
    the t=1 endpoints.
    """
    # A slides right into B; B is stationary.
    a0 = (0.0, 0.0, 1.0, 1.0)
    a1 = (5.0, 0.0, 6.0, 1.0)
    b0 = (5.5, 0.0, 6.5, 1.0)
    b1 = (5.5, 0.0, 6.5, 1.0)
    collided, toi = swept_aabb_overlap(a0, a1, b0, b1)
    assert collided is True
    assert 0.0 < toi <= 1.0
    # Endpoints overlap, so the static check at t=1 must agree.
    assert not (a1[2] < b1[0] or b1[2] < a1[0])


def test_swept_aabb_through_pass() -> None:
    """Small AABB starts left, ends right; a thin static wall sits in the
    middle. Discrete broadphase would miss this; CCD must catch it.
    """
    # Ball: 2x2 wide, moves from x=-50 to x=+50.
    a0 = (-50.0, 0.0, -48.0, 2.0)
    a1 = (50.0, 0.0, 52.0, 2.0)
    # Wall: a thin 1-px slab at x ≈ 0.
    b0 = (-0.5, -10.0, 0.5, 10.0)
    b1 = (-0.5, -10.0, 0.5, 10.0)
    collided, toi = swept_aabb_overlap(a0, a1, b0, b1)
    assert collided is True
    assert 0.0 < toi < 1.0
    # The ball's right edge sweeps from -48 → 52; it should reach the
    # wall's left edge (-0.5) at roughly t = (47.5 / 100) ≈ 0.475.
    assert toi == pytest.approx(0.475, abs=1e-3)


def test_swept_aabb_grazing_corner() -> None:
    """Diagonal sweep that brings two corners together right at t≈1.

    Should report ``collided`` but with ``toi`` very close to (and <) 1.
    """
    # A sweeps diagonally; at t=1 its lower-right corner exactly touches
    # B's upper-left corner.
    a0 = (0.0, 0.0, 1.0, 1.0)
    a1 = (4.0, 4.0, 5.0, 5.0)
    # B is stationary with its top-left corner at (5, 5).
    b0 = (5.0, 5.0, 7.0, 7.0)
    b1 = (5.0, 5.0, 7.0, 7.0)
    collided, toi = swept_aabb_overlap(a0, a1, b0, b1)
    assert collided is True
    assert toi < 1.0 + 1e-6
    assert toi > 0.9  # nearly all of the step is consumed.


def test_swept_aabb_zero_velocity_already_overlapping() -> None:
    """Edge case: identical boxes that don't move must report toi=0."""
    box = (0.0, 0.0, 2.0, 2.0)
    collided, toi = swept_aabb_overlap(box, box, box, box)
    assert collided is True
    assert toi == pytest.approx(0.0)


def test_swept_aabb_zero_velocity_separated() -> None:
    """Edge case: stationary, non-overlapping boxes never collide."""
    a = (0.0, 0.0, 1.0, 1.0)
    b = (5.0, 5.0, 6.0, 6.0)
    collided, toi = swept_aabb_overlap(a, a, b, b)
    assert collided is False
    assert toi == pytest.approx(1.0)


def test_swept_aabb_axis_aligned_exact_graze() -> None:
    """Two boxes sliding along the same X line, meeting edge-to-edge.

    Their Y extents touch exactly; X velocities close the gap. This
    exercises the ``rvy == 0`` short-circuit on one axis simultaneously
    with a closing X axis.
    """
    a0 = (0.0, 0.0, 1.0, 1.0)
    a1 = (2.0, 0.0, 3.0, 1.0)
    b0 = (4.0, 0.0, 5.0, 1.0)
    b1 = (4.0, 0.0, 5.0, 1.0)
    collided, toi = swept_aabb_overlap(a0, a1, b0, b1)
    # A moves right by 2 units; gap is 3, so they don't touch this frame.
    assert collided is False
    assert toi == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# position_at_toi
# ---------------------------------------------------------------------------


def test_position_at_toi_basic() -> None:
    """``position_at_toi`` must linearly interpolate using stored velocity."""
    tree = HullTree()
    hid = tree.spawn_root(
        x=10.0,
        y=20.0,
        cell_size_x=1.0,
        cell_size_y=1.0,
        mass=1.0,
        inertia=1.0,
        material_id=1,
    )
    tree.velocity[hid, 0] = 100.0
    tree.velocity[hid, 1] = -50.0
    px, py = position_at_toi(tree, hid, toi=0.5, dt=0.1)
    # Δt = 0.5 * 0.1 = 0.05 → Δx = 5.0, Δy = -2.5.
    assert px == pytest.approx(15.0)
    assert py == pytest.approx(17.5)


def test_position_at_toi_zero() -> None:
    """toi=0 returns the current position exactly."""
    tree = HullTree()
    hid = tree.spawn_root(
        x=7.5,
        y=-3.25,
        cell_size_x=1.0,
        cell_size_y=1.0,
        mass=1.0,
        inertia=1.0,
        material_id=1,
    )
    tree.velocity[hid, 0] = 1000.0  # irrelevant at toi=0.
    px, py = position_at_toi(tree, hid, toi=0.0, dt=1.0 / 60.0)
    assert px == pytest.approx(7.5)
    assert py == pytest.approx(-3.25)


# ---------------------------------------------------------------------------
# predict_contact_pairs
# ---------------------------------------------------------------------------


def _spawn_ball(tree: HullTree, x: float, y: float, vx: float, vy: float) -> int:
    """Helper: spawn a small (cell_size=1) hull and set its velocity."""
    hid = tree.spawn_root(
        x=x,
        y=y,
        cell_size_x=1.0,
        cell_size_y=1.0,
        mass=1.0,
        inertia=1.0,
        material_id=1,
    )
    tree.velocity[hid, 0] = vx
    tree.velocity[hid, 1] = vy
    return hid


def _spawn_wall(tree: HullTree, x: float, y: float) -> int:
    """Spawn a fixed wall hull (no velocity)."""
    hid = tree.spawn_root(
        x=x,
        y=y,
        cell_size_x=1.0,
        cell_size_y=1.0,
        mass=1.0,
        inertia=1.0,
        material_id=1,
        fixed=True,
    )
    return hid


def test_predict_contact_pairs_returns_fast_pairs() -> None:
    """A 200 px/s ball heading toward a wall must show up in the pair list."""
    tree = HullTree()
    # The hull's bounding box is 32 px wide (cell_size_x=1, grid=32 →
    # half-extent 16). Place ball at x=-50 so its right edge is at -34;
    # wall at x=+50 so its left edge is at +34. Closing gap = 68 px.
    ball = _spawn_ball(tree, x=-50.0, y=0.0, vx=200.0, vy=0.0)
    wall = _spawn_wall(tree, x=50.0, y=0.0)
    # Step is long enough to traverse the gap: 200 px/s * 0.5 s = 100 px.
    pairs = predict_contact_pairs(tree, dt=0.5, speed_threshold=50.0)
    ids = {(min(a, b), max(a, b)) for a, b, _ in pairs}
    assert (min(ball, wall), max(ball, wall)) in ids
    # toi must be strictly inside the step.
    for a, b, toi in pairs:
        if {a, b} == {ball, wall}:
            assert 0.0 < toi < 1.0


def test_predict_contact_pairs_skips_slow_pairs() -> None:
    """A 10 px/s ball is below threshold → no pair predicted."""
    tree = HullTree()
    _spawn_ball(tree, x=-50.0, y=0.0, vx=10.0, vy=0.0)
    _spawn_wall(tree, x=50.0, y=0.0)
    pairs = predict_contact_pairs(tree, dt=0.5, speed_threshold=50.0)
    assert pairs == []


def test_predict_contact_pairs_ignores_misses() -> None:
    """A fast ball flying past (not toward) a wall must not be reported."""
    tree = HullTree()
    # Ball flies upward; wall is to the right — they never meet.
    _spawn_ball(tree, x=-50.0, y=0.0, vx=0.0, vy=-200.0)
    _spawn_wall(tree, x=50.0, y=0.0)
    pairs = predict_contact_pairs(tree, dt=0.5, speed_threshold=50.0)
    assert pairs == []


def test_predict_contact_pairs_handles_freed_hulls() -> None:
    """Dead/freed hulls must be excluded from the predicted-pair list."""
    tree = HullTree()
    ball = _spawn_ball(tree, x=-50.0, y=0.0, vx=200.0, vy=0.0)
    wall = _spawn_wall(tree, x=50.0, y=0.0)
    tree.free(ball)
    pairs = predict_contact_pairs(tree, dt=0.5, speed_threshold=50.0)
    assert pairs == []
    # And the wall on its own should not pair with itself.
    assert not any(a == b for a, b, _ in pairs)
    # Ensure the wall id wasn't reused — we never spawned anything else.
    assert tree.is_alive(wall)


def test_predict_contact_pairs_zero_dt() -> None:
    """dt=0 must return an empty list (no motion possible)."""
    tree = HullTree()
    _spawn_ball(tree, x=-50.0, y=0.0, vx=1000.0, vy=0.0)
    _spawn_wall(tree, x=50.0, y=0.0)
    assert predict_contact_pairs(tree, dt=0.0, speed_threshold=50.0) == []
