// pressure_project.wgsl
// Phase C — divergence-free pressure projection for fluid cells.
//
// CPU reference: ``PhysicsWorld._pressure_project_arrays`` in
// physics/world.py.  This shader is the GPU port and must match the
// CPU output to within 1e-3 (consistent with the existing
// test_gpu_matches_cpu_on_one_substep tolerance).
//
// Two code paths share one entry point:
//   * Single-grid Red-Black SOR (legacy, ``use_multigrid == 0``).
//     Mirrors ``_pressure_project_arrays`` line-for-line.
//   * Two-level V-cycle (WP-I, ``use_multigrid == 1``).  Mirrors the
//     CPU ``pressure_multigrid.vcycle_project_v`` path: pre-smooth on
//     32×32, restrict residual to 16×16, coarse-solve there with
//     SOR×coarse_iters, prolong bilinearly back, post-smooth on 32×32,
//     repeat ``n_cycles = max(1, iters // 4)`` times.
//
// Why workgroup-shared memory?
//   The K-iteration loop needs neighbour synchronization between
//   sweeps.  Storage-buffer atomics or storage barriers are heavy.
//   The 32×32 grid fits in 1024 cells × 4 B = 4 KB of shared memory;
//   the 16×16 coarse grid adds 256 cells × 4 B = 1 KB per array.
//   Total budget here is ~35 KB, well under the 49152 B that recent
//   adapters expose (we probed the host limit before bumping).
//
// Workgroup size: 16×16 = 256 invocations, each invocation owns a 2×2
// fine tile (32/16 = 2) and a 1×1 coarse tile.

const CELL_GRID_SIZE: u32 = 32u;
const COARSE_GRID_SIZE: u32 = 16u;
const OMEGA: f32 = 1.5;
// V-cycle knobs — mirror CPU defaults in pressure_multigrid.vcycle_project_v.
const VC_SMOOTH_PRE: u32 = 2u;
const VC_SMOOTH_POST: u32 = 2u;
const VC_COARSE_ITERS: u32 = 8u;

struct HullParams {
    // Geometry / integration
    width: u32,
    height: u32,
    is_fluid: u32,
    _pad0: u32,
    dt: f32,
    // Mechanical
    E: f32,
    Y: f32,
    brittle_modulus: f32,
    rho: f32,
    viscosity: f32,
    torn_damping: f32,
    tear_strength: f32,
    remold_rate: f32,
    bond_intact_threshold: f32,
    bond_intact_slope: f32,
    brittle_damage_rate: f32,
    brittle_tear_rate: f32,
    brittle_bond_loss_rate: f32,
    brittle_stretch_amplification: f32,
    // Catastrophic brittle severance (WP-V) — mirrored from per_pixel_sim.wgsl
    // so a single packed params record can be bound to either shader.
    brittle_catastrophic_excess_ratio: f32,
    brittle_catastrophic_bond_floor: f32,
    brittle_catastrophic_damage_gate: f32,
    ductile_plastic_strain_rate: f32,
    ductile_poisson_ratio: f32,
    ductile_damage_rate: f32,
    tear_growth_rate: f32,
    melt_point: f32,
    melt_anneal_rate: f32,
    melt_viscous_damping: f32,
    thermal_k: f32,
    emissivity: f32,
    thermal_softening_coefficient: f32,
    damage_weakening_coefficient: f32,
    heat_strain_energy_factor: f32,
    fluid_pressure_coupling: f32,
    fluid_pressure_smoothing: f32,
    fluid_pressure_decay: f32,
    silhouette_mask_threshold: f32,
    E_wave: f32,
    // Engine-wide KE → heat scaling (WP-T).  Mirrors per_pixel_sim.wgsl
    // so a single packed params record can be bound to either shader.
    heat_damping_to_heat_factor: f32,
};

struct PixelState {
    u:              vec2<f32>,
    v:              vec2<f32>,
    perm_strain_xx: f32,
    perm_strain_yy: f32,
    perm_strain_xy: f32,
    pressure:       f32,
    damage:         f32,
    density:        f32,
    stretch:        f32,
    tear:           f32,
    heat:           f32,
    bond_n:         f32,
    bond_e:         f32,
    bond_s:         f32,
};

struct ProjectionConfig {
    iters: u32,
    use_multigrid: u32,
    n_cycles: u32,
    _pad2: u32,
};

