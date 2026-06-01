// mesh_frag_pbr_simple.wgsl
// Minimal Cook-Torrance PBR fragment shader for the default `MeshPipeline`
// (python/slappyengine/gpu/mesh_pipeline.py).
//
// This shader exposes ONLY the bindings the default pipeline layout provides:
//   group(0) binding(0) — MeshUniforms      (model/view/proj/normal_matrix)
//   group(1) binding(0) — MaterialUniforms  (matches PbrMaterial.to_gpu_bytes)
//
// Texture sampling, dynamic point lights, and IBL groups live in the full
// `mesh_frag_pbr.wgsl` and are consumed by the clustered/IBL pipelines.
// Demos such as `hello_3d_layer.py` and `hello_bake.py` only need flat-shaded
// PBR with a fixed key light + sky-ambient, which this shader provides.

// ── Mesh uniforms (group 0) ────────────────────────────────────────────────
struct MeshUniforms {
    model:         mat4x4<f32>,
    view:          mat4x4<f32>,
    proj:          mat4x4<f32>,
    normal_matrix: mat4x4<f32>,
}

@group(0) @binding(0) var<uniform> mesh: MeshUniforms;

// ── Material uniforms (group 1) ────────────────────────────────────────────
// GPU layout — must match PbrMaterial.to_gpu_bytes() (48 bytes):
//   vec4  albedo            (16 bytes)
//   f32   metallic          ( 4 bytes)
//   f32   roughness         ( 4 bytes)
//   f32   ior               ( 4 bytes)
//   f32   _pad0             ( 4 bytes)
//   vec3  emissive          (12 bytes)
//   f32   emissive_strength ( 4 bytes)
struct MaterialUniforms {
    albedo:            vec4<f32>,
    metallic:          f32,
    roughness:         f32,
    ior:               f32,
    _pad0:             f32,
    emissive:          vec3<f32>,
    emissive_strength: f32,
}

@group(1) @binding(0) var<uniform> material: MaterialUniforms;

// ── Fragment input (matches VertexOutput from mesh_vert_3d.wgsl) ──────────
struct FragmentInput {
    @location(0) world_pos:    vec3<f32>,
    @location(1) world_normal: vec3<f32>,
    @location(2) uv:           vec2<f32>,
    @location(3) tangent:      vec3<f32>,
    @location(4) bitangent:    vec3<f32>,
}

// ── Inlined PBR math helpers ───────────────────────────────────────────────
fn distribution_ggx(n_dot_h: f32, roughness: f32) -> f32 {
    let a     = roughness * roughness;
    let a2    = a * a;
    let denom = n_dot_h * n_dot_h * (a2 - 1.0) + 1.0;
    return a2 / (3.14159265 * denom * denom);
}

fn geometry_schlick_ggx(n_dot_v: f32, roughness: f32) -> f32 {
    let r = roughness + 1.0;
    let k = (r * r) / 8.0;
    return n_dot_v / (n_dot_v * (1.0 - k) + k);
}

fn geometry_smith(n_dot_v: f32, n_dot_l: f32, roughness: f32) -> f32 {
    return geometry_schlick_ggx(n_dot_v, roughness)
         * geometry_schlick_ggx(n_dot_l, roughness);
}

fn fresnel_schlick(cos_theta: f32, f0: vec3<f32>) -> vec3<f32> {
    let t  = clamp(1.0 - cos_theta, 0.0, 1.0);
    let t2 = t * t;
    let t5 = t2 * t2 * t;
    return f0 + (vec3<f32>(1.0) - f0) * t5;
}

fn camera_world_pos(view: mat4x4<f32>) -> vec3<f32> {
    let inv_r = mat3x3<f32>(
        vec3<f32>(view[0].x, view[1].x, view[2].x),
        vec3<f32>(view[0].y, view[1].y, view[2].y),
        vec3<f32>(view[0].z, view[1].z, view[2].z),
    );
    return -(inv_r * view[3].xyz);
}

// ── Entry point ────────────────────────────────────────────────────────────
@fragment
fn fs_main(f: FragmentInput) -> @location(0) vec4<f32> {
    let base_color = material.albedo;
    if base_color.a < 0.01 { discard; }

    let albedo    = base_color.rgb;
    let n         = normalize(f.world_normal);
    let cam_pos   = camera_world_pos(mesh.view);
    let v         = normalize(cam_pos - f.world_pos);

    let roughness = clamp(material.roughness, 0.04, 1.0);
    let metallic  = clamp(material.metallic,  0.0,  1.0);

    let ior_f0    = (material.ior - 1.0) / (material.ior + 1.0);
    let f0_scalar = ior_f0 * ior_f0;
    let f0        = mix(vec3<f32>(f0_scalar), albedo, metallic);

    // Fixed key light from above-right (simulates a sun) so meshes are shaded
    // even with no dynamic lighting context.  Matches the legacy demo look.
    let key_dir   = normalize(vec3<f32>(0.4, 0.8, 0.5));
    let key_color = vec3<f32>(1.0, 0.95, 0.85) * 1.5;

    let h       = normalize(v + key_dir);
    let n_dot_v = max(dot(n, v),       0.0001);
    let n_dot_l = max(dot(n, key_dir), 0.0);
    let n_dot_h = max(dot(n, h),       0.0);
    let h_dot_v = max(dot(h, v),       0.0);

    let ndf     = distribution_ggx(n_dot_h, roughness);
    let g       = geometry_smith(n_dot_v, n_dot_l, roughness);
    let fresnel = fresnel_schlick(h_dot_v, f0);

    let spec_num = ndf * g * fresnel;
    let specular = spec_num / (4.0 * n_dot_v * n_dot_l + 0.0001);

    let k_s  = fresnel;
    let k_d  = (vec3<f32>(1.0) - k_s) * (1.0 - metallic);
    let diff = k_d * albedo / 3.14159265;

    let lo = (diff + specular) * key_color * n_dot_l;

    // Hemispherical sky/ground ambient — cheap stand-in for IBL.
    let sky_color    = vec3<f32>(0.35, 0.40, 0.55);
    let ground_color = vec3<f32>(0.18, 0.16, 0.14);
    let hemi_t       = clamp(0.5 * (n.y + 1.0), 0.0, 1.0);
    let ambient_col  = mix(ground_color, sky_color, hemi_t);
    let ambient      = albedo * ambient_col * (1.0 - metallic * 0.5);

    let emissive = material.emissive * material.emissive_strength;

    let final_color = ambient + lo + emissive;
    return vec4<f32>(final_color, base_color.a);
}
