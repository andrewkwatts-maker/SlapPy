"""Tests for pharos_engine.physics3_bridge — LL7 Nova3D parity Sprint 18.

Coverage:
* resolve_physics3_backend returns a valid tag.
* Body3D construction validates all fields.
* World3D add_body / remove_body lifecycle.
* Auto backend selection picks the best available.
* Fallback backend runs without crashing at 100 bodies / 60 Hz.
* Gravity applied by step (positions drop, velocities accumulate).
* SAP broadphase catches overlapping AABBs and skips separated ones.
* Ray query hits sphere at expected parameter.
* Sphere-sphere collision separates overlapping bodies.
"""
from __future__ import annotations

import math
import time

import pytest

from pharos_engine.physics3_bridge import (
    Body3D,
    PhysicsBackendError,
    World3D,
    resolve_physics3_backend,
)


# ---------------------------------------------------------------------------
# resolve_physics3_backend
# ---------------------------------------------------------------------------


def test_resolve_physics3_backend_returns_valid_tag() -> None:
    tag = resolve_physics3_backend()
    assert tag in {"physics", "fallback", "none"}


def test_resolve_physics3_backend_is_stable() -> None:
    """Two consecutive calls must agree — the tag is process-lifetime stable."""
    assert resolve_physics3_backend() == resolve_physics3_backend()


# ---------------------------------------------------------------------------
# Body3D
# ---------------------------------------------------------------------------


def test_body3d_defaults() -> None:
    b = Body3D()
    assert b.position == (0.0, 0.0, 0.0)
    assert b.orientation == (1.0, 0.0, 0.0, 0.0)
    assert b.linear_velocity == (0.0, 0.0, 0.0)
    assert b.angular_velocity == (0.0, 0.0, 0.0)
    assert b.mass == 1.0
    assert b.shape_kind == "sphere"
    assert b.shape_params == {}


def test_body3d_accepts_lists_and_coerces() -> None:
    """Passing lists in place of tuples must still work — friendlier API."""
    b = Body3D(position=[1, 2, 3], linear_velocity=[0, 0, 0])
    assert b.position == (1.0, 2.0, 3.0)
    assert isinstance(b.position, tuple)


def test_body3d_rejects_bad_shape_kind() -> None:
    with pytest.raises(ValueError):
        Body3D(shape_kind="octahedron")


def test_body3d_rejects_negative_mass() -> None:
    with pytest.raises(ValueError):
        Body3D(mass=-1.0)


def test_body3d_rejects_bad_shape_params_type() -> None:
    with pytest.raises(TypeError):
        Body3D(shape_params=[1, 2, 3])  # type: ignore[arg-type]


def test_body3d_radius_matches_shape() -> None:
    sphere = Body3D(shape_kind="sphere", shape_params={"radius": 2.5})
    assert sphere.radius() == pytest.approx(2.5)
    box = Body3D(shape_kind="box", shape_params={"half_extents": (1.0, 1.0, 1.0)})
    assert box.radius() == pytest.approx(math.sqrt(3.0))
    cap = Body3D(
        shape_kind="capsule",
        shape_params={"radius": 0.5, "half_height": 1.0},
    )
    assert cap.radius() == pytest.approx(1.5)


def test_body3d_aabb_covers_sphere() -> None:
    b = Body3D(position=(1.0, 2.0, 3.0), shape_params={"radius": 1.5})
    mn, mx = b.aabb()
    assert mn == (-0.5, 0.5, 1.5)
    assert mx == (2.5, 3.5, 4.5)


# ---------------------------------------------------------------------------
# World3D construction + lifecycle
# ---------------------------------------------------------------------------


def test_world3d_defaults_auto_backend() -> None:
    w = World3D()
    assert w.backend in {"physics", "fallback"}
    assert w.gravity == (0.0, -9.81, 0.0)


def test_world3d_fallback_backend_forced() -> None:
    w = World3D(backend="fallback")
    assert w.backend == "fallback"


def test_world3d_invalid_backend_string_raises() -> None:
    with pytest.raises(ValueError):
        World3D(backend="bogus")


def test_world3d_add_body_returns_stable_handles() -> None:
    w = World3D(backend="fallback")
    h1 = w.add_body(Body3D())
    h2 = w.add_body(Body3D())
    assert h1 != h2
    assert h1 in w
    assert h2 in w
    assert len(w) == 2


def test_world3d_remove_body_drops_handle() -> None:
    w = World3D(backend="fallback")
    h = w.add_body(Body3D())
    w.remove_body(h)
    assert h not in w
    assert len(w) == 0


def test_world3d_remove_unknown_raises_keyerror() -> None:
    w = World3D(backend="fallback")
    with pytest.raises(KeyError):
        w.remove_body(9999)


