// svgf_temporal.wgsl — SVGF Pass 1: Temporal accumulation
// EMA blend noisy color with previous frame; track moments and history length.
// Rejects history on depth/normal discontinuity.
//
// Bindings:
//   group(0) binding(0) — noisy_color   texture_2d<f32>              (current noisy input, rgba16float)
//   group(0) binding(1) — gbuf_pos      texture_2d<f32>              (world-space position, rgba32float)
//   group(0) binding(2) — gbuf_normal   texture_2d<f32>              (world-space normals,  rgba8unorm)
//   group(0) binding(3) — gbuf_depth    texture_2d<f32>              (linear depth,         r32float)
//   group(0) binding(4) — accum_color   texture_storage_2d<rgba16float, read_write>
//   group(0) binding(5) — accum_moments texture_storage_2d<rg32float,   read_write>
//   group(0) binding(6) — history_len   texture_storage_2d<r16float,    read_write>
//   group(0) binding(7) — u             SvgfUniforms (uniform)

struct SvgfUniforms {
    phi_color:      f32,
    phi_normal:     f32,
    phi_depth:      f32,
    sigma_lum:      f32,
    temporal_alpha: f32,  // 0.1 = keep 90% history
    iteration:      f32,
    step_width:     f32,
    _pad:           f32,
};

@group(0) @binding(0) var noisy_color:   texture_2d<f32>;
@group(0) @binding(1) var gbuf_pos:      texture_2d<f32>;
@group(0) @binding(2) var gbuf_normal:   texture_2d<f32>;
@group(0) @binding(3) var gbuf_depth:    texture_2d<f32>;
@group(0) @binding(4) var accum_color:   texture_storage_2d<rgba16float, read_write>;
@group(0) @binding(5) var accum_moments: texture_storage_2d<rg32float, read_write>;
@group(0) @binding(6) var history_len:   texture_storage_2d<r16float, read_write>;
@group(0) @binding(7) var<uniform> u:    SvgfUniforms;

// ── Helpers ───────────────────────────────────────────────────────────────────

fn luminance(c: vec3<f32>) -> f32 {
    return dot(c, vec3<f32>(0.2126, 0.7152, 0.0722));
}

// ── Kernel ────────────────────────────────────────────────────────────────────

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let dims = textureDimensions(noisy_color);
    if (gid.x >= dims.x || gid.y >= dims.y) { return; }
    let coord = vec2<i32>(gid.xy);

    let new_color  = textureLoad(noisy_color, coord, 0).rgb;
    let cur_depth  = textureLoad(gbuf_depth,  coord, 0).r;
    let cur_normal = textureLoad(gbuf_normal, coord, 0).xyz;

    let hist_len     = textureLoad(history_len,   coord).r;
    let prev_color   = textureLoad(accum_color,   coord).rgb;
    let prev_moments = textureLoad(accum_moments, coord).rg;

    // Depth and normal thresholds for disocclusion rejection
    let depth_threshold  = 0.05;
    let normal_threshold = 0.95;

    // Simple reprojection: same pixel (no motion vectors for now)
    let depth_ok  = abs(cur_depth - textureLoad(gbuf_depth, coord, 0).r) < depth_threshold;
    let normal_ok = dot(cur_normal, cur_normal) > 0.01 &&
                    dot(cur_normal, cur_normal) > normal_threshold;
    let valid_history = depth_ok && hist_len > 0.0;

    let alpha   = select(1.0, u.temporal_alpha, valid_history);
    let new_len = select(1.0, min(hist_len + 1.0, 32.0), valid_history);

    // Exponential moving average blend
    let blended = mix(prev_color, new_color, alpha);

    // Update first and second luminance moments
    let lum = luminance(new_color);
    let m1  = mix(prev_moments.x, lum,       alpha);
    let m2  = mix(prev_moments.y, lum * lum, alpha);

    textureStore(accum_color,   coord, vec4<f32>(blended, 1.0));
    textureStore(accum_moments, coord, vec4<f32>(m1, m2, 0.0, 0.0));
    textureStore(history_len,   coord, vec4<f32>(new_len, 0.0, 0.0, 0.0));
}
