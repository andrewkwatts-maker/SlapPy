// svgf_wavelet.wgsl — SVGF Pass 3-7: À-trous wavelet edge-stopping filter
// Dispatched 5 times with step_width = 1, 2, 4, 8, 16 (set via u.step_width).
// Edge-stopping weights on depth, normal, and luminance guided by variance.
//
// Bindings:
//   group(0) binding(0) — input_color  texture_2d<f32>               (filtered color from previous pass)
//   group(0) binding(1) — variance_tex texture_2d<f32>               (per-pixel variance estimate)
//   group(0) binding(2) — history_len  texture_2d<f32>               (accumulated frame count)
//   group(0) binding(3) — gbuf_pos     texture_2d<f32>               (world-space position)
//   group(0) binding(4) — gbuf_normal  texture_2d<f32>               (world-space normals)
//   group(0) binding(5) — gbuf_depth   texture_2d<f32>               (linear depth)
//   group(0) binding(6) — output_color texture_storage_2d<rgba16float, write>
//   group(0) binding(7) — u            SvgfUniforms (uniform)

struct SvgfUniforms {
    phi_color:      f32,
    phi_normal:     f32,
    phi_depth:      f32,
    sigma_lum:      f32,
    temporal_alpha: f32,
    iteration:      f32,
    step_width:     f32,
    _pad:           f32,
};

@group(0) @binding(0) var input_color:  texture_2d<f32>;
@group(0) @binding(1) var variance_tex: texture_2d<f32>;
@group(0) @binding(2) var history_len:  texture_2d<f32>;
@group(0) @binding(3) var gbuf_pos:     texture_2d<f32>;
@group(0) @binding(4) var gbuf_normal:  texture_2d<f32>;
@group(0) @binding(5) var gbuf_depth:   texture_2d<f32>;
@group(0) @binding(6) var output_color: texture_storage_2d<rgba16float, write>;
@group(0) @binding(7) var<uniform> u:   SvgfUniforms;

// ── Constants ─────────────────────────────────────────────────────────────────

// 3×3 Gaussian kernel weights (row-major, top-left first)
const KERNEL: array<f32, 9> = array<f32, 9>(
    1.0/16.0, 2.0/16.0, 1.0/16.0,
    2.0/16.0, 4.0/16.0, 2.0/16.0,
    1.0/16.0, 2.0/16.0, 1.0/16.0,
);

// ── Helpers ───────────────────────────────────────────────────────────────────

fn luminance(c: vec3<f32>) -> f32 {
    return dot(c, vec3<f32>(0.2126, 0.7152, 0.0722));
}

// ── Kernel ────────────────────────────────────────────────────────────────────

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let dims = textureDimensions(input_color);
    if (gid.x >= dims.x || gid.y >= dims.y) { return; }
    let coord = vec2<i32>(gid.xy);

    let center_color  = textureLoad(input_color, coord, 0).rgb;
    let center_normal = textureLoad(gbuf_normal, coord, 0).xyz;
    let center_depth  = textureLoad(gbuf_depth,  coord, 0).r;
    let center_lum    = luminance(center_color);
    let variance      = textureLoad(variance_tex, coord, 0).r;

    // Variance-guided luminance stopping threshold
    let phi_l = u.sigma_lum * sqrt(max(0.0, variance));
    let step  = i32(u.step_width);

    var accum_color  = vec3<f32>(0.0);
    var accum_weight = 0.0;

    for (var ky = 0; ky < 3; ky++) {
        for (var kx = 0; kx < 3; kx++) {
            let offset = vec2<i32>((kx - 1) * step, (ky - 1) * step);
            let sc     = coord + offset;
            if (sc.x < 0 || sc.y < 0 || u32(sc.x) >= dims.x || u32(sc.y) >= dims.y) {
                continue;
            }

            let s_color  = textureLoad(input_color, sc, 0).rgb;
            let s_normal = textureLoad(gbuf_normal, sc, 0).xyz;
            let s_depth  = textureLoad(gbuf_depth,  sc, 0).r;
            let s_lum    = luminance(s_color);

            let kernel_w = KERNEL[ky * 3 + kx];

            // Luminance edge-stopping (variance-guided)
            let w_lum = exp(-abs(center_lum - s_lum) / (phi_l + 1e-6));

            // Normal edge-stopping: cosine similarity raised to phi_normal power
            let n_dot    = max(0.0, dot(center_normal, s_normal));
            let w_normal = pow(n_dot, u.phi_normal);

            // Depth edge-stopping: relative gradient suppression
            let grad_d  = abs(center_depth - s_depth);
            let w_depth = exp(-grad_d / (u.phi_depth * grad_d + 1e-6));

            let w = kernel_w * w_lum * w_normal * w_depth;
            accum_color  += s_color * w;
            accum_weight += w;
        }
    }

    let result = select(center_color, accum_color / accum_weight, accum_weight > 1e-6);
    textureStore(output_color, coord, vec4<f32>(result, 1.0));
}
