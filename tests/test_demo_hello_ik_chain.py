"""Tests for the ``examples/hello_ik_chain.py`` demo.

These tests pin five things:

1. The demo's ``main()`` is callable in-process at a short frame count and
   never raises.
2. For a target that stays inside the chain's reach (true for the orbiting
   target in this demo) the CCD solver converges on at least 80% of frames.
3. Stepping the demo for 240 frames produces only finite node positions
   (no NaNs sneak in via division by zero in the CCD math).
4. For frames where ``solve_ik`` reported convergence the tip is genuinely
   within tolerance of the target (<= 0.05).
5. The rasteriser reproduces a stable golden-master via the
   :mod:`slappyengine.testing` harness (writes baseline on first run).
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
_DEMO_PATH = _REPO_ROOT / "examples" / "hello_ik_chain.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("hello_ik_chain_demo", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_ik_chain_demo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


# ────────────────────────────────────────────────────────────────────────────
# Test 1: demo runs cleanly at a short frame count
# ────────────────────────────────────────────────────────────────────────────

def test_hello_ik_chain_runs_without_error(demo, tmp_path):
    """``main(frames=60, render=False)`` returns a summary and never raises."""
    summary = demo.main(frames=60, render=False, out=tmp_path / "ignored.png")
    assert summary["frames"] == 60
    assert "frames_converged" in summary
    assert "convergence_rate" in summary
    assert np.isfinite(summary["max_tip_to_target"])
    # Records are emitted one per frame.
    assert len(summary["records"]) == 60


# ────────────────────────────────────────────────────────────────────────────
# Test 2: convergence on reachable targets
# ────────────────────────────────────────────────────────────────────────────

def test_hello_ik_chain_converges_for_reachable_target(demo):
    """When the target stays inside the chain's reach CCD converges most frames.

    The orbiting target has ``|target|`` peaking around ``sqrt((2+1.5)^2 +
    (1+1.5)^2) ~ 4.3`` and dipping down to ``~1``; the chain reach is
    ``5.0`` units, so every frame's target is reachable. We require
    ``solve_ik`` to return True for at least 80% of frames.
    """
    world, spec = demo.build_world()
    records = demo.run_frames(world, spec, demo.DEFAULT_FRAMES)

    converged = sum(1 for r in records if r[5])
    total = len(records)
    rate = converged / total
    assert rate >= 0.80, (
        f"solve_ik converged on only {converged}/{total} frames "
        f"(rate={rate:.3f}, expected >= 0.80)"
    )

    # Sanity-check: every target is in fact reachable.
    base = np.asarray(demo.BASE_POSITION, dtype=np.float64)
    reach = demo.LINK_LENGTH * (demo.NODE_COUNT - 1)
    for frame, tx, ty, _tipx, _tipy, _ok in records:
        dist = math.hypot(tx - base[0], ty - base[1])
        assert dist <= reach + 1e-9, (
            f"frame {frame}: target ({tx:.3f}, {ty:.3f}) outside reach {reach}"
        )


# ────────────────────────────────────────────────────────────────────────────
# Test 3: no NaNs in node positions
# ────────────────────────────────────────────────────────────────────────────

def test_hello_ik_chain_no_nan_in_step(demo):
    """After 240 frames every node position remains finite."""
    world, spec = demo.build_world()
    demo.run_frames(world, spec, 240)
    positions = world.positions
    assert np.isfinite(positions).all(), (
        f"non-finite positions after 240 frames: {positions}"
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 4: converged frames really do hit the target
# ────────────────────────────────────────────────────────────────────────────

def test_hello_ik_chain_end_effector_tracks_target(demo):
    """Every frame ``solve_ik`` reports converged must have tip ~= target."""
    world, spec = demo.build_world()
    records = demo.run_frames(world, spec, demo.DEFAULT_FRAMES)

    converged = [r for r in records if r[5]]
    assert converged, "no converged frames — IK regressed"
    max_dist = 0.0
    for frame, tx, ty, tipx, tipy, _ok in converged:
        dist = math.hypot(tipx - tx, tipy - ty)
        max_dist = max(max_dist, dist)
    assert max_dist <= 0.05, (
        f"converged frames had tip drift {max_dist:.4f} > 0.05"
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 5: visual baseline (golden-master)
# ────────────────────────────────────────────────────────────────────────────

def test_hello_ik_chain_visual_baseline(demo):
    """Render the chain and diff against the committed baseline PNG.

    First run writes ``python/slappyengine/testing/baselines/hello_ik_chain.png``
    and passes; subsequent runs require a max per-channel diff <= 0.05.
    """
    world, spec = demo.build_world()
    demo.run_frames(world, spec, demo.DEFAULT_FRAMES)

    rendered = demo._render_frame(world, spec)
    assert rendered.dtype == np.uint8
    assert rendered.shape == (demo.RENDER_H, demo.RENDER_W, 4)

    scene = SimpleNamespace(_image_data=rendered)
    assert_scene_matches(
        scene,
        "hello_ik_chain",
        tolerance=0.05,
        width=demo.RENDER_W,
        height=demo.RENDER_H,
    )
