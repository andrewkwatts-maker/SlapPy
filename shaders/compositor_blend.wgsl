// compositor_blend.wgsl — Blends a render-pass channel over the base frame.
// Supports: lerp (0), additive (1), multiply (2), screen (3), replace (4).

struct Params {
    tint_r:     f32,
    tint_g:     f32,
    tint_b:     f32,
    gain:       f32,
    blend_alpha: f32,
    blend_mode:  u32,   // 0=lerp 1=additive 2=multiply 3=screen 4=replace
    width:       u32,
    height:      u32,
}

@group(0) @binding(0) var<uniform>        params   : Params;
@group(0) @binding(1) var                 base_tex : texture_2d<f32>;
@group(0) @binding(2) var                 out_tex  : texture_storage_2d<rgba8unorm, write>;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3u) {
    let x = i32(gid.x);
    let y = i32(gid.y);
    if u32(x) >= params.width || u32(y) >= params.height { return; }

    let coord = vec2i(x, y);
    let base_sample = textureLoad(base_tex, coord, 0);
    let base = base_sample.rgb;
    let alpha_out = base_sample.a;

    let tint = vec3<f32>(params.tint_r, params.tint_g, params.tint_b);
    let pass_color = base * tint * params.gain;
    let ba = params.blend_alpha;

    var out: vec3<f32>;
    switch params.blend_mode {
        // lerp
        case 0u: {
            out = mix(base, pass_color, ba);
        }
        // additive
        case 1u: {
            out = base + pass_color * ba;
        }
        // multiply
        case 2u: {
            out = base * mix(vec3<f32>(1.0, 1.0, 1.0), pass_color, ba);
        }
        // screen
        case 3u: {
            out = 1.0 - (1.0 - base) * (1.0 - pass_color * ba);
        }
        // replace (and default)
        default: {
            out = mix(base, pass_color, ba);
        }
    }

    textureStore(out_tex, coord, vec4<f32>(clamp(out, vec3<f32>(0.0), vec3<f32>(1.0)), alpha_out));
}
