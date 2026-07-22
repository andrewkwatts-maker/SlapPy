//! Hot-path PBF (position-based fluids) kernels.
//!
//! Two functions are exposed:
//! * [`build_neighbour_table`] — spatial-hash 9-cell neighbour gather.
//!   Mirrors `_build_neighbour_table` in `python/slappyengine/fluid/solver.py`
//!   but skips the all-Python numpy chain.
//! * [`pbf_iter`] — one iteration of the density-constraint projection
//!   (poly6 / spiky_grad / density / lambda / delta_p). Runs `iters *
//!   substeps` times per frame (typically 32x).
//!
//! Position arrays arrive as a writable `Bound<PyByteArray>` so we mutate
//! in place — no copy back. Read-only arrays arrive as `&[u8]`
//! reinterpreted via `bytemuck::cast_slice`.
//!
//! **Precision contract:** PBF positions are reset every substep via the
//! prediction step (`pos = prev_pos + vel*dt`), so the float-summation
//! order of the density accumulator isn't part of a long error chain.
//! This means we can use straight sequential `bincount`-style scatter
//! (one pass appending per particle) — the same drift the
//! pure-Python `np.bincount` path already tolerated upstream.

use bytemuck::cast_slice;
use pyo3::prelude::*;
use pyo3::types::{PyByteArray, PyBytes};
use rayon::prelude::*;
use std::f32::consts::PI;
use wide::{f32x4, CmpGe, CmpGt, CmpLt};

// Per-element work thresholds below which the rayon overhead exceeds the
// gain in PBF kernels. ``pbf_iter`` runs 32x per step so its threshold
// is tuned carefully — only pay the dispatch cost when there's bulk
// work.
//
// Tier-8-cleanup tuning: even the 30x20 = 600-particle test (≈10k pairs
// after the 9-cell gather) stays serial — at that scale the per-call
// inner work is on the order of rayon's dispatch cost. Larger scenes
// (5k+ particles, 100k+ pairs) cross the thresholds and benefit from
// the parallel split. The SIMD pre-pass in pbf_iter still runs on every
// call regardless of the parallel gate, so smaller scenes still benefit
// from the f32x4 inner loop.
const PARALLEL_PARTICLE_MIN: usize = 4096;
const PARALLEL_PAIR_MIN: usize = 65536;

#[inline(always)]
fn poly6_coefficient(h: f32) -> f32 {
    // 4 / (pi * h^8)
    let h2 = h * h;
    let h4 = h2 * h2;
    let h8 = h4 * h4;
    4.0 / (PI * h8)
}

#[inline(always)]
fn spiky_grad_coefficient(h: f32) -> f32 {
    // -30 / (pi * h^5)
    let h2 = h * h;
    let h4 = h2 * h2;
    let h5 = h4 * h;
    -30.0 / (PI * h5)
}

/// Build the neighbour table for PBF using a spatial hash + 9-cell gather.
///
/// `pos_bytes` is `(N, 2)` row-major f32 bytes. `h` is the kernel radius
/// (cell size = h). Returns `(i_idx, j_idx)` as Python `bytes` objects
/// that contain packed `int64` values — the caller wraps these with
/// `np.frombuffer(..., dtype=np.int64)`.
///
/// Pairs are filtered by `i != j` and `r2 < h*h`; the order of pairs
/// is the same emit order as the Python implementation (sorted by own
/// cell key, then by 9-cell offset).
#[pyfunction]
pub fn build_neighbour_table(
    py: Python<'_>,
    pos_bytes: &[u8],
    h: f32,
    n: usize,
) -> PyResult<(PyObject, PyObject)> {
    if n == 0 {
        let empty = PyBytes::new_bound(py, &[]);
        return Ok((empty.clone().into(), empty.into()));
    }
    let pos: &[f32] = cast_slice(pos_bytes);
    if pos.len() < n * 2 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "pos buffer too small",
        ));
    }

    let inv_cell = 1.0f32 / h;
    let h2 = h * h;

    // Compute per-particle cell indices.
    let mut ix = vec![0i64; n];
    let mut iy = vec![0i64; n];
    for i in 0..n {
        ix[i] = (pos[2 * i] * inv_cell).floor() as i64;
        iy[i] = (pos[2 * i + 1] * inv_cell).floor() as i64;
    }

    // Hash each particle into a 64-bit key.
    const P1: i64 = 73856093;
    const P2: i64 = 19349663;
    let mut own_key = vec![0i64; n];
    for i in 0..n {
        own_key[i] = ix[i].wrapping_mul(P1) ^ iy[i].wrapping_mul(P2);
    }

    // Stable sort by own_key — record the order permutation.
    let mut order: Vec<usize> = (0..n).collect();
    order.sort_by(|&a, &b| own_key[a].cmp(&own_key[b]));
    let mut key_sorted = vec![0i64; n];
    for k in 0..n {
        key_sorted[k] = own_key[order[k]];
    }

    // For each particle, search each of the 9 neighbouring cell keys
    // in the sorted key array via binary search (matches Python's
    // np.searchsorted approach).
    let offsets: [(i64, i64); 9] = [
        (-1, -1), (-1, 0), (-1, 1),
        ( 0, -1), ( 0, 0), ( 0, 1),
        ( 1, -1), ( 1, 0), ( 1, 1),
    ];

    let mut i_out: Vec<i64> = Vec::new();
    let mut j_out: Vec<i64> = Vec::new();

    if n >= PARALLEL_PARTICLE_MIN {
        // Chunked parallel neighbour gather. Each chunk emits one flat
        // (i_idx, j_idx) buffer pair to minimise allocation pressure
        // compared to a per-particle Vec<Vec>. Chunks are processed in
        // increasing particle-index order so the merged output matches
        // the serial loop's emit order.
        let n_threads = rayon::current_num_threads().max(1);
        let chunk_size = ((n + (n_threads * 4) - 1) / (n_threads * 4)).max(256);
        let chunk_starts: Vec<usize> = (0..n).step_by(chunk_size).collect();
        type Chunk = (Vec<i64>, Vec<i64>);
        let chunks: Vec<Chunk> = chunk_starts
            .par_iter()
            .map(|&start| {
                let end = (start + chunk_size).min(n);
                let approx_cap = (end - start) * 32;
                let mut li: Vec<i64> = Vec::with_capacity(approx_cap);
                let mut lj: Vec<i64> = Vec::with_capacity(approx_cap);
                for i in start..end {
                    let pxi = pos[2 * i];
                    let pyi = pos[2 * i + 1];
                    let cx = ix[i];
                    let cy = iy[i];
                    for &(ox, oy) in offsets.iter() {
                        let qx = cx + ox;
                        let qy = cy + oy;
                        let qkey = qx.wrapping_mul(P1) ^ qy.wrapping_mul(P2);
                        let lo = key_sorted.partition_point(|&k| k < qkey);
                        let hi = key_sorted.partition_point(|&k| k <= qkey);
                        for k in lo..hi {
                            let j = order[k];
                            if j == i {
                                continue;
                            }
                            let dx = pxi - pos[2 * j];
                            let dy = pyi - pos[2 * j + 1];
                            let r2 = dx * dx + dy * dy;
                            if r2 < h2 {
                                li.push(i as i64);
                                lj.push(j as i64);
                            }
                        }
                    }
                }
                (li, lj)
            })
            .collect();
        let total: usize = chunks.iter().map(|c| c.0.len()).sum();
        i_out.reserve(total);
        j_out.reserve(total);
        for (li, lj) in chunks.into_iter() {
            i_out.extend_from_slice(&li);
            j_out.extend_from_slice(&lj);
        }
    } else {
        // Serial path — reserve ~32 neighbours per particle (matches the
        // original capacity hint) and inline the gather.
        i_out.reserve(n * 32);
        j_out.reserve(n * 32);
        for i in 0..n {
            let pxi = pos[2 * i];
            let pyi = pos[2 * i + 1];
            let cx = ix[i];
            let cy = iy[i];
            for &(ox, oy) in offsets.iter() {
                let qx = cx + ox;
                let qy = cy + oy;
                let qkey = qx.wrapping_mul(P1) ^ qy.wrapping_mul(P2);
                let lo = key_sorted.partition_point(|&k| k < qkey);
                let hi = key_sorted.partition_point(|&k| k <= qkey);
                for k in lo..hi {
                    let j = order[k];
                    if j == i {
                        continue;
                    }
                    let dx = pxi - pos[2 * j];
                    let dy = pyi - pos[2 * j + 1];
                    let r2 = dx * dx + dy * dy;
                    if r2 < h2 {
                        i_out.push(i as i64);
                        j_out.push(j as i64);
                    }
                }
            }
        }
    }

    // Cast to bytes — pyo3's PyBytes::new_bound copies, but it's a one-shot
    // O(pairs * 8) memcpy which is fast.
    let i_bytes: &[u8] = cast_slice(&i_out);
    let j_bytes: &[u8] = cast_slice(&j_out);
    let i_py = PyBytes::new_bound(py, i_bytes);
    let j_py = PyBytes::new_bound(py, j_bytes);
    Ok((i_py.into(), j_py.into()))
}

