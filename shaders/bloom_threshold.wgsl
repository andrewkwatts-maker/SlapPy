// bloom_threshold.wgsl — Lottes 2017 smooth-threshold bloom extraction
//
// Reads the scene texture and writes a glow buffer containing only the
// above-threshold contribution.  Unlike the legacy hard cutoff, the
// Lottes "smooth knee" curve ramps the contribution in gradually around
// the threshold, eliminating the popping artifact you see when a single
// bright pixel crosses the cutoff boundary frame-to-frame.
//
// Reference luma is per-pixel max(R, G, B) — we want saturated colour
// channels (a deep-red flash, an emissive blue marker) to bloom even
// when their BT.709 perceptual luma is low.
//
// Formula:
//     luma   = max(R, G, B)
//     soft   = clamp(luma - threshold + knee, 0, 2*knee)^2 / (4*knee + eps)
//     contrib = max(luma - threshold, soft)
//     weight  = contrib / max(luma, eps)
//     out     = colour * weight * intensity
//
// When ``knee == 0`` the soft branch collapses to ``max(luma - threshold, 0)``
// which reproduces the legacy hard-cutoff behaviour bit-for-bit.
//
// Bindings:
//   group(0) binding(0) — scene_in   texture_2d<f32>
//   group(0) binding(1) — glow_out   texture_storage_2d<rgba8unorm, write>
//   group(0) binding(2) — BloomParams (uniform)

struct BloomParams {
    threshold: f32,
    knee:      f32,
    intensity: f32,
    _pad:      f32,
};

@group(0) @binding(0) var          scene_in : texture_2d<f32>;
@group(0) @binding(1) var          glow_out : texture_storage_2d<rgba8unorm, write>;
@group(0) @binding(2) var<uniform> params   : BloomParams;

const EPS: f32 = 1.0e-6;

// Lottes 2017 smooth-threshold curve.
//
// luma : peak-brightness reference (max channel).
// t    : threshold.
// k    : knee width.  k == 0 is the legacy hard cutoff.
//
// Returns the bloom contribution magnitude in luma units.
fn lottes_threshold(luma: f32, t: f32, k: f32) -> f32 {
    let hard = max(luma - t, 0.0);
    if (k <= 0.0) {
        return hard;
    }
    let soft_in = clamp(luma - t + k, 0.0, 2.0 * k);
    let soft = (soft_in * soft_in) / (4.0 * k + EPS);
    return max(hard, soft);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let dims = textureDimensions(scene_in);
    if (gid.x >= dims.x || gid.y >= dims.y) {
        return;
    }
    let px = vec2<i32>(i32(gid.x), i32(gid.y));
    let colour = textureLoad(scene_in, px, 0).rgb;

    let luma = max(colour.r, max(colour.g, colour.b));
    let contrib = lottes_threshold(luma, params.threshold, params.knee);
    let weight = contrib / max(luma, EPS);

    let glow = colour * weight * params.intensity;
    textureStore(glow_out, px, vec4<f32>(glow, 1.0));
}
