// per_pixel_sim.wgsl
// Per-pixel hierarchical-hull continuous solver.
//
// Binding indices are kept contiguous 0..3.  An earlier draft included a
// per-pixel silhouette ``mask`` storage buffer at @binding(3); it was
// dead-code-eliminated by the shader compiler (the kernel uses the
// density-threshold gate instead), which made ``layout="auto"`` report
// only 4 bindings and broke the Python side that uploaded 5.  The mask
// binding has been removed and ``active_hulls`` moved to @binding(3).
//
// Sprint 3: extended to support a single indirect dispatch over many active
// hulls.  The dispatch shape is (4, 4, N_ACTIVE_HULLS); workgroup_id.z picks
// which active-hull slot this workgroup is processing.  Per-hull material
// parameters live in `per_hull_params` (one HullParams record per active
// hull) and `active_hulls` maps slot-in-dispatch → cell-pool slot id.
//
// Backwards compatibility:
//   The single-hull legacy path (one dispatch per hull, no z axis) is still
//   served by leaving `per_hull_params` length == 1 and `active_hulls[0]`
//   pointing at the slot of interest; the host code handles this.
//
// Layout invariants:
//   * 32x32 cell grid per hull (CELL_GRID_SIZE = 32).
//   * One slot = 1024 PixelState entries laid out row-major.
//   * Active hulls share the SAME src/dst storage buffer; offsets are
//     computed inside the shader from active_hulls[wgid.z] * 1024.

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
    // Bond intact mapping
    bond_intact_threshold: f32,
    bond_intact_slope: f32,
    // Brittle
    brittle_damage_rate: f32,
    brittle_tear_rate: f32,
    brittle_bond_loss_rate: f32,
    brittle_stretch_amplification: f32,
    // Catastrophic brittle severance (WP-V): vm > brittle_eff * ratio
    // AND damage > damage_gate → drop the dominant-axis bond on this cell
    // to ``floor`` in a single substep.
    brittle_catastrophic_excess_ratio: f32,
    brittle_catastrophic_bond_floor: f32,
    brittle_catastrophic_damage_gate: f32,
    // Ductile
    ductile_plastic_strain_rate: f32,
    ductile_poisson_ratio: f32,
    ductile_damage_rate: f32,
    // Tear (stretch)
    tear_growth_rate: f32,
    // Thermal
    melt_point: f32,
    melt_anneal_rate: f32,
    melt_viscous_damping: f32,
    thermal_k: f32,
    emissivity: f32,
    thermal_softening_coefficient: f32,
    damage_weakening_coefficient: f32,
    heat_strain_energy_factor: f32,
    // Fluid
    fluid_pressure_coupling: f32,
    fluid_pressure_smoothing: f32,
    fluid_pressure_decay: f32,
    // Numerical
    silhouette_mask_threshold: f32,
    // Phase D — effective elastic modulus used by the wave-Laplacian force.
    // Decoupled from ``E`` so stress / yield arithmetic stays calibrated
    // while the wave-front propagation can be retuned per material via
    // ``CellMaterial.wave_crossing_frames``.
    E_wave: f32,
    // Engine-wide KE → heat scaling (CellConfig.heat_damping_to_heat_factor
    // in config/physics.yml).  Pulled out of the legacy hard-coded ``0.5``
    // so the GPU and CPU kernels share a single tunable.
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

// Bind group layout (4 bindings — silhouette gating is performed via the
// density-threshold check at the end of the kernel, so a separate ``mask``
// storage buffer is not required).  Bindings are contiguous 0..3 to keep
// the auto-inferred bind group layout consistent with the Python host code.
@group(0) @binding(0) var<storage, read>       per_hull_params: array<HullParams>;
@group(0) @binding(1) var<storage, read>       src:  array<PixelState>;
@group(0) @binding(2) var<storage, read_write> dst:  array<PixelState>;
@group(0) @binding(3) var<storage, read>       active_hulls: array<u32>;

