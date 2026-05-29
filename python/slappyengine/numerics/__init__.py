"""Generic numerical primitives.

This package gives long-lived, reusable numerical kernels a clean home,
decoupled from any particular physics flavour. Today it ships a single
public entry point — a 2-D multigrid V-cycle for the Poisson equation —
that will eventually back inflated-softbody pressure projection and any
future heat-equation work.

`vcycle_poisson(rhs, mask, iters_per_level=2, levels=3) -> solution`
--------------------------------------------------------------------
Solves the discrete 5-point Poisson system ``Δp = rhs`` on a regular
cell-centred grid with a binary fluid/vacuum mask. ``Δ`` is the standard
``p_l + p_r + p_t + p_b - 4·p`` stencil restricted to live cells; vacuum
cells contribute nothing to neighbour sums and are clamped to zero.

The solver is a classic recursive multigrid V-cycle:

1. Pre-smooth ``iters_per_level`` Red-Black SOR sweeps on the fine grid.
2. Compute the residual ``r = rhs - Δp``.
3. Restrict ``r`` and the mask to a 2×-coarser grid (block-mean / block-max).
4. Recursively solve the coarse correction problem (down to ``levels`` deep
   or until the grid becomes too small / odd to coarsen).
5. Prolong the coarse correction back via bilinear up-sampling and apply.
6. Post-smooth another ``iters_per_level`` Red-Black SOR sweeps.

The implementation is intentionally self-contained — it does not import
from ``slappyengine.physics`` so it can survive Phase D's strip pass and
serve as the canonical Poisson solver going forward.

Algorithm provenance
--------------------
Lifted from the working core of
``slappyengine.physics.pressure_multigrid``'s ``vcycle_project_v`` so
behaviour parity is exact for matching inputs (see
``test_numerics_vcycle.py::test_cross_check_against_physics_module``).
"""
from __future__ import annotations

import numpy as np

from ._validation import (
    validate_2d_array,
    validate_matching_shape,
    validate_omega,
    validate_positive_float,
    validate_positive_int,
)


__all__ = ["vcycle_poisson", "sor_smooth", "compute_residual"]


# ---------------------------------------------------------------------------
# Grid transfer operators (2× cell-centred restriction / bilinear prolong)
# ---------------------------------------------------------------------------


