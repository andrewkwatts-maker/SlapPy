// Fluid initial-condition generator.
// Writes rgba8unorm density texture: R=density, G=temperature, BA=0.
// Supports three noise modes (selected by params.noise_mode):
//   0 = fbm   (fractal brownian motion, 6 octaves of value noise)
//   1 = worley (cell noise → swirly voids)
//   2 = uniform (raw hash)

struct NoiseParams {
    sim_w      : u32,
    sim_h      : u32,
    noise_mode : u32,   // 0=fbm, 1=worley, 2=uniform
    seed       : u32,
    noise_scale: f32,
    _pad0      : f32,
    _pad1      : f32,
    _pad2      : f32,
};

@group(0) @binding(0) var<uniform>             params : NoiseParams;
@group(0) @binding(1) var                      out_tex: texture_storage_2d<rgba8unorm, write>;

// ── PRNG / hash helpers ──────────────────────────────────────────────────────

fn hash_u(v: u32) -> u32 {
    var x = v;
    x ^= x >> 16u;
    x *= 0x45d9f3bu;
    x ^= x >> 16u;
    return x;
}

fn hash2(x: u32, y: u32, seed: u32) -> u32 {
    return hash_u(hash_u(x) ^ hash_u(y ^ seed));
}

fn hash_to_f32(h: u32) -> f32 {
    // Map u32 to [0, 1]
    return f32(h & 0x00FFFFFFu) / f32(0x01000000u);
}

// Value noise on integer grid
fn value_noise(p: vec2<f32>, seed: u32) -> f32 {
    let ip = vec2<i32>(floor(p));
    let fp = fract(p);
    let u  = fp * fp * (3.0 - 2.0 * fp);  // smoothstep

    let a = hash_to_f32(hash2(u32(ip.x),     u32(ip.y),     seed));
    let b = hash_to_f32(hash2(u32(ip.x + 1), u32(ip.y),     seed));
    let c = hash_to_f32(hash2(u32(ip.x),     u32(ip.y + 1), seed));
    let d = hash_to_f32(hash2(u32(ip.x + 1), u32(ip.y + 1), seed));

    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

// FBM: 6 octaves of value noise
fn fbm(p: vec2<f32>, seed: u32) -> f32 {
    var val  = 0.0;
    var amp  = 0.5;
    var freq = 1.0;
    for (var i = 0u; i < 6u; i++) {
        val  += amp * value_noise(p * freq, seed + i * 7919u);
        amp  *= 0.5;
        freq *= 2.0;
    }
    return clamp(val, 0.0, 1.0);
}

// Worley noise: distance to nearest of 4 grid-cell neighbours
fn worley(p: vec2<f32>, seed: u32) -> f32 {
    let ip = vec2<i32>(floor(p));
    var min_dist = 1.0e9;
    for (var dy = -1; dy <= 1; dy++) {
        for (var dx = -1; dx <= 1; dx++) {
            let cell = vec2<i32>(ip.x + dx, ip.y + dy);
            let h1 = hash_to_f32(hash2(u32(cell.x), u32(cell.y), seed));
            let h2 = hash_to_f32(hash2(u32(cell.x) + 57u, u32(cell.y) + 131u, seed));
            let cell_pt = vec2<f32>(f32(cell.x) + h1, f32(cell.y) + h2);
            let d = length(p - cell_pt);
            min_dist = min(min_dist, d);
        }
    }
    // Invert so cell centres are bright (swirly voids around edges)
    return 1.0 / (1.0 + min_dist);
}

// ── main ─────────────────────────────────────────────────────────────────────

@compute @workgroup_size(8, 8)
fn noise_init_main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= params.sim_w || gid.y >= params.sim_h) { return; }

    let p = vec2<f32>(f32(gid.x), f32(gid.y)) * params.noise_scale;

    var density     = 0.0;
    var temperature = 0.0;

    if (params.noise_mode == 0u) {
        // FBM mode
        density     = fbm(p, params.seed);
        temperature = fbm(p + vec2<f32>(43.7, 17.3), params.seed + 1u);
    } else if (params.noise_mode == 1u) {
        // Worley mode
        density     = worley(p, params.seed);
        temperature = worley(p + vec2<f32>(29.1, 53.7), params.seed + 3u);
    } else {
        // Uniform random
        density     = hash_to_f32(hash2(gid.x, gid.y, params.seed));
        temperature = hash_to_f32(hash2(gid.x + 10000u, gid.y + 10000u, params.seed + 5u));
    }

    textureStore(out_tex, vec2<i32>(i32(gid.x), i32(gid.y)),
                 vec4<f32>(density, temperature, 0.0, 1.0));
}
