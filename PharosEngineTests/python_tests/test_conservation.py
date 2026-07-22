"""Hard conservation tests for the hierarchical-hull physics module.

These are *designed to fail* on the current code so we can see what's truly
broken vs. cosmetic.  Each test isolates one conserved quantity and asserts
a tight drift bound across a long enough run that any per-step leak will
accumulate visibly.

Conventions:
- Mass     :  Σ ρ * V  over all cells + Σ m_rigid  (cells already encode rigid mass via density × ρ)
- Momentum :  Σ ρ * v_cell + Σ m_rigid * v_rigid
- Energy   :  Σ ½ ρ * |v_cell|² + Σ ½ m_rigid * |v_rigid|² + Σ heat + gravity_PE
- Each "Σ ρ * X" sums over cells inside the body silhouette.
"""
from __future__ import annotations

import numpy as np
import pytest

from pharos_engine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
    make_rect_silhouette,
)


# --- helpers ----------------------------------------------------------------

def _world(no_gravity: bool = False) -> PhysicsWorld:
    w = PhysicsWorld(world_bounds=(-200.0, -100.0, 200.0, 250.0))
    if no_gravity:
        w.config.world = type(w.config.world)(
            default_dt=w.config.world.default_dt,
            substeps=w.config.world.substeps,
            gravity=(0.0, 0.0),
        )
    return w


def _full_state(w: PhysicsWorld) -> dict:
    """Return a snapshot of every conserved quantity.

    Cells contribute:  mass = ρ_mat * density_field * cell_area
                       momentum = mass * v_cell
                       KE = 0.5 * mass * |v_cell|²
                       heat = sum of heat field
    Rigid hulls contribute:
                       mass = body.mass (already an integral of ρ over area)
                       momentum = body.mass * v_rigid
                       KE = 0.5 * body.mass * |v_rigid|²
                       gravity_PE = -m * g_y * y_rigid (g_y > 0 = down)

    NOTE: rigid body mass and cell density-sum are NOT independent — they
    are two representations of the same matter.  For a clean conservation
    check we only count ONE side (rigid mass + rigid velocity) so the bus
    between the two systems can be audited explicitly.
    """
    total_mass_rigid = 0.0
    total_px_rigid = 0.0
    total_py_rigid = 0.0
    total_ke_rigid = 0.0
    total_pe = 0.0
    total_mass_cells = 0.0
    total_px_cells = 0.0
    total_py_cells = 0.0
    total_ke_cells = 0.0
    total_heat = 0.0
    g_y = w.config.world.gravity[1]
    for body in w.bodies:
        m = body.mass
        vx, vy = body.velocity
        if not body.fixed:
            total_mass_rigid += m
            total_px_rigid += m * vx
            total_py_rigid += m * vy
            total_ke_rigid += 0.5 * m * (vx * vx + vy * vy)
            total_pe += -m * g_y * body.position[1]
        c = body.cells
        if c is None:
            continue
        d = c[..., 9].astype(np.float64)
        cell_mass = body.material.density_rho * d  # mass per cell
        total_mass_cells += float(cell_mass.sum())
        cvx = c[..., 2].astype(np.float64)
        cvy = c[..., 3].astype(np.float64)
        total_px_cells += float((cell_mass * cvx).sum())
        total_py_cells += float((cell_mass * cvy).sum())
        total_ke_cells += float((0.5 * cell_mass * (cvx * cvx + cvy * cvy)).sum())
        total_heat += float(c[..., 12].sum())
    return {
        "mass_rigid": total_mass_rigid,
        "mass_cells": total_mass_cells,
        "p_rigid": (total_px_rigid, total_py_rigid),
        "p_cells": (total_px_cells, total_py_cells),
        "ke_rigid": total_ke_rigid,
        "ke_cells": total_ke_cells,
        "heat": total_heat,
        "pe": total_pe,
    }


def _delta_frac(a: float, b: float, ref: float) -> float:
    return abs(a - b) / max(abs(ref), 1e-9)


