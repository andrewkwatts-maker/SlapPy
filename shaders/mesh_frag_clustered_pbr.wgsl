// mesh_frag_clustered_pbr.wgsl
// Cook-Torrance PBR fragment shader with 3D clustered lighting.
//
// This shader replaces the brute-force light loop in mesh_frag_pbr.wgsl with a
// cluster-based lookup:  each fragment identifies its 3D cluster (tile_x,
// tile_y, depth_slice) and iterates only the lights that were binned into that
// cluster by cluster_cull_3d.wgsl.  The rest of the PBR math is identical to
// mesh_frag_pbr.wgsl.
//
// Bind groups
// -----------
//   group(0) binding(0) — MeshUniforms        (model/view/proj/normal_matrix)
//   group(1) binding(0) — MaterialUniforms    (albedo, metallic, roughness, ior,
//                                              emissive, texture presence flags)
//   group(1) binding(1) — albedo_tex          texture_2d<f32>
//   group(1) binding(2) — normal_tex          texture_2d<f32>
//   group(1) binding(3) — tex_sampler         sampler
//   group(2) binding(0) — lights[]            array<GpuLight3D>  (storage, read)
//   group(2) binding(1) — light_grid[]        array<u32>         (storage, read)
//   group(2) binding(2) — light_count_grid[]  array<u32>         (storage, read)
//   group(2) binding(3) — ClusterFragUniforms (uniform)
//   group(3) binding(0) — ibl_sh              IblSH  (9 × vec4 SH coefficients)
//   group(3) binding(1) — ibl_prefilter       texture_2d<f32>
//   group(3) binding(2) — ibl_brdf_lut        texture_2d<f32>
//   group(3) binding(3) — ibl_sampler         sampler
//
// Cluster constants (must match cluster_build_3d.wgsl / cluster_cull_3d.wgsl)
// ---------------------------------------------------------------------------

const TILES_X:             u32 = 16u;
const TILES_Y:             u32 = 9u;
const TILES_Z:             u32 = 24u;
const MAX_LIGHTS_PER_CLUSTER: u32 = 64u;

// ── Group 0 — Mesh uniforms ────────────────────────────────────────────────

struct MeshUniforms {
    model:         mat4x4<f32>,
    view:          mat4x4<f32>,
    proj:          mat4x4<f32>,
    normal_matrix: mat4x4<f32>,
}

@group(0) @binding(0) var<uniform> mesh: MeshUniforms;

// ── Group 1 — Material uniforms and textures ───────────────────────────────
// GPU layout must match PbrMaterial.to_gpu_bytes() (80 bytes):
//   albedo           : vec4<f32>   offset  0  (16 bytes)
//   metallic         : f32         offset 16  ( 4 bytes)
//   roughness        : f32         offset 20  ( 4 bytes)
//   emissive_strength: f32         offset 24  ( 4 bytes)
//   ior              : f32         offset 28  ( 4 bytes)
//   emissive         : vec3<f32>   offset 32  (12 bytes)
//   _pad             : f32         offset 44  ( 4 bytes)
//   has_albedo_tex   : u32         offset 48  ( 4 bytes)
//   has_normal_tex   : u32         offset 52  ( 4 bytes)
//   _pad2            : u32         offset 56  ( 4 bytes)
//   _pad3            : u32         offset 60  ( 4 bytes)

struct MaterialUniforms {
    albedo:            vec4<f32>,
    metallic:          f32,
    roughness:         f32,
    emissive_strength: f32,
    ior:               f32,
    emissive:          vec3<f32>,
    _pad:              f32,
    has_albedo_tex:    u32,
    has_normal_tex:    u32,
    _pad2:             u32,
    _pad3:             u32,
}

@group(1) @binding(0) var<uniform> material:    MaterialUniforms;
@group(1) @binding(1) var          albedo_tex:  texture_2d<f32>;
@group(1) @binding(2) var          normal_tex:  texture_2d<f32>;
@group(1) @binding(3) var          tex_sampler: sampler;

// ── Group 2 — Clustered lighting buffers ───────────────────────────────────

// A single 3D point light (view-space, packed as two vec4s for alignment).
// Must match GpuLight3D in cluster_cull_3d.wgsl.
struct GpuLight3D {
    // xyz = world-space position, w = effective radius.
    pos_radius:      vec4<f32>,
    // xyz = linear RGB colour, w = intensity multiplier.
    color_intensity: vec4<f32>,
}

