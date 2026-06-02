// film_grain.wgsl — Neutral film grain post-process pass
// Adds uniform luminance noise scaled by strength. No colour shift.
// Binding convention: binding 0 = input_tex, binding 1 = output_tex, binding 2 = params uniform.

struct Params {
    strength: f32,
    time:     f32,
    width:    u32,
    height:   u32,
}

@group(0) @binding(0) var input_tex  : texture_2d<f32>;
@group(0) @binding(1) var output_tex : texture_storage_2d<rgba8unorm, write>;
@group(0) @binding(2) var<uniform>  params : Params;

fn hash21(p: vec2f, t: f32) -> f32 {
    var q = vec3f(p, t);
    q = fract(q * vec3f(127.1, 311.7, 74.7));
    q += dot(q, q.yzx + 19.19);
    return fract((q.x + q.y) * q.z);
}

@compute @workgroup_size(8, 8)
fn film_grain_main(@builtin(global_invocation_id) gid: vec3u) {
    let x = gid.x;
    let y = gid.y;
    if x >= params.width || y >= params.height { return; }

    var col = textureLoad(input_tex, vec2i(i32(x), i32(y)), 0);

    // Symmetric noise in [-1, 1], applied equally to all channels (no colour shift)
    let noise = (hash21(vec2f(f32(x), f32(y)), params.time) * 2.0 - 1.0) * params.strength;
    let out = vec4f(
        clamp(col.r + noise, 0.0, 1.0),
        clamp(col.g + noise, 0.0, 1.0),
        clamp(col.b + noise, 0.0, 1.0),
        col.a,
    );

    textureStore(output_tex, vec2i(i32(x), i32(y)), out);
}
