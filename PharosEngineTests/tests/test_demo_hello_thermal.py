"""Tests for the ``examples/hello_thermal.py`` demo.

Pins six behaviours of the thermal diffusion demo:

1. ``main()`` runs cleanly in-process (60-frame quick path).
2. The hot spots in ``grid_a`` cool over the 240-frame integration.
3. The cold spot in ``grid_b`` warms toward ambient over 240 frames.
4. A standalone :class:`HeatField` with ``boundary='clamp'`` conserves
   total energy to within float tolerance (no cross-grid exchange).
5. No NaNs leak from either grid.
6. The rasterised side-by-side view reproduces the committed visual
   baseline via :func:`pharos_engine.testing.assert_scene_matches`.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from pharos_engine.testing import assert_scene_matches
from pharos_engine.thermal import HeatField

# ── Load the demo as a module so we don't depend on examples/ being on path ──
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "PharosEngineExamples" / "examples" / "hello_thermal.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("hello_thermal_demo", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_thermal_demo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


# ────────────────────────────────────────────────────────────────────────────
# Test 1: demo runs cleanly
# ────────────────────────────────────────────────────────────────────────────

def test_hello_thermal_runs_without_error(demo, tmp_path):
    """``main(frames=60, render=False)`` returns a summary and never raises."""
    summary = demo.main(frames=60, render=False, out=tmp_path / "ignored.png")
    assert summary["frames"] == 60
    assert np.isfinite(summary["grid_a_total_energy"])
    assert np.isfinite(summary["grid_b_total_energy"])
    assert np.isfinite(summary["initial_total_energy"])
    assert np.isfinite(summary["final_total_energy"])
    assert summary["nan_seen"] is False


# ────────────────────────────────────────────────────────────────────────────
# Test 2: grid_a hot spots cool over time
# ────────────────────────────────────────────────────────────────────────────

def test_hello_thermal_hot_spots_cool_over_time(demo):
    """max(grid_a) at frame 240 must be strictly less than max(grid_a) at frame 0.

    Initial peak is :data:`HOT_T` = 400.0; diffusion with clamp boundary
    spreads that heat over neighbours so the peak monotonically drops.
    """
    grid_a, grid_b = demo.build_grids()
    initial_max_a = float(grid_a.temperature.max())
    assert initial_max_a == pytest.approx(demo.HOT_T)

    trace = demo.step_grids(grid_a, grid_b, frames=240, dt=demo.DEFAULT_DT)
    final_max_a = float(grid_a.temperature.max())

    assert final_max_a < initial_max_a, (
        f"grid_a hot spots did not cool: initial max={initial_max_a:.4f}, "
        f"final max={final_max_a:.4f}"
    )
    # History recorded by step_grids agrees with the live grid.
    assert trace["max_a_history"][0] == pytest.approx(initial_max_a)
    assert trace["max_a_history"][-1] == pytest.approx(final_max_a)


# ────────────────────────────────────────────────────────────────────────────
# Test 3: grid_b cold spot warms over time
# ────────────────────────────────────────────────────────────────────────────

def test_hello_thermal_cold_spot_warms_over_time(demo):
    """min(grid_b) at frame 240 must be strictly greater than min(grid_b) at frame 0.

    Initial trough is :data:`COLD_T` = -100.0; diffusion against the
    ambient 20.0 plateau pulls that trough upward.
    """
    grid_a, grid_b = demo.build_grids()
    initial_min_b = float(grid_b.temperature.min())
    assert initial_min_b == pytest.approx(demo.COLD_T)

    trace = demo.step_grids(grid_a, grid_b, frames=240, dt=demo.DEFAULT_DT)
    final_min_b = float(grid_b.temperature.min())

    assert final_min_b > initial_min_b, (
        f"grid_b cold spot did not warm: initial min={initial_min_b:.4f}, "
        f"final min={final_min_b:.4f}"
    )
    assert trace["min_b_history"][0] == pytest.approx(initial_min_b)
    assert trace["min_b_history"][-1] == pytest.approx(final_min_b)


# ────────────────────────────────────────────────────────────────────────────
# Test 4: single-grid conservation under clamp boundary
# ────────────────────────────────────────────────────────────────────────────

def test_hello_thermal_conservation_per_grid():
    """A solo HeatField with boundary='clamp' must hold Σ T constant.

    This test deliberately does *not* call ``exchange_with`` — it isolates
    the per-grid step path so any conservation regression in the explicit
    edge-flux loop is caught without the cross-grid contact strip
    confusing the bookkeeping.
    """
    T = np.full((32, 32), 20.0, dtype=np.float64)
    T[8, 16] = 400.0
    T[24, 16] = 400.0
    T[16, 16] = -100.0  # mix in a cold spot for asymmetric flux
    field = HeatField(T, conductivity=1.0, diffusivity=0.1)

    initial_total = field.total_heat()
    for _ in range(240):
        field.step(1.0 / 60.0, boundary="clamp")
    final_total = field.total_heat()

    residual = abs(final_total - initial_total)
    # 32x32 grid x 240 steps x 4 neighbours per cell -> well under 1e-6
    # of float64 rounding noise when Σ T is O(2e4).
    assert residual < 1e-6, (
        f"per-grid conservation broken: initial={initial_total:.6f}, "
        f"final={final_total:.6f}, residual={residual:.6e}"
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 5: no NaNs in either grid
# ────────────────────────────────────────────────────────────────────────────

def test_hello_thermal_no_nan(demo):
    """All temperatures remain finite after a full 240-frame integration."""
    grid_a, grid_b = demo.build_grids()
    demo.step_grids(grid_a, grid_b, frames=240, dt=demo.DEFAULT_DT)

    assert np.all(np.isfinite(grid_a.temperature)), "grid_a contains non-finite values"
    assert np.all(np.isfinite(grid_b.temperature)), "grid_b contains non-finite values"


# ────────────────────────────────────────────────────────────────────────────
# Test 6: visual baseline (golden-master)
# ────────────────────────────────────────────────────────────────────────────

def test_hello_thermal_visual_baseline(demo):
    """Render the side-by-side panel and diff against the committed baseline.

    First run writes ``python/pharos_engine/testing/baselines/hello_thermal.png``
    and passes; subsequent runs require a max per-channel diff <= 0.05.
    """
    grid_a, grid_b = demo.build_grids()
    demo.step_grids(grid_a, grid_b, frames=240, dt=demo.DEFAULT_DT)

    rendered = demo._render_frame(grid_a, grid_b)
    assert rendered.dtype == np.uint8
    assert rendered.shape == (demo.RENDER_H, demo.RENDER_W, 4)

    scene = SimpleNamespace(_image_data=rendered)
    assert_scene_matches(
        scene,
        "hello_thermal",
        tolerance=0.05,
        width=demo.RENDER_W,
        height=demo.RENDER_H,
    )