// Per-frame cluster parameters needed to reconstruct the cluster index for
// each fragment.
struct ClusterFragUniforms {
    // Camera near and far distances (positive magnitudes).
    near:     f32,
    far:      f32,
    // Framebuffer dimensions in pixels.
    screen_w: f32,
    screen_h: f32,
}

@group(2) @binding(0) var<storage, read> lights:           array<GpuLight3D>;
// Flat index list; stride per cluster = MAX_LIGHTS_PER_CLUSTER + 1 u32s.
@group(2) @binding(1) var<storage, read> light_grid:       array<u32>;
// Per-cluster light counts (non-atomic u32 — safe to read after cull pass).
@group(2) @binding(2) var<storage, read> light_count_grid: array<u32>;
@group(2) @binding(3) var<uniform>       cluster_params:   ClusterFragUniforms;

// ── Group 3 — IBL bindings ─────────────────────────────────────────────────

struct IblSH { coeffs: array<vec4<f32>, 9> }

@group(3) @binding(0) var<uniform> ibl_sh:        IblSH;
@group(3) @binding(1) var          ibl_prefilter: texture_2d<f32>;
@group(3) @binding(2) var          ibl_brdf_lut:  texture_2d<f32>;
@group(3) @binding(3) var          ibl_sampler:   sampler;

// ── Fragment input (matches VertexOutput from mesh_vert_3d.wgsl) ──────────

struct FragmentInput {
    @location(0) world_pos:    vec3<f32>,
    @location(1) world_normal: vec3<f32>,
    @location(2) uv:           vec2<f32>,
    @location(3) tangent:      vec3<f32>,
    @location(4) bitangent:    vec3<f32>,
    // Clip-space position is automatically provided by the rasterizer; we
    // declare it here so we can read the NDC coordinates for cluster lookup.
    @builtin(position) frag_coord: vec4<f32>,
}

// ── PBR math helpers (identical to mesh_frag_pbr.wgsl) ────────────────────

// GGX / Trowbridge-Reitz normal distribution function.
fn distribution_ggx(n_dot_h: f32, roughness: f32) -> f32 {
    let a     = roughness * roughness;
    let a2    = a * a;
    let denom = n_dot_h * n_dot_h * (a2 - 1.0) + 1.0;
    return a2 / (3.14159265 * denom * denom);
}

// Schlick-GGX geometry sub-function.
fn geometry_schlick_ggx(n_dot_v: f32, roughness: f32) -> f32 {
    let r = roughness + 1.0;
    let k = (r * r) / 8.0;
    return n_dot_v / (n_dot_v * (1.0 - k) + k);
}

// Smith geometry function (view and light terms combined).
fn geometry_smith(n_dot_v: f32, n_dot_l: f32, roughness: f32) -> f32 {
    return geometry_schlick_ggx(n_dot_v, roughness)
         * geometry_schlick_ggx(n_dot_l, roughness);
}

// Fresnel-Schlick approximation.
fn fresnel_schlick(cos_theta: f32, f0: vec3<f32>) -> vec3<f32> {
    let t  = clamp(1.0 - cos_theta, 0.0, 1.0);
    let t2 = t * t;
    let t5 = t2 * t2 * t;
    return f0 + (vec3<f32>(1.0) - f0) * t5;
}

// Cook-Torrance BRDF for a single punctual point light.
fn pbr_cook_torrance_point(
    albedo:    vec3<f32>,
    metallic:  f32,
    roughness: f32,
    f0:        vec3<f32>,
    n:         vec3<f32>,
    v:         vec3<f32>,
    l:         vec3<f32>,
    radiance:  vec3<f32>,
) -> vec3<f32> {
    let h       = normalize(v + l);
    let n_dot_v = max(dot(n, v), 0.0001);
    let n_dot_l = max(dot(n, l), 0.0);
    let n_dot_h = max(dot(n, h), 0.0);
    let h_dot_v = max(dot(h, v), 0.0);

    let ndf     = distribution_ggx(n_dot_h, roughness);
    let g       = geometry_smith(n_dot_v, n_dot_l, roughness);
    let fresnel = fresnel_schlick(h_dot_v, f0);

    let spec_num = ndf * g * fresnel;
    let specular = spec_num / (4.0 * n_dot_v * n_dot_l + 0.0001);

    let k_s  = fresnel;
    let k_d  = (vec3<f32>(1.0) - k_s) * (1.0 - metallic);
    let diff = k_d * albedo / 3.14159265;

    return (diff + specular) * radiance * n_dot_l;
}

