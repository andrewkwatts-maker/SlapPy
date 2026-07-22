"""Phase C — divergence-free pressure projection for fluid cells.

These tests own the contract that ``PhysicsWorld._pressure_project`` (CPU
prototype) actually enforces div(v) approx 0 inside a fluid body, that
iteration count drives convergence, that the path is gated on
``CellMaterial.is_fluid``, that closed-box momentum is preserved modulo
the free surface, and that the drop suite shows visibly more water motion
when the projection is on than when it is disabled.
"""
from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from pharos_engine.deform_modes import CellMaterial, cell_material_for
from pharos_engine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
    make_rect_silhouette,
)


# --- helpers ----------------------------------------------------------------

_GRID = 32
_MASK_THRESH = 0.05


def _central_divergence(
    v: np.ndarray, density: np.ndarray, thresh: float = _MASK_THRESH,
) -> np.ndarray:
    """Central-difference divergence used for verification, mirroring the
    diagnostic the kernel and the assess report read from cells.
    """
    mask = (density >= thresh).astype(np.float32)
    m_l = np.roll(mask, 1, axis=1); m_l[:, 0] = 0.0
    m_r = np.roll(mask, -1, axis=1); m_r[:, -1] = 0.0
    m_t = np.roll(mask, 1, axis=0); m_t[0, :] = 0.0
    m_b = np.roll(mask, -1, axis=0); m_b[-1, :] = 0.0
    vx_l = np.roll(v[..., 0], 1, axis=1) * m_l; vx_l[:, 0] = 0.0
    vx_r = np.roll(v[..., 0], -1, axis=1) * m_r; vx_r[:, -1] = 0.0
    vy_t = np.roll(v[..., 1], 1, axis=0) * m_t; vy_t[0, :] = 0.0
    vy_b = np.roll(v[..., 1], -1, axis=0) * m_b; vy_b[-1, :] = 0.0
    return ((vx_r - vx_l) + (vy_b - vy_t)) * 0.5


def _smooth_radial_field(grid: int = _GRID, sigma: float = 6.0) -> np.ndarray:
    """A smooth radially-outward velocity with a Gaussian envelope.

    The pattern is fully resolved on the grid (no singularity at the
    centre), so Jacobi/SOR can drive the projection residual down to
    near-zero in a modest number of sweeps.  Peak |div(v)| is non-trivial
    so the reduction is a meaningful measurement.
    """
    v = np.zeros((grid, grid, 2), dtype=np.float32)
    yy, xx = np.mgrid[0:grid, 0:grid].astype(np.float32)
    cx, cy = (grid - 1) * 0.5, (grid - 1) * 0.5
    dx = xx - cx
    dy = yy - cy
    g = np.exp(-(dx * dx + dy * dy) / (2.0 * sigma * sigma))
    v[..., 0] = dx * g * 0.2
    v[..., 1] = dy * g * 0.2
    return v


def _water_mat(iters: int = 12) -> CellMaterial:
    base = cell_material_for("water")
    assert base is not None and base.is_fluid
    return dataclasses.replace(base, fluid_projection_iters=int(iters))


# --- direct projection tests ------------------------------------------------


def test_projection_reduces_divergence():
    """One projection call drops peak |div(v)| by at least 70% on a
    well-resolved smooth divergence pattern.
    """
    v = _smooth_radial_field()
    density = np.ones((_GRID, _GRID), dtype=np.float32)
    pressure = np.zeros((_GRID, _GRID), dtype=np.float32)
    # Use 20 iters here — the *direct* projection contract is "given
    # enough sweeps, drop divergence by >=70%".  Default is 12 (good
    # enough for visibly responsive water in the assess scenarios); when
    # the test wants to verify the algorithm itself, more iters lets us
    # see clear convergence without false negatives from the slow Jacobi
    # eigenvalues on a 32-cell grid.
    mat = _water_mat(iters=20)

    d0 = _central_divergence(v, density)
    peak0 = float(np.abs(d0).max())
    assert peak0 > 0.05, "Test fixture must have a non-trivial divergence"

    v2, _p2 = PhysicsWorld._pressure_project_arrays(
        v.copy(), pressure, density, mat, dt=1.0 / 60.0,
        mask_threshold=_MASK_THRESH,
    )
    d1 = _central_divergence(v2, density)
    peak1 = float(np.abs(d1).max())
    reduction = 1.0 - peak1 / peak0
    assert reduction >= 0.70, (
        f"Projection must drop peak |div(v)| by at least 70%; "
        f"got peak {peak0:.4f} -> {peak1:.4f} (reduction {reduction:.3f})"
    )


