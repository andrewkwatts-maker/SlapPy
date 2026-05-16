// svgf_variance.wgsl — SVGF Pass 2: Variance estimation from accumulated moments
// Var = E[X²] - E[X]² from temporal moments; falls back to a 5×5 spatial
// kernel when history length is too short (< 4 frames) to be reliable.
//
// Bindings:
//   group(0) binding(0) — accum_color   texture_2d<f32>             (temporally accumulated color)
//   group(0) binding(1) — accum_moments texture_2d<f32>             (rg = first/second moment)
//   group(0) binding(2) — history_len   texture_2d<f32>             (accumulated frame count)
//   group(0) binding(3) — variance_out  texture_storage_2d<r16float, write>
//   group(0) binding(4) — u             SvgfUniforms (uniform)

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

@group(0) @binding(0) var accum_color:   texture_2d<f32>;
@group(0) @binding(1) var accum_moments: texture_2d<f32>;
@group(0) @binding(2) var history_len:   texture_2d<f32>;
@group(0) @binding(3) var variance_out:  texture_storage_2d<r16float, write>;
@group(0) @binding(4) var<uniform> u:    SvgfUniforms;

// ── Helpers ───────────────────────────────────────────────────────────────────

fn luminance(c: vec3<f32>) -> f32 {
    return dot(c, vec3<f32>(0.2126, 0.7152, 0.0722));
}

// ── Kernel ────────────────────────────────────────────────────────────────────

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let dims = textureDimensions(accum_color);
    if (gid.x >= dims.x || gid.y >= dims.y) { return; }
    let coord = vec2<i32>(gid.xy);

    let moments = textureLoad(accum_moments, coord, 0).rg;
    let hist    = textureLoad(history_len,   coord, 0).r;

    // Temporal variance: E[X²] - E[X]²
    var variance = max(0.0, moments.y - moments.x * moments.x);

    // Boost variance estimate in low-history regions using a 5×5 spatial kernel
    if (hist < 4.0) {
        var sum_lum  = 0.0;
        var sum_lum2 = 0.0;
        var count    = 0.0;

        for (var dy = -2; dy <= 2; dy++) {
            for (var dx = -2; dx <= 2; dx++) {
                let sc = coord + vec2<i32>(dx, dy);
                if (sc.x < 0 || sc.y < 0 || u32(sc.x) >= dims.x || u32(sc.y) >= dims.y) {
                    continue;
                }
                let c = textureLoad(accum_color, sc, 0).rgb;
                let l = luminance(c);
                sum_lum  += l;
                sum_lum2 += l * l;
                count    += 1.0;
            }
        }

        if (count > 0.0) {
            let m1          = sum_lum  / count;
            let m2          = sum_lum2 / count;
            let spatial_var = max(0.0, m2 - m1 * m1);
            // Blend toward spatial estimate proportionally to how little history we have
            let blend = clamp(1.0 - hist / 4.0, 0.0, 1.0);
            variance  = mix(variance, spatial_var, blend);
        }
    }

    textureStore(variance_out, coord, vec4<f32>(variance, 0.0, 0.0, 0.0));
}
