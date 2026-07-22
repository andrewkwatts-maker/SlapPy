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
   :mod:`pharos_engine.testing` harness.
8. (Y2) The demo runs 60 steps without emitting ``RuntimeWarning`` — the
   over-damp guard that W1 fixed for ``hello_ragdoll`` and X2 fixed for
   ``hello_rope``.
9. (Y2) ``iters * damping`` stays at or below 0.3 (throttle band cap).
10. (Y2) Every node in every scene stays inside the demo's view bounds.
11. (Y2) By frame 60 the CoM speed of the free-swinging nodes settles
    below 0.5 m/s.
12. (Y2) All distance joints hold rest-length within 5% after 60 frames.
13. (Y2) At least one joint stays live (``enabled``) — no joint
    disintegration under passive gravity.
14. (Y2) ``main(render=False)`` is warning-clean end-to-end.
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

from pharos_engine.testing import assert_scene_matches

# ── Load the demo as a module so we don't depend on examples/ being on path ──
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_joint.py"


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

    First run writes ``python/pharos_engine/testing/baselines/hello_joint.png``
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


# ────────────────────────────────────────────────────────────────────────────
# Helpers used by the Y2 regression tests below (mirror W1 / X2 template).
# ────────────────────────────────────────────────────────────────────────────

def _node_masses(world, node_idx):
    """Return per-node masses (0 for pinned nodes)."""
    inv = world.inv_masses[node_idx]
    return np.where(inv > 0, 1.0 / np.where(inv > 0, inv, 1.0), 0.0)


def _com_velocity_of(world, node_idx):
    """Mass-weighted CoM velocity of the given node indices."""
    m = _node_masses(world, node_idx)
    v = world.velocities[node_idx]
    total = float(m.sum())
    if total <= 0.0:
        return np.zeros(2, dtype=np.float64)
    return (m[:, None] * v).sum(axis=0) / total


def _all_scene_nodes(info):
    """Return every node index used by any of the four scenes."""
    return [
        info["scene_a"]["anchor"], info["scene_a"]["node"],
        info["scene_b"]["top"], info["scene_b"]["mid"], info["scene_b"]["bot"],
        info["scene_c"]["pivot"], info["scene_c"]["bob"],
        info["scene_d"]["anchor"], info["scene_d"]["ref"], info["scene_d"]["bob"],
    ]


def _free_scene_nodes(info, world):
    """Return the free (non-pinned) node indices — those with inv_mass > 0."""
    idx = _all_scene_nodes(info)
    inv = world.inv_masses[idx]
    return [i for i, im in zip(idx, inv) if float(im) > 0.0]


# ────────────────────────────────────────────────────────────────────────────
# Test 8 (Y2): no RuntimeWarning during a 60-step run
# ────────────────────────────────────────────────────────────────────────────

def test_hello_joint_60_steps_no_runtime_warning(demo):
    """Stepping the world 60 frames must not raise any ``RuntimeWarning``.

    The over-damp diagnostic in :mod:`pharos_engine.dynamics.world` is the
    usual culprit: keeps a lid on ``iters * damping``. Any future edit that
    silently drives the product above 0.3 will fail this test.
    """
    # The over-damp warning is throttled process-wide; clear the cache so
    # any regression is observable in this test regardless of test order.
    from pharos_engine.dynamics import world as _dyn_world
    _dyn_world._reset_warning_cache()

    world, info = demo.build_world()
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        demo.step_world(world, info, frames=60, dt=demo.DEFAULT_DT)


# ────────────────────────────────────────────────────────────────────────────
# Test 9 (Y2): iters * damping stays inside the throttle band
# ────────────────────────────────────────────────────────────────────────────

def test_hello_joint_damping_product_under_threshold(demo):
    """The tuning constants keep ``iters * damping`` at or below 0.3.

    That's the guidance the ``World._check_overdamping`` warning emits —
    below the effective-damping ``0.5`` threshold with plenty of headroom.
    """
    product = demo.SOLVER_ITERATIONS * demo.DAMPING
    assert product <= 0.3 + 1e-9, (
        f"iters * damping = {product:.3f} exceeds the recommended 0.3 cap"
    )
    # Sanity-check both sides so a future edit that swaps both to zero
    # doesn't silently pass.
    assert demo.SOLVER_ITERATIONS >= 1
    assert demo.DAMPING > 0.0
    # And every per-kind constant stays inside the same band.
    for name in ("RIGID_DAMPING", "BALL_DAMPING", "HINGE_DAMPING"):
        val = float(getattr(demo, name))
        assert demo.SOLVER_ITERATIONS * val <= 0.3 + 1e-9, (
            f"{name}={val} pushes iters * damping over 0.3"
        )


# ────────────────────────────────────────────────────────────────────────────
# Test 10 (Y2): every scene node stays inside the demo's view bounds
# ────────────────────────────────────────────────────────────────────────────

