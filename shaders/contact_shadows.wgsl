// contact_shadows.wgsl — SDF contact shadows (cone-traced soft shadows)
// Cone-marches the SDF scene to compute soft shadows for geometry within
// max_range (default 0.5 m), complementing the CSM for close-range contact.
//
// Based on Nova3D SDFConeShadow.cpp technique.
//
// Algorithm:
//   For each screen pixel with a valid G-buffer position:
//     1. March a ray from the surface position toward the light.
//     2. At each step query the scene SDF (depth-buffer fallback or full SDF).
//     3. Accumulate the minimum cone ratio (cone_k * d / t) as the shadow factor.
//     4. Early-exit if the march exceeds max_range or shadow is essentially 0.
//
// Bind groups:
//   group(0) binding(0) — gbuf_pos     texture_2d<f32>          (world-space XYZ in RGB)
//   group(0) binding(1) — gbuf_depth   texture_2d<f32>          (linear depth, r32float)
//   group(0) binding(2) — shadow_out   texture_storage_2d<r8unorm, write>
//   group(0) binding(3) — u            ContactShadowUniforms    (uniform)

// ── Uniform struct ─────────────────────────────────────────────────────────

struct ContactShadowUniforms {
    screen_w:    u32,
    screen_h:    u32,
    max_range:   f32,  // max shadow march distance (world units, e.g. 0.5)
    cone_k:      f32,  // cone sharpness (8.0 = soft, 16.0 = sharp)
    light_dir_x: f32,
    light_dir_y: f32,
    light_dir_z: f32,
    _pad:        f32,
};

// ── Bindings ───────────────────────────────────────────────────────────────

@group(0) @binding(0) var gbuf_pos:   texture_2d<f32>;
@group(0) @binding(1) var gbuf_depth: texture_2d<f32>;
@group(0) @binding(2) var shadow_out: texture_storage_2d<r8unorm, write>;
@group(0) @binding(3) var<uniform>    u: ContactShadowUniforms;

// ── Scene SDF approximation ────────────────────────────────────────────────
// This is a depth-buffer fallback: returns a conservative minimum distance
// to occluding geometry.  When SdfRenderer is active, it replaces this call
// with a dispatch into sdf_scene.wgsl for accurate world-space distances.
fn scene_sdf(pos: vec3<f32>) -> f32 {
    // Stub: real SDF dispatch wired by SdfRenderer.
    // Returns a small positive value so the marcher always advances and
    // eventually exits via the t > max_range condition.
    return 0.1;
}

// ── Cone-march shadow function ─────────────────────────────────────────────
// pos       : world-space surface position (start of the shadow ray)
// light_dir : normalised direction toward the light
// Returns   : shadow factor in [0, 1] — 1.0 = fully lit, 0.0 = fully occluded
fn sdf_contact_shadow(pos: vec3<f32>, light_dir: vec3<f32>) -> f32 {
    let step_min = 0.002;   // minimum march step (avoids self-intersection)
    let step_max = 0.1;     // maximum march step (caps overshoot)
    var t      = 0.02;      // initial offset to avoid self-shadowing
    var shadow = 1.0;

    for (var i = 0; i < 32; i++) {
        let p = pos + light_dir * t;
        let d = scene_sdf(p);
        // Cone ratio: smaller d relative to t means a sharper / deeper shadow.
        shadow = min(shadow, u.cone_k * d / t);
        t += clamp(d, step_min, step_max);
        if t > u.max_range || shadow < 0.0001 {
            break;
        }
    }
    return clamp(shadow, 0.0, 1.0);
}

// ── Compute entry point ────────────────────────────────────────────────────

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if gid.x >= u.screen_w || gid.y >= u.screen_h { return; }
    let coord = vec2<i32>(gid.xy);

    // Skip sky / far-plane pixels (depth == 1.0 written by CSM early-out).
    let depth = textureLoad(gbuf_depth, coord, 0).r;
    if depth >= 0.9999 {
        textureStore(shadow_out, coord, vec4<f32>(1.0, 0.0, 0.0, 1.0));
        return;
    }

    let pos       = textureLoad(gbuf_pos, coord, 0).xyz;
    let light_dir = normalize(vec3<f32>(u.light_dir_x, u.light_dir_y, u.light_dir_z));

    let shadow = sdf_contact_shadow(pos, light_dir);

    // r8unorm: 1.0 = fully lit, 0.0 = fully in shadow (same convention as CSM).
    textureStore(shadow_out, coord, vec4<f32>(shadow, 0.0, 0.0, 1.0));
}
