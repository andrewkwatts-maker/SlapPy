// sdf_gbuffer_write.wgsl — SDF hit-to-G-buffer compositor
//
// Reads the hit_pos and hit_normal textures produced by sdf_raymarching.wgsl
// and writes into the three G-buffer slices consumed by the deferred lighting
// passes (lighting_point.wgsl, lighting_directional.wgsl, etc.).
//
// For each pixel:
//   hit_flag == 1  →  write normal, view-depth, and albedo to G-buffer targets.
//   hit_flag == 0  →  write zeros (sky / miss pixel; the lighting pass skips it).
//
// Bind groups:
//   @group(0) @binding(0) — hit_pos_tex      texture_2d<f32>                    (rgba32float)
//                           world-space hit position (xyz) + march distance (w)
//   @group(0) @binding(1) — hit_normal_tex   texture_2d<f32>                    (rgba16float)
//                           world-space normal (xyz) + hit flag (w: 0=miss, 1=hit)
//   @group(0) @binding(2) — albedo_tex       texture_storage_2d<rgba8unorm, write>
//   @group(0) @binding(3) — gbuf_normal_tex  texture_storage_2d<rgba16float, write>
//   @group(0) @binding(4) — gbuf_depth_tex   texture_storage_2d<r32float, write>
//   @group(0) @binding(5) — gbuf_uniforms    GbufUniforms                       (uniform)
//
// Dispatch: ceil(width/8) × ceil(height/8) × 1 workgroups.
//
// Future material system:
//   When per-primitive material indices are added (SdfPrimitive.material_id),
//   bind a material SSBO at @group(1) @binding(0) and index it using the
//   primitive ID packed into hit_pos_tex.w (march distance can move to a
//   separate r32float texture at that point).

// ── Uniforms ──────────────────────────────────────────────────────────────────

// GPU layout (32 bytes):
//   default_albedo: vec4<f32>   offset  0   (rgba, used for all SDF geometry
//                                            until the material system is wired up)
//   width:          u32         offset 16
//   height:         u32         offset 20
//   _pad0:          u32         offset 24
//   _pad1:          u32         offset 28
struct GbufUniforms {
    default_albedo: vec4<f32>,
    width:          u32,
    height:         u32,
    _pad0:          u32,
    _pad1:          u32,
}

// ── Bindings ──────────────────────────────────────────────────────────────────

@group(0) @binding(0) var          hit_pos_tex     : texture_2d<f32>;
@group(0) @binding(1) var          hit_normal_tex  : texture_2d<f32>;
@group(0) @binding(2) var          albedo_tex      : texture_storage_2d<rgba8unorm,  write>;
@group(0) @binding(3) var          gbuf_normal_tex : texture_storage_2d<rgba16float, write>;
@group(0) @binding(4) var          gbuf_depth_tex  : texture_storage_2d<r32float,    write>;
@group(0) @binding(5) var<uniform> gbuf_uniforms   : GbufUniforms;

// ── Compute entry point ───────────────────────────────────────────────────────

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) id: vec3<u32>) {
    let px = vec2<i32>(id.xy);

    // Bounds guard — discard threads outside the output texture.
    if u32(px.x) >= gbuf_uniforms.width || u32(px.y) >= gbuf_uniforms.height { return; }

    // ── Sample raymarcher outputs ─────────────────────────────────────────────
    // textureLoad with explicit mip-level 0 (storage textures have no mips).
    let hit_pos_sample    = textureLoad(hit_pos_tex,    px, 0);
    let hit_normal_sample = textureLoad(hit_normal_tex, px, 0);

    let world_pos  = hit_pos_sample.xyz;
    let march_dist = hit_pos_sample.w;
    let world_norm = hit_normal_sample.xyz;
    let hit_flag   = hit_normal_sample.w;   // 1.0 = hit, 0.0 = miss

    // ── Write G-buffer ────────────────────────────────────────────────────────
    if hit_flag > 0.5 {
        // Hit pixel — write all three G-buffer slices.

        // Albedo: use the uniform default colour until per-primitive materials
        // are available.  Alpha is kept from the uniform (typically 1.0).
        textureStore(albedo_tex,      px, gbuf_uniforms.default_albedo);

        // Normal: pack world-space unit normal into rgba16float.
        // The w channel is set to 0 to reserve it for future use (e.g. packing
        // a smoothness / roughness hint from the material system).
        textureStore(gbuf_normal_tex, px, vec4<f32>(world_norm, 0.0));

        // Depth: store world-space Z (positive = in front of camera).
        // Deferred lighting passes reconstruct world position from this + the
        // normal + the inverse-view-proj, or use it directly for depth sorting.
        textureStore(gbuf_depth_tex,  px, vec4<f32>(world_pos.z, 0.0, 0.0, 0.0));
    } else {
        // Miss pixel — write zeroes to all three G-buffer slices.
        // A zero normal (length == 0) is the sentinel that the lighting pass
        // uses to skip deferred shading for sky / background pixels.
        textureStore(albedo_tex,      px, vec4<f32>(0.0, 0.0, 0.0, 0.0));
        textureStore(gbuf_normal_tex, px, vec4<f32>(0.0, 0.0, 0.0, 0.0));
        textureStore(gbuf_depth_tex,  px, vec4<f32>(0.0, 0.0, 0.0, 0.0));
    }
}
