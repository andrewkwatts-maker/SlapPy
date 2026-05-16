// ao_gtao.wgsl — Ground Truth Ambient Occlusion (horizon-based, GTAO)
// Estimates per-pixel occlusion by searching for the maximum horizon angle
// in multiple screen-space slice directions, then integrates over the
// hemisphere to produce a visibility term.
//
// Bindings:
//   group(0) binding(0) — GtaoParams   (uniform)
//   group(0) binding(1) — depth_tex    texture_2d<f32>  (linear depth, r32float)
//   group(0) binding(2) — normal_tex   texture_2d<f32>  (world-space normals, rgba8unorm)
//   group(0) binding(3) — ao_output    texture_storage_2d<r8unorm, write>

struct GtaoParams {
    inv_proj:         mat4x4<f32>,   // 64 bytes — reconstructs view-space position
    radius:           f32,           // world-space AO radius (e.g. 0.5 m)
    max_pixel_radius: f32,           // radius clamped in pixels (e.g. 64 px)
    num_directions:   u32,           // number of slice planes (4–8)
    num_steps:        u32,           // marching steps per direction (4–8)
    power:            f32,           // AO darkening curve (2.0 = strong)
    bias:             f32,           // horizon angle bias to suppress self-shadowing (rad)
    width:            u32,
    height:           u32,
}

@group(0) @binding(0) var<uniform> gtao_params : GtaoParams;
@group(0) @binding(1) var          depth_tex   : texture_2d<f32>;
@group(0) @binding(2) var          normal_tex  : texture_2d<f32>;
@group(0) @binding(3) var          ao_output   : texture_storage_2d<r8unorm, write>;

// ── Constants ─────────────────────────────────────────────────────────────────

const PI:     f32 = 3.14159265358979;
const TWO_PI: f32 = 6.28318530717959;
const HALF_PI: f32 = 1.5707963267949;

// ── Noise / dithering ─────────────────────────────────────────────────────────

// Interleaved gradient noise — distributes sample patterns across pixels to
// hide banding without a texture lookup.
fn interleaved_gradient_noise(pixel: vec2f) -> f32 {
    return fract(52.9829189 * fract(0.06711056*pixel.x + 0.00583715*pixel.y));
}

// ── Depth / position helpers ──────────────────────────────────────────────────

// Load linear depth for a clamped pixel coordinate.
fn load_depth(coord: vec2i, w: i32, h: i32) -> f32 {
    let c = vec2i(clamp(coord.x, 0, w - 1), clamp(coord.y, 0, h - 1));
    return textureLoad(depth_tex, c, 0).r;
}

// Reconstruct view-space position from a pixel coordinate and linear depth.
// Uses inv_proj to reverse the projection.  The depth value is interpreted as
// the linear view-space Z (positive into the scene).
fn reconstruct_view_pos(coord: vec2i, depth: f32, w: i32, h: i32) -> vec3f {
    // Map pixel centre to NDC [-1, 1] (Y flipped for WGPU's top-left origin).
    let ndc_x =  (f32(coord.x) + 0.5) / f32(w) *  2.0 - 1.0;
    let ndc_y = -(f32(coord.y) + 0.5) / f32(h) *  2.0 + 1.0;

    // Reconstruct clip-space position using the stored linear depth as -Z.
    let clip = vec4f(ndc_x, ndc_y, -1.0, 1.0);
    var view = gtao_params.inv_proj * clip;
    view /= view.w;

    // Scale the ray to the actual depth.
    let ray_dir = normalize(view.xyz);
    return ray_dir * (depth / abs(ray_dir.z));
}

// ── Normal helpers ────────────────────────────────────────────────────────────

// Decode world-space normal from [0,1] stored in rgba8unorm → [-1,1] unit vec.
fn load_view_normal(coord: vec2i, w: i32, h: i32) -> vec3f {
    let c      = vec2i(clamp(coord.x, 0, w - 1), clamp(coord.y, 0, h - 1));
    let packed = textureLoad(normal_tex, c, 0).xyz;
    return normalize(packed * 2.0 - 1.0);
}

// ── Entry point ───────────────────────────────────────────────────────────────

