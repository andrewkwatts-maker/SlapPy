// ReSTIR Pass 1: Initial RIS (Reservoir Importance Sampling)
// For each pixel, test max_candidates light candidates, keep 1 via weighted reservoir sampling.
// Uses PCG hash for deterministic per-pixel RNG seeded by position + frame.

struct GpuLight {
    position:  vec4<f32>,  // xyz=world pos, w=type
    direction: vec4<f32>,  // xyz=dir, w=radius
    color:     vec4<f32>,  // xyz=rgb, w=intensity
    params:    vec4<f32>,  // x=range, y=falloff, z=flags, w=reserved
};

struct Reservoir {
    light_index: u32,
    weight_sum:  f32,
    W:           f32,   // normalized contribution weight
    M:           f32,   // sample count
    sample_pos:  vec2<f32>,
    sample_n:    vec2<f32>,
};

struct RestirUniforms {
    width:          u32,
    height:         u32,
    n_lights:       u32,
    max_candidates: u32,
    frame_count:    u32,
    _pad0: u32, _pad1: u32, _pad2: u32,
};

@group(0) @binding(0) var gbuf_pos:    texture_2d<f32>;
@group(0) @binding(1) var gbuf_normal: texture_2d<f32>;
@group(0) @binding(2) var gbuf_albedo: texture_2d<f32>;
@group(0) @binding(3) var<storage, read>       lights:     array<GpuLight>;
@group(0) @binding(4) var<storage, read_write> reservoirs: array<Reservoir>;
@group(0) @binding(5) var<uniform>             u:          RestirUniforms;

// PCG hash for per-pixel RNG
fn pcg_hash(seed: u32) -> u32 {
    var s = seed * 747796405u + 2891336453u;
    s = ((s >> ((s >> 28u) + 4u)) ^ s) * 277803737u;
    return (s >> 22u) ^ s;
}

fn rand_f32(state: ptr<function, u32>) -> f32 {
    *state = pcg_hash(*state);
    return f32(*state) / f32(0xFFFFFFFFu);
}

fn luminance(c: vec3<f32>) -> f32 {
    return dot(c, vec3<f32>(0.2126, 0.7152, 0.0722));
}

fn target_pdf(light: GpuLight, pos: vec3<f32>, normal: vec3<f32>, albedo: vec3<f32>) -> f32 {
    let to_light = light.position.xyz - pos;
    let dist     = length(to_light);
    let l_dir    = to_light / max(dist, 0.001);
    let n_dot_l  = max(0.0, dot(normal, l_dir));
    let range    = max(light.params.x, 0.001);
    let atten    = max(0.0, 1.0 - dist / range);
    let radiance = light.color.rgb * light.color.w * atten * atten;
    return luminance(radiance * albedo * n_dot_l);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= u.width || gid.y >= u.height) { return; }
    let idx = gid.y * u.width + gid.x;
    let coord = vec2<i32>(gid.xy);

    let pos    = textureLoad(gbuf_pos,    coord, 0).xyz;
    let normal = textureLoad(gbuf_normal, coord, 0).xyz;
    let albedo = textureLoad(gbuf_albedo, coord, 0).rgb;

    if (length(normal) < 0.1) {
        reservoirs[idx] = Reservoir(0u, 0.0, 0.0, 0.0, vec2<f32>(0.0), vec2<f32>(0.0));
        return;
    }

    var rng = pcg_hash(gid.x + gid.y * u.width + u.frame_count * 1000000u);
    var reservoir = Reservoir(0u, 0.0, 0.0, 0.0, vec2<f32>(0.0), vec2<f32>(0.0));

    let n_candidates = min(u.max_candidates, u.n_lights);

    for (var i = 0u; i < n_candidates; i++) {
        // Randomly select a light
        let li = u32(rand_f32(&rng) * f32(u.n_lights)) % u.n_lights;
        let p_hat = target_pdf(lights[li], pos, normal, albedo);
        let w = p_hat;  // uniform source PDF = 1/n_lights, so weight = p_hat / (1/n_lights) * n_lights = p_hat * n_lights
        reservoir.weight_sum += w;
        reservoir.M += 1.0;
        // Reservoir update: accept with probability w / weight_sum
        if (rand_f32(&rng) < w / reservoir.weight_sum) {
            reservoir.light_index = li;
            reservoir.sample_pos  = lights[li].position.xy;
            reservoir.sample_n    = lights[li].direction.xy;
        }
    }

    // Compute unbiased contribution weight W
    let final_p_hat = target_pdf(lights[reservoir.light_index], pos, normal, albedo);
    reservoir.W = select(0.0, reservoir.weight_sum / (reservoir.M * max(final_p_hat, 1e-6)), final_p_hat > 0.0);

    reservoirs[idx] = reservoir;
}
