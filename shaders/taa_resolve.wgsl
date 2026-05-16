// taa_resolve.wgsl — Temporal Anti-Aliasing resolve pass
// Blends the current rendered frame with a reprojected history buffer using
// YCoCg variance clipping to eliminate ghosting.
//
// Bindings:
//   group(0) binding(0) — TaaParams        (uniform)
//   group(0) binding(1) — current_frame    texture_2d<f32>   (rgba8unorm)
//   group(0) binding(2) — history_frame    texture_2d<f32>   (rgba16float)
//   group(0) binding(3) — motion_vectors   texture_2d<f32>   (rg16float, NDC UV-space)
//   group(0) binding(4) — taa_output       texture_storage_2d<rgba16float, write>

struct TaaParams {
    blend_factor: f32,   // fraction of current frame blended in (0.1 = 10% current)
    sharpening:   f32,   // post-sharpen strength (0.0 = none, 0.2 = mild)
    width:        u32,
    height:       u32,
}

@group(0) @binding(0) var<uniform> taa_params    : TaaParams;
@group(0) @binding(1) var          current_frame  : texture_2d<f32>;
@group(0) @binding(2) var          history_frame  : texture_2d<f32>;
@group(0) @binding(3) var          motion_vectors : texture_2d<f32>;
@group(0) @binding(4) var          taa_output     : texture_storage_2d<rgba16float, write>;

// ── YCoCg helpers ─────────────────────────────────────────────────────────────

fn rgb_to_ycocg(c: vec3f) -> vec3f {
    return vec3f(
         0.25*c.r + 0.5*c.g + 0.25*c.b,
         0.5*c.r              - 0.5*c.b,
        -0.25*c.r + 0.5*c.g  - 0.25*c.b,
    );
}

fn ycocg_to_rgb(c: vec3f) -> vec3f {
    let tmp = c.x - c.z;
    return vec3f(tmp + c.y, c.x + c.z, tmp - c.y);
}

// ── Bilinear fetch helpers ─────────────────────────────────────────────────────

// Bilinear sample from a texture_2d<f32> at normalised UV [0,1], clamped.
fn sample_bilinear_current(uv: vec2f, w: i32, h: i32) -> vec4f {
    let tc  = uv * vec2f(f32(w), f32(h)) - 0.5;
    let i   = vec2i(clamp(i32(tc.x), 0, w - 1), clamp(i32(tc.y), 0, h - 1));
    let i1  = vec2i(clamp(i.x + 1,  0, w - 1), clamp(i.y + 1,  0, h - 1));
    let f   = fract(tc);

    let c00 = textureLoad(current_frame, vec2i(i.x,  i.y),  0);
    let c10 = textureLoad(current_frame, vec2i(i1.x, i.y),  0);
    let c01 = textureLoad(current_frame, vec2i(i.x,  i1.y), 0);
    let c11 = textureLoad(current_frame, vec2i(i1.x, i1.y), 0);

    return mix(mix(c00, c10, f.x), mix(c01, c11, f.x), f.y);
}

// Bilinear sample from history_frame at normalised UV [0,1], clamped.
fn sample_bilinear_history(uv: vec2f, w: i32, h: i32) -> vec4f {
    let tc  = uv * vec2f(f32(w), f32(h)) - 0.5;
    let i   = vec2i(clamp(i32(tc.x), 0, w - 1), clamp(i32(tc.y), 0, h - 1));
    let i1  = vec2i(clamp(i.x + 1,  0, w - 1), clamp(i.y + 1,  0, h - 1));
    let f   = fract(tc);

    let c00 = textureLoad(history_frame, vec2i(i.x,  i.y),  0);
    let c10 = textureLoad(history_frame, vec2i(i1.x, i.y),  0);
    let c01 = textureLoad(history_frame, vec2i(i.x,  i1.y), 0);
    let c11 = textureLoad(history_frame, vec2i(i1.x, i1.y), 0);

    return mix(mix(c00, c10, f.x), mix(c01, c11, f.x), f.y);
}

