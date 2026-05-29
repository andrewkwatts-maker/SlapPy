"""Tests for the ``examples/hello_motor.py`` demo.

These tests pin five things:

1. The demo's ``main()`` is callable in-process and doesn't raise.
2. After 240 frames the measured rim angular velocity is within 20% of
   the configured ``target_omega`` — guards the motor projection from
   silently regressing.
3. The hub-to-rim distance stays within ``RADIUS +/- 0.05`` across the
   full trajectory — guards the rim distance joints from drifting.
4. No NaNs leak out of the XPBD solver.
5. The visual rasterisation reproduces a stable golden master via the
   :mod:`slappyengine.testing` harness (golden on first run, diff on
   subsequent runs).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from slappyengine.testing import assert_scene_matches

# ── Load the demo as a module so we don't depend on examples/ being on path ──
_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEMO_PATH = _REPO_ROOT / "examples" / "hello_motor.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("hello_motor_demo", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_motor_demo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


# ────────────────────────────────────────────────────────────────────────────
# Test 1: demo runs cleanly
# ────────────────────────────────────────────────────────────────────────────

def test_hello_motor_runs_without_error(demo, tmp_path):
    """``main(frames=60, render=False)`` returns a summary and never raises."""
    summary = demo.main(frames=60, render=False, out=tmp_path / "ignored.png")
    assert summary["frames"] == 60
    assert summary["hub_position"] == (0.0, 0.0)
    assert np.isfinite(summary["rim_a_final_angle"])
    assert np.isfinite(summary["rim_b_final_angle"])
    assert np.isfinite(summary["measured_omega"])
    assert summary["nan_seen"] is False


# ────────────────────────────────────────────────────────────────────────────
# Test 2: motor reaches its target angular velocity
# ────────────────────────────────────────────────────────────────────────────

def test_hello_motor_spins_at_target_omega(demo):
    """After 240 frames the measured ω is within 20% of ``target_omega``."""
    world, info = demo.build_world()
    trace = demo.step_world(world, info, frames=240, dt=demo.DEFAULT_DT)
    summary = demo.summarise(world, info, trace, frames=240)

    target = float(demo.TARGET_OMEGA)
    measured = float(summary["measured_omega"])
    assert target > 0.0
    ratio = measured / target
    # Specification: within 20% (i.e. ratio in [0.8, 1.2]).
    assert 0.8 <= ratio <= 1.2, (
        f"motor did not reach target_omega: target={target:.4f}, "
        f"measured={measured:.4f}, ratio={ratio:.4f}"
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 3: rim stays on the configured radius
# ────────────────────────────────────────────────────────────────────────────

def test_hello_motor_rim_stays_on_radius(demo):
    """Distance hub -> each rim is within ``RADIUS +/- 0.05`` across all frames."""
    world, info = demo.build_world()
    trace = demo.step_world(world, info, frames=240, dt=demo.DEFAULT_DT)

    radii_a = np.asarray(trace["radii_a"], dtype=np.float64)
    radii_b = np.asarray(trace["radii_b"], dtype=np.float64)
    target = float(demo.RADIUS)

    dev_a = float(np.max(np.abs(radii_a - target)))
    dev_b = float(np.max(np.abs(radii_b - target)))
    assert dev_a <= 0.05, (
        f"rim_a drifted off-radius: max dev={dev_a:.4f}, target={target:.4f}"
    )
    assert dev_b <= 0.05, (
        f"rim_b drifted off-radius: max dev={dev_b:.4f}, target={target:.4f}"
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 4: no NaN leakage from the solver
# ────────────────────────────────────────────────────────────────────────────

def test_hello_motor_no_nan(demo):
    """Every node position is finite after a full 240-frame integration."""
    world, info = demo.build_world()
    demo.step_world(world, info, frames=240, dt=demo.DEFAULT_DT)
    assert np.all(np.isfinite(world.positions))
    assert np.all(np.isfinite(world.velocities))


# ────────────────────────────────────────────────────────────────────────────
# Test 5: visual baseline (golden-master)
# ────────────────────────────────────────────────────────────────────────────

def test_hello_motor_visual_baseline(demo):
    """Render the wheel and diff against the committed baseline PNG.

    First run writes ``python/slappyengine/testing/baselines/hello_motor.png``
    and passes; subsequent runs require a max per-channel diff <= 0.05.
    """
    world, info = demo.build_world()
    trace = demo.step_world(world, info, frames=240, dt=demo.DEFAULT_DT)

    rendered = demo._render_frame(world, info, trace)
    assert rendered.dtype == np.uint8
    assert rendered.shape == (demo.RENDER_H, demo.RENDER_W, 4)

    scene = SimpleNamespace(_image_data=rendered)
    assert_scene_matches(
        scene,
        "hello_motor",
        tolerance=0.05,
        width=demo.RENDER_W,
        height=demo.RENDER_H,
    )
