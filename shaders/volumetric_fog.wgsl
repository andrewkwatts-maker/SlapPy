// volumetric_fog.wgsl — Froxelated Volumetric Lighting compute pass
// Produces a fog colour+opacity layer (rgba16float) for additive blending
// over the 3D scene after the PBR / shadow passes.
//
// Algorithm:
//   For each screen pixel:
//     1. Reconstruct the view-space ray direction from inv_proj.
//     2. Ray-march from fog_start to min(fog_end, scene_depth) in num_steps steps.
//     3. At each step sample the precomputed froxel fog density LUT, evaluate the
//        Henyey-Greenstein phase function for the sun, apply shadow_mask attenuation,
//        and accumulate colour with Beer-Lambert transmittance.
//     4. Write vec4f(accumulated_rgb, 1.0 - transmittance) to fog_out.
//        The alpha channel encodes fog opacity for the compositor.
//
// Bind groups:
//   group(0) binding(0) — VolumetricParams  (uniform)
//   group(0) binding(1) — scene_depth       texture_2d<f32>         (linear depth, r32float)
//   group(0) binding(2) — shadow_mask       texture_2d<f32>         (r8unorm shadow factor)
//   group(0) binding(3) — fog_lut           texture_3d<f32>         (density LUT, rgba8unorm,
//                                                                     160×90×64 froxels)
//   group(0) binding(4) — fog_out           texture_storage_2d<rgba16float, write>

// ── Uniform struct ─────────────────────────────────────────────────────────
// VolumetricParams — 112 bytes (std140 compatible)
//   inv_proj      : mat4x4<f32>   offset   0  (64 bytes)
//   fog_color     : vec3<f32>     offset  64  (12 bytes)
//   fog_density   : f32           offset  76  ( 4 bytes)
//   scatter_g     : f32           offset  80  ( 4 bytes)  Henyey-Greenstein g [-1,1]
//   fog_start     : f32           offset  84  ( 4 bytes)  linear depth where fog begins
//   fog_end       : f32           offset  88  ( 4 bytes)  linear depth of full density
//   sun_intensity : f32           offset  92  ( 4 bytes)
//   sun_dir       : vec3<f32>     offset  96  (12 bytes)  normalized world-space
//   ambient       : f32           offset 108  ( 4 bytes)  ambient fog luminance
//   num_steps     : u32           offset 112  ( 4 bytes)  ray-march steps (16-32)
//   width         : u32           offset 116  ( 4 bytes)
//   height        : u32           offset 120  ( 4 bytes)
//   time          : f32           offset 124  ( 4 bytes)  animation clock (seconds)
//   _pad          : f32           offset 128  ( 4 bytes)  alignment
struct VolumetricParams {
    inv_proj:      mat4x4<f32>,
    fog_color:     vec3<f32>,
    fog_density:   f32,
    scatter_g:     f32,
    fog_start:     f32,
    fog_end:       f32,
    sun_intensity: f32,
    sun_dir:       vec3<f32>,
    ambient:       f32,
    num_steps:     u32,
    width:         u32,
    height:        u32,
    time:          f32,
    _pad:          f32,
}

// ── Bindings ───────────────────────────────────────────────────────────────

@group(0) @binding(0) var<uniform> params      : VolumetricParams;
@group(0) @binding(1) var          scene_depth : texture_2d<f32>;
@group(0) @binding(2) var          shadow_mask : texture_2d<f32>;
@group(0) @binding(3) var          fog_lut     : texture_3d<f32>;
@group(0) @binding(4) var          fog_out     : texture_storage_2d<rgba16float, write>;

// ── Henyey-Greenstein phase function ──────────────────────────────────────
// Models anisotropic scattering of light in participating media.
//   cos_theta : cosine of angle between view ray and sun direction
//   g         : asymmetry parameter, -1 (full back-scatter) .. +1 (full forward-scatter)
//               0.0 = isotropic, 0.3 = mild forward scatter (typical for haze/dust)
fn hg_phase(cos_theta: f32, g: f32) -> f32 {
    let PI = 3.14159265358979;
    let g2 = g * g;
    return (1.0 - g2) / (4.0 * PI * pow(1.0 + g2 - 2.0 * g * cos_theta, 1.5));
}

// ── Froxel LUT lookup ──────────────────────────────────────────────────────
// Maps a (uv, linear_depth) sample to the fog_lut voxel grid.
// The LUT covers the frustum from fog_start to fog_end along the Z axis.
// Returns density in the r channel (the lut may encode other data in g/b/a
// for future extension; only r is consumed here).
fn sample_fog_lut(uv: vec2f, linear_depth: f32) -> f32 {
    let lut_dims = vec3f(textureDimensions(fog_lut, 0));

    // Normalised slice position along the depth axis [0,1].
    let depth_range = max(params.fog_end - params.fog_start, 0.0001);
    let depth_t     = clamp((linear_depth - params.fog_start) / depth_range, 0.0, 1.0);

    // Convert to integer voxel coordinates.
    let voxel = vec3i(
        clamp(i32(uv.x * lut_dims.x), 0, i32(lut_dims.x) - 1),
        clamp(i32(uv.y * lut_dims.y), 0, i32(lut_dims.y) - 1),
        clamp(i32(depth_t  * lut_dims.z), 0, i32(lut_dims.z) - 1),
    );
    return textureLoad(fog_lut, voxel, 0).r;
}

