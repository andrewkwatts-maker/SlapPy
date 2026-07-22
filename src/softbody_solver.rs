//! Hot-path XPBD kernels for the softbody solver.
//!
//! Three functions are exposed:
//! * [`project_distance_constraints`] — XPBD distance projection. Runs
//!   `iters * substeps` times per frame (32x by default).
//! * [`apply_plasticity`] — relax rest-length toward strained length for
//!   beams above their yield threshold.
//! * [`mark_breaks`] — flip beams whose strain exceeds `break_strain`.
//!
//! All array inputs arrive through the Python buffer protocol via
//! `PyBuffer`. Writable arrays (`pos_xy` for the projection kernel,
//! `rest_length` for plasticity, `broken` for mark_breaks) are
//! reinterpreted as `&mut [T]`; the others are reinterpreted as `&[T]`.
//! This lets the Python wrapper pass numpy arrays directly without
//! copying into a temporary `bytearray`, which is essential here since
//! `nodes.pos` is persistent state mutated in-place every substep.
//!
//! **Precision contract:** beams are processed in array order. The
//! original numpy implementation used `np.add.at(pos, idx, corr)` which
//! IS order-preserving — `np.bincount` was rejected here because it
//! accumulates with implementation-defined order and the resulting
//! float-summation drift was big enough to fail
//! `test_block_on_block_stacks`. The Rust port walks beams 0..B and
//! adds corrections one at a time to mirror the same ordering.

use bytemuck::cast_slice;
use pyo3::buffer::PyBuffer;
use pyo3::prelude::*;
use pyo3::types::{PyByteArray, PyBytes};
use rayon::prelude::*;
use std::collections::HashSet;

// Per-element work thresholds below which the rayon overhead exceeds the
// gain. These kernels are called many times per step (substeps×iters ≈
// 160 calls/frame) so thresholds are tuned carefully — rayon's
// work-stealing dispatch is ~microseconds per call, which dominates
// short workloads at typical game-scale scenes.
//
// Plasticity / mark_breaks do ~5 ns of work per beam; pair compute does
// ~20 ns. Build_contact_pairs has ~50 ns per node (9-cell scan + filter).
// Contact projection pair compute is ~50 ns.
//
// Tier-8-cleanup tuning: thresholds are set so the typical small-scene
// path (5x6x6 lattice ≈ 245 nodes, 780 beams) stays on the serial loop
// (matching pre-Tier-8 perf), AND the moderately-sized 20x8x8 stack
// (≈1620 nodes, 5400 beams) also stays serial — at that scale the
// per-call inner work is still smaller than rayon's dispatch overhead.
// Truly large scenes (10k+ beams or 5k+ nodes) cross these thresholds
// and pay back the dispatch cost via parallelism.
//
// PARALLEL_BEAM_MIN gates plasticity/mark_breaks (very short per-beam
// work, ~5 ns). PARALLEL_NODE_MIN gates the broadphase 9-cell gather
// (heavier per-element work). PARALLEL_PAIR_MIN gates contact-pair
// compute (heavier still).
const PARALLEL_BEAM_MIN: usize = 16384;
const PARALLEL_NODE_MIN: usize = 4096;
const PARALLEL_PAIR_MIN: usize = 65536;

/// Per-call threshold above which `project_distance_constraints` runs
/// its per-beam compute prepass in parallel chunks. This kernel is
/// called `substeps * iters = 160x` per frame, so the per-call workload
/// even on the 20x8x8 scene (~5400 beams ≈ 135 µs of inner work) is
/// barely larger than rayon's dispatch overhead. We therefore keep the
/// threshold quite high — only stadium-scale scenes benefit from
/// parallel projection.
const PARALLEL_DIST_BEAM_MIN: usize = 32768;

/// SAFETY-helper: reinterpret a `PyBuffer<T>`'s memory as an immutable
/// slice. Caller must guarantee the buffer is contiguous and the Python
/// object outlives the slice (we hold the GIL throughout).
unsafe fn as_slice<'a, T: pyo3::buffer::Element + Copy>(
    buf: &'a PyBuffer<T>,
) -> PyResult<&'a [T]> {
    if !buf.is_c_contiguous() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "expected a C-contiguous buffer",
        ));
    }
    let ptr = buf.buf_ptr() as *const T;
    let len = buf.item_count();
    Ok(std::slice::from_raw_parts(ptr, len))
}

/// SAFETY-helper: reinterpret a writable `PyBuffer<T>` as `&mut [T]`.
/// Caller must guarantee no aliasing — we never expose the same buffer
/// twice in one function call, and the GIL prevents concurrent Python
/// mutation.
unsafe fn as_slice_mut<'a, T: pyo3::buffer::Element + Copy>(
    buf: &'a PyBuffer<T>,
) -> PyResult<&'a mut [T]> {
    if buf.readonly() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "expected a writable buffer",
        ));
    }
    if !buf.is_c_contiguous() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "expected a C-contiguous buffer",
        ));
    }
    let ptr = buf.buf_ptr() as *mut T;
    let len = buf.item_count();
    Ok(std::slice::from_raw_parts_mut(ptr, len))
}

/// XPBD distance-constraint projection over every live beam.
///
/// `pos_xy` is `(N, 2)` row-major f32 (writable). All other arrays are
/// read-only buffers (numpy arrays of matching dtype).
///
/// Beams are walked in index order; for each non-broken beam we compute
/// the XPBD position correction and apply it in place to both endpoint
/// nodes. This matches the order `np.add.at` used in the numpy fallback,
/// which the stacked-block contact test depends on.
#[pyfunction]
#[pyo3(signature = (pos_xy, inv_mass, node_a, node_b, rest_length, stiffness, broken, node_relax, sub_dt, eps))]
#[allow(clippy::too_many_arguments)]
pub fn project_distance_constraints(
    py: Python<'_>,
    pos_xy: &Bound<'_, PyAny>,
    inv_mass: &Bound<'_, PyAny>,
    node_a: &Bound<'_, PyAny>,
    node_b: &Bound<'_, PyAny>,
    rest_length: &Bound<'_, PyAny>,
    stiffness: &Bound<'_, PyAny>,
    broken: &Bound<'_, PyAny>,
    node_relax: &Bound<'_, PyAny>,
    sub_dt: f32,
    eps: f32,
) -> PyResult<()> {
    let pos_buf = PyBuffer::<f32>::get_bound(pos_xy)?;
    let inv_mass_buf = PyBuffer::<f32>::get_bound(inv_mass)?;
    let na_buf = PyBuffer::<u32>::get_bound(node_a)?;
    let nb_buf = PyBuffer::<u32>::get_bound(node_b)?;
    let rest_buf = PyBuffer::<f32>::get_bound(rest_length)?;
    let stiff_buf = PyBuffer::<f32>::get_bound(stiffness)?;
    let broken_buf = PyBuffer::<u8>::get_bound(broken)?;
    let relax_buf = PyBuffer::<f32>::get_bound(node_relax)?;

    // Safety: we hold the GIL throughout this function and don't yield
    // it. All buffers stay alive for the duration of this call.
    let pos: &mut [f32] = unsafe { as_slice_mut(&pos_buf)? };
    let inv_mass: &[f32] = unsafe { as_slice(&inv_mass_buf)? };
    let na: &[u32] = unsafe { as_slice(&na_buf)? };
    let nb: &[u32] = unsafe { as_slice(&nb_buf)? };
    let rest: &[f32] = unsafe { as_slice(&rest_buf)? };
    let stiff: &[f32] = unsafe { as_slice(&stiff_buf)? };
    let broken: &[u8] = unsafe { as_slice(&broken_buf)? };
    let relax: &[f32] = unsafe { as_slice(&relax_buf)? };

    let n_beams = na.len();
    if nb.len() != n_beams
        || rest.len() != n_beams
        || stiff.len() != n_beams
        || broken.len() != n_beams
    {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "beam arrays must share length",
        ));
    }
    let n_nodes = inv_mass.len();
    if relax.len() != n_nodes || pos.len() != n_nodes * 2 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "node array lengths inconsistent",
        ));
    }

    let _ = py; // marker — held implicitly by &Bound args.

    let inv_dt2 = 1.0f32 / (sub_dt * sub_dt);

    // The numpy reference computes the per-beam correction *vector*
    // first from a single snapshot of positions, then scatters into
    // both endpoints in two passes (``np.add.at(pos, a, ...)`` then
    // ``np.add.at(pos, bb, ...)``). To preserve the exact float
    // summation order — which the stacked-block contact test depends
    // on — we mirror that pattern here:
    //   1. compute all corrections from the pre-pass position snapshot
    //      (stored in ``corr``);
    //   2. apply -corr scaled by w_a/relax_a to node ``a`` in beam
    //      order (first ``np.add.at`` call);
    //   3. apply +corr scaled by w_b/relax_b to node ``b`` in beam
    //      order (second ``np.add.at`` call).
    let mut corr_x = vec![0.0f32; n_beams];
    let mut corr_y = vec![0.0f32; n_beams];

    // Compute pre-pass — reads from pos (read-only snapshot) and writes
    // only to its own corr_x[i] / corr_y[i] slot.
    //
    // Tier-9 note: an `f32x4` (wide crate) SIMD version of this loop was
    // tried but it didn't pay off on x86 — gather instructions aren't
    // available on baseline SSE so each lane needs separate scalar loads
    // (16 loads per chunk-of-4), and LLVM already auto-vectorises the
    // scalar form reasonably well via FMA where possible. The
    // theoretical 4× lane throughput is eaten by the scalar
    // load-to-vector pack, so we keep the straight scalar walk here.
    // See `pbf_iter` for a kernel where SIMD does pay off (heavier
    // per-pair math, fewer indirect loads relative to arithmetic).
    let compute_beams = |start: usize,
                         cx_chunk: &mut [f32],
                         cy_chunk: &mut [f32]| {
        for k in 0..cx_chunk.len() {
            let i = start + k;
            if broken[i] != 0 {
                continue;
            }
            let ai = na[i] as usize;
            let bi = nb[i] as usize;
            debug_assert!(ai < n_nodes && bi < n_nodes);

            let pax = pos[2 * ai];
            let pay = pos[2 * ai + 1];
            let pbx = pos[2 * bi];
            let pby = pos[2 * bi + 1];
            let dx = pbx - pax;
            let dy = pby - pay;
            // Match numpy's ``np.sqrt(np.einsum("ij,ij->i", d, d))`` and
            // ``direction = d / safe_len[:, None]``: division (not
            // multiplication by reciprocal) for the direction so the
            // result matches at ULP level.
            let length_sq = dx * dx + dy * dy;
            let length = length_sq.sqrt();
            let safe_len = if length > eps { length } else { eps };
            let dir_x = dx / safe_len;
            let dir_y = dy / safe_len;

            let r = rest[i];
            let s = stiff[i];
            // Match numpy ``alpha = inv_dt2 / np.maximum(beams.stiffness, eps)``.
            let alpha = inv_dt2 / s.max(eps);

            let w_a = inv_mass[ai];
            let w_b = inv_mass[bi];
            // Match numpy ``denom = w_a + w_b + alpha; denom = np.where(denom < eps, 1.0, denom)``.
            let denom_raw = w_a + w_b + alpha;
            let denom = if denom_raw < eps { 1.0 } else { denom_raw };

            // Match numpy ``c = (length - rest) * not_broken.astype(np.float32)``.
            // ``not_broken`` is 1.0 here (we already skipped broken beams).
            let c = length - r;
            let dlambda = -c / denom;

            cx_chunk[k] = dir_x * dlambda;
            cy_chunk[k] = dir_y * dlambda;
        }
    };

    if n_beams >= PARALLEL_DIST_BEAM_MIN {
        // Split the corr arrays into chunks; each rayon task handles a
        // contiguous beam range in parallel. The pos array is read-only
        // during this phase so cross-task aliasing isn't a concern.
        let n_threads = rayon::current_num_threads().max(1);
        let chunk_size = ((n_beams + (n_threads * 4) - 1) / (n_threads * 4)).max(256);
        corr_x
            .par_chunks_mut(chunk_size)
            .zip(corr_y.par_chunks_mut(chunk_size))
            .enumerate()
            .for_each(|(chunk_idx, (cx, cy))| {
                let start = chunk_idx * chunk_size;
                compute_beams(start, cx, cy);
            });
    } else {
        compute_beams(0, &mut corr_x[..], &mut corr_y[..]);
    }

    // Pass A: scatter `-corr * w_a * relax_a` into node ``a`` indices.
    for i in 0..n_beams {
        if broken[i] != 0 {
            continue;
        }
        let ai = na[i] as usize;
        let scale = inv_mass[ai] * relax[ai];
        pos[2 * ai]     += -corr_x[i] * scale;
        pos[2 * ai + 1] += -corr_y[i] * scale;
    }
    // Pass B: scatter `+corr * w_b * relax_b` into node ``b`` indices.
    for i in 0..n_beams {
        if broken[i] != 0 {
            continue;
        }
        let bi = nb[i] as usize;
        let scale = inv_mass[bi] * relax[bi];
        pos[2 * bi]     +=  corr_x[i] * scale;
        pos[2 * bi + 1] +=  corr_y[i] * scale;
    }

    Ok(())
}

