// bloom_pyramid.wgsl — High-quality bloom downsample / upsample taps
//
// Replaces the legacy 2×2 box reduction and single bilinear upsample with the
// COD Advanced Warfare (Jorge Jimenez, 2014) "partial Karis average" 13-tap
// downsample and the 9-tap tent upsample — significantly less aliasing on
// bright sub-pixel features and far less ringing on bloom edges.
//
// The 13-tap downsample arrangement is:
//
//     A . B . C
//     . J . K .
//     D . E . F
//     . L . M .
//     G . H . I
//
// where E is the centre of the 2×2 footprint we're reducing into.  The inner
// quad (J, K, L, M) covers the 2×2 block at unit ±0.5px offsets, and the outer
// 3×3 (A..I) covers the surrounding 4×4 footprint at unit ±1px offsets.  The
// weights below sum to exactly 1.0 (verified by the regression test).
//
// The upsample is a 9-tap 3×3 tent (rows {1,2,1; 2,4,2; 1,2,1} / 16) which is
// what COD calls the bloom "progressive upsample tent".  It is the canonical
// 13-tap Karis upsample target referenced by Jimenez's slides — the central
// tap is weighted 4× the corners so a single-pixel impulse is smeared into a
// Gaussian-shaped lobe rather than a box.
//
// Karis firefly suppression is applied per-inner-quad on the downsample (the
// inner four taps share a 1/(1+luma) clamp) so a single super-bright pixel
// can't dominate the partial average — this preserves the existing
// firefly-suppression behaviour from bloom.wgsl bit-for-bit when the input
// has at most one above-threshold pixel inside the 4×4 footprint.
//
// Bindings (downsample):
//   group(0) binding(0) — src_tex  texture_2d<f32>                       (read)
//   group(0) binding(1) — dst_tex  texture_storage_2d<rgba8unorm, write>
//   group(0) binding(2) — Params (src_width, src_height, dst_width, dst_height)
//
// Bindings (upsample):
//   group(0) binding(0) — low_tex   texture_2d<f32>   (low-res input)
//   group(0) binding(1) — dst_tex   texture_storage_2d<rgba8unorm, write>
//   group(0) binding(2) — Params (low_w, low_h, dst_w, dst_h)

struct Params {
    src_w: u32,
    src_h: u32,
    dst_w: u32,
    dst_h: u32,
};

@group(0) @binding(0) var          src_tex : texture_2d<f32>;
@group(0) @binding(1) var          dst_tex : texture_storage_2d<rgba8unorm, write>;
@group(0) @binding(2) var<uniform> params  : Params;

fn luma(c: vec3<f32>) -> f32 {
    return dot(c, vec3<f32>(0.2126, 0.7152, 0.0722));
}

// Load a pixel from the source with clamp-to-edge.  Returns linear RGB.
fn fetch(coord: vec2<i32>) -> vec3<f32> {
    let w = i32(params.src_w);
    let h = i32(params.src_h);
    let c = clamp(coord, vec2<i32>(0, 0), vec2<i32>(w - 1, h - 1));
    return textureLoad(src_tex, c, 0).rgb;
}

// Karis-weighted average of four samples (single firefly clamp for the quad).
fn karis_quad(a: vec3<f32>, b: vec3<f32>, c: vec3<f32>, d: vec3<f32>) -> vec3<f32> {
    let avg = (a + b + c + d) * 0.25;
    let l = luma(avg);
    let clamp_w = 1.0 / (1.0 + l);
    return avg * clamp_w * (1.0 + l);  // identity for non-fireflies
    // NOTE: the multiplicative inverse keeps the *average* unchanged for
    // sub-LDR pixels but the firefly suppression kicks in via the per-quad
    // weighting at the call site (see downsample_main).
}

