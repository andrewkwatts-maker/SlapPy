// ssr.wgsl — Screen Space Reflections (SSR) compute pass
// Ray-marches reflected rays in screen space with 16 exponential steps followed
// by 4-iteration binary refinement on a depth-thickness hit.  A BlueNoise-style
// per-pixel rotation (interleaved gradient noise) jitters the ray origin to
// break up banding without a noise texture lookup.
//
// Roughness is approximated from the deviation of the world-space normal from
// camera-space vertical (no roughness texture is available in this pass).
// Pixels whose estimated roughness exceeds roughness_cutoff are skipped, and
// the scene colour is passed through unchanged.
//
// Bindings (all group 0):
//   binding(0) — SsrParams              uniform
//   binding(1) — gbuffer_pos            texture_2d<f32>  (world-space XYZ in RGB)
//   binding(2) — gbuffer_normal         texture_2d<f32>  (world-space normal  in RGB, [0,1] packed)
//   binding(3) — scene_color            texture_2d<f32>  (current frame HDR colour)
//   binding(4) — depth_tex              texture_2d<f32>  (linear depth, r32float)
//   binding(5) — tex_sampler            sampler
//   binding(6) — ssr_out                texture_storage_2d<rgba16float, write>

// ── Uniform struct ─────────────────────────────────────────────────────────────

struct SsrParams {
    width:            u32,
    height:           u32,
    max_steps:        u32,   // ray-march step count  (spec: 16)
    stride:           f32,   // initial step size in pixels (spec: 1.5)
    thickness:        f32,   // depth-difference tolerance for a hit (world units)
    strength:         f32,   // reflection blend strength [0, 1]
    roughness_cutoff: f32,   // skip pixels with estimated roughness above this
    _pad:             u32,
}

// ── Bindings ───────────────────────────────────────────────────────────────────

@group(0) @binding(0) var<uniform> ssr      : SsrParams;
@group(0) @binding(1) var gbuffer_pos       : texture_2d<f32>;
@group(0) @binding(2) var gbuffer_normal    : texture_2d<f32>;
@group(0) @binding(3) var scene_color       : texture_2d<f32>;
@group(0) @binding(4) var depth_tex         : texture_2d<f32>;
@group(0) @binding(5) var tex_sampler       : sampler;
@group(0) @binding(6) var ssr_out           : texture_storage_2d<rgba16float, write>;

// ── Constants ──────────────────────────────────────────────────────────────────

const BINARY_REFINE_STEPS: i32 = 4;

// ── Helpers ────────────────────────────────────────────────────────────────────

// Interleaved gradient noise — cheap, low-discrepancy, no texture needed.
// Produces a scalar in [0, 1) that varies smoothly across pixels.
fn ign(px: vec2f) -> f32 {
    return fract(52.9829189 * fract(0.06711056 * px.x + 0.00583715 * px.y));
}

// Load linear depth at an integer pixel coordinate, clamped to valid range.
fn load_depth(coord: vec2i) -> f32 {
    let w = i32(ssr.width);
    let h = i32(ssr.height);
    let c = vec2i(clamp(coord.x, 0, w - 1), clamp(coord.y, 0, h - 1));
    return textureLoad(depth_tex, c, 0).r;
}