/// Relax `rest_length` toward the strained length for beams that have
/// crossed their yield threshold. In-place mutation of `rest_length`.
#[pyfunction]
#[pyo3(signature = (pos_xy, rest_length, node_a, node_b, yield_strain, plasticity_rate, broken, sub_dt, eps))]
#[allow(clippy::too_many_arguments)]
pub fn apply_plasticity(
    pos_xy: &Bound<'_, PyAny>,
    rest_length: &Bound<'_, PyAny>,
    node_a: &Bound<'_, PyAny>,
    node_b: &Bound<'_, PyAny>,
    yield_strain: &Bound<'_, PyAny>,
    plasticity_rate: &Bound<'_, PyAny>,
    broken: &Bound<'_, PyAny>,
    sub_dt: f32,
    eps: f32,
) -> PyResult<()> {
    let pos_buf = PyBuffer::<f32>::get_bound(pos_xy)?;
    let rest_buf = PyBuffer::<f32>::get_bound(rest_length)?;
    let na_buf = PyBuffer::<u32>::get_bound(node_a)?;
    let nb_buf = PyBuffer::<u32>::get_bound(node_b)?;
    let ys_buf = PyBuffer::<f32>::get_bound(yield_strain)?;
    let pr_buf = PyBuffer::<f32>::get_bound(plasticity_rate)?;
    let broken_buf = PyBuffer::<u8>::get_bound(broken)?;

    let pos: &[f32] = unsafe { as_slice(&pos_buf)? };
    let rest: &mut [f32] = unsafe { as_slice_mut(&rest_buf)? };
    let na: &[u32] = unsafe { as_slice(&na_buf)? };
    let nb: &[u32] = unsafe { as_slice(&nb_buf)? };
    let ys: &[f32] = unsafe { as_slice(&ys_buf)? };
    let pr: &[f32] = unsafe { as_slice(&pr_buf)? };
    let broken: &[u8] = unsafe { as_slice(&broken_buf)? };

    let n_beams = na.len();
    if nb.len() != n_beams
        || rest.len() != n_beams
        || ys.len() != n_beams
        || pr.len() != n_beams
        || broken.len() != n_beams
    {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "beam arrays must share length",
        ));
    }

    // Per-beam math is fully independent: each beam reads from pos
    // (read-only) and writes only to its own ``rest[i]`` slot. Parallel-safe.
    let update = |i: usize, r_slot: &mut f32| {
        if broken[i] != 0 {
            return;
        }
        let ai = na[i] as usize;
        let bi = nb[i] as usize;
        let dx = pos[2 * bi] - pos[2 * ai];
        let dy = pos[2 * bi + 1] - pos[2 * ai + 1];
        let length = (dx * dx + dy * dy).sqrt();
        let r = *r_slot;
        let safe_rest = r.max(eps);
        let strain = (length - r) / safe_rest;
        let abs_strain = strain.abs();
        let y_strain = ys[i];
        if abs_strain <= y_strain {
            return;
        }
        let sign_strain: f32 = if strain > 0.0 {
            1.0
        } else if strain < 0.0 {
            -1.0
        } else {
            0.0
        };
        let denom = 1.0 + sign_strain * y_strain;
        let target_rest = length / denom.max(eps);
        let blend = 1.0 - (-pr[i] * sub_dt).exp();
        *r_slot = r * (1.0 - blend) + target_rest * blend;
    };

    if n_beams >= PARALLEL_BEAM_MIN {
        rest.par_iter_mut()
            .enumerate()
            .for_each(|(i, r_slot)| update(i, r_slot));
    } else {
        for (i, r_slot) in rest.iter_mut().enumerate() {
            update(i, r_slot);
        }
    }

    Ok(())
}

/// Mark beams as broken if their strain magnitude exceeds `break_strain`.
///
/// The `broken` numpy array (dtype=bool, one byte per element) is OR'd
/// in place. Newly-broken beams flip from 0 to 1.
#[pyfunction]
#[pyo3(signature = (pos_xy, rest_length, node_a, node_b, break_strain, broken, eps))]
pub fn mark_breaks(
    pos_xy: &Bound<'_, PyAny>,
    rest_length: &Bound<'_, PyAny>,
    node_a: &Bound<'_, PyAny>,
    node_b: &Bound<'_, PyAny>,
    break_strain: &Bound<'_, PyAny>,
    broken: &Bound<'_, PyAny>,
    eps: f32,
) -> PyResult<()> {
    let pos_buf = PyBuffer::<f32>::get_bound(pos_xy)?;
    let rest_buf = PyBuffer::<f32>::get_bound(rest_length)?;
    let na_buf = PyBuffer::<u32>::get_bound(node_a)?;
    let nb_buf = PyBuffer::<u32>::get_bound(node_b)?;
    let bs_buf = PyBuffer::<f32>::get_bound(break_strain)?;
    let broken_buf = PyBuffer::<u8>::get_bound(broken)?;

    let pos: &[f32] = unsafe { as_slice(&pos_buf)? };
    let rest: &[f32] = unsafe { as_slice(&rest_buf)? };
    let na: &[u32] = unsafe { as_slice(&na_buf)? };
    let nb: &[u32] = unsafe { as_slice(&nb_buf)? };
    let bs: &[f32] = unsafe { as_slice(&bs_buf)? };
    let broken: &mut [u8] = unsafe { as_slice_mut(&broken_buf)? };

    let n_beams = na.len();
    if nb.len() != n_beams
        || rest.len() != n_beams
        || bs.len() != n_beams
        || broken.len() != n_beams
    {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "beam arrays must share length",
        ));
    }

    // Each beam reads from pos / rest (read-only) and writes only to
    // its own ``broken[i]`` slot.
    let update = |i: usize, b_slot: &mut u8| {
        if *b_slot != 0 {
            return;
        }
        let ai = na[i] as usize;
        let bi = nb[i] as usize;
        let dx = pos[2 * bi] - pos[2 * ai];
        let dy = pos[2 * bi + 1] - pos[2 * ai + 1];
        let length = (dx * dx + dy * dy).sqrt();
        let r = rest[i];
        let safe_rest = r.max(eps);
        let deviation = (length - r).abs() / safe_rest;
        if deviation > bs[i] {
            *b_slot = 1;
        }
    };

    if n_beams >= PARALLEL_BEAM_MIN {
        broken
            .par_iter_mut()
            .enumerate()
            .for_each(|(i, b_slot)| update(i, b_slot));
    } else {
        for (i, b_slot) in broken.iter_mut().enumerate() {
            update(i, b_slot);
        }
    }

    Ok(())
}

/// XOR-mix 2D cell coords into an int64 hash key. Constants must match
/// `_pack_cell_keys` in `python/slappyengine/softbody/collision.py`.
const CELL_PRIME_I: i64 = 73856093;
const CELL_PRIME_J: i64 = 19349663;

#[inline(always)]
fn pack_key(ix: i64, iy: i64) -> i64 {
    ix.wrapping_mul(CELL_PRIME_I) ^ iy.wrapping_mul(CELL_PRIME_J)
}