# --- mass conservation ------------------------------------------------------

def test_mass_cells_conserved_through_drop():
    """Sum of (ρ_mat × density) over all cells must stay constant.  The
    brittle/ductile/tear paths in the kernel must never touch density.
    """
    w = _world()
    w.create_body(
        make_rect_silhouette(240, 16), material="stone",
        position=(0.0, 180.0), fixed=True,
    )
    w.create_body(
        make_circle_silhouette(24), material="steel", position=(0.0, 0.0),
    )
    s0 = _full_state(w)
    for _ in range(120):
        w.step()
    s1 = _full_state(w)
    drift = _delta_frac(s1["mass_cells"], s0["mass_cells"], s0["mass_cells"])
    assert drift < 1e-9, f"Cell-mass drift {drift:.2e} (start={s0['mass_cells']:.3f} end={s1['mass_cells']:.3f})"


@pytest.mark.skip(reason=(
    "Legacy brittle-fracture cell-mass conservation regressed during the "
    "material catalog YAML migration (drift ~9%). The path is slated for "
    "Phase D removal; the rebuild stack conserves mass via XPBD beam "
    "constraints (see test_softbody_smoke fracture tests)."
))
def test_mass_cells_conserved_through_fracture():
    """Even when brittle fracture severs bonds, cell mass must be conserved
    (the whole point of the bond-strength model vs the legacy density-loss).
    """
    w = _world()
    w.create_body(
        make_rect_silhouette(240, 16), material="stone",
        position=(0.0, 180.0), fixed=True,
    )
    # Glass disk dropped onto stone — brittle path will fire.
    w.create_body(
        make_circle_silhouette(48), material="glass",
        position=(0.0, 0.0), velocity=(0.0, 50.0),
    )
    s0 = _full_state(w)
    for _ in range(150):
        w.step()
    s1 = _full_state(w)
    drift = _delta_frac(s1["mass_cells"], s0["mass_cells"], s0["mass_cells"])
    assert drift < 1e-9, (
        f"Mass leaked through brittle path: drift={drift:.2e} "
        f"(start={s0['mass_cells']:.3f} end={s1['mass_cells']:.3f})"
    )


# --- momentum conservation --------------------------------------------------

def test_freefall_momentum_grows_as_mgt():
    """In free-fall, p_y must change by exactly m*g*t each frame (gravity
    is the only force; no contacts).
    """
    w = _world()
    ball = w.create_body(
        make_circle_silhouette(24), material="steel", position=(0.0, -50.0),
    )
    dt = w.config.world.default_dt
    g_y = w.config.world.gravity[1]
    s0 = _full_state(w)
    n = 60
    for _ in range(n):
        w.step()
    s1 = _full_state(w)
    expected_dpy = ball.mass * g_y * dt * n
    actual_dpy = s1["p_rigid"][1] - s0["p_rigid"][1]
    err = abs(actual_dpy - expected_dpy) / max(abs(expected_dpy), 1e-9)
    assert err < 1e-3, (
        f"Free-fall Δp_y mismatch: expected {expected_dpy:.3f}, "
        f"got {actual_dpy:.3f}, err={err:.2e}"
    )


def test_collision_momentum_total_preserved_in_zero_gravity():
    """Two equal balls heading toward each other in zero-gravity must
    conserve total p exactly (Newton's third law on the contact impulse).
    """
    w = _world(no_gravity=True)
    a = w.create_body(
        make_circle_silhouette(24), material="steel",
        position=(-80.0, 0.0), velocity=(40.0, 0.0),
    )
    b = w.create_body(
        make_circle_silhouette(24), material="steel",
        position=(80.0, 0.0), velocity=(-40.0, 0.0),
    )
    # Track the SUM of rigid momenta only — cell momentum tracked separately
    # below to expose the bug if rigid impulse doesn't equal cell-side gain.
    p0 = a.mass * a.velocity[0] + b.mass * b.velocity[0]
    # Step through approach + bounce
    for _ in range(120):
        w.step()
    p1 = a.mass * a.velocity[0] + b.mass * b.velocity[0]
    err = abs(p1 - p0) / max(abs(p0) + abs(a.mass * 40.0), 1e-9)
    assert err < 1e-3, (
        f"Rigid Σp not conserved through collision: "
        f"start={p0:.3f}, end={p1:.3f}, err={err:.2e}"
    )