/// One iteration of the PBF density-constraint projection.
///
/// Performs:
///   1. delta_ij = pos[i] - pos[j]; r = |delta|
///   2. w_ij = poly6(r^2, h);  density[i] += sum_j mass[j] * w_ij + self
///   3. c_i = max(density/rho0 - 1, density_floor)
///   4. grad_ij = spiky_grad(delta, r, h) / rho0
///   5. denom = sum_grad_self^2 + sum_grad_neighbour_sq + relax
///   6. lambda_i = -c_i / max(denom, eps)
///   7. delta_p[i] += grad_ij * (lam[i] + lam[j] + s_corr_ij)
///   8. pos += delta_p (in place)
///
/// `pos_xy` is `(N, 2)` f32 (writable bytearray). `mass_bytes` is `(N,)`
/// f32. `i_idx`/`j_idx` are `(P,)` int64 bytes (packed). Constants
/// `poly6_coef = 4/(pi h^8)` and `spiky_coef = -30/(pi h^5)` are recomputed
/// in Rust to avoid Python overhead.
///
/// Boundary projection (clamping to floor/ceiling/walls) is left to the
/// Python wrapper — it's cheap and stays out of this kernel.
#[pyfunction]
#[pyo3(signature = (pos_xy, mass_bytes, i_idx, j_idx, h, rho0, relax, eps, density_floor, cohesion_on, k_corr, n_corr, dq_w))]
#[allow(clippy::too_many_arguments)]
pub fn pbf_iter(
    pos_xy: &Bound<'_, PyByteArray>,
    mass_bytes: &[u8],
    i_idx: &[u8],
    j_idx: &[u8],
    h: f32,
    rho0: f32,
    relax: f32,
    eps: f32,
    density_floor: f32,
    cohesion_on: bool,
    k_corr: f32,
    n_corr: f32,
    dq_w: f32,
) -> PyResult<()> {
    let mass: &[f32] = cast_slice(mass_bytes);
    let i_arr: &[i64] = cast_slice(i_idx);
    let j_arr: &[i64] = cast_slice(j_idx);
    let n = mass.len();
    if i_arr.len() != j_arr.len() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "i_idx/j_idx length mismatch",
        ));
    }
    let n_pairs = i_arr.len();

    // Safety: GIL is held throughout.
    let pos_bytes: &mut [u8] = unsafe { pos_xy.as_bytes_mut() };
    if pos_bytes.len() < n * 2 * 4 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "pos buffer too small",
        ));
    }
    let pos: &mut [f32] = bytemuck::cast_slice_mut(pos_bytes);

    let inv_rho0 = 1.0f32 / rho0.max(eps);
    let h2 = h * h;
    let poly6_coef = poly6_coefficient(h);
    let spiky_coef = spiky_grad_coefficient(h);

    // Self contribution: poly6(0, h) = (4 / (pi h^8)) * (h^2)^3 = 4 / (pi h^2)
    // (the Python form is `poly6_coefficient(h) * (h^2)^3`).
    let self_w0 = poly6_coef * (h2 * h2 * h2);

    // Per-pair scratch buffers.
    // We compute w_ij, grad_x, grad_y, r once and reuse for the
    // delta_p accumulation. n_pairs * 16 bytes is fine for ~10k pairs.
    let mut w_ij = vec![0.0f32; n_pairs];
    let mut grad_x = vec![0.0f32; n_pairs];
    let mut grad_y = vec![0.0f32; n_pairs];

    // density[i] = self_w0 * mass[i] + sum_j mass[j] * w_ij.
    // Use f64 accumulators to match the numpy fallback (which goes through
    // `np.bincount(weights=float32, minlength=n)` returning float64).
    // Densely-packed particles have ~20-30 neighbours contributing summed
    // floats of the same magnitude, so f32 drift would shift c_i by
    // a few %, enough to bias the sand pile dynamics.
    let mut density = vec![0.0f64; n];
    for i in 0..n {
        density[i] = (self_w0 * mass[i]) as f64;
    }

    // grad sums per particle (also f64 to match bincount path).
    let mut sgs_x = vec![0.0f64; n];
    let mut sgs_y = vec![0.0f64; n];
    let mut sum_grad_neighbour_sq = vec![0.0f64; n];

    let denom_w = dq_w.max(eps);

    // SIMD-vectorised per-pair compute (Tier 9): walks the pair list in
    // chunks of 4 producing `w_ij[p]`, `grad_x[p]`, `grad_y[p]`. Reads
    // from `pos` (read-only snapshot) — fully parallel-safe across
    // chunks. Branches in the scalar form (`if r2 < h2`, `if r > 0`)
    // are converted to lane masks and blends so the same f32 ops happen
    // on every lane.
    //
    // Precision: the lane-by-lane math reproduces the scalar code
    // op-for-op (subtraction, mul, sqrt, max, div) so each lane is
    // bit-identical to the scalar output. The serial scatter into
    // density / sgs / sum_grad_neighbour_sq that follows is unaffected.
    let h2_v = f32x4::splat(h2);
    let h_v = f32x4::splat(h);
    let eps_v = f32x4::splat(eps);
    let inv_rho0_v = f32x4::splat(inv_rho0);
    let poly6_v = f32x4::splat(poly6_coef);
    let spiky_v = f32x4::splat(spiky_coef);
    let zero_v = f32x4::splat(0.0);

    let compute_pair_chunk = |start: usize,
                              w_chunk: &mut [f32],
                              gx_chunk: &mut [f32],
                              gy_chunk: &mut [f32]| {
        let chunk_len = w_chunk.len();
        let mut k = 0;
        while k + 4 <= chunk_len {
            let p0 = start + k;
            let i0 = i_arr[p0] as usize;
            let i1 = i_arr[p0 + 1] as usize;
            let i2 = i_arr[p0 + 2] as usize;
            let i3 = i_arr[p0 + 3] as usize;
            let j0 = j_arr[p0] as usize;
            let j1 = j_arr[p0 + 1] as usize;
            let j2 = j_arr[p0 + 2] as usize;
            let j3 = j_arr[p0 + 3] as usize;

            let pix = f32x4::from([pos[2 * i0], pos[2 * i1], pos[2 * i2], pos[2 * i3]]);
            let piy = f32x4::from([pos[2 * i0 + 1], pos[2 * i1 + 1], pos[2 * i2 + 1], pos[2 * i3 + 1]]);
            let pjx = f32x4::from([pos[2 * j0], pos[2 * j1], pos[2 * j2], pos[2 * j3]]);
            let pjy = f32x4::from([pos[2 * j0 + 1], pos[2 * j1 + 1], pos[2 * j2 + 1], pos[2 * j3 + 1]]);

            let dx = pix - pjx;
            let dy = piy - pjy;
            let r2 = dx * dx + dy * dy;

            // w = if (r2 < h2 && r2 >= 0) poly6 * (h2 - r2)^3 else 0
            let diff = h2_v - r2;
            let w_full = poly6_v * diff * diff * diff;
            let mask_w = r2.cmp_lt(h2_v) & r2.cmp_ge(zero_v);
            let w = mask_w.blend(w_full, zero_v);

            let r = r2.sqrt();
            let safe_r = r.max(eps_v);
            // factor = if (r > 0 && r < h) spiky * (h - r)^2 / safe_r else 0
            let dh = h_v - r;
            let factor_full = spiky_v * dh * dh / safe_r;
            let mask_f = r.cmp_gt(zero_v) & r.cmp_lt(h_v);
            let factor = mask_f.blend(factor_full, zero_v);

            let gx = dx * factor * inv_rho0_v;
            let gy = dy * factor * inv_rho0_v;

            let w_arr = w.to_array();
            let gx_arr = gx.to_array();
            let gy_arr = gy.to_array();
            w_chunk[k]     = w_arr[0];
            w_chunk[k + 1] = w_arr[1];
            w_chunk[k + 2] = w_arr[2];
            w_chunk[k + 3] = w_arr[3];
            gx_chunk[k]     = gx_arr[0];
            gx_chunk[k + 1] = gx_arr[1];
            gx_chunk[k + 2] = gx_arr[2];
            gx_chunk[k + 3] = gx_arr[3];
            gy_chunk[k]     = gy_arr[0];
            gy_chunk[k + 1] = gy_arr[1];
            gy_chunk[k + 2] = gy_arr[2];
            gy_chunk[k + 3] = gy_arr[3];
            k += 4;
        }
        // Scalar tail.
        while k < chunk_len {
            let p = start + k;
            let i = i_arr[p] as usize;
            let j = j_arr[p] as usize;
            let dx = pos[2 * i] - pos[2 * j];
            let dy = pos[2 * i + 1] - pos[2 * j + 1];
            let r2 = dx * dx + dy * dy;
            let w = if r2 < h2 && r2 >= 0.0 {
                let diff = h2 - r2;
                poly6_coef * diff * diff * diff
            } else {
                0.0
            };
            let r = r2.sqrt();
            let safe_r = r.max(eps);
            let factor = if r > 0.0 && r < h {
                let dh = h - r;
                spiky_coef * dh * dh / safe_r
            } else {
                0.0
            };
            w_chunk[k] = w;
            gx_chunk[k] = dx * factor * inv_rho0;
            gy_chunk[k] = dy * factor * inv_rho0;
            k += 1;
        }
    };

    if n_pairs >= PARALLEL_PAIR_MIN {
        // Pass 1a: parallel SIMD compute of w_ij / grad_x / grad_y.
        // Read-only on ``pos`` — parallel-safe.
        let n_threads = rayon::current_num_threads().max(1);
        let chunk_size = ((n_pairs + (n_threads * 4) - 1)
            / (n_threads * 4))
            .max(512);
        // Round chunk to a multiple of 4 so SIMD lanes never straddle a
        // chunk boundary (avoids redundant scalar-tail work per chunk).
        let chunk_size = ((chunk_size + 3) / 4) * 4;
        w_ij.par_chunks_mut(chunk_size)
            .zip(grad_x.par_chunks_mut(chunk_size))
            .zip(grad_y.par_chunks_mut(chunk_size))
            .enumerate()
            .for_each(|(chunk_idx, ((w_chunk, gx_chunk), gy_chunk))| {
                let start = chunk_idx * chunk_size;
                compute_pair_chunk(start, w_chunk, gx_chunk, gy_chunk);
            });
    } else {
        // Serial SIMD compute — one chunk covering the full pair list.
        compute_pair_chunk(0, &mut w_ij[..], &mut grad_x[..], &mut grad_y[..]);
    }

    // Pass 1b: serial scatter into density / sgs / sum_grad_neighbour_sq.
    // Precision-sensitive (f64 accumulators, order matters for
    // bincount-equivalent output) — must stay serial.
    for p in 0..n_pairs {
        let i = i_arr[p] as usize;
        let j = j_arr[p] as usize;
        debug_assert!(i < n && j < n);
        let w = w_ij[p];
        let gx = grad_x[p];
        let gy = grad_y[p];
        density[i] += (mass[j] * w) as f64;
        sgs_x[i] += gx as f64;
        sgs_y[i] += gy as f64;
        sum_grad_neighbour_sq[i] += (gx * gx + gy * gy) as f64;
    }

    // Pass 2: compute lambda per particle. Match numpy's float64-thru-cast:
    // density is cast back to f32 first, c_i in f32, then divisions in f64
    // (numpy's bincount-returned grad sums are float64).
    let mut lam = vec![0.0f32; n];
    let relax_64 = relax as f64;
    let eps_64 = eps as f64;
    for i in 0..n {
        let density_f32 = density[i] as f32;
        let c_i = ((density_f32 * inv_rho0) - 1.0).max(density_floor) as f64;
        let sgsx = sgs_x[i];
        let sgsy = sgs_y[i];
        let sum_grad_sq = sgsx * sgsx + sgsy * sgsy;
        let denom = (sum_grad_sq + sum_grad_neighbour_sq[i] + relax_64).max(eps_64);
        lam[i] = (-c_i / denom) as f32;
    }

    // Pass 3: scatter delta_p = grad * (lam[i] + lam[j] + s_corr_ij).
    // Accumulate in f64 (matches numpy's bincount path).
    let mut dp_x = vec![0.0f64; n];
    let mut dp_y = vec![0.0f64; n];
    if cohesion_on {
        for p in 0..n_pairs {
            let i = i_arr[p] as usize;
            let j = j_arr[p] as usize;
            let base_ratio = (w_ij[p] / denom_w).max(0.0);
            let s_corr_ij = -k_corr * base_ratio.powf(n_corr);
            let mult = (lam[i] + lam[j] + s_corr_ij) as f64;
            dp_x[i] += (grad_x[p] as f64) * mult;
            dp_y[i] += (grad_y[p] as f64) * mult;
        }
    } else {
        for p in 0..n_pairs {
            let i = i_arr[p] as usize;
            let j = j_arr[p] as usize;
            let mult = (lam[i] + lam[j]) as f64;
            dp_x[i] += (grad_x[p] as f64) * mult;
            dp_y[i] += (grad_y[p] as f64) * mult;
        }
    }

    // Apply delta_p in place to pos. The f64 → f32 cast matches numpy's
    // `delta_p.astype(np.float32)` step.
    for i in 0..n {
        pos[2 * i] += dp_x[i] as f32;
        pos[2 * i + 1] += dp_y[i] as f32;
    }

    Ok(())
}

