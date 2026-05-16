// Black body radiation — temperature → emissive glow via Planck approximation
struct Params {
    threshold_k: f32,
    max_k: f32,
    emission_scale: f32,
    width: u32, height: u32,
    _pad: vec3<f32>,
};
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var physics_tex: texture_2d<f32>; // r=vel_x,g=vel_y,b=mass,a=temperature
@group(0) @binding(2) var<storage, read_write> emission_accum: array<vec4<f32>>;

fn planck_color(temp: f32) -> vec3<f32> {
    let t = clamp(temp, 800.0, 20000.0);
    let r = clamp(1.0 - (t - 1000.0) / 5000.0 * (-1.0), 0.0, 1.0);
    // Simplified approximation: red peak ~1500K, white ~5500K, blue-white ~10000K+
    let norm = (t - 800.0) / (20000.0 - 800.0);
    let rr = clamp(1.0 - 2.0 * abs(norm - 0.15), 0.0, 1.0) + clamp(norm - 0.5, 0.0, 0.5);
    let gg = clamp(norm * 2.0 - 0.1, 0.0, 1.0) * clamp(1.5 - norm * 1.5, 0.0, 1.0);
    let bb = clamp((norm - 0.5) * 3.0, 0.0, 1.0);
    return vec3(rr, gg, bb);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= params.width || gid.y >= params.height) { return; }
    let px_data = textureLoad(physics_tex, vec2<i32>(gid.xy), 0);
    let temp = px_data.a;  // temperature stored in alpha channel of physics texture
    if (temp < params.threshold_k) { return; }
    let t_norm = (temp - params.threshold_k) / (params.max_k - params.threshold_k);
    let emit_intensity = clamp(t_norm, 0.0, 1.0) * params.emission_scale;
    let emit_color = planck_color(temp);
    let idx = gid.y * params.width + gid.x;
    emission_accum[idx] = emission_accum[idx] + vec4(emit_color * emit_intensity, 0.0);
}