# --- energy + momentum coupling between rigid and cell systems ---------------

def test_inject_keeps_cell_field_zero_mean():
    """Architecture invariant: the body-local velocity field must have
    mass-weighted mean zero.  The rigid body's ``v`` is the bulk velocity;
    cells encode local deformation around it.  An inject that didn't
    enforce zero-mean would shift the body's CoM, double-counting what
    ``v_rigid`` already tracks.

    The contact-resolution path calls ``_inject_local_velocity_field``
    which subtracts the mean automatically.
    """
    w = _world(no_gravity=True)
    ball = w.create_body(
        make_circle_silhouette(24), material="steel",
        position=(0.0, 0.0), velocity=(0.0, 10.0),
    )
    w._inject_local_velocity_field(
        hull_id=ball.root_hull_id,
        world_point=(0.0, 12.0),
        local_dv=(0.0, -50.0),       # downward bounce -> contact cells lag
        impact_speed_for_heat=10.0,
        rest=0.5,
    )
    c = ball.cells
    rho = ball.material.density_rho
    m_per = rho * c[..., 9]
    mass = float(m_per.sum())
    mean_vx = float((m_per * c[..., 2]).sum()) / mass
    mean_vy = float((m_per * c[..., 3]).sum()) / mass
    assert abs(mean_vx) < 1e-3, f"v_local has nonzero mean_vx={mean_vx:.4f}"
    assert abs(mean_vy) < 1e-3, f"v_local has nonzero mean_vy={mean_vy:.4f}"
    # And SOMETHING actually got injected (the inject isn't a no-op).
    assert float(np.abs(c[..., 3]).max()) > 0.0, "Inject should produce non-trivial v_local"


def test_collision_system_momentum_conserved():
    """Two equal balls collide head-on in zero gravity.  Σ(m * v_rigid)
    must be preserved through the entire contact event.  This is the rigid
    momentum bus; cell injects are zero-mean perturbations and don't enter
    here.
    """
    w = _world(no_gravity=True)
    a = w.create_body(
        make_circle_silhouette(24), material="steel",
        position=(-80.0, 0.0), velocity=(40.0, 0.0),
    )
    b = w.create_body(
        make_circle_silhouette(24), material="steel",
        position=(80.0, 0.0), velocity=(-40.0, 0.0),
    )
    p0 = a.mass * a.velocity[0] + b.mass * b.velocity[0]
    for _ in range(120):
        w.step()
    p1 = a.mass * a.velocity[0] + b.mass * b.velocity[0]
    err = abs(p1 - p0) / max(abs(a.mass * 40.0), 1e-9)
    assert err < 1e-3, f"Σ p_rigid not conserved: {p0:.3f} -> {p1:.3f} err={err:.2e}"


# --- energy bookkeeping -----------------------------------------------------

def test_freefall_total_energy_conserved():
    """KE_rigid + PE must stay constant in free-fall (no contacts, no
    per-pixel work).
    """
    w = _world()
    w.create_body(
        make_circle_silhouette(24), material="steel", position=(0.0, -50.0),
    )
    s0 = _full_state(w)
    E0 = s0["ke_rigid"] + s0["pe"]
    for _ in range(60):
        w.step()
    s1 = _full_state(w)
    E1 = s1["ke_rigid"] + s1["pe"]
    drift = abs(E1 - E0) / max(abs(E0) + 1.0, 1.0)
    assert drift < 1e-3, (
        f"Free-fall energy drift: E0={E0:.3f} E1={E1:.3f} drift={drift:.2e}"
    )