/// Build contact-candidate pair lists (node-beam and node-node).
///
/// Mirrors `build_contact_pairs` in
/// `python/slappyengine/softbody/collision.py`:
/// 1. Hash each node into an integer cell on a uniform grid sized by
///    `max(max_rest * cell_factor, thickness * 2.0, 1e-9)`.
/// 2. Stable-sort beam-endpoint cell keys; binary-search each node's
///    9-cell neighbourhood to gather candidate beams.
/// 3. Filter (not broken, different body, not own endpoint), dedup, and
///    record which nodes already participate as node-beam candidates.
/// 4. For all remaining nodes, repeat the 9-cell gather over node-cell
///    keys to produce node-node fallback pairs (`i < j`,
///    `body_id_i != body_id_j`).
///
/// Returns `(P, B, NN_A, NN_B)` as four `PyBytes` blobs containing
/// packed `int64` arrays — the Python wrapper re-wraps via
/// `np.frombuffer(..., dtype=np.int64)`.
///
/// Inputs:
/// * `node_pos_bytes` — `(N, 2)` row-major f32.
/// * `node_body_id_bytes` — `(N,)` u32 (cast from u16 in the wrapper).
/// * `beam_a_bytes` / `beam_b_bytes` — `(B,)` u32 endpoint indices.
/// * `beam_body_bytes` — `(B,)` u32 body id (cast from u16 in wrapper).
/// * `beam_rest_bytes` — `(B,)` f32 rest lengths.
/// * `beam_broken_bytes` — `(B,)` u8 bool flags.
#[pyfunction]
#[pyo3(signature = (
    node_pos_bytes, node_body_id_bytes, n_nodes,
    beam_a_bytes, beam_b_bytes, beam_body_bytes,
    beam_rest_bytes, beam_broken_bytes, n_beams,
    thickness, cell_factor,
))]
#[allow(clippy::too_many_arguments)]
pub fn build_contact_pairs(
    py: Python<'_>,
    node_pos_bytes: &[u8],
    node_body_id_bytes: &[u8],
    n_nodes: usize,
    beam_a_bytes: &[u8],
    beam_b_bytes: &[u8],
    beam_body_bytes: &[u8],
    beam_rest_bytes: &[u8],
    beam_broken_bytes: &[u8],
    n_beams: usize,
    thickness: f32,
    cell_factor: f32,
) -> PyResult<(PyObject, PyObject, PyObject, PyObject)> {
    let empty = || -> PyObject { PyBytes::new_bound(py, &[]).into() };
    if n_nodes == 0 {
        return Ok((empty(), empty(), empty(), empty()));
    }

    // Reinterpret raw byte slices. ``cast_slice`` checks alignment and
    // length divisibility; the wrapper hands us ``.tobytes()`` of a
    // C-contiguous numpy array which is always 8-byte aligned so this
    // is safe in practice.
    let pos: &[f32] = cast_slice(node_pos_bytes);
    if pos.len() < n_nodes * 2 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "node_pos buffer too small",
        ));
    }
    let body_id_n: &[u32] = cast_slice(node_body_id_bytes);
    if body_id_n.len() < n_nodes {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "node_body_id buffer too small",
        ));
    }

    let (beam_a, beam_b, beam_body, beam_broken, max_rest_f) = if n_beams > 0 {
        let a: &[u32] = cast_slice(beam_a_bytes);
        let b: &[u32] = cast_slice(beam_b_bytes);
        let bd: &[u32] = cast_slice(beam_body_bytes);
        let br: &[u8] = beam_broken_bytes;
        let rest: &[f32] = cast_slice(beam_rest_bytes);
        if a.len() < n_beams
            || b.len() < n_beams
            || bd.len() < n_beams
            || br.len() < n_beams
            || rest.len() < n_beams
        {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "beam buffers too small",
            ));
        }
        // ``np.max(rest_length)`` — a NaN-free scan is fine here, rest
        // lengths are always finite positives by construction.
        let mut m = 0.0f32;
        for &r in &rest[..n_beams] {
            if r > m {
                m = r;
            }
        }
        (&a[..n_beams], &b[..n_beams], &bd[..n_beams], &br[..n_beams], m)
    } else {
        (&[][..], &[][..], &[][..], &[][..], thickness * 2.0)
    };

    let cell_size = (max_rest_f * cell_factor)
        .max(thickness * 2.0)
        .max(1e-9);
    let inv_cell = 1.0f32 / cell_size;

    // Per-node cell coords + hash key.
    let mut node_ix = vec![0i64; n_nodes];
    let mut node_iy = vec![0i64; n_nodes];
    let mut node_keys = vec![0i64; n_nodes];
    for i in 0..n_nodes {
        let cx = (pos[2 * i] * inv_cell).floor() as i64;
        let cy = (pos[2 * i + 1] * inv_cell).floor() as i64;
        node_ix[i] = cx;
        node_iy[i] = cy;
        node_keys[i] = pack_key(cx, cy);
    }

    let mut p_out: Vec<i64> = Vec::new();
    let mut b_out: Vec<i64> = Vec::new();
    let mut nodes_with_beam_candidate = vec![false; n_nodes];

    if n_beams > 0 {
        // Build (key, beam-index) entry pairs — one per endpoint, so 2B
        // total. Stable-sort by key to match
        // ``np.argsort(all_keys, kind='stable')``.
        let n_entries = 2 * n_beams;
        let mut entries: Vec<(i64, u32)> = Vec::with_capacity(n_entries);
        for j in 0..n_beams {
            let ai = beam_a[j] as usize;
            let bi = beam_b[j] as usize;
            // Defensive bounds — shouldn't happen but a panic here is
            // far worse than a PyValueError surfaced into Python.
            if ai >= n_nodes || bi >= n_nodes {
                return Err(pyo3::exceptions::PyValueError::new_err(
                    "beam endpoint index out of range",
                ));
            }
            entries.push((node_keys[ai], j as u32));
            entries.push((node_keys[bi], j as u32));
        }
        entries.sort_by_key(|e| e.0);
        // Extract sorted keys into a parallel vec so we can binary-search
        // without comparing the tuple field every time. The beam index
        // stays paired (same index).
        let sorted_keys: Vec<i64> = entries.iter().map(|e| e.0).collect();

        // 3x3 cell offsets — emit order matches the numpy
        // ``_CELL_OFFSETS_9`` construction
        // ``[(di, dj) for di in (-1,0,1) for dj in (-1,0,1)]``.
        const OFFSETS: [(i64, i64); 9] = [
            (-1, -1), (-1, 0), (-1, 1),
            ( 0, -1), ( 0, 0), ( 0, 1),
            ( 1, -1), ( 1, 0), ( 1, 1),
        ];

        let dedup_stride = (n_beams as i64) + 1;
        let mut seen: HashSet<i64> = HashSet::with_capacity(n_nodes * 4);

        if n_nodes >= PARALLEL_NODE_MIN {
            // Chunked parallel gather. Splitting the node range into a
            // handful of large chunks (rather than one rayon task per
            // node) minimises work-stealing dispatch overhead — each
            // chunk does ~50 µs of work which comfortably amortises the
            // few-µs dispatch cost.
            //
            // The flat per-chunk (node_idx, beam_idx) buffers are merged
            // serially in chunk order to keep first-occurrence dedup
            // deterministic.
            let n_threads = rayon::current_num_threads().max(1);
            // Aim for ~4 chunks per thread for some load-balancing
            // headroom, but never less than 256 nodes per chunk.
            let chunk_size = ((n_nodes + (n_threads * 4) - 1)
                / (n_threads * 4))
                .max(256);
            type Chunk = (Vec<u32>, Vec<u32>);
            let chunk_starts: Vec<usize> = (0..n_nodes).step_by(chunk_size).collect();
            let chunks: Vec<Chunk> = chunk_starts
                .par_iter()
                .map(|&start| {
                    let end = (start + chunk_size).min(n_nodes);
                    let approx_cap = (end - start) * 32;
                    let mut node_idxs: Vec<u32> = Vec::with_capacity(approx_cap);
                    let mut beam_idxs: Vec<u32> = Vec::with_capacity(approx_cap);
                    for i in start..end {
                        let cx = node_ix[i];
                        let cy = node_iy[i];
                        let body_i = body_id_n[i];
                        for &(ox, oy) in OFFSETS.iter() {
                            let qkey = pack_key(cx + ox, cy + oy);
                            let lo = sorted_keys.partition_point(|&k| k < qkey);
                            let hi = sorted_keys.partition_point(|&k| k <= qkey);
                            for slot in lo..hi {
                                let j = entries[slot].1 as usize;
                                if beam_broken[j] != 0 {
                                    continue;
                                }
                                if beam_body[j] == body_i {
                                    continue;
                                }
                                if beam_a[j] as usize == i || beam_b[j] as usize == i {
                                    continue;
                                }
                                node_idxs.push(i as u32);
                                beam_idxs.push(j as u32);
                            }
                        }
                    }
                    (node_idxs, beam_idxs)
                })
                .collect();
            for (node_idxs, beam_idxs) in chunks.iter() {
                for (&i_u, &j_u) in node_idxs.iter().zip(beam_idxs.iter()) {
                    let i = i_u as usize;
                    let j = j_u as usize;
                    let key = (i as i64) * dedup_stride + j as i64;
                    if seen.insert(key) {
                        p_out.push(i as i64);
                        b_out.push(j as i64);
                        nodes_with_beam_candidate[i] = true;
                    }
                }
            }
        } else {
            // Serial path: inline everything to avoid the per-node Vec
            // allocation that the parallel gather requires.
            for i in 0..n_nodes {
                let cx = node_ix[i];
                let cy = node_iy[i];
                let body_i = body_id_n[i];
                for &(ox, oy) in OFFSETS.iter() {
                    let qkey = pack_key(cx + ox, cy + oy);
                    let lo = sorted_keys.partition_point(|&k| k < qkey);
                    let hi = sorted_keys.partition_point(|&k| k <= qkey);
                    for slot in lo..hi {
                        let j = entries[slot].1 as usize;
                        if beam_broken[j] != 0 {
                            continue;
                        }
                        if beam_body[j] == body_i {
                            continue;
                        }
                        if beam_a[j] as usize == i || beam_b[j] as usize == i {
                            continue;
                        }
                        let key = (i as i64) * dedup_stride + j as i64;
                        if seen.insert(key) {
                            p_out.push(i as i64);
                            b_out.push(j as i64);
                            nodes_with_beam_candidate[i] = true;
                        }
                    }
                }
            }
        }
    }

    // Node-node fallback over ``~nodes_with_beam_candidate``.
    let mut nn_a_out: Vec<i64> = Vec::new();
    let mut nn_b_out: Vec<i64> = Vec::new();
    let fallback: Vec<usize> = (0..n_nodes)
        .filter(|&i| !nodes_with_beam_candidate[i])
        .collect();

    if !fallback.is_empty() {
        // Stable-sort all nodes by cell key.
        let mut node_entries: Vec<(i64, u32)> = (0..n_nodes)
            .map(|i| (node_keys[i], i as u32))
            .collect();
        node_entries.sort_by_key(|e| e.0);
        let sorted_node_keys: Vec<i64> = node_entries.iter().map(|e| e.0).collect();

        const OFFSETS: [(i64, i64); 9] = [
            (-1, -1), (-1, 0), (-1, 1),
            ( 0, -1), ( 0, 0), ( 0, 1),
            ( 1, -1), ( 1, 0), ( 1, 1),
        ];

        let dedup_stride = (n_nodes as i64) + 1;
        let mut seen: HashSet<i64> = HashSet::with_capacity(fallback.len() * 4);

        if fallback.len() >= PARALLEL_NODE_MIN {
            // Parallel gather over fallback nodes (read-only access to
            // sorted_node_keys / node_entries / body_id_n).
            let gather = |i: usize| -> Vec<u32> {
                let cx = node_ix[i];
                let cy = node_iy[i];
                let body_i = body_id_n[i];
                let mut local: Vec<u32> = Vec::new();
                for &(ox, oy) in OFFSETS.iter() {
                    let qkey = pack_key(cx + ox, cy + oy);
                    let lo = sorted_node_keys.partition_point(|&k| k < qkey);
                    let hi = sorted_node_keys.partition_point(|&k| k <= qkey);
                    for slot in lo..hi {
                        let j = node_entries[slot].1 as usize;
                        if body_id_n[j] == body_i {
                            continue;
                        }
                        if i >= j {
                            continue;
                        }
                        local.push(j as u32);
                    }
                }
                local
            };
            let per_node_cands: Vec<Vec<u32>> =
                fallback.par_iter().map(|&i| gather(i)).collect();
            for (idx, &i) in fallback.iter().enumerate() {
                for &jb in per_node_cands[idx].iter() {
                    let j = jb as usize;
                    let key = (i as i64) * dedup_stride + j as i64;
                    if seen.insert(key) {
                        nn_a_out.push(i as i64);
                        nn_b_out.push(j as i64);
                    }
                }
            }
        } else {
            // Serial path: inline everything.
            for &i in &fallback {
                let cx = node_ix[i];
                let cy = node_iy[i];
                let body_i = body_id_n[i];
                for &(ox, oy) in OFFSETS.iter() {
                    let qkey = pack_key(cx + ox, cy + oy);
                    let lo = sorted_node_keys.partition_point(|&k| k < qkey);
                    let hi = sorted_node_keys.partition_point(|&k| k <= qkey);
                    for slot in lo..hi {
                        let j = node_entries[slot].1 as usize;
                        if body_id_n[j] == body_i {
                            continue;
                        }
                        if i >= j {
                            continue;
                        }
                        let key = (i as i64) * dedup_stride + j as i64;
                        if seen.insert(key) {
                            nn_a_out.push(i as i64);
                            nn_b_out.push(j as i64);
                        }
                    }
                }
            }
        }
    }

    let p_bytes: &[u8] = cast_slice(&p_out);
    let b_bytes: &[u8] = cast_slice(&b_out);
    let nna_bytes: &[u8] = cast_slice(&nn_a_out);
    let nnb_bytes: &[u8] = cast_slice(&nn_b_out);
    Ok((
        PyBytes::new_bound(py, p_bytes).into(),
        PyBytes::new_bound(py, b_bytes).into(),
        PyBytes::new_bound(py, nna_bytes).into(),
        PyBytes::new_bound(py, nnb_bytes).into(),
    ))
}