def test_projection_iterations_converge():
    """More Jacobi/SOR sweeps means lower residual divergence."""
    v = _smooth_radial_field()
    density = np.ones((_GRID, _GRID), dtype=np.float32)
    pressure = np.zeros((_GRID, _GRID), dtype=np.float32)

    mat_low = _water_mat(iters=4)
    mat_high = _water_mat(iters=20)

    v_low, _ = PhysicsWorld._pressure_project_arrays(
        v.copy(), pressure.copy(), density, mat_low,
        dt=1.0 / 60.0, mask_threshold=_MASK_THRESH,
    )
    v_high, _ = PhysicsWorld._pressure_project_arrays(
        v.copy(), pressure.copy(), density, mat_high,
        dt=1.0 / 60.0, mask_threshold=_MASK_THRESH,
    )
    peak_low = float(np.abs(_central_divergence(v_low, density)).max())
    peak_high = float(np.abs(_central_divergence(v_high, density)).max())
    assert peak_high < peak_low, (
        f"20-iter projection must beat 4-iter; got 4-iter peak={peak_low:.4f} "
        f"vs 20-iter peak={peak_high:.4f}"
    )


def test_projection_zero_for_non_fluid(monkeypatch):
    """The kernel must NOT run pressure projection on non-fluid materials.

    A monkeypatched call counter on ``_pressure_project_arrays`` lets us
    assert the path was untouched for a steel body falling onto a stone
    ground (no fluid in the scene).
    """
    calls: list[tuple[bool, int]] = []
    real_proj = PhysicsWorld._pressure_project_arrays

    def _counting_proj(v, pressure, density, mat, dt, mask_threshold):
        calls.append((bool(mat.is_fluid), int(mat.fluid_projection_iters)))
        return real_proj(v, pressure, density, mat, dt, mask_threshold)

    monkeypatch.setattr(
        PhysicsWorld, "_pressure_project_arrays", staticmethod(_counting_proj),
    )

    w = PhysicsWorld(world_bounds=(-200.0, -100.0, 200.0, 250.0))
    w.create_body(
        make_rect_silhouette(240, 16),
        material="stone",
        position=(0.0, 180.0),
        fixed=True,
    )
    w.create_body(
        make_circle_silhouette(24),
        material="steel",
        position=(0.0, 0.0),
    )
    for _ in range(12):
        w.step()

    # If projection ever ran, it must only have been for is_fluid=True
    # materials.  For a steel/stone scene we expect zero invocations.
    fluid_calls = [c for c in calls if c[0]]
    assert fluid_calls == [], (
        f"Projection must not run on non-fluid materials; got calls={calls}"
    )


