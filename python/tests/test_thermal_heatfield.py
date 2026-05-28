"""Tests for the Phase B ``slappyengine.thermal.HeatField`` public surface.

These cover the spec'd Phase B API:

* ``HeatField(grid, conductivity, diffusivity)`` over an existing array
  (modified in place).
* ``field.step(dt)`` runs one explicit heat-equation update with the
  pairwise Laplacian formula lifted from
  ``physics.boundary_exchange.py:_exchange_pair``.
* ``field.exchange_with(other, contact_pairs)`` conserves total energy
  across two fields.
* ``boundary='clamp'`` does not leak heat through the outer rectangle;
  ``boundary='periodic'`` (default) wraps the grid.
"""
from __future__ import annotations

import numpy as np
import pytest


# ── Spec'd surface: grid-as-positional construction ────────────────────────


def test_grid_constructor_holds_reference_and_mutates_in_place():
    """``HeatField(grid)`` must mutate the caller's array in place."""
    from slappyengine.thermal import HeatField

    T = np.zeros((8, 8), dtype=np.float64)
    T[4, 4] = 100.0
    f = HeatField(T, conductivity=1.0, diffusivity=0.1)
    # The field exposes the same array, not a copy.
    assert f.temperature is T
    f.step(0.1)
    # Peak dropped: the centre cell shed heat to its neighbours.
    assert T[4, 4] < 100.0
    # Neighbours warmed.
    assert T[3, 4] > 0.0
    assert T[5, 4] > 0.0
    assert T[4, 3] > 0.0
    assert T[4, 5] > 0.0


def test_grid_constructor_requires_2d():
    from slappyengine.thermal import HeatField

    with pytest.raises(ValueError):
        HeatField(np.zeros(16, dtype=np.float64))


def test_grid_constructor_requires_ndarray():
    from slappyengine.thermal import HeatField

    with pytest.raises(TypeError):
        HeatField([[0.0, 1.0], [2.0, 3.0]])  # type: ignore[arg-type]


def test_subpackage_lazy_import():
    """``from slappyengine import thermal`` must resolve via ``_LAZY_MAP``."""
    import slappyengine

    th = slappyengine.thermal
    assert hasattr(th, "HeatField")
    assert hasattr(th, "exchange_two_regions")


# ── Hot blob diffuses outward, energy approximately conserved ─────────────


def test_hot_blob_diffuses_outward_with_energy_conservation():
    """A hot central blob spreads to its neighbours; peak drops, total
    heat stays put (conservation comes from the pairwise edge formula)."""
    from slappyengine.thermal import HeatField

    T = np.zeros((16, 16), dtype=np.float64)
    T[8, 8] = 1000.0
    T[8, 7] = 1000.0
    T[7, 8] = 1000.0
    T[7, 7] = 1000.0
    initial_total = float(T.sum())
    initial_peak = float(T.max())

    f = HeatField(T, conductivity=1.0, diffusivity=0.1)
    for _ in range(20):
        f.step(0.05)

    final_total = float(T.sum())
    final_peak = float(T.max())

    # Peak fell (blob smeared out).
    assert final_peak < initial_peak * 0.9, (
        f"peak did not drop: initial {initial_peak} final {final_peak}"
    )
    # Edges of the original hot block warmed.
    assert T[6, 7] > 1.0
    assert T[9, 7] > 1.0
    # Total energy preserved within float tolerance. f64 + pairwise
    # edge updates → drift should be near machine epsilon.
    drift = abs(final_total - initial_total)
    assert drift < 1e-9 * max(1.0, initial_total), (
        f"energy drift {drift:.3e} exceeds tolerance; "
        f"initial={initial_total}, final={final_total}"
    )


def test_step_with_zero_dt_is_noop():
    from slappyengine.thermal import HeatField

    T = np.full((4, 4), 5.0, dtype=np.float64)
    T_ref = T.copy()
    f = HeatField(T)
    f.step(0.0)
    assert np.array_equal(T, T_ref)


def test_step_rejects_unknown_boundary():
    from slappyengine.thermal import HeatField

    f = HeatField(np.zeros((4, 4), dtype=np.float64))
    with pytest.raises(ValueError):
        f.step(0.1, boundary="nonsense")