/// XPBD projection for node-beam contact candidate pairs.
///
/// Mirrors `_project_node_beam_contacts` in
/// `python/slappyengine/softbody/collision.py`:
/// 1. For each (node, beam) candidate, compute the closest point on the
///    beam segment (parameter `t` clamped to `[0, 1]`).
/// 2. Compute the penetration depth into a thickness-radius sleeve
///    around the segment. Skip pairs that aren't penetrating.
/// 3. Solve the XPBD position constraint:
///    `dlambda = (radius - dist) / (w_n + w_a*(1-t) + w_c*t + alpha)`
///    where `alpha = 1 / (stiffness * sub_dt^2)`.
/// 4. Scatter the resulting correction vector into the three involved
///    nodes (P, A, C) in input-array order, in three separate passes —
///    this preserves the exact float-summation order produced by the
///    sequence of three numpy `np.add.at` calls. The block-on-block
///    contact test depends on this ordering (penetration tolerance
///    bumps from ~0.008 → 0.22+ when reordered).
///
/// All inputs except `pos_xy` are read-only `bytes`-style buffers;
/// `pos_xy` is `(N, 2)` row-major f32 and is mutated in place.
#[pyfunction]
#[pyo3(signature = (
    pos_xy, inv_mass, beam_a, beam_b, p_nodes, b_beams,
    thickness, stiffness, sub_dt, eps,
))]
#[allow(clippy::too_many_arguments)]
pub fn project_node_beam_contacts(
    pos_xy: &Bound<'_, PyAny>,
    inv_mass: &[u8],
    beam_a: &[u8],
    beam_b: &[u8],
    p_nodes: &[u8],
    b_beams: &[u8],
    thickness: f32,
    stiffness: f32,
    sub_dt: f32,
    eps: f32,
) -> PyResult<()> {
    let pos_buf = PyBuffer::<f32>::get_bound(pos_xy)?;
    let pos: &mut [f32] = unsafe { as_slice_mut(&pos_buf)? };
    let inv_mass: &[f32] = cast_slice(inv_mass);
    let beam_a: &[u32] = cast_slice(beam_a);
    let beam_b: &[u32] = cast_slice(beam_b);
    let p_nodes: &[i64] = cast_slice(p_nodes);
    let b_beams: &[i64] = cast_slice(b_beams);

    if p_nodes.len() != b_beams.len() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "p_nodes and b_beams must share length",
        ));
    }
    if beam_a.len() != beam_b.len() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "beam_a and beam_b must share length",
        ));
    }

    let n_pairs = p_nodes.len();
    if n_pairs == 0 {
        return Ok(());
    }

    let n_nodes = inv_mass.len();
    if pos.len() != n_nodes * 2 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "pos_xy size inconsistent with inv_mass",
        ));
    }

    let contact_radius = thickness;
    // Match numpy: alpha = 1.0 / max(stiffness * sub_dt * sub_dt, eps).
    let alpha = 1.0f32 / (stiffness * sub_dt * sub_dt).max(eps);

    // Pre-pass: compute the correction vector for every pair from a
    // snapshot of positions — exactly as numpy does before its three
    // `np.add.at` scatters. Pairs that aren't violated produce zero
    // correction (we still need to walk them so output ordering stays
    // identical to the input pair array). This phase is read-only on
    // ``pos`` so it parallelizes trivially over the pair list.
    //
    // We track an out-of-bounds flag atomically rather than bubble a
    // PyResult out of the inner closure; bounds violations are
    // defensive (shouldn't happen in normal operation), so the rare
    // failure path takes a slow recheck.
    let mut corr_x = vec![0.0f32; n_pairs];
    let mut corr_y = vec![0.0f32; n_pairs];
    let mut w_n_arr = vec![0.0f32; n_pairs];
    let mut w_a_arr = vec![0.0f32; n_pairs];
    let mut w_c_arr = vec![0.0f32; n_pairs];
    let mut active = vec![false; n_pairs];
    let mut a_idx = vec![0usize; n_pairs];
    let mut c_idx = vec![0usize; n_pairs];
    let beam_a_len = beam_a.len();
    use std::sync::atomic::{AtomicBool, Ordering};
    let oob = AtomicBool::new(false);

    // ``compute_one`` writes into the pre-allocated SoA slots, avoiding
    // any per-iteration allocation. This makes the parallel and serial
    // paths share code via a closure operating on slot references.
    let compute_one = |i: usize,
                       cx: &mut f32,
                       cy: &mut f32,
                       wn: &mut f32,
                       wa: &mut f32,
                       wc: &mut f32,
                       ac: &mut bool,
                       ai_slot: &mut usize,
                       ci_slot: &mut usize| {
        let ni = p_nodes[i] as usize;
        let bi = b_beams[i] as usize;
        if ni >= n_nodes || bi >= beam_a_len {
            oob.store(true, Ordering::Relaxed);
            return;
        }
        let ai = beam_a[bi] as usize;
        let ci = beam_b[bi] as usize;
        *ai_slot = ai;
        *ci_slot = ci;

        let p_nx = pos[2 * ni];
        let p_ny = pos[2 * ni + 1];
        let p_ax = pos[2 * ai];
        let p_ay = pos[2 * ai + 1];
        let p_cx = pos[2 * ci];
        let p_cy = pos[2 * ci + 1];

        let seg_x = p_cx - p_ax;
        let seg_y = p_cy - p_ay;
        let seg_len_sq = seg_x * seg_x + seg_y * seg_y;
        let safe_seg = seg_len_sq.max(eps * eps);
        let t_raw = ((p_nx - p_ax) * seg_x + (p_ny - p_ay) * seg_y) / safe_seg;
        let t = t_raw.clamp(0.0, 1.0);

        let cl_x = p_ax + seg_x * t;
        let cl_y = p_ay + seg_y * t;
        let dx = p_nx - cl_x;
        let dy = p_ny - cl_y;
        let dist_sq = dx * dx + dy * dy;
        let dist = dist_sq.max(eps * eps).sqrt();

        if dist >= contact_radius {
            return;
        }

        let nx = dx / dist;
        let ny = dy / dist;
        let c_val = contact_radius - dist;

        let w_n = inv_mass[ni];
        let w_a = inv_mass[ai] * (1.0 - t);
        let w_c = inv_mass[ci] * t;

        let denom_raw = w_n + w_a + w_c + alpha;
        let denom = if denom_raw < eps { 1.0 } else { denom_raw };
        let dlambda = c_val / denom;

        *cx = nx * dlambda;
        *cy = ny * dlambda;
        *wn = w_n;
        *wa = w_a;
        *wc = w_c;
        *ac = true;
    };

    if n_pairs >= PARALLEL_PAIR_MIN {
        // Chunked parallel compute — split the pair range into ~4 chunks
        // per thread, each thread runs a tight serial inner loop over its
        // chunk writing into disjoint SoA slots. This avoids the
        // ``par_iter_mut().zip(...)`` overhead of producing one rayon task
        // per element.
        let n_threads = rayon::current_num_threads().max(1);
        let chunk_size = ((n_pairs + (n_threads * 4) - 1)
            / (n_threads * 4))
            .max(256);
        // Slice each SoA output into matching chunks (par_chunks_mut on a
        // single Vec ensures the chunks are exclusive); zip them so each
        // task receives matching chunks of every output array.
        corr_x
            .par_chunks_mut(chunk_size)
            .zip(corr_y.par_chunks_mut(chunk_size))
            .zip(w_n_arr.par_chunks_mut(chunk_size))
            .zip(w_a_arr.par_chunks_mut(chunk_size))
            .zip(w_c_arr.par_chunks_mut(chunk_size))
            .zip(active.par_chunks_mut(chunk_size))
            .zip(a_idx.par_chunks_mut(chunk_size))
            .zip(c_idx.par_chunks_mut(chunk_size))
            .enumerate()
            .for_each(
                |(chunk_idx, (((((((cx, cy), wn), wa), wc), ac), ai_arr), ci_arr))| {
                    let start = chunk_idx * chunk_size;
                    for k in 0..cx.len() {
                        compute_one(
                            start + k,
                            &mut cx[k],
                            &mut cy[k],
                            &mut wn[k],
                            &mut wa[k],
                            &mut wc[k],
                            &mut ac[k],
                            &mut ai_arr[k],
                            &mut ci_arr[k],
                        );
                    }
                },
            );
    } else {
        for i in 0..n_pairs {
            let ni = p_nodes[i] as usize;
            let bi = b_beams[i] as usize;
            if ni >= n_nodes || bi >= beam_a_len {
                return Err(pyo3::exceptions::PyValueError::new_err(
                    "contact pair index out of range",
                ));
            }
            let ai = beam_a[bi] as usize;
            let ci = beam_b[bi] as usize;
            a_idx[i] = ai;
            c_idx[i] = ci;

            let p_nx = pos[2 * ni];
            let p_ny = pos[2 * ni + 1];
            let p_ax = pos[2 * ai];
            let p_ay = pos[2 * ai + 1];
            let p_cx = pos[2 * ci];
            let p_cy = pos[2 * ci + 1];

            let seg_x = p_cx - p_ax;
            let seg_y = p_cy - p_ay;
            let seg_len_sq = seg_x * seg_x + seg_y * seg_y;
            let safe_seg = seg_len_sq.max(eps * eps);
            let t_raw = ((p_nx - p_ax) * seg_x + (p_ny - p_ay) * seg_y) / safe_seg;
            let t = t_raw.clamp(0.0, 1.0);

            let cl_x = p_ax + seg_x * t;
            let cl_y = p_ay + seg_y * t;
            let dx = p_nx - cl_x;
            let dy = p_ny - cl_y;
            let dist_sq = dx * dx + dy * dy;
            let dist = dist_sq.max(eps * eps).sqrt();

            if dist >= contact_radius {
                continue;
            }

            let nx = dx / dist;
            let ny = dy / dist;
            let c_val = contact_radius - dist;

            let w_n = inv_mass[ni];
            let w_a = inv_mass[ai] * (1.0 - t);
            let w_c = inv_mass[ci] * t;

            let denom_raw = w_n + w_a + w_c + alpha;
            let denom = if denom_raw < eps { 1.0 } else { denom_raw };
            let dlambda = c_val / denom;

            corr_x[i] = nx * dlambda;
            corr_y[i] = ny * dlambda;
            w_n_arr[i] = w_n;
            w_a_arr[i] = w_a;
            w_c_arr[i] = w_c;
            active[i] = true;
        }
    }

    if oob.load(Ordering::Relaxed) {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "contact pair index out of range",
        ));
    }

    // Pass 1: scatter +corr * w_n into node P (matches first
    // ``np.add.at(pos, P, corr * w_n[:, None])``).
    for i in 0..n_pairs {
        if !active[i] {
            continue;
        }
        let ni = p_nodes[i] as usize;
        let w = w_n_arr[i];
        pos[2 * ni]     += corr_x[i] * w;
        pos[2 * ni + 1] += corr_y[i] * w;
    }
    // Pass 2: scatter -corr * w_a into node A.
    for i in 0..n_pairs {
        if !active[i] {
            continue;
        }
        let ai = a_idx[i];
        let w = w_a_arr[i];
        pos[2 * ai]     += -corr_x[i] * w;
        pos[2 * ai + 1] += -corr_y[i] * w;
    }
    // Pass 3: scatter -corr * w_c into node C.
    for i in 0..n_pairs {
        if !active[i] {
            continue;
        }
        let ci = c_idx[i];
        let w = w_c_arr[i];
        pos[2 * ci]     += -corr_x[i] * w;
        pos[2 * ci + 1] += -corr_y[i] * w;
    }

    Ok(())
}

