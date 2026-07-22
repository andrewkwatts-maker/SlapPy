"""Tests for pharos_engine.physics.constraints (joint/constraint solver)."""
from __future__ import annotations

import math


from pharos_engine.physics import (
    ConstraintSolver,
    DistanceConstraint,
    PhysicsWorld,
    PinConstraint,
    WeldConstraint,
    make_circle_silhouette,
    make_rect_silhouette,
)


def _world(no_gravity: bool = True) -> PhysicsWorld:
    w = PhysicsWorld(world_bounds=(-500.0, -500.0, 500.0, 500.0))
    if no_gravity:
        w.config.world = type(w.config.world)(
            default_dt=w.config.world.default_dt,
            substeps=w.config.world.substeps,
            gravity=(0.0, 0.0),
        )
    return w


def _make_ball(w: PhysicsWorld, pos: tuple[float, float], d: int = 24, mat: str = "steel"):
    return w.create_body(make_circle_silhouette(d), material=mat, position=pos)


def _world_anchor(body, local):
    ang = float(body.world.hulls.angle[body.root_hull_id])
    c, s = math.cos(ang), math.sin(ang)
    px, py = body.position
    return (px + c * local[0] - s * local[1], py + s * local[0] + c * local[1])


# --------------------------------------------------------------------------- #
# Pin                                                                          #
# --------------------------------------------------------------------------- #


def test_pin_keeps_bodies_attached():
    w = _world(no_gravity=True)
    a = _make_ball(w, (-20.0, 0.0))
    b = _make_ball(w, (20.0, 0.0))
    # Pin at the midpoint between the two centres.  Local anchors put both
    # at world (0, 0) initially.
    pin = PinConstraint(a, b, local_anchor_a=(20.0, 0.0), local_anchor_b=(-20.0, 0.0))
    solver = ConstraintSolver(iterations=8)
    solver.add(pin)

    # Push body A.
    a.velocity = (50.0, 0.0)
    dt = w.config.world.default_dt
    for _ in range(60):
        w.step(dt)
        solver.solve(w, dt)

    ax, ay = _world_anchor(a, (20.0, 0.0))
    bx, by = _world_anchor(b, (-20.0, 0.0))
    err = math.hypot(ax - bx, ay - by)
    assert err < 0.5, f"pin anchors drifted by {err:.3f}px"


# --------------------------------------------------------------------------- #
# Distance                                                                     #
# --------------------------------------------------------------------------- #


def test_distance_keeps_separation_constant():
    w = PhysicsWorld(world_bounds=(-500.0, -500.0, 500.0, 500.0))  # gravity on
    a = _make_ball(w, (0.0, -10.0))
    b = _make_ball(w, (20.0, -10.0))
    # Centre-to-centre rod of length 20.
    dist = DistanceConstraint(a, b, (0.0, 0.0), (0.0, 0.0), distance=20.0, stiffness=1.0)
    solver = ConstraintSolver(iterations=12)
    solver.add(dist)

    dt = w.config.world.default_dt
    for _ in range(120):
        w.step(dt)
        solver.solve(w, dt)
    ax, ay = a.position
    bx, by = b.position
    d_final = math.hypot(ax - bx, ay - by)
    assert abs(d_final - 20.0) < 1.0, f"distance drifted to {d_final:.3f} (want ~20)"


# --------------------------------------------------------------------------- #
# Weld                                                                         #
# --------------------------------------------------------------------------- #


def test_weld_locks_orientation():
    w = _world(no_gravity=True)
    a = _make_ball(w, (0.0, 0.0))
    b = _make_ball(w, (20.0, 0.0))
    weld = WeldConstraint(a, b, (10.0, 0.0), (-10.0, 0.0), target_relative_angle=0.0)
    solver = ConstraintSolver(iterations=8)
    solver.add(weld)

    # Manually spin body B.
    w.hulls.omega[b.root_hull_id] = 5.0
    dt = w.config.world.default_dt
    for _ in range(60):
        w.step(dt)
        solver.solve(w, dt)

    ang_a = float(w.hulls.angle[a.root_hull_id])
    ang_b = float(w.hulls.angle[b.root_hull_id])
    diff = ang_a - ang_b
    # Wrap to (-pi, pi].
    while diff > math.pi:
        diff -= 2 * math.pi
    while diff < -math.pi:
        diff += 2 * math.pi
    assert abs(diff) < 0.5, f"weld should pull angles together; got diff={diff:.3f}rad"


# --------------------------------------------------------------------------- #
# Break force                                                                  #
# --------------------------------------------------------------------------- #


