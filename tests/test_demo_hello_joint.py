"""Tests for the ``examples/hello_joint.py`` demo.

These tests pin the behavioural contract of each of the four ``JointSpec``
kinds shown in the side-by-side demo:

1. ``main()`` is callable in-process and doesn't raise.
2. ``kind="distance"`` (Scene A) holds the rest length to within ``0.02``
   across the full trajectory -- the rigid-rod claim from the docstring.
3. ``kind="weld"`` (Scene B) keeps the two welded segment lengths within
   the same tight tolerance, so the 3-node bar behaves as a rigid body.
4. ``kind="ball"`` (Scene C) admits free rotation around the pivot -- the
   swinging bob reaches at least ``|angle| >= pi/4`` at some frame.
5. ``kind="hinge"`` (Scene D) clamps the joint angle into
   ``[-pi/4, +pi/4]`` (allowing a small tolerance for XPBD overshoot).
6. No NaNs leak out of the XPBD solver in any scene.
7. The visual rasterisation reproduces a stable golden master via the
   :mod:`slappyengine.testing` harness.
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from slappyengine.testing import assert_scene_matches

# ── Load the demo as a module so we don't depend on examples/ being on path ──
_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEMO_PATH = _REPO_ROOT / "examples" / "hello_joint.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("hello_joint_demo", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_joint_demo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


# ── Cache a full 240-frame run so the per-kind tests share work ─────────────

@pytest.fixture(scope="module")
def long_run(demo):
    world, info = demo.build_world()
    trace = demo.step_world(world, info, frames=240, dt=demo.DEFAULT_DT)
    return world, info, trace


# ────────────────────────────────────────────────────────────────────────────
# Test 1: demo runs cleanly
# ────────────────────────────────────────────────────────────────────────────

def test_hello_joint_runs_without_error(demo, tmp_path):
    """``main(frames=60, render=False)`` returns a summary and never raises."""
    summary = demo.main(frames=60, render=False, out=tmp_path / "ignored.png")
    assert summary["frames"] == 60
    for key in ("scene_a", "scene_b", "scene_c", "scene_d"):
        scene = summary[key]
        assert isinstance(scene, dict)
        # Each scene reports either a violation or an angle metric. Both
        # must be finite for a successful run.
        for metric_key in ("max_violation", "max_angle"):
            if metric_key in scene:
                assert np.isfinite(scene[metric_key])
    assert summary["nan_seen"] is False


# ────────────────────────────────────────────────────────────────────────────
# Test 2: distance joint holds its rest length
# ────────────────────────────────────────────────────────────────────────────

def test_distance_kind_holds_rest_length(long_run):
    """Scene A's per-frame |distance - rest_length| stays below 0.02."""
    _world, _info, trace = long_run
    violations = np.asarray(trace["a_violations"], dtype=np.float64)
    assert violations.size > 0
    max_violation = float(np.max(violations))
    assert max_violation < 0.02, (
        f"distance joint drifted off rest length: "
        f"max violation = {max_violation:.6f} (limit 0.02)"
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 3: weld joints keep the rigid bar's two bonds tight
# ────────────────────────────────────────────────────────────────────────────

def test_weld_kind_keeps_rigid_bar(long_run):
    """Both welds in Scene B stay within ``0.02`` of their segment length."""
    _world, _info, trace = long_run
    top_dev = np.asarray(trace["b_violations_top"], dtype=np.float64)
    bot_dev = np.asarray(trace["b_violations_bot"], dtype=np.float64)
    assert top_dev.size > 0 and bot_dev.size > 0
    max_top = float(np.max(top_dev))
    max_bot = float(np.max(bot_dev))
    assert max_top < 0.02, (
        f"weld A--B drifted: max deviation = {max_top:.6f} (limit 0.02)"
    )
    assert max_bot < 0.02, (
        f"weld B--C drifted: max deviation = {max_bot:.6f} (limit 0.02)"
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 4: ball joint admits free rotation around the pivot
# ────────────────────────────────────────────────────────────────────────────

def test_ball_kind_allows_free_swing(long_run):
    """Scene C's swinging bob reaches ``|angle| >= pi/4`` at some frame."""
    _world, _info, trace = long_run
    angles = np.asarray(trace["c_angles"], dtype=np.float64)
    assert angles.size > 0
    max_abs = float(np.max(np.abs(angles)))
    assert max_abs >= math.pi / 4.0, (
        f"ball joint did not allow free swing: "
        f"max |angle| = {max_abs:.6f} rad < pi/4 = {math.pi / 4.0:.6f}"
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 5: hinge joint clamps its angle to the declared limit
# ────────────────────────────────────────────────────────────────────────────

def test_hinge_kind_respects_limits(long_run, demo):
    """Scene D's joint angle stays inside ``[-pi/4 - 0.05, +pi/4 + 0.05]``."""
    _world, _info, trace = long_run
    angles = np.asarray(trace["d_angles"], dtype=np.float64)
    assert angles.size > 0
    lo = -math.pi / 4.0 - 0.05
    hi = +math.pi / 4.0 + 0.05
    min_a = float(np.min(angles))
    max_a = float(np.max(angles))
    assert lo <= min_a, (
        f"hinge angle escaped lower limit: min = {min_a:.6f}, allowed >= {lo:.6f}"
    )
    assert max_a <= hi, (
        f"hinge angle escaped upper limit: max = {max_a:.6f}, allowed <= {hi:.6f}"
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 6: no NaN leakage from the XPBD solver
# ────────────────────────────────────────────────────────────────────────────

def test_hello_joint_no_nan(long_run):
    """Every node position is finite after the full 240-frame integration."""
    world, _info, trace = long_run
    assert trace["nan_seen"] is False
    assert np.all(np.isfinite(world.positions))
    assert np.all(np.isfinite(world.velocities))


# ────────────────────────────────────────────────────────────────────────────
# Test 7: visual baseline (golden-master)
# ────────────────────────────────────────────────────────────────────────────

def test_hello_joint_visual_baseline(long_run, demo):
    """Render the four-scene panel and diff against the committed baseline.

    First run writes ``python/slappyengine/testing/baselines/hello_joint.png``
    and passes; subsequent runs require a max per-channel diff <= 0.05.
    """
    world, info, _trace = long_run

    rendered = demo._render_frame(world, info)
    assert rendered.dtype == np.uint8
    assert rendered.shape == (demo.RENDER_H, demo.RENDER_W, 4)

    scene = SimpleNamespace(_image_data=rendered)
    assert_scene_matches(
        scene,
        "hello_joint",
        tolerance=0.05,
        width=demo.RENDER_W,
        height=demo.RENDER_H,
    )
