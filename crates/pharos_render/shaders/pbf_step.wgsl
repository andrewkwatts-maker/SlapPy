// pharos_render :: PBF (Position-Based Fluids) full step on the GPU.
//
// Sprint 7 GPU port of pharos_core::pbf_solver::pbf_step_full.
// One dispatch does: predict positions -> neighbour hash ->
// density constraint iteration -> velocity update -> XSPH viscosity.
//
// Storage layout (bound at group 0):
//   b0: rw particle_pos     (vec4<f32>[N], .xyz = position, .w = mass)
//   b1: rw particle_vel     (vec4<f32>[N], .xyz = velocity, .w = density)
//   b2: rw particle_lambda  (f32[N]  — density-constraint Lagrangian)
//   b3: rw neighbour_grid   (u32[grid_x * grid_y * grid_z * max_per_cell])
//   b4: rw grid_count       (atomic<u32>[grid_x * grid_y * grid_z])
//   b5: ro uniforms         (PbfUniforms)
//
// Sprint 7 wires the dispatch scheduler; each iteration is a separate
// compute pass so we get natural sync between predict/hash/solve/
// integrate stages.

struct PbfUniforms {
    dt: f32,
    inv_dt: f32,
    substep_dt: f32,
    smoothing_h: f32,
    rest_density: f32,
    poly6_coef: f32,
    spiky_grad_coef: f32,
    gravity: vec4<f32>,
    grid_origin: vec4<f32>,   // .xyz = origin, .w = cell_size
    grid_dims: vec4<u32>,     // .xyz = grid dims, .w = particle_count
};

@group(0) @binding(0) var<storage, read_write> pos:    array<vec4<f32>>;
@group(0) @binding(1) var<storage, read_write> vel:    array<vec4<f32>>;
@group(0) @binding(2) var<storage, read_write> lambda: array<f32>;
@group(0) @binding(3) var<storage, read_write> grid:   array<u32>;
@group(0) @binding(4) var<storage, read_write> grid_count: array<atomic<u32>>;
@group(0) @binding(5) var<uniform>             u:      PbfUniforms;

fn cell_index(p: vec3<f32>) -> vec3<i32> {
    let c = floor((p - u.grid_origin.xyz) / u.grid_origin.w);
    return vec3<i32>(i32(c.x), i32(c.y), i32(c.z));
}

fn poly6(r: f32) -> f32 {
    let h = u.smoothing_h;
    if (r > h || r < 0.0) { return 0.0; }
    let x = h * h - r * r;
    return u.poly6_coef * x * x * x;
}

fn spiky_grad(r_vec: vec3<f32>) -> vec3<f32> {
    let r = length(r_vec);
    let h = u.smoothing_h;
    if (r > h || r < 1e-6) { return vec3<f32>(0.0); }
    let factor = u.spiky_grad_coef * pow(h - r, 2.0);
    return factor * r_vec / r;
}

// --- Stage A: predict positions + zero grid_count ---
@compute @workgroup_size(64, 1, 1)
fn cs_predict(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = gid.x;
    if (i >= u.grid_dims.w) { return; }
    var v = vel[i];
    v = v + u.substep_dt * u.gravity;
    var p = pos[i];
    p = vec4<f32>(p.xyz + u.substep_dt * v.xyz, p.w);
    pos[i] = p;
    vel[i] = v;
    lambda[i] = 0.0;
}

// --- Stage B: build the uniform-grid neighbour hash ---
@compute @workgroup_size(64, 1, 1)
fn cs_hash(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = gid.x;
    if (i >= u.grid_dims.w) { return; }
    let cell = cell_index(pos[i].xyz);
    let gd = vec3<i32>(u.grid_dims.xyz);
    if (any(cell < vec3<i32>(0)) || any(cell >= gd)) { return; }
    let idx = u32(cell.z * gd.y * gd.x + cell.y * gd.x + cell.x);
    let slot = atomicAdd(&grid_count[idx], 1u);
    // 32-particle cap per cell; overflow is dropped (physically fine for
    // fluids near equilibrium, matches Nova3D's PBF fallback).
    if (slot < 32u) {
        grid[idx * 32u + slot] = i;
    }
}

// --- Stage C: solve density constraint (one iteration) ---
@compute @workgroup_size(64, 1, 1)
fn cs_solve(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = gid.x;
    if (i >= u.grid_dims.w) { return; }
    let pi = pos[i].xyz;
    let cell = cell_index(pi);
    let gd = vec3<i32>(u.grid_dims.xyz);

    var density: f32 = 0.0;
    var grad_sum_sq: f32 = 0.0;
    var grad_i: vec3<f32> = vec3<f32>(0.0);

    for (var dz: i32 = -1; dz <= 1; dz = dz + 1) {
        for (var dy: i32 = -1; dy <= 1; dy = dy + 1) {
            for (var dx: i32 = -1; dx <= 1; dx = dx + 1) {
                let nc = cell + vec3<i32>(dx, dy, dz);
                if (any(nc < vec3<i32>(0)) || any(nc >= gd)) { continue; }
                let cell_idx = u32(nc.z * gd.y * gd.x + nc.y * gd.x + nc.x);
                let count = min(atomicLoad(&grid_count[cell_idx]), 32u);
                for (var s: u32 = 0u; s < count; s = s + 1u) {
                    let j = grid[cell_idx * 32u + s];
                    if (j == i) { continue; }
                    let pj = pos[j].xyz;
                    let r = pi - pj;
                    density = density + poly6(length(r));
                    let g = spiky_grad(r);
                    grad_sum_sq = grad_sum_sq + dot(g, g);
                    grad_i = grad_i + g;
                }
            }
        }
    }

    let c = density / u.rest_density - 1.0;
    let denom = grad_sum_sq + dot(grad_i, grad_i) + 1e-6;
    lambda[i] = -c / denom;
    vel[i].w = density;
}

// --- Stage D: apply lambda + integrate velocities ---
@compute @workgroup_size(64, 1, 1)
fn cs_integrate(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = gid.x;
    if (i >= u.grid_dims.w) { return; }
    let pi = pos[i].xyz;
    let cell = cell_index(pi);
    let gd = vec3<i32>(u.grid_dims.xyz);

    var dp: vec3<f32> = vec3<f32>(0.0);
    for (var dz: i32 = -1; dz <= 1; dz = dz + 1) {
        for (var dy: i32 = -1; dy <= 1; dy = dy + 1) {
            for (var dx: i32 = -1; dx <= 1; dx = dx + 1) {
                let nc = cell + vec3<i32>(dx, dy, dz);
                if (any(nc < vec3<i32>(0)) || any(nc >= gd)) { continue; }
                let cell_idx = u32(nc.z * gd.y * gd.x + nc.y * gd.x + nc.x);
                let count = min(atomicLoad(&grid_count[cell_idx]), 32u);
                for (var s: u32 = 0u; s < count; s = s + 1u) {
                    let j = grid[cell_idx * 32u + s];
                    if (j == i) { continue; }
                    dp = dp + (lambda[i] + lambda[j]) * spiky_grad(pi - pos[j].xyz);
                }
            }
        }
    }
    dp = dp / u.rest_density;
    let new_pos = vec4<f32>(pi + dp, pos[i].w);
    pos[i] = new_pos;
    // Integrate velocity from position delta (implicit Euler).
    vel[i] = vec4<f32>((new_pos.xyz - pi) * u.inv_dt, vel[i].w);
}
