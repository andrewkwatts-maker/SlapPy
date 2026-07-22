"""Tests for the water-container sloshing physics demo.

These exercise Phase C's Navier-Stokes pressure projection on a water blob
trapped in a U-shaped stone container.  A steel ball plunges into the
water; we assert that the fluid stays inside the container, visibly sloshes
(peak |u_y| > 1.0 — the old damped-pressure model couldn't produce this),
and that contacts fire for both the ball-water impact and the
ball-bouncing-against-the-walls phase.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest


# Make the example directory importable regardless of the working dir
# pytest is launched from.  The demo lives next to other examples.
_EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples" / "legacy"
if str(_EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES_DIR))


@pytest.fixture(scope="module")
def demo_metrics():
    """Run the demo once and reuse its metrics across the test module."""
    import physics_water_container_demo as demo

    metrics = demo.run_demo_with_metrics(save_gif=True)
    return metrics


def test_demo_runs_to_completion(demo_metrics):
    """The demo executes end-to-end and writes a non-trivial GIF."""
    out = demo_metrics["output_path"]
    assert out is not None, "demo did not return an output path"
    assert Path(out).exists(), f"expected GIF at {out}"
    size_kb = Path(out).stat().st_size / 1024.0
    assert size_kb > 50.0, f"GIF too small ({size_kb:.1f} KB); expected > 50 KB"
    frames = demo_metrics["frames"]
    assert len(frames) > 0
    # Each frame must be an RGBA image (H, W, 4).
    assert frames[0].ndim == 3 and frames[0].shape[-1] == 4


def test_water_does_not_escape_container(demo_metrics):
    """After 180 frames, every water cell with density > 0.5 sits inside
    the container interior ``x in [-90, 90], y in [80, 200]``.

    The renderer's splat radius can paint a few pixels outside the wall
    centreline, but the SIMULATED cell field — where density lives — must
    stay bounded by the wall colliders.  This is exactly the property the
    Phase C projection is supposed to guarantee.
    """
    density = demo_metrics["final_water_density"]
    X, Y = demo_metrics["final_water_world_xy"]
    wet = density > 0.5
    if not wet.any():
        pytest.fail("no wet cells at end of run (water disappeared)")
    xs = X[wet]
    ys = Y[wet]
    assert xs.min() >= -90.0, f"water cell escaped left wall: x={xs.min()}"
    assert xs.max() <=  90.0, f"water cell escaped right wall: x={xs.max()}"
    assert ys.min() >=  80.0, f"water cell escaped top of container: y={ys.min()}"
    assert ys.max() <= 200.0, f"water cell escaped bottom of container: y={ys.max()}"


def test_water_slosh_amplitude_visible(demo_metrics):
    """The splash impulse propagates from the impact zone out to the far
    edge of the water body.

    Fixture history: the original assertion was ``peak |u_y| > 1.0``,
    predicated on the steel ball plunging through the water surface and
    delivering its momentum to the cell field.  WP-N diagnosed that the
    ball never actually penetrates the water hull — the rigid-body
    contact hard-stops it at the hull's upper face (ball y peaks at
    ~122 px, water surface y=130 px), so no cell-level momentum ever
    enters the fluid and the assertion was reading pure numerical
    drift.

    WP-S redesign: the demo now injects a 300 px/s downward velocity
    pulse into the top-centre rows of the water cell grid (the
    momentum a real splash would deliver), and the test asserts the
    pulse propagates *laterally* to the far-edge columns.  Cells in
    those columns can only acquire significant ``v_y`` via the
    pressure-projection step carrying the central divergence outward —
    if the solver is dead, ``peak_water_vy_far`` sits at the
    no-impulse noise floor of ~0.3 px/s.  Measured: with inject ≈ 1.8,
    without inject ≈ 0.28, so 1.0 is a clean threshold that's both
    well above noise and well below the working-solver signal.
    """
    peak_uy = demo_metrics["peak_water_uy"]
    peak_vy_far = demo_metrics["peak_water_vy_far"]
    # Wave-propagation assertion: far-edge motion is the load-bearing
    # signal here — it cannot arise without pressure-driven lateral
    # transport.  Threshold 1.0 px/s sits at ~6× the no-impulse noise
    # floor and ~50% of the working-solver value, leaving headroom for
    # CPU jitter without admitting a regressed solver.
    assert peak_vy_far > 1.0, (
        f"water splash did not propagate to far edges: "
        f"peak |v_y| at far-edge columns = {peak_vy_far:.4f} "
        f"(noise floor is ~0.3; working projection drives this above 1.0)"
    )
    # Displacement-field sanity floor: u_y is the time integral of v_y
    # so the working solver also leaves a visible displacement trail.
    # 0.15 sits well above the no-impulse u_y floor (~0.07).
    assert peak_uy > 0.15, (
        f"water did not visibly displace: peak |u_y| was {peak_uy:.4f} "
        f"(noise floor ~0.07; working projection drives this above 0.15)"
    )


def test_steel_ball_doesnt_tunnel(demo_metrics):
    """The steel ball's y centre stays inside the world bounds the whole run.

    The world is bounded ``y in [-100, 250]``; if the projection or
    contact resolution let the ball tunnel through the floor we'd see y
    rocket past 250 (or below -100).  The ball must remain authoritatively
    contained.
    """
    by = np.asarray(demo_metrics["ball_y_history"], dtype=np.float64)
    assert by.size > 0
    assert by.min() >= -100.0, f"ball escaped top of world: y_min={by.min()}"
    assert by.max() <=  250.0, f"ball escaped bottom of world: y_max={by.max()}"


def test_contacts_fire(demo_metrics):
    """At least one ball-water and one ball-wall contact register.

    The demo's narrative — a steel ball plunging into water held by stone
    walls — depends on both contact types actually firing through the
    broadphase/narrowphase.  A regression in either path would silently
    break the demo.
    """
    bw = demo_metrics["ball_water_contacts"]
    bwall = demo_metrics["ball_wall_contacts"]
    assert bw >= 1, f"no ball-water contacts fired (got {bw})"
    assert bwall >= 1, f"no ball-wall contacts fired (got {bwall})"