@group(0) @binding(0) var<storage, read>       per_hull_params: array<HullParams>;
@group(0) @binding(1) var<storage, read_write> cells:  array<PixelState>;
@group(0) @binding(2) var<storage, read>       active_hulls: array<u32>;
@group(0) @binding(3) var<uniform>             cfg: ProjectionConfig;

// Workgroup-shared 32×32 tiles for pressure, RHS (== div for single-grid;
// == -div for V-cycle), and the masks.
var<workgroup> ws_p:    array<f32, 1024>;
var<workgroup> ws_rhs:  array<f32, 1024>;  // legacy name ws_div: now holds Poisson rhs
var<workgroup> ws_mask: array<f32, 1024>;
var<workgroup> ws_m_l:  array<f32, 1024>;
var<workgroup> ws_m_r:  array<f32, 1024>;
var<workgroup> ws_m_t:  array<f32, 1024>;
var<workgroup> ws_m_b:  array<f32, 1024>;

// Coarse-grid (16×16) workgroup-shared arrays for the V-cycle path.
// Sized 256 each; cost is 7 KB total when V-cycle is active.
var<workgroup> wc_p:    array<f32, 256>;
var<workgroup> wc_rhs:  array<f32, 256>;
var<workgroup> wc_mask: array<f32, 256>;
var<workgroup> wc_m_l:  array<f32, 256>;
var<workgroup> wc_m_r:  array<f32, 256>;
var<workgroup> wc_m_t:  array<f32, 256>;
var<workgroup> wc_m_b:  array<f32, 256>;

fn ws_idx(x: u32, y: u32) -> u32 {
    return y * CELL_GRID_SIZE + x;
}

fn wc_idx(x: u32, y: u32) -> u32 {
    return y * COARSE_GRID_SIZE + x;
}

fn neighbour_p_fine(x: i32, y: i32) -> f32 {
    if x < 0 || y < 0 || x >= i32(CELL_GRID_SIZE) || y >= i32(CELL_GRID_SIZE) {
        return 0.0;
    }
    return ws_p[ws_idx(u32(x), u32(y))];
}

fn neighbour_p_coarse(x: i32, y: i32) -> f32 {
    if x < 0 || y < 0 || x >= i32(COARSE_GRID_SIZE) || y >= i32(COARSE_GRID_SIZE) {
        return 0.0;
    }
    return wc_p[wc_idx(u32(x), u32(y))];
}

// One Red-Black SOR sweep over the fine 32×32 grid (each thread updates its 2×2 tile).
// The (tx, ty) is the local-thread tile origin in the 16×16 thread grid.
fn fine_sor_sweep(tx: u32, ty: u32) {
    // Red pass.
    for (var dy: u32 = 0u; dy < 2u; dy = dy + 1u) {
        for (var dx: u32 = 0u; dx < 2u; dx = dx + 1u) {
            let cx = tx * 2u + dx;
            let cy = ty * 2u + dy;
            let idx_local = ws_idx(cx, cy);
            let is_red = ((cx + cy) & 1u) == 0u;
            let m = ws_mask[idx_local];
            if is_red && m > 0.5 {
                let p_l = neighbour_p_fine(i32(cx) - 1, i32(cy)) * ws_m_l[idx_local];
                let p_r = neighbour_p_fine(i32(cx) + 1, i32(cy)) * ws_m_r[idx_local];
                let p_t = neighbour_p_fine(i32(cx), i32(cy) - 1) * ws_m_t[idx_local];
                let p_b = neighbour_p_fine(i32(cx), i32(cy) + 1) * ws_m_b[idx_local];
                let p_jacobi = (p_l + p_r + p_t + p_b - ws_rhs[idx_local]) * 0.25;
                let p_old = ws_p[idx_local];
                ws_p[idx_local] = p_old + OMEGA * (p_jacobi - p_old);
            }
        }
    }
    workgroupBarrier();
    // Black pass.
    for (var dy: u32 = 0u; dy < 2u; dy = dy + 1u) {
        for (var dx: u32 = 0u; dx < 2u; dx = dx + 1u) {
            let cx = tx * 2u + dx;
            let cy = ty * 2u + dy;
            let idx_local = ws_idx(cx, cy);
            let is_black = ((cx + cy) & 1u) == 1u;
            let m = ws_mask[idx_local];
            if is_black && m > 0.5 {
                let p_l = neighbour_p_fine(i32(cx) - 1, i32(cy)) * ws_m_l[idx_local];
                let p_r = neighbour_p_fine(i32(cx) + 1, i32(cy)) * ws_m_r[idx_local];
                let p_t = neighbour_p_fine(i32(cx), i32(cy) - 1) * ws_m_t[idx_local];
                let p_b = neighbour_p_fine(i32(cx), i32(cy) + 1) * ws_m_b[idx_local];
                let p_jacobi = (p_l + p_r + p_t + p_b - ws_rhs[idx_local]) * 0.25;
                let p_old = ws_p[idx_local];
                ws_p[idx_local] = p_old + OMEGA * (p_jacobi - p_old);
            }
        }
    }
    workgroupBarrier();
    // Restrict to fluid cells (matches CPU "p = p * mask" each iter).
    for (var dy: u32 = 0u; dy < 2u; dy = dy + 1u) {
        for (var dx: u32 = 0u; dx < 2u; dx = dx + 1u) {
            let cx = tx * 2u + dx;
            let cy = ty * 2u + dy;
            let idx_local = ws_idx(cx, cy);
            ws_p[idx_local] = ws_p[idx_local] * ws_mask[idx_local];
        }
    }
    workgroupBarrier();
}