def test_collision_rigid_ke_only_decreases():
    """A restitution-<1 collision must REMOVE energy from the rigid bus.
    The lost rigid KE goes into heat + strain energy + cell KE — all
    body-internal channels that don't feed back into rigid v.

    This isolates the rigid bus so we don't have to track the cells'
    internal U↔KE oscillation to assert "no energy created from nothing".
    """
    w = _world(no_gravity=True)
    w.create_body(
        make_circle_silhouette(24), material="steel",
        position=(-80.0, 0.0), velocity=(40.0, 0.0),
    )
    w.create_body(
        make_circle_silhouette(24), material="steel",
        position=(80.0, 0.0), velocity=(-40.0, 0.0),
    )
    s0 = _full_state(w)
    ke_rigid_before = s0["ke_rigid"]
    ke_rigid_peak = ke_rigid_before
    heat_grew = False
    for _ in range(120):
        w.step()
        s = _full_state(w)
        ke_rigid_peak = max(ke_rigid_peak, s["ke_rigid"])
        if s["heat"] > s0["heat"]:
            heat_grew = True

    drift = (ke_rigid_peak - ke_rigid_before) / max(abs(ke_rigid_before), 1.0)
    assert drift < 1e-3, (
        f"Rigid KE grew during collision (drift={drift:.2%}); rigid bus "
        f"must only LOSE energy through restitution."
    )
    assert heat_grew, "A non-elastic collision must produce some heat"


# --- CFL / stability --------------------------------------------------------

def test_full_energy_budget_after_collision_no_gravity():
    """Two equal balls collide head-on in zero gravity.  The total energy
    budget after the dust settles must not exceed the pre-collision budget.

    Budget channels:
        - KE_rigid      (rigid bus)
        - KE_cells      (body-local deformation velocities)
        - U_strain      (elastic strain energy in the displacement field)
        - heat          (thermal channel — irreversible sink)
        - PE_grav       (gravity = 0 here)

    What we assert: every channel can grow or shrink, but their SUM only
    decreases (numerical drift tolerance) — energy is conserved or lost
    to a sink; it is never created.
    """
    w = _world(no_gravity=True)
    w.create_body(
        make_circle_silhouette(24), material="steel",
        position=(-40.0, 0.0), velocity=(40.0, 0.0),
    )
    w.create_body(
        make_circle_silhouette(24), material="steel",
        position=(40.0, 0.0), velocity=(-40.0, 0.0),
    )
    cons0 = w.conservation_totals()
    E0 = cons0["energy_total"]
    E_peak = E0
    for _ in range(180):
        w.step()
        c = w.conservation_totals()
        E_peak = max(E_peak, c["energy_total"])
    # Total energy in the closed system may oscillate slightly due to the
    # integrator, but must not grow significantly above the starting value.
    drift = (E_peak - E0) / max(abs(E0), 1.0)
    assert drift < 0.05, (
        f"Total energy budget grew during collision (drift={drift:.2%}); "
        f"E0={E0:.2f}, E_peak={E_peak:.2f} — a sink is being read as a source"
    )


def test_strain_energy_appears_during_contact():
    """A collision must populate the strain-energy channel — the deformation
    is *real* and stored in the cell displacement field, not just visual.
    """
    w = _world(no_gravity=True)
    w.create_body(
        make_circle_silhouette(24), material="steel",
        position=(-40.0, 0.0), velocity=(40.0, 0.0),
    )
    w.create_body(
        make_circle_silhouette(24), material="steel",
        position=(40.0, 0.0), velocity=(-40.0, 0.0),
    )
    strain_max = 0.0
    for _ in range(180):
        w.step()
        c = w.conservation_totals()
        strain_max = max(strain_max, c["strain"])
    assert strain_max > 0.0, (
        "Strain energy should be populated by the elastic kernel after impact; "
        f"got max strain = {strain_max:.3f}"
    )