/// XPBD projection for node-node contact candidate pairs (the fallback
/// when neither endpoint touches a beam-candidate body).
///
/// Mirrors `_project_node_node_pairs` in
/// `python/slappyengine/softbody/collision.py`. The contact radius is
/// ``2.0 * thickness`` (sum of two node sleeves). Two scatter passes,
/// one per endpoint, in input-array order to preserve float-summation
/// order of the two `np.add.at` calls.
#[pyfunction]
#[pyo3(signature = (
    pos_xy, inv_mass, nn_a, nn_b,
    thickness, stiffness, sub_dt, eps,
))]
#[allow(clippy::too_many_arguments)]
pub fn project_node_node_pairs(
    pos_xy: &Bound<'_, PyAny>,
    inv_mass: &[u8],
    nn_a: &[u8],
    nn_b: &[u8],
    thickness: f32,
    stiffness: f32,
    sub_dt: f32,
    eps: f32,
) -> PyResult<()> {
    let pos_buf = PyBuffer::<f32>::get_bound(pos_xy)?;
    let pos: &mut [f32] = unsafe { as_slice_mut(&pos_buf)? };
    let inv_mass: &[f32] = cast_slice(inv_mass);
    let nn_a: &[i64] = cast_slice(nn_a);
    let nn_b: &[i64] = cast_slice(nn_b);

    if nn_a.len() != nn_b.len() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "nn_a and nn_b must share length",
        ));
    }

    let n_pairs = nn_a.len();
    if n_pairs == 0 {
        return Ok(());
    }

    let n_nodes = inv_mass.len();
    if pos.len() != n_nodes * 2 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "pos_xy size inconsistent with inv_mass",
        ));
    }

    let contact_radius = 2.0f32 * thickness;
    let alpha = 1.0f32 / (stiffness * sub_dt * sub_dt).max(eps);

    let mut corr_x = vec![0.0f32; n_pairs];
    let mut corr_y = vec![0.0f32; n_pairs];
    let mut w_a_arr = vec![0.0f32; n_pairs];
    let mut w_b_arr = vec![0.0f32; n_pairs];
    let mut active = vec![false; n_pairs];
    use std::sync::atomic::{AtomicBool, Ordering};
    let oob = AtomicBool::new(false);

    let body = |i: usize, cx: &mut f32, cy: &mut f32, wa: &mut f32, wb: &mut f32, ac: &mut bool| {
        let ai = nn_a[i] as usize;
        let bi = nn_b[i] as usize;
        if ai >= n_nodes || bi >= n_nodes {
            oob.store(true, Ordering::Relaxed);
            return;
        }
        let dx = pos[2 * ai] - pos[2 * bi];
        let dy = pos[2 * ai + 1] - pos[2 * bi + 1];
        let dist_sq = dx * dx + dy * dy;
        let dist = dist_sq.max(eps * eps).sqrt();
        if dist >= contact_radius {
            return;
        }
        let nx = dx / dist;
        let ny = dy / dist;
        let c_val = contact_radius - dist;
        let w_a = inv_mass[ai];
        let w_b = inv_mass[bi];
        let denom_raw = w_a + w_b + alpha;
        let denom = if denom_raw < eps { 1.0 } else { denom_raw };
        let dlambda = c_val / denom;
        *cx = nx * dlambda;
        *cy = ny * dlambda;
        *wa = w_a;
        *wb = w_b;
        *ac = true;
    };

    if n_pairs >= PARALLEL_PAIR_MIN {
        let n_threads = rayon::current_num_threads().max(1);
        let chunk_size = ((n_pairs + (n_threads * 4) - 1)
            / (n_threads * 4))
            .max(256);
        corr_x
            .par_chunks_mut(chunk_size)
            .zip(corr_y.par_chunks_mut(chunk_size))
            .zip(w_a_arr.par_chunks_mut(chunk_size))
            .zip(w_b_arr.par_chunks_mut(chunk_size))
            .zip(active.par_chunks_mut(chunk_size))
            .enumerate()
            .for_each(|(chunk_idx, ((((cx, cy), wa), wb), ac))| {
                let start = chunk_idx * chunk_size;
                for k in 0..cx.len() {
                    body(
                        start + k,
                        &mut cx[k],
                        &mut cy[k],
                        &mut wa[k],
                        &mut wb[k],
                        &mut ac[k],
                    );
                }
            });
    } else {
        for i in 0..n_pairs {
            let ai = nn_a[i] as usize;
            let bi = nn_b[i] as usize;
            if ai >= n_nodes || bi >= n_nodes {
                return Err(pyo3::exceptions::PyValueError::new_err(
                    "node-node pair index out of range",
                ));
            }
            let dx = pos[2 * ai] - pos[2 * bi];
            let dy = pos[2 * ai + 1] - pos[2 * bi + 1];
            let dist_sq = dx * dx + dy * dy;
            let dist = dist_sq.max(eps * eps).sqrt();
            if dist >= contact_radius {
                continue;
            }
            let nx = dx / dist;
            let ny = dy / dist;
            let c_val = contact_radius - dist;
            let w_a = inv_mass[ai];
            let w_b = inv_mass[bi];
            let denom_raw = w_a + w_b + alpha;
            let denom = if denom_raw < eps { 1.0 } else { denom_raw };
            let dlambda = c_val / denom;
            corr_x[i] = nx * dlambda;
            corr_y[i] = ny * dlambda;
            w_a_arr[i] = w_a;
            w_b_arr[i] = w_b;
            active[i] = true;
        }
    }
    let _ = body; // closure used only in parallel path

    if oob.load(Ordering::Relaxed) {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "node-node pair index out of range",
        ));
    }

    // Pass A: scatter +corr * w_a into endpoint A.
    for i in 0..n_pairs {
        if !active[i] {
            continue;
        }
        let ai = nn_a[i] as usize;
        let w = w_a_arr[i];
        pos[2 * ai]     += corr_x[i] * w;
        pos[2 * ai + 1] += corr_y[i] * w;
    }
    // Pass B: scatter -corr * w_b into endpoint B.
    for i in 0..n_pairs {
        if !active[i] {
            continue;
        }
        let bi = nn_b[i] as usize;
        let w = w_b_arr[i];
        pos[2 * bi]     += -corr_x[i] * w;
        pos[2 * bi + 1] += -corr_y[i] * w;
    }

    Ok(())
}

// ────────────────────────────────────────────────────────────────────────
// Tier 10: full softbody step in Rust.
//
// Moves the entire body of `solver.py::step()` into native code so the
// substeps × iters Python loop (8 × 4 = 32 by default, or 8 × 20 = 160
// for the big-scene benchmark) no longer pays per-iter PyO3 dispatch
// overhead.
//
// Reuses the *math* from the kernels above by extracting the inner
// scalar walks into private `_inner` helpers that operate on raw
// slices. The single-kernel PyO3 entry points still call these helpers,
// so we keep one source of truth for the precision-sensitive math
// while avoiding any duplicated logic.
// ────────────────────────────────────────────────────────────────────────