def _restrict_2x2(field: np.ndarray) -> np.ndarray:
    """Average 2×2 blocks: ``(H, W) → (H//2, W//2)``.

    Full-weighting restriction on a cell-centred grid. Single
    ``reshape + mean`` — no Python loop.
    """
    H, W = field.shape
    return field.reshape(H // 2, 2, W // 2, 2).mean(axis=(1, 3))


def _restrict_mask(mask: np.ndarray) -> np.ndarray:
    """Coarse mask = ``max`` over each 2×2 block.

    A coarse cell counts as fluid if *any* of its four fine children is
    fluid. Using ``max`` rather than ``mean`` keeps thin one-cell-wide
    features alive on the coarse grid where averaging would erode them
    below the 0.5 threshold the smoother expects.
    """
    H, W = mask.shape
    return mask.reshape(H // 2, 2, W // 2, 2).max(axis=(1, 3))


def _prolong_bilinear(coarse: np.ndarray, fine_shape: tuple[int, int]) -> np.ndarray:
    """Bilinear up-sample ``(Hc, Wc) → (Hf, Wf)`` with ``Hf == 2·Hc``.

    Uses ``np.repeat`` for the 2× nearest-neighbour step, then averages
    with one-cell-shifted copies along each axis — equivalent to bilinear
    interpolation on a cell-centred grid and faster than a fixed-factor
    call out to ``scipy.ndimage.zoom``.
    """
    Hf, Wf = fine_shape
    Hc, Wc = coarse.shape
    assert Hf == 2 * Hc and Wf == 2 * Wc, (
        f"prolong needs 2x factor, got coarse {Hc}x{Wc} → fine {Hf}x{Wf}"
    )
    nn = np.repeat(np.repeat(coarse, 2, axis=0), 2, axis=1)
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
# Red-Black SOR smoother on the 5-point Poisson operator
# ---------------------------------------------------------------------------


def _build_neighbour_masks(mask: np.ndarray) -> tuple[np.ndarray, ...]:
    """Pre-shift the binary mask once, return ``(left, right, top, bottom)``.

    Each shifted mask is zero where the corresponding neighbour is vacuum
    or off-grid, so neighbour sums implicitly enforce the no-flux boundary
    without per-cell branching in the smoother.
    """
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
    """Red-Black SOR sweeps on ``Δp = rhs`` — ``iters`` complete passes.

    Each pass updates the "red" sub-lattice then the "black" sub-lattice
    using the Jacobi-style relaxation ``p ← (Σ neighbours − rhs) / 4``
    weighted by the over-relaxation factor ``omega``. The inner loop
    allocates zero temporaries — neighbour sums accumulate into a
    pre-allocated ``nb_sum`` scratch using ``out=`` and in-place ops.

    Modifies and returns ``p``.
    """
    if iters <= 0:
        return p
    omega32 = np.float32(omega)
    yy, xx = np.indices(p.shape)
    red_w = (((yy + xx) % 2 == 0).astype(np.float32) * mask) * omega32
    black_w = (((yy + xx) % 2 == 1).astype(np.float32) * mask) * omega32
    nb_sum = np.empty_like(p)
    for _ in range(iters):
        # Red sweep — gather neighbours → in-place SOR update.
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
    """Residual ``r = rhs − Δp`` on the masked 5-point operator.

    With ``Δp[i,j] = p_l + p_r + p_t + p_b − 4·p[i,j]`` the residual is
    exactly what a V-cycle restricts to the coarse grid. Zero in vacuum.
    """
    nb_sum = np.zeros_like(p)
    nb_sum[:, 1:] += p[:, :-1] * m_l[:, 1:]
    nb_sum[:, :-1] += p[:, 1:] * m_r[:, :-1]
    nb_sum[1:, :] += p[:-1, :] * m_t[1:, :]
    nb_sum[:-1, :] += p[1:, :] * m_b[:-1, :]
    lap_p = nb_sum - np.float32(4.0) * p
    return (rhs - lap_p) * mask


# ---------------------------------------------------------------------------
# Recursive V-cycle
# ---------------------------------------------------------------------------


def _can_coarsen(shape: tuple[int, int]) -> bool:
    """A grid can be coarsened if both dims are even and ≥ 4."""
    H, W = shape
    return H >= 4 and W >= 4 and (H % 2 == 0) and (W % 2 == 0)


def _v_cycle(
    p: np.ndarray,
    rhs: np.ndarray,
    mask: np.ndarray,
    *,
    omega: float,
    iters_per_level: int,
    levels: int,
    coarse_iters: int,
) -> np.ndarray:
    """Single recursive V-cycle on ``Δp = rhs``.

    Pre-smooth → restrict residual → recurse → prolong correction →
    post-smooth. Bottoms out when either ``levels`` drops to 1 OR the
    grid is too small / odd to coarsen further; either way the bottom
    level falls back to a pure SOR solve with ``coarse_iters`` sweeps.
    """
    m_l, m_r, m_t, m_b = _build_neighbour_masks(mask)

    # 1. Pre-smooth.
    p = _sor_sweep(p, rhs, mask, m_l, m_r, m_t, m_b, iters_per_level, omega)

    # Bottom level: just smooth more and return.
    if levels <= 1 or not _can_coarsen(p.shape):
        return _sor_sweep(p, rhs, mask, m_l, m_r, m_t, m_b, coarse_iters, omega)

    # 2. Residual on fine grid.
    residual = _compute_residual(p, rhs, mask, m_l, m_r, m_t, m_b)

    # 3. Restrict residual + mask to the coarse grid.
    rhs_coarse = _restrict_2x2(residual)
    mask_coarse = _restrict_mask(mask)

    # 4. Recurse on the coarse correction problem (zero initial guess).
    # Scale RHS by 4× to account for the doubled grid spacing — the
    # discrete Laplacian (1/h²)·Δ absorbs h² into RHS in our normalisation,
    # and 2h → 4·h². Skipping this scaling makes the correction undershoot
    # by ~4× — still converges but slow.
    p_coarse = np.zeros_like(rhs_coarse)
    rhs_coarse_scaled = rhs_coarse * np.float32(4.0)
    p_coarse = _v_cycle(
        p_coarse,
        rhs_coarse_scaled,
        mask_coarse,
        omega=omega,
        iters_per_level=iters_per_level,
        levels=levels - 1,
        coarse_iters=coarse_iters,
    )

    # 5. Prolong correction back to fine + apply (vacuum cells unchanged).
    correction = _prolong_bilinear(p_coarse, p.shape)
    correction *= mask
    p += correction

    # 6. Post-smooth.
    p = _sor_sweep(p, rhs, mask, m_l, m_r, m_t, m_b, iters_per_level, omega)
    return p


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def vcycle_poisson(
    rhs: np.ndarray,
    mask: np.ndarray | None = None,
    iters_per_level: int = 2,
    levels: int = 3,
    *,
    n_cycles: int = 1,
    omega: float = 1.5,
    coarse_iters: int = 8,
    initial: np.ndarray | None = None,
    smooth_pre: int | None = None,
    smooth_post: int | None = None,
) -> np.ndarray:
    """Solve ``Δp = rhs`` with ``n_cycles`` multigrid V-cycles.

    Generic 2-D Poisson solver on a cell-centred grid with a binary
    fluid/vacuum mask. Pure numpy — no scipy / no Rust / no GPU.

    Parameters
    ----------
    rhs : ``(H, W)`` float
        Right-hand side. Values in vacuum cells are ignored (masked out
        before the first sweep) so callers don't have to zero them.
    mask : ``(H, W)`` bool or float
        Live-cell mask. Truthy ≥ 0.5 → fluid (solved for); else vacuum
        (clamped to zero, no contribution to neighbours).
    iters_per_level : int, default 2
        Red-Black SOR sweeps before AND after the recursive correction
        at each level (so 2·``iters_per_level`` per level per cycle).
    levels : int, default 3
        Maximum coarsening depth. Coarsening also stops automatically
        when the grid becomes too small (< 4 cells) or odd in either
        dimension.
    n_cycles : int, default 1, keyword-only
        Number of V-cycles. Each cycle roughly halves the residual on
        the long-wavelength modes; 2-3 cycles are usually plenty.
    omega : float, default 1.5, keyword-only
        SOR over-relaxation factor. 1.0 = Gauss-Seidel; 1.5 is near-
        optimal for the 5-point Laplacian on grids up to ~64²; values
        > 1.9 destabilise.
    coarse_iters : int, default 8, keyword-only
        SOR sweeps at the bottom of the V (where coarsening stopped). On
        a small coarse grid SOR damps all remaining error modes cheaply.
    initial : ``(H, W)`` float or ``None``, keyword-only
        Optional warm-start guess. Default zero — matches the
        single-grid path. Passed a previous solution to converge faster
        on tightly correlated frames.

    Returns
    -------
    p : ``(H, W)`` float32
        Approximate solution; vacuum cells exactly zero. NaN / ±inf are
        scrubbed so the caller can safely persist the field across frames.

    Raises
    ------
    TypeError
        If ``rhs`` is not a 2-D numpy ndarray, or ``mask`` / ``initial``
        are non-ndarray when provided, or ``iters_per_level`` / ``levels``
        / ``n_cycles`` are not integers, or ``omega`` is not a real number.
    ValueError
        If ``rhs`` is not 2-D, ``mask`` / ``initial`` shapes do not match
        ``rhs``, the iteration counters are < 1, or ``omega`` is non-finite
        or outside ``(0, 2)``.
    """
    rhs = validate_2d_array("rhs", "vcycle_poisson", rhs)
    if mask is not None:
        validate_matching_shape("mask", "vcycle_poisson", mask, rhs.shape)
    # Back-compat: legacy callers pass smooth_pre / smooth_post explicitly
    # (separate pre/post smoothers). The unified V-cycle uses one
    # iters_per_level setting; take the max so the smoothing effort
    # matches or exceeds the legacy intent.
    if smooth_pre is not None or smooth_post is not None:
        iters_per_level = max(
            int(iters_per_level),
            int(smooth_pre or 0),
            int(smooth_post or 0),
        )
    iters_per_level = validate_positive_int(
        "iters_per_level", "vcycle_poisson", iters_per_level,
    )
    levels = validate_positive_int("levels", "vcycle_poisson", levels)
    n_cycles = validate_positive_int("n_cycles", "vcycle_poisson", n_cycles)
    omega = validate_omega("vcycle_poisson", omega)

    if mask is None:
        mask_f = np.ones(rhs.shape, dtype=np.float32)
    else:
        mask_f = (np.asarray(mask) >= 0.5).astype(np.float32, copy=False)
    rhs_f = np.asarray(rhs, dtype=np.float32) * mask_f

    if initial is None:
        p = np.zeros(rhs.shape, dtype=np.float32)
    else:
        validate_matching_shape("initial", "vcycle_poisson", initial, rhs.shape)
        p = np.asarray(initial, dtype=np.float32).copy() * mask_f

    for _ in range(int(n_cycles)):
        p = _v_cycle(
            p,
            rhs_f,
            mask_f,
            omega=omega,
            iters_per_level=iters_per_level,
            levels=levels,
            coarse_iters=coarse_iters,
        )

    outside = mask_f < 0.5
    p[outside] = 0.0
    p = np.nan_to_num(p, nan=0.0, posinf=0.0, neginf=0.0)
    return p


# ---------------------------------------------------------------------------
# Public smoother / residual entry points
# ---------------------------------------------------------------------------


def sor_smooth(
    p: np.ndarray,
    rhs: np.ndarray,
    iters: int = 1,
    omega: float = 1.5,
    *,
    mask: np.ndarray | None = None,
) -> np.ndarray:
    """Run ``iters`` Red-Black SOR sweeps on ``Δp = rhs``.

    Public wrapper around the internal Red-Black SOR smoother. Mutates
    and returns ``p`` so it can be chained. Pure numpy.

    Parameters
    ----------
    p : ``(H, W)`` float
        Current pressure / solution estimate. Mutated in place.
    rhs : ``(H, W)`` float
        Right-hand side. Must have the same shape as ``p``.
    iters : int, default 1
        Number of full Red-Black sweeps to perform. Must be ≥ 1.
    omega : float, default 1.5
        SOR over-relaxation factor. Must be in ``(0, 2)``.
    mask : ``(H, W)`` bool or float, optional
        Live-cell mask. Defaults to all-ones (every cell solved for).

    Returns
    -------
    p : ``(H, W)`` float
        The mutated solution buffer.

    Raises
    ------
    TypeError
        If ``p`` or ``rhs`` is not a numpy ndarray, or ``iters`` is not an
        integer, or ``omega`` is not a real number.
    ValueError
        If shapes mismatch, ``iters < 1``, or ``omega`` is outside
        ``(0, 2)``.
    """
    p = validate_2d_array("p", "sor_smooth", p)
    rhs = validate_matching_shape("rhs", "sor_smooth", rhs, p.shape)
    iters = validate_positive_int("iters", "sor_smooth", iters)
    omega = validate_omega("sor_smooth", omega)

    if mask is None:
        mask_f = np.ones(p.shape, dtype=np.float32)
    else:
        validate_matching_shape("mask", "sor_smooth", mask, p.shape)
        mask_f = (np.asarray(mask) >= 0.5).astype(np.float32, copy=False)

    p32 = p.astype(np.float32, copy=False)
    rhs32 = (np.asarray(rhs, dtype=np.float32) * mask_f)
    m_l, m_r, m_t, m_b = _build_neighbour_masks(mask_f)
    _sor_sweep(p32, rhs32, mask_f, m_l, m_r, m_t, m_b, iters, omega)
    return p32


def compute_residual(
    p: np.ndarray,
    rhs: np.ndarray,
    *,
    mask: np.ndarray | None = None,
) -> np.ndarray:
    """Return ``rhs − Δp`` on the masked 5-point Laplacian.

    Public wrapper around the internal residual kernel.

    Parameters
    ----------
    p : ``(H, W)`` float
        Current solution estimate.
    rhs : ``(H, W)`` float
        Right-hand side; must match ``p`` in shape.
    mask : ``(H, W)`` bool or float, optional
        Live-cell mask; defaults to all-ones.

    Returns
    -------
    residual : ``(H, W)`` float32
        Residual array. Zero outside the live mask.

    Raises
    ------
    TypeError
        If ``p`` or ``rhs`` is not a numpy ndarray.
    ValueError
        If ``p`` is not 2-D, or ``rhs`` / ``mask`` shapes do not match
        ``p``.
    """
    p = validate_2d_array("p", "compute_residual", p)
    rhs = validate_matching_shape("rhs", "compute_residual", rhs, p.shape)

    if mask is None:
        mask_f = np.ones(p.shape, dtype=np.float32)
    else:
        validate_matching_shape("mask", "compute_residual", mask, p.shape)
        mask_f = (np.asarray(mask) >= 0.5).astype(np.float32, copy=False)

    p32 = p.astype(np.float32, copy=False)
    rhs32 = (np.asarray(rhs, dtype=np.float32) * mask_f)
    m_l, m_r, m_t, m_b = _build_neighbour_masks(mask_f)
    return _compute_residual(p32, rhs32, mask_f, m_l, m_r, m_t, m_b)
