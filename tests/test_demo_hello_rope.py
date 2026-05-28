"""Tests for the ``examples/hello_rope.py`` demo.

These tests pin three things:

1. The demo's ``main()`` is callable in-process and doesn't raise.
2. After 120 frames the rope has visibly drooped — guards the dynamics
   substrate against regressing back to a taut/straight rest state.
3. The visual rasterisation reproduces a stable golden master via the
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
_DEMO_PATH = _REPO_ROOT / "examples" / "hello_rope.py"


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

    First run writes ``python/slappyengine/testing/baselines/hello_rope.png``
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