// Project a world-space position into screen UV [0,1] × [0,1] and return its
// linear depth.  This is a screen-space technique so we re-use the depth buffer
// to derive the camera-space relationship.
//
// We interpret gbuffer_pos.z as the linear camera-space depth for the current
// pixel and derive the per-pixel projection scale from the ratio of projected
// pixel coordinates to their depth — a thin-lens approximation that avoids
// needing an explicit view-projection matrix in this pass.
//
// world_to_screen converts a world-space point to screen UV using the reference
// pixel (ref_px) that established the camera-space frame.  It returns
// (uv.x, uv.y, view_depth) where view_depth is the linearly interpolated Z
// used for depth comparison.
fn world_to_screen(
    world_pos:  vec3f,
    ref_world:  vec3f,   // world-space position of the reference (shaded) pixel
    ref_depth:  f32,     // linear depth of the reference pixel
    ref_px:     vec2i,   // integer pixel coordinates of the reference pixel
) -> vec3f {
    let w = f32(ssr.width);
    let h = f32(ssr.height);

    // Derive camera-space direction vectors from the reference pixel.
    // In a standard pinhole model, the screen-space (s,t) coordinates of any
    // world point P satisfy:
    //   s = ref_s + (P - ref_world) . right / depth_scale
    //   t = ref_t + (P - ref_world) . up    / depth_scale
    // where depth_scale encodes the fov.  We approximate this by treating the
    // difference from the reference position in a view-aligned plane.

    // Camera-up is the world Y axis (simplified — works for non-tilted cameras).
    let cam_up    = vec3f(0.0, 1.0, 0.0);
    // Camera-right is derived so it is perpendicular to the view direction and up.
    let view_dir  = normalize(-ref_world);   // approximate view direction (cam at origin)
    let cam_right = normalize(cross(view_dir, cam_up));
    let cam_up2   = cross(cam_right, view_dir);

    // Tangential displacement in the view-aligned plane.
    let delta = world_pos - ref_world;
    let dx    = dot(delta, cam_right);
    let dy    = dot(delta, cam_up2);

    // Scale factor: at the reference depth, one unit of world displacement maps
    // to (w / (2 * tan(fov/2) * ref_depth)) pixels.  We derive the pixel scale
    // empirically from the reference pixel's NDC position.
    let ref_ndc_x = (f32(ref_px.x) + 0.5) / w * 2.0 - 1.0;
    let ref_ndc_y = (f32(ref_px.y) + 0.5) / h * 2.0 - 1.0;
    // tan(half_fov) approximation from the aspect and NDC depth.
    // pixel_per_world_unit at ref_depth:
    let half_w_world = abs(ref_ndc_x) * ref_depth + 0.001;
    let px_per_unit_x = (w * 0.5) / max(half_w_world, 0.001);

    let half_h_world = abs(ref_ndc_y) * ref_depth + 0.001;
    let px_per_unit_y = (h * 0.5) / max(half_h_world, 0.001);

    // New pixel position.
    let new_px_x = f32(ref_px.x) + dx * px_per_unit_x;
    let new_px_y = f32(ref_px.y) - dy * px_per_unit_y;  // Y flipped (top-left origin)

    // Estimated depth at the new position (linear interpolation).
    let view_depth = ref_depth + dot(delta, -view_dir);

    let uv = vec2f(
        (new_px_x + 0.5) / w,
        (new_px_y + 0.5) / h,
    );
    return vec3f(uv, view_depth);
}

// Sample scene_color at a normalised UV, clamped (no sampler needed for load).
fn sample_scene(uv: vec2f) -> vec3f {
    let w  = i32(ssr.width);
    let h  = i32(ssr.height);
    let px = vec2i(
        clamp(i32(uv.x * f32(w)), 0, w - 1),
        clamp(i32(uv.y * f32(h)), 0, h - 1),
    );
    return textureLoad(scene_color, px, 0).rgb;
}