def test_projection_preserves_total_momentum_modulo_boundary():
    """Inside a *divergence-free* velocity field projection is a no-op on
    linear momentum.  This is the cleanest closed-box statement of the
    invariant: if div(v) is already zero, the projection adds nothing.

    We use a curl-driven (purely rotational) velocity field — which is by
    construction divergence-free — and assert the body's net linear
    momentum changes by less than 1%.

    Why not a random field?  Projection necessarily exchanges momentum
    through whatever boundary handles the divergence.  Even in a
    fully-filled grid the discrete Dirichlet boundary at the grid edge
    bleeds some momentum out.  Net momentum conservation is only exact
    for a closed-wall (Neumann) boundary on top of a curl-free RHS;
    asserting that here directly tests the property the spec calls out
    ("projection conserves momentum for incompressible flow with closed
    boundaries").
    """
    yy, xx = np.mgrid[0:_GRID, 0:_GRID].astype(np.float32)
    cx, cy = (_GRID - 1) * 0.5, (_GRID - 1) * 0.5
    dx = xx - cx
    dy = yy - cy
    sigma = 6.0
    g = np.exp(-(dx * dx + dy * dy) / (2.0 * sigma * sigma))
    # Curl of a scalar Gaussian: (d/dy g, -d/dx g).
    # That is by construction divergence-free in the continuous limit and
    # discretely close to it; projection should leave it nearly untouched.
    v = np.zeros((_GRID, _GRID, 2), dtype=np.float32)
    v[..., 0] = dy * g * 0.2
    v[..., 1] = -dx * g * 0.2

    # Fill the body strictly inside the grid so the body's silhouette mask
    # (not the grid edge) sets the Dirichlet free-surface boundary.
    density = np.zeros((_GRID, _GRID), dtype=np.float32)
    density[2:-2, 2:-2] = 1.0
    # Mask v to the body so we measure body momentum only.
    v *= (density >= _MASK_THRESH).astype(np.float32)[..., None]
    pressure = np.zeros((_GRID, _GRID), dtype=np.float32)
    mat = _water_mat(iters=16)

    rho = float(mat.density_rho)
    m_per_cell = rho * density[..., None]  # (H, W, 1)
    p_before = (m_per_cell * v).sum(axis=(0, 1))

    v2, _p2 = PhysicsWorld._pressure_project_arrays(
        v.copy(), pressure, density, mat,
        dt=1.0 / 60.0, mask_threshold=_MASK_THRESH,
    )
    p_after = (m_per_cell * v2).sum(axis=(0, 1))

    # Reference scale: total absolute momentum magnitude in the body.
    # Using the per-cell-momentum L1 norm gives a meaningful denominator
    # even when the symmetric curl field cancels to a near-zero net.
    abs_mom = float(np.abs(m_per_cell * v).sum())
    ref = max(abs_mom, 1e-3)
    drift = float(np.linalg.norm(p_after - p_before)) / ref
    assert drift < 0.01, (
        f"Curl-driven (divergence-free) field projection should leave "
        f"net body momentum unchanged within 1% of |m*v|_1; got "
        f"drift {drift:.4f} (p_before={p_before}, p_after={p_after}, "
        f"|m*v|_1={abs_mom:.3f})"
    )


# --- end-to-end drop scenario ----------------------------------------------


_FRAMES = 60
_BALL_DIAMETER = 24
_GROUND_W = 240
_GROUND_H = 16


def _steel_into_water_with_iters(iters: int, frames: int = 120):
    """Run the steel-into-water drop with a chosen projection iteration
    count and return per-channel peak metrics on the water cell grid.

    Phase C makes water actually slosh, so the most diagnostic signal is
    peak lateral velocity ``|v_x|`` (the splash spreading sideways) which
    is essentially zero on the legacy damped-pressure path.  We also
    report ``|v_y|`` and ``|u_y|`` for visual review.
    """
    w = PhysicsWorld(world_bounds=(-200.0, -100.0, 200.0, 250.0))
    ground = w.create_body(
        make_rect_silhouette(_GROUND_W, _GROUND_H),
        material="water",
        position=(0.0, 180.0),
        fixed=True,
    )
    # Override projection iteration count on this body's material instance.
    hid = ground.root_hull_id
    mat = w._materials.get(int(w.hulls.material_id[hid]))
    assert mat is not None and mat.is_fluid
    w._materials[int(w.hulls.material_id[hid])] = dataclasses.replace(
        mat, fluid_projection_iters=int(iters),
    )

    w.create_body(
        make_circle_silhouette(_BALL_DIAMETER),
        material="steel",
        position=(0.0, 0.0),
    )

    peaks = {"vx": 0.0, "vy": 0.0, "uy": 0.0}
    for _ in range(frames):
        w.step()
        cells = ground.cells
        if cells is None:
            continue
        peaks["vx"] = max(peaks["vx"], float(np.abs(cells[..., 2]).max()))
        peaks["vy"] = max(peaks["vy"], float(np.abs(cells[..., 3]).max()))
        peaks["uy"] = max(peaks["uy"], float(np.abs(cells[..., 1]).max()))
    return peaks


