"""Marching-squares surface extraction for PBF particle fields.

Given a particle set with positions, produces a 2D density grid via the
existing poly6 kernel, then extracts an isoline of constant density. The
output is a `(M, 2, 2)` array of line segments — each segment is
`[[start_x, start_y], [end_x, end_y]]`. A higher-level renderer connects
segments into closed polylines and shades them (see `fluid/render.py`'s
upcoming surface mode).

Math + 16-case table referenced in `docs/fluid_design.md` § Surface.
"""
from __future__ import annotations

import numpy as np

# Native-Rust poly6 splat. Falls back to the numpy implementation if the
# extension hasn't been built. The flag follows the same pattern used in
# ``fluid/render.py`` (HAS_NATIVE_FLUID_SHADER).
try:
    from slappyengine import _core as _native_core  # type: ignore
    _HAS_NATIVE_DENSITY_GRID = hasattr(_native_core, "sample_density_grid_rs")
    _HAS_NATIVE_EXTRACT_ISOLINES = hasattr(_native_core, "extract_isolines_rs")
except ImportError:  # pragma: no cover
    _native_core = None  # type: ignore
    _HAS_NATIVE_DENSITY_GRID = False
    _HAS_NATIVE_EXTRACT_ISOLINES = False

# Marching-squares case → edge-pair list.
# Corner-bit packing: bit 0 = BL, bit 1 = BR, bit 2 = TR, bit 3 = TL.
# Edge indices: 0 = bottom (BL→BR), 1 = right (BR→TR), 2 = top (TR→TL),
#               3 = left (TL→BL).
# Each tuple is an unordered (edge_a, edge_b) line segment.
EDGE_TABLE: tuple[tuple[tuple[int, int], ...], ...] = (
    (),                       # 0  ____
    ((3, 0),),                # 1  BL
    ((0, 1),),                # 2  BR
    ((3, 1),),                # 3  BL+BR
    ((1, 2),),                # 4  TR
    ((3, 0), (1, 2)),         # 5  BL+TR  (saddle)
    ((0, 2),),                # 6  BR+TR
    ((3, 2),),                # 7  BL+BR+TR
    ((2, 3),),                # 8  TL
    ((0, 2),),                # 9  BL+TL
    ((0, 1), (2, 3)),         # 10 BR+TL  (saddle)
    ((1, 2),),                # 11 BL+BR+TL
    ((3, 1),),                # 12 TR+TL
    ((0, 1),),                # 13 BL+TR+TL
    ((0, 3),),                # 14 BR+TR+TL
    (),                       # 15 XXXX
)


def _poly6_coefficient_2d(h: float) -> float:
    return 4.0 / (np.pi * (h ** 8))


