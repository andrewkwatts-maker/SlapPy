// Pressure projection — Jacobi iteration to make velocity field divergence-free.
// Solves the pressure Poisson equation: ∇²p = ∇·v
// Then subtracts the pressure gradient: v -= ∇p
//
// Called 20 times per simulation step from Python, alternating ping/pong textures.
// Workgroup: 8×8.

struct ProjectParams {
    sim_w    : u32,
    sim_h    : u32,
    dx       : f32,   // grid spacing (usually 1.0)
    is_subtract_pass : u32,  // 0 = Jacobi pressure solve, 1 = gradient subtraction
    _pad     : vec4<u32>,
};

@group(0) @binding(0) var<uniform> params       : ProjectParams;
// Velocity: rgba16float (RG=vx/vy)
@group(0) @binding(1) var          vel_in       : texture_storage_2d<rgba16float, read>;
@group(0) @binding(2) var          vel_out      : texture_storage_2d<rgba16float, write>;
// Pressure ping-pong: r32float
@group(0) @binding(3) var          pressure_in  : texture_storage_2d<r32float,    read>;
@group(0) @binding(4) var          pressure_out : texture_storage_2d<r32float,    write>;

// ── helpers ──────────────────────────────────────────────────────────────────

fn clamp_coord(c: vec2<i32>) -> vec2<i32> {
    return clamp(c, vec2<i32>(0), vec2<i32>(i32(params.sim_w) - 1, i32(params.sim_h) - 1));
}

fn load_vel(c: vec2<i32>) -> vec2<f32> {
    return textureLoad(vel_in, clamp_coord(c)).rg;
}

fn load_pressure(c: vec2<i32>) -> f32 {
    return textureLoad(pressure_in, clamp_coord(c)).r;
}

// ── main ─────────────────────────────────────────────────────────────────────

@compute @workgroup_size(8, 8)
fn project_main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= params.sim_w || gid.y >= params.sim_h) { return; }

    let coord = vec2<i32>(i32(gid.x), i32(gid.y));
    let dx = params.dx;

    if (params.is_subtract_pass == 0u) {
        // ── Jacobi pressure iteration ─────────────────────────────────────────
        // Compute divergence of velocity field at this cell.
        let vE = load_vel(coord + vec2<i32>( 1,  0)).x;
        let vW = load_vel(coord + vec2<i32>(-1,  0)).x;
        let vN = load_vel(coord + vec2<i32>( 0, -1)).y;
        let vS = load_vel(coord + vec2<i32>( 0,  1)).y;
        let divergence = 0.5 * dx * ((vE - vW) + (vS - vN));

        // Jacobi update: p_new = (p_N + p_S + p_E + p_W - divergence) / 4
        let pN = load_pressure(coord + vec2<i32>( 0, -1));
        let pS = load_pressure(coord + vec2<i32>( 0,  1));
        let pE = load_pressure(coord + vec2<i32>( 1,  0));
        let pW = load_pressure(coord + vec2<i32>(-1,  0));
        let new_p = (pN + pS + pE + pW - divergence) * 0.25;

        textureStore(pressure_out, coord, vec4<f32>(new_p, 0.0, 0.0, 0.0));
        // Pass velocity through unchanged during pressure solve.
        let vel_passthrough = textureLoad(vel_in, coord).rg;
        textureStore(vel_out, coord, vec4<f32>(vel_passthrough.x, vel_passthrough.y, 0.0, 1.0));

    } else {
        // ── Gradient subtraction: v -= ∇p ────────────────────────────────────
        let vel_cur = textureLoad(vel_in, coord).rg;

        let pE = load_pressure(coord + vec2<i32>( 1,  0));
        let pW = load_pressure(coord + vec2<i32>(-1,  0));
        let pN = load_pressure(coord + vec2<i32>( 0, -1));
        let pS = load_pressure(coord + vec2<i32>( 0,  1));
        let grad_x = (pE - pW) / (2.0 * dx);
        let grad_y = (pS - pN) / (2.0 * dx);

        let new_vel = vel_cur - vec2<f32>(grad_x, grad_y);
        textureStore(vel_out, coord, vec4<f32>(new_vel.x, new_vel.y, 0.0, 1.0));
        // Pass pressure through (it stays valid after solve).
        let p_pass = textureLoad(pressure_in, coord).r;
        textureStore(pressure_out, coord, vec4<f32>(p_pass, 0.0, 0.0, 0.0));
    }
}