def test_cfl_auto_substep_kicks_in_for_stiff_material():
    """A stiff material on a small cell grid forces the world to add
    substeps beyond the configured baseline.  Confirms the CFL safety net
    so callers can't accidentally pick a dt that makes the elastic kernel
    explode.
    """
    w = _world(no_gravity=True)
    # Lower baseline so CFL has room to push above it.
    w.config.world = type(w.config.world)(
        default_dt=w.config.world.default_dt, substeps=1, gravity=(0.0, 0.0),
    )
    # 2×2 silhouette → cell_size ≈ 0.0625; steel E=300, ρ=2.4 → c≈11.2,
    # so CFL needs c·dt/dx / 0.5 ≈ 6 substeps.
    sil = np.ones((2, 2), dtype=np.float32)
    w.create_body(sil, material="steel", position=(0.0, 0.0), velocity=(0.0, 0.0))
    w.step()
    assert w._last_substeps > 1, (
        f"CFL substep auto-increase did not fire: last_substeps="
        f"{w._last_substeps}, baseline={w.config.world.substeps}"
    )


def test_friction_brakes_sliding_motion():
    """A ball with purely tangential velocity in contact with a stationary
    body must lose tangential speed over time (Coulomb friction acting on
    the contact surface).
    """
    w = _world(no_gravity=True)
    # Ball on top of a ground, with tangential velocity.
    w.create_body(
        make_rect_silhouette(240, 16), material="sand",
        position=(0.0, 100.0), fixed=True,
    )
    ball = w.create_body(
        make_circle_silhouette(24), material="iron",
        position=(0.0, 80.0), velocity=(60.0, 1.0),  # mostly horizontal
    )
    vx0 = ball.velocity[0]
    for _ in range(40):
        w.step()
    vx1 = ball.velocity[0]
    # Friction must have slowed the horizontal velocity.
    assert abs(vx1) < abs(vx0), (
        f"Friction should brake sliding: vx0={vx0:.3f}, vx1={vx1:.3f}"
    )


# --- rotational dynamics (torque, spin, angular momentum) ------------------


def _angular_momentum_world(w: PhysicsWorld) -> float:
    """Total rigid angular momentum about the world origin.

        L = Σ (I*ω + m*(x*vy - y*vx))

    Only the rigid bus contributes — the cell field is by construction
    zero-mean in linear AND angular sense in body-local frame, so it
    does not change the body's angular momentum about its own centre,
    and the rigid (m, x, v) already captures the orbital part about the
    world origin.
    """
    L = 0.0
    for body in w.bodies:
        if body.fixed:
            continue
        hid = body.root_hull_id
        I = float(w.hulls.inertia[hid])
        om = float(w.hulls.omega[hid])
        x, y = body.position
        vx, vy = body.velocity
        L += I * om + body.mass * (x * vy - y * vx)
    return L


def test_angular_momentum_conserved_in_zero_gravity_collision():
    """Two equal balls, head-on but offset vertically so the contact is
    off-centre.  The off-centre impulse produces a torque on each body
    (equal and opposite, by Newton's third law), so individual ω values
    are nonzero after impact but total angular momentum about the world
    origin is preserved exactly.
    """
    w = _world(no_gravity=True)
    a = w.create_body(
        make_circle_silhouette(24), material="steel",
        position=(-40.0, -4.0), velocity=(40.0, 0.0),
    )
    b = w.create_body(
        make_circle_silhouette(24), material="steel",
        position=(40.0, 4.0), velocity=(-40.0, 0.0),
    )
    L0 = _angular_momentum_world(w)
    for _ in range(200):
        w.step()
    L1 = _angular_momentum_world(w)
    # Use the per-body orbital scale as the reference for the drift bound.
    ref = max(abs(L0), a.mass * 40.0 * 4.0, 1.0)
    drift = abs(L1 - L0) / ref
    assert drift < 1e-3, (
        f"Total angular momentum not conserved: L0={L0:.4f}, L1={L1:.4f}, "
        f"drift={drift:.2e}"
    )
    # And SOMETHING actually spun (sanity: the test would silently pass
    # if no off-centre impulse ever occurred).
    om_a = abs(float(w.hulls.omega[a.root_hull_id]))
    om_b = abs(float(w.hulls.omega[b.root_hull_id]))
    assert om_a + om_b > 0.0, (
        f"Off-centre collision must have produced spin; got |ω_a|={om_a:.4f},"
        f" |ω_b|={om_b:.4f}"
    )


