// Final lighting combine pass: scene_tex × (ambient + accum) → rgba8unorm storage texture.
// scene_tex can be any wgpu-compatible format (rgba8unorm, bgra8unorm) — WGSL semantic
// channels (r,g,b,a) are always correct regardless of memory layout.
struct Params {
    ambient_r: f32, ambient_g: f32, ambient_b: f32, ambient_intensity: f32,
    width: u32, height: u32, _pad0: u32, _pad1: u32,
};
@group(0) @binding(0) var<uniform>       params    : Params;
@group(0) @binding(1) var                scene_tex : texture_2d<f32>;
@group(0) @binding(2) var<storage, read> accum     : array<vec4<f32>>;
@group(0) @binding(3) var                out_tex   : texture_storage_2d<rgba8unorm, write>;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= params.width || gid.y >= params.height) { return; }
    let scene = textureLoad(scene_tex, vec2<i32>(gid.xy), 0);
    let idx   = gid.y * params.width + gid.x;
    let light = accum[idx].rgb;
    let amb   = vec3<f32>(params.ambient_r, params.ambient_g, params.ambient_b) * params.ambient_intensity;
    let total = clamp(amb + light, vec3<f32>(0.0), vec3<f32>(1.0));
    textureStore(out_tex, vec2<i32>(gid.xy), vec4<f32>(scene.rgb * total, scene.a));
}
