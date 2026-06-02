"""Wall-contact tests for the hierarchical-hull physics module.

The wall solver in ``PhysicsWorld._resolve_walls`` was previously a linear
restitution flip on the velocity component normal to the wall.  These tests
pin down its post-refactor invariants: off-centre wall hits must produce
torque, centred hits must not, friction must brake tangential velocity,
the cell field must receive heat and a zero-mean (linear + angular)
velocity inject, and the rigid bounce must not double-count into the cell
field.
"""
from __future__ import annotations

import numpy as np

from slappyengine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
)


_BALL_DIAMETER = 24
_BOUNDS = (-200.0, -200.0, 200.0, 200.0)


def _world() -> PhysicsWorld:
    return PhysicsWorld(world_bounds=_BOUNDS)


def _spawn_ball(
    w: PhysicsWorld,
    *,
    position: tuple[float, float],
    velocity: tuple[float, float],
    material: str = "steel",
):
    return w.create_body(
        make_circle_silhouette(_BALL_DIAMETER),
        material=material,
        position=position,
        velocity=velocity,
    )


def _step_until_wall_contact(w: PhysicsWorld, ball, *, max_frames: int = 240):
    """Step the world until a wall contact resolves on this frame.

    Returns the (frame_index, contacts) pair so the caller can inspect the
    body state directly afterwards.  Fails if no wall contact occurs.
    """
    for f in range(max_frames):
        contacts = w.step()
        wall_hits = [c for c in contacts if c.b == -1 and c.a == ball.root_hull_id]
        if wall_hits:
            return f, wall_hits
    raise AssertionError(f"No wall contact within {max_frames} frames")


# --------------------------------------------------------------------------- #
# 1. Off-centre wall hit produces spin.                                       #
# --------------------------------------------------------------------------- #

def test_ball_scraping_wall_gains_spin():
    """A ball travelling (60, 1) into the left wall hits *just* below
    centre-of-mass height — the contact point sits exactly along the wall
    normal at the body surface (``position - r * n``), so on-paper there's
    no lever arm there.  What gives the ball spin is the *tangential*
    friction impulse: the body's contact-point velocity has a tangential
    component (the ball's vy + the off-axis approach skew), and the
    Coulomb friction impulse applied at radius ``r`` from the body centre
    produces a torque ``r × J_t``.  We assert ``|ω| > 0.05 rad/s`` after
    the contact — the previous linear-only solver would leave ω at zero.
    """
    w = _world()
    # Disable gravity so the test isolates the impulse, not free-fall.
    w.config.world = type(w.config.world)(
        default_dt=w.config.world.default_dt,
        substeps=w.config.world.substeps,
        gravity=(0.0, 0.0),
    )
    # Spawn near the left wall heading into it off-axis (tangential vy = 1).
    ball = _spawn_ball(w, position=(-180.0, 0.0), velocity=(-60.0, 30.0))
    _step_until_wall_contact(w, ball)
    omega = float(w.hulls.omega[ball.root_hull_id])
    assert abs(omega) > 0.05, (
        f"Expected off-centre/tangential wall hit to spin the ball; "
        f"got |omega|={abs(omega):.4f} rad/s"
    )


# --------------------------------------------------------------------------- #
# 2. Pure head-on hit produces no spin.                                       #
# --------------------------------------------------------------------------- #

def test_centred_wall_impact_no_spin():
    """A ball moving purely along the wall normal (no tangential velocity,
    no angular velocity going in) must not pick up any spin: the impulse
    is along the normal, the lever arm to the contact point lies along
    that normal, and ``r × n = 0``.  Friction sees zero tangential
    velocity so it contributes nothing either.
    """
    w = _world()
    w.config.world = type(w.config.world)(
        default_dt=w.config.world.default_dt,
        substeps=w.config.world.substeps,
        gravity=(0.0, 0.0),
    )
    ball = _spawn_ball(w, position=(-180.0, 0.0), velocity=(-100.0, 0.0))
    _step_until_wall_contact(w, ball)
    omega = float(w.hulls.omega[ball.root_hull_id])
    assert abs(omega) < 1e-3, (
        f"Centred wall hit should leave omega ~0; got {omega:.6f}"
    )


# --------------------------------------------------------------------------- #
# 3. Friction brakes tangential velocity at a wall.                           #
# --------------------------------------------------------------------------- #

def test_wall_friction_brakes_tangential_velocity():
    """A ball falling onto the bottom wall with horizontal velocity must
    see ``|vx|`` decrease across the contact.  The previous solver only
    flipped vy and left vx untouched — friction was missing.
    """
    w = _world()
    # Keep gravity so the ball commits to the bottom wall, but use a
    # modest horizontal speed so friction has something to bite into.
    ball = _spawn_ball(w, position=(0.0, 150.0), velocity=(40.0, 50.0))
    vx_pre = ball.velocity[0]
    _step_until_wall_contact(w, ball)
    vx_post = ball.velocity[0]
    assert abs(vx_post) < abs(vx_pre), (
        f"Friction should reduce |vx|: pre={vx_pre:.3f} post={vx_post:.3f}"
    )
    # And the same impulse must inject a corresponding spin into the body
    # (rolling response on the floor).
    assert abs(float(w.hulls.omega[ball.root_hull_id])) > 1e-3, (
        "Friction at the floor should also produce a torque (roll-up)"
    )


# --------------------------------------------------------------------------- #
# 4. Wall contact deposits heat in contact-zone cells.                        #
# --------------------------------------------------------------------------- #