// Load a single texel from current_frame, clamping coords to valid range.
fn load_current_clamped(coord: vec2i, w: i32, h: i32) -> vec4f {
    let c = vec2i(clamp(coord.x, 0, w - 1), clamp(coord.y, 0, h - 1));
    return textureLoad(current_frame, c, 0);
}

// ── Variance clipping ─────────────────────────────────────────────────────────

// Clip history_sample (YCoCg) to the AABB of the 3×3 neighbourhood min/max.
fn clip_to_aabb(history_ycocg: vec3f, aabb_min: vec3f, aabb_max: vec3f) -> vec3f {
    return clamp(history_ycocg, aabb_min, aabb_max);
}

// ── Entry point ───────────────────────────────────────────────────────────────

@compute @workgroup_size(8, 8)
fn taa_resolve_main(@builtin(global_invocation_id) gid: vec3u) {
    let x = gid.x;
    let y = gid.y;
    if x >= taa_params.width || y >= taa_params.height { return; }

    let w = i32(taa_params.width);
    let h = i32(taa_params.height);
    let px = vec2i(i32(x), i32(y));

    // ── 1. Sample current pixel ────────────────────────────────────────────────
    let current_color = textureLoad(current_frame, px, 0).rgb;

    // ── 2. Build 3×3 YCoCg neighbourhood AABB for variance clipping ───────────
    var ycocg_min = vec3f( 1e9,  1e9,  1e9);
    var ycocg_max = vec3f(-1e9, -1e9, -1e9);

    for (var dy: i32 = -1; dy <= 1; dy++) {
        for (var dx: i32 = -1; dx <= 1; dx++) {
            let s = load_current_clamped(vec2i(px.x + dx, px.y + dy), w, h).rgb;
            let yc = rgb_to_ycocg(s);
            ycocg_min = min(ycocg_min, yc);
            ycocg_max = max(ycocg_max, yc);
        }
    }

    // ── 3. Reproject: read motion vector and compute history UV ───────────────
    // Motion vector is stored as (mv_x, mv_y) in UV-space NDC.
    let mv  = textureLoad(motion_vectors, px, 0).rg;
    let uv  = vec2f((f32(x) + 0.5) / f32(w), (f32(y) + 0.5) / f32(h));
    let history_uv = uv - mv;

    // ── 4. Sample history with manual bilinear filtering ──────────────────────
    let history_color = sample_bilinear_history(history_uv, w, h).rgb;

    // ── 5. Clip history to neighbourhood AABB in YCoCg space (anti-ghost) ─────
    let history_ycocg  = rgb_to_ycocg(history_color);
    let clipped_ycocg  = clip_to_aabb(history_ycocg, ycocg_min, ycocg_max);
    let history_clipped = ycocg_to_rgb(clipped_ycocg);

    // ── 6. Temporal blend: small blend_factor = slower convergence, less noise ─
    let blend   = clamp(taa_params.blend_factor, 0.0, 1.0);
    var blended = mix(history_clipped, current_color, blend);

    // ── 7. Optional sharpening (simple 3×3 unsharp mask) ─────────────────────
    if taa_params.sharpening > 0.0 {
        // Laplacian: centre*5 - cardinal neighbours*1.  Weight by sharpening.
        let n_px  = load_current_clamped(vec2i(px.x,     px.y - 1), w, h).rgb;
        let s_px  = load_current_clamped(vec2i(px.x,     px.y + 1), w, h).rgb;
        let e_px  = load_current_clamped(vec2i(px.x + 1, px.y    ), w, h).rgb;
        let w_px  = load_current_clamped(vec2i(px.x - 1, px.y    ), w, h).rgb;
        let laplacian = blended - 0.25 * (n_px + s_px + e_px + w_px);
        blended = blended + taa_params.sharpening * laplacian;
    }

    // Clamp to avoid HDR blow-out from the sharpen pass.
    blended = max(blended, vec3f(0.0));

    textureStore(taa_output, px, vec4f(blended, 1.0));
}