# ── exchange_with: conserves total energy across two fields ───────────────


def test_exchange_with_moves_heat_hot_to_cold_and_conserves_total():
    """Two fields, one hot cell vs one cold cell — heat flows hot → cold,
    total energy across both fields stays constant."""
    from slappyengine.thermal import HeatField

    A = np.zeros((4, 4), dtype=np.float64)
    B = np.zeros((4, 4), dtype=np.float64)
    A[2, 2] = 100.0
    B[1, 1] = 0.0

    fa = HeatField(A, conductivity=1.0, diffusivity=0.1)
    fb = HeatField(B, conductivity=1.0, diffusivity=0.1)
    initial = float(A.sum() + B.sum())

    pairs = [((2, 2), (1, 1))]
    # Single short step.
    q = fa.exchange_with(fb, pairs, dt=0.05)
    assert q > 0.0  # A was hotter → positive flux to B
    assert A[2, 2] < 100.0
    assert B[1, 1] > 0.0
    final = float(A.sum() + B.sum())
    assert abs(final - initial) < 1e-12, (
        f"total energy drifted by {final - initial:.3e}"
    )


def test_exchange_with_equilibrates_over_time():
    """Repeated exchanges across the same pair drive the two cells to
    equal temperature; total ΔE ≈ 0."""
    from slappyengine.thermal import HeatField

    A = np.array([[80.0]], dtype=np.float64)
    B = np.array([[0.0]], dtype=np.float64)
    # The single-cell case still passes shape (1, N>=2)? No — the constructor
    # requires 2x2 minimum. Pad with zero cells that never participate.
    A_grid = np.zeros((2, 2), dtype=np.float64)
    B_grid = np.zeros((2, 2), dtype=np.float64)
    A_grid[0, 0] = 80.0
    B_grid[0, 0] = 0.0
    fa = HeatField(A_grid, conductivity=1.0, diffusivity=1.0)
    fb = HeatField(B_grid, conductivity=1.0, diffusivity=1.0)
    initial = float(A_grid.sum() + B_grid.sum())

    pairs = [((0, 0), (0, 0))]
    for _ in range(500):
        fa.exchange_with(fb, pairs, dt=0.05)

    final = float(A_grid.sum() + B_grid.sum())
    # Conservation — exact to float rounding.
    assert abs(final - initial) < 1e-9, (
        f"total ΔE = {final - initial:.3e} (expected ≈ 0)"
    )
    # Equilibrium reached.
    assert abs(float(A_grid[0, 0]) - float(B_grid[0, 0])) < 0.5, (
        f"did not equilibrate: A={A_grid[0, 0]}, B={B_grid[0, 0]}"
    )
    # Equilibrium is the mass-weighted mean (m=1 each → arithmetic mean).
    assert abs((float(A_grid[0, 0]) + float(B_grid[0, 0])) / 2.0 - 40.0) < 0.01


def test_exchange_with_no_op_for_equal_temperatures():
    from slappyengine.thermal import HeatField

    A = np.full((3, 3), 25.0, dtype=np.float64)
    B = np.full((3, 3), 25.0, dtype=np.float64)
    fa = HeatField(A)
    fb = HeatField(B)
    q = fa.exchange_with(fb, [((0, 0), (0, 0)), ((1, 1), (1, 1))], dt=0.1)
    assert q == 0.0
    assert np.array_equal(A, np.full((3, 3), 25.0))
    assert np.array_equal(B, np.full((3, 3), 25.0))


def test_exchange_with_skips_out_of_bounds_pairs():
    from slappyengine.thermal import HeatField

    A = np.zeros((2, 2), dtype=np.float64)
    B = np.zeros((2, 2), dtype=np.float64)
    A[0, 0] = 10.0
    fa = HeatField(A)
    fb = HeatField(B)
    # Mix valid and invalid indices.
    pairs = [
        ((0, 0), (0, 0)),    # valid
        ((5, 5), (0, 0)),    # OOB on A
        ((0, 0), (-1, 0)),   # OOB on B
    ]
    initial = float(A.sum() + B.sum())
    fa.exchange_with(fb, pairs, dt=0.01)
    final = float(A.sum() + B.sum())
    assert abs(final - initial) < 1e-12