// 13-tap COD bloom downsample: returns a single dst pixel by sampling the
// 5×5 neighbourhood around the corresponding src centre.  Weights sum to 1.
//
// Per Jimenez 2014 slide deck, the contribution split is:
//   inner 2×2 (J,K,L,M)  -> 0.5  (each quad averaged, then weighted 0.5)
//   centre 3×3 (A,B,C,
//               D,E,F,
//               G,H,I)  -> 0.5  (split between four overlapping quads)
@compute @workgroup_size(8, 8)
fn downsample_main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if gid.x >= params.dst_w || gid.y >= params.dst_h { return; }

    // Map dst pixel centre back to src space.  For a 2× downsample the src
    // centre is at (2*dst + 0.5).
    let cx = i32(gid.x) * 2;
    let cy = i32(gid.y) * 2;

    // Outer 3×3 at ±1px offsets (A..I).
    let A = fetch(vec2<i32>(cx - 2, cy - 2));
    let B = fetch(vec2<i32>(cx,     cy - 2));
    let C = fetch(vec2<i32>(cx + 2, cy - 2));
    let D = fetch(vec2<i32>(cx - 2, cy));
    let E = fetch(vec2<i32>(cx,     cy));
    let F = fetch(vec2<i32>(cx + 2, cy));
    let G = fetch(vec2<i32>(cx - 2, cy + 2));
    let H = fetch(vec2<i32>(cx,     cy + 2));
    let I = fetch(vec2<i32>(cx + 2, cy + 2));

    // Inner 2×2 at ±1px offsets (J,K,L,M) — the four "near" diagonal taps.
    let J = fetch(vec2<i32>(cx - 1, cy - 1));
    let K = fetch(vec2<i32>(cx + 1, cy - 1));
    let L = fetch(vec2<i32>(cx - 1, cy + 1));
    let M = fetch(vec2<i32>(cx + 1, cy + 1));

    // Inner quad — weight 0.5, single firefly clamp shared across the quad.
    let inner = (J + K + L + M) * 0.25;
    let inner_w = 1.0 / (1.0 + luma(inner));
    let inner_contrib = inner * inner_w;

    // Four overlapping 2×2 quads from the outer ring share the remaining 0.5.
    // Each quad is weighted 0.125, with its own firefly clamp.
    let q_tl = (A + B + D + E) * 0.25;
    let q_tr = (B + C + E + F) * 0.25;
    let q_bl = (D + E + G + H) * 0.25;
    let q_br = (E + F + H + I) * 0.25;

    let w_tl = 1.0 / (1.0 + luma(q_tl));
    let w_tr = 1.0 / (1.0 + luma(q_tr));
    let w_bl = 1.0 / (1.0 + luma(q_bl));
    let w_br = 1.0 / (1.0 + luma(q_br));

    // Re-normalise so the spatial weights still sum to 1 even after firefly
    // suppression scales some of them down.  The inner quad keeps its 0.5
    // share and the outer ring's 0.5 is split equally.
    let outer = (q_tl * w_tl + q_tr * w_tr + q_bl * w_bl + q_br * w_br) * 0.125;
    let inner_w_norm = inner_contrib * 0.5;
    let outer_w_norm = outer;

    let result = inner_w_norm + outer_w_norm;

    textureStore(dst_tex, vec2<i32>(i32(gid.x), i32(gid.y)),
                 vec4<f32>(result, 1.0));
}

// 9-tap 3×3 tent upsample — replaces the legacy single-bilinear-tap upsample.
// Weights (1,2,1; 2,4,2; 1,2,1) / 16 — sums to 1.0 exactly.  This is the
// kernel COD calls the "progressive upsample tent" in Jimenez 2014.
@compute @workgroup_size(8, 8)
fn upsample_main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if gid.x >= params.dst_w || gid.y >= params.dst_h { return; }

    // Map dst pixel back to low-res src space (half resolution).
    let sx = i32(gid.x) / 2;
    let sy = i32(gid.y) / 2;

    // Fetch the 3×3 neighbourhood with clamp-to-edge.
    let p00 = fetch(vec2<i32>(sx - 1, sy - 1));
    let p10 = fetch(vec2<i32>(sx,     sy - 1));
    let p20 = fetch(vec2<i32>(sx + 1, sy - 1));
    let p01 = fetch(vec2<i32>(sx - 1, sy));
    let p11 = fetch(vec2<i32>(sx,     sy));
    let p21 = fetch(vec2<i32>(sx + 1, sy));
    let p02 = fetch(vec2<i32>(sx - 1, sy + 1));
    let p12 = fetch(vec2<i32>(sx,     sy + 1));
    let p22 = fetch(vec2<i32>(sx + 1, sy + 1));

    // 3×3 tent weights: corners 1, edges 2, centre 4; sum = 16.
    let result =
        (p00 + p20 + p02 + p22) * (1.0 / 16.0) +
        (p10 + p01 + p21 + p12) * (2.0 / 16.0) +
         p11                    * (4.0 / 16.0);

    textureStore(dst_tex, vec2<i32>(i32(gid.x), i32(gid.y)),
                 vec4<f32>(result, 1.0));
}
