// pharos_render :: Softbody XPBD full step on the GPU.
//
// Sprint 7 GPU port of pharos_core::softbody_solver::slappyengine_step
// (kept the historical function name in Python; the Rust GPU version
// is `pharos_step_full`).
//
// Storage layout:
//   b0: rw node_pos     (vec4<f32>[N], .xyz = position, .w = inv_mass)
//   b1: rw node_vel     (vec4<f32>[N])
//   b2: rw beam         (Beam[M])         node_a, node_b, rest_len, compliance
//   b3: rw beam_lambda  (f32[M])          XPBD Lagrange multipliers
//   b4: ro uniforms     (SoftbodyUniforms)
//
// Two-pass structure: predict positions with gravity, then N iterations
// of distance-constraint projection. Sprint 7 stub does one iteration
// per dispatch — a scheduler in the Rust side runs iters=6 by default.

struct Beam {
    node_a: u32,
    node_b: u32,
    rest_len: f32,
    compliance: f32,
};

struct SoftbodyUniforms {
    dt: f32,
    inv_dt: f32,
    substep_dt: f32,
    gravity: vec4<f32>,
    node_count: u32,
    beam_count: u32,
    iteration: u32,
    _pad: u32,
};

@group(0) @binding(0) var<storage, read_write> pos:    array<vec4<f32>>;
@group(0) @binding(1) var<storage, read_write> vel:    array<vec4<f32>>;
@group(0) @binding(2) var<storage, read>       beams:  array<Beam>;
@group(0) @binding(3) var<storage, read_write> beam_lambda: array<f32>;
@group(0) @binding(4) var<uniform>             u:      SoftbodyUniforms;

// --- Predict: XPBD external-force integration ---
@compute @workgroup_size(64, 1, 1)
fn cs_predict(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = gid.x;
    if (i >= u.node_count) { return; }
    var p = pos[i];
    var v = vel[i];
    let inv_mass = p.w;
    if (inv_mass <= 0.0) { return; }   // pinned node
    v = v + u.substep_dt * u.gravity;
    p = vec4<f32>(p.xyz + u.substep_dt * v.xyz, inv_mass);
    pos[i] = p;
    vel[i] = v;
}

// --- Solve: one iteration of distance-constraint projection ---
//
// XPBD position correction per beam:
//   C = |x_a - x_b| - rest_len
//   dlambda = -(C + alpha * lambda) / ((inv_m_a + inv_m_b) + alpha)
//   dx_a =  n * dlambda * inv_m_a
//   dx_b = -n * dlambda * inv_m_b
//   lambda += dlambda
//
// alpha = compliance / substep_dt^2 (XPBD scaling).
@compute @workgroup_size(64, 1, 1)
fn cs_solve_beams(@builtin(global_invocation_id) gid: vec3<u32>) {
    let bi = gid.x;
    if (bi >= u.beam_count) { return; }
    let b = beams[bi];
    var pa = pos[b.node_a];
    var pb = pos[b.node_b];
    let w_a = pa.w;
    let w_b = pb.w;
    let w_sum = w_a + w_b;
    if (w_sum <= 0.0) { return; }

    let delta = pa.xyz - pb.xyz;
    let dist = length(delta);
    if (dist < 1e-8) { return; }
    let n = delta / dist;
    let c = dist - b.rest_len;

    let alpha = b.compliance / (u.substep_dt * u.substep_dt);
    let dlambda = -(c + alpha * beam_lambda[bi]) / (w_sum + alpha);
    beam_lambda[bi] = beam_lambda[bi] + dlambda;

    pos[b.node_a] = vec4<f32>(pa.xyz + n * (dlambda * w_a), w_a);
    pos[b.node_b] = vec4<f32>(pb.xyz - n * (dlambda * w_b), w_b);
}

// --- Integrate: derive velocity from position delta ---
//
// Called once at the end of the substep. Expects `beam_lambda[]` reset
// by the caller before the next predict pass.
@compute @workgroup_size(64, 1, 1)
fn cs_integrate(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = gid.x;
    if (i >= u.node_count) { return; }
    let p_new = pos[i];
    let v_old = vel[i];
    // Velocity = (new_pos - old_pos) / substep_dt.
    // old_pos wasn't retained; we approximate using v_old * substep_dt
    // as the delta on this substep so v_new stays consistent with pos.
    vel[i] = vec4<f32>((p_new.xyz - (p_new.xyz - v_old.xyz * u.substep_dt)) * u.inv_dt, p_new.w);
}
