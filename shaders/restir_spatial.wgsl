// ReSTIR Pass 3: Spatial reuse — share reservoirs with neighbors
// 3 iterations × 5 neighbors at 30px radius

struct Reservoir {
    light_index: u32, weight_sum: f32, W: f32, M: f32,
    sample_pos: vec2<f32>, sample_n: vec2<f32>,
};
struct RestirUniforms {
    width: u32, height: u32, n_lights: u32, max_candidates: u32,
    frame_count: u32, _pad0: u32, _pad1: u32, _pad2: u32,
};

@group(0) @binding(0) var<storage, read_write> reservoirs: array<Reservoir>;
@group(0) @binding(1) var gbuf_pos:    texture_2d<f32>;
@group(0) @binding(2) var gbuf_normal: texture_2d<f32>;
@group(0) @binding(3) var<uniform>             u:          RestirUniforms;

fn pcg_hash(seed: u32) -> u32 {
    var s = seed * 747796405u + 2891336453u;
    s = ((s >> ((s >> 28u) + 4u)) ^ s) * 277803737u;
    return (s >> 22u) ^ s;
}
fn rand_f32(state: ptr<function, u32>) -> f32 {
    *state = pcg_hash(*state);
    return f32(*state) / f32(0xFFFFFFFFu);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= u.width || gid.y >= u.height) { return; }
    let idx = gid.y * u.width + gid.x;
    let coord = vec2<i32>(gid.xy);

    let center_normal = textureLoad(gbuf_normal, coord, 0).xyz;
    let center_depth  = textureLoad(gbuf_pos, coord, 0).z;

    var merged = reservoirs[idx];
    var rng = pcg_hash(idx + u.frame_count * 777u + 12345u);

    // 3 spatial iterations, 5 neighbors each
    for (var iter = 0u; iter < 3u; iter++) {
        for (var nb = 0u; nb < 5u; nb++) {
            let angle  = rand_f32(&rng) * 6.28318;
            let radius = rand_f32(&rng) * 30.0;
            let nx = i32(f32(gid.x) + cos(angle) * radius);
            let ny = i32(f32(gid.y) + sin(angle) * radius);
            if (nx < 0 || ny < 0 || u32(nx) >= u.width || u32(ny) >= u.height) {
                continue;
            }
            let nb_idx = u32(ny) * u.width + u32(nx);
            let nb_res = reservoirs[nb_idx];
            let nb_coord = vec2<i32>(nx, ny);
            let nb_normal = textureLoad(gbuf_normal, nb_coord, 0).xyz;
            let nb_depth  = textureLoad(gbuf_pos, nb_coord, 0).z;

            // Surface similarity check
            let normal_ok = dot(center_normal, nb_normal) > 0.8;
            let depth_ok  = abs(center_depth - nb_depth) < 0.1;
            if (!normal_ok || !depth_ok) { continue; }

            // Merge neighbor reservoir
            let w_nb = nb_res.weight_sum;
            merged.weight_sum += w_nb;
            merged.M += nb_res.M;
            if (rand_f32(&rng) < w_nb / merged.weight_sum) {
                merged.light_index = nb_res.light_index;
                merged.sample_pos  = nb_res.sample_pos;
                merged.sample_n    = nb_res.sample_n;
            }
        }
    }

    reservoirs[idx] = merged;
}
