// luminance.wgsl — Perceptual luminance from linear RGB.
//
// Default coefficients are Rec.709 (sRGB primaries), which is what every
// engine pass (bloom, tonemap, SVGF, ReSTIR) currently uses.  A BT.601
// variant is provided for legacy / NTSC content.

// Rec.709 (sRGB) luminance — the engine default.
fn luminance(c: vec3<f32>) -> f32 {
    return dot(c, vec3<f32>(0.2126, 0.7152, 0.0722));
}

// BT.601 luminance — legacy NTSC/YUV content.
fn luminance_bt601(c: vec3<f32>) -> f32 {
    return dot(c, vec3<f32>(0.299, 0.587, 0.114));
}
