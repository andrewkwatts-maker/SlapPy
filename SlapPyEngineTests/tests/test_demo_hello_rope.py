"""Tests for the ``examples/hello_rope.py`` demo.

These tests pin the demo behaviour end-to-end:

1. ``main()`` is callable in-process and doesn't raise.
2. After 120 frames the rope has visibly drooped — guards the dynamics
   substrate against regressing back to a taut/straight rest state.
3. The visual rasterisation reproduces a stable golden master via the
   :mod:`pharos_engine.testing` harness (golden on first run, diff on
   subsequent runs).
4. The demo runs 60 steps without emitting ``RuntimeWarning`` (over-damp
   guard — the X2 fix for the same pattern W1 fixed for ``hello_ragdoll``).
5. ``iters * damping`` stays at or under 0.3 (throttle band cap).
6. Rope endpoints remain inside the demo's view rectangle after 60 steps.
7. ``|CoM v|`` < 0.5 by frame 60 (rope has settled).
8. Every distance joint stays live (``enabled``) — no rope disintegration.
9. Distance joints hold rest-length within 5% after 60 frames.
10. ``main()`` runs its 60-frame smoke without tripping any warning.
"""
from __future__ import annotations

import importlib.util
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from pharos_engine.testing import assert_scene_matches

# ── Load the demo as a module so we don't depend on examples/ being on path ──
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_rope.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("hello_rope_demo", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_rope_demo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


# ────────────────────────────────────────────────────────────────────────────
# Shared helpers (mirror the W1 regression pattern in test_demo_hello_ragdoll).
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
# Test 1: demo runs cleanly
# ────────────────────────────────────────────────────────────────────────────

def test_hello_rope_runs_without_error(demo, tmp_path):
    """``main(frames=60, render=False)`` returns a summary and never raises."""
    summary = demo.main(frames=60, render=False, out=tmp_path / "ignored.png")
    assert summary["nodes"] == demo.NODE_COUNT
    assert summary["frames"] == 60
    assert np.isfinite(summary["midpoint_y"])
    assert np.isfinite(summary["droop"])


# ────────────────────────────────────────────────────────────────────────────
# Test 2: physical droop (catenary sanity)
# ────────────────────────────────────────────────────────────────────────────

def test_hello_rope_catenary_droop(demo):
    """After 120 steps the midpoint sits well below the anchor line."""
    world, body = demo.build_world()
    demo.step_world(world, frames=120, dt=demo.DEFAULT_DT)
    summary = demo.summarise(world, body, frames=120)

    droop = summary["droop"]
    # Spec: midpoint y is significantly lower than anchor y, droop > 30% of length.
    assert droop > 0.3 * demo.TOTAL_LENGTH, (
        f"rope did not droop enough: droop={droop:.4f}, "
        f"threshold={0.3 * demo.TOTAL_LENGTH:.4f}"
    )
    # And the droop should be bounded by the physically plausible range.
    assert droop <= summary["expected_hi"] + 1e-6
    # And we have not blown the simulation up.
    assert not np.isnan(world.positions).any()


# ────────────────────────────────────────────────────────────────────────────
# Test 3: visual baseline (golden-master)
# ────────────────────────────────────────────────────────────────────────────

def test_hello_rope_visual_baseline(demo):
    """Render the rope and diff against the committed baseline PNG.

    First run writes ``python/pharos_engine/testing/baselines/hello_rope.png``
    and passes; subsequent runs require a max per-channel diff <= 0.05.
    """
    world, body = demo.build_world()
    demo.step_world(world, frames=120, dt=demo.DEFAULT_DT)

    rendered = demo._render_frame(world)
    assert rendered.dtype == np.uint8
    assert rendered.shape == (demo.RENDER_H, demo.RENDER_W, 4)

    # ``assert_scene_matches`` extracts ``scene._image_data`` first, so wrap
    # the numpy array in a trivial holder. The renderer is deterministic at
    # this point so the harness diff will be exactly zero on a clean re-run.
    scene = SimpleNamespace(_image_data=rendered)
    assert_scene_matches(
        scene,
        "hello_rope",
        tolerance=0.05,
        width=demo.RENDER_W,
        height=demo.RENDER_H,
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 4 (X2): no RuntimeWarning during a 60-step run
# ────────────────────────────────────────────────────────────────────────────

def test_hello_rope_60_steps_no_runtime_warning(demo):
    """Stepping the world 60 frames must not raise any ``RuntimeWarning``.

    The over-damp diagnostic in :mod:`pharos_engine.dynamics.world` is the
    usual culprit: keeps a lid on ``iters * damping``. Any future edit that
    silently drives the product above 0.3 will fail this test.
    """
    world, _body = demo.build_world()
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        demo.step_world(world, frames=60, dt=demo.DEFAULT_DT)


# ────────────────────────────────────────────────────────────────────────────
# Test 5 (X2): iters * damping stays inside the throttle band
# ────────────────────────────────────────────────────────────────────────────

def test_hello_rope_damping_product_under_threshold(demo):
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


# ────────────────────────────────────────────────────────────────────────────
# Test 6 (X2): rope endpoints stay inside the demo's view bounds
# ────────────────────────────────────────────────────────────────────────────

def test_hello_rope_endpoints_stay_in_bounds(demo):
    """After 60 frames every rope node sits inside ``[VIEW_MIN, VIEW_MAX]``.

    The demo's view rectangle is the effective world/render bound; if the
    rope droops through it we'd start rasterising nodes outside the frame
    and the visual test would silently drift.
    """
    world, body = demo.build_world()
    demo.step_world(world, frames=60, dt=demo.DEFAULT_DT)
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
# Test 7 (X2): CoM velocity settles by step 60
# ────────────────────────────────────────────────────────────────────────────

def test_hello_rope_com_velocity_settles_by_step_60(demo):
    """``|CoM v| < 0.5`` by frame 60.

    Both anchors are pinned, so the rope's only degree of freedom is the
    droop of the interior nodes falling under gravity. With the tuned
    damping the interior CoM should be nearly stationary by frame 60.
    """
    world, body = demo.build_world()
    demo.step_world(world, frames=60, dt=demo.DEFAULT_DT)
    v_com = _com_velocity(world, body)
    speed = float(np.linalg.norm(v_com))
    assert speed < 0.5, (
        f"CoM speed {speed:.4f} did not settle within 60 frames "
        f"(v_com={v_com})"
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 8 (X2): at least one joint stays live (no rope disintegration)
# ────────────────────────────────────────────────────────────────────────────

def test_hello_rope_at_least_one_joint_live(demo):
    """After a full 120-frame integration at least one joint stays live.

    The current :class:`JointSpec` API has no ``state`` field; the
    "broken" concept is expressed via the boolean ``enabled`` flag (a
    joint that snaps its break-force is disabled). This test uses
    ``enabled`` as the live-vs-broken signal — a passive drop should
    never break any joint, and a 24-node rope has 23 distance joints so
    the count is a strong lower bound.
    """
    world, _body = demo.build_world()
    demo.step_world(world, frames=120, dt=demo.DEFAULT_DT)
    live = [j for j in world.joints if getattr(j, "enabled", True)]
    assert live, "expected at least one joint to remain under tension"
    # Bonus: the passive drop shouldn't break any joint at all.
    assert len(live) == len(world.joints), (
        f"unexpected joint breakage: "
        f"{len(world.joints) - len(live)}/{len(world.joints)} broken"
    )
    # And the rope's expected segment joints are all present.
    distance_joints = [j for j in world.joints if j.kind == "distance"]
    assert len(distance_joints) == demo.NODE_COUNT - 1, (
        f"expected {demo.NODE_COUNT - 1} distance joints, "
        f"got {len(distance_joints)}"
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 9 (X2): distance joints hold rest-length within 5%
# ────────────────────────────────────────────────────────────────────────────

def test_hello_rope_distance_joints_hold_rest_length(demo):
    """After 60 frames every distance joint is within 5% of its rest length.

    A visibly stretched rope would show up as one or more distance joints
    at 110%+ of rest — this pins the XPBD projection at a coarse level
    without over-specifying convergence.
    """
    world, _body = demo.build_world()
    demo.step_world(world, frames=60, dt=demo.DEFAULT_DT)
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


# ────────────────────────────────────────────────────────────────────────────
# Test 10 (X2): main(render=False) is warning-clean end-to-end
# ────────────────────────────────────────────────────────────────────────────

def test_hello_rope_main_no_warnings(demo, tmp_path):
    """The full CLI path (``main``) must run its 60-frame smoke without
    tripping any warning category — belt-and-braces coverage over the
    per-step check in :func:`test_hello_rope_60_steps_no_runtime_warning`.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        summary = demo.main(
            frames=60, render=False, out=tmp_path / "ignored.png"
        )
    assert summary["frames"] == 60
    assert summary["iters_x_damping"] <= 0.3 + 1e-9


# ────────────────────────────────────────────────────────────────────────────
# Test 11 (X2): rope settles into a symmetric catenary (equal-height anchors)
# ────────────────────────────────────────────────────────────────────────────

def test_hello_rope_settles_symmetric(demo):
    """After 120 frames the catenary is left-right symmetric about x=0.

    Both anchors are at the same height and mirrored across the y-axis, so
    the equilibrium catenary should have its axis of symmetry at x=0. We
    check the mean x-coordinate of the interior nodes (dropping the pinned
    endpoints), which must be near zero even at low convergence.
    """
    world, body = demo.build_world()
    demo.step_world(world, frames=120, dt=demo.DEFAULT_DT)
    idx = list(body.node_indices)
    # Drop the pinned endpoints so their asymmetric anchor positions don't
    # skew the mean.
    interior = idx[1:-1]
    xs = world.positions[interior, 0]
    mean_x = float(xs.mean())
    assert abs(mean_x) < 0.2, (
        f"interior mean x={mean_x:.4f} — expected near 0 by symmetry"
    )