// One Red-Black SOR sweep over the coarse 16×16 grid; each thread owns exactly one cell.
fn coarse_sor_sweep(tx: u32, ty: u32) {
    let cx = tx;
    let cy = ty;
    let idx_local = wc_idx(cx, cy);
    let m = wc_mask[idx_local];
    let is_red = ((cx + cy) & 1u) == 0u;
    // Red.
    if is_red && m > 0.5 {
        let p_l = neighbour_p_coarse(i32(cx) - 1, i32(cy)) * wc_m_l[idx_local];
        let p_r = neighbour_p_coarse(i32(cx) + 1, i32(cy)) * wc_m_r[idx_local];
        let p_t = neighbour_p_coarse(i32(cx), i32(cy) - 1) * wc_m_t[idx_local];
        let p_b = neighbour_p_coarse(i32(cx), i32(cy) + 1) * wc_m_b[idx_local];
        let p_jacobi = (p_l + p_r + p_t + p_b - wc_rhs[idx_local]) * 0.25;
        let p_old = wc_p[idx_local];
        wc_p[idx_local] = p_old + OMEGA * (p_jacobi - p_old);
    }
    workgroupBarrier();
    // Black.
    if !is_red && m > 0.5 {
        let p_l = neighbour_p_coarse(i32(cx) - 1, i32(cy)) * wc_m_l[idx_local];
        let p_r = neighbour_p_coarse(i32(cx) + 1, i32(cy)) * wc_m_r[idx_local];
        let p_t = neighbour_p_coarse(i32(cx), i32(cy) - 1) * wc_m_t[idx_local];
        let p_b = neighbour_p_coarse(i32(cx), i32(cy) + 1) * wc_m_b[idx_local];
        let p_jacobi = (p_l + p_r + p_t + p_b - wc_rhs[idx_local]) * 0.25;
        let p_old = wc_p[idx_local];
        wc_p[idx_local] = p_old + OMEGA * (p_jacobi - p_old);
    }
    workgroupBarrier();
    // Restrict to fluid cells.
    wc_p[idx_local] = wc_p[idx_local] * wc_mask[idx_local];
    workgroupBarrier();
}

