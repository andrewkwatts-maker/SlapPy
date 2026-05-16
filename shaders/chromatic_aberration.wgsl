// chromatic_aberration.wgsl — Chromatic aberration post-process pass
// Samples the R, G, and B channels at radially-offset UVs proportional to
// the distance from a configurable center point × strength.
// Binding convention: binding 0 = input_tex, binding 1 = output_tex, binding 2 = params uniform.

struct Params {
    strength: f32,
    center_x: f32,
    center_y: f32,
    _pad:     f32,
    width:    u32,
    height:   u32,
    _pad0:    u32,
    _pad1:    u32,
}

@group(0) @binding(0) var input_tex  : texture_2d<f32>;
@group(0) @binding(1) var output_tex : texture_storage_2d<rgba8unorm, write>;
@group(0) @binding(2) var<uniform>  params    : Params;

// Bilinear sample from a texture_2d<f32> at normalised UV [0,1],
// clamped to valid texel range.
fn sample_bilinear(tex: texture_2d<f32>, uv: vec2f, w: i32, h: i32) -> vec4f {
    // Convert UV to texel space, align to texel centres.
    let tc  = uv * vec2f(f32(w), f32(h)) - 0.5;
    let i   = vec2i(clamp(i32(tc.x), 0, w - 1), clamp(i32(tc.y), 0, h - 1));
    let i1  = vec2i(clamp(i.x + 1,  0, w - 1), clamp(i.y + 1,  0, h - 1));
    let f   = fract(tc);

    let c00 = textureLoad(tex, vec2i(i.x,  i.y),  0);
    let c10 = textureLoad(tex, vec2i(i1.x, i.y),  0);
    let c01 = textureLoad(tex, vec2i(i.x,  i1.y), 0);
    let c11 = textureLoad(tex, vec2i(i1.x, i1.y), 0);

    return mix(mix(c00, c10, f.x), mix(c01, c11, f.x), f.y);
}

@compute @workgroup_size(8, 8)
fn chromatic_aberration_main(@builtin(global_invocation_id) gid: vec3u) {
    let x = gid.x;
    let y = gid.y;
    if x >= params.width || y >= params.height { return; }

    let w = i32(params.width);
    let h = i32(params.height);

    // UV with half-pixel offset so we're sampling texel centres.
    let uv      = vec2f((f32(x) + 0.5) / f32(w), (f32(y) + 0.5) / f32(h));
    let center  = vec2f(params.center_x, params.center_y);
    let delta   = uv - center;
    let dist    = length(delta);

    // Radial direction from center; zero-safe.
    var dir = vec2f(0.0, 0.0);
    if dist > 0.00001 {
        dir = delta / dist;
    }

    // Each channel is offset radially outward by a scalar multiple of strength.
    // R is pushed furthest, G stays near center, B is pushed inward relative to G.
    let offset = dir * dist * params.strength;

    let uv_r = uv + offset;
    let uv_g = uv;
    let uv_b = uv - offset;

    let r = sample_bilinear(input_tex, uv_r, w, h).r;
    let g = sample_bilinear(input_tex, uv_g, w, h).g;
    let b = sample_bilinear(input_tex, uv_b, w, h).b;
    let a = sample_bilinear(input_tex, uv_g, w, h).a;

    textureStore(output_tex, vec2i(i32(x), i32(y)), vec4f(r, g, b, a));
}
