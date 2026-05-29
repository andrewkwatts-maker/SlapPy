"""Tests for the ``examples/hello_ragdoll.py`` demo.

These tests pin five things:

1. The demo's ``main()`` is callable in-process and doesn't raise.
2. After 180 frames the lowest bone sits at or near the ground plane.
3. Every hinge joint angle stays inside its declared band across the
   full 180-frame trajectory — guards the angular-limit projection from
   silently regressing.
4. No NaNs leak out of the XPBD solver.
5. The visual rasterisation reproduces a stable golden master via the
   :mod:`slappyengine.testing` harness (golden on first run, diff on
   subsequent runs).
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
_DEMO_PATH = _REPO_ROOT / "examples" / "hello_ragdoll.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("hello_ragdoll_demo", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_ragdoll_demo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


# ────────────────────────────────────────────────────────────────────────────
# Test 1: demo runs cleanly
# ────────────────────────────────────────────────────────────────────────────

def test_hello_ragdoll_runs_without_error(demo, tmp_path):
    """``main(frames=60, render=False)`` returns a summary and never raises."""
    summary = demo.main(frames=60, render=False, out=tmp_path / "ignored.png")
    assert summary["bones"] == 6
    assert summary["joints"] >= 6  # one distance per bone + hinges
    assert summary["frames"] == 60
    assert np.isfinite(summary["lowest_bone_y"])
    assert isinstance(summary["limits_respected"], bool)


# ────────────────────────────────────────────────────────────────────────────
# Test 2: ground landing
# ────────────────────────────────────────────────────────────────────────────

def test_hello_ragdoll_lands_on_ground(demo):
    """After 180 frames the lowest bone is at or just above ``y = 0``."""
    world, body, spec = demo.build_world()
    trace = demo.step_world(world, frames=180, dt=demo.DEFAULT_DT)
    summary = demo.summarise(world, body, spec, trace, 180)
    # The ground clamp pins anything that crosses y=0 to exactly the plane,
    # so the lowest tip of the skeleton should be ≤ 0.1 after 3 seconds.
    assert summary["lowest_bone_y"] <= 0.1, (
        f"ragdoll did not land: lowest_bone_y={summary['lowest_bone_y']:.4f}"
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 3: angular limits respected across the trajectory
# ────────────────────────────────────────────────────────────────────────────

def test_hello_ragdoll_joint_limits_respected(demo):
    """Every hinge stays inside its ``[min_angle, max_angle]`` band for 180 frames."""
    world, body, spec = demo.build_world()
    trace = demo.step_world(world, frames=180, dt=demo.DEFAULT_DT, audit_limits=True)
    assert trace["limits_respected"] is True
    # And, independently, re-measure at the final frame.
    for j in demo._hinge_joints(world):
        ang = demo._joint_angle(world, j)
        lo = float(j.params.get("min_angle", -math.pi))
        hi = float(j.params.get("max_angle", math.pi))
        assert lo - 1e-3 <= ang <= hi + 1e-3, (
            f"joint angle {ang:.4f} outside [{lo:.4f}, {hi:.4f}]"
        )


# ────────────────────────────────────────────────────────────────────────────
# Test 4: no NaN leakage from the solver
# ────────────────────────────────────────────────────────────────────────────

def test_hello_ragdoll_no_nan_in_step(demo):
    """Every node position is finite after a full 180-frame integration."""
    world, body, spec = demo.build_world()
    demo.step_world(world, frames=180, dt=demo.DEFAULT_DT)
    assert np.all(np.isfinite(world.positions))
    assert np.all(np.isfinite(world.velocities))


# ────────────────────────────────────────────────────────────────────────────
# Test 5: visual baseline (golden-master)
# ────────────────────────────────────────────────────────────────────────────

def test_hello_ragdoll_visual_baseline(demo):
    """Render the skeleton and diff against the committed baseline PNG.

    First run writes ``python/slappyengine/testing/baselines/hello_ragdoll.png``
    and passes; subsequent runs require a max per-channel diff <= 0.05.
    """
    world, body, spec = demo.build_world()
    demo.step_world(world, frames=180, dt=demo.DEFAULT_DT)

    rendered = demo._render_frame(world, body)
    assert rendered.dtype == np.uint8
    assert rendered.shape == (demo.RENDER_H, demo.RENDER_W, 4)

    scene = SimpleNamespace(_image_data=rendered)
    assert_scene_matches(
        scene,
        "hello_ragdoll",
        tolerance=0.05,
        width=demo.RENDER_W,
        height=demo.RENDER_H,
    )