// Evaluate L2 spherical-harmonic irradiance for a world-space normal.
fn sh_irradiance(n: vec3<f32>, sh: IblSH) -> vec3<f32> {
    let c = sh.coeffs;
    return max(vec3<f32>(0.0),
          c[0].rgb * 0.282095
        + c[1].rgb * 0.488603 * n.y
        + c[2].rgb * 0.488603 * n.z
        + c[3].rgb * 0.488603 * n.x
        + c[4].rgb * 1.092548 * n.x * n.y
        + c[5].rgb * 1.092548 * n.y * n.z
        + c[6].rgb * 0.315392 * (3.0 * n.z * n.z - 1.0)
        + c[7].rgb * 1.092548 * n.x * n.z
        + c[8].rgb * 0.546274 * (n.x * n.x - n.y * n.y)
    );
}

// Recover camera world position from the view matrix.
// view[3] = -R^T * t  →  cam_pos = t
fn camera_world_pos(view: mat4x4<f32>) -> vec3<f32> {
    let inv_r = mat3x3<f32>(
        vec3<f32>(view[0].x, view[1].x, view[2].x),
        vec3<f32>(view[0].y, view[1].y, view[2].y),
        vec3<f32>(view[0].z, view[1].z, view[2].z),
    );
    return -(inv_r * view[3].xyz);
}

// ── Cluster index lookup ───────────────────────────────────────────────────
//
// Given a fragment's NDC position and view-space position, compute the flat
// cluster index into the 16×9×24 grid.
//
// Arguments
//   frag_coord — gl_FragCoord.xy (pixel-centre coordinates, origin bottom-left
//                in wgpu/Vulkan convention; caller must verify this matches
//                the NDC space used in cluster_build_3d.wgsl)
//   view_pos   — fragment position in view space (camera at origin, -Z forward)
//
// Returns the flat cluster index: tile_x + tile_y*16 + tile_z*144

fn world_to_cluster_idx(frag_coord: vec2<f32>, view_pos: vec3<f32>) -> u32 {
    // ── X tile: map screen X pixel to [0, TILES_X) ───────────────────────
    let tile_x_f = (frag_coord.x / cluster_params.screen_w) * f32(TILES_X);
    let tile_x   = min(u32(tile_x_f), TILES_X - 1u);

    // ── Y tile: map screen Y pixel to [0, TILES_Y) ───────────────────────
    // frag_coord.y increases downward in wgpu (Vulkan NDC), matching the
    // cluster grid's top-to-bottom row ordering.
    let tile_y_f = (frag_coord.y / cluster_params.screen_h) * f32(TILES_Y);
    let tile_y   = min(u32(tile_y_f), TILES_Y - 1u);

    // ── Z slice: exponential (log) depth partitioning ─────────────────────
    // view_pos.z is negative (camera looks down -Z); take the magnitude.
    let view_z   = -view_pos.z;
    // Clamp to [near, far] to avoid log(0) or out-of-range slices.
    let safe_z   = clamp(view_z, cluster_params.near, cluster_params.far);
    let log_near = log(cluster_params.near);
    let log_far  = log(cluster_params.far);
    let tile_z_f = (log(safe_z) - log_near) / (log_far - log_near) * f32(TILES_Z);
    let tile_z   = min(u32(tile_z_f), TILES_Z - 1u);

    // Flat index: x + y*TILES_X + z*(TILES_X*TILES_Y)
    return tile_x + tile_y * TILES_X + tile_z * (TILES_X * TILES_Y);
}

// ── Fragment entry point ───────────────────────────────────────────────────

