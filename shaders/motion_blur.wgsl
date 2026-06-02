// motion_blur.wgsl — Velocity-buffer motion blur compute shader
//
// Reads per-pixel screen-space velocity (in pixels) from velocity_tex and
// marches sample_count samples along ±velocity, weighting closer samples
// more heavily.  Pixels with very small velocity pass through unmodified.
//
// Bindings:
//   group(0) binding(0) — MotionBlurParams   (uniform)
//   group(0) binding(1) — scene_color         texture_2d<f32>
//   group(0) binding(2) — velocity_tex        texture_2d<f32>  RG = velocity (pixels)
//   group(0) binding(3) — tex_sampler         sampler
//   group(0) binding(4) — mb_out              texture_storage_2d<rgba16float, write>

struct MotionBlurParams {
    width:        u32,
    height:       u32,
    sample_count: u32,   // total samples along blur vector (default 8)
    strength:     f32,   // scales velocity before sampling (default 1.0)
    _pad:         vec4u,
}

@group(0) @binding(0) var<uniform> mb_params   : MotionBlurParams;
@group(0) @binding(1) var          scene_color : texture_2d<f32>;
@group(0) @binding(2) var          velocity_tex: texture_2d<f32>;
@group(0) @binding(3) var          tex_sampler : sampler;
@group(0) @binding(4) var          mb_out      : texture_storage_2d<rgba16float, write>;

// ── Entry point ───────────────────────────────────────────────────────────────
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3u) {
    let x = gid.x;
    let y = gid.y;
    if x >= mb_params.width || y >= mb_params.height { return; }

    let w  = i32(mb_params.width);
    let h  = i32(mb_params.height);
    let px = vec2i(i32(x), i32(y));

    // Sample velocity at this pixel (RG channels, in screen-space pixels)
    let vel_raw = textureLoad(velocity_tex, px, 0).rg;
    let vel     = vel_raw * mb_params.strength;

    // Skip blur for near-static pixels
    if length(vel) < 0.5 {
        textureStore(mb_out, px, textureLoad(scene_color, px, 0));
        return;
    }

    let n         = max(mb_params.sample_count, 1u);
    let n_f       = f32(n);
    // Half-range: march from -(vel/2) to +(vel/2) so the blur is symmetric
    let step_vec  = vel / n_f;

    var accum      = vec4f(0.0);
    var weight_sum = 0.0;

    for (var i: u32 = 0u; i < n; i++) {
        // t in [-0.5 .. +0.5] → offset spans -(vel/2) to +(vel/2)
        let t      = (f32(i) / (n_f - 1.0) - 0.5);
        let offset = vel * t;
        let dist   = abs(t);   // distance from centre [0..0.5]

        // Weight: closer to centre = more influence (dist=0 → w=1, dist=0.5 → w≈0.67)
        let w_     = 1.0 / (1.0 + dist * 2.0);

        let sp = vec2i(
            clamp(px.x + i32(offset.x), 0, w - 1),
            clamp(px.y + i32(offset.y), 0, h - 1),
        );
        accum      += textureLoad(scene_color, sp, 0) * w_;
        weight_sum += w_;
    }

    let result = accum / max(weight_sum, 1e-6);
    textureStore(mb_out, px, result);
}