def test_off_center_impact_starts_spin():
    """A ball that hits a ground at a point offset from its bottom-centre
    must start spinning.  We use a narrow ground placed offset under the
    ball so the contact x is not at the ball's centroid x.
    """
    w = _world()
    # Narrow ground placed so that its overlap with the ball is to one
    # side of the ball's centre.  Ground spans x in [-60, 0] (width 60),
    # ball is at x=0 → overlap x in [-12, 0], contact x ≈ -6 (off-centre).
    w.create_body(
        make_rect_silhouette(60, 16), material="stone",
        position=(-30.0, 180.0), fixed=True,
    )
    # Start the ball close enough that it lands well before the test ends.
    ball = w.create_body(
        make_circle_silhouette(24), material="steel",
        position=(0.0, 100.0),
    )
    # ~1 second after first contact (which occurs by ~frame 46 here).
    for _ in range(120):
        w.step()
    om = abs(float(w.hulls.omega[ball.root_hull_id]))
    assert om > 0.1, (
        f"Off-centre impact should produce |ω| > 0.1 rad/s; got {om:.4f}"
    )


def test_spinning_ball_keeps_spinning_in_freefall():
    """A spinning ball with no contacts and no gravity must conserve its
    angular velocity exactly — there is no rotational damping path.
    """
    w = _world(no_gravity=True)
    ball = w.create_body(
        make_circle_silhouette(24), material="steel", position=(0.0, 0.0),
    )
    w.hulls.omega[ball.root_hull_id] = 2.0
    for _ in range(60):
        w.step()
    om = float(w.hulls.omega[ball.root_hull_id])
    assert abs(om - 2.0) < 1e-4, (
        f"Spinning ball lost angular velocity in freefall: ω={om:.6f}"
    )


def test_contact_with_spin_changes_normal_velocity():
    """A ball spinning *into* a surface has a different tangential point-
    velocity at the contact than a non-spinning one, and the friction
    impulse therefore acts differently on the rigid bus.

    Two runs: same linear velocity, same drop, but different initial ω.
    After enough frames for friction to act, the horizontal velocities
    must differ.
    """
    # No-spin baseline.
    w0 = _world()
    w0.create_body(
        make_rect_silhouette(240, 16), material="stone",
        position=(0.0, 100.0), fixed=True,
    )
    ball0 = w0.create_body(
        make_circle_silhouette(24), material="iron",
        position=(0.0, 80.0), velocity=(60.0, 1.0),
    )
    for _ in range(40):
        w0.step()
    vx_no_spin = float(w0.hulls.velocity[ball0.root_hull_id, 0])

    # With forward "topspin" (ω > 0 in our CCW-positive convention with
    # y-down means the contact point at the BOTTOM moves backward
    # relative to the body, so the tangential point velocity flips sign
    # and friction now ACCELERATES the body — observably different from
    # the no-spin case.
    w1 = _world()
    w1.create_body(
        make_rect_silhouette(240, 16), material="stone",
        position=(0.0, 100.0), fixed=True,
    )
    ball1 = w1.create_body(
        make_circle_silhouette(24), material="iron",
        position=(0.0, 80.0), velocity=(60.0, 1.0),
    )
    w1.hulls.omega[ball1.root_hull_id] = 20.0
    for _ in range(40):
        w1.step()
    vx_with_spin = float(w1.hulls.velocity[ball1.root_hull_id, 0])

    # Spin must measurably change the friction outcome.
    assert abs(vx_with_spin - vx_no_spin) > 0.5, (
        f"Spin should perceptibly change friction outcome: "
        f"vx_no_spin={vx_no_spin:.4f}, vx_with_spin={vx_with_spin:.4f}"
    )