@fragment
fn fs_main(f: FragmentInput) -> @location(0) vec4<f32> {
    // ── 1. Albedo ──────────────────────────────────────────────────────────
    var base_color: vec4<f32>;
    if material.has_albedo_tex != 0u {
        base_color = textureSample(albedo_tex, tex_sampler, f.uv);
    } else {
        base_color = material.albedo;
    }
    if base_color.a < 0.01 { discard; }

    let albedo = base_color.rgb;

    // ── 2. Surface normal ─────────────────────────────────────────────────
    var n: vec3<f32>;
    if material.has_normal_tex != 0u {
        // Decode tangent-space normal from [0,1] → [-1,1].
        let ts_normal = textureSample(normal_tex, tex_sampler, f.uv).xyz * 2.0 - 1.0;
        // TBN matrix — columns are T, B, N in world space.
        let tbn = mat3x3<f32>(
            normalize(f.tangent),
            normalize(f.bitangent),
            normalize(f.world_normal),
        );
        n = normalize(tbn * ts_normal);
    } else {
        n = normalize(f.world_normal);
    }

    // ── 3. View direction & material parameters ───────────────────────────
    let cam_pos = camera_world_pos(mesh.view);
    let v       = normalize(cam_pos - f.world_pos);

    let roughness = clamp(material.roughness, 0.04, 1.0);
    let metallic  = clamp(material.metallic,  0.0,  1.0);

    // IOR-derived F0 for dielectrics; blended toward albedo for metals.
    let ior_f0    = (material.ior - 1.0) / (material.ior + 1.0);
    let f0_scalar = ior_f0 * ior_f0;
    let f0        = mix(vec3<f32>(f0_scalar), albedo, metallic);

    // ── 4. Cluster lookup ─────────────────────────────────────────────────
    // Compute the view-space position of this fragment.
    let world_pos4 = vec4<f32>(f.world_pos, 1.0);
    let view_pos4  = mesh.view * world_pos4;
    let view_pos   = view_pos4.xyz;

    // frag_coord.xy contains pixel-centre coordinates in screen space.
    let cluster_idx = world_to_cluster_idx(f.frag_coord.xy, view_pos);

    // How many lights are in this cluster?
    let count = light_count_grid[cluster_idx];

    // ── 5. Accumulate cluster point-light contributions ───────────────────
    var lo = vec3<f32>(0.0);

    for (var i = 0u; i < min(count, MAX_LIGHTS_PER_CLUSTER); i = i + 1u) {
        // Fetch the light index stored by cluster_cull_3d.
        let li    = light_grid[cluster_idx * (MAX_LIGHTS_PER_CLUSTER + 1u) + i];
        let light = lights[li];

        // Light is stored in world space; compute per-fragment vectors.
        let l_unnorm = light.pos_radius.xyz - f.world_pos;
        let dist     = length(l_unnorm);
        let radius   = light.pos_radius.w;

        // Cull lights beyond their radius (redundant guard after cluster cull,
        // but eliminates very faint contributions cleanly).
        if dist > radius { continue; }

        let l   = l_unnorm / dist;
        let r2  = radius * radius;

        // Inverse-square with smooth windowed falloff at the radius boundary.
        let intensity = light.color_intensity.w;
        let atten = (intensity / (dist * dist + 1.0))
                  * clamp(1.0 - (dist * dist) / r2, 0.0, 1.0);
        if atten < 0.0001 { continue; }

        let radiance = light.color_intensity.xyz * atten;
        lo += pbr_cook_torrance_point(albedo, metallic, roughness, f0, n, v, l, radiance);
    }

    // ── 6. Ambient — Image-Based Lighting (split-sum) ─────────────────────
    let n_dot_v_ibl = max(dot(n, v), 0.0001);

    // Diffuse indirect: SH irradiance × albedo, attenuated for metals.
    let irradiance       = sh_irradiance(n, ibl_sh);
    let diffuse_indirect = albedo * irradiance * (1.0 - metallic);

    // Specular indirect: pre-filtered env sample + BRDF LUT (split-sum).
    let refl_dir   = reflect(-v, n);
    let refl_phi   = atan2(refl_dir.z, refl_dir.x);
    let refl_theta = asin(clamp(refl_dir.y, -1.0, 1.0));
    let env_uv     = vec2<f32>(refl_phi / (2.0 * 3.14159265) + 0.5,
                               refl_theta / 3.14159265 + 0.5);
    let max_refl_lod   = 7.0;
    let env_color      = textureSampleLevel(ibl_prefilter, ibl_sampler,
                                            env_uv, roughness * max_refl_lod).rgb;
    let brdf_uv        = vec2<f32>(n_dot_v_ibl, roughness);
    let brdf           = textureSample(ibl_brdf_lut, ibl_sampler, brdf_uv).rg;
    let specular_indirect = env_color * (f0 * brdf.x + brdf.y);

    let ambient = diffuse_indirect + specular_indirect;

    // ── 7. Emissive ────────────────────────────────────────────────────────
    let emissive = material.emissive * material.emissive_strength;

    let final_color = ambient + lo + emissive;
    return vec4<f32>(final_color, base_color.a);
}