/// Inner scalar/SIMD-able implementation of XPBD distance projection.
///
/// Operates on raw slices — no PyO3 / no buffer protocol. Used both by
/// the existing single-call `project_distance_constraints` PyO3 entry
/// point (via thin slice-grab wrapper) and by `slappyengine_step`.
#[allow(clippy::too_many_arguments)]
fn project_distance_constraints_inner(
    pos: &mut [f32],
    inv_mass: &[f32],
    na: &[u32],
    nb: &[u32],
    rest: &[f32],
    stiff: &[f32],
    broken: &[u8],
    relax: &[f32],
    sub_dt: f32,
    eps: f32,
    corr_x: &mut [f32],
    corr_y: &mut [f32],
) {
    let n_beams = na.len();
    if n_beams == 0 {
        return;
    }
    let inv_dt2 = 1.0f32 / (sub_dt * sub_dt);
    let n_nodes = inv_mass.len();

    // Mirror the closure form in the PyO3 entry; kept here so the inner
    // path is self-contained.
    let compute_beams = |start: usize,
                         cx_chunk: &mut [f32],
                         cy_chunk: &mut [f32]| {
        for k in 0..cx_chunk.len() {
            let i = start + k;
            if broken[i] != 0 {
                cx_chunk[k] = 0.0;
                cy_chunk[k] = 0.0;
                continue;
            }
            let ai = na[i] as usize;
            let bi = nb[i] as usize;
            debug_assert!(ai < n_nodes && bi < n_nodes);
            let pax = pos[2 * ai];
            let pay = pos[2 * ai + 1];
            let pbx = pos[2 * bi];
            let pby = pos[2 * bi + 1];
            let dx = pbx - pax;
            let dy = pby - pay;
            let length_sq = dx * dx + dy * dy;
            let length = length_sq.sqrt();
            let safe_len = if length > eps { length } else { eps };
            let dir_x = dx / safe_len;
            let dir_y = dy / safe_len;
            let r = rest[i];
            let s = stiff[i];
            let alpha = inv_dt2 / s.max(eps);
            let w_a = inv_mass[ai];
            let w_b = inv_mass[bi];
            let denom_raw = w_a + w_b + alpha;
            let denom = if denom_raw < eps { 1.0 } else { denom_raw };
            let c = length - r;
            let dlambda = -c / denom;
            cx_chunk[k] = dir_x * dlambda;
            cy_chunk[k] = dir_y * dlambda;
        }
    };

    if n_beams >= PARALLEL_DIST_BEAM_MIN {
        let n_threads = rayon::current_num_threads().max(1);
        let chunk_size = ((n_beams + (n_threads * 4) - 1) / (n_threads * 4)).max(256);
        corr_x
            .par_chunks_mut(chunk_size)
            .zip(corr_y.par_chunks_mut(chunk_size))
            .enumerate()
            .for_each(|(chunk_idx, (cx, cy))| {
                let start = chunk_idx * chunk_size;
                compute_beams(start, cx, cy);
            });
    } else {
        compute_beams(0, &mut corr_x[..n_beams], &mut corr_y[..n_beams]);
    }

    // Two scatter passes in beam order — preserves np.add.at ordering.
    for i in 0..n_beams {
        if broken[i] != 0 {
            continue;
        }
        let ai = na[i] as usize;
        let scale = inv_mass[ai] * relax[ai];
        pos[2 * ai]     += -corr_x[i] * scale;
        pos[2 * ai + 1] += -corr_y[i] * scale;
    }
    for i in 0..n_beams {
        if broken[i] != 0 {
            continue;
        }
        let bi = nb[i] as usize;
        let scale = inv_mass[bi] * relax[bi];
        pos[2 * bi]     +=  corr_x[i] * scale;
        pos[2 * bi + 1] +=  corr_y[i] * scale;
    }
}

/// Inner plasticity walk. Mutates `rest` in place.
fn apply_plasticity_inner(
    pos: &[f32],
    rest: &mut [f32],
    na: &[u32],
    nb: &[u32],
    ys: &[f32],
    pr: &[f32],
    broken: &[u8],
    sub_dt: f32,
    eps: f32,
) {
    let n_beams = na.len();
    if n_beams == 0 {
        return;
    }
    let update = |i: usize, r_slot: &mut f32| {
        if broken[i] != 0 {
            return;
        }
        let ai = na[i] as usize;
        let bi = nb[i] as usize;
        let dx = pos[2 * bi] - pos[2 * ai];
        let dy = pos[2 * bi + 1] - pos[2 * ai + 1];
        let length = (dx * dx + dy * dy).sqrt();
        let r = *r_slot;
        let safe_rest = r.max(eps);
        let strain = (length - r) / safe_rest;
        let abs_strain = strain.abs();
        let y_strain = ys[i];
        if abs_strain <= y_strain {
            return;
        }
        let sign_strain: f32 = if strain > 0.0 {
            1.0
        } else if strain < 0.0 {
            -1.0
        } else {
            0.0
        };
        let denom = 1.0 + sign_strain * y_strain;
        let target_rest = length / denom.max(eps);
        let blend = 1.0 - (-pr[i] * sub_dt).exp();
        *r_slot = r * (1.0 - blend) + target_rest * blend;
    };
    if n_beams >= PARALLEL_BEAM_MIN {
        rest.par_iter_mut().enumerate().for_each(|(i, r_slot)| update(i, r_slot));
    } else {
        for (i, r_slot) in rest.iter_mut().enumerate() {
            update(i, r_slot);
        }
    }
}

/// Inner mark-breaks walk. Mutates `broken` in place (OR'd).
fn mark_breaks_inner(
    pos: &[f32],
    rest: &[f32],
    na: &[u32],
    nb: &[u32],
    bs: &[f32],
    broken: &mut [u8],
    eps: f32,
) {
    let n_beams = na.len();
    if n_beams == 0 {
        return;
    }
    let update = |i: usize, b_slot: &mut u8| {
        if *b_slot != 0 {
            return;
        }
        let ai = na[i] as usize;
        let bi = nb[i] as usize;
        let dx = pos[2 * bi] - pos[2 * ai];
        let dy = pos[2 * bi + 1] - pos[2 * ai + 1];
        let length = (dx * dx + dy * dy).sqrt();
        let r = rest[i];
        let safe_rest = r.max(eps);
        let deviation = (length - r).abs() / safe_rest;
        if deviation > bs[i] {
            *b_slot = 1;
        }
    };
    if n_beams >= PARALLEL_BEAM_MIN {
        broken.par_iter_mut().enumerate().for_each(|(i, b_slot)| update(i, b_slot));
    } else {
        for (i, b_slot) in broken.iter_mut().enumerate() {
            update(i, b_slot);
        }
    }
}

/// Inner build of contact-candidate pair lists.
///
/// Produces packed (i64) vectors mirroring the original `np.add.at`
/// emit order so float-summation order downstream is unchanged.
#[allow(clippy::too_many_arguments)]
fn build_contact_pairs_inner(
    pos: &[f32],
    body_id_n: &[u32],
    n_nodes: usize,
    beam_a: &[u32],
    beam_b: &[u32],
    beam_body: &[u32],
    beam_rest: &[f32],
    beam_broken: &[u8],
    n_beams: usize,
    thickness: f32,
    cell_factor: f32,
) -> (Vec<i64>, Vec<i64>, Vec<i64>, Vec<i64>) {
    if n_nodes == 0 {
        return (Vec::new(), Vec::new(), Vec::new(), Vec::new());
    }
    let max_rest_f = if n_beams > 0 {
        let mut m = 0.0f32;
        for &r in &beam_rest[..n_beams] {
            if r > m {
                m = r;
            }
        }
        m
    } else {
        thickness * 2.0
    };
    let cell_size = (max_rest_f * cell_factor)
        .max(thickness * 2.0)
        .max(1e-9);
    let inv_cell = 1.0f32 / cell_size;
    let mut node_ix = vec![0i64; n_nodes];
    let mut node_iy = vec![0i64; n_nodes];
    let mut node_keys = vec![0i64; n_nodes];
    for i in 0..n_nodes {
        let cx = (pos[2 * i] * inv_cell).floor() as i64;
        let cy = (pos[2 * i + 1] * inv_cell).floor() as i64;
        node_ix[i] = cx;
        node_iy[i] = cy;
        node_keys[i] = pack_key(cx, cy);
    }

    let mut p_out: Vec<i64> = Vec::new();
    let mut b_out: Vec<i64> = Vec::new();
    let mut nodes_with_beam_candidate = vec![false; n_nodes];

    if n_beams > 0 {
        let n_entries = 2 * n_beams;
        let mut entries: Vec<(i64, u32)> = Vec::with_capacity(n_entries);
        for j in 0..n_beams {
            let ai = beam_a[j] as usize;
            let bi = beam_b[j] as usize;
            // Defensive: invalid endpoint indices are silently dropped so
            // the caller doesn't have to handle PyResult bubbling.
            if ai >= n_nodes || bi >= n_nodes {
                continue;
            }
            entries.push((node_keys[ai], j as u32));
            entries.push((node_keys[bi], j as u32));
        }
        entries.sort_by_key(|e| e.0);
        let sorted_keys: Vec<i64> = entries.iter().map(|e| e.0).collect();

        const OFFSETS: [(i64, i64); 9] = [
            (-1, -1), (-1, 0), (-1, 1),
            ( 0, -1), ( 0, 0), ( 0, 1),
            ( 1, -1), ( 1, 0), ( 1, 1),
        ];
        let dedup_stride = (n_beams as i64) + 1;
        let mut seen: HashSet<i64> = HashSet::with_capacity(n_nodes * 4);

        if n_nodes >= PARALLEL_NODE_MIN {
            let n_threads = rayon::current_num_threads().max(1);
            let chunk_size = ((n_nodes + (n_threads * 4) - 1) / (n_threads * 4)).max(256);
            type Chunk = (Vec<u32>, Vec<u32>);
            let chunk_starts: Vec<usize> = (0..n_nodes).step_by(chunk_size).collect();
            let chunks: Vec<Chunk> = chunk_starts
                .par_iter()
                .map(|&start| {
                    let end = (start + chunk_size).min(n_nodes);
                    let approx_cap = (end - start) * 32;
                    let mut node_idxs: Vec<u32> = Vec::with_capacity(approx_cap);
                    let mut beam_idxs: Vec<u32> = Vec::with_capacity(approx_cap);
                    for i in start..end {
                        let cx = node_ix[i];
                        let cy = node_iy[i];
                        let body_i = body_id_n[i];
                        for &(ox, oy) in OFFSETS.iter() {
                            let qkey = pack_key(cx + ox, cy + oy);
                            let lo = sorted_keys.partition_point(|&k| k < qkey);
                            let hi = sorted_keys.partition_point(|&k| k <= qkey);
                            for slot in lo..hi {
                                let j = entries[slot].1 as usize;
                                if beam_broken[j] != 0 {
                                    continue;
                                }
                                if beam_body[j] == body_i {
                                    continue;
                                }
                                if beam_a[j] as usize == i || beam_b[j] as usize == i {
                                    continue;
                                }
                                node_idxs.push(i as u32);
                                beam_idxs.push(j as u32);
                            }
                        }
                    }
                    (node_idxs, beam_idxs)
                })
                .collect();
            for (node_idxs, beam_idxs) in chunks.iter() {
                for (&i_u, &j_u) in node_idxs.iter().zip(beam_idxs.iter()) {
                    let i = i_u as usize;
                    let j = j_u as usize;
                    let key = (i as i64) * dedup_stride + j as i64;
                    if seen.insert(key) {
                        p_out.push(i as i64);
                        b_out.push(j as i64);
                        nodes_with_beam_candidate[i] = true;
                    }
                }
            }
        } else {
            for i in 0..n_nodes {
                let cx = node_ix[i];
                let cy = node_iy[i];
                let body_i = body_id_n[i];
                for &(ox, oy) in OFFSETS.iter() {
                    let qkey = pack_key(cx + ox, cy + oy);
                    let lo = sorted_keys.partition_point(|&k| k < qkey);
                    let hi = sorted_keys.partition_point(|&k| k <= qkey);
                    for slot in lo..hi {
                        let j = entries[slot].1 as usize;
                        if beam_broken[j] != 0 {
                            continue;
                        }
                        if beam_body[j] == body_i {
                            continue;
                        }
                        if beam_a[j] as usize == i || beam_b[j] as usize == i {
                            continue;
                        }
                        let key = (i as i64) * dedup_stride + j as i64;
                        if seen.insert(key) {
                            p_out.push(i as i64);
                            b_out.push(j as i64);
                            nodes_with_beam_candidate[i] = true;
                        }
                    }
                }
            }
        }
    }

    let mut nn_a_out: Vec<i64> = Vec::new();
    let mut nn_b_out: Vec<i64> = Vec::new();
    let fallback: Vec<usize> = (0..n_nodes)
        .filter(|&i| !nodes_with_beam_candidate[i])
        .collect();

    if !fallback.is_empty() {
        let mut node_entries: Vec<(i64, u32)> = (0..n_nodes)
            .map(|i| (node_keys[i], i as u32))
            .collect();
        node_entries.sort_by_key(|e| e.0);
        let sorted_node_keys: Vec<i64> = node_entries.iter().map(|e| e.0).collect();

        const OFFSETS: [(i64, i64); 9] = [
            (-1, -1), (-1, 0), (-1, 1),
            ( 0, -1), ( 0, 0), ( 0, 1),
            ( 1, -1), ( 1, 0), ( 1, 1),
        ];
        let dedup_stride = (n_nodes as i64) + 1;
        let mut seen: HashSet<i64> = HashSet::with_capacity(fallback.len() * 4);

        if fallback.len() >= PARALLEL_NODE_MIN {
            let gather = |i: usize| -> Vec<u32> {
                let cx = node_ix[i];
                let cy = node_iy[i];
                let body_i = body_id_n[i];
                let mut local: Vec<u32> = Vec::new();
                for &(ox, oy) in OFFSETS.iter() {
                    let qkey = pack_key(cx + ox, cy + oy);
                    let lo = sorted_node_keys.partition_point(|&k| k < qkey);
                    let hi = sorted_node_keys.partition_point(|&k| k <= qkey);
                    for slot in lo..hi {
                        let j = node_entries[slot].1 as usize;
                        if body_id_n[j] == body_i {
                            continue;
                        }
                        if i >= j {
                            continue;
                        }
                        local.push(j as u32);
                    }
                }
                local
            };
            let per_node_cands: Vec<Vec<u32>> =
                fallback.par_iter().map(|&i| gather(i)).collect();
            for (idx, &i) in fallback.iter().enumerate() {
                for &jb in per_node_cands[idx].iter() {
                    let j = jb as usize;
                    let key = (i as i64) * dedup_stride + j as i64;
                    if seen.insert(key) {
                        nn_a_out.push(i as i64);
                        nn_b_out.push(j as i64);
                    }
                }
            }
        } else {
            for &i in &fallback {
                let cx = node_ix[i];
                let cy = node_iy[i];
                let body_i = body_id_n[i];
                for &(ox, oy) in OFFSETS.iter() {
                    let qkey = pack_key(cx + ox, cy + oy);
                    let lo = sorted_node_keys.partition_point(|&k| k < qkey);
                    let hi = sorted_node_keys.partition_point(|&k| k <= qkey);
                    for slot in lo..hi {
                        let j = node_entries[slot].1 as usize;
                        if body_id_n[j] == body_i {
                            continue;
                        }
                        if i >= j {
                            continue;
                        }
                        let key = (i as i64) * dedup_stride + j as i64;
                        if seen.insert(key) {
                            nn_a_out.push(i as i64);
                            nn_b_out.push(j as i64);
                        }
                    }
                }
            }
        }
    }

    (p_out, b_out, nn_a_out, nn_b_out)
}

