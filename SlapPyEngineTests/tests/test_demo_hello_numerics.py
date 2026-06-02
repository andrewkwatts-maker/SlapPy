"""Tests for the ``examples/hello_numerics.py`` demo.

Pins six behaviours of the multigrid Poisson demo:

1. ``main()`` runs cleanly in-process and returns a sane summary dict.
2. Solution is smooth inside the live mask — the absolute solution value
   at the mask centre is non-trivial AND the max per-cell gradient
   magnitude is bounded (no high-frequency error blow-up).
3. Solution is exactly zero outside the mask — vacuum clamp invariant.
4. The L2 residual norm after 5 V-cycles stays below an empirical bound
   (the solver converges by an order of magnitude relative to the bump
   peak, even at the default smoother strength).
5. No NaN / ±inf leak into the solution.
6. The rasterised 3-panel render reproduces the committed visual
   baseline via :func:`slappyengine.testing.assert_scene_matches`.

The Poisson equation as written by the demo is ``Δp = +rhs`` on a
Dirichlet-zero boundary, so the solution is *everywhere non-positive*
for a non-negative source. Tests therefore assert on ``abs(centre)``
rather than ``centre > 0``.
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
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_numerics.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("hello_numerics_demo", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_numerics_demo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


# ────────────────────────────────────────────────────────────────────────────
# Test 1: demo runs cleanly
# ────────────────────────────────────────────────────────────────────────────

def test_hello_numerics_runs_without_error(demo, tmp_path):
    """``main(render=False)`` returns a summary dict and never raises."""
    summary = demo.main(render=False, out=tmp_path / "ignored.png")
    assert summary["grid_size"] == demo.GRID_SIZE
    assert summary["n_cycles"] == demo.N_CYCLES
    assert np.isfinite(summary["max_rhs"])
    assert np.isfinite(summary["max_solution"])
    assert np.isfinite(summary["max_abs_residual"])
    assert np.isfinite(summary["residual_l2_norm"])
    assert summary["nan_seen"] is False


# ────────────────────────────────────────────────────────────────────────────
# Test 2: solution is smooth inside the mask
# ────────────────────────────────────────────────────────────────────────────

def test_solution_is_smooth_inside_mask(demo):
    """Centre value is non-trivial and the in-mask gradient stays bounded.

    With a positive Gaussian source feeding ``Δp = +rhs`` and Dirichlet
    zero on the disc boundary, the solution dips to a strong negative
    minimum at the mask centre. The test checks the magnitude (sign
    convention is encoded by the solver, not the demo).

    The max per-cell central-difference gradient inside the mask must
    remain below ``5.0`` — that bound is empirically ~1.8 for the
    converged 5-cycle solution, so a 5x headroom catches any high-
    frequency error spike without flagging healthy gradients near the
    bump shoulder.
    """
    rhs = demo.build_source()
    mask = demo.build_mask()
    solution, residual = demo.solve(rhs, mask, n_cycles=demo.N_CYCLES)
    summary = demo.summarise(rhs, solution, residual, mask)

    centre_val = summary["centre_solution"]
    assert abs(centre_val) > 0.0, (
        f"solution at mask centre is trivially zero: {centre_val}"
    )
    # Looser positive lower bound on magnitude — the converged centre
    # value is ~30 for this rhs / mask / cycle count combination, so
    # 1.0 catches any catastrophic collapse without being brittle.
    assert abs(centre_val) > 1.0, (
        f"solution at mask centre is too small: abs={abs(centre_val):.6f}"
    )

    max_grad = summary["max_grad_inside"]
    assert max_grad < 5.0, (
        f"max in-mask gradient too large: {max_grad:.4f} "
        "(suggests SOR didn't damp high-frequency error)"
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 3: solution is zero outside the mask
# ────────────────────────────────────────────────────────────────────────────

def test_solution_zero_outside_mask(demo):
    """Every vacuum cell of the returned solution is exactly 0.

    ``vcycle_poisson`` masks the output before returning so this should
    hold to bit-exactness, not just float tolerance.
    """
    rhs = demo.build_source()
    mask = demo.build_mask()
    solution, _ = demo.solve(rhs, mask, n_cycles=demo.N_CYCLES)

    outside = ~mask
    vac_values = np.asarray(solution)[outside]
    assert vac_values.size > 0, "test prerequisite: mask must leave vacuum cells"
    assert np.all(vac_values == 0.0), (
        f"non-zero solution in vacuum: count="
        f"{int(np.count_nonzero(vac_values))}, "
        f"max|val|={float(np.max(np.abs(vac_values))):.6e}"
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 4: residual L2 norm stays below an empirical bound
# ────────────────────────────────────────────────────────────────────────────

def test_residual_norm_below_bound(demo):
    """5 V-cycles drive ||r||_2 well below the rhs peak.

    The Poisson rhs has unit peak and an L2 mass of ~25 (Gaussian
    sigma=4 on a 64² grid). At ``n_cycles=5`` with the solver's default
    ``iters_per_level=2, levels=3`` knobs, ``||r||_2`` lands around
    0.23 — two orders of magnitude below the source. The 0.3 bound
    leaves headroom for solver-internal tuning while still catching a
    real convergence regression (e.g. SOR smoother breakage would
    blow this past 1.0).
    """
    rhs = demo.build_source()
    mask = demo.build_mask()
    solution, residual = demo.solve(rhs, mask, n_cycles=demo.N_CYCLES)

    l2 = float(np.linalg.norm(residual))
    assert l2 < 0.3, f"residual L2 norm too large: ||r||_2={l2:.6e}"
    # Sanity: the solver actually reduced the residual compared to the
    # initial guess (where r = rhs and ||rhs||_2 ≈ 25).
    rhs_l2 = float(np.linalg.norm(rhs * mask.astype(np.float32)))
    assert l2 < 0.05 * rhs_l2, (
        f"residual not significantly reduced vs initial rhs L2: "
        f"||r||_2={l2:.4e}, ||rhs||_2={rhs_l2:.4e}"
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 5: no NaN / ±inf in the solution
# ────────────────────────────────────────────────────────────────────────────

def test_no_nan_in_solution(demo):
    """All solution cells remain finite."""
    rhs = demo.build_source()
    mask = demo.build_mask()
    solution, _ = demo.solve(rhs, mask, n_cycles=demo.N_CYCLES)

    assert np.all(np.isfinite(solution)), (
        "solution contains non-finite values"
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 6: visual baseline (golden-master)
# ────────────────────────────────────────────────────────────────────────────

def test_hello_numerics_visual_baseline(demo):
    """Render the 3-panel composite and diff against the committed baseline.

    First run writes ``python/slappyengine/testing/baselines/hello_numerics.png``
    and passes; subsequent runs require a max per-channel diff <= 0.05.
    """
    rhs = demo.build_source()
    mask = demo.build_mask()
    solution, residual = demo.solve(rhs, mask, n_cycles=demo.N_CYCLES)

    rendered = demo._render_frame(rhs, solution, residual)
    assert rendered.dtype == np.uint8
    assert rendered.shape == (demo.RENDER_H, demo.RENDER_W, 4)

    scene = SimpleNamespace(_image_data=rendered)
    assert_scene_matches(
        scene,
        "hello_numerics",
        tolerance=0.05,
        width=demo.RENDER_W,
        height=demo.RENDER_H,
    )
