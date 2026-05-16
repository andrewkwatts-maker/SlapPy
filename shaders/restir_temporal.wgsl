// ReSTIR Pass 2: Temporal reuse — merge current frame reservoirs with previous frame
// Reprojects via same-pixel (no motion vectors yet), caps M to prevent bias buildup.

struct Reservoir {
    light_index: u32, weight_sum: f32, W: f32, M: f32,
    sample_pos: vec2<f32>, sample_n: vec2<f32>,
};
struct RestirUniforms {
    width: u32, height: u32, n_lights: u32, max_candidates: u32,
    frame_count: u32, _pad0: u32, _pad1: u32, _pad2: u32,
};

@group(0) @binding(0) var<storage, read_write> curr_res: array<Reservoir>;
@group(0) @binding(1) var<storage, read>       prev_res: array<Reservoir>;
@group(0) @binding(2) var gbuf_pos:    texture_2d<f32>;
@group(0) @binding(3) var gbuf_normal: texture_2d<f32>;
@group(0) @binding(4) var<uniform>             u:        RestirUniforms;

const MAX_M: f32 = 20.0;  // cap sample count to prevent temporal bias buildup

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

    var cur = curr_res[idx];
    let prev = prev_res[idx];

    let cur_depth  = textureLoad(gbuf_pos, coord, 0).z;
    let cur_normal = textureLoad(gbuf_normal, coord, 0).xyz;

    // Accept previous reservoir if surface is consistent
    let depth_ok  = abs(cur_depth - textureLoad(gbuf_pos, coord, 0).z) < 0.05;
    let normal_ok = dot(cur_normal, normalize(cur_normal)) > 0.95;
    let valid     = depth_ok && normal_ok && prev.M > 0.0;

    if (valid) {
        var rng = pcg_hash(idx + u.frame_count * 999983u);
        // Merge prev reservoir into curr using reservoir combination
        let w_prev = prev.weight_sum;
        cur.weight_sum += w_prev;
        cur.M = min(cur.M + prev.M, MAX_M);
        if (rand_f32(&rng) < w_prev / cur.weight_sum) {
            cur.light_index = prev.light_index;
            cur.sample_pos  = prev.sample_pos;
            cur.sample_n    = prev.sample_n;
        }
    }

    curr_res[idx] = cur;
}