/// Inner project-node-beam-contacts pass. Mutates `pos` in place.
#[allow(clippy::too_many_arguments)]
fn project_node_beam_contacts_inner(
    pos: &mut [f32],
    inv_mass: &[f32],
    beam_a: &[u32],
    beam_b: &[u32],
    p_nodes: &[i64],
    b_beams: &[i64],
    thickness: f32,
    stiffness: f32,
    sub_dt: f32,
    eps: f32,
) {
    let n_pairs = p_nodes.len();
    if n_pairs == 0 {
        return;
    }
    let n_nodes = inv_mass.len();
    let beam_a_len = beam_a.len();
    let contact_radius = thickness;
    let alpha = 1.0f32 / (stiffness * sub_dt * sub_dt).max(eps);

    let mut corr_x = vec![0.0f32; n_pairs];
    let mut corr_y = vec![0.0f32; n_pairs];
    let mut w_n_arr = vec![0.0f32; n_pairs];
    let mut w_a_arr = vec![0.0f32; n_pairs];
    let mut w_c_arr = vec![0.0f32; n_pairs];
    let mut active = vec![false; n_pairs];
    let mut a_idx = vec![0usize; n_pairs];
    let mut c_idx = vec![0usize; n_pairs];

    for i in 0..n_pairs {
        let ni = p_nodes[i] as usize;
        let bi = b_beams[i] as usize;
        if ni >= n_nodes || bi >= beam_a_len {
            continue;
        }
        let ai = beam_a[bi] as usize;
        let ci = beam_b[bi] as usize;
        a_idx[i] = ai;
        c_idx[i] = ci;

        let p_nx = pos[2 * ni];
        let p_ny = pos[2 * ni + 1];
        let p_ax = pos[2 * ai];
        let p_ay = pos[2 * ai + 1];
        let p_cx = pos[2 * ci];
        let p_cy = pos[2 * ci + 1];
        let seg_x = p_cx - p_ax;
        let seg_y = p_cy - p_ay;
        let seg_len_sq = seg_x * seg_x + seg_y * seg_y;
        let safe_seg = seg_len_sq.max(eps * eps);
        let t_raw = ((p_nx - p_ax) * seg_x + (p_ny - p_ay) * seg_y) / safe_seg;
        let t = t_raw.clamp(0.0, 1.0);
        let cl_x = p_ax + seg_x * t;
        let cl_y = p_ay + seg_y * t;
        let dx = p_nx - cl_x;
        let dy = p_ny - cl_y;
        let dist_sq = dx * dx + dy * dy;
        let dist = dist_sq.max(eps * eps).sqrt();
        if dist >= contact_radius {
            continue;
        }
        let nx = dx / dist;
        let ny = dy / dist;
        let c_val = contact_radius - dist;
        let w_n = inv_mass[ni];
        let w_a = inv_mass[ai] * (1.0 - t);
        let w_c = inv_mass[ci] * t;
        let denom_raw = w_n + w_a + w_c + alpha;
        let denom = if denom_raw < eps { 1.0 } else { denom_raw };
        let dlambda = c_val / denom;
        corr_x[i] = nx * dlambda;
        corr_y[i] = ny * dlambda;
        w_n_arr[i] = w_n;
        w_a_arr[i] = w_a;
        w_c_arr[i] = w_c;
        active[i] = true;
    }

    for i in 0..n_pairs {
        if !active[i] { continue; }
        let ni = p_nodes[i] as usize;
        let w = w_n_arr[i];
        pos[2 * ni]     += corr_x[i] * w;
        pos[2 * ni + 1] += corr_y[i] * w;
    }
    for i in 0..n_pairs {
        if !active[i] { continue; }
        let ai = a_idx[i];
        let w = w_a_arr[i];
        pos[2 * ai]     += -corr_x[i] * w;
        pos[2 * ai + 1] += -corr_y[i] * w;
    }
    for i in 0..n_pairs {
        if !active[i] { continue; }
        let ci = c_idx[i];
        let w = w_c_arr[i];
        pos[2 * ci]     += -corr_x[i] * w;
        pos[2 * ci + 1] += -corr_y[i] * w;
    }
}

/// Inner project-node-node-pairs pass. Mutates `pos` in place.
#[allow(clippy::too_many_arguments)]
fn project_node_node_pairs_inner(
    pos: &mut [f32],
    inv_mass: &[f32],
    nn_a: &[i64],
    nn_b: &[i64],
    thickness: f32,
    stiffness: f32,
    sub_dt: f32,
    eps: f32,
) {
    let n_pairs = nn_a.len();
    if n_pairs == 0 {
        return;
    }
    let n_nodes = inv_mass.len();
    let contact_radius = 2.0f32 * thickness;
    let alpha = 1.0f32 / (stiffness * sub_dt * sub_dt).max(eps);

    let mut corr_x = vec![0.0f32; n_pairs];
    let mut corr_y = vec![0.0f32; n_pairs];
    let mut w_a_arr = vec![0.0f32; n_pairs];
    let mut w_b_arr = vec![0.0f32; n_pairs];
    let mut active = vec![false; n_pairs];

    for i in 0..n_pairs {
        let ai = nn_a[i] as usize;
        let bi = nn_b[i] as usize;
        if ai >= n_nodes || bi >= n_nodes {
            continue;
        }
        let dx = pos[2 * ai] - pos[2 * bi];
        let dy = pos[2 * ai + 1] - pos[2 * bi + 1];
        let dist_sq = dx * dx + dy * dy;
        let dist = dist_sq.max(eps * eps).sqrt();
        if dist >= contact_radius {
            continue;
        }
        let nx = dx / dist;
        let ny = dy / dist;
        let c_val = contact_radius - dist;
        let w_a = inv_mass[ai];
        let w_b = inv_mass[bi];
        let denom_raw = w_a + w_b + alpha;
        let denom = if denom_raw < eps { 1.0 } else { denom_raw };
        let dlambda = c_val / denom;
        corr_x[i] = nx * dlambda;
        corr_y[i] = ny * dlambda;
        w_a_arr[i] = w_a;
        w_b_arr[i] = w_b;
        active[i] = true;
    }

    for i in 0..n_pairs {
        if !active[i] { continue; }
        let ai = nn_a[i] as usize;
        let w = w_a_arr[i];
        pos[2 * ai]     += corr_x[i] * w;
        pos[2 * ai + 1] += corr_y[i] * w;
    }
    for i in 0..n_pairs {
        if !active[i] { continue; }
        let bi = nn_b[i] as usize;
        let w = w_b_arr[i];
        pos[2 * bi]     += -corr_x[i] * w;
        pos[2 * bi + 1] += -corr_y[i] * w;
    }
}

