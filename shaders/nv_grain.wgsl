// nv_grain.wgsl — Night-vision post-process pass
// Applies gain amplification, pseudo-random grain noise, and circular vignette.
// Binding convention: binding 0 = input_tex, binding 1 = output_tex, binding 2 = params uniform.

struct Params {
    gain:              f32,
    grain_strength:    f32,
    vignette_strength: f32,
    time:              f32,
    width:             u32,
    height:            u32,
    _pad0:             u32,
    _pad1:             u32,
}

@group(0) @binding(0) var input_tex  : texture_2d<f32>;
@group(0) @binding(1) var output_tex : texture_storage_2d<rgba8unorm, write>;
@group(0) @binding(2) var<uniform>  params    : Params;

// Hash-based pseudo-random scalar in [0, 1].
fn hash21(p: vec2f, t: f32) -> f32 {
    var q = vec3f(p, t);
    q = fract(q * vec3f(127.1, 311.7, 74.7));
    q += dot(q, q.yzx + 19.19);
    return fract((q.x + q.y) * q.z);
}

@compute @workgroup_size(8, 8)
fn nv_grain_main(@builtin(global_invocation_id) gid: vec3u) {
    let x = gid.x;
    let y = gid.y;
    if x >= params.width || y >= params.height { return; }

    let w = f32(params.width);
    let h = f32(params.height);
    let fx = f32(x);
    let fy = f32(y);

    // --- Sample input and apply gain (boost green channel for NV tint) ---
    var col = textureLoad(input_tex, vec2i(i32(x), i32(y)), 0);
    let green_gained = clamp(col.g * params.gain, 0.0, 1.0);
    let red_damp     = clamp(col.r * (1.0 - params.gain * 0.15), 0.0, 1.0);
    let blue_damp    = clamp(col.b * (1.0 - params.gain * 0.15), 0.0, 1.0);
    var out = vec4f(red_damp, green_gained, blue_damp, col.a);

    // --- Grain noise (hash-based, time-varying) ---
    let noise = hash21(vec2f(fx, fy), params.time) * 2.0 - 1.0; // [-1, 1]
    out = vec4f(
        clamp(out.r + noise * params.grain_strength * 0.3, 0.0, 1.0),
        clamp(out.g + noise * params.grain_strength,       0.0, 1.0),
        clamp(out.b + noise * params.grain_strength * 0.3, 0.0, 1.0),
        out.a,
    );

    // --- Circular vignette falloff ---
    // UV in [0, 1]; offset from center in [-0.5, 0.5].
    let uv     = vec2f((fx + 0.5) / w, (fy + 0.5) / h);
    let offset = uv - vec2f(0.5, 0.5);
    // Normalise: dist = 1.0 at corners (~0.707 at edge midpoints).
    let dist   = length(offset) / length(vec2f(0.5, 0.5));
    let vignette = clamp(1.0 - pow(dist * params.vignette_strength, 2.0), 0.0, 1.0);
    out = vec4f(out.rgb * vignette, out.a);

    textureStore(output_tex, vec2i(i32(x), i32(y)), out);
}
