"""Tests for the ``examples/hello_spring.py`` demo.

These tests pin five physical guarantees plus a visual baseline:

1. The demo's ``main()`` is callable in-process and never raises.
2. The mass oscillates: there are at least four full cycles inside the
   4 s sample window (theoretical ~6.36).
3. The measured period from zero-crossings is within 15 % of the
   analytical ``T = 2 * pi * sqrt(m / k)``.
4. Damping bleeds amplitude — the peak amplitude in the last 60 frames
   is strictly smaller than in the first 60 frames.
5. No positions go NaN or inf during the simulation.
6. The rasterised final frame matches the committed golden master.
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from pharos_engine.testing import assert_scene_matches

# -- Load the demo as a module so we don't depend on examples/ being on path --
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "PharosEngineExamples" / "examples" / "hello_spring.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("hello_spring_demo", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_spring_demo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


# ----------------------------------------------------------------------------
# Test 1: demo runs cleanly
# ----------------------------------------------------------------------------

def test_hello_spring_runs_without_error(demo, tmp_path):
    """``main(frames=60, render=False)`` returns a summary without raising."""
    summary = demo.main(frames=60, render=False, out=tmp_path / "ignored.png")
    assert summary["frames"] == 60
    assert summary["theoretical_period"] == pytest.approx(
        2.0 * math.pi * math.sqrt(demo.MASS / demo.STIFFNESS)
    )
    assert np.isfinite(summary["final_y"])
    assert np.isfinite(summary["peak_amplitude_early"])


# ----------------------------------------------------------------------------
# Test 2: oscillates at least ~4 cycles inside the 4 s window
# ----------------------------------------------------------------------------

def test_hello_spring_oscillates(demo):
    world, _, mass_idx = demo.build_world()
    history = demo.step_world(
        world, mass_idx, frames=demo.DEFAULT_FRAMES, dt=demo.DEFAULT_DT,
    )
    summary = demo.analyse(history, demo.DEFAULT_DT)
    # Two zero crossings per period; theoretical ~6.36 cycles in 4 s.
    assert summary["cycles"] >= 4.0, (
        f"expected >=4 oscillation cycles in {summary['duration']:.2f} s, "
        f"got {summary['cycles']:.2f} (zero crossings={summary['zero_crossings']})"
    )


# ----------------------------------------------------------------------------
# Test 3: measured period within 15 % of theory
# ----------------------------------------------------------------------------

def test_hello_spring_period_matches_theory(demo):
    world, _, mass_idx = demo.build_world()
    history = demo.step_world(
        world, mass_idx, frames=demo.DEFAULT_FRAMES, dt=demo.DEFAULT_DT,
    )
    summary = demo.analyse(history, demo.DEFAULT_DT)
    theoretical = 2.0 * math.pi * math.sqrt(demo.MASS / demo.STIFFNESS)
    assert summary["theoretical_period"] == pytest.approx(theoretical)
    rel_err = abs(summary["measured_period"] - theoretical) / theoretical
    assert rel_err <= 0.15, (
        f"measured period {summary['measured_period']:.4f}s is "
        f"{rel_err * 100.0:.2f}% off theory {theoretical:.4f}s (tolerance: 15%)"
    )


# ----------------------------------------------------------------------------
# Test 4: damping shrinks amplitude over time
# ----------------------------------------------------------------------------

def test_hello_spring_damping_reduces_amplitude(demo):
    world, _, mass_idx = demo.build_world()
    history = demo.step_world(
        world, mass_idx, frames=demo.DEFAULT_FRAMES, dt=demo.DEFAULT_DT,
    )
    centered = history - demo.MASS_POS_REST[1]
    win = 60
    peak_first = float(np.max(np.abs(centered[:win])))
    peak_last = float(np.max(np.abs(centered[-win:])))
    assert peak_last < peak_first, (
        f"damping did not reduce amplitude: "
        f"first-window peak={peak_first:.4f}, last-window peak={peak_last:.4f}"
    )


# ----------------------------------------------------------------------------
# Test 5: positions stay finite
# ----------------------------------------------------------------------------

def test_hello_spring_no_nan(demo):
    world, _, mass_idx = demo.build_world()
    history = demo.step_world(
        world, mass_idx, frames=demo.DEFAULT_FRAMES, dt=demo.DEFAULT_DT,
    )
    assert np.all(np.isfinite(history)), "mass y-history contains NaN/inf"
    assert np.all(np.isfinite(world.positions)), (
        "world.positions contains NaN/inf at end of simulation"
    )


# ----------------------------------------------------------------------------
# Test 6: visual baseline (golden-master)
# ----------------------------------------------------------------------------

def test_hello_spring_visual_baseline(demo):
    """Render the spring scene and diff against the committed baseline PNG.

    First run writes ``python/pharos_engine/testing/baselines/hello_spring.png``
    and passes; subsequent runs require ``max_pixel_diff <= 0.05``.
    """
    world, anchor_idx, mass_idx = demo.build_world()
    demo.step_world(
        world, mass_idx, frames=demo.DEFAULT_FRAMES, dt=demo.DEFAULT_DT,
    )

    rendered = demo._render_frame(world, anchor_idx, mass_idx)
    assert rendered.dtype == np.uint8
    assert rendered.shape == (demo.RENDER_H, demo.RENDER_W, 4)

    scene = SimpleNamespace(_image_data=rendered)
    assert_scene_matches(
        scene,
        "hello_spring",
        tolerance=0.05,
        width=demo.RENDER_W,
        height=demo.RENDER_H,
    )
