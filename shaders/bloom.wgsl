// bloom.wgsl — Two-pass bloom effect (threshold + additive glow)
//
// Pass A (threshold): extracts pixels above threshold into a glow buffer.
// Pass B (blend):     additively blends the blurred glow back into the scene.
//
// This shader is dispatched as Pass A — it reads the scene texture, extracts
// bright regions, and writes to a glow storage texture.  A separate blur pass
// (blur.wgsl, radius=8) is expected to run on the glow texture before the
// compositor additively blends it over the scene.
//
// Bindings:
//   group(0) binding(0) — BloomParams   (uniform)
//   group(0) binding(1) — scene_in      texture_2d<f32>                (rgba8unorm)
//   group(0) binding(2) — glow_out      texture_storage_2d<rgba8unorm, write>

struct BloomParams {
    threshold:  f32,   // luminance threshold [0,1]; pixels above this glow
    intensity:  f32,   // scale factor applied to the extracted glow
    width:      u32,   // viewport width  — executor fills
    height:     u32,   // viewport height — executor fills
}

@group(0) @binding(0) var<uniform> params    : BloomParams;
@group(0) @binding(1) var          scene_in  : texture_2d<f32>;
@group(0) @binding(2) var          glow_out  : texture_storage_2d<rgba8unorm, write>;

// ── Luminance (BT.709) ────────────────────────────────────────────────────────
fn luminance(c: vec3f) -> f32 {
    return dot(c, vec3f(0.2126, 0.7152, 0.0722));
}

// ── Soft knee threshold ───────────────────────────────────────────────────────
// Avoids hard cutoff by blending a soft-knee curve around the threshold.
fn soft_threshold(lum: f32, t: f32) -> f32 {
    let knee = t * 0.5;
    if lum <= t - knee { return 0.0; }
    if lum >= t + knee { return 1.0; }
    let x = lum - (t - knee);
    return x * x / (4.0 * knee + 0.0001);
}

// ── 3×3 tent filter for pre-blur on extraction (reduces aliasing) ─────────────
fn sample_tent(coord: vec2i, w: i32, h: i32) -> vec4f {
    var acc = vec4f(0.0);
    var wsum = 0.0;
    for (var dy: i32 = -1; dy <= 1; dy++) {
        for (var dx: i32 = -1; dx <= 1; dx++) {
            let c = clamp(coord + vec2i(dx, dy), vec2i(0), vec2i(w - 1, h - 1));
            let w_ = (1.0 - abs(f32(dx)) * 0.5) * (1.0 - abs(f32(dy)) * 0.5);
            acc += textureLoad(scene_in, c, 0) * w_;
            wsum += w_;
        }
    }
    return acc / wsum;
}

// ── Entry point ───────────────────────────────────────────────────────────────
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3u) {
    let x = gid.x;
    let y = gid.y;
    if x >= params.width || y >= params.height { return; }

    let px   = vec2i(i32(x), i32(y));
    let w    = i32(params.width);
    let h    = i32(params.height);

    // Tent-filtered scene sample for smoother bloom edges
    let color = sample_tent(px, w, h).rgb;
    let lum   = luminance(color);

    // Extract above-threshold luminance.
    let weight = soft_threshold(lum, params.threshold) * params.intensity;

    // Karis average firefly suppression. A single very-bright pixel (the
    // archetypal "firefly" from raymarched specular highlights and small
    // emissive sources) divided by (1 + luma) caps its contribution so the
    // subsequent blur doesn't smear a single 100-nit speck across the
    // screen as a strobing halo. This is the same weight Frostbite uses
    // for their bloom downsample chain.
    let firefly_clamp = 1.0 / (1.0 + lum);
    let glow = color * weight * firefly_clamp;

    textureStore(glow_out, px, vec4f(glow, 1.0));
}
