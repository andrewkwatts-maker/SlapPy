// cross_layer_composite.wgsl — DDD2 cross-layer buffer sampling shader.
//
// Full-screen composite that samples one or two source layers (previously
// rendered off-screen by a Layer2D or Layer3D) and blends them into the
// current render target. Selects the blend at draw time via
// ``u_composite.mode``:
//   0 = add      (a.rgb + b.rgb)
//   1 = multiply (a * b)
//   2 = alpha    (mix(a, b, b.a))
//   3 = screen   (1 - (1-a)*(1-b))
//
// Bind group 0
//   binding 0: source A texture view
//   binding 1: source A sampler
//   binding 2: source B texture view (optional — falls back to transparent)
//   binding 3: source B sampler
// Bind group 1
//   binding 0: uniform CompositeParams { u32 mode; f32 mix; f32 pad0; f32 pad1; }

struct CompositeParams {
    mode: u32,
    mix:  f32,
    pad0: f32,
    pad1: f32,
};

@group(0) @binding(0) var u_source_layer_a: texture_2d<f32>;
@group(0) @binding(1) var u_source_layer_a_sampler: sampler;
@group(0) @binding(2) var u_source_layer_b: texture_2d<f32>;
@group(0) @binding(3) var u_source_layer_b_sampler: sampler;
@group(1) @binding(0) var<uniform> u_composite: CompositeParams;

struct VSOut {
    @builtin(position) clip_pos: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

// Full-screen triangle trick: three vertices covering NDC [-1,1]^2 with a
// single winding — no vertex buffer required, dispatch with vertex_count=3.
@vertex
fn vs_main(@builtin(vertex_index) vid: u32) -> VSOut {
    var out: VSOut;
    let x = f32((vid << 1u) & 2u);
    let y = f32(vid & 2u);
    out.clip_pos = vec4<f32>(x * 2.0 - 1.0, 1.0 - y * 2.0, 0.0, 1.0);
    out.uv = vec2<f32>(x, y);
    return out;
}

fn blend_add(a: vec4<f32>, b: vec4<f32>) -> vec4<f32> {
    return vec4<f32>(a.rgb + b.rgb, max(a.a, b.a));
}

fn blend_multiply(a: vec4<f32>, b: vec4<f32>) -> vec4<f32> {
    return a * b;
}

fn blend_alpha(a: vec4<f32>, b: vec4<f32>) -> vec4<f32> {
    return mix(a, b, b.a);
}

fn blend_screen(a: vec4<f32>, b: vec4<f32>) -> vec4<f32> {
    let one = vec4<f32>(1.0);
    return one - (one - a) * (one - b);
}

@fragment
fn fs_main(in: VSOut) -> @location(0) vec4<f32> {
    let a = textureSample(u_source_layer_a, u_source_layer_a_sampler, in.uv);
    let b = textureSample(u_source_layer_b, u_source_layer_b_sampler, in.uv);
    var col: vec4<f32>;
    switch (u_composite.mode) {
        case 0u: { col = blend_add(a, b); }
        case 1u: { col = blend_multiply(a, b); }
        case 2u: { col = blend_alpha(a, b); }
        case 3u: { col = blend_screen(a, b); }
        default: { col = a; }
    }
    return mix(a, col, u_composite.mix);
}
