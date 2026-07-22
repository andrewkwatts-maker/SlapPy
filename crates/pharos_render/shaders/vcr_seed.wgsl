// pharos_render :: VCR Stage 1 — Seed reservoirs.
//
// Fullscreen compute pass. For each pixel, read the G-buffer and
// initialise up to VCR_K_SLOTS reservoir slots with ray directions
// derived from normal + roughness (specular cone) + IoR (refractive
// cone). Nova3D §5 Stage 1.

// G-buffer inputs (bound by the pipeline builder at group 0):
@group(0) @binding(0) var g_pos_matid    : texture_2d<f32>;   // RT0
@group(0) @binding(1) var g_normal_rough : texture_2d<f32>;   // RT1
@group(0) @binding(2) var g_base_metal   : texture_2d<f32>;   // RT2
@group(0) @binding(3) var g_ior_absorb   : texture_2d<f32>;   // RT3

// Reservoir output — write only.
@group(1) @binding(0) var reservoir : texture_storage_3d<rgba32float, write>;

// Per-frame push constants (view matrix column-major).
struct SeedUniforms {
    camera_pos: vec4<f32>,
    view_dir_hint: vec4<f32>,
};
@group(2) @binding(0) var<uniform> seed_u: SeedUniforms;

// Injected by pharos_render::vcr::config::wgsl_define_block.
// VCR_K_SLOTS       : u32
// VCR_RES_SCALE     : f32
// VCR_TEMPORAL_ENABLED : bool
// VCR_ALPHA_DROP_THRESHOLD : f32
// VCR_COVERAGE_OPT_OUT : f32

@compute @workgroup_size(8, 8, 1)
fn cs_main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let uv = vec2<i32>(gid.xy);
    let dims = textureDimensions(g_pos_matid);
    if (uv.x >= i32(dims.x) || uv.y >= i32(dims.y)) { return; }

    let pos_matid = textureLoad(g_pos_matid, uv, 0);
    let world_pos = pos_matid.xyz;
    let normal_rough = textureLoad(g_normal_rough, uv, 0);
    let normal = normalize(normal_rough.xyz);
    let roughness = normal_rough.a;
    let ior_absorb = textureLoad(g_ior_absorb, uv, 0);
    let ior = ior_absorb.x;

    // Primary specular slot: reflect view against normal, cone = roughness.
    let view_dir = normalize(world_pos - seed_u.camera_pos.xyz);
    let refl = reflect(view_dir, normal);
    let cone = roughness * 1.57079632;   // roughness [0..1] -> half-angle [0..PI/2]

    // Slot 0: specular reflection.
    let slot0_lo = vec4<f32>(world_pos, 0.0);        // pos + matid
    let slot0_hi = vec4<f32>(refl, cone);            // dir + cone
    textureStore(reservoir, vec3<i32>(uv, 0), slot0_lo);
    textureStore(reservoir, vec3<i32>(uv, 1), slot0_hi);

    // Slot 1: refraction (if K >= 2 and ior != 1.0).
    if (VCR_K_SLOTS >= 2u && abs(ior - 1.0) > 0.001) {
        let eta = 1.0 / ior;
        let refr = refract(view_dir, normal, eta);
        let slot1_lo = vec4<f32>(world_pos, 1.0);
        let slot1_hi = vec4<f32>(refr, cone);
        textureStore(reservoir, vec3<i32>(uv, 2), slot1_lo);
        textureStore(reservoir, vec3<i32>(uv, 3), slot1_hi);
    }

    // Slots 2..K-1: subsurface / diffuse hemisphere samples (later
    // stages accumulate contributions when they hit geometry).
}