def test_hello_joint_bodies_stay_inside_world_bounds(long_run, demo):
    """After 240 frames every scene node sits inside ``[VIEW_MIN, VIEW_MAX]``.

    The view rectangle is what the renderer rasterises — if any node
    escapes it we'd start drawing outside the frame and the visual
    baseline would silently drift.
    """
    world, info, _trace = long_run
    idx = _all_scene_nodes(info)
    pos = world.positions[idx]
    xs, ys = pos[:, 0], pos[:, 1]
    vx0, vy0 = demo.VIEW_MIN
    vx1, vy1 = demo.VIEW_MAX
    assert float(xs.min()) >= vx0 - 1e-6, f"x_min {xs.min():.4f} < {vx0}"
    assert float(xs.max()) <= vx1 + 1e-6, f"x_max {xs.max():.4f} > {vx1}"
    assert float(ys.min()) >= vy0 - 1e-6, f"y_min {ys.min():.4f} < {vy0}"
    assert float(ys.max()) <= vy1 + 1e-6, f"y_max {ys.max():.4f} > {vy1}"


# ────────────────────────────────────────────────────────────────────────────
# Test 11 (Y2): CoM velocity of the settling scenes reaches rest by step 60
# ────────────────────────────────────────────────────────────────────────────

def test_hello_joint_com_velocity_settles_by_step_60(demo):
    """``|CoM v| < 0.5`` by frame 60 across scenes A, B and C.

    Scenes A (pendulum), B (rigid bar) and C (ball joint on pivot) all
    settle onto their static equilibrium under the tuned damping. Scene D
    is deliberately excluded — its hinge bob is designed to oscillate
    inside the ±pi/4 band and pinning it here would fight the demo's
    documented behaviour.
    """
    world, info = demo.build_world()
    demo.step_world(world, info, frames=60, dt=demo.DEFAULT_DT)
    settling_idx = [
        info["scene_a"]["node"],
        info["scene_b"]["mid"], info["scene_b"]["bot"],
        info["scene_c"]["bob"],
    ]
    v_com = _com_velocity_of(world, settling_idx)
    speed = float(np.linalg.norm(v_com))
    assert speed < 0.5, (
        f"CoM speed {speed:.4f} did not settle within 60 frames "
        f"(v_com={v_com})"
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 12 (Y2): distance joints hold rest-length within 5%
# ────────────────────────────────────────────────────────────────────────────

def test_hello_joint_distance_joints_hold_rest_length(demo):
    """After 60 frames every distance joint is within 5% of its rest length.

    Scenes A / B / D all rely on a distance-style projection (``distance``
    for A, ``weld`` for B, and ``hinge`` uses an internal distance segment
    plus an angular limit for D). This pins the XPBD projection at a coarse
    level without over-specifying convergence.
    """
    world, info = demo.build_world()
    demo.step_world(world, info, frames=60, dt=demo.DEFAULT_DT)
    tracked = 0
    for j in world.joints:
        if j.kind not in ("distance", "weld", "hinge"):
            continue
        pa = world.positions[j.node_a]
        pb = world.positions[j.node_b]
        length = float(np.linalg.norm(pb - pa))
        rest = float(j.rest_length)
        if rest <= 0.0:
            continue
        rel = abs(length - rest) / rest
        assert rel < 0.05, (
            f"joint {j.kind} {j.node_a}->{j.node_b} rest={rest:.4f} "
            f"actual={length:.4f} rel_err={rel:.4f}"
        )
        tracked += 1
    # Scenes A (1 dist) + B (2 welds) + D (1 hinge segment) = 4 joints.
    assert tracked >= 4, (
        f"expected at least 4 rest-length joints, tracked {tracked}"
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 13 (Y2): at least one joint stays live (no disintegration)
# ────────────────────────────────────────────────────────────────────────────

def test_hello_joint_at_least_one_joint_live(demo):
    """After a full 240-frame integration at least one joint stays live.

    :class:`JointSpec` expresses "broken" through the boolean ``enabled``
    flag (a joint that snaps its break-force is disabled). This test uses
    ``enabled`` as the live-vs-broken signal — a passive demo should
    never break any joint, and the four scenes contribute five joints in
    total so the count is a strong lower bound.
    """
    world, info = demo.build_world()
    demo.step_world(world, info, frames=240, dt=demo.DEFAULT_DT)
    live = [j for j in world.joints if getattr(j, "enabled", True)]
    assert live, "expected at least one joint to remain under tension"
    # Bonus: the passive demo shouldn't break any joint at all.
    assert len(live) == len(world.joints), (
        f"unexpected joint breakage: "
        f"{len(world.joints) - len(live)}/{len(world.joints)} broken"
    )
    # And the four scenes should contribute the expected joint mix.
    kinds = sorted(j.kind for j in world.joints)
    assert kinds == ["ball", "distance", "hinge", "weld", "weld"], (
        f"unexpected joint kinds: {kinds}"
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 14 (Y2): main(render=False) is warning-clean end-to-end
# ────────────────────────────────────────────────────────────────────────────

def test_hello_joint_main_no_warnings(demo, tmp_path):
    """The full CLI path (``main``) must run its 60-frame smoke without
    tripping any warning category — belt-and-braces coverage over the
    per-step check in :func:`test_hello_joint_60_steps_no_runtime_warning`.
    """
    from pharos_engine.dynamics import world as _dyn_world
    _dyn_world._reset_warning_cache()

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        summary = demo.main(
            frames=60, render=False, out=tmp_path / "ignored.png"
        )
    assert summary["frames"] == 60
    assert summary["iters_x_damping"] <= 0.3 + 1e-9
