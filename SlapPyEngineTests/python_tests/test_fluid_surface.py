"""Tests for the marching-squares surface-extraction foundation.

These are correctness tests for the algorithm (does it produce a
connected isoline of the right shape?), independent of the
yet-to-be-built surface renderer.
"""
from __future__ import annotations

import warnings

import numpy as np
import pytest

from slappyengine.fluid.surface import (
    compute_density_normals,
    extract_isolines,
    sample_density_grid,
    slerp_normals,
)


@pytest.fixture(autouse=True)
def _no_runtime_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error", category=RuntimeWarning)
        yield


def _sample_circle_density(
    centre: tuple[float, float],
    n_particles: int,
    radius: float,
    kernel_radius: float,
    grid_origin: tuple[float, float],
    n_cells: tuple[int, int],
    cell_size: float,
) -> np.ndarray:
    """Helper: place `n_particles` uniformly inside a disc, sample density."""
    rng = np.random.default_rng(1234)
    # Uniform-in-disc via sqrt sampling
    r = radius * np.sqrt(rng.random(n_particles, dtype=np.float64))
    theta = 2.0 * np.pi * rng.random(n_particles, dtype=np.float64)
    px = centre[0] + r * np.cos(theta)
    py = centre[1] + r * np.sin(theta)
    pos = np.stack([px, py], axis=1).astype(np.float32)
    return sample_density_grid(pos, None, kernel_radius, grid_origin, n_cells, cell_size)


def test_density_grid_is_nonzero_where_particles_are():
    pos = np.array([[1.0, 1.0]], dtype=np.float32)
    g = sample_density_grid(
        pos, None, kernel_radius=0.3,
        origin=(0.0, 0.0), n_cells=(10, 10), cell_size=0.2,
    )
    assert g.shape == (10, 10)
    # Particle is at (1, 1); cell index (5, 5) covers x=[1.0, 1.2), y=[1.0, 1.2).
    # Density at that cell should be > 0.
    assert g[5, 5] > 0.0
    # Cells far from the particle should be zero.
    assert g[0, 0] == 0.0
    assert g[9, 9] == 0.0


def test_density_grid_sums_more_with_more_particles():
    centre = (1.0, 1.0)
    g1 = _sample_circle_density(centre, 50, radius=0.3,
                                 kernel_radius=0.4,
                                 grid_origin=(0.0, 0.0), n_cells=(20, 20),
                                 cell_size=0.1)
    g2 = _sample_circle_density(centre, 200, radius=0.3,
                                 kernel_radius=0.4,
                                 grid_origin=(0.0, 0.0), n_cells=(20, 20),
                                 cell_size=0.1)
    assert g2.sum() > g1.sum() * 1.5, "4× particles should give substantially higher integrated density"


def test_marching_squares_closed_circle():
    """A circular density blob produces a near-closed polyline."""
    centre = (1.0, 1.0)
    g = _sample_circle_density(centre, 400, radius=0.3,
                                kernel_radius=0.25,
                                grid_origin=(0.0, 0.0), n_cells=(40, 40),
                                cell_size=0.05)
    iso = g.max() * 0.3
    segments = extract_isolines(g, iso, origin=(0.0, 0.0), cell_size=0.05)

    assert segments.shape[1:] == (2, 2)
    n_seg = segments.shape[0]
    assert n_seg > 12, f"expected a meaningful isoline contour, got {n_seg} segments"

    # All vertices should be close-ish to the original circle radius.
    verts = segments.reshape(-1, 2)
    dx = verts[:, 0] - centre[0]
    dy = verts[:, 1] - centre[1]
    r = np.sqrt(dx * dx + dy * dy)
    # Expected isoline radius is somewhere inside [0.0, radius+h]; just check
    # that all vertices live in a plausible annulus.
    assert (r > 0.05).all(), "all vertices too close to centre"
    assert (r < 0.6).all(), f"isoline blew up: max r={r.max():.3f}"

    # The contour should be approximately closed: every vertex appears as the
    # start of one segment and the end of another (within a small tolerance).
    starts = segments[:, 0]
    ends = segments[:, 1]
    # Each end should have a near-by start
    start_kd = starts[None, :, :] - ends[:, None, :]
    dists = np.sqrt(np.einsum("ijk,ijk->ij", start_kd, start_kd))
    nearest = dists.min(axis=1)
    assert (nearest < 0.06).all(), (
        f"contour not closed; max end-to-start gap = {nearest.max():.3f}"
    )