def sample_density_grid(
    positions: np.ndarray,
    masses: np.ndarray | None,
    kernel_radius: float,
    origin: tuple[float, float],
    n_cells: tuple[int, int],
    cell_size: float,
) -> np.ndarray:
    """Sample particles into a (ny, nx) density grid using the 2D poly6 kernel.

    Parameters
    ----------
    positions : (N, 2) array of particle positions.
    masses    : (N,) array of particle masses, or `None` for uniform mass 1.
    kernel_radius : `h` in the poly6 formula. Set to the PBF kernel radius
        (the value used during simulation).
    origin    : world-space (x, y) of the grid's lower-left cell corner.
    n_cells   : (nx, ny) grid resolution.
    cell_size : world-space cell side length.

    Returns
    -------
    density : (ny, nx) float32 array. `density[j, i]` is the kernel-summed
        density at the *centre* of cell `(i, j)`.
    """
    nx, ny = int(n_cells[0]), int(n_cells[1])
    n_pts = int(positions.shape[0]) if positions.size else 0
    if n_pts == 0:
        return np.zeros((ny, nx), dtype=np.float32)

    if masses is None:
        m_arr = np.ones(n_pts, dtype=np.float32)
    else:
        m_arr = np.asarray(masses, dtype=np.float32)
        if m_arr.shape[0] != n_pts:
            raise ValueError("masses must match positions length")

    ox, oy = float(origin[0]), float(origin[1])
    h = float(kernel_radius)

    if _HAS_NATIVE_DENSITY_GRID:
        pos_f32 = np.ascontiguousarray(positions, dtype=np.float32)
        grid_ba = bytearray(nx * ny * 4)
        _native_core.sample_density_grid_rs(
            pos_f32.tobytes(), m_arr.tobytes(), grid_ba,
            int(nx), int(ny),
            float(ox), float(oy),
            float(h), float(cell_size),
        )
        return np.frombuffer(bytes(grid_ba), dtype=np.float32).reshape(ny, nx).copy()

    grid = np.zeros((ny, nx), dtype=np.float32)
    h2 = h * h
    coef = _poly6_coefficient_2d(h)

    px = positions[:, 0].astype(np.float32, copy=False) - ox
    py = positions[:, 1].astype(np.float32, copy=False) - oy
    cx = np.floor(px / cell_size).astype(np.int32)
    cy = np.floor(py / cell_size).astype(np.int32)

    r_cells = int(np.ceil(h / cell_size)) + 1

    for dx in range(-r_cells, r_cells + 1):
        for dy in range(-r_cells, r_cells + 1):
            tx = cx + dx
            ty = cy + dy
            valid = (tx >= 0) & (tx < nx) & (ty >= 0) & (ty < ny)
            if not np.any(valid):
                continue
            tx_v = tx[valid]
            ty_v = ty[valid]
            m_v = m_arr[valid]
            wx = ox + (tx_v.astype(np.float32) + 0.5) * cell_size
            wy = oy + (ty_v.astype(np.float32) + 0.5) * cell_size
            dxw = wx - positions[valid, 0].astype(np.float32, copy=False)
            dyw = wy - positions[valid, 1].astype(np.float32, copy=False)
            r2 = dxw * dxw + dyw * dyw
            inside = r2 < h2
            if not np.any(inside):
                continue
            r2_i = r2[inside]
            tx_i = tx_v[inside]
            ty_i = ty_v[inside]
            m_i = m_v[inside]
            k = (coef * (h2 - r2_i) ** 3).astype(np.float32) * m_i
            np.add.at(grid, (ty_i, tx_i), k.astype(np.float32))

    return grid


def _interp_vertex(
    edge_idx: int,
    cell_x: np.ndarray,
    cell_y: np.ndarray,
    density: np.ndarray,
    isovalue: float,
    origin: tuple[float, float],
    cell_size: float,
) -> np.ndarray:
    """Linear interpolation on a marching-squares cell edge.

    Returns (N, 2) world-space vertex positions.
    """
    ox, oy = float(origin[0]), float(origin[1])
    bl_x = ox + cell_x.astype(np.float32) * cell_size
    bl_y = oy + cell_y.astype(np.float32) * cell_size
    eps = np.float32(1.0e-9)

    if edge_idx == 0:
        v0 = density[cell_y, cell_x]
        v1 = density[cell_y, cell_x + 1]
        denom = v1 - v0
        t = np.where(np.abs(denom) < eps, 0.5, (isovalue - v0) / denom)
        return np.stack([bl_x + t * cell_size, bl_y], axis=1).astype(np.float32)
    if edge_idx == 1:
        v0 = density[cell_y, cell_x + 1]
        v1 = density[cell_y + 1, cell_x + 1]
        denom = v1 - v0
        t = np.where(np.abs(denom) < eps, 0.5, (isovalue - v0) / denom)
        return np.stack([bl_x + cell_size, bl_y + t * cell_size], axis=1).astype(np.float32)
    if edge_idx == 2:
        v0 = density[cell_y + 1, cell_x + 1]
        v1 = density[cell_y + 1, cell_x]
        denom = v1 - v0
        t = np.where(np.abs(denom) < eps, 0.5, (isovalue - v0) / denom)
        return np.stack([bl_x + cell_size - t * cell_size, bl_y + cell_size], axis=1).astype(np.float32)
    if edge_idx == 3:
        v0 = density[cell_y + 1, cell_x]
        v1 = density[cell_y, cell_x]
        denom = v1 - v0
        t = np.where(np.abs(denom) < eps, 0.5, (isovalue - v0) / denom)
        return np.stack([bl_x, bl_y + cell_size - t * cell_size], axis=1).astype(np.float32)
    raise ValueError(f"edge_idx must be 0..3, got {edge_idx}")