/// Granular Coulomb-friction position correction over neighbour pairs.
///
/// Walks the masked pair list (`i_idx[p], j_idx[p]` for the granular
/// overlap subset) in order, computing a tangential position correction
/// and applying it sequentially to `pos_xy` — mirroring the
/// `np.add.at(pos, ii, corr_i)` / `np.add.at(pos, jj, corr_j)` pattern
/// in `fluid/solver.py::friction_pass`. Sequential scatter (rather than
/// fused bincount) is necessary because the same particle index appears
/// many times across pairs and the order-dependent f32 accumulation
/// shifts the final pile shape enough to swing the granular tests.
///
/// `pos_xy` is `(N, 2)` row-major f32, writable. All other arrays are
/// read-only `&[u8]` blocks reinterpreted via `bytemuck::cast_slice`.
/// `material_id` is `(N,)` u8 (matches `ParticleSoA.material_id`).
/// `mu_lookup` is `(M,)` f32 where `M = len(world.materials)`.
/// `i_idx`/`j_idx` are `(P,)` int64 pairs from the neighbour table.
#[pyfunction]
#[pyo3(signature = (pos_xy, prev_pos_xy, inv_mass, material_id, is_granular, mu_lookup, i_idx, j_idx, contact_radius, eps, tan_eps, dt_scale, normal_proxy_floor_factor))]
#[allow(clippy::too_many_arguments)]
pub fn friction_pass_rs(
    pos_xy: &Bound<'_, PyByteArray>,
    prev_pos_xy: &[u8],
    inv_mass: &[u8],
    material_id: &[u8],
    is_granular: &[u8],
    mu_lookup: &[u8],
    i_idx: &[u8],
    j_idx: &[u8],
    contact_radius: f32,
    eps: f32,
    tan_eps: f32,
    dt_scale: f32,
    normal_proxy_floor_factor: f32,
) -> PyResult<()> {
    let prev_pos: &[f32] = cast_slice(prev_pos_xy);
    let inv_m: &[f32] = cast_slice(inv_mass);
    let mat_id: &[u8] = material_id; // u8 directly
    let gran: &[u8] = is_granular;   // 0/1 per material
    let mu_tab: &[f32] = cast_slice(mu_lookup);
    let i_arr: &[i64] = cast_slice(i_idx);
    let j_arr: &[i64] = cast_slice(j_idx);

    let n = inv_m.len();
    if i_arr.len() != j_arr.len() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "i_idx/j_idx length mismatch",
        ));
    }
    let n_pairs = i_arr.len();

    // Safety: GIL is held throughout.
    let pos_bytes: &mut [u8] = unsafe { pos_xy.as_bytes_mut() };
    if pos_bytes.len() < n * 2 * 4 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "pos buffer too small",
        ));
    }
    let pos: &mut [f32] = bytemuck::cast_slice_mut(pos_bytes);
    if prev_pos.len() < n * 2 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "prev_pos buffer too small",
        ));
    }
    if mat_id.len() < n {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "material_id buffer too small",
        ));
    }

    let normal_proxy_floor = normal_proxy_floor_factor * contact_radius;
    let contact_r2 = contact_radius * contact_radius;
    let eps2 = eps * eps;

    for p in 0..n_pairs {
        let i = i_arr[p] as usize;
        let j = j_arr[p] as usize;
        // Mirror Python's `pair_mask = is_gran[i] & is_gran[j] & (i < j)`.
        if i >= j {
            continue;
        }
        let mi = mat_id[i] as usize;
        let mj = mat_id[j] as usize;
        if gran[mi] == 0 || gran[mj] == 0 {
            continue;
        }

        let dx = pos[2 * i] - pos[2 * j];
        let dy = pos[2 * i + 1] - pos[2 * j + 1];
        let r2 = dx * dx + dy * dy;
        // overlap_mask: r < contact_radius AND r > eps
        if r2 >= contact_r2 || r2 <= eps2 {
            continue;
        }
        let r = r2.sqrt();
        let inv_r = 1.0 / r;
        let nx = dx * inv_r;
        let ny = dy * inv_r;

        let rel_dx_x =
            (pos[2 * i] - prev_pos[2 * i]) - (pos[2 * j] - prev_pos[2 * j]);
        let rel_dx_y =
            (pos[2 * i + 1] - prev_pos[2 * i + 1]) - (pos[2 * j + 1] - prev_pos[2 * j + 1]);
        let rel_dot_n = rel_dx_x * nx + rel_dx_y * ny;
        let dx_t_x = rel_dx_x - nx * rel_dot_n;
        let dx_t_y = rel_dx_y - ny * rel_dot_n;
        let t_mag2 = dx_t_x * dx_t_x + dx_t_y * dx_t_y;
        if t_mag2 <= tan_eps * tan_eps {
            continue;
        }
        let t_mag = t_mag2.sqrt();

        let pen = contact_radius - r;
        let mu_pair = 0.5 * (mu_tab[mi] + mu_tab[mj]);
        let normal_proxy = pen + normal_proxy_floor;
        let cap = mu_pair * normal_proxy;
        let s = if t_mag < cap { t_mag } else { cap };
        let s = s * dt_scale;

        let inv_t = 1.0 / t_mag;
        let tdx = dx_t_x * inv_t;
        let tdy = dx_t_y * inv_t;

        let w_i = inv_m[i];
        let w_j = inv_m[j];
        let w_sum = w_i + w_j;
        let inv_w_sum = 1.0 / w_sum.max(eps);
        let cs_i = s * w_i * inv_w_sum;
        let cs_j = s * w_j * inv_w_sum;

        // pos[i] -= t_dir * cs_i; pos[j] += t_dir * cs_j
        // Cast through f32 to match `corr_i.astype(np.float32)` in numpy.
        pos[2 * i] -= tdx * cs_i;
        pos[2 * i + 1] -= tdy * cs_i;
        pos[2 * j] += tdx * cs_j;
        pos[2 * j + 1] += tdy * cs_j;
    }

    Ok(())
}