// ── Compute entry point ────────────────────────────────────────────────────

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let px = gid.x;
    let py = gid.y;
    if px >= params.width || py >= params.height { return; }

    let coord = vec2i(i32(px), i32(py));

    // ── 1. Load scene depth ────────────────────────────────────────────────
    // scene_depth stores linear (view-space) depth; no perspective divide needed.
    let scene_z = textureLoad(scene_depth, coord, 0).r;

    // UV for shadow/LUT sampling (pixel centre in [0,1]).
    let uv = (vec2f(f32(px), f32(py)) + vec2f(0.5)) / vec2f(f32(params.width), f32(params.height));

    // ── 2. Reconstruct view-space ray direction from inv_proj ──────────────
    // Convert pixel centre to NDC (WGPU: y=0 at top → NDC y=+1 up).
    let ndc_x =  uv.x * 2.0 - 1.0;
    let ndc_y = -uv.y * 2.0 + 1.0;

    // Unproject a point on the far plane (z=1) into view space to get direction.
    let far_ndc   = vec4f(ndc_x, ndc_y, 1.0, 1.0);
    let far_view  = params.inv_proj * far_ndc;
    let ray_dir_v = normalize(far_view.xyz / far_view.w);

    // ── 3. Ray-march through the fog volume ───────────────────────────────
    // Clamp the march to [fog_start, min(fog_end, scene_z)] so fog doesn't
    // bleed in front of solid geometry.
    let march_start = params.fog_start;
    let march_end   = min(params.fog_end, scene_z);

    // Early-out: nothing to accumulate.
    if march_end <= march_start {
        textureStore(fog_out, coord, vec4f(0.0, 0.0, 0.0, 0.0));
        return;
    }

    let march_length = march_end - march_start;
    let num_steps    = max(params.num_steps, 1u);
    let step_size    = march_length / f32(num_steps);

    // Cosine of angle between view ray and sun direction (negate ray because
    // ray_dir_v points away from camera; sun_dir points toward the sun).
    // Work in view space: sun_dir is world-space but for a distant directional
    // light the angle is uniform across the froxel grid.
    // We only need the dot product, so world-vs-view distinction doesn't matter
    // when no camera roll is applied (typical).  Use world-space sun_dir directly.
    let view_world_dir = -ray_dir_v;   // points from surface toward camera
    let cos_theta = dot(view_world_dir, params.sun_dir);

    // Precompute the phase function (constant along a ray for a parallel light).
    let phase = hg_phase(cos_theta, params.scatter_g);

    // Shadow mask for this pixel (bilinear fetch approximated via textureLoad).
    // The shadow_mask is written at the same resolution, so a direct load works.
    let shadow = textureLoad(shadow_mask, coord, 0).r;

    // Accumulated fog colour and transmittance.
    var fog_color_acc = vec3f(0.0);
    var transmittance = 1.0;

    for (var i = 0u; i < num_steps; i++) {
        // Sample at the midpoint of this step.
        let t         = march_start + (f32(i) + 0.5) * step_size;
        let step_pos  = ray_dir_v * t;   // view-space position along ray

        // -- Fog density at this step --
        // Re-project step_pos back to a UV for the LUT lookup (assumes the LUT
        // is a top-down froxel grid aligned to the view frustum).
        // step_pos.xy are in view space; map through inv_proj column to NDC then UV.
        // For a frustum-aligned LUT it is simpler to compute the NDC directly:
        let step_ndc_x =  (step_pos.x / (-step_pos.z)) * params.inv_proj[0][0];
        let step_ndc_y =  (step_pos.y / (-step_pos.z)) * params.inv_proj[1][1];
        let step_uv    = clamp(
            vec2f(step_ndc_x * 0.5 + 0.5, -step_ndc_y * 0.5 + 0.5),
            vec2f(0.0), vec2f(1.0),
        );

        let base_density = sample_fog_lut(step_uv, t);

        // Animate density with a simple time-based modulation (subtle waviness).
        let anim_mod = 1.0 + 0.05 * sin(params.time * 0.7 + step_pos.x * 0.3 + step_pos.z * 0.2);
        let density  = base_density * params.fog_density * anim_mod;

        // -- Scattering contribution --
        // Sun in-scattering: attenuated by shadow_mask and phase function.
        let sun_scatter  = params.fog_color * params.sun_intensity * phase * shadow;
        // Ambient in-scattering: isotropic, not shadowed.
        let amb_scatter  = params.fog_color * params.ambient;
        let step_color   = (sun_scatter + amb_scatter) * density * step_size;

        // -- Beer-Lambert accumulation --
        fog_color_acc += step_color * transmittance;
        transmittance *= exp(-density * step_size);

        // Early-out when fog is opaque enough that further steps have negligible effect.
        if transmittance < 0.001 { break; }
    }

    // ── 4. Write output ────────────────────────────────────────────────────
    // Alpha = fog opacity (0 = transparent, 1 = fully fogged).
    // Compositor adds this layer over the scene with alpha blending.
    let fog_alpha = 1.0 - transmittance;
    textureStore(fog_out, coord, vec4f(fog_color_acc, fog_alpha));
}