def extract_isolines(
    density: np.ndarray,
    isovalue: float,
    origin: tuple[float, float],
    cell_size: float,
) -> np.ndarray:
    """Run marching squares and return line segments crossing the isovalue.

    Returns an `(M, 2, 2)` float32 array. `out[k, 0]` is the segment's
    start vertex (x, y); `out[k, 1]` is the end vertex.
    """
    ny, nx = density.shape
    if nx < 2 or ny < 2:
        return np.zeros((0, 2, 2), dtype=np.float32)

    if _HAS_NATIVE_EXTRACT_ISOLINES:
        ox, oy = float(origin[0]), float(origin[1])
        density_bytes = np.ascontiguousarray(density, dtype=np.float32).tobytes()
        raw = _native_core.extract_isolines_rs(
            density_bytes, int(nx), int(ny),
            float(isovalue), float(ox), float(oy), float(cell_size),
        )
        if not raw:
            return np.zeros((0, 2, 2), dtype=np.float32)
        # raw is bytes of (M*4) f32; reshape (M, 2, 2).
        flat = np.frombuffer(raw, dtype=np.float32)
        m = flat.size // 4
        return flat.reshape(m, 2, 2).copy()

    bl = density[:-1, :-1] >= isovalue
    br = density[:-1, 1:] >= isovalue
    tr = density[1:, 1:] >= isovalue
    tl = density[1:, :-1] >= isovalue

    case = (
        bl.astype(np.uint8)
        | (br.astype(np.uint8) << 1)
        | (tr.astype(np.uint8) << 2)
        | (tl.astype(np.uint8) << 3)
    )

    out: list[np.ndarray] = []
    for code in range(16):
        edges = EDGE_TABLE[code]
        if not edges:
            continue
        ys, xs = np.nonzero(case == code)
        if xs.size == 0:
            continue
        cell_x = xs.astype(np.int32)
        cell_y = ys.astype(np.int32)
        for (e_a, e_b) in edges:
            a = _interp_vertex(e_a, cell_x, cell_y, density, isovalue, origin, cell_size)
            b = _interp_vertex(e_b, cell_x, cell_y, density, isovalue, origin, cell_size)
            seg = np.stack([a, b], axis=1)  # (N, 2, 2)
            out.append(seg)
    if not out:
        return np.zeros((0, 2, 2), dtype=np.float32)
    return np.concatenate(out, axis=0).astype(np.float32)


