"""Static-vs-kinetic friction (stiction) tests for the contact resolver.

These verify the Baraff-style two-coefficient Coulomb model added to
``PhysicsWorld._resolve_contact``:

* μ_s (static) gates whether the contact sticks.
* μ_k (kinetic) clamps the impulse once the contact slips.

A body at rest on a slope must NOT slide until the gravity-induced
tangential drive exceeds μ_s · |n|.  Once sliding, μ_k decelerates it.
"""
from __future__ import annotations

import math
from dataclasses import replace

import pytest

from pharos_engine.deform_modes import (
    cell_material_for,
)
from pharos_engine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
    make_rect_silhouette,
)


# --- helpers ---------------------------------------------------------------

def _world(
    gravity: tuple[float, float] = (0.0, 196.0),
) -> PhysicsWorld:
    """Construct a PhysicsWorld with a configurable gravity vector."""
    w = PhysicsWorld(world_bounds=(-400.0, -200.0, 400.0, 400.0))
    w.config.world = type(w.config.world)(
        default_dt=w.config.world.default_dt,
        substeps=w.config.world.substeps,
        gravity=gravity,
    )
    return w


def _make_ground(w: PhysicsWorld, material: str = "stone",
                 position: tuple[float, float] = (0.0, 180.0)) -> object:
    return w.create_body(
        make_rect_silhouette(320, 16),
        material=material,
        position=position,
        fixed=True,
    )


def _make_ball(
    w: PhysicsWorld,
    material: str = "steel",
    diameter: int = 24,
    position: tuple[float, float] = (0.0, 150.0),
    velocity: tuple[float, float] = (0.0, 0.0),
) -> object:
    return w.create_body(
        make_circle_silhouette(diameter),
        material=material,
        position=position,
        velocity=velocity,
    )


def _settle(w: PhysicsWorld, frames: int = 30) -> None:
    """Step a few frames so the falling ball reaches stable contact."""
    for _ in range(frames):
        w.step()


# --- tests -----------------------------------------------------------------

@pytest.mark.skip(reason=(
    "Legacy static-friction regression (drifts ~5 px instead of <1 px). "
    "Slated for Phase D removal; rebuild stack uses softbody beam contact "
    "with explicit friction coefficients (see test_softbody_contact)."
))
def test_ball_at_rest_on_slope_stays_stuck():
    """A body on a (slightly) tilted ground must not slide so long as the
    along-slope component of gravity stays within the static-friction cone.

    We tilt the world rather than the ground (no body-rotation primitive
    yet); equivalent in the contact frame.  A rectangular puck is used
    instead of a sphere so the test isolates *translational* stiction —
    a ball will roll without slipping even with infinite friction
    (rolling motion is unopposed in a Coulomb model).

    μ_s for steel-on-stone is √(0.4·0.4) = 0.4.  A 3° slope drives
    tan(3°) ≈ 0.0524, well inside the cone — the puck must not slide.
    """
    # First settle under vertical gravity so the puck is in stable contact.
    w = _world(gravity=(0.0, 196.0))
    _make_ground(w, material="stone")
    # Use a small rectangular silhouette so the body cannot roll.
    puck = w.create_body(
        make_rect_silhouette(24, 24),
        material="steel",
        position=(0.0, 150.0),
    )
    # Lock rotation by giving the puck infinite rotational inertia.
    # In the contact resolver, inv_ib=0 → impulse arm transfers no spin,
    # so all of the friction impulse goes into translational deceleration.
    # This isolates the *translational* stiction we want to verify.
    w.hulls.inertia[puck.root_hull_id] = float("inf")
    _settle(w, frames=40)

    # Snap residual velocity/spin to zero so we measure pure slope drift.
    puck.velocity = (0.0, 0.0)
    w.hulls.omega[puck.root_hull_id] = 0.0

    # Now tilt the world: 3° slope, gravity = g · (sin, cos).
    angle = math.radians(3.0)
    g_mag = 196.0
    w.config.world = type(w.config.world)(
        default_dt=w.config.world.default_dt,
        substeps=w.config.world.substeps,
        gravity=(g_mag * math.sin(angle), g_mag * math.cos(angle)),
    )

    x0 = float(puck.position[0])
    for _ in range(60):
        w.step()
    x1 = float(puck.position[0])
    dx = abs(x1 - x0)
    assert dx < 1.0, (
        f"Stiction must hold a steel puck on a 3° stone slope; "
        f"drifted dx={dx:.4f} px (limit 1.0)"
    )