/// Thermal pass: pairwise heat exchange + ambient relaxation + phase
/// change flag pass.
///
/// Mirrors `fluid/thermal_step.py::thermal_step`. Position arrays are
/// shared bytearrays — temperature (writable f32) and material_id
/// (writable u8) — so this kernel mutates them in place. The Python
/// wrapper does the per-material lookup table assembly and the final
/// phase-change count tally.
///
/// Pair ordering: `T` is touched once per (active) pair with the same
/// scatter pattern as `np.subtract.at(T, ii, q/ma)` /
/// `np.add.at(T, jj, q/mb)`. Walking pairs in array order with a
/// single-element scatter mirrors that. Note however that the Python
/// version applies BOTH subtract.at(T,ii,...) and add.at(T,jj,...) as
/// SEPARATE passes over the same pair list — so a particle that is the
/// jj of an earlier pair sees its T updated BEFORE it gets subtracted
/// from as the ii of a later pair. We replicate this by doing two
/// passes: (1) compute and scatter subtract on T using i, (2) walk
/// pairs again and scatter add on T using j. The intermediate flux
/// `q` is recomputed via the *original* T values cached during pass 1.
#[pyfunction]
#[pyo3(signature = (
    temperature, material_id, mass_bytes, i_idx, j_idx,
    cond_lookup, ambient_lookup, melt_t_lookup, freeze_t_lookup,
    melt_to_lookup, freeze_to_lookup,
    sub_dt, diffusion_rate, ambient_rate))]