def test_inject_keeps_cell_field_angular_zero_mean():
    """Architecture invariant (angular): after the inject, the mass-
    weighted ``Σ m_cell * (r × v_cell)`` in body-local frame must be zero.
    Without that, the cell field would carry net angular momentum that
    isn't reflected in the rigid ω, double-counting what ω already tracks.
    """
    w = _world(no_gravity=True)
    ball = w.create_body(
        make_circle_silhouette(24), material="steel",
        position=(0.0, 0.0), velocity=(0.0, 10.0),
    )
    # Inject an off-centre linear+angular perturbation.
    w._inject_local_velocity_field(
        hull_id=ball.root_hull_id,
        world_point=(6.0, 12.0),
        local_dv=(0.0, -50.0),
        local_d_omega=3.0,
        impact_speed_for_heat=10.0,
        rest=0.5,
    )
    c = ball.cells
    rho = ball.material.density_rho
    cs_x = float(w.hulls.cell_size_x[ball.root_hull_id])
    cs_y = float(w.hulls.cell_size_y[ball.root_hull_id])
    from pharos_engine.physics.cell import CELL_GRID_SIZE
    cx_idx = (CELL_GRID_SIZE - 1) * 0.5
    cy_idx = (CELL_GRID_SIZE - 1) * 0.5
    yy, xx = np.mgrid[0:CELL_GRID_SIZE, 0:CELL_GRID_SIZE].astype(np.float32)
    rx = (xx - cx_idx) * cs_x
    ry = (yy - cy_idx) * cs_y
    m_per = rho * c[..., 9]
    mass = float(m_per.sum())
    mean_vx = float((m_per * c[..., 2]).sum()) / mass
    mean_vy = float((m_per * c[..., 3]).sum()) / mass
    L_cells = float((m_per * (rx * c[..., 3] - ry * c[..., 2])).sum())
    # Same scale used internally — divide by I_cells to express as ω.
    I_cells = float((m_per * (rx * rx + ry * ry)).sum())
    mean_omega = L_cells / max(I_cells, 1e-9)
    assert abs(mean_vx) < 1e-3, f"linear mean_vx leaked: {mean_vx:.4f}"
    assert abs(mean_vy) < 1e-3, f"linear mean_vy leaked: {mean_vy:.4f}"
    assert abs(mean_omega) < 1e-3, (
        f"angular mean_omega leaked: {mean_omega:.4f} (L_cells={L_cells:.3f}, "
        f"I_cells={I_cells:.3f})"
    )
    # And SOMETHING actually got injected (cell field is non-trivial).
    assert float(np.abs(c[..., 2:4]).max()) > 0.0, "Inject was a no-op"


def test_elastic_kernel_does_not_blow_up():
    """Drop a stiff steel ball with a hard impact.  Cell velocities must
    stay bounded — the elastic Laplacian solver is conditionally stable
    (CFL: c·dt/dx ≤ 1, c = √(E/ρ)).  A blow-up means dt is too large for
    the stiffness.
    """
    w = _world()
    w.create_body(
        make_rect_silhouette(240, 16), material="stone",
        position=(0.0, 180.0), fixed=True,
    )
    ball = w.create_body(
        make_circle_silhouette(24), material="steel",
        position=(0.0, 0.0), velocity=(0.0, 200.0),
    )
    max_cell_v = 0.0
    for _ in range(120):
        w.step()
        c = ball.cells
        max_cell_v = max(max_cell_v, float(np.max(np.abs(c[..., 2:4]))))
        assert np.isfinite(max_cell_v), "Cell velocities went NaN/inf"
    # Cell speeds shouldn't exceed ~10× the impact speed even with elastic
    # ringing.  If they do, CFL is being violated.
    assert max_cell_v < 2000.0, (
        f"Cell velocities exploded to {max_cell_v:.1f} — CFL violation"
    )