// NaN/inf-safety clamps — mirror ``PhysicsWorld._cpu_kernel`` write-back
// guard rails (world.py ~ line 1880).  Without these the GPU path lets
// ``heat`` / ``v`` / ``u`` / ``pressure`` drift past float32-safe ranges
// across long substep histories, eventually producing inf that propagates
// into boundary_exchange (``invalid value encountered in multiply``) and
// the renderer's forward-splat cast (``invalid value encountered in cast``).
// Limits sit well below float32 overflow but generously above any
// physically meaningful value for the per-pixel sim.
const _U_LIMIT:        f32 = 1.0e8;
const _V_LIMIT:        f32 = 1.0e6;
const _HEAT_LIMIT:     f32 = 1.0e6;
const _PRESSURE_LIMIT: f32 = 1.0e8;

// WGSL core has no isnan/isinf intrinsic, but ``x != x`` is true only
// for NaN, and ``clamp`` resolves inf to its bound.  Combined these give
// a branch-free NaN-replace + range clamp.
fn sanitize_f32(x: f32, lo: f32, hi: f32) -> f32 {
    let y = select(x, 0.0, x != x);
    return clamp(y, lo, hi);
}

fn sanitize_vec2(v: vec2<f32>, lo: f32, hi: f32) -> vec2<f32> {
    return vec2<f32>(sanitize_f32(v.x, lo, hi), sanitize_f32(v.y, lo, hi));
}


fn read_state(cell_base: u32, x: i32, y: i32, w: u32, h: u32) -> PixelState {
    let xi = clamp(x, 0, i32(w) - 1);
    let yi = clamp(y, 0, i32(h) - 1);
    return src[cell_base + u32(yi) * w + u32(xi)];
}

fn in_bounds(x: i32, y: i32, w: u32, h: u32) -> f32 {
    if x < 0 || y < 0 || x >= i32(w) || y >= i32(h) {
        return 0.0;
    }
    return 1.0;
}