#[allow(clippy::too_many_arguments)]
pub fn thermal_step_rs(
    temperature: &Bound<'_, PyByteArray>,
    material_id: &Bound<'_, PyByteArray>,
    mass_bytes: &[u8],
    i_idx: &[u8],
    j_idx: &[u8],
    cond_lookup: &[u8],
    ambient_lookup: &[u8],
    melt_t_lookup: &[u8],
    freeze_t_lookup: &[u8],
    melt_to_lookup: &[u8],
    freeze_to_lookup: &[u8],
    sub_dt: f32,
    diffusion_rate: f32,
    ambient_rate: f32,
) -> PyResult<u32> {
    let mass: &[f32] = cast_slice(mass_bytes);
    let i_arr: &[i64] = cast_slice(i_idx);
    let j_arr: &[i64] = cast_slice(j_idx);
    let cond_tab: &[f32] = cast_slice(cond_lookup);
    let amb_tab: &[f32] = cast_slice(ambient_lookup);
    let melt_t_tab: &[f32] = cast_slice(melt_t_lookup);
    let freeze_t_tab: &[f32] = cast_slice(freeze_t_lookup);
    let melt_to_tab: &[i32] = cast_slice(melt_to_lookup);
    let freeze_to_tab: &[i32] = cast_slice(freeze_to_lookup);

    let n = mass.len();
    if i_arr.len() != j_arr.len() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "i_idx/j_idx length mismatch",
        ));
    }
    let n_pairs = i_arr.len();

    let temp_bytes: &mut [u8] = unsafe { temperature.as_bytes_mut() };
    if temp_bytes.len() < n * 4 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "temperature buffer too small",
        ));
    }
    let t_arr: &mut [f32] = bytemuck::cast_slice_mut(temp_bytes);

    let mat_bytes: &mut [u8] = unsafe { material_id.as_bytes_mut() };
    if mat_bytes.len() < n {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "material_id buffer too small",
        ));
    }

    // ── 1) Pairwise heat exchange ──────────────────────────────────────
    //
    // Python form (pair-wise):
    //   ka = cond[ids[i]]; kb = cond[ids[j]]
    //   active = (ka > 0) & (kb > 0)
    //   k_harm = 2*ka*kb / max(ka+kb, 1e-9)
    //   q = k_harm * (ta - tb) * diffusion_rate * sub_dt
    //   m_eff = 1/(1/ma + 1/mb) = ma*mb/(ma+mb)
    //   q_eq = (ta - tb) * m_eff
    //   q = clamp_to_eq(q, q_eq)   # min/max preserving sign of q_eq
    //   T[i] -= q/ma;  T[j] += q/mb
    //
    // The Python implementation first runs `subtract.at(T, ii, q/ma)`
    // (sequential, with q computed from a SNAPSHOT of T at the start
    // of the pass), then `add.at(T, jj, q/mb)` (also using the same
    // snapshot q). To match precisely we cache the original T into a
    // scratch buffer, then iterate pairs once and apply both ends.
    let mut n_changes: u32 = 0;

    if n_pairs > 0 {
        // Cache initial T — numpy uses `ta = T[ii]` / `tb = T[jj]` BEFORE
        // any scatter writes, so we need a frozen view.
        let mut t0 = vec![0.0f32; n];
        t0.copy_from_slice(&t_arr[..n]);

        let dr_dt = diffusion_rate * sub_dt;
        for p in 0..n_pairs {
            let i = i_arr[p] as usize;
            let j = j_arr[p] as usize;
            let mi = mat_bytes[i] as usize;
            let mj = mat_bytes[j] as usize;
            let ka = cond_tab[mi];
            let kb = cond_tab[mj];
            if !(ka > 0.0 && kb > 0.0) {
                continue;
            }
            let k_sum = (ka + kb).max(1.0e-9);
            let k_harm = 2.0 * ka * kb / k_sum;
            let ta = t0[i];
            let tb = t0[j];
            let dt_ab = ta - tb;
            let q_raw = k_harm * dt_ab * dr_dt;
            let ma = mass[i].max(1.0e-9);
            let mb = mass[j].max(1.0e-9);
            let m_eff = 1.0 / (1.0 / ma + 1.0 / mb);
            let q_eq = dt_ab * m_eff;
            let q = if q_eq >= 0.0 {
                q_raw.max(0.0).min(q_eq)
            } else {
                q_raw.min(0.0).max(q_eq)
            };
            // np.subtract.at on T[ii] then np.add.at on T[jj] — but since
            // those passes iterate the same pair list, a particle that
            // appears as both ii and jj across different pairs sees its
            // T mutated between events. We collapse that into a single
            // pair walk because the two passes are independent (q is
            // pre-snapshotted), so order-within-the-pair doesn't matter
            // for the final sum.
            t_arr[i] -= q / ma;
            t_arr[j] += q / mb;
        }
    }

    // ── 2) Ambient relaxation (implicit Euler) ─────────────────────────
    if ambient_rate > 0.0 && sub_dt > 0.0 {
        let ar_dt = ambient_rate * sub_dt;
        let denom = 1.0 + ar_dt;
        let inv_denom = 1.0 / denom;
        for i in 0..n {
            let mi = mat_bytes[i] as usize;
            let amb = amb_tab[mi];
            t_arr[i] = (t_arr[i] + ar_dt * amb) * inv_denom;
        }
    }

    // ── 3) Phase change ────────────────────────────────────────────────
    for i in 0..n {
        let mi = mat_bytes[i] as usize;
        let ti = t_arr[i];
        let mtarget = melt_to_tab[mi];
        let ftarget = freeze_to_tab[mi];
        if mtarget >= 0 && ti > melt_t_tab[mi] {
            mat_bytes[i] = mtarget as u8;
            n_changes += 1;
        } else if ftarget >= 0 && ti < freeze_t_tab[mi] {
            mat_bytes[i] = ftarget as u8;
            n_changes += 1;
        }
    }

    Ok(n_changes)
}

// ────────────────────────────────────────────────────────────────────────
// Tier 10: full PBF step in Rust.
//
// Moves `pbf_step()` from `python/slappyengine/fluid/solver.py` into a
// single PyO3 call to amortise per-iter dispatch overhead. The substep
// loop + per-substep iter loop run entirely native; only the
// boundary-clamp / damping / clamp-velocity passes happen here too.
// ────────────────────────────────────────────────────────────────────────

/// Build neighbour table directly into Vec<i64> buffers (no PyBytes).
fn build_neighbour_table_inner(pos: &[f32], n: usize, h: f32) -> (Vec<i64>, Vec<i64>) {
    if n == 0 {
        return (Vec::new(), Vec::new());
    }
    let inv_cell = 1.0f32 / h;
    let h2 = h * h;

    let mut ix = vec![0i64; n];
    let mut iy = vec![0i64; n];
    for i in 0..n {
        ix[i] = (pos[2 * i] * inv_cell).floor() as i64;
        iy[i] = (pos[2 * i + 1] * inv_cell).floor() as i64;
    }
    const P1: i64 = 73856093;
    const P2: i64 = 19349663;
    let mut own_key = vec![0i64; n];
    for i in 0..n {
        own_key[i] = ix[i].wrapping_mul(P1) ^ iy[i].wrapping_mul(P2);
    }
    let mut order: Vec<usize> = (0..n).collect();
    order.sort_by(|&a, &b| own_key[a].cmp(&own_key[b]));
    let mut key_sorted = vec![0i64; n];
    for k in 0..n {
        key_sorted[k] = own_key[order[k]];
    }
    let offsets: [(i64, i64); 9] = [
        (-1, -1), (-1, 0), (-1, 1),
        ( 0, -1), ( 0, 0), ( 0, 1),
        ( 1, -1), ( 1, 0), ( 1, 1),
    ];
    let mut i_out: Vec<i64> = Vec::with_capacity(n * 32);
    let mut j_out: Vec<i64> = Vec::with_capacity(n * 32);
    if n >= PARALLEL_PARTICLE_MIN {
        let n_threads = rayon::current_num_threads().max(1);
        let chunk_size = ((n + (n_threads * 4) - 1) / (n_threads * 4)).max(256);
        let chunk_starts: Vec<usize> = (0..n).step_by(chunk_size).collect();
        type Chunk = (Vec<i64>, Vec<i64>);
        let chunks: Vec<Chunk> = chunk_starts
            .par_iter()
            .map(|&start| {
                let end = (start + chunk_size).min(n);
                let approx_cap = (end - start) * 32;
                let mut li: Vec<i64> = Vec::with_capacity(approx_cap);
                let mut lj: Vec<i64> = Vec::with_capacity(approx_cap);
                for i in start..end {
                    let pxi = pos[2 * i];
                    let pyi = pos[2 * i + 1];
                    let cx = ix[i];
                    let cy = iy[i];
                    for &(ox, oy) in offsets.iter() {
                        let qx = cx + ox;
                        let qy = cy + oy;
                        let qkey = qx.wrapping_mul(P1) ^ qy.wrapping_mul(P2);
                        let lo = key_sorted.partition_point(|&k| k < qkey);
                        let hi = key_sorted.partition_point(|&k| k <= qkey);
                        for k in lo..hi {
                            let j = order[k];
                            if j == i { continue; }
                            let dx = pxi - pos[2 * j];
                            let dy = pyi - pos[2 * j + 1];
                            let r2 = dx * dx + dy * dy;
                            if r2 < h2 {
                                li.push(i as i64);
                                lj.push(j as i64);
                            }
                        }
                    }
                }
                (li, lj)
            })
            .collect();
        for (li, lj) in chunks.into_iter() {
            i_out.extend_from_slice(&li);
            j_out.extend_from_slice(&lj);
        }
    } else {
        for i in 0..n {
            let pxi = pos[2 * i];
            let pyi = pos[2 * i + 1];
            let cx = ix[i];
            let cy = iy[i];
            for &(ox, oy) in offsets.iter() {
                let qx = cx + ox;
                let qy = cy + oy;
                let qkey = qx.wrapping_mul(P1) ^ qy.wrapping_mul(P2);
                let lo = key_sorted.partition_point(|&k| k < qkey);
                let hi = key_sorted.partition_point(|&k| k <= qkey);
                for k in lo..hi {
                    let j = order[k];
                    if j == i { continue; }
                    let dx = pxi - pos[2 * j];
                    let dy = pyi - pos[2 * j + 1];
                    let r2 = dx * dx + dy * dy;
                    if r2 < h2 {
                        i_out.push(i as i64);
                        j_out.push(j as i64);
                    }
                }
            }
        }
    }
    (i_out, j_out)
}

