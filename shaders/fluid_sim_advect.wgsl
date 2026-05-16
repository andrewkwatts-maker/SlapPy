// Fluid simulation: semi-Lagrangian advection + diffusion + buoyancy/gravity + border wrap.
// Dispatched once per active LOD zone per frame.
// Workgroup: 8×8.

struct SimParams {
    sim_w        : u32,
    sim_h        : u32,
    pad_x        : u32,
    pad_y        : u32,
    dt           : f32,
    viscosity    : f32,
    diffusion    : f32,
    buoyancy     : f32,
    gravity      : f32,
    density_decay: f32,
    velocity_decay: f32,
    zone         : u32,
    zone_skip    : u32,
    _pad         : vec2<u32>,
};

@group(0) @binding(0) var<uniform>                    params      : SimParams;
@group(0) @binding(1) var                             vel_in      : texture_storage_2d<rgba16float, read>;
@group(0) @binding(2) var                             vel_out     : texture_storage_2d<rgba16float, write>;
@group(0) @binding(3) var                             density_in  : texture_storage_2d<rgba8unorm,  read>;
@group(0) @binding(4) var                             density_out : texture_storage_2d<rgba8unorm,  write>;
@group(0) @binding(5) var                             initial_density : texture_2d<f32>;

// ── helpers ──────────────────────────────────────────────────────────────────

fn clamp_coord(c: vec2<i32>) -> vec2<i32> {
    return clamp(c, vec2<i32>(0), vec2<i32>(i32(params.sim_w) - 1, i32(params.sim_h) - 1));
}

// Bilinear sample from a rgba16float storage texture (velocity).
fn sample_vel_bilinear(pos: vec2<f32>) -> vec2<f32> {
    let x0 = i32(floor(pos.x));
    let y0 = i32(floor(pos.y));
    let x1 = x0 + 1;
    let y1 = y0 + 1;
    let tx = fract(pos.x);
    let ty = fract(pos.y);

    let v00 = textureLoad(vel_in, clamp_coord(vec2<i32>(x0, y0))).rg;
    let v10 = textureLoad(vel_in, clamp_coord(vec2<i32>(x1, y0))).rg;
    let v01 = textureLoad(vel_in, clamp_coord(vec2<i32>(x0, y1))).rg;
    let v11 = textureLoad(vel_in, clamp_coord(vec2<i32>(x1, y1))).rg;

    return mix(mix(v00, v10, tx), mix(v01, v11, tx), ty);
}

// Bilinear sample from a rgba8unorm storage texture (density/temperature).
fn sample_den_bilinear(pos: vec2<f32>) -> vec2<f32> {
    let x0 = i32(floor(pos.x));
    let y0 = i32(floor(pos.y));
    let x1 = x0 + 1;
    let y1 = y0 + 1;
    let tx = fract(pos.x);
    let ty = fract(pos.y);

    let d00 = textureLoad(density_in, clamp_coord(vec2<i32>(x0, y0))).rg;
    let d10 = textureLoad(density_in, clamp_coord(vec2<i32>(x1, y0))).rg;
    let d01 = textureLoad(density_in, clamp_coord(vec2<i32>(x0, y1))).rg;
    let d11 = textureLoad(density_in, clamp_coord(vec2<i32>(x1, y1))).rg;

    return mix(mix(d00, d10, tx), mix(d01, d11, tx), ty);
}

// Smoothstep border blend factor: 0 at border, 1 at >= 8 px inward.
fn border_blend(coord: vec2<u32>) -> f32 {
    let bx = f32(min(coord.x, params.sim_w  - 1u - coord.x));
    let by = f32(min(coord.y, params.sim_h - 1u - coord.y));
    let dist = min(bx, by);
    return smoothstep(0.0, 8.0, dist);
}

// ── main ─────────────────────────────────────────────────────────────────────

@compute @workgroup_size(8, 8)
fn advect_main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= params.sim_w || gid.y >= params.sim_h) { return; }

    let coord = vec2<i32>(i32(gid.x), i32(gid.y));
    let fcoord = vec2<f32>(f32(gid.x), f32(gid.y));

    // ── 1. Semi-Lagrangian advection: trace back along velocity ──────────────
    let vel_cur = textureLoad(vel_in, coord).rg;
    let back_pos = fcoord - vel_cur * params.dt;
    var new_vel = sample_vel_bilinear(back_pos);
    var new_den = sample_den_bilinear(back_pos);

    // ── 2. Diffusion: weighted average of 4 neighbours ───────────────────────
    let n = textureLoad(density_in, clamp_coord(coord + vec2<i32>( 0, -1))).rg;
    let s = textureLoad(density_in, clamp_coord(coord + vec2<i32>( 0,  1))).rg;
    let e = textureLoad(density_in, clamp_coord(coord + vec2<i32>( 1,  0))).rg;
    let w = textureLoad(density_in, clamp_coord(coord + vec2<i32>(-1,  0))).rg;
    let neighbour_avg = (n + s + e + w) * 0.25;
    new_den = mix(new_den, neighbour_avg, params.diffusion);

    // ── 3. Buoyancy: temperature (G channel) drives upward force ─────────────
    //    Positive buoyancy lifts warm fluid upward (−Y in screen coords).
    let temperature = new_den.g;
    new_vel.y -= params.buoyancy * temperature * params.dt;

    // ── 4. Gravity: downward pull on density ─────────────────────────────────
    new_vel.y += params.gravity * params.dt;

    // ── 5. Density decay (evaporation / dissipation) ─────────────────────────
    new_den.r *= params.density_decay;

    // ── 6. Velocity decay (viscous drag) ─────────────────────────────────────
    new_vel *= params.velocity_decay;

    // ── 7. Border wrap: lerp toward initial conditions near the edge ─────────
    let bt = border_blend(gid.xy);
    let init_den = textureLoad(initial_density, coord, 0).rg;
    new_den = mix(init_den, new_den, bt);
    // At the border, velocity also relaxes toward zero (fresh fluid, no momentum).
    new_vel = mix(vec2<f32>(0.0), new_vel, bt);

    // ── Write outputs ─────────────────────────────────────────────────────────
    textureStore(vel_out,     coord, vec4<f32>(new_vel.x, new_vel.y, 0.0, 1.0));
    textureStore(density_out, coord, vec4<f32>(new_den.r, new_den.g, 0.0, 1.0));
}