def test_break_force_disconnects():
    w = _world(no_gravity=True)
    a = _make_ball(w, (-20.0, 0.0))
    b = _make_ball(w, (20.0, 0.0))
    pin = PinConstraint(
        a, b,
        local_anchor_a=(20.0, 0.0),
        local_anchor_b=(-20.0, 0.0),
        break_force=1.0,  # absurdly fragile
    )
    solver = ConstraintSolver(iterations=4)
    solver.add(pin)

    dt = w.config.world.default_dt
    # Slam massive opposing velocities -> impulse will exceed 1.0.
    a.velocity = (500.0, 0.0)
    b.velocity = (-500.0, 0.0)
    w.step(dt)
    solver.solve(w, dt)

    assert pin in solver.broken, "fragile pin should have moved to solver.broken"
    assert pin not in solver.constraints, "broken pin should leave active set"

    # Subsequent solves are no-ops on the broken constraint -> bodies drift apart.
    for _ in range(30):
        w.step(dt)
        solver.solve(w, dt)
    ax, _ = a.position
    bx, _ = b.position
    sep = abs(ax - bx)
    assert sep > 50.0, f"after break bodies should separate; got sep={sep:.3f}"


# --------------------------------------------------------------------------- #
# Vehicle scenario                                                             #
# --------------------------------------------------------------------------- #


def test_two_pin_constraints_chassis_and_wheels():
    w = _world(no_gravity=True)
    chassis = w.create_body(make_rect_silhouette(60, 24), material="steel", position=(0.0, 0.0))
    wheel_l = _make_ball(w, (-15.0, 12.0), d=12, mat="iron")
    wheel_r = _make_ball(w, (+15.0, 12.0), d=12, mat="iron")
    solver = ConstraintSolver(iterations=8)
    solver.add(PinConstraint(chassis, wheel_l, (-15.0, 12.0), (0.0, 0.0)))
    solver.add(PinConstraint(chassis, wheel_r, (+15.0, 12.0), (0.0, 0.0)))

    # Drive the chassis forward.
    chassis.velocity = (40.0, 0.0)
    dt = w.config.world.default_dt
    x0_chassis = chassis.position[0]
    x0_l = wheel_l.position[0]
    x0_r = wheel_r.position[0]
    for _ in range(30):
        w.step(dt)
        solver.solve(w, dt)
    dx_chassis = chassis.position[0] - x0_chassis
    dx_l = wheel_l.position[0] - x0_l
    dx_r = wheel_r.position[0] - x0_r
    # All three should move together to within 1px.
    assert abs(dx_chassis - dx_l) < 1.0, (
        f"left wheel didn't track chassis: chassis Δx={dx_chassis:.3f}, wheel Δx={dx_l:.3f}"
    )
    assert abs(dx_chassis - dx_r) < 1.0, (
        f"right wheel didn't track chassis: chassis Δx={dx_chassis:.3f}, wheel Δx={dx_r:.3f}"
    )
    assert dx_chassis > 1.0, "chassis should have moved forward at all"


# --------------------------------------------------------------------------- #
# Zero iterations                                                              #
# --------------------------------------------------------------------------- #


def test_solver_zero_iterations_is_noop():
    w = _world(no_gravity=True)
    # Pull bodies apart from each other so they don't collide if the pin
    # fails to enforce -- we want to isolate the solver's effect.
    a = _make_ball(w, (-100.0, 0.0))
    b = _make_ball(w, (100.0, 0.0))
    pin = PinConstraint(a, b, (100.0, 0.0), (-100.0, 0.0))
    solver = ConstraintSolver(iterations=0)
    solver.add(pin)
    a.velocity = (-100.0, 0.0)  # move A further away from B
    dt = w.config.world.default_dt
    for _ in range(30):
        w.step(dt)
        solver.solve(w, dt)
    sep = abs(a.position[0] - b.position[0])
    # With no solve passes, body A flies away from B; if the pin enforced
    # them they'd stay anchored together (sep ~= 200).
    assert sep > 240.0, (
        f"with iterations=0, constraint must NOT enforce; sep={sep:.3f}"
    )


# --------------------------------------------------------------------------- #
# Disabled config                                                              #
# --------------------------------------------------------------------------- #


def test_disabled_in_config_skips_solve():
    w = _world(no_gravity=True)
    a = _make_ball(w, (-20.0, 0.0))
    b = _make_ball(w, (20.0, 0.0))
    pin = PinConstraint(a, b, (20.0, 0.0), (-20.0, 0.0))
    solver = ConstraintSolver(iterations=8, enabled=False)
    solver.add(pin)

    pa_before = a.position
    pb_before = b.position
    a.velocity = (50.0, 0.0)
    dt = w.config.world.default_dt
    # Call solve directly without world.step so we can verify *solve itself*
    # mutates nothing when disabled.
    solver.solve(w, dt)
    assert a.position == pa_before
    assert b.position == pb_before
    assert pin not in solver.broken