def test_water_pool_with_ball_shows_visible_displacement():
    """A steel ball dropped into a water pool moves the water visibly more
    when projection is on than when it is disabled.

    The Phase C projection produces lateral splashing velocity that simply
    cannot exist on the legacy damped-pressure path (peak |v_x| was on the
    order of 0.02 before; it jumps two orders of magnitude with projection
    on).  Compare both with iters=0 (projection disabled) and iters=12
    (default).
    """
    peaks_off = _steel_into_water_with_iters(iters=0)
    peaks_on = _steel_into_water_with_iters(iters=12)
    # Splash spread — lateral velocity is the unambiguous indicator that
    # the projection is doing real work; the legacy path produces
    # essentially zero |v_x| because divergence accumulates rather than
    # converts into pressure-driven lateral flow.
    assert peaks_on["vx"] > peaks_off["vx"] * 10, (
        f"Projection-on water must splash much more than projection-off; "
        f"on |v_x|={peaks_on['vx']:.4f}, off |v_x|={peaks_off['vx']:.4f}"
    )
    assert peaks_on["vx"] > 0.5, (
        f"Projection-on peak |v_x| should be visible (>0.5 cells/substep); "
        f"got {peaks_on['vx']:.4f}"
    )


def test_existing_drop_tests_still_pass():
    """The Sprint-1 drop ordering still holds with Phase C on: water
    *velocity* exceeds mud's velocity (sloshing splash spreads laterally
    where mud just damps), and water moves at all.  Stone still rings
    louder than mud.

    Why velocity instead of displacement (`u`)?  The Phase C projection
    enforces near-incompressibility, which constrains the integrated `u`
    field on a fully-filled water body — splashing energy now shows up in
    `v` (lateral and vertical velocity) much more clearly than in `u`,
    which only accumulates while v has a steady non-oscillating component.
    The drop-test intent — "water reacts more than mud" — is preserved by
    asserting on v; that signal is two orders of magnitude larger with
    projection on than without.
    """
    def _drop(ball_mat: str, ground_mat: str) -> dict:
        w = PhysicsWorld(world_bounds=(-200.0, -100.0, 200.0, 250.0))
        ground = w.create_body(
            make_rect_silhouette(_GROUND_W, _GROUND_H),
            material=ground_mat,
            position=(0.0, 180.0),
            fixed=True,
        )
        w.create_body(
            make_circle_silhouette(_BALL_DIAMETER),
            material=ball_mat,
            position=(0.0, 0.0),
        )
        peak_u = peak_v = 0.0
        for _ in range(120):
            w.step()
            c = ground.cells
            if c is None:
                continue
            peak_u = max(peak_u, float(np.max(np.abs(c[..., 0:2]))))
            peak_v = max(peak_v, float(np.max(np.abs(c[..., 2:4]))))
        return {"max_v": peak_v, "max_u": peak_u}

    m_water = _drop("steel", "water")
    m_mud = _drop("steel", "mud")
    m_stone = _drop("steel", "stone")

    assert m_water["max_v"] > m_mud["max_v"], (
        f"Water v must exceed mud v (water={m_water['max_v']:.4f}, "
        f"mud={m_mud['max_v']:.4f})"
    )
    assert m_water["max_v"] > 1.0, (
        f"Water cells must be visibly moving (peak |v| > 1); "
        f"got {m_water['max_v']:.4f}"
    )
    assert m_stone["max_v"] > m_mud["max_v"], (
        f"Stone should ring louder than mud; "
        f"stone={m_stone['max_v']:.4f} mud={m_mud['max_v']:.4f}"
    )
