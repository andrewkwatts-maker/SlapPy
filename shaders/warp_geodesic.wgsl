// Geodesic UV warp — gravitational lensing / black hole effect
struct GravitySource { pos_x: f32, pos_y: f32, mass: f32, radius: f32, falloff: f32, _pad: vec3<f32> };
struct Params {
    num_sources: u32,
    width: u32, height: u32,
    _pad: u32,
    sources: array<GravitySource, 4>,
};
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var scene_tex: texture_2d<f32>;
@group(0) @binding(2) var scene_samp: sampler;
@group(0) @binding(3) var<storage, read_write> out_buf: array<vec4<f32>>;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= params.width || gid.y >= params.height) { return; }
    var warp = vec2<f32>(0.0, 0.0);
    var in_horizon = false;
    for (var i = 0u; i < params.num_sources; i++) {
        let src = params.sources[i];
        let dx = f32(gid.x) - src.pos_x;
        let dy = f32(gid.y) - src.pos_y;
        let dist = sqrt(dx*dx + dy*dy);
        if (dist < src.radius) { in_horizon = true; break; }
        let w = src.mass / (dist*dist + src.falloff);
        warp = warp + normalize(vec2(dx, dy)) * (-w);
    }
    let idx = gid.y * params.width + gid.x;
    if (in_horizon) { out_buf[idx] = vec4(0.0); return; }
    let warped_uv = (vec2<f32>(gid.xy) + warp) / vec2<f32>(f32(params.width), f32(params.height));
    out_buf[idx] = textureSampleLevel(scene_tex, scene_samp, clamp(warped_uv, vec2(0.0), vec2(1.0)), 0.0);
}