@compute @workgroup_size(8, 8)
fn ao_gtao_main(@builtin(global_invocation_id) gid: vec3u) {
    let x = gid.x;
    let y = gid.y;
    if x >= gtao_params.width || y >= gtao_params.height { return; }

    let w  = i32(gtao_params.width);
    let h  = i32(gtao_params.height);
    let px = vec2i(i32(x), i32(y));

    // ── 1. Reconstruct view-space position and normal ─────────────────────────
    let depth = load_depth(px, w, h);

    // Skip sky / background (depth near 0 means nothing was rendered here).
    if depth < 0.0001 {
        textureStore(ao_output, px, vec4f(1.0, 0.0, 0.0, 0.0));
        return;
    }

    let P = reconstruct_view_pos(px, depth, w, h);
    let N = load_view_normal(px, w, h);

    // View-space view direction (camera is at origin in view space).
    let V = normalize(-P);

    // ── 2. Compute screen-space radius in pixels ──────────────────────────────
    // Project the world-space radius onto the screen at the sample's depth.
    // Approximation: pixel_radius ≈ radius / (|P.z| * tan(half_fov_y)).
    // We derive the pixel-per-unit scale from inv_proj[1][1] = 1/tan(half_fov_y).
    let tan_half_fov_inv = gtao_params.inv_proj[1][1];  // = 1/tan(half_fov_y)
    let pixel_scale      = (f32(h) * 0.5) * tan_half_fov_inv;
    let pixel_radius     = clamp(
        gtao_params.radius * pixel_scale / max(abs(P.z), 0.001),
        1.0,
        gtao_params.max_pixel_radius,
    );

    // Step size in pixels along each slice direction.
    let step_size_px = pixel_radius / f32(gtao_params.num_steps);

    // ── 3. Per-pixel random rotation to break up banding ─────────────────────
    let noise_val    = interleaved_gradient_noise(vec2f(f32(x), f32(y)));
    let angle_offset = noise_val * PI;  // rotate slice directions per pixel

    // ── 4. Horizon integration over num_directions slices ────────────────────
    var ao_sum = 0.0;

    let num_dir = gtao_params.num_directions;
    let num_stp = gtao_params.num_steps;

    for (var dir_idx: u32 = 0u; dir_idx < num_dir; dir_idx++) {
        // Spread directions evenly across [0, PI); add per-pixel rotation.
        let angle  = (f32(dir_idx) / f32(num_dir)) * PI + angle_offset;
        let slice_dir = vec2f(cos(angle), sin(angle));

        // ── 4a. Find the maximum horizon angle h+ along this slice ────────────
        var h_angle_pos: f32 = -HALF_PI;  // worst-case: horizon behind us

        for (var step: u32 = 1u; step <= num_stp; step++) {
            // March outward in pixel space.
            let offset_px = slice_dir * (f32(step) * step_size_px);
            let sample_px = vec2i(
                clamp(px.x + i32(round(offset_px.x)), 0, w - 1),
                clamp(px.y + i32(round(offset_px.y)), 0, h - 1),
            );

            let sample_depth = load_depth(sample_px, w, h);
            if sample_depth < 0.0001 { continue; }  // skip sky

            let S = reconstruct_view_pos(sample_px, sample_depth, w, h);

            // Horizon vector from current position to sample.
            let horizon_vec = S - P;
            let dist        = length(horizon_vec);
            if dist < 0.0001 { continue; }

            // Elevation angle of this sample relative to the view direction.
            let elev_angle = asin(clamp(dot(horizon_vec / dist, V), -1.0, 1.0));

            // Keep the maximum (highest) horizon angle.
            h_angle_pos = max(h_angle_pos, elev_angle);
        }

        // ── 4b. Apply angle bias to suppress self-shadowing artefacts ─────────
        h_angle_pos = max(h_angle_pos, -HALF_PI + gtao_params.bias);

        // ── 4c. Bent-normal AO contribution for this slice ────────────────────
        // GTAO integration: visibility ≈ 1 - sin(h+)^2 weighted by N·T.
        // We use the simplified form: AO_slice = sin(h+) contribution.
        let sin_h  = sin(h_angle_pos);
        let slice_contribution = sin_h * sin_h;
        ao_sum += slice_contribution;
    }

    // ── 5. Average over all directions and apply power curve ─────────────────
    let mean_occlusion = ao_sum / f32(num_dir);

    // mean_occlusion ∈ [0,1]: 0 = fully visible, 1 = fully occluded.
    // Invert to get visibility, then darken with power.
    let visibility = 1.0 - mean_occlusion;
    let ao_final   = clamp(pow(visibility, 1.0 / max(gtao_params.power, 0.001)), 0.0, 1.0);

    // ── 6. Write result (r8unorm: 1.0 = no occlusion, 0.0 = fully occluded) ──
    textureStore(ao_output, px, vec4f(ao_final, 0.0, 0.0, 0.0));
}
