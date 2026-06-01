// contact_shadows_depth.wgsl — Bouvier 2014 screen-space contact shadows.
//
// Round-13 lighting polish: depth-buffer ray-march contact shadows that
// compose with the round-12 Vogel-disk PCF in shadow_csm.wgsl.
//
// Reference:
//   Bouvier, "Contact Shadows in The Order: 1886", GDC 2014.
//
// Algorithm:
//   For each lit pixel:
//     1. Reconstruct view-space surface position from the depth buffer.
//     2. Ray-march in the dominant light direction with N exponentially
//        increasing world-space step distances (covers max_distance total).
//     3. At each sample, reproject the ray's view-space position to NDC.
//     4. Read the depth buffer at the reprojected screen coordinate.
//     5. If the ray's depth at this sample exceeds the depth-buffer hit
//        by more than thickness_threshold the pixel is in contact shadow.
//
// Composition with the main CSM shadow term (Bouvier 2014 §4):
//
//     final_shadow = min(main_shadow, 1.0 - contact_strength * blend)
//
// so contact shadows *only* darken — they cannot brighten a pixel that
// the main CSM has already decided is fully shadowed.
//
// Bind groups:
//   group(0) binding(0) — params       (uniform, 32 bytes)
//   group(0) binding(1) — depth_tex    texture_2d<f32>           (linear depth)
//   group(0) binding(2) — shadow_in    texture_2d<f32>           (CSM shadow mask r8unorm)
//   group(0) binding(3) — inv_proj     (uniform, 64-byte mat4x4)
//   group(0) binding(4) — proj         (uniform, 64-byte mat4x4)
//   group(0) binding(5) — shadow_out   texture_storage_2d<r8unorm, write>

// ── Uniform structs ────────────────────────────────────────────────────────

struct ContactShadowsParams {
    light_dir:     vec3<f32>,  // normalised, points TOWARD the light
    samples:       u32,        // 0 = pass is a no-op (back-compat opt-out)
    max_distance:  f32,        // world units
    thickness:     f32,        // world units; gap required to register occlusion
    blend:         f32,        // [0, 1]; composition strength
    _pad:          u32,
}

struct ProjBuf {
    mat: mat4x4<f32>,
}

// ── Bindings ───────────────────────────────────────────────────────────────

@group(0) @binding(0) var<uniform> params     : ContactShadowsParams;
@group(0) @binding(1) var          depth_tex  : texture_2d<f32>;
@group(0) @binding(2) var          shadow_in  : texture_2d<f32>;
@group(0) @binding(3) var<uniform> inv_proj   : ProjBuf;
@group(0) @binding(4) var<uniform> proj       : ProjBuf;
@group(0) @binding(5) var          shadow_out : texture_storage_2d<r8unorm, write>;

// ── View-space reconstruction from depth ───────────────────────────────────
fn view_pos_from_depth(ndc_xy: vec2<f32>, depth: f32) -> vec3<f32> {
    let ndc  = vec4<f32>(ndc_xy, depth, 1.0);
    let view = inv_proj.mat * ndc;
    return view.xyz / view.w;
}

// ── Exponential per-step distance (matches Python mirror) ──────────────────
// Returns the world-space ray length at step index ``i`` in [0, N).
//   t_i = max_distance * (2^((i + 1) / N) - 1)
// so t_{N-1} == max_distance and t_0 is small but nonzero (no self-shadow).
fn step_distance(i: u32, samples: u32, max_distance: f32) -> f32 {
    let frac = f32(i + 1u) / f32(samples);
    return max_distance * (exp2(frac) - 1.0);
}

// ── Compute entry point ────────────────────────────────────────────────────

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let dims = textureDimensions(shadow_out);
    if gid.x >= dims.x || gid.y >= dims.y { return; }
    let coord = vec2<i32>(gid.xy);

    // Read the current main-shadow term up-front so the no-op /
    // sky early-outs can forward it unchanged.
    let main_shadow = textureLoad(shadow_in, coord, 0).r;

    // Back-compat opt-out: samples == 0 → forward main shadow unchanged.
    if params.samples == 0u {
        textureStore(shadow_out, coord, vec4<f32>(main_shadow, 0.0, 0.0, 1.0));
        return;
    }

    // Skip sky / far-plane pixels.
    let depth = textureLoad(depth_tex, coord, 0).r;
    if depth >= 0.9999 {
        textureStore(shadow_out, coord, vec4<f32>(main_shadow, 0.0, 0.0, 1.0));
        return;
    }

    // Reconstruct view-space surface position.
    let w = f32(dims.x);
    let h = f32(dims.y);
    let ndc_x = (f32(gid.x) + 0.5) / w *  2.0 - 1.0;
    let ndc_y = (f32(gid.y) + 0.5) / h * -2.0 + 1.0;
    let surface_view = view_pos_from_depth(vec2<f32>(ndc_x, ndc_y), depth);

    // Light direction is uniform and already normalised on the CPU side.
    let L = params.light_dir;

    // Bouvier 2014 ray-march: N samples at exponentially-increasing world
    // distances along the light vector.
    var occluded = 0.0;
    for (var i = 0u; i < params.samples; i = i + 1u) {
        let t = step_distance(i, params.samples, params.max_distance);
        let ray_view = surface_view + L * t;

        // Reproject to NDC.
        let clip = proj.mat * vec4<f32>(ray_view, 1.0);
        if clip.w <= 0.0 { continue; }
        let ndc = clip.xyz / clip.w;
        if any(ndc.xy < vec2<f32>(-1.0)) || any(ndc.xy > vec2<f32>(1.0))
           || ndc.z < 0.0 || ndc.z > 1.0 {
            continue;
        }

        // Convert NDC xy to integer pixel coord.
        let uv = ndc.xy * vec2<f32>(0.5, -0.5) + vec2<f32>(0.5);
        let sx = i32(clamp(uv.x, 0.0, 1.0) * w);
        let sy = i32(clamp(uv.y, 0.0, 1.0) * h);
        let sample_depth_raw = textureLoad(depth_tex, vec2<i32>(sx, sy), 0).r;
        if sample_depth_raw >= 0.9999 { continue; }

        // Reproject the depth-buffer hit to view space along the same
        // pixel column to compare like-for-like in world units.
        let buf_view = view_pos_from_depth(
            vec2<f32>(ndc.x, -ndc.y) * vec2<f32>(1.0, 1.0),
            sample_depth_raw,
        );

        // Bouvier 2014 §3.2 occlusion test: ray is "behind" the depth
        // buffer (further from camera) by more than the thickness gap.
        // View-space Z is negative in front of camera (RH); compare on
        // |z| so positive thickness threshold has the obvious meaning.
        let ray_camera_dist = -ray_view.z;
        let buf_camera_dist = -buf_view.z;
        let delta = ray_camera_dist - buf_camera_dist;
        if delta > params.thickness {
            occluded = 1.0;
            break;
        }
    }

    // Compose: contact shadow can only DARKEN the main shadow term.
    let composed = min(main_shadow, 1.0 - occluded * params.blend);
    textureStore(shadow_out, coord, vec4<f32>(composed, 0.0, 0.0, 1.0));
}