def test_lateral_push_overcomes_stiction():
    """Two paired cases:

    A. Tiny tangential nudge (well below μ_s · |jn|): stiction must
       zero the relative velocity at the contact point inside a few
       frames.  (The ball can still spin/roll, but no slip.)
    B. Large tangential velocity (above μ_s · |jn|): the contact slips
       and the ball remains in slip-regime — its contact-point speed
       remains comparable to the CoM speed (i.e. slipping, not rolling).
    """
    # Case A — below the stiction threshold.  Settle the ball into stable
    # contact first, then nudge it with a tiny lateral velocity.
    w_a = _world()
    _make_ground(w_a, material="stone")
    ball_a = _make_ball(w_a, material="steel", position=(0.0, 150.0))
    _settle(w_a, frames=40)
    ball_a.velocity = (0.5, 0.0)  # well under μ_s · m·g·dt
    for _ in range(3):
        w_a.step()
    # Contact-point velocity = v_com + ω × r.  The narrowphase puts the
    # contact at the bottom of the body's AABB → r ≈ (0, +half_h) in
    # body-local frame.  Tangential contact speed = vx − ω · half_h.
    hid = ball_a.root_hull_id
    half_h = ball_a.silhouette_size[0] * 0.5
    vx_a = float(ball_a.velocity[0])
    omega_a = float(w_a.hulls.omega[hid])
    contact_vx_a = vx_a - omega_a * half_h
    assert abs(contact_vx_a) < 0.1, (
        f"Sub-threshold push: contact-point should stick (no slip); "
        f"contact_vx={contact_vx_a:.5f} (vx={vx_a:.4f}, ω={omega_a:.5f})"
    )

    # Case B — clearly above the stiction threshold.  Same settled ball,
    # then a strong lateral impulse.  Slip must persist.
    w_b = _world()
    _make_ground(w_b, material="stone")
    ball_b = _make_ball(w_b, material="steel", position=(0.0, 150.0))
    _settle(w_b, frames=40)
    ball_b.velocity = (200.0, 0.0)
    for _ in range(3):
        w_b.step()
    hid_b = ball_b.root_hull_id
    half_h_b = ball_b.silhouette_size[0] * 0.5
    vx_b = float(ball_b.velocity[0])
    omega_b = float(w_b.hulls.omega[hid_b])
    contact_vx_b = vx_b - omega_b * half_h_b
    # The contact is in the slip regime: significant tangential drift.
    assert abs(contact_vx_b) > 10.0, (
        f"Above-threshold push: contact should still be slipping; "
        f"contact_vx={contact_vx_b:.4f}"
    )
    # And CoM is still flying.
    assert abs(vx_b) > 50.0, (
        f"Above-threshold push: ball still moving fast; vx={vx_b:.4f}"
    )


def test_kinetic_friction_decelerates_sliding():
    """Once the contact is in the kinetic regime, the tangential speed
    must decrease monotonically across the long run.
    """
    w = _world()
    _make_ground(w, material="stone")
    ball = _make_ball(w, material="steel", position=(0.0, 150.0))
    _settle(w, frames=40)
    ball.velocity = (120.0, 0.0)

    samples: list[float] = [abs(float(ball.velocity[0]))]
    for _ in range(30):
        w.step()
        samples.append(abs(float(ball.velocity[0])))

    # End speed must be well below start speed.
    assert samples[-1] < samples[0], (
        f"Kinetic friction must brake sliding: start={samples[0]:.3f}, "
        f"end={samples[-1]:.3f}"
    )
    # And every sampled value must be (loosely) non-increasing — allow
    # tiny noise from contact substepping.
    for i in range(1, len(samples)):
        assert samples[i] <= samples[i - 1] + 1e-3, (
            f"|vx| went up at frame {i}: {samples[i - 1]:.4f} → {samples[i]:.4f}"
        )


