// tonemap.wgsl — Tone-mapping and colour-grading post-process pass
// Reads scene-linear HDR input, applies:
//   1. Exposure (exp2(exposure_ev) pre-multiply)
//   2. ACES filmic -or- Reinhard tone mapping (mode-selectable)
//   3. Per-channel lift / gain / gamma (shadow / highlight / midtone control)
//   4. Saturation relative to BT.709 luminance
//   5. Contrast (S-curve centred at 0.5)
// Binding convention: binding 0 = input_tex, binding 1 = output_tex, binding 2 = params uniform.

// Params struct (56 bytes, std140-compatible, no implicit padding):
//   exposure_ev  f32   — EV stops; 0.0 = no change; applied as exp2(ev)
//   mode         u32   — 0 = ACES filmic, 1 = Reinhard
//   saturation   f32   — 1.0 = identity; 0.0 = greyscale; 2.0 = vivid
//   contrast     f32   — 1.0 = identity; S-curve around 0.5
//   lift_r       f32   — shadow lift, red channel
//   lift_g       f32   — shadow lift, green channel
//   lift_b       f32   — shadow lift, blue channel
//   gain_r       f32   — highlight gain, red channel
//   gain_g       f32   — highlight gain, green channel
//   gain_b       f32   — highlight gain, blue channel
//   gamma        f32   — midtone gamma; 1.0 = identity
//   _pad         f32   — reserved / alignment
//   width        u32   — texture width  in pixels
//   height       u32   — texture height in pixels
struct Params {
    exposure_ev : f32,
    mode        : u32,
    saturation  : f32,
    contrast    : f32,
    lift_r      : f32,
    lift_g      : f32,
    lift_b      : f32,
    gain_r      : f32,
    gain_g      : f32,
    gain_b      : f32,
    gamma       : f32,
    _pad        : f32,
    width       : u32,
    height      : u32,
}

@group(0) @binding(0) var input_tex  : texture_2d<f32>;
@group(0) @binding(1) var output_tex : texture_storage_2d<rgba8unorm, write>;
@group(0) @binding(2) var<uniform> params : Params;

// ---------------------------------------------------------------------------
// Tone-mapping operators
// ---------------------------------------------------------------------------

// ACES filmic curve (Hill / Narkowicz approximation).
// Input and output are both in [0, ∞) → [0, 1].
fn aces_filmic(x: vec3f) -> vec3f {
    let a = 2.51;
    let b = 0.03;
    let c = 2.43;
    let d = 0.59;
    let e = 0.14;
    return clamp((x * (a * x + b)) / (x * (c * x + d) + e), vec3f(0.0), vec3f(1.0));
}

// Per-channel Reinhard operator.
fn reinhard(x: vec3f) -> vec3f {
    return x / (x + vec3f(1.0));
}

// ---------------------------------------------------------------------------
// Colour-grading helpers
// ---------------------------------------------------------------------------

// BT.709 luminance coefficients.
fn luminance(c: vec3f) -> f32 {
    return dot(c, vec3f(0.2126, 0.7152, 0.0722));
}

// ---------------------------------------------------------------------------
// Main compute entry point
// ---------------------------------------------------------------------------

@compute @workgroup_size(8, 8)
fn tonemap_main(@builtin(global_invocation_id) gid: vec3u) {
    let x = gid.x;
    let y = gid.y;
    if x >= params.width || y >= params.height { return; }

    // Load the linear-HDR source pixel.
    let src = textureLoad(input_tex, vec2i(i32(x), i32(y)), 0);
    var col = src.rgb;

    // ------------------------------------------------------------------
    // 1. Exposure — scale into the desired luminance range.
    // ------------------------------------------------------------------
    col = col * exp2(params.exposure_ev);

    // ------------------------------------------------------------------
    // 2. Tone mapping — bring HDR into [0, 1] display range.
    // ------------------------------------------------------------------
    if params.mode == 0u {
        col = aces_filmic(col);
    } else {
        col = reinhard(col);
    }

    // ------------------------------------------------------------------
    // 3. Lift / Gain / Gamma — per-channel shadow / highlight / midtone.
    //    Formula: col = pow(col * gain + lift, 1.0 / gamma)
    //    Clamp before pow to avoid NaN from negative bases.
    // ------------------------------------------------------------------
    let lift  = vec3f(params.lift_r,  params.lift_g,  params.lift_b);
    let gain  = vec3f(params.gain_r,  params.gain_g,  params.gain_b);
    let gamma = max(params.gamma, 0.0001);               // guard against /0 or negative
    let base  = clamp(col * gain + lift, vec3f(0.0), vec3f(1.0));
    col = pow(base, vec3f(1.0 / gamma));

    // ------------------------------------------------------------------
    // 4. Saturation — blend between luminance (greyscale) and full colour.
    // ------------------------------------------------------------------
    let lum = luminance(col);
    col = mix(vec3f(lum), col, params.saturation);

    // ------------------------------------------------------------------
    // 5. Contrast — linear S-curve centred at 0.5.
    // ------------------------------------------------------------------
    col = clamp((col - 0.5) * params.contrast + 0.5, vec3f(0.0), vec3f(1.0));

    textureStore(output_tex, vec2i(i32(x), i32(y)), vec4f(col, src.a));
}