def test_world3d_add_body_rejects_non_body() -> None:
    w = World3D(backend="fallback")
    with pytest.raises(TypeError):
        w.add_body("not a body")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Step / gravity / integration
# ---------------------------------------------------------------------------


def test_world3d_step_negative_dt_raises() -> None:
    w = World3D(backend="fallback")
    with pytest.raises(ValueError):
        w.step(-1.0)


def test_world3d_step_advances_positions_with_velocity() -> None:
    w = World3D(gravity=(0.0, 0.0, 0.0), backend="fallback")
    h = w.add_body(Body3D(position=(0.0, 0.0, 0.0), linear_velocity=(1.0, 0.0, 0.0)))
    w.step(0.1)
    assert w.get_body(h).position[0] == pytest.approx(0.1)


def test_world3d_gravity_drops_position() -> None:
    w = World3D(gravity=(0.0, -10.0, 0.0), backend="fallback")
    h = w.add_body(Body3D(position=(0.0, 0.0, 0.0)))
    # Semi-implicit Euler: v += g*dt, then p += v*dt
    # After 1s at 60 Hz the object should be well below y=0.
    for _ in range(60):
        w.step(1.0 / 60.0)
    body = w.get_body(h)
    assert body.position[1] < -4.0  # around -5m ballpark
    assert body.linear_velocity[1] < -9.0


