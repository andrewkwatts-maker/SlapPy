// pharos_render :: Postprocess — Depth-of-field bokeh gather.
//
// Nova3D delta port (S1-W1/W2, 2026-07-23) — source in
// nova3d assets/shaders/dof_bokeh.comp @ 40b8a9a.
//
// Two entry points: dilate (3x3 max on the CoC buffer) and gather
// (variable-radius Vogel-disc bokeh sampling of colour). Dispatch
// selects one or the other rather than the GLSL u_pass branch.

struct BokehUniforms {
    texel_size:     vec2<f32>,
    num_rings:      u32,
    max_coc_pixels: f32,
};

@group(0) @binding(0) var<uniform> u: BokehUniforms;
@group(0) @binding(1) var color_in:  texture_storage_2d<rgba16float, read>;
@group(0) @binding(2) var coc_buf:   texture_storage_2d<rgba16float, read>;
@group(0) @binding(3) var color_out: texture_storage_2d<rgba16float, write>;

const PI: f32 = 3.14159265;
const GOLDEN_ANGLE: f32 = 2.399963;

fn vogel_disk(i: u32, n: u32, phi: f32) -> vec2<f32> {
    let r     = sqrt(f32(i) + 0.5) / sqrt(f32(n));
    let theta = f32(i) * GOLDEN_ANGLE + phi;
    return r * vec2<f32>(cos(theta), sin(theta));
}

@compute @workgroup_size(8, 8, 1)
fn cs_dilate(@builtin(global_invocation_id) gid: vec3<u32>) {
    let coord = vec2<i32>(gid.xy);
    var max_coc: f32 = 0.0;
    for (var y: i32 = -1; y <= 1; y = y + 1) {
        for (var x: i32 = -1; x <= 1; x = x + 1) {
            let s = textureLoad(coc_buf, coord + vec2<i32>(x, y)).r;
            max_coc = max(max_coc, s);
        }
    }
    let orig = textureLoad(coc_buf, coord);
    textureStore(color_out, coord, vec4<f32>(max_coc, orig.g, 0.0, 1.0));
}

@compute @workgroup_size(8, 8, 1)
fn cs_bokeh(@builtin(global_invocation_id) gid: vec3<u32>) {
    let coord = vec2<i32>(gid.xy);
    let centre = textureLoad(coc_buf, coord);
    let radius = abs(centre.r);

    if (radius < 0.5) {
        textureStore(color_out, coord, textureLoad(color_in, coord));
        return;
    }

    let ring_samples = i32(u.num_rings * u.num_rings * 4u);
    let num_samples  = clamp(ring_samples, 16, 64);

    var accum: vec4<f32> = vec4<f32>(0.0);
    var weight: f32 = 0.0;

    // Per-pixel golden-ratio phase — deterministic hash.
    let hash = sin(f32(coord.x) * 127.1 + f32(coord.y) * 311.7) * 43758.5453;
    let phi  = fract(hash);

    for (var i: i32 = 0; i < num_samples; i = i + 1) {
        let offset = vogel_disk(u32(i), u32(num_samples), phi) * radius;
        let sc = coord + vec2<i32>(round(offset));
        let s_col = textureLoad(color_in, sc);
        let s_coc = textureLoad(coc_buf, sc);
        let s_rad = abs(s_coc.r);
        let w = step(length(offset), max(radius, s_rad));
        accum  = accum  + s_col * w;
        weight = weight + w;
    }

    var result: vec4<f32>;
    if (weight > 0.0) {
        result = accum / weight;
    } else {
        result = textureLoad(color_in, coord);
    }
    textureStore(color_out, coord, result);
}