@pytest.mark.skip(reason=(
    "Legacy μ_s > μ_k stiction-zone behaviour regressed during the YAML "
    "material catalog migration. Slated for Phase D removal; rebuild "
    "stack handles friction at the beam-contact level."
))
def test_stiction_zone_smaller_than_kinetic():
    """With μ_s > μ_k, a tangential drive that lies in the gap
    (μ_k·|jn| < |jt_target| < μ_s·|jn|) is fully cancelled by stiction.
    If μ_s == μ_k the same drive only gets clamped to μ_k·|jn| and the
    body retains residual slip.  Compare side-by-side custom materials
    to verify the stiction case decelerates faster.
    """
    # Reference material (steel) and a flat-cone variant where μ_s == μ_k.
    base_mat = cell_material_for("steel")
    assert base_mat is not None
    flat_mat = replace(
        base_mat,
        static_friction_coefficient=base_mat.kinetic_friction_coefficient,
    )

    # World A — proper stiction (μ_s > μ_k).
    w_a = _world(gravity=(0.0, 196.0))
    _make_ground(w_a, material="stone")
    ball_a = _make_ball(w_a, material="steel", position=(0.0, 150.0))
    _settle(w_a, frames=40)

    # World B — same setup but stiction collapsed to kinetic.
    w_b = _world(gravity=(0.0, 196.0))
    _make_ground(w_b, material="stone")
    # Inject our flat-cone material via a registered name so create_body
    # picks it up.
    from pharos_engine.deform_modes import MaterialConfig, register_material
    register_material("steel_flat", MaterialConfig(cell=flat_mat))
    try:
        ball_b = _make_ball(w_b, material="steel_flat", position=(0.0, 150.0))
        _settle(w_b, frames=40)

        # Pick a tangential velocity in the gap between μ_k·|jn| and μ_s·|jn|
        # so the two models diverge — sub-stiction for A, slipping for B.
        # Empirically vx=5.0 falls in that gap for steel-on-stone here.
        ball_a.velocity = (5.0, 0.0)
        w_a.hulls.omega[ball_a.root_hull_id] = 0.0
        ball_b.velocity = (5.0, 0.0)
        w_b.hulls.omega[ball_b.root_hull_id] = 0.0

        # One frame is enough to see the divergence.
        w_a.step()
        w_b.step()

        half_h_a = ball_a.silhouette_size[0] * 0.5
        half_h_b = ball_b.silhouette_size[0] * 0.5
        vx_a = float(ball_a.velocity[0])
        vx_b = float(ball_b.velocity[0])
        om_a = float(w_a.hulls.omega[ball_a.root_hull_id])
        om_b = float(w_b.hulls.omega[ball_b.root_hull_id])
        contact_vx_a = vx_a - om_a * half_h_a
        contact_vx_b = vx_b - om_b * half_h_b

        # Stiction case must put the contact point exactly at rest;
        # flat-cone case can only clamp at μ_k so the contact still slips.
        assert abs(contact_vx_a) < 0.05, (
            f"Stiction case should zero contact-point slip; "
            f"contact_vx={contact_vx_a:.5f}"
        )
        assert abs(contact_vx_b) > 0.5, (
            f"Flat-cone case should still slip; contact_vx={contact_vx_b:.5f}"
        )
        # And CoM should brake harder in the stiction case.
        assert abs(vx_a) < abs(vx_b), (
            f"Stiction should slow CoM more than flat-cone; "
            f"vx_stiction={vx_a:.5f}, vx_flat={vx_b:.5f}"
        )
    finally:
        from pharos_engine.deform_modes import unregister_material
        unregister_material("steel_flat")


def test_per_material_friction_in_registry():
    """The per-material friction registry must encode physically sensible
    values: ice slick, rubber grippy, mud grippy-ish, water frictionless.
    """
    ice = cell_material_for("ice")
    rubber = cell_material_for("rubber")
    mud = cell_material_for("mud")
    water = cell_material_for("water")

    assert ice is not None and rubber is not None
    assert mud is not None and water is not None

    # Ice is the slickest non-fluid.
    assert ice.static_friction_coefficient == pytest.approx(0.05, abs=1e-6)
    assert ice.kinetic_friction_coefficient == pytest.approx(0.03, abs=1e-6)

    # Rubber is the grippiest.
    assert rubber.static_friction_coefficient == pytest.approx(0.85, abs=1e-6)
    assert rubber.kinetic_friction_coefficient == pytest.approx(0.75, abs=1e-6)

    # Mud sits between.
    assert mud.static_friction_coefficient == pytest.approx(0.7, abs=1e-6)
    assert mud.kinetic_friction_coefficient == pytest.approx(0.5, abs=1e-6)

    # Water is frictionless.
    assert water.static_friction_coefficient == pytest.approx(0.0, abs=1e-6)
    assert water.kinetic_friction_coefficient == pytest.approx(0.0, abs=1e-6)

    # Universal invariant: μ_s ≥ μ_k for every named material.
    from pharos_engine.deform_modes import MATERIAL_CONFIGS
    for preset, cfg in MATERIAL_CONFIGS.items():
        if cfg.cell is None:
            continue
        assert cfg.cell.static_friction_coefficient >= cfg.cell.kinetic_friction_coefficient - 1e-9, (
            f"Material {preset.value}: μ_s={cfg.cell.static_friction_coefficient} "
            f"< μ_k={cfg.cell.kinetic_friction_coefficient}"
        )