@compute @workgroup_size(8, 8)
fn main(
    @builtin(global_invocation_id) gid: vec3<u32>,
    @builtin(workgroup_id) wgid: vec3<u32>,
) {
    // Pick the per-hull parameter record and cell-pool slot for this dispatch.
    let p = per_hull_params[wgid.z];
    if gid.x >= p.width || gid.y >= p.height { return; }

    let cell_slot = active_hulls[wgid.z];
    let cells_per_slot: u32 = p.width * p.height;
    let cell_base = cell_slot * cells_per_slot;
    let mask_base = cell_slot * cells_per_slot;

    let idx = cell_base + gid.y * p.width + gid.x;

    let s = src[idx];

    let ix = i32(gid.x);
    let iy = i32(gid.y);
    let s_l = read_state(cell_base, ix - 1, iy, p.width, p.height);
    let s_r = read_state(cell_base, ix + 1, iy, p.width, p.height);
    let s_t = read_state(cell_base, ix, iy - 1, p.width, p.height);
    let s_b = read_state(cell_base, ix, iy + 1, p.width, p.height);

    // bond_w = east bond of left neighbour; bond_n = south bond of top neighbour
    let b_l = s_l.bond_e;
    let b_r = s.bond_e;
    let b_t = s_t.bond_s;
    let b_b = s.bond_s;

    let in_l = in_bounds(ix - 1, iy, p.width, p.height);
    let in_r = in_bounds(ix + 1, iy, p.width, p.height);
    let in_t = in_bounds(ix, iy - 1, p.width, p.height);
    let in_b = in_bounds(ix, iy + 1, p.width, p.height);
    let m_l = s_l.density * b_l * in_l;
    let m_r = s_r.density * b_r * in_r;
    let m_t = s_t.density * b_t * in_t;
    let m_b = s_b.density * b_b * in_b;

    let u_l = s_l.u * m_l;
    let u_r = s_r.u * m_r;
    let u_t = s_t.u * m_t;
    let u_b = s_b.u * m_b;

    // Strain tensor (central differences).
    let eps_xx = (u_r.x - u_l.x) * 0.5;
    let eps_yy = (u_b.y - u_t.y) * 0.5;
    let eps_xy = ((u_r.y - u_l.y) + (u_b.x - u_t.x)) * 0.25;

    // Stretch metric.
    let dux_dx = u_r.x - u_l.x;
    let duy_dy = u_b.y - u_t.y;
    let dux_dy = u_t.x - u_b.x;
    let duy_dx = u_r.y - u_l.y;
    let stretch_now = sqrt(dux_dx * dux_dx + duy_dy * duy_dy
                          + dux_dy * dux_dy + duy_dx * duy_dx);

    // Elastic stress (Hooke minus permanent strain).
    let eps_el_xx = eps_xx - s.perm_strain_xx;
    let eps_el_yy = eps_yy - s.perm_strain_yy;
    let eps_el_xy = eps_xy - s.perm_strain_xy;
    let sigma_xx = p.E * eps_el_xx;
    let sigma_yy = p.E * eps_el_yy;
    let sigma_xy = p.E * eps_el_xy;
    let s_mean = (sigma_xx + sigma_yy) * 0.5;
    let s_dev_xx = sigma_xx - s_mean;
    let s_dev_yy = sigma_yy - s_mean;
    let vm = sqrt(s_dev_xx * s_dev_xx + s_dev_yy * s_dev_yy
                  + 3.0 * sigma_xy * sigma_xy);

    // Laplacian force on u (linearised elasticity).
    // Phase D: use ``E_wave`` (renormalised modulus driving the visible
    // wave-front speed) rather than the raw ``E`` (stress / yield scale).
    let lap_u_x = u_l.x + u_r.x + u_t.x + u_b.x - 4.0 * s.u.x * s.density;
    let lap_u_y = u_l.y + u_r.y + u_t.y + u_b.y - 4.0 * s.u.y * s.density;
    var f_x = p.E_wave * lap_u_x;
    var f_y = p.E_wave * lap_u_y;

    if p.is_fluid == 1u {
        let p_l = s_l.pressure * m_l;
        let p_r = s_r.pressure * m_r;
        let p_t = s_t.pressure * m_t;
        let p_b = s_b.pressure * m_b;
        f_x = f_x - (p_r - p_l);
        f_y = f_y - (p_b - p_t);
    }

    // Mass-modulated integration.
    let mass = max(p.rho * s.density, 0.001);
    var v = s.v + vec2<f32>(f_x, f_y) * (p.dt / mass);

    // Bond-intact damping.
    let bond_intact = clamp(
        1.0 - max(0.0, s.tear - p.bond_intact_threshold) * p.bond_intact_slope,
        0.0, 1.0
    );
    let effective_D = p.torn_damping * (1.0 - bond_intact) + p.viscosity * bond_intact;
    v = v * effective_D;

    // Heat path.
    let v_mag2 = v.x * v.x + v.y * v.y;
    let ke = 0.5 * mass * v_mag2;
    let damped_ke = ke * (1.0 - effective_D * effective_D);
    // Symmetric, conservation-preserving heat-diffusion stencil:
    //   heat_lap[i] = sum_j c_ij * (h[j] - h[i])
    // Pulling the self-coefficient from the same m_* weights as the
    // inflow makes the inter-cell flux antisymmetric in (i, j) so total
    // heat is conserved.  The legacy ``-4 * heat * density`` form was
    // asymmetric (inflow weighted by neighbour density, self-term by
    // own density), which let heat accumulate in partial-density edge
    // cells every substep — root cause of the WP-O frame-229 inf
    // cascade that originated at lava cell (31, 21) with density ~0.07.
    let heat_lap = s_l.heat * m_l + s_r.heat * m_r
                 + s_t.heat * m_t + s_b.heat * m_b
                 - s.heat * (m_l + m_r + m_t + m_b);
    var heat = s.heat + heat_lap * p.dt * p.thermal_k;
    // Density-weighted KE → heat injection (mirrors CPU kernel).  Skipped
    // for fluids: the discrete viscous-dissipation form double-counts the
    // KE→heat conversion at high-viscosity fluids (LAVA at viscosity=0.65
    // dumps 57.8 % of cell KE into heat per substep), forming a positive
    // feedback loop with thermal softening that saturates the 1e6 heat
    // clamp by frame ~60 of the lava-flow demo.  Fluids rely on
    // BoundaryExchange / emissivity for thermal state changes (WP-T).
    if p.is_fluid == 0u {
        heat = heat + damped_ke * p.heat_damping_to_heat_factor * s.density;
    }
    heat = heat * (1.0 - p.emissivity);

    // Thermal + damage weakening of yield surfaces.
    let soft_factor = 1.0 / (1.0 + heat * p.thermal_softening_coefficient);
    let damage_factor = 1.0 - clamp(
        s.damage * p.damage_weakening_coefficient,
        0.0, p.damage_weakening_coefficient
    );
    let weakness = soft_factor * damage_factor;
    let Y_eff = p.Y * weakness;
    let brittle_eff = p.brittle_modulus * weakness;

    // Plastic / fracture branches.
    var perm_xx = s.perm_strain_xx;
    var perm_yy = s.perm_strain_yy;
    var perm_xy = s.perm_strain_xy;
    var dmg = s.damage;
    var tear = s.tear;
    var bond_n_new = s.bond_n;
    var bond_e_new = s.bond_e;
    var bond_s_new = s.bond_s;

    let is_melted = heat > p.melt_point;
    if is_melted {
        perm_xx = perm_xx * p.melt_anneal_rate;
        perm_yy = perm_yy * p.melt_anneal_rate;
        perm_xy = perm_xy * p.melt_anneal_rate;
        v = v * p.melt_viscous_damping;
    }

    let is_brittle_material = p.brittle_modulus < 800.0;
    let brittle = (!is_melted) && (vm > brittle_eff) && is_brittle_material;
    if brittle {
        let excess_b = vm - brittle_eff;
        dmg = clamp(dmg + excess_b * p.dt * p.brittle_damage_rate, 0.0, 1.0);
        tear = clamp(tear + excess_b * p.dt * p.brittle_tear_rate, 0.0, 1.5);
        let bond_loss = excess_b * p.dt * p.brittle_bond_loss_rate
                      * (1.0 + stretch_now * p.brittle_stretch_amplification);
        let sever_h = abs(sigma_xx) > abs(sigma_yy);
        if sever_h {
            bond_e_new = max(0.0, bond_e_new - bond_loss);
        } else {
            bond_s_new = max(0.0, bond_s_new - bond_loss);
        }
        // Catastrophic severance — see WP-V notes in the Python kernel.
        let cat_excess = brittle_eff * (p.brittle_catastrophic_excess_ratio - 1.0);
        if excess_b > cat_excess && dmg > p.brittle_catastrophic_damage_gate {
            if sever_h {
                bond_e_new = min(bond_e_new, p.brittle_catastrophic_bond_floor);
            } else {
                bond_s_new = min(bond_s_new, p.brittle_catastrophic_bond_floor);
            }
        }
    }

    let ductile = (!is_melted) && (!brittle) && (vm > Y_eff);
    if ductile {
        let s_diff = (sigma_xx - sigma_yy) * 0.5;
        let R_stress = sqrt(s_diff * s_diff + sigma_xy * sigma_xy);
        let theta = 0.5 * atan2(sigma_xy, s_diff);
        let ct = cos(theta);
        let st_ = sin(theta);
        let ct2 = ct * ct;
        let st2 = st_ * st_;
        let excess_d = (vm - Y_eff) / max(vm, 1e-4);
        let d_eps_1 = excess_d * p.ductile_plastic_strain_rate
                    * R_stress / max(p.E, 1.0);
        let d_eps_2 = -d_eps_1 * p.ductile_poisson_ratio;
        let d_eps_xx = d_eps_1 * ct2 + d_eps_2 * st2;
        let d_eps_yy = d_eps_1 * st2 + d_eps_2 * ct2;
        let d_eps_xy = (d_eps_1 - d_eps_2) * st_ * ct;
        perm_xx = perm_xx + d_eps_xx;
        perm_yy = perm_yy + d_eps_yy;
        perm_xy = perm_xy + d_eps_xy;
        dmg = clamp(dmg + (vm - Y_eff) * p.dt * p.ductile_damage_rate, 0.0, 1.0);
        let strain_energy = 0.5 * p.E *
            (eps_el_xx * eps_el_xx + eps_el_yy * eps_el_yy
             + 2.0 * eps_el_xy * eps_el_xy) * excess_d;
        // Density-weighted plastic-work → heat (mirrors CPU kernel).
        // Fluids skip this injection — their irreversible dissipation lives
        // in the viscous-damping ``damped_ke`` term above.  Running the
        // ductile branch for LAVA injects a runaway ``0.5 * E * eps²``
        // every substep once heat dips just past ``melt_point`` (WP-T).
        if p.is_fluid == 0u {
            heat = heat + strain_energy * p.heat_strain_energy_factor * s.density;
        }
    }

    // Remold (anneal plastic strain).
    let remold_decay = 1.0 - p.remold_rate * p.dt * 60.0;
    perm_xx = perm_xx * remold_decay;
    perm_yy = perm_yy * remold_decay;
    perm_xy = perm_xy * remold_decay;

    // Stretch-driven tearing.
    if p.tear_strength < 800.0 {
        if stretch_now > p.tear_strength {
            let excess_t = stretch_now - p.tear_strength;
            tear = clamp(tear + excess_t * p.dt * p.tear_growth_rate, 0.0, 1.5);
        }
    }

    // Update displacement.
    var u_new = s.u + v * p.dt;

    // Fluid pressure update.
    var pressure = s.pressure;
    if p.is_fluid == 1u {
        let div_v = (s_r.v.x * m_r - s_l.v.x * m_l
                   + s_b.v.y * m_b - s_t.v.y * m_t) * 0.5;
        pressure = pressure - div_v * p.E * p.dt * p.fluid_pressure_coupling;
        let p_avg = (s_l.pressure * m_l + s_r.pressure * m_r
                   + s_t.pressure * m_t + s_b.pressure * m_b) * 0.25;
        pressure = pressure * (1.0 - p.fluid_pressure_smoothing)
                 + p_avg * p.fluid_pressure_smoothing;
        pressure = pressure * p.fluid_pressure_decay;
    }

    // Silhouette mask.  Heat is also zeroed in vacuum cells: those have
    // no thermal mass, so any residue accumulated through the asymmetric
    // legacy Laplacian (or boundary effects) must not persist between
    // substeps.  See the symmetric heat_lap stencil above.
    let outside = s.density < p.silhouette_mask_threshold;
    if outside {
        u_new = vec2<f32>(0.0, 0.0);
        v = vec2<f32>(0.0, 0.0);
        heat = 0.0;
    }

    let density = s.density;

    // Final NaN/inf-safety clamps — match the CPU kernel write-back
    // guard rails (world.py ~ line 1880).  Branch-free sanitize+clamp on
    // each persisted float so the cell pool is *never* stored with
    // non-finite values; this is what removes the upstream source of the
    // ``invalid value encountered in cast`` warnings the renderer raises.
    u_new    = sanitize_vec2(u_new, -_U_LIMIT, _U_LIMIT);
    v        = sanitize_vec2(v,     -_V_LIMIT, _V_LIMIT);
    heat     = sanitize_f32(heat,     0.0,             _HEAT_LIMIT);
    pressure = sanitize_f32(pressure, -_PRESSURE_LIMIT, _PRESSURE_LIMIT);

    dst[idx] = PixelState(
        u_new, v,
        perm_xx, perm_yy, perm_xy,
        pressure, dmg, density, stretch_now, tear, heat,
        bond_n_new, bond_e_new, bond_s_new,
    );
}