def test_marching_squares_two_separate_blobs():
    """Two well-separated blobs produce two distinct isoline groups."""
    h = 0.25
    g_left = _sample_circle_density((0.6, 1.0), 200, radius=0.2,
                                     kernel_radius=h,
                                     grid_origin=(0.0, 0.0),
                                     n_cells=(40, 40), cell_size=0.05)
    g_right = _sample_circle_density((1.6, 1.0), 200, radius=0.2,
                                      kernel_radius=h,
                                      grid_origin=(0.0, 0.0),
                                      n_cells=(40, 40), cell_size=0.05)
    g = g_left + g_right
    iso = g.max() * 0.3
    segments = extract_isolines(g, iso, origin=(0.0, 0.0), cell_size=0.05)
    assert segments.shape[0] > 16

    # Bin segment midpoints by which blob's centre they're closer to.
    mids = 0.5 * (segments[:, 0] + segments[:, 1])
    left_count = int(np.sum(mids[:, 0] < 1.1))
    right_count = int(np.sum(mids[:, 0] >= 1.1))
    assert left_count > 4 and right_count > 4, (
        f"both blobs should have non-trivial isolines: L={left_count} R={right_count}"
    )


def test_normals_point_radially_outward_on_circle():
    centre = (1.0, 1.0)
    g = _sample_circle_density(centre, 500, radius=0.3,
                                kernel_radius=0.25,
                                grid_origin=(0.0, 0.0), n_cells=(40, 40),
                                cell_size=0.05)
    iso = g.max() * 0.3
    segments = extract_isolines(g, iso, origin=(0.0, 0.0), cell_size=0.05)
    verts = segments.reshape(-1, 2)
    normals = compute_density_normals(g, verts, origin=(0.0, 0.0), cell_size=0.05)
    assert normals.shape == verts.shape

    # Radial direction from blob centre to vertex
    rx = verts[:, 0] - centre[0]
    ry = verts[:, 1] - centre[1]
    rmag = np.sqrt(rx * rx + ry * ry)
    keep = rmag > 1.0e-3
    rx = rx[keep] / rmag[keep]
    ry = ry[keep] / rmag[keep]
    nx = normals[keep, 0]
    ny = normals[keep, 1]

    # Cosine of angle between (computed normal) and (radial outward direction).
    cos_t = rx * nx + ry * ny
    # Majority of normals should point outward (cos > 0). Tolerance for cells
    # where the gradient is noisy at the contour edges.
    fraction_outward = float(np.mean(cos_t > 0.5))
    assert fraction_outward > 0.85, (
        f"normals not pointing outward: only {fraction_outward:.2%} agree with radial"
    )


def test_slerp_normals_endpoints():
    n_a = np.array([[1.0, 0.0]], dtype=np.float32)
    n_b = np.array([[0.0, 1.0]], dtype=np.float32)
    at_start = slerp_normals(n_a, n_b, 0.0)
    at_end = slerp_normals(n_a, n_b, 1.0)
    at_mid = slerp_normals(n_a, n_b, 0.5)
    assert np.allclose(at_start, n_a, atol=1.0e-5)
    assert np.allclose(at_end, n_b, atol=1.0e-5)
    # 45 degrees midpoint should be (cos45, sin45)
    s = float(np.sqrt(0.5))
    assert np.allclose(at_mid[0], [s, s], atol=1.0e-4)


def test_slerp_normals_small_angle_uses_linear_fallback():
    n_a = np.array([[1.0, 0.0]], dtype=np.float32)
    n_b = np.array([[1.0, 1.0e-6]], dtype=np.float32)
    # Should not error and should return a finite, unit-magnitude vector.
    out = slerp_normals(n_a, n_b, 0.5)
    assert np.all(np.isfinite(out))
    mag = float(np.linalg.norm(out))
    assert abs(mag - 1.0) < 1.0e-3


def test_empty_input_returns_empty_arrays():
    g = sample_density_grid(
        np.zeros((0, 2), dtype=np.float32), None,
        kernel_radius=0.2, origin=(0.0, 0.0),
        n_cells=(10, 10), cell_size=0.1,
    )
    assert g.shape == (10, 10)
    assert float(g.sum()) == 0.0

    segs = extract_isolines(g, 1.0, origin=(0.0, 0.0), cell_size=0.1)
    assert segs.shape == (0, 2, 2)

    normals = compute_density_normals(g, np.zeros((0, 2), dtype=np.float32),
                                       origin=(0.0, 0.0), cell_size=0.1)
    assert normals.shape == (0, 2)
