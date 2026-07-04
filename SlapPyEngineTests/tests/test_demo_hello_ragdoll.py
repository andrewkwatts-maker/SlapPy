"""Tests for the ``examples/hello_ragdoll.py`` demo.

These tests pin the demo behaviour end-to-end:

1. ``main()`` is callable in-process and doesn't raise.
2. After 180 frames the lowest bone sits at or near the ground plane.
3. Every hinge joint angle stays inside its declared band across the
   full 180-frame trajectory — guards the angular-limit projection from
   silently regressing.
4. No NaNs leak out of the XPBD solver.
5. The visual rasterisation reproduces a stable golden master.
6. The demo runs 60 steps without emitting ``RuntimeWarning`` (over-damp).
7. All body centres finish within the world view bounds.
8. At least one joint stays live (``enabled``) — the ragdoll never tears
   itself apart under passive gravity.
9. The CoM y-velocity settles ``< 0.5`` in absolute value by step 60.
10. ``iters * damping`` stays at or under 0.3 (the throttle band).
"""
from __future__ import annotations

import importlib.util
import math
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from slappyengine.testing import assert_scene_matches

# ── Load the demo as a module so we don't depend on examples/ being on path ──
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_ragdoll.py"


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


# ────────────────────────────────────────────────────────────────────────────
# Helpers used by the W1 regression tests below.
# ────────────────────────────────────────────────────────────────────────────

def _node_masses(world, node_idx):
    """Return per-node masses (0 for pinned nodes)."""
    inv = world.inv_masses[node_idx]
    return np.where(inv > 0, 1.0 / np.where(inv > 0, inv, 1.0), 0.0)


def _com_velocity(world, body):
    """Mass-weighted CoM velocity of every node in ``body``."""
    idx = list(body.node_indices)
    m = _node_masses(world, idx)
    v = world.velocities[idx]
    total = float(m.sum())
    if total <= 0.0:
        return np.zeros(2, dtype=np.float64)
    return (m[:, None] * v).sum(axis=0) / total


# ────────────────────────────────────────────────────────────────────────────
# Test 6 (W1): no RuntimeWarning during a 60-step run
# ────────────────────────────────────────────────────────────────────────────

def test_hello_ragdoll_60_steps_no_runtime_warning(demo):
    """Stepping the world 60 frames must not raise any ``RuntimeWarning``.

    The over-damp diagnostic in :mod:`slappyengine.dynamics.world` is the
    usual culprit: keeps a lid on ``iters * damping``. Any future edit that
    silently drives the product above 0.3 will fail this test.
    """
    world, body, spec = demo.build_world()
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        demo.step_world(world, frames=60, dt=demo.DEFAULT_DT, body=body)


# ────────────────────────────────────────────────────────────────────────────
# Test 7 (W1): every body centre finishes inside the demo's view bounds
# ────────────────────────────────────────────────────────────────────────────

def test_hello_ragdoll_bodies_stay_inside_world_bounds(demo):
    """After 60 frames every ragdoll node sits inside ``[VIEW_MIN, VIEW_MAX]``.

    The demo's view rectangle is the effective world/render bound; if the
    ragdoll pushes through it we'd start rasterising the skeleton outside
    the frame and the visual test would silently drift.
    """
    world, body, spec = demo.build_world()
    demo.step_world(world, frames=60, dt=demo.DEFAULT_DT, body=body)
    idx = list(body.node_indices)
    pos = world.positions[idx]
    xs, ys = pos[:, 0], pos[:, 1]
    vx0, vy0 = demo.VIEW_MIN
    vx1, vy1 = demo.VIEW_MAX
    assert float(xs.min()) >= vx0 - 1e-6, f"x_min {xs.min():.4f} < {vx0}"
    assert float(xs.max()) <= vx1 + 1e-6, f"x_max {xs.max():.4f} > {vx1}"
    assert float(ys.min()) >= vy0 - 1e-6, f"y_min {ys.min():.4f} < {vy0}"
    assert float(ys.max()) <= vy1 + 1e-6, f"y_max {ys.max():.4f} > {vy1}"


# ────────────────────────────────────────────────────────────────────────────
# Test 8 (W1): at least one joint stays live (no ragdoll disintegration)
# ────────────────────────────────────────────────────────────────────────────

