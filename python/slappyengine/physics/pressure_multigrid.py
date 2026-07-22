"""pressure_multigrid.py — Multi-grid V-cycle pressure projection.

Single-grid Red-Black SOR (the legacy path in
:py:meth:`PhysicsWorld._pressure_project_arrays`) damps high-frequency error
modes quickly but converges geometrically on the long-wavelength modes —
the spectral radius scales like ``cos(π/N)``, so a 32-cell grid takes 50+
sweeps to drop a low-frequency residual by an order of magnitude.

A multi-grid V-cycle attacks the long-wavelength modes by restricting the
residual to a coarser grid (16×16), smoothing aggressively there (where
those modes become high-frequency relative to the coarse spacing), and
prolonging the correction back up.  Two V-cycles routinely beat 30+
single-grid sweeps on the canonical Gaussian-divergence fixture.

Operator pair (matches the single-grid solver in ``world.py``)
--------------------------------------------------------------
* Divergence: backward-difference  ``div = (vx - vx_l) + (vy - vy_t)``.
* Gradient:   forward-difference   ``grad p = (p_r - p, p_b - p)``.

Composed, these give the standard 5-point Laplacian with no checkerboard
null-space, so SOR converges on the kept Fourier modes rather than
stalling on the cancelling pair.

Boundary
--------
Cells outside the silhouette mask (``density < threshold``) are treated as
vacuum: pressure clamped to zero, no contribution to neighbour updates,
no gradient subtracted.  Identical to the single-grid path so the V-cycle
output is a drop-in replacement.

Cost model
----------
The fine smoother costs ``S × 32²`` cell updates per sweep.  The coarse
solve costs ``C × 16²`` per sweep.  One V-cycle with
``smooth_pre=smooth_post=2, coarse_iters=8`` runs
``(2 + 2) × 32² + 8 × 16² = 4096 + 2048 = 6144`` cell updates, which is
the equivalent of ``6144 / 32² = 6`` single-grid sweeps in pure work but
removes long-wavelength modes that 6 single-grid sweeps cannot touch.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from slappyengine._compat import CellMaterial


__all__ = ["vcycle_project", "vcycle_project_v"]


# ---------------------------------------------------------------------------
#  Grid transfer operators
# ---------------------------------------------------------------------------


def _restrict_2x2(field: np.ndarray) -> np.ndarray:
    """Average 2×2 blocks: (H, W) → (H//2, W//2).

    Pure 2×2 block-mean (a.k.a. full-weighting on a cell-centred grid).
    Single numpy reshape+mean — no Python loop.
    """
    H, W = field.shape
    assert H % 2 == 0 and W % 2 == 0, f"restrict needs even dims, got {H}x{W}"
    return field.reshape(H // 2, 2, W // 2, 2).mean(axis=(1, 3))


def _restrict_mask(mask: np.ndarray) -> np.ndarray:
    """Coarse mask is the maximum of each 2×2 block (a coarse cell is
    fluid if *any* of its four fine children is fluid).

    Using max rather than mean gives the coarse Laplacian a sensible
    boundary even when the fine body has thin one-cell-wide features.
    """
    H, W = mask.shape
    return mask.reshape(H // 2, 2, W // 2, 2).max(axis=(1, 3))


def _prolong_bilinear(coarse: np.ndarray, fine_shape: tuple[int, int]) -> np.ndarray:
    """Bilinear upsample (Hc, Wc) → (Hf, Wf).

    Uses ``np.kron`` for the 2× nearest-neighbour step then averages with
    a one-cell-shifted copy along each axis — equivalent to bilinear
    interpolation on a cell-centred grid, and faster than calling out to
    ``scipy.ndimage.zoom`` for a fixed 2× factor.
    """
    Hf, Wf = fine_shape
    Hc, Wc = coarse.shape
    assert Hf == 2 * Hc and Wf == 2 * Wc, (
        f"prolong needs 2x factor, got coarse {Hc}x{Wc} → fine {Hf}x{Wf}"
    )
    # Nearest-neighbour 2x upsample.
    nn = np.repeat(np.repeat(coarse, 2, axis=0), 2, axis=1)
    # Average with x-shifted and y-shifted neighbours to smooth seams.
    # Pad-replicate at boundaries so corners aren't pulled to zero.
    nn_xshift = np.empty_like(nn)
    nn_xshift[:, :-1] = nn[:, 1:]
    nn_xshift[:, -1] = nn[:, -1]
    nn_yshift = np.empty_like(nn)
    nn_yshift[:-1, :] = nn[1:, :]
    nn_yshift[-1, :] = nn[-1, :]
    nn_xyshift = np.empty_like(nn)
    nn_xyshift[:-1, :-1] = nn[1:, 1:]
    nn_xyshift[-1, :] = nn_xshift[-1, :]
    nn_xyshift[:, -1] = nn_yshift[:, -1]
    return (nn + nn_xshift + nn_yshift + nn_xyshift) * 0.25


# ---------------------------------------------------------------------------
#  SOR smoother (matches the in-place sweep in world.py)
# ---------------------------------------------------------------------------


def _build_neighbour_masks(mask: np.ndarray) -> tuple[np.ndarray, ...]:
    """Pre-shift the binary mask once.  Identical layout to ``world.py``."""
    m_l = np.zeros_like(mask)
    m_l[:, 1:] = mask[:, :-1]
    m_r = np.zeros_like(mask)
    m_r[:, :-1] = mask[:, 1:]
    m_t = np.zeros_like(mask)
    m_t[1:, :] = mask[:-1, :]
    m_b = np.zeros_like(mask)
    m_b[:-1, :] = mask[1:, :]
    return m_l, m_r, m_t, m_b


def _sor_sweep(
    p: np.ndarray,
    rhs: np.ndarray,
    mask: np.ndarray,
    m_l: np.ndarray,
    m_r: np.ndarray,
    m_t: np.ndarray,
    m_b: np.ndarray,
    iters: int,
    omega: float,
) -> np.ndarray:
    """Red-Black SOR sweeps on the 5-point Poisson operator.

    Solves ``Δp = rhs`` (in the Jacobi-style relaxation:
    ``p[i,j] = (sum_neighbours - rhs) / 4``) for ``iters`` complete
    red-then-black passes.  Modifies and returns ``p``.

    Performance: the per-sweep arithmetic is reorganised into in-place
    ops on the ``nb_sum`` scratch (``np.subtract(..., out=nb_sum)``
    style) so the inner loop allocates zero temporaries — matching the
    optimisation applied to the single-grid path in
    :py:meth:`PhysicsWorld._pressure_project_arrays`.
    """
    if iters <= 0:
        return p
    omega32 = np.float32(omega)
    yy, xx = np.indices(p.shape)
    red_w = (((yy + xx) % 2 == 0).astype(np.float32) * mask) * omega32
    black_w = (((yy + xx) % 2 == 1).astype(np.float32) * mask) * omega32
    nb_sum = np.empty_like(p)
    for _ in range(iters):
        # Red sweep — gather → in-place SOR update on nb_sum, then add to p.
        nb_sum.fill(0.0)
        nb_sum[:, 1:] += p[:, :-1] * m_l[:, 1:]
        nb_sum[:, :-1] += p[:, 1:] * m_r[:, :-1]
        nb_sum[1:, :] += p[:-1, :] * m_t[1:, :]
        nb_sum[:-1, :] += p[1:, :] * m_b[:-1, :]
        np.subtract(nb_sum, rhs, out=nb_sum)
        nb_sum *= 0.25
        np.subtract(nb_sum, p, out=nb_sum)
        nb_sum *= red_w
        p += nb_sum
        # Black sweep — same in-place form on regathered neighbours.
        nb_sum.fill(0.0)
        nb_sum[:, 1:] += p[:, :-1] * m_l[:, 1:]
        nb_sum[:, :-1] += p[:, 1:] * m_r[:, :-1]
        nb_sum[1:, :] += p[:-1, :] * m_t[1:, :]
        nb_sum[:-1, :] += p[1:, :] * m_b[:-1, :]
        np.subtract(nb_sum, rhs, out=nb_sum)
        nb_sum *= 0.25
        np.subtract(nb_sum, p, out=nb_sum)
        nb_sum *= black_w
        p += nb_sum
        p *= mask
    return p


def _compute_residual(
    p: np.ndarray,
    rhs: np.ndarray,
    mask: np.ndarray,
    m_l: np.ndarray,
    m_r: np.ndarray,
    m_t: np.ndarray,
    m_b: np.ndarray,
) -> np.ndarray:
    """Residual ``r = rhs - Δp`` on the masked 5-point operator.

    For the discrete Laplacian
    ``Δp[i,j] = p_l + p_r + p_t + p_b - 4 p[i,j]``
    the residual the V-cycle needs to restrict is exactly
    ``rhs - Δp`` (zero in vacuum cells).
    """
    nb_sum = np.zeros_like(p)
    nb_sum[:, 1:] += p[:, :-1] * m_l[:, 1:]
    nb_sum[:, :-1] += p[:, 1:] * m_r[:, :-1]
    nb_sum[1:, :] += p[:-1, :] * m_t[1:, :]
    nb_sum[:-1, :] += p[1:, :] * m_b[:-1, :]
    lap_p = nb_sum - np.float32(4.0) * p
    return (rhs - lap_p) * mask


# ---------------------------------------------------------------------------
#  Public V-cycle entry points
# ---------------------------------------------------------------------------


def vcycle_project_v(
    v: np.ndarray,
    pressure: np.ndarray,
    density: np.ndarray,
    mat: "CellMaterial",
    dt: float,
    mask_threshold: float,
    *,
    omega: float = 1.5,
    smooth_pre: int = 2,
    smooth_post: int = 2,
    coarse_iters: int = 8,
    n_cycles: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Drop-in replacement for ``_pressure_project_arrays`` using a V-cycle.

    Signature mirrors the single-grid solver so the integration in
    :py:meth:`PhysicsWorld._pressure_project_arrays` is a one-line branch.

    Parameters
    ----------
    v : (H, W, 2) float
        Combined velocity (``v[..., 0] = v_x``, ``v[..., 1] = v_y``).
    pressure : (H, W) float
        Current pressure field (used only for early-out / dimensions —
        the V-cycle restarts from zero like the single-grid path).
    density : (H, W) float
        Silhouette mass; cells with ``density < mask_threshold`` are
        treated as vacuum.
    mat : CellMaterial
        ``fluid_projection_iters`` controls how many V-cycles to run
        (``n_cycles = max(1, fluid_projection_iters // 4)``) when
        ``n_cycles`` is None.  Roughly maps a single-grid budget of
        4/8/12/16 iters → 1/2/3/4 V-cycles.
    dt, mask_threshold : float
        Same role as in the single-grid path.
    omega, smooth_pre, smooth_post, coarse_iters : numeric
        V-cycle knobs.  Defaults tuned for 32-cell hull grids.
    n_cycles : int | None
        Override the V-cycle count.  Default scales with
        ``fluid_projection_iters`` so the legacy "more iters = better
        convergence" intent carries through.
    """
    if n_cycles is None:
        budget = int(getattr(mat, "fluid_projection_iters", 0))
        if budget <= 0:
            return v, pressure
        # 4 single-grid sweeps ≈ 1 V-cycle on a 32-cell grid in raw work;
        # round up so the cheapest fluids still get one cycle.
        n_cycles = max(1, budget // 4)

    v = v.astype(np.float32, copy=True)
    pressure = pressure.astype(np.float32, copy=True)
    H, W = density.shape
    mask = (density >= mask_threshold).astype(np.float32, copy=False)
    m_l, m_r, m_t, m_b = _build_neighbour_masks(mask)

    v_x = v[..., 0]
    v_y = v[..., 1]

    # Backward-difference divergence with vacuum cells zero-padded —
    # exactly matches the single-grid path so RHS scale is identical.
    shifted = np.zeros_like(v_x)
    shifted[:, 1:] = v_x[:, :-1]
    v_x_l = shifted * m_l
    shifted = np.zeros_like(v_y)
    shifted[1:, :] = v_y[:-1, :]
    v_y_t = shifted * m_t
    div = (v_x - v_x_l) + (v_y - v_y_t)

    # Early-out (same threshold as single-grid).
    if float(np.abs(div).max()) < 1e-3:
        return v, pressure

    p = np.zeros((H, W), dtype=np.float32)
    # Solve ``Δp = +div`` to match the single-grid convention in
    # :py:meth:`PhysicsWorld._pressure_project_arrays`.
    #
    # Critical: the projected pressure is *persisted* into the cell
    # grid and re-used on the next frame as a body force
    # (``f -= grad p`` in ``_cpu_kernel``).  A previous version of
    # this routine solved ``Δp = -div`` and applied ``v += grad p``,
    # which is algebraically equivalent for the velocity update on
    # one step but flips the *sign* of the returned pressure field
    # versus the single-grid path.  Carrying a sign-flipped pressure
    # forward inverts next-frame's pressure-gradient force and
    # produces an artificial damping that suppresses water motion
    # in long runs (e.g. the multigrid water_container demo collapsed
    # peak |u_y| from ~170 to ~0.04).
    rhs_poisson = div.astype(np.float32, copy=True) * mask

    for _ in range(int(n_cycles)):
        p = _v_cycle(
            p, rhs_poisson, mask, m_l, m_r, m_t, m_b,
            omega=omega,
            smooth_pre=smooth_pre,
            smooth_post=smooth_post,
            coarse_iters=coarse_iters,
        )

    # Forward-difference gradient — matches single-grid path so v
    # update is numerically equivalent at convergence.
    shifted = np.zeros_like(p)
    shifted[:, :-1] = p[:, 1:]
    p_r_arr = shifted * m_r
    shifted = np.zeros_like(p)
    shifted[:-1, :] = p[1:, :]
    p_b_arr = shifted * m_b
    # ``v -= grad(p)`` — paired with ``Δp = +div`` above, identical to
    # the single-grid path's projection direction.
    v_x_new = v_x - (p_r_arr - p)
    v_y_new = v_y - (p_b_arr - p)

    v_out = np.empty_like(v)
    v_out[..., 0] = v_x_new
    v_out[..., 1] = v_y_new

    outside = mask < 0.5
    v_out[outside] = 0.0
    # NaN guard — vacuum islands inside the mask can produce non-finite
    # residuals before the gradient subtraction wipes them out.  Same
    # invariant as the single-grid path: never persist NaNs.
    v_out = np.nan_to_num(v_out, nan=0.0, posinf=0.0, neginf=0.0)
    p_out = p.copy()
    p_out[outside] = 0.0
    p_out = np.nan_to_num(p_out, nan=0.0, posinf=0.0, neginf=0.0)
    return v_out, p_out


def vcycle_project(
    u_x: np.ndarray,
    u_y: np.ndarray,
    v_x: np.ndarray,
    v_y: np.ndarray,
    pressure: np.ndarray,
    density: np.ndarray,
    mask: np.ndarray,
    dt: float,
    omega: float = 1.5,
    smooth_pre: int = 2,
    smooth_post: int = 2,
    coarse_iters: int = 8,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """V-cycle pressure projection on staggered (u, v) inputs.

    Convenience signature used in the design doc and in unit tests where
    callers want to keep their displacement/velocity components split.
    Internally folds (v_x, v_y) into the combined-velocity layout and
    delegates to :func:`vcycle_project_v`.

    Returns
    -------
    (v_x_new, v_y_new, pressure)
        Projected velocity components and the solved pressure field.
        ``u_x``/``u_y`` are inputs only — the V-cycle does not change
        displacement (the caller is expected to advect with the
        projected ``v``).
    """
    H, W = density.shape
    v_combined = np.empty((H, W, 2), dtype=np.float32)
    v_combined[..., 0] = v_x
    v_combined[..., 1] = v_y
    # Bridge mask back to a synthetic density that triggers the same
    # threshold check inside vcycle_project_v: any cell where mask>=0.5
    # is fluid, otherwise vacuum.  This keeps both call styles consistent.
    synth_density = mask.astype(np.float32) * np.float32(1.0)

    # Build a minimal-shape stand-in for CellMaterial so we can reuse the
    # main entry without forcing callers to import the dataclass.
    class _MatStub:
        fluid_projection_iters = max(1, smooth_pre + smooth_post + coarse_iters)
        is_fluid = True
        density_rho = 1.0
    stub = _MatStub()

    v_out, p_out = vcycle_project_v(
        v_combined, pressure, synth_density, stub, dt, mask_threshold=0.5,
        omega=omega, smooth_pre=smooth_pre, smooth_post=smooth_post,
        coarse_iters=coarse_iters, n_cycles=1,
    )
    return v_out[..., 0].copy(), v_out[..., 1].copy(), p_out


# ---------------------------------------------------------------------------
#  Core V-cycle
# ---------------------------------------------------------------------------


def _v_cycle(
    p: np.ndarray,
    rhs: np.ndarray,
    mask: np.ndarray,
    m_l: np.ndarray,
    m_r: np.ndarray,
    m_t: np.ndarray,
    m_b: np.ndarray,
    *,
    omega: float,
    smooth_pre: int,
    smooth_post: int,
    coarse_iters: int,
) -> np.ndarray:
    """One V-cycle: pre-smooth → restrict → coarse-solve → prolong → post-smooth.

    Operates on the Poisson system ``Δp = rhs``.  Updates ``p`` in place
    (and returns it for chaining).
    """
    H, W = p.shape

    # 1. Pre-smooth on the fine grid.
    p = _sor_sweep(p, rhs, mask, m_l, m_r, m_t, m_b, smooth_pre, omega)

    # 2. Compute residual on the fine grid.
    residual = _compute_residual(p, rhs, mask, m_l, m_r, m_t, m_b)

    # If the fine grid is too small to coarsen sensibly (one of the
    # demos uses a 16×16 sub-hull), just do extra fine sweeps and exit.
    if H < 4 or W < 4 or (H % 2) or (W % 2):
        return _sor_sweep(
            p, rhs, mask, m_l, m_r, m_t, m_b, smooth_post, omega,
        )

    # 3. Restrict residual + mask to the coarse grid.
    rhs_coarse = _restrict_2x2(residual)
    mask_coarse = _restrict_mask(mask)
    m_l_c, m_r_c, m_t_c, m_b_c = _build_neighbour_masks(mask_coarse)

    # 4. Coarse solve (zero initial guess + many SOR sweeps).  The
    #    coarse grid is half the resolution so each sweep is 4× cheaper
    #    AND the long-wavelength modes of the fine grid become
    #    high-frequency modes here, which SOR damps in O(1) sweeps.
    p_coarse = np.zeros_like(rhs_coarse)
    # The residual on a cell-centred Poisson with grid spacing h has
    # the operator ``(1/h²) Δp = rhs``.  Restricting to spacing 2h gives
    # ``(1/(2h)²) Δp_c = rhs_c`` ⇒ the coarse RHS in the
    # *grid-spacing-independent* normalisation of our SOR sweep
    # (which solves ``p = (Σnb - rhs)/4`` so rhs absorbs ``h²``) needs
    # to be scaled by 4× to account for the doubled spacing.  Skipping
    # this scaling makes the correction undershoot by ~4× — fine for
    # convergence but slow.
    rhs_coarse_scaled = rhs_coarse * np.float32(4.0)
    p_coarse = _sor_sweep(
        p_coarse, rhs_coarse_scaled, mask_coarse,
        m_l_c, m_r_c, m_t_c, m_b_c, coarse_iters, omega,
    )

    # 5. Prolong correction back to the fine grid and add to p.
    correction = _prolong_bilinear(p_coarse, (H, W))
    correction *= mask  # don't push vacuum cells off zero.
    p += correction

    # 6. Post-smooth.
    p = _sor_sweep(p, rhs, mask, m_l, m_r, m_t, m_b, smooth_post, omega)
    return p