/// Inner PBF density-projection iteration (no PyO3). Mutates `pos` in place.
#[allow(clippy::too_many_arguments)]
fn pbf_iter_inner(
    pos: &mut [f32],
    mass: &[f32],
    i_arr: &[i64],
    j_arr: &[i64],
    h: f32,
    rho0: f32,
    relax: f32,
    eps: f32,
    density_floor: f32,
    cohesion_on: bool,
    k_corr: f32,
    n_corr: f32,
    dq_w: f32,
) {
    let n = mass.len();
    let n_pairs = i_arr.len();
    if n == 0 {
        return;
    }
    let inv_rho0 = 1.0f32 / rho0.max(eps);
    let h2 = h * h;
    let poly6_coef = poly6_coefficient(h);
    let spiky_coef = spiky_grad_coefficient(h);
    let self_w0 = poly6_coef * (h2 * h2 * h2);

    let mut w_ij = vec![0.0f32; n_pairs];
    let mut grad_x = vec![0.0f32; n_pairs];
    let mut grad_y = vec![0.0f32; n_pairs];

    let mut density = vec![0.0f64; n];
    for i in 0..n {
        density[i] = (self_w0 * mass[i]) as f64;
    }
    let mut sgs_x = vec![0.0f64; n];
    let mut sgs_y = vec![0.0f64; n];
    let mut sum_grad_neighbour_sq = vec![0.0f64; n];

    let denom_w = dq_w.max(eps);

    let h2_v = f32x4::splat(h2);
    let h_v = f32x4::splat(h);
    let eps_v = f32x4::splat(eps);
    let inv_rho0_v = f32x4::splat(inv_rho0);
    let poly6_v = f32x4::splat(poly6_coef);
    let spiky_v = f32x4::splat(spiky_coef);
    let zero_v = f32x4::splat(0.0);

    let compute_pair_chunk = |start: usize,
                              w_chunk: &mut [f32],
                              gx_chunk: &mut [f32],
                              gy_chunk: &mut [f32]| {
        let chunk_len = w_chunk.len();
        let mut k = 0;
        while k + 4 <= chunk_len {
            let p0 = start + k;
            let i0 = i_arr[p0] as usize;
            let i1 = i_arr[p0 + 1] as usize;
            let i2 = i_arr[p0 + 2] as usize;
            let i3 = i_arr[p0 + 3] as usize;
            let j0 = j_arr[p0] as usize;
            let j1 = j_arr[p0 + 1] as usize;
            let j2 = j_arr[p0 + 2] as usize;
            let j3 = j_arr[p0 + 3] as usize;
            let pix = f32x4::from([pos[2 * i0], pos[2 * i1], pos[2 * i2], pos[2 * i3]]);
            let piy = f32x4::from([pos[2 * i0 + 1], pos[2 * i1 + 1], pos[2 * i2 + 1], pos[2 * i3 + 1]]);
            let pjx = f32x4::from([pos[2 * j0], pos[2 * j1], pos[2 * j2], pos[2 * j3]]);
            let pjy = f32x4::from([pos[2 * j0 + 1], pos[2 * j1 + 1], pos[2 * j2 + 1], pos[2 * j3 + 1]]);
            let dx = pix - pjx;
            let dy = piy - pjy;
            let r2 = dx * dx + dy * dy;
            let diff = h2_v - r2;
            let w_full = poly6_v * diff * diff * diff;
            let mask_w = r2.cmp_lt(h2_v) & r2.cmp_ge(zero_v);
            let w = mask_w.blend(w_full, zero_v);
            let r = r2.sqrt();
            let safe_r = r.max(eps_v);
            let dh = h_v - r;
            let factor_full = spiky_v * dh * dh / safe_r;
            let mask_f = r.cmp_gt(zero_v) & r.cmp_lt(h_v);
            let factor = mask_f.blend(factor_full, zero_v);
            let gx = dx * factor * inv_rho0_v;
            let gy = dy * factor * inv_rho0_v;
            let w_arr = w.to_array();
            let gx_arr = gx.to_array();
            let gy_arr = gy.to_array();
            w_chunk[k]     = w_arr[0];
            w_chunk[k + 1] = w_arr[1];
            w_chunk[k + 2] = w_arr[2];
            w_chunk[k + 3] = w_arr[3];
            gx_chunk[k]     = gx_arr[0];
            gx_chunk[k + 1] = gx_arr[1];
            gx_chunk[k + 2] = gx_arr[2];
            gx_chunk[k + 3] = gx_arr[3];
            gy_chunk[k]     = gy_arr[0];
            gy_chunk[k + 1] = gy_arr[1];
            gy_chunk[k + 2] = gy_arr[2];
            gy_chunk[k + 3] = gy_arr[3];
            k += 4;
        }
        while k < chunk_len {
            let p = start + k;
            let i = i_arr[p] as usize;
            let j = j_arr[p] as usize;
            let dx = pos[2 * i] - pos[2 * j];
            let dy = pos[2 * i + 1] - pos[2 * j + 1];
            let r2 = dx * dx + dy * dy;
            let w = if r2 < h2 && r2 >= 0.0 {
                let diff = h2 - r2;
                poly6_coef * diff * diff * diff
            } else { 0.0 };
            let r = r2.sqrt();
            let safe_r = r.max(eps);
            let factor = if r > 0.0 && r < h {
                let dh = h - r;
                spiky_coef * dh * dh / safe_r
            } else { 0.0 };
            w_chunk[k] = w;
            gx_chunk[k] = dx * factor * inv_rho0;
            gy_chunk[k] = dy * factor * inv_rho0;
            k += 1;
        }
    };

    if n_pairs >= PARALLEL_PAIR_MIN {
        let n_threads = rayon::current_num_threads().max(1);
        let chunk_size = ((n_pairs + (n_threads * 4) - 1) / (n_threads * 4)).max(512);
        let chunk_size = ((chunk_size + 3) / 4) * 4;
        w_ij.par_chunks_mut(chunk_size)
            .zip(grad_x.par_chunks_mut(chunk_size))
            .zip(grad_y.par_chunks_mut(chunk_size))
            .enumerate()
            .for_each(|(chunk_idx, ((w_chunk, gx_chunk), gy_chunk))| {
                let start = chunk_idx * chunk_size;
                compute_pair_chunk(start, w_chunk, gx_chunk, gy_chunk);
            });
    } else {
        compute_pair_chunk(0, &mut w_ij[..], &mut grad_x[..], &mut grad_y[..]);
    }

    for p in 0..n_pairs {
        let i = i_arr[p] as usize;
        let j = j_arr[p] as usize;
        let w = w_ij[p];
        let gx = grad_x[p];
        let gy = grad_y[p];
        density[i] += (mass[j] * w) as f64;
        sgs_x[i] += gx as f64;
        sgs_y[i] += gy as f64;
        sum_grad_neighbour_sq[i] += (gx * gx + gy * gy) as f64;
    }

    let mut lam = vec![0.0f32; n];
    let relax_64 = relax as f64;
    let eps_64 = eps as f64;
    for i in 0..n {
        let density_f32 = density[i] as f32;
        let c_i = ((density_f32 * inv_rho0) - 1.0).max(density_floor) as f64;
        let sgsx = sgs_x[i];
        let sgsy = sgs_y[i];
        let sum_grad_sq = sgsx * sgsx + sgsy * sgsy;
        let denom = (sum_grad_sq + sum_grad_neighbour_sq[i] + relax_64).max(eps_64);
        lam[i] = (-c_i / denom) as f32;
    }

    let mut dp_x = vec![0.0f64; n];
    let mut dp_y = vec![0.0f64; n];
    if cohesion_on {
        for p in 0..n_pairs {
            let i = i_arr[p] as usize;
            let j = j_arr[p] as usize;
            let base_ratio = (w_ij[p] / denom_w).max(0.0);
            let s_corr_ij = -k_corr * base_ratio.powf(n_corr);
            let mult = (lam[i] + lam[j] + s_corr_ij) as f64;
            dp_x[i] += (grad_x[p] as f64) * mult;
            dp_y[i] += (grad_y[p] as f64) * mult;
        }
    } else {
        for p in 0..n_pairs {
            let i = i_arr[p] as usize;
            let j = j_arr[p] as usize;
            let mult = (lam[i] + lam[j]) as f64;
            dp_x[i] += (grad_x[p] as f64) * mult;
            dp_y[i] += (grad_y[p] as f64) * mult;
        }
    }
    for i in 0..n {
        pos[2 * i] += dp_x[i] as f32;
        pos[2 * i + 1] += dp_y[i] as f32;
    }
}

