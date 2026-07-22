// tonemap.wgsl — Nova3D pillar 2 (DDD4).
//
// Fullscreen fragment. Reads the HDR light-accumulation buffer,
// applies the ACES "narkowicz 2015" tonemap curve, then gamma-corrects
// into the swapchain / target format (rgba8unorm sRGB or rgba16float).
//
// Bindings:
//   @group(0) @binding(0) — hdr_texture   (rgba16float sampled)
//   @group(0) @binding(1) — hdr_sampler
//   @group(0) @binding(2) — TonemapParams (exposure + gamma)

struct TonemapParams {
    // x = exposure stops, y = gamma (typ. 2.2), z = white point,
    // w = 0 (linear-out) / 1 (sRGB gamma-out).
    knobs: vec4<f32>,
};

@group(0) @binding(0) var hdr_texture: texture_2d<f32>;
@group(0) @binding(1) var hdr_sampler: sampler;
@group(0) @binding(2) var<uniform> u_params: TonemapParams;

struct VSOut {
    @builtin(position) clip_pos: vec4<f32>,
    @location(0)       uv:       vec2<f32>,
};

@vertex
fn vs_main(@builtin(vertex_index) vid: u32) -> VSOut {
    var out: VSOut;
    let x = f32((vid << 1u) & 2u);
    let y = f32(vid & 2u);
    out.uv = vec2<f32>(x, y);
    out.clip_pos = vec4<f32>(x * 2.0 - 1.0, 1.0 - y * 2.0, 0.0, 1.0);
    return out;
}

// Narkowicz 2015 ACES fit — 5-coefficient rational.
// Reference: https://knarkowicz.wordpress.com/2016/01/06/aces-filmic-tone-mapping-curve/
fn aces_narkowicz(x: vec3<f32>) -> vec3<f32> {
    let a = 2.51;
    let b = 0.03;
    let c = 2.43;
    let d = 0.59;
    let e = 0.14;
    return clamp((x * (a * x + vec3<f32>(b))) / (x * (c * x + vec3<f32>(d)) + vec3<f32>(e)),
                 vec3<f32>(0.0), vec3<f32>(1.0));
}

@fragment
fn fs_main(in: VSOut) -> @location(0) vec4<f32> {
    let hdr = textureSample(hdr_texture, hdr_sampler, in.uv).rgb;

    let exposure = pow(2.0, u_params.knobs.x);
    let mapped = aces_narkowicz(hdr * exposure);

    // Optional gamma path. If knob.w >= 0.5 we output non-linear sRGB;
    // otherwise let a *_srgb swapchain do the encoding for us.
    var out_rgb = mapped;
    if (u_params.knobs.w >= 0.5) {
        let g = max(u_params.knobs.y, 1e-4);
        out_rgb = pow(mapped, vec3<f32>(1.0 / g));
    }
    return vec4<f32>(out_rgb, 1.0);
}