# ── Boundary modes: clamp vs periodic ─────────────────────────────────────


def test_clamp_boundary_does_not_leak_through_edges():
    """With ``boundary='clamp'``, a hot strip on the east edge does NOT warm
    the west edge — there's no toroidal wrap."""
    from slappyengine.thermal import HeatField

    T = np.zeros((8, 8), dtype=np.float64)
    T[:, 7] = 100.0  # entire east edge hot
    initial_total = float(T.sum())

    f = HeatField(T, conductivity=1.0, diffusivity=0.2)
    for _ in range(30):
        f.step(0.05, boundary="clamp")

    # With pure diffusion across 7 cells the west edge will warm some
    # via direct propagation, but with 30 short steps it stays well
    # below the east edge temperature.
    assert float(T[:, 0].max()) < float(T[:, 7].max()) * 0.5

    # Energy preserved exactly across the clamp boundary too.
    final_total = float(T.sum())
    drift = abs(final_total - initial_total)
    assert drift < 1e-9 * max(1.0, initial_total), (
        f"clamp boundary drift {drift:.3e} on total={initial_total:.3f}"
    )


def test_periodic_boundary_wraps_heat_around_edges():
    """With ``boundary='periodic'`` (default), heat injected on the east
    edge quickly warms the west edge via toroidal wrap — much faster than
    direct diffusion would predict for a single step."""
    from slappyengine.thermal import HeatField

    # Periodic case
    T_per = np.zeros((4, 8), dtype=np.float64)
    T_per[:, 7] = 100.0
    f_per = HeatField(T_per, conductivity=1.0, diffusivity=0.2)
    f_per.step(0.05)  # default periodic
    west_per = float(T_per[:, 0].mean())

    # Clamp case for contrast — same initial state, same step size.
    T_clamp = np.zeros((4, 8), dtype=np.float64)
    T_clamp[:, 7] = 100.0
    f_clamp = HeatField(T_clamp, conductivity=1.0, diffusivity=0.2)
    f_clamp.step(0.05, boundary="clamp")
    west_clamp = float(T_clamp[:, 0].mean())

    # Periodic west edge is far warmer than clamp west edge after one
    # step (the only way heat reaches column 0 in periodic mode is via
    # the column-7 ↔ column-0 wrap; clamp has no such shortcut).
    assert west_per > west_clamp + 1.0, (
        f"periodic wrap did not heat west edge: per={west_per}, clamp={west_clamp}"
    )

    # Both runs conserve their own initial totals.
    assert abs(float(T_per.sum()) - 4 * 100.0) < 1e-9
    assert abs(float(T_clamp.sum()) - 4 * 100.0) < 1e-9


def test_clamp_explicit_conservation_long_run():
    """30 frames with hot/cold random pattern, ``boundary='clamp'`` — Σ T
    is invariant to float tolerance."""
    from slappyengine.thermal import HeatField

    rng = np.random.default_rng(42)
    T = rng.uniform(0.0, 100.0, size=(12, 12))
    initial_total = float(T.sum())
    f = HeatField(T, conductivity=1.0, diffusivity=0.15)
    for _ in range(30):
        f.step(0.05, boundary="clamp")
    final_total = float(T.sum())
    drift = abs(final_total - initial_total)
    assert drift < 1e-9 * initial_total, (
        f"clamp boundary drift {drift:.3e} on total={initial_total:.3f}"
    )


def test_periodic_explicit_conservation_long_run():
    """Same long-run check for the periodic boundary."""
    from slappyengine.thermal import HeatField

    rng = np.random.default_rng(7)
    T = rng.uniform(0.0, 100.0, size=(12, 12))
    initial_total = float(T.sum())
    f = HeatField(T, conductivity=1.0, diffusivity=0.15)
    for _ in range(30):
        f.step(0.05, boundary="periodic")
    final_total = float(T.sum())
    drift = abs(final_total - initial_total)
    assert drift < 1e-9 * initial_total, (
        f"periodic boundary drift {drift:.3e} on total={initial_total:.3f}"
    )