/// Inner boundary projection.
#[inline]
fn project_boundaries_inner(
    pos: &mut [f32],
    n: usize,
    floor_y: f32,
    wall_x_min: f32,
    wall_x_max: f32,
    ceiling_y: f32,
) {
    // Mirror numpy:
    //   np.minimum(pos[:, 1], floor_y, out=pos[:, 1])    # clamp y ≤ floor_y
    //   np.maximum(pos[:, 1], ceiling_y, out=pos[:, 1])  # clamp y ≥ ceiling_y
    //   np.maximum(pos[:, 0], wall_x_min, out=pos[:, 0])
    //   np.minimum(pos[:, 0], wall_x_max, out=pos[:, 0])
    for i in 0..n {
        let mut y = pos[2 * i + 1];
        if y > floor_y { y = floor_y; }
        if y < ceiling_y { y = ceiling_y; }
        pos[2 * i + 1] = y;
        let mut x = pos[2 * i];
        if x < wall_x_min { x = wall_x_min; }
        if x > wall_x_max { x = wall_x_max; }
        pos[2 * i] = x;
    }
}

/// Inner friction pass (granular Coulomb). Mutates `pos` in place.
#[allow(clippy::too_many_arguments)]
fn friction_pass_inner(
    pos: &mut [f32],
    prev_pos: &[f32],
    inv_m: &[f32],
    mat_id: &[u8],
    gran: &[u8],
    mu_tab: &[f32],
    i_arr: &[i64],
    j_arr: &[i64],
    contact_radius: f32,
    eps: f32,
    tan_eps: f32,
    dt_scale: f32,
    normal_proxy_floor_factor: f32,
) {
    let n_pairs = i_arr.len();
    if n_pairs == 0 {
        return;
    }
    let normal_proxy_floor = normal_proxy_floor_factor * contact_radius;
    let contact_r2 = contact_radius * contact_radius;
    let eps2 = eps * eps;
    for p in 0..n_pairs {
        let i = i_arr[p] as usize;
        let j = j_arr[p] as usize;
        if i >= j { continue; }
        let mi = mat_id[i] as usize;
        let mj = mat_id[j] as usize;
        if gran[mi] == 0 || gran[mj] == 0 { continue; }
        let dx = pos[2 * i] - pos[2 * j];
        let dy = pos[2 * i + 1] - pos[2 * j + 1];
        let r2 = dx * dx + dy * dy;
        if r2 >= contact_r2 || r2 <= eps2 { continue; }
        let r = r2.sqrt();
        let inv_r = 1.0 / r;
        let nx = dx * inv_r;
        let ny = dy * inv_r;
        let rel_dx_x =
            (pos[2 * i] - prev_pos[2 * i]) - (pos[2 * j] - prev_pos[2 * j]);
        let rel_dx_y =
            (pos[2 * i + 1] - prev_pos[2 * i + 1]) - (pos[2 * j + 1] - prev_pos[2 * j + 1]);
        let rel_dot_n = rel_dx_x * nx + rel_dx_y * ny;
        let dx_t_x = rel_dx_x - nx * rel_dot_n;
        let dx_t_y = rel_dx_y - ny * rel_dot_n;
        let t_mag2 = dx_t_x * dx_t_x + dx_t_y * dx_t_y;
        if t_mag2 <= tan_eps * tan_eps { continue; }
        let t_mag = t_mag2.sqrt();
        let pen = contact_radius - r;
        let mu_pair = 0.5 * (mu_tab[mi] + mu_tab[mj]);
        let normal_proxy = pen + normal_proxy_floor;
        let cap = mu_pair * normal_proxy;
        let s = if t_mag < cap { t_mag } else { cap };
        let s = s * dt_scale;
        let inv_t = 1.0 / t_mag;
        let tdx = dx_t_x * inv_t;
        let tdy = dx_t_y * inv_t;
        let w_i = inv_m[i];
        let w_j = inv_m[j];
        let w_sum = w_i + w_j;
        let inv_w_sum = 1.0 / w_sum.max(eps);
        let cs_i = s * w_i * inv_w_sum;
        let cs_j = s * w_j * inv_w_sum;
        pos[2 * i] -= tdx * cs_i;
        pos[2 * i + 1] -= tdy * cs_i;
        pos[2 * j] += tdx * cs_j;
        pos[2 * j + 1] += tdy * cs_j;
    }
}

/// Inner thermal step. Mutates `t_arr` and `mat_bytes` in place.
/// Returns the number of phase-change flips.
#[allow(clippy::too_many_arguments)]
fn thermal_step_inner(
    t_arr: &mut [f32],
    mat_bytes: &mut [u8],
    mass: &[f32],
    i_arr: &[i64],
    j_arr: &[i64],
    cond_tab: &[f32],
    amb_tab: &[f32],
    melt_t_tab: &[f32],
    freeze_t_tab: &[f32],
    melt_to_tab: &[i32],
    freeze_to_tab: &[i32],
    sub_dt: f32,
    diffusion_rate: f32,
    ambient_rate: f32,
) -> u32 {
    let n = mass.len();
    let n_pairs = i_arr.len();
    let mut n_changes: u32 = 0;
    if n_pairs > 0 {
        let mut t0 = vec![0.0f32; n];
        t0.copy_from_slice(&t_arr[..n]);
        let dr_dt = diffusion_rate * sub_dt;
        for p in 0..n_pairs {
            let i = i_arr[p] as usize;
            let j = j_arr[p] as usize;
            let mi = mat_bytes[i] as usize;
            let mj = mat_bytes[j] as usize;
            let ka = cond_tab[mi];
            let kb = cond_tab[mj];
            if !(ka > 0.0 && kb > 0.0) { continue; }
            let k_sum = (ka + kb).max(1.0e-9);
            let k_harm = 2.0 * ka * kb / k_sum;
            let ta = t0[i];
            let tb = t0[j];
            let dt_ab = ta - tb;
            let q_raw = k_harm * dt_ab * dr_dt;
            let ma = mass[i].max(1.0e-9);
            let mb = mass[j].max(1.0e-9);
            let m_eff = 1.0 / (1.0 / ma + 1.0 / mb);
            let q_eq = dt_ab * m_eff;
            let q = if q_eq >= 0.0 {
                q_raw.max(0.0).min(q_eq)
            } else {
                q_raw.min(0.0).max(q_eq)
            };
            t_arr[i] -= q / ma;
            t_arr[j] += q / mb;
        }
    }
    if ambient_rate > 0.0 && sub_dt > 0.0 {
        let ar_dt = ambient_rate * sub_dt;
        let denom = 1.0 + ar_dt;
        let inv_denom = 1.0 / denom;
        for i in 0..n {
            let mi = mat_bytes[i] as usize;
            let amb = amb_tab[mi];
            t_arr[i] = (t_arr[i] + ar_dt * amb) * inv_denom;
        }
    }
    for i in 0..n {
        let mi = mat_bytes[i] as usize;
        let ti = t_arr[i];
        let mtarget = melt_to_tab[mi];
        let ftarget = freeze_to_tab[mi];
        if mtarget >= 0 && ti > melt_t_tab[mi] {
            mat_bytes[i] = mtarget as u8;
            n_changes += 1;
        } else if ftarget >= 0 && ti < freeze_t_tab[mi] {
            mat_bytes[i] = ftarget as u8;
            n_changes += 1;
        }
    }
    n_changes
}