def compute_density_normals(
    density: np.ndarray,
    vertices: np.ndarray,
    origin: tuple[float, float],
    cell_size: float,
) -> np.ndarray:
    """Outward-pointing surface normals at given world-space vertices.

    Normal direction is opposite to ∇density (gradient points "into" the
    high-density region). For a circular blob, all normals point radially
    outward.

    Parameters
    ----------
    density : (ny, nx) scalar field.
    vertices : (M, 2) world-space query points.
    origin, cell_size : same grid frame as `sample_density_grid`.

    Returns
    -------
    normals : (M, 2) float32 unit vectors. Returns `(0, 1)` for vertices
        falling outside the grid (rare, harmless).
    """
    if vertices.shape[0] == 0:
        return np.zeros((0, 2), dtype=np.float32)
    ny, nx = density.shape
    ox, oy = float(origin[0]), float(origin[1])
    eps = np.float32(1.0e-9)

    # Central differences of the density field
    grad_x = np.zeros_like(density, dtype=np.float32)
    grad_y = np.zeros_like(density, dtype=np.float32)
    grad_x[:, 1:-1] = (density[:, 2:] - density[:, :-2]) * (0.5 / cell_size)
    grad_y[1:-1, :] = (density[2:, :] - density[:-2, :]) * (0.5 / cell_size)

    # Bilinear sample of (grad_x, grad_y) at the vertex positions
    vx = (vertices[:, 0] - ox) / cell_size - 0.5
    vy = (vertices[:, 1] - oy) / cell_size - 0.5
    i0 = np.clip(np.floor(vx).astype(np.int32), 0, nx - 2)
    j0 = np.clip(np.floor(vy).astype(np.int32), 0, ny - 2)
    i1 = i0 + 1
    j1 = j0 + 1
    fx = (vx - i0).astype(np.float32)
    fy = (vy - j0).astype(np.float32)

    def _sample(field: np.ndarray) -> np.ndarray:
        return (
            field[j0, i0] * ((1.0 - fx) * (1.0 - fy))
            + field[j0, i1] * (fx * (1.0 - fy))
            + field[j1, i0] * ((1.0 - fx) * fy)
            + field[j1, i1] * (fx * fy)
        )

    gx = _sample(grad_x)
    gy = _sample(grad_y)
    # Surface normal points OUT of the fluid: opposite to density gradient.
    nx_v = -gx
    ny_v = -gy
    mag = np.sqrt(nx_v * nx_v + ny_v * ny_v)
    safe = mag > eps
    n = np.zeros((vertices.shape[0], 2), dtype=np.float32)
    n[:, 1] = -1.0  # fallback "up" in y-down convention
    n[safe, 0] = (nx_v[safe] / mag[safe]).astype(np.float32)
    n[safe, 1] = (ny_v[safe] / mag[safe]).astype(np.float32)
    return n


def slerp_normals(n_a: np.ndarray, n_b: np.ndarray, t: np.ndarray | float) -> np.ndarray:
    """Spherical linear interpolation between unit 2D normals.

    Falls back to linear interpolation when the angle between `n_a` and
    `n_b` is small (numerically equivalent and avoids division by zero).
    """
    a = np.asarray(n_a, dtype=np.float32)
    b = np.asarray(n_b, dtype=np.float32)
    if a.ndim == 1:
        a = a[None, :]
    if b.ndim == 1:
        b = b[None, :]
    t_arr = np.asarray(t, dtype=np.float32)
    if t_arr.ndim == 0:
        t_arr = np.full(a.shape[0], float(t_arr), dtype=np.float32)
    dot = np.clip(np.einsum("ij,ij->i", a, b), -1.0, 1.0)
    theta = np.arccos(dot)
    small = theta < 1.0e-4
    sin_t = np.sin(theta)
    # Use linear for nearly-parallel pairs (small angle), slerp otherwise.
    w_a = np.where(small, 1.0 - t_arr, np.sin((1.0 - t_arr) * theta) / np.maximum(sin_t, 1.0e-9))
    w_b = np.where(small, t_arr,       np.sin(t_arr * theta)       / np.maximum(sin_t, 1.0e-9))
    out = (a * w_a[:, None] + b * w_b[:, None]).astype(np.float32)
    # Re-normalise (safety against accumulated float error)
    mag = np.sqrt(np.einsum("ij,ij->i", out, out))
    safe = mag > 1.0e-9
    out[safe] = out[safe] / mag[safe, None]
    return out


__all__ = [
    "EDGE_TABLE",
    "compute_density_normals",
    "extract_isolines",
    "sample_density_grid",
    "slerp_normals",
]