def test_wall_contact_injects_heat():
    """A high-speed wall hit must inject heat into the body's contact-zone
    cells, just like a body-body contact does.  The previous wall path
    bypassed ``_inject_local_velocity_field`` entirely so the heat field
    stayed flat regardless of impact energy.
    """
    w = _world()
    w.config.world = type(w.config.world)(
        default_dt=w.config.world.default_dt,
        substeps=w.config.world.substeps,
        gravity=(0.0, 0.0),
    )
    # Mud over steel so the impact has a big inelastic loss to deposit.
    ball = _spawn_ball(w, position=(-180.0, 0.0), velocity=(-300.0, 0.0),
                      material="mud")
    cells_pre_max_heat = float(ball.cells[..., 12].max())
    _step_until_wall_contact(w, ball)
    cells_post_max_heat = float(ball.cells[..., 12].max())
    assert cells_post_max_heat > cells_pre_max_heat, (
        f"Wall contact should deposit heat in contact-zone cells; "
        f"pre={cells_pre_max_heat:.4f} post={cells_post_max_heat:.4f}"
    )


# --------------------------------------------------------------------------- #
# 5. Cell-field zero-mean invariant survives a wall contact.                  #
# --------------------------------------------------------------------------- #

def test_wall_contact_preserves_zero_mean_invariant():
    """The cell-velocity field is *purely* the per-cell deformation around
    the body's rigid translation + spin.  At the moment the wall inject
    finishes the field's mass-weighted linear and angular momentum about
    the centre of mass must both be ~zero in the body-local frame —
    otherwise the cell inject is silently shifting the body's CoM or its
    spin and double-counting what the rigid state already tracks.

    We measure the invariant *immediately after the wall solve runs* —
    before the per-pixel substep kernel evolves the field, since the
    Hooke-law / fluid-pressure dynamics in the substep are themselves a
    separate solver whose conservation guarantees aren't what this test
    is pinning down.  We do that by calling ``_resolve_walls`` directly
    on a body manually pushed past the wall, which is exactly the path
    ``step()`` takes between integration and substeps.

    We mirror the same invariant ``_inject_local_velocity_field`` enforces
    for body-body contacts: ``Σ m·v ≈ 0`` and ``Σ m·(r × v) ≈ 0``, both
    weighted by per-cell mass and computed about the cell-mass centroid.
    """
    w = _world()
    w.config.world = type(w.config.world)(
        default_dt=w.config.world.default_dt,
        substeps=w.config.world.substeps,
        gravity=(0.0, 0.0),
    )
    ball = _spawn_ball(w, position=(-180.0, 0.0), velocity=(-200.0, 30.0))
    # Manually push the ball through the left wall and invoke the wall
    # solver directly — that runs the inject without the subsequent
    # _cpu_substep evolution touching the cell field.
    hid = ball.root_hull_id
    x0 = _BOUNDS[0]
    r = float(w.hulls.radius[hid])
    w.hulls.position[hid, 0] = x0 + r - 1.0    # ~1px overlap
    wall_hits = w._resolve_walls()
    assert any(c.b == -1 and c.a == hid for c in wall_hits), (
        "Direct _resolve_walls call should produce a wall contact"
    )

    cells = ball.cells
    assert cells is not None
    cs_x = float(w.hulls.cell_size_x[hid])
    cs_y = float(w.hulls.cell_size_y[hid])
    from slappyengine.physics import CELL_GRID_SIZE
    yy, xx = np.mgrid[0:CELL_GRID_SIZE, 0:CELL_GRID_SIZE].astype(np.float32)
    cx_idx = (CELL_GRID_SIZE - 1) * 0.5
    cy_idx = (CELL_GRID_SIZE - 1) * 0.5

    density = cells[..., 9]
    mat_id = int(w.hulls.material_id[hid])
    mat = w._materials[mat_id]
    m_per_cell = mat.density_rho * density
    body_mass = float(m_per_cell.sum())
    assert body_mass > 1e-9

    com_x = float((m_per_cell * (xx - cx_idx)).sum()) / body_mass
    com_y = float((m_per_cell * (yy - cy_idx)).sum()) / body_mass
    rx = (xx - cx_idx - com_x) * cs_x
    ry = (yy - cy_idx - com_y) * cs_y

    vx = cells[..., 2]
    vy = cells[..., 3]
    # Mass-weighted linear and angular momentum of the local field.
    px_local = float((m_per_cell * vx).sum())
    py_local = float((m_per_cell * vy).sum())
    L_local = float((m_per_cell * (rx * vy - ry * vx)).sum())

    # The invariants are scale-relative; normalise by the natural scale of
    # the body so the tolerance is independent of mass / radius.
    radius = float(w.hulls.radius[hid])
    char_v = max(1e-3, float(np.linalg.norm(ball.velocity)))
    p_scale = body_mass * char_v
    L_scale = body_mass * radius * char_v

    assert abs(px_local) / p_scale < 1e-3, (
        f"Linear mean of cell-velocity field not zero: "
        f"|p|/p_scale = {abs(px_local) / p_scale:.2e}"
    )
    assert abs(py_local) / p_scale < 1e-3, (
        f"Linear mean of cell-velocity field not zero: "
        f"|p|/p_scale = {abs(py_local) / p_scale:.2e}"
    )
    assert abs(L_local) / L_scale < 1e-3, (
        f"Angular mean of cell-velocity field not zero: "
        f"|L|/L_scale = {abs(L_local) / L_scale:.2e}"
    )