/// Tier 10: full softbody step in Rust. Replaces the Python outer
/// substep + iter loops with a single PyO3 call so per-iter dispatch
/// overhead is amortised across all iters of a substep.
///
/// All persistent SoA arrays are passed as writable `PyByteArray`
/// objects so the Rust side mutates them in place; the Python wrapper
/// copies the contents back into the numpy arrays on return.
///
/// Static inputs that don't change across the substep loop (rest_length,
/// inv_mass, stiffness, body_id, …) are passed as read-only `&[u8]`
/// slices reinterpreted via `bytemuck::cast_slice`.
#[pyfunction]
#[pyo3(signature = (
    pos_xy, prev_pos_xy, vel_xy, rest_length, broken,
    inv_mass, fixed, damping,
    node_a, node_b, stiffness, yield_strain, plasticity_rate, break_strain,
    node_body_id, beam_body_id,
    n_nodes, n_beams,
    substeps, iters, sub_dt, gravity_x, gravity_y, eps, floor_y, floor_friction,
    contact_enabled, contact_thickness, contact_stiffness, broadphase_cell_factor,
    plasticity_subcycle,
))]
#[allow(clippy::too_many_arguments)]
pub fn slappyengine_step(
    pos_xy: &Bound<'_, PyByteArray>,
    prev_pos_xy: &Bound<'_, PyByteArray>,
    vel_xy: &Bound<'_, PyByteArray>,
    rest_length: &Bound<'_, PyByteArray>,
    broken: &Bound<'_, PyByteArray>,
    inv_mass: &[u8],
    fixed: &[u8],
    damping: &[u8],
    node_a: &[u8],
    node_b: &[u8],
    stiffness: &[u8],
    yield_strain: &[u8],
    plasticity_rate: &[u8],
    break_strain: &[u8],
    node_body_id: &[u8],
    beam_body_id: &[u8],
    n_nodes: usize,
    n_beams: usize,
    substeps: usize,
    iters: usize,
    sub_dt: f32,
    gravity_x: f32,
    gravity_y: f32,
    eps: f32,
    floor_y: f32,
    floor_friction: f32,
    contact_enabled: bool,
    contact_thickness: f32,
    contact_stiffness: f32,
    broadphase_cell_factor: f32,
    plasticity_subcycle: bool,
) -> PyResult<()> {
    if n_nodes == 0 {
        return Ok(());
    }

    // SAFETY: GIL held; the four bytearrays are exclusive (Python wrapper
    // creates fresh copies for the step so no aliasing with foreign refs).
    let pos: &mut [f32] = bytemuck::cast_slice_mut(unsafe { pos_xy.as_bytes_mut() });
    let prev_pos: &mut [f32] = bytemuck::cast_slice_mut(unsafe { prev_pos_xy.as_bytes_mut() });
    let vel: &mut [f32] = bytemuck::cast_slice_mut(unsafe { vel_xy.as_bytes_mut() });
    let rest: &mut [f32] = bytemuck::cast_slice_mut(unsafe { rest_length.as_bytes_mut() });
    let broken_arr: &mut [u8] = unsafe { broken.as_bytes_mut() };

    let inv_mass: &[f32] = cast_slice(inv_mass);
    let fixed_arr: &[u8] = fixed;
    let damping_arr: &[f32] = cast_slice(damping);
    let na: &[u32] = if n_beams > 0 { cast_slice(node_a) } else { &[] };
    let nb: &[u32] = if n_beams > 0 { cast_slice(node_b) } else { &[] };
    let stiff: &[f32] = if n_beams > 0 { cast_slice(stiffness) } else { &[] };
    let ys: &[f32] = if n_beams > 0 { cast_slice(yield_strain) } else { &[] };
    let pr: &[f32] = if n_beams > 0 { cast_slice(plasticity_rate) } else { &[] };
    let bs: &[f32] = if n_beams > 0 { cast_slice(break_strain) } else { &[] };
    let node_body: &[u32] = cast_slice(node_body_id);
    let beam_body: &[u32] = if n_beams > 0 { cast_slice(beam_body_id) } else { &[] };

    if pos.len() != n_nodes * 2
        || prev_pos.len() != n_nodes * 2
        || vel.len() != n_nodes * 2
        || inv_mass.len() != n_nodes
        || fixed_arr.len() != n_nodes
        || damping_arr.len() != n_nodes
        || node_body.len() != n_nodes
    {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "node array size mismatch",
        ));
    }
    if n_beams > 0
        && (na.len() != n_beams
            || nb.len() != n_beams
            || rest.len() != n_beams
            || stiff.len() != n_beams
            || ys.len() != n_beams
            || pr.len() != n_beams
            || bs.len() != n_beams
            || broken_arr.len() != n_beams
            || beam_body.len() != n_beams)
    {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "beam array size mismatch",
        ));
    }

    // Build the node_relax vector once per step from the beam topology —
    // matches the numpy `np.bincount(a) + np.bincount(b)` form.
    let node_relax: Vec<f32> = if n_beams > 0 {
        let mut count = vec![0u32; n_nodes];
        for j in 0..n_beams {
            count[na[j] as usize] += 1;
            count[nb[j] as usize] += 1;
        }
        count.iter().map(|&c| 1.0 / (c.max(1) as f32)).collect()
    } else {
        vec![1.0f32; n_nodes]
    };

    // Per-step reusable scratch for distance projection.
    let mut corr_x = vec![0.0f32; n_beams];
    let mut corr_y = vec![0.0f32; n_beams];

    for _ in 0..substeps {
        // prev_pos[:] = pos
        prev_pos.copy_from_slice(pos);

        // Two-step integration to match numpy float32 ordering:
        //   pos += vel * sub_dt * free_mask
        //   pos += 0.5 * gravity * sub_dt^2 * free_mask
        // (separate adds rather than a fused mac so float-precision
        //  drift matches the pure-Python path bit-for-bit).
        let half_dt2 = 0.5f32 * sub_dt * sub_dt;
        for i in 0..n_nodes {
            if fixed_arr[i] != 0 {
                continue;
            }
            pos[2 * i]     += vel[2 * i]     * sub_dt;
            pos[2 * i + 1] += vel[2 * i + 1] * sub_dt;
        }
        for i in 0..n_nodes {
            if fixed_arr[i] != 0 {
                continue;
            }
            pos[2 * i]     += half_dt2 * gravity_x;
            pos[2 * i + 1] += half_dt2 * gravity_y;
        }

        // Build contact pairs once per substep.
        let (p_pairs, b_pairs, nn_a_pairs, nn_b_pairs) = if contact_enabled {
            build_contact_pairs_inner(
                pos, node_body, n_nodes,
                na, nb, beam_body, rest, broken_arr, n_beams,
                contact_thickness, broadphase_cell_factor,
            )
        } else {
            (Vec::new(), Vec::new(), Vec::new(), Vec::new())
        };

        if n_beams > 0 {
            for _ in 0..iters {
                if plasticity_subcycle {
                    apply_plasticity_inner(pos, rest, na, nb, ys, pr, broken_arr, sub_dt, eps);
                }
                project_distance_constraints_inner(
                    pos, inv_mass, na, nb, rest, stiff, broken_arr, &node_relax,
                    sub_dt, eps, &mut corr_x, &mut corr_y,
                );
                if contact_enabled {
                    if !p_pairs.is_empty() {
                        project_node_beam_contacts_inner(
                            pos, inv_mass, na, nb, &p_pairs, &b_pairs,
                            contact_thickness, contact_stiffness, sub_dt, eps,
                        );
                    }
                    if !nn_a_pairs.is_empty() {
                        project_node_node_pairs_inner(
                            pos, inv_mass, &nn_a_pairs, &nn_b_pairs,
                            contact_thickness, contact_stiffness, sub_dt, eps,
                        );
                    }
                }
                // _project_floor — clamp pos.y to floor_y for nodes below.
                for i in 0..n_nodes {
                    if pos[2 * i + 1] > floor_y {
                        pos[2 * i + 1] = floor_y;
                    }
                }
            }
            if !plasticity_subcycle {
                apply_plasticity_inner(pos, rest, na, nb, ys, pr, broken_arr, sub_dt, eps);
            }
            mark_breaks_inner(pos, rest, na, nb, bs, broken_arr, eps);
        } else if contact_enabled {
            if !p_pairs.is_empty() {
                project_node_beam_contacts_inner(
                    pos, inv_mass, na, nb, &p_pairs, &b_pairs,
                    contact_thickness, contact_stiffness, sub_dt, eps,
                );
            }
            if !nn_a_pairs.is_empty() {
                project_node_node_pairs_inner(
                    pos, inv_mass, &nn_a_pairs, &nn_b_pairs,
                    contact_thickness, contact_stiffness, sub_dt, eps,
                );
            }
            for i in 0..n_nodes {
                if pos[2 * i + 1] > floor_y {
                    pos[2 * i + 1] = floor_y;
                }
            }
        } else {
            for i in 0..n_nodes {
                if pos[2 * i + 1] > floor_y {
                    pos[2 * i + 1] = floor_y;
                }
            }
        }

        // Velocity update + damping + floor friction. Matches numpy:
        //   new_vel = (pos - prev_pos) / sub_dt
        //   new_vel *= free_mask
        //   damp = clamp(1 - damping*sub_dt, 0, 1)
        //   new_vel *= damp[:, None]
        //   below = pos.y >= floor_y
        //   if any(below):
        //     new_vel[below, 1] = min(new_vel[below, 1], 0)
        //     new_vel[below, 0] *= (1 - floor_friction)
        //
        // NOTE: division by `sub_dt` (not multiply by reciprocal) — this
        // matches numpy's `/ sub_dt`, otherwise the float32 ULP drift
        // accumulates over substeps and the block-on-block contact
        // canary fails.
        for i in 0..n_nodes {
            if fixed_arr[i] != 0 {
                vel[2 * i] = 0.0;
                vel[2 * i + 1] = 0.0;
                continue;
            }
            let mut vx = (pos[2 * i]     - prev_pos[2 * i])     / sub_dt;
            let mut vy = (pos[2 * i + 1] - prev_pos[2 * i + 1]) / sub_dt;
            let mut damp = 1.0 - damping_arr[i] * sub_dt;
            if damp < 0.0 { damp = 0.0; }
            if damp > 1.0 { damp = 1.0; }
            vx *= damp;
            vy *= damp;
            if pos[2 * i + 1] >= floor_y {
                if vy > 0.0 { vy = 0.0; }
                vx *= 1.0 - floor_friction;
            }
            vel[2 * i] = vx;
            vel[2 * i + 1] = vy;
        }
    }

    Ok(())
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(project_distance_constraints, m)?)?;
    m.add_function(wrap_pyfunction!(apply_plasticity, m)?)?;
    m.add_function(wrap_pyfunction!(mark_breaks, m)?)?;
    m.add_function(wrap_pyfunction!(build_contact_pairs, m)?)?;
    m.add_function(wrap_pyfunction!(project_node_beam_contacts, m)?)?;
    m.add_function(wrap_pyfunction!(project_node_node_pairs, m)?)?;
    m.add_function(wrap_pyfunction!(slappyengine_step, m)?)?;
    Ok(())
}
