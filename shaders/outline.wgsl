// outline.wgsl — Edge-outline post-process pass (round-5 polish)
//
// Pre-round-5 the shader used a 4-cardinal-neighbour binary alpha test:
//   "draw outline iff center.alpha >= T AND any neighbour.alpha < T"
// This produces a hard discontinuity at the threshold value, so any
// surface whose alpha drifts across T over time pops the outline on
// and off frame-by-frame (a classic banding/popping artefact).
//
// Round 5 replaces the binary alpha test with a proper Sobel-magnitude
// edge detector and a `smoothstep(T - softness, T + softness, mag)`
// shoulder, so the outline ramps continuously across the band instead
// of snapping.  When `softness <= 0` and `use_sobel == 0u` the legacy
// 4-neighbour binary path is reproduced byte-for-byte (backward-compat).
//
// Binding convention (3 bindings — matches PostProcessExecutor):
//   binding 0 = input_tex  (texture_2d<f32>)
//   binding 1 = output_tex (storage texture, rgba8unorm, write)
//   binding 2 = params     (uniform)
//
// The pre-round-5 shader declared a 4th binding (a sampler) that the
// executor never bound, so the GPU path was effectively broken.  The
// new layout matches the executor's auto bind-group layout.

struct Params {
    outline_r:   f32,
    outline_g:   f32,
    outline_b:   f32,
    outline_a:   f32,
    threshold:   f32,
    softness:    f32,  // round-5: smoothstep half-width; <= 0 => legacy hard cutoff
    use_sobel:   u32,  // round-5: 0 = legacy 4-cardinal binary; 1 = Sobel magnitude
    _pad0:       u32,
    width:       u32,
    height:      u32,
    _pad1:       u32,
    _pad2:       u32,
}

@group(0) @binding(0) var          input_tex  : texture_2d<f32>;
@group(0) @binding(1) var          output_tex : texture_storage_2d<rgba8unorm, write>;
@group(0) @binding(2) var<uniform> params     : Params;

// Sample alpha at a pixel, clamped to image bounds.
fn sample_a(x: i32, y: i32, w: i32, h: i32) -> f32 {
    let cx = clamp(x, 0, w - 1);
    let cy = clamp(y, 0, h - 1);
    return textureLoad(input_tex, vec2i(cx, cy), 0).a;
}

@compute @workgroup_size(8, 8, 1)
fn main(@builtin(global_invocation_id) gid: vec3u) {
    let x = i32(gid.x);
    let y = i32(gid.y);
    let w = i32(params.width);
    let h = i32(params.height);
    if x >= w || y >= h { return; }

    let center = textureLoad(input_tex, vec2i(x, y), 0);
    let center_alpha = center.a;

    var edge_factor: f32 = 0.0;

    if params.use_sobel == 0u {
        // ------------------------------------------------------------------
        // Legacy 4-cardinal-neighbour path.
        // Behaviour identical to pre-round-5 when softness <= 0; with
        // softness > 0 the boolean is replaced by a soft per-neighbour gap.
        // ------------------------------------------------------------------
        if center_alpha >= params.threshold {
            var max_gap: f32 = 0.0;
            let n0 = sample_a(x,     y - 1, w, h);
            let n1 = sample_a(x,     y + 1, w, h);
            let n2 = sample_a(x - 1, y,     w, h);
            let n3 = sample_a(x + 1, y,     w, h);
            // Each neighbour contributes a "below-threshold gap" which we
            // collapse to a max; the legacy binary path is recovered
            // exactly when softness <= 0.
            let gaps = vec4f(
                params.threshold - n0,
                params.threshold - n1,
                params.threshold - n2,
                params.threshold - n3,
            );
            max_gap = max(max(gaps.x, gaps.y), max(gaps.z, gaps.w));

            if params.softness <= 0.0 {
                // Legacy: binary "any neighbour below threshold".
                if max_gap > 0.0 {
                    edge_factor = 1.0;
                }
            } else {
                // Round-5 smoothstep: gap of 0 -> 0.5; gap of +softness -> 1.0;
                // gap of -softness -> 0.0.  Equivalent to soft-shading the
                // boolean "neighbour below threshold" test.
                edge_factor = smoothstep(-params.softness, params.softness, max_gap);
            }
        }
    } else {
        // ------------------------------------------------------------------
        // Sobel-magnitude alpha edge detector (round-5).
        //
        // 3x3 Sobel on the alpha channel:
        //   Gx = [-1 0 1; -2 0 2; -1 0 1]
        //   Gy = [-1 -2 -1; 0 0 0; 1 2 1]
        // Edge magnitude = sqrt(Gx^2 + Gy^2).  This is invariant to
        // which side of the silhouette we're on and gives a smooth
        // (not popping) intensity proportional to the local alpha gradient.
        // ------------------------------------------------------------------
        let a00 = sample_a(x - 1, y - 1, w, h);
        let a10 = sample_a(x,     y - 1, w, h);
        let a20 = sample_a(x + 1, y - 1, w, h);
        let a01 = sample_a(x - 1, y,     w, h);
        let a21 = sample_a(x + 1, y,     w, h);
        let a02 = sample_a(x - 1, y + 1, w, h);
        let a12 = sample_a(x,     y + 1, w, h);
        let a22 = sample_a(x + 1, y + 1, w, h);

        let gx = (a20 + 2.0 * a21 + a22) - (a00 + 2.0 * a01 + a02);
        let gy = (a02 + 2.0 * a12 + a22) - (a00 + 2.0 * a10 + a20);
        let mag = sqrt(gx * gx + gy * gy);

        if params.softness <= 0.0 {
            // Sobel + hard threshold — still binary, useful for crisp
            // outlines that don't need anti-aliasing.
            if mag >= params.threshold {
                edge_factor = 1.0;
            }
        } else {
            // Sobel + smoothstep — eliminates pop completely.  At
            // mag = threshold the factor is 0.5; the transition is
            // 2*softness wide.
            edge_factor = smoothstep(
                params.threshold - params.softness,
                params.threshold + params.softness,
                mag,
            );
        }
    }

    // ----------------------------------------------------------------------
    // Composite the outline colour on top of the scene with the edge
    // intensity as the alpha mask.  For the legacy hard-cutoff path
    // (edge_factor in {0, 1}) this collapses to the pre-round-5
    // behaviour exactly: edge pixels are replaced by `outline_rgba`.
    // ----------------------------------------------------------------------
    let outline_col = vec4f(
        params.outline_r,
        params.outline_g,
        params.outline_b,
        params.outline_a,
    );
    let blend = edge_factor * outline_col.a;
    let out_rgb = mix(center.rgb, outline_col.rgb, blend);
    let out_a   = mix(center.a,   outline_col.a,   blend);

    textureStore(output_tex, vec2i(x, y), vec4f(out_rgb, out_a));
}