def test_hello_ragdoll_at_least_one_joint_live(demo):
    """After a full 180-frame integration at least one joint stays live.

    The current :class:`JointSpec` API has no ``state`` field; the
    "broken" concept is expressed via the boolean ``enabled`` flag (a
    joint that snaps its break-force is disabled). This test uses
    ``enabled`` as the live-vs-broken signal — a passive drop should
    never break any joint.
    """
    world, body, spec = demo.build_world()
    demo.step_world(world, frames=180, dt=demo.DEFAULT_DT, body=body)
    live = [j for j in world.joints if getattr(j, "enabled", True)]
    assert live, "expected at least one joint to remain under tension"
    # Bonus: the passive drop shouldn't break any joint at all.
    assert len(live) == len(world.joints), (
        f"unexpected joint breakage: "
        f"{len(world.joints) - len(live)}/{len(world.joints)} broken"
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 9 (W1): CoM y-velocity settles by step 60
# ────────────────────────────────────────────────────────────────────────────

def test_hello_ragdoll_com_yvel_settles_by_step_60(demo):
    """``|CoM v_y| < 0.5`` by frame 60.

    The ragdoll is dropped from y=2.0 with g=-9.81: it hits the ground
    around frame 35, then the ground clamp + XPBD damping bleed the
    remaining vertical energy. By frame 60 the CoM y-velocity should be
    well under 0.5 m/s.
    """
    world, body, spec = demo.build_world()
    demo.step_world(world, frames=60, dt=demo.DEFAULT_DT, body=body)
    v_com = _com_velocity(world, body)
    assert abs(float(v_com[1])) < 0.5, (
        f"CoM y-velocity {v_com[1]:.4f} did not settle within 60 frames"
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 10 (W1): iters * damping stays inside the throttle band
# ────────────────────────────────────────────────────────────────────────────

def test_hello_ragdoll_damping_product_under_threshold(demo):
    """The tuning constants keep ``iters * damping`` at or below 0.3.

    That's the guidance the ``World._check_overdamping`` warning emits —
    below the effective-damping ``0.5`` threshold with plenty of headroom.
    """
    product = demo.SOLVER_ITERATIONS * demo.RAGDOLL_DAMPING
    assert product <= 0.3 + 1e-9, (
        f"iters * damping = {product:.3f} exceeds the recommended 0.3 cap"
    )
    # Sanity-check both sides so a future edit that swaps both to zero
    # doesn't silently pass.
    assert demo.SOLVER_ITERATIONS >= 1
    assert demo.RAGDOLL_DAMPING > 0.0


# ────────────────────────────────────────────────────────────────────────────
# Test 11 (W1): ragdoll comes to rest laterally
# ────────────────────────────────────────────────────────────────────────────

def test_hello_ragdoll_com_xvel_small_by_step_60(demo):
    """The demo drops straight down: the CoM x-velocity stays tiny.

    The spec has left/right leg tilts of ±0.3 in the x direction which
    imparts a small lateral asymmetry once the legs slap the ground,
    but the mirror pair of arms and legs should keep any lateral drift
    bounded well below the fall speed.
    """
    world, body, spec = demo.build_world()
    demo.step_world(world, frames=60, dt=demo.DEFAULT_DT, body=body)
    v_com = _com_velocity(world, body)
    assert abs(float(v_com[0])) < 0.5, (
        f"CoM x-velocity {v_com[0]:.4f} unexpectedly large"
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 12 (W1): main(render=False) is warning-clean end-to-end
# ────────────────────────────────────────────────────────────────────────────

def test_hello_ragdoll_main_no_warnings(demo, tmp_path):
    """The full CLI path (``main``) must run its 60-frame smoke without
    tripping any warning category — belt-and-braces coverage over the
    per-step check in :func:`test_hello_ragdoll_60_steps_no_runtime_warning`.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        summary = demo.main(
            frames=60, render=False, out=tmp_path / "ignored.png"
        )
    assert summary["frames"] == 60
    assert summary["iters_x_damping"] <= 0.3 + 1e-9


# ────────────────────────────────────────────────────────────────────────────
# Test 13 (W1): distance joints hold rest-length within a small tolerance
# ────────────────────────────────────────────────────────────────────────────

def test_hello_ragdoll_distance_joints_hold_rest_length(demo):
    """After 60 frames every distance joint is within 5% of its rest length.

    A visibly broken ragdoll would show up as one or more distance joints
    stretched or compressed heavily — this pins the XPBD projection at a
    coarse level without over-specifying convergence.
    """
    world, body, spec = demo.build_world()
    demo.step_world(world, frames=60, dt=demo.DEFAULT_DT, body=body)
    for j in world.joints:
        if j.kind != "distance":
            continue
        pa = world.positions[j.node_a]
        pb = world.positions[j.node_b]
        length = float(np.linalg.norm(pb - pa))
        rest = float(j.rest_length)
        rel = abs(length - rest) / max(rest, 1e-9)
        assert rel < 0.05, (
            f"distance joint {j.node_a}->{j.node_b} rest={rest:.4f} "
            f"actual={length:.4f} rel_err={rel:.4f}"
        )
