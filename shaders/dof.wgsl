// dof.wgsl — Depth of Field (gather-based bokeh) compute shader
//
// Single-pass gather DoF: for each output pixel, compute its Circle of
// Confusion (CoC) radius from linear depth vs focal plane, then scatter-
// gather bokeh samples from a 16-point Poisson disk weighted by their own
// CoC.  The result is blended against the sharp scene colour proportional
// to the pixel's own CoC.
//
// Bindings:
//   group(0) binding(0) — DofParams         (uniform)
//   group(0) binding(1) — scene_color        texture_2d<f32>
//   group(0) binding(2) — depth_tex          texture_2d<f32>  linear depth [0..1]
//   group(0) binding(3) — tex_sampler        sampler
//   group(0) binding(4) — dof_out            texture_storage_2d<rgba16float, write>

struct DofParams {
    width:          u32,
    height:         u32,
    focal_distance: f32,   // linear depth of the focal plane [0..1]
    focal_range:    f32,   // depth range over which CoC grows to max_coc_radius
    max_coc_radius: f32,   // maximum CoC radius in pixels
    bokeh_samples:  u32,   // number of Poisson samples (capped at 16 internally)
    _pad:           vec2u,
}

@group(0) @binding(0) var<uniform> params      : DofParams;
@group(0) @binding(1) var          scene_color : texture_2d<f32>;
@group(0) @binding(2) var          depth_tex   : texture_2d<f32>;
@group(0) @binding(3) var          tex_sampler : sampler;
@group(0) @binding(4) var          dof_out     : texture_storage_2d<rgba16float, write>;

// ── 16-point Poisson disk (unit-disk normalised) ──────────────────────────────
// Generated from a well-spaced low-discrepancy 16-tap layout.
const POISSON_COUNT: u32 = 16u;

fn poisson_disk(i: u32) -> vec2f {
    switch i {
        case  0u: { return vec2f( 0.000000,  0.000000); }
        case  1u: { return vec2f( 0.527837, -0.085868); }
        case  2u: { return vec2f(-0.040088,  0.536087); }
        case  3u: { return vec2f(-0.670445, -0.179949); }
        case  4u: { return vec2f(-0.419418,  0.616039); }
        case  5u: { return vec2f( 0.440453, -0.639399); }
        case  6u: { return vec2f(-0.757088,  0.349334); }
        case  7u: { return vec2f( 0.574619,  0.685879); }
        case  8u: { return vec2f( 0.842785, -0.071951); }
        case  9u: { return vec2f(-0.351958, -0.781361); }
        case 10u: { return vec2f( 0.141526, -0.894406); }
        case 11u: { return vec2f(-0.942484,  0.247322); }
        case 12u: { return vec2f( 0.134606,  0.933761); }
        case 13u: { return vec2f(-0.955920, -0.198534); }
        case 14u: { return vec2f( 0.728288, -0.528013); }
        case 15u: { return vec2f(-0.529344, -0.663776); }
        default:  { return vec2f(0.0, 0.0); }
    }
}

// ── CoC computation ───────────────────────────────────────────────────────────
fn compute_coc(depth: f32) -> f32 {
    return abs(depth - params.focal_distance) / max(params.focal_range, 1e-6)
           * params.max_coc_radius;
}

// ── Entry point ───────────────────────────────────────────────────────────────
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3u) {
    let x = gid.x;
    let y = gid.y;
    if x >= params.width || y >= params.height { return; }

    let w  = i32(params.width);
    let h  = i32(params.height);
    let px = vec2i(i32(x), i32(y));

    // Sharp colour and CoC at the centre pixel
    let sharp_color  = textureLoad(scene_color, px, 0);
    let centre_depth = textureLoad(depth_tex,   px, 0).r;
    let centre_coc   = compute_coc(centre_depth);

    // Number of gather samples, clamped to the disk size
    let n_samples = min(params.bokeh_samples, POISSON_COUNT);

    var accum      = vec4f(0.0);
    var weight_sum = 0.0;

    for (var i: u32 = 0u; i < n_samples; i++) {
        // Scale Poisson disk offset by the centre CoC radius (in pixels)
        let disk_offset = poisson_disk(i) * centre_coc;
        let sample_px   = px + vec2i(i32(disk_offset.x), i32(disk_offset.y));
        let sample_px_c = vec2i(
            clamp(sample_px.x, 0, w - 1),
            clamp(sample_px.y, 0, h - 1),
        );

        let s_color = textureLoad(scene_color, sample_px_c, 0);
        let s_depth = textureLoad(depth_tex,   sample_px_c, 0).r;
        let s_coc   = compute_coc(s_depth);

        // Weight by the sample's own CoC: larger CoC = more blurry = more influence
        let w_ = max(s_coc, 0.001);
        accum      += s_color * w_;
        weight_sum += w_;
    }

    // Normalise accumulated colour
    let blurred = accum / max(weight_sum, 1e-6);

    // Blend: coc=0 → sharp, coc≥1 → fully blurred
    let blend_factor = saturate(centre_coc / max(params.max_coc_radius, 1.0));
    let result = mix(sharp_color, blurred, blend_factor);

    textureStore(dof_out, px, result);
}