/// Tier 10: full PBF step in Rust.
#[pyfunction]
#[pyo3(signature = (
    pos_xy, prev_pos_xy, vel_xy, temperature, material_id,
    mass_bytes, inv_mass_bytes,
    is_granular_bytes, mu_lookup_bytes,
    cond_lookup, ambient_lookup, melt_t_lookup, freeze_t_lookup,
    melt_to_lookup, freeze_to_lookup,
    n_particles,
    substeps, iters, sub_dt,
    gravity_x, gravity_y, eps, max_velocity,
    floor_y, wall_x_min, wall_x_max, ceiling_y,
    h, rho0, relax, k_corr, n_corr, dq_w, cohesion_on,
    visc, xsph_on, density_floor,
    granular_enabled, contact_radius, tan_eps, dt_scale, normal_proxy_floor_factor,
    thermal_enabled, diffusion_rate, ambient_rate,
))]
#[allow(clippy::too_many_arguments)]
pub fn pbf_step_full(
    pos_xy: &Bound<'_, PyByteArray>,
    prev_pos_xy: &Bound<'_, PyByteArray>,
    vel_xy: &Bound<'_, PyByteArray>,
    temperature: &Bound<'_, PyByteArray>,
    material_id: &Bound<'_, PyByteArray>,
    mass_bytes: &[u8],
    inv_mass_bytes: &[u8],
    is_granular_bytes: &[u8],
    mu_lookup_bytes: &[u8],
    cond_lookup: &[u8],
    ambient_lookup: &[u8],
    melt_t_lookup: &[u8],
    freeze_t_lookup: &[u8],
    melt_to_lookup: &[u8],
    freeze_to_lookup: &[u8],
    n_particles: usize,
    substeps: usize,
    iters: usize,
    sub_dt: f32,
    gravity_x: f32,
    gravity_y: f32,
    eps: f32,
    max_velocity: f32,
    floor_y: f32,
    wall_x_min: f32,
    wall_x_max: f32,
    ceiling_y: f32,
    h: f32,
    rho0: f32,
    relax: f32,
    k_corr: f32,
    n_corr: f32,
    dq_w: f32,
    cohesion_on: bool,
    visc: f32,
    xsph_on: bool,
    density_floor: f32,
    granular_enabled: bool,
    contact_radius: f32,
    tan_eps: f32,
    dt_scale: f32,
    normal_proxy_floor_factor: f32,
    thermal_enabled: bool,
    diffusion_rate: f32,
    ambient_rate: f32,
) -> PyResult<u32> {
    if n_particles == 0 {
        return Ok(0);
    }
    let pos: &mut [f32] = bytemuck::cast_slice_mut(unsafe { pos_xy.as_bytes_mut() });
    let prev_pos: &mut [f32] = bytemuck::cast_slice_mut(unsafe { prev_pos_xy.as_bytes_mut() });
    let vel: &mut [f32] = bytemuck::cast_slice_mut(unsafe { vel_xy.as_bytes_mut() });
    let t_arr: &mut [f32] = bytemuck::cast_slice_mut(unsafe { temperature.as_bytes_mut() });
    let mat_bytes: &mut [u8] = unsafe { material_id.as_bytes_mut() };

    let mass: &[f32] = cast_slice(mass_bytes);
    let inv_mass: &[f32] = cast_slice(inv_mass_bytes);
    let is_granular: &[u8] = is_granular_bytes;
    let mu_lookup: &[f32] = cast_slice(mu_lookup_bytes);
    let cond_tab: &[f32] = cast_slice(cond_lookup);
    let amb_tab: &[f32] = cast_slice(ambient_lookup);
    let melt_t_tab: &[f32] = cast_slice(melt_t_lookup);
    let freeze_t_tab: &[f32] = cast_slice(freeze_t_lookup);
    let melt_to_tab: &[i32] = cast_slice(melt_to_lookup);
    let freeze_to_tab: &[i32] = cast_slice(freeze_to_lookup);

    if pos.len() != n_particles * 2
        || prev_pos.len() != n_particles * 2
        || vel.len() != n_particles * 2
        || t_arr.len() != n_particles
        || mat_bytes.len() != n_particles
        || mass.len() != n_particles
        || inv_mass.len() != n_particles
    {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "pbf_step_full: array size mismatch",
        ));
    }

    let mut total_phase_changes: u32 = 0;

    for _ in 0..substeps {
        // prev_pos = pos
        prev_pos.copy_from_slice(pos);
        // vel += gravity * sub_dt; pos += vel * sub_dt
        for i in 0..n_particles {
            vel[2 * i]     += gravity_x * sub_dt;
            vel[2 * i + 1] += gravity_y * sub_dt;
            pos[2 * i]     += vel[2 * i] * sub_dt;
            pos[2 * i + 1] += vel[2 * i + 1] * sub_dt;
        }
        project_boundaries_inner(pos, n_particles, floor_y, wall_x_min, wall_x_max, ceiling_y);

        // Build neighbour table once per substep.
        let (i_idx, j_idx) = build_neighbour_table_inner(pos, n_particles, h);

        if !i_idx.is_empty() {
            for _ in 0..iters {
                pbf_iter_inner(
                    pos, mass, &i_idx, &j_idx,
                    h, rho0, relax, eps, density_floor,
                    cohesion_on, k_corr, n_corr, dq_w,
                );
                project_boundaries_inner(pos, n_particles, floor_y, wall_x_min, wall_x_max, ceiling_y);
            }
            if granular_enabled {
                friction_pass_inner(
                    pos, prev_pos, inv_mass, mat_bytes, is_granular, mu_lookup,
                    &i_idx, &j_idx,
                    contact_radius, eps, tan_eps, dt_scale, normal_proxy_floor_factor,
                );
            }
            project_boundaries_inner(pos, n_particles, floor_y, wall_x_min, wall_x_max, ceiling_y);
            if thermal_enabled {
                total_phase_changes = total_phase_changes.wrapping_add(thermal_step_inner(
                    t_arr, mat_bytes, mass, &i_idx, &j_idx,
                    cond_tab, amb_tab, melt_t_tab, freeze_t_tab,
                    melt_to_tab, freeze_to_tab,
                    sub_dt, diffusion_rate, ambient_rate,
                ));
            }
        }

        // Velocity update + xsph + clamp.
        // new_vel = (pos - prev_pos) / sub_dt
        let inv_sub_dt = 1.0f32 / sub_dt;
        // Compute new_vel into a scratch so xsph can read neighbour vels.
        let mut new_vel = vec![0.0f32; n_particles * 2];
        for i in 0..n_particles {
            new_vel[2 * i]     = (pos[2 * i]     - prev_pos[2 * i])     * inv_sub_dt;
            new_vel[2 * i + 1] = (pos[2 * i + 1] - prev_pos[2 * i + 1]) * inv_sub_dt;
        }

        if !i_idx.is_empty() && xsph_on && visc > 0.0 {
            // XSPH viscosity. delta is r/h for poly6 weight; we already
            // computed r2 inside pbf_iter but didn't keep it — recompute
            // here. Cheap relative to the per-iter density solve.
            let h2 = h * h;
            let poly6_coef = poly6_coefficient(h);
            let inv_rho0 = 1.0 / rho0.max(eps);
            let mut acc_x = vec![0.0f32; n_particles];
            let mut acc_y = vec![0.0f32; n_particles];
            for p in 0..i_idx.len() {
                let i = i_idx[p] as usize;
                let j = j_idx[p] as usize;
                let dx = pos[2 * i] - pos[2 * j];
                let dy = pos[2 * i + 1] - pos[2 * j + 1];
                let r2 = dx * dx + dy * dy;
                if r2 >= h2 || r2 < 0.0 { continue; }
                let diff = h2 - r2;
                let w = poly6_coef * diff * diff * diff;
                let vol_j = mass[j] * inv_rho0;
                let vdx = new_vel[2 * j] - new_vel[2 * i];
                let vdy = new_vel[2 * j + 1] - new_vel[2 * i + 1];
                acc_x[i] += vdx * (w * vol_j);
                acc_y[i] += vdy * (w * vol_j);
            }
            for i in 0..n_particles {
                new_vel[2 * i]     += visc * acc_x[i];
                new_vel[2 * i + 1] += visc * acc_y[i];
            }
        }

        // Clamp velocity magnitude.
        for i in 0..n_particles {
            let vx = new_vel[2 * i];
            let vy = new_vel[2 * i + 1];
            let speed = (vx * vx + vy * vy).sqrt();
            let scale = if speed > eps { (max_velocity / speed.max(eps)).min(1.0) } else { 1.0 };
            vel[2 * i]     = vx * scale;
            vel[2 * i + 1] = vy * scale;
        }
    }

    Ok(total_phase_changes)
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(build_neighbour_table, m)?)?;
    m.add_function(wrap_pyfunction!(pbf_iter, m)?)?;
    m.add_function(wrap_pyfunction!(friction_pass_rs, m)?)?;
    m.add_function(wrap_pyfunction!(thermal_step_rs, m)?)?;
    m.add_function(wrap_pyfunction!(pbf_step_full, m)?)?;
    Ok(())
}