@compute @workgroup_size(16, 16)
fn main(
    @builtin(local_invocation_id) lid: vec3<u32>,
    @builtin(workgroup_id) wgid: vec3<u32>,
) {
    let p = per_hull_params[wgid.z];
    if p.is_fluid != 1u {
        return;
    }
    if cfg.iters == 0u {
        return;
    }

    let cell_slot = active_hulls[wgid.z];
    let cells_per_slot: u32 = p.width * p.height;
    let cell_base = cell_slot * cells_per_slot;
    let thresh = p.silhouette_mask_threshold;
    let use_mg = cfg.use_multigrid == 1u;

    let tx = lid.x;
    let ty = lid.y;

    // ---------- Phase 1: load v + density, build masks, compute rhs ----------
    for (var dy: u32 = 0u; dy < 2u; dy = dy + 1u) {
        for (var dx: u32 = 0u; dx < 2u; dx = dx + 1u) {
            let cx = tx * 2u + dx;
            let cy = ty * 2u + dy;
            let idx_local = ws_idx(cx, cy);
            let s = cells[cell_base + cy * p.width + cx];
            let m = select(0.0, 1.0, s.density >= thresh);
            ws_mask[idx_local] = m;
            ws_p[idx_local] = 0.0;
        }
    }
    workgroupBarrier();

    // Directional neighbour masks + backward-difference divergence.
    for (var dy: u32 = 0u; dy < 2u; dy = dy + 1u) {
        for (var dx: u32 = 0u; dx < 2u; dx = dx + 1u) {
            let cx = tx * 2u + dx;
            let cy = ty * 2u + dy;
            let idx_local = ws_idx(cx, cy);

            var m_l_v = 0.0;
            var m_r_v = 0.0;
            var m_t_v = 0.0;
            var m_b_v = 0.0;
            if cx > 0u {
                m_l_v = ws_mask[ws_idx(cx - 1u, cy)];
            }
            if cx + 1u < CELL_GRID_SIZE {
                m_r_v = ws_mask[ws_idx(cx + 1u, cy)];
            }
            if cy > 0u {
                m_t_v = ws_mask[ws_idx(cx, cy - 1u)];
            }
            if cy + 1u < CELL_GRID_SIZE {
                m_b_v = ws_mask[ws_idx(cx, cy + 1u)];
            }
            ws_m_l[idx_local] = m_l_v;
            ws_m_r[idx_local] = m_r_v;
            ws_m_t[idx_local] = m_t_v;
            ws_m_b[idx_local] = m_b_v;

            let s_here = cells[cell_base + cy * p.width + cx];
            var vx_l: f32 = 0.0;
            var vy_t: f32 = 0.0;
            if cx > 0u {
                vx_l = cells[cell_base + cy * p.width + (cx - 1u)].v.x;
            }
            if cy > 0u {
                vy_t = cells[cell_base + (cy - 1u) * p.width + cx].v.y;
            }
            vx_l = vx_l * m_l_v;
            vy_t = vy_t * m_t_v;
            let div_here = (s_here.v.x - vx_l) + (s_here.v.y - vy_t);
            // Both paths solve Δp = +div (so v -= grad p tail).
            // The persistent pressure field is reused next frame as a
            // body force (f -= grad p in the kernel) and a sign mismatch
            // between paths would invert that force and damp motion.
            // Mask applied for V-cycle (it expects rhs zero in vacuum);
            // single-grid masks via the SOR step's red/black weights.
            if use_mg {
                ws_rhs[idx_local] = div_here * ws_mask[idx_local];
            } else {
                ws_rhs[idx_local] = div_here;
            }
        }
    }
    workgroupBarrier();

    // ---------- Phase 2: solve ----------
    if !use_mg {
        // Legacy single-grid Red-Black SOR.
        let iters = cfg.iters;
        for (var k: u32 = 0u; k < iters; k = k + 1u) {
            fine_sor_sweep(tx, ty);
        }
    } else {
        // Two-level V-cycle, run n_cycles times.
        let n_cycles = max(1u, cfg.n_cycles);
        for (var cyc: u32 = 0u; cyc < n_cycles; cyc = cyc + 1u) {
            // 1. Pre-smooth on the fine grid.
            for (var k: u32 = 0u; k < VC_SMOOTH_PRE; k = k + 1u) {
                fine_sor_sweep(tx, ty);
            }

            // 2. Compute residual r = rhs - Δp (5-point Laplacian),
            //    masked to fluid cells.  Restrict to coarse grid via 2×2 mean.
            //    Each coarse cell is owned by one thread (tx, ty) ∈ [0,16).
            //    We use the same thread mapping: tx is coarse x, ty is coarse y.
            // First compute the four fine residuals for this coarse cell,
            // average them, store in wc_rhs (×4 scaling for 2h spacing).
            {
                let cx0 = tx * 2u;
                let cy0 = ty * 2u;
                var rsum: f32 = 0.0;
                for (var dy: u32 = 0u; dy < 2u; dy = dy + 1u) {
                    for (var dx: u32 = 0u; dx < 2u; dx = dx + 1u) {
                        let fx = cx0 + dx;
                        let fy = cy0 + dy;
                        let fidx = ws_idx(fx, fy);
                        let p_l = neighbour_p_fine(i32(fx) - 1, i32(fy)) * ws_m_l[fidx];
                        let p_r = neighbour_p_fine(i32(fx) + 1, i32(fy)) * ws_m_r[fidx];
                        let p_t = neighbour_p_fine(i32(fx), i32(fy) - 1) * ws_m_t[fidx];
                        let p_b = neighbour_p_fine(i32(fx), i32(fy) + 1) * ws_m_b[fidx];
                        let lap_p = p_l + p_r + p_t + p_b - 4.0 * ws_p[fidx];
                        let r_here = (ws_rhs[fidx] - lap_p) * ws_mask[fidx];
                        rsum = rsum + r_here;
                    }
                }
                let r_coarse = rsum * 0.25;

                // Coarse mask = max of 2×2 fine block (any-fluid).
                let m00 = ws_mask[ws_idx(cx0, cy0)];
                let m10 = ws_mask[ws_idx(cx0 + 1u, cy0)];
                let m01 = ws_mask[ws_idx(cx0, cy0 + 1u)];
                let m11 = ws_mask[ws_idx(cx0 + 1u, cy0 + 1u)];
                let mc = max(max(m00, m10), max(m01, m11));

                let cidx = wc_idx(tx, ty);
                wc_mask[cidx] = mc;
                // Scale RHS by 4× to account for 2h spacing (matches CPU).
                wc_rhs[cidx] = r_coarse * 4.0;
                wc_p[cidx] = 0.0;
            }
            workgroupBarrier();

            // Build coarse neighbour masks (now that coarse mask is in shared memory).
            {
                let cx = tx;
                let cy = ty;
                let cidx = wc_idx(cx, cy);
                var m_l_c = 0.0;
                var m_r_c = 0.0;
                var m_t_c = 0.0;
                var m_b_c = 0.0;
                if cx > 0u {
                    m_l_c = wc_mask[wc_idx(cx - 1u, cy)];
                }
                if cx + 1u < COARSE_GRID_SIZE {
                    m_r_c = wc_mask[wc_idx(cx + 1u, cy)];
                }
                if cy > 0u {
                    m_t_c = wc_mask[wc_idx(cx, cy - 1u)];
                }
                if cy + 1u < COARSE_GRID_SIZE {
                    m_b_c = wc_mask[wc_idx(cx, cy + 1u)];
                }
                wc_m_l[cidx] = m_l_c;
                wc_m_r[cidx] = m_r_c;
                wc_m_t[cidx] = m_t_c;
                wc_m_b[cidx] = m_b_c;
            }
            workgroupBarrier();

            // 3. Coarse solve.
            for (var k: u32 = 0u; k < VC_COARSE_ITERS; k = k + 1u) {
                coarse_sor_sweep(tx, ty);
            }

            // 4. Prolong correction back to fine grid (bilinear-like:
            //    nearest-neighbour 2× upsample averaged with x-shift,
            //    y-shift, and xy-shift; identical to the CPU formula).
            //    Each fine cell (fx, fy) maps to coarse (fx/2, fy/2).
            //    We compute the four contributions and average.
            for (var dy: u32 = 0u; dy < 2u; dy = dy + 1u) {
                for (var dx: u32 = 0u; dx < 2u; dx = dx + 1u) {
                    let fx = tx * 2u + dx;
                    let fy = ty * 2u + dy;
                    let fidx = ws_idx(fx, fy);
                    // Replicate np.kron 2x upsample + 3 shifted copies.
                    // The CPU code builds nn, nn_xshift, nn_yshift, nn_xyshift
                    // arrays on the FINE grid by taking the kron result and
                    // shifting it.  Translated to per-fine-cell:
                    //   nn[fx, fy]        = coarse[fx>>1, fy>>1]
                    //   nn_xshift[fx, fy] = nn[fx, fy+0, fx+1<W ? fx+1>>1 : same]
                    // ...messy.  We replicate the exact 4-sample average the
                    // CPU code produces by indexing the kron-array directly.
                    //
                    // Equivalent direct formula:
                    //   For fine cell (fx, fy), let cx = fx>>1, cy = fy>>1.
                    //   nn        = coarse[cx, cy]
                    //   xshift sample comes from kron[fx, fy+1 along x]:
                    //     if fx < FINE-1: from coarse[(fx+1)>>1, cy]
                    //     else: same as nn (boundary replicate)
                    //   yshift sample: similarly along y.
                    //   xyshift sample: combined.
                    let cx = fx >> 1u;
                    let cy = fy >> 1u;
                    let nn_v = wc_p[wc_idx(cx, cy)];

                    var xs_v: f32 = nn_v;
                    if fx + 1u < CELL_GRID_SIZE {
                        let cx_xs = (fx + 1u) >> 1u;
                        xs_v = wc_p[wc_idx(cx_xs, cy)];
                    }
                    var ys_v: f32 = nn_v;
                    if fy + 1u < CELL_GRID_SIZE {
                        let cy_ys = (fy + 1u) >> 1u;
                        ys_v = wc_p[wc_idx(cx, cy_ys)];
                    }
                    var xys_v: f32 = nn_v;
                    if fx + 1u < CELL_GRID_SIZE && fy + 1u < CELL_GRID_SIZE {
                        let cx_xs = (fx + 1u) >> 1u;
                        let cy_ys = (fy + 1u) >> 1u;
                        xys_v = wc_p[wc_idx(cx_xs, cy_ys)];
                    } else if fx + 1u < CELL_GRID_SIZE {
                        // last-row: xys mirrors xs (yshift falls back to nn,
                        // CPU: nn_xyshift[-1, :] = nn_xshift[-1, :]).
                        let cx_xs = (fx + 1u) >> 1u;
                        xys_v = wc_p[wc_idx(cx_xs, cy)];
                    } else if fy + 1u < CELL_GRID_SIZE {
                        // last-col: xys mirrors ys.
                        let cy_ys = (fy + 1u) >> 1u;
                        xys_v = wc_p[wc_idx(cx, cy_ys)];
                    }

                    let correction = (nn_v + xs_v + ys_v + xys_v) * 0.25;
                    // correction *= mask so vacuum cells stay at zero.
                    ws_p[fidx] = ws_p[fidx] + correction * ws_mask[fidx];
                }
            }
            workgroupBarrier();

            // 5. Post-smooth.
            for (var k: u32 = 0u; k < VC_SMOOTH_POST; k = k + 1u) {
                fine_sor_sweep(tx, ty);
            }
        }
    }

    // ---------- Phase 3: forward-diff grad(p), update v + u ----------
    for (var dy: u32 = 0u; dy < 2u; dy = dy + 1u) {
        for (var dx: u32 = 0u; dx < 2u; dx = dx + 1u) {
            let cx = tx * 2u + dx;
            let cy = ty * 2u + dy;
            let idx_local = ws_idx(cx, cy);
            let cell_idx = cell_base + cy * p.width + cx;

            let p_here = ws_p[idx_local];
            var p_r: f32 = 0.0;
            var p_b: f32 = 0.0;
            if cx + 1u < CELL_GRID_SIZE {
                p_r = ws_p[ws_idx(cx + 1u, cy)] * ws_m_r[idx_local];
            }
            if cy + 1u < CELL_GRID_SIZE {
                p_b = ws_p[ws_idx(cx, cy + 1u)] * ws_m_b[idx_local];
            }

            var s = cells[cell_idx];
            let v_pre_x = s.v.x;
            let v_pre_y = s.v.y;
            // Both paths solve Δp = div and apply v -= grad p
            // (forward-difference gradient).  Identical sign convention
            // keeps the persistent pressure field consistent across
            // single-grid and V-cycle frames.
            var v_new_x = v_pre_x - (p_r - p_here);
            var v_new_y = v_pre_y - (p_b - p_here);
            var p_out = p_here;

            if ws_mask[idx_local] < 0.5 {
                v_new_x = 0.0;
                v_new_y = 0.0;
                p_out = 0.0;
            }
            // u-correction (same as legacy path) so total u reflects projected v.
            let du_x = (v_new_x - v_pre_x) * p.dt;
            let du_y = (v_new_y - v_pre_y) * p.dt;
            s.u.x = s.u.x + du_x;
            s.u.y = s.u.y + du_y;
            s.v.x = v_new_x;
            s.v.y = v_new_y;
            s.pressure = p_out;
            cells[cell_idx] = s;
        }
    }
}
