// pixel_physics.wgsl — per-pixel physics simulation
// Dispatched per-frame over each asset's pixel struct buffer.

struct PixelPhysics {
    vel_x:       f32,
    vel_y:       f32,
    mass:        f32,
    friction:    f32,
    elasticity:  f32,
    temperature: f32,
    state:       u32,
    _pad:        u32,
};

struct Params {
    dt:        f32,
    gravity:   f32,
    melt_temp: f32,
    boil_temp: f32,
    max_vel:   f32,
    width:     u32,
    height:    u32,
    _pad:      u32,
};

@group(0) @binding(0) var<storage, read_write> pixels: array<PixelPhysics>;
@group(0) @binding(1) var<uniform> params: Params;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let idx = gid.y * params.width + gid.x;
    if (gid.x >= params.width || gid.y >= params.height) { return; }

    var p = pixels[idx];

    // Static pixels (mass==0) only have state transitions, no motion
    if (p.mass <= 0.0) {
        p = state_transition(p, params);
        pixels[idx] = p;
        return;
    }

    // Gravity (downward = positive y)
    p.vel_y = p.vel_y + params.gravity * params.dt;

    // Speed cap
    let speed = sqrt(p.vel_x * p.vel_x + p.vel_y * p.vel_y);
    if (speed > params.max_vel) {
        let s = params.max_vel / speed;
        p.vel_x = p.vel_x * s;
        p.vel_y = p.vel_y * s;
    }

    // Friction (lateral damping when near-grounded)
    if (abs(p.vel_y) < 10.0) {
        p.vel_x = p.vel_x * (1.0 - p.friction * params.dt);
    }

    // Solid neighbour below? Bounce.
    let below_idx = (gid.y + 1u) * params.width + gid.x;
    if (gid.y + 1u < params.height) {
        let below = pixels[below_idx];
        if (below.mass <= 0.0 && p.vel_y > 0.0) {
            p.vel_y = -p.vel_y * p.elasticity;
            p.vel_x = p.vel_x * (1.0 - p.friction);
        }
    } else if (p.vel_y > 0.0) {
        // At bottom edge
        p.vel_y = -p.vel_y * p.elasticity;
    }

    p = state_transition(p, params);
    pixels[idx] = p;
}

fn state_transition(p: PixelPhysics, params: Params) -> PixelPhysics {
    var out = p;
    // Melting: solid -> liquid
    if (out.state == 0u && out.temperature > params.melt_temp && out.mass > 0.0) {
        out.state = 1u;
        out.friction = out.friction * 0.1;  // liquid has low friction
    }
    // Boiling: liquid -> gas
    if (out.state == 1u && out.temperature > params.boil_temp) {
        out.state = 2u;
        out.vel_y = out.vel_y - 50.0;       // gas rises
    }
    // Condensing: gas -> liquid
    if (out.state == 2u && out.temperature < params.melt_temp * 0.5) {
        out.state = 1u;
    }
    // Freezing: liquid -> solid
    if (out.state == 1u && out.temperature < params.melt_temp * 0.3) {
        out.state = 0u;
    }
    // Plasma: extremely hot gas
    if (out.state == 2u && out.temperature > 3000.0) {
        out.state = 3u;
    }
    if (out.state == 3u && out.temperature < 2000.0) {
        out.state = 2u;
    }
    return out;
}