// ── Entry point ────────────────────────────────────────────────────────────────

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3u) {
    let x = gid.x;
    let y = gid.y;
    if x >= ssr.width || y >= ssr.height { return; }

    let w  = i32(ssr.width);
    let h  = i32(ssr.height);
    let px = vec2i(i32(x), i32(y));

    // ── 1. Read G-buffer ──────────────────────────────────────────────────────
    let world_pos    = textureLoad(gbuffer_pos,    px, 0).xyz;
    let normal_raw   = textureLoad(gbuffer_normal, px, 0).xyz;
    let scene_pixel  = textureLoad(scene_color,    px, 0);
    let frag_depth   = load_depth(px);

    // ── 2. Sky / background guard ─────────────────────────────────────────────
    // A depth near zero means no geometry was rendered here.
    if frag_depth < 0.0001 {
        textureStore(ssr_out, px, scene_pixel);
        return;
    }

    // Decode packed normal ([0,1] → [-1,1]) and normalise.
    let N = normalize(normal_raw * 2.0 - 1.0);

    // ── 3. Roughness estimate from normal deviation ───────────────────────────
    // The world-space camera-up (Y) serves as the canonical "mirror" axis.
    // High deviation → tilted surface → effectively rougher for SSR purposes.
    // roughness_factor ∈ [0, 1]: 0 = mirror-flat (N points straight up), 1 = max tilt.
    let roughness_factor = 1.0 - abs(N.y);

    if roughness_factor > ssr.roughness_cutoff {
        // Surface too rough — pass scene colour unchanged.
        textureStore(ssr_out, px, scene_pixel);
        return;
    }

    // ── 4. Reflect the view direction about the surface normal ────────────────
    // Approximate view direction from the world-space position.
    // Camera is assumed to be near the origin in world space; for a proper
    // implementation supply view-space positions from the G-buffer.
    let V          = normalize(-world_pos);       // direction toward camera
    let R          = normalize(reflect(-V, N));    // reflected direction (away from camera)

    // ── 5. Blue-noise jitter via IGN ─────────────────────────────────────────
    // Jitter the first march step so adjacent pixels explore different depths,
    // breaking up the characteristic SSR staircase pattern.
    let noise_val  = ign(vec2f(f32(x), f32(y)));

    // ── 6. Ray march in screen space ─────────────────────────────────────────
    // We march ray_pos in world space and project each step to screen UV,
    // then compare against the depth buffer to detect intersections.

    var ray_pos      = world_pos;
    var hit_uv       = vec2f(-1.0);   // sentinel: no hit
    var hit_found    = false;

    // Exponential step size: starts small near the surface, grows outward.
    // The stride param scales the base step; noise_val offsets the first step.
    var step_size = ssr.stride * (1.0 + noise_val * 0.5);

    for (var i: u32 = 0u; i < ssr.max_steps; i++) {
        ray_pos  += R * step_size;
        step_size *= 1.25;   // exponential growth — covers more range with fewer steps

        // Project ray_pos to screen space.
        let proj  = world_to_screen(ray_pos, world_pos, frag_depth, px);
        let ray_uv    = proj.xy;
        let ray_depth = proj.z;

        // Reject rays that leave the screen.
        if ray_uv.x < 0.0 || ray_uv.x > 1.0 || ray_uv.y < 0.0 || ray_uv.y > 1.0 {
            break;
        }
        if ray_depth <= 0.0 {
            continue;
        }

        // Sample the depth buffer at the projected position.
        let screen_px    = vec2i(
            clamp(i32(ray_uv.x * f32(w)), 0, w - 1),
            clamp(i32(ray_uv.y * f32(h)), 0, h - 1),
        );
        let scene_depth  = load_depth(screen_px);

        // A hit occurs when the ray is behind the depth-buffer surface by less
        // than the thickness tolerance (avoids false hits through thin walls).
        let depth_diff = ray_depth - scene_depth;
        if depth_diff > 0.0 && depth_diff < ssr.thickness {
            // ── 7. Binary refinement ─────────────────────────────────────────
            // Bisect the march interval to find a more accurate hit UV.
            var lo   = ray_pos - R * (step_size / 1.25);   // last miss position
            var hi   = ray_pos;                              // current hit position
            var best_uv = ray_uv;

            for (var r: i32 = 0; r < BINARY_REFINE_STEPS; r++) {
                let mid      = (lo + hi) * 0.5;
                let mid_proj = world_to_screen(mid, world_pos, frag_depth, px);
                let mid_uv   = mid_proj.xy;
                let mid_depth = mid_proj.z;

                if mid_uv.x < 0.0 || mid_uv.x > 1.0 ||
                   mid_uv.y < 0.0 || mid_uv.y > 1.0 {
                    break;
                }

                let mid_screen_px = vec2i(
                    clamp(i32(mid_uv.x * f32(w)), 0, w - 1),
                    clamp(i32(mid_uv.y * f32(h)), 0, h - 1),
                );
                let mid_scene_depth = load_depth(mid_screen_px);
                let mid_diff = mid_depth - mid_scene_depth;

                if mid_diff > 0.0 && mid_diff < ssr.thickness {
                    // Still a hit — push lo forward to narrow the interval.
                    lo       = mid;
                    best_uv  = mid_uv;
                } else {
                    // Miss or overshoot — pull hi back.
                    hi = mid;
                }
            }

            hit_uv    = best_uv;
            hit_found = true;
            break;
        }
    }

    // ── 8. Compose output ─────────────────────────────────────────────────────
    if hit_found {
        let reflected_color = sample_scene(hit_uv);

        // Scale reflection strength: full-strength on mirror surfaces, fades
        // toward zero as roughness approaches the cutoff.
        let roughness_fade = 1.0 - roughness_factor / max(ssr.roughness_cutoff, 0.001);
        let blend_weight   = ssr.strength * clamp(roughness_fade, 0.0, 1.0);

        // Edge fade: attenuate reflections near screen borders to hide pop-in.
        let edge_fade_x = min(hit_uv.x, 1.0 - hit_uv.x) * 10.0;
        let edge_fade_y = min(hit_uv.y, 1.0 - hit_uv.y) * 10.0;
        let edge_fade   = clamp(min(edge_fade_x, edge_fade_y), 0.0, 1.0);

        let final_blend = blend_weight * edge_fade;
        let out_color   = mix(scene_pixel.rgb, reflected_color, final_blend);
        textureStore(ssr_out, px, vec4f(out_color, scene_pixel.a));
    } else {
        // No hit — pass through unmodified scene colour.
        textureStore(ssr_out, px, scene_pixel);
    }
}