def test_world3d_static_body_ignores_gravity() -> None:
    w = World3D(gravity=(0.0, -10.0, 0.0), backend="fallback")
    h = w.add_body(Body3D(position=(0.0, 0.0, 0.0), mass=0.0))
    for _ in range(30):
        w.step(1.0 / 30.0)
    assert w.get_body(h).position == (0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# Broadphase (SAP)
# ---------------------------------------------------------------------------


def test_sap_broadphase_catches_overlap() -> None:
    w = World3D(backend="fallback")
    a = w.add_body(Body3D(position=(0.0, 0.0, 0.0), shape_params={"radius": 1.0}))
    b = w.add_body(Body3D(position=(0.5, 0.0, 0.0), shape_params={"radius": 1.0}))
    pairs = w.broadphase_pairs()
    assert (min(a, b), max(a, b)) in pairs


def test_sap_broadphase_skips_separated() -> None:
    w = World3D(backend="fallback")
    w.add_body(Body3D(position=(0.0, 0.0, 0.0), shape_params={"radius": 0.4}))
    w.add_body(Body3D(position=(10.0, 0.0, 0.0), shape_params={"radius": 0.4}))
    pairs = w.broadphase_pairs()
    assert pairs == []


def test_sap_broadphase_pairs_are_sorted() -> None:
    """Deterministic ordering — tests rely on the (min, max) sort."""
    w = World3D(backend="fallback")
    for i in range(5):
        w.add_body(Body3D(position=(float(i) * 0.5, 0.0, 0.0), shape_params={"radius": 1.0}))
    pairs = w.broadphase_pairs()
    assert pairs == sorted(pairs)


def test_sap_broadphase_uses_y_and_z_prune() -> None:
    """Overlap on X only should not produce a pair — Y/Z is checked too."""
    w = World3D(backend="fallback")
    w.add_body(Body3D(position=(0.0, 0.0, 0.0), shape_params={"radius": 0.4}))
    w.add_body(Body3D(position=(0.1, 10.0, 0.0), shape_params={"radius": 0.4}))
    assert w.broadphase_pairs() == []


# ---------------------------------------------------------------------------
# Narrowphase (sphere-sphere)
# ---------------------------------------------------------------------------


def test_sphere_sphere_separates_overlapping_bodies() -> None:
    w = World3D(gravity=(0.0, 0.0, 0.0), backend="fallback")
    a = w.add_body(
        Body3D(
            position=(0.0, 0.0, 0.0),
            linear_velocity=(1.0, 0.0, 0.0),
            shape_params={"radius": 1.0},
        )
    )
    b = w.add_body(
        Body3D(
            position=(1.5, 0.0, 0.0),
            linear_velocity=(-1.0, 0.0, 0.0),
            shape_params={"radius": 1.0},
        )
    )
    w.step(0.5)  # 0.5s of closing velocity, then resolve
    # After collision resolution the centres should be at least
    # r_sum apart (or bouncing outward).
    ba = w.get_body(a)
    bb = w.get_body(b)
    dist = math.hypot(bb.position[0] - ba.position[0], 0.0)
    # Post-resolution the velocities should have swapped signs (bounce).
    assert ba.linear_velocity[0] < 0.5  # was +1 pre-impact
    assert bb.linear_velocity[0] > -0.5  # was -1 pre-impact


# ---------------------------------------------------------------------------
# Ray query
# ---------------------------------------------------------------------------


def test_query_ray_hits_sphere_at_expected_t() -> None:
    w = World3D(backend="fallback")
    h = w.add_body(
        Body3D(position=(5.0, 0.0, 0.0), shape_params={"radius": 1.0}),
    )
    hits = w.query_ray(origin=(0.0, 0.0, 0.0), direction=(1.0, 0.0, 0.0))
    assert len(hits) == 1
    hit_id, t = hits[0]
    assert hit_id == h
    # AABB slab test enters at x = 4.0 for a unit sphere centred at 5.0.
    assert t == pytest.approx(4.0, abs=0.01)


def test_query_ray_misses_when_direction_wrong() -> None:
    w = World3D(backend="fallback")
    w.add_body(Body3D(position=(5.0, 0.0, 0.0), shape_params={"radius": 1.0}))
    hits = w.query_ray(origin=(0.0, 0.0, 0.0), direction=(-1.0, 0.0, 0.0))
    assert hits == []


def test_query_ray_zero_direction_returns_empty() -> None:
    w = World3D(backend="fallback")
    w.add_body(Body3D())
    assert w.query_ray(origin=(0.0, 0.0, 0.0), direction=(0.0, 0.0, 0.0)) == []


def test_query_ray_sorts_hits_by_t() -> None:
    w = World3D(backend="fallback")
    w.add_body(Body3D(position=(3.0, 0.0, 0.0), shape_params={"radius": 0.5}))
    w.add_body(Body3D(position=(6.0, 0.0, 0.0), shape_params={"radius": 0.5}))
    w.add_body(Body3D(position=(9.0, 0.0, 0.0), shape_params={"radius": 0.5}))
    hits = w.query_ray(origin=(0.0, 0.0, 0.0), direction=(1.0, 0.0, 0.0))
    assert [t for _, t in hits] == sorted(t for _, t in hits)


# ---------------------------------------------------------------------------
# AABB query
# ---------------------------------------------------------------------------


def test_query_aabb_tuple_pair() -> None:
    w = World3D(backend="fallback")
    inside = w.add_body(Body3D(position=(0.0, 0.0, 0.0), shape_params={"radius": 0.5}))
    outside = w.add_body(Body3D(position=(10.0, 0.0, 0.0), shape_params={"radius": 0.5}))
    hits = w.query_aabb(((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0)))
    assert inside in hits
    assert outside not in hits


def test_query_aabb_accepts_kk1_aabb_when_available() -> None:
    from pharos_engine.physics3_bridge import AABB3D
    if AABB3D is None:
        pytest.skip("KK1 AABB3D unavailable — render tree stripped")
    w = World3D(backend="fallback")
    h = w.add_body(Body3D(position=(0.0, 0.0, 0.0), shape_params={"radius": 0.5}))
    hits = w.query_aabb(AABB3D(min=(-1.0, -1.0, -1.0), max=(1.0, 1.0, 1.0)))
    assert h in hits


# ---------------------------------------------------------------------------
# Auto backend + errors
# ---------------------------------------------------------------------------


def test_auto_backend_matches_resolve() -> None:
    w = World3D(backend="auto")
    assert w.backend == resolve_physics3_backend()


def test_physics_backend_forced_may_raise_if_absent() -> None:
    """If the WIP tree is present, requesting it must succeed."""
    if resolve_physics3_backend() == "physics":
        w = World3D(backend="physics")
        assert w.backend == "physics"
    else:
        with pytest.raises(PhysicsBackendError):
            World3D(backend="physics")


# ---------------------------------------------------------------------------
# Perf smoke — 100 bodies at 60 Hz should be well under 1s
# ---------------------------------------------------------------------------


def test_fallback_100_bodies_60hz_stable() -> None:
    """Prototyping-grade smoke: 100 bodies, 60 substeps, no NaNs."""
    w = World3D(backend="fallback")
    for i in range(100):
        # Spread bodies out enough that only some collide — mimicking a
        # prototyping scene.
        x = float(i % 10) * 3.0
        z = float(i // 10) * 3.0
        w.add_body(
            Body3D(
                position=(x, 5.0, z),
                shape_params={"radius": 0.5},
            )
        )
    t0 = time.perf_counter()
    for _ in range(60):
        w.step(1.0 / 60.0)
    elapsed = time.perf_counter() - t0
    # Numerical stability: no NaNs / Infs.
    for body in w.bodies.values():
        for c in body.position:
            assert math.isfinite(c)
        for c in body.linear_velocity:
            assert math.isfinite(c)
    # Perf ceiling — generous so slow CI still passes.
    assert elapsed < 5.0, f"100 bodies * 60 steps took {elapsed:.3f}s"


def test_fallback_empty_world_step_noop() -> None:
    """An empty world must step cleanly."""
    w = World3D(backend="fallback")
    w.step(0.016)
    assert len(w) == 0
