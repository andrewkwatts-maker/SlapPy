// mesh_frag_gbuffer.wgsl — G-buffer write pass for deferred GI (ReSTIR / SVGF)
//
// Outputs 3 render targets:
//   location(0) — gbuffer_pos    rgba32float  (world-space position XYZ, W=1)
//   location(1) — gbuffer_normal rgba32float  (world-space normal  XYZ, W=0)
//   location(2) — gbuffer_albedo rgba8unorm   (base albedo RGB, A=1)
//
// Bindings mirror mesh_frag_pbr.wgsl group(0) and group(1) — vertex shader
// (mesh_vert_3d.wgsl) is reused unchanged.
//
// Bind groups:
//   group(0) binding(0) — MeshUniforms   (same as PBR shader)
//   group(1) binding(0) — MaterialUniforms
//   group(1) binding(1) — albedo_tex     texture_2d<f32>
//   group(1) binding(2) — normal_tex     texture_2d<f32>
//   group(1) binding(3) — tex_sampler    sampler
//   group(1) binding(4) — lights         LightBuffer (not used here — kept for layout compat)

struct MeshUniforms {
    model:         mat4x4<f32>,
    view:          mat4x4<f32>,
    proj:          mat4x4<f32>,
    normal_matrix: mat4x4<f32>,
}
@group(0) @binding(0) var<uniform> mesh: MeshUniforms;

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
@group(1) @binding(0) var<uniform>       material:    MaterialUniforms;
@group(1) @binding(1) var                albedo_tex:  texture_2d<f32>;
@group(1) @binding(2) var                normal_tex:  texture_2d<f32>;
@group(1) @binding(3) var                tex_sampler: sampler;

// Vertex output (must match mesh_vert_3d.wgsl)
struct VertexOut {
    @builtin(position) clip_pos: vec4<f32>,
    @location(0)       world_pos: vec3<f32>,
    @location(1)       world_normal: vec3<f32>,
    @location(2)       uv: vec2<f32>,
    @location(3)       world_tangent: vec3<f32>,
    @location(4)       world_bitangent: vec3<f32>,
}

// G-buffer output (MRT — 3 color attachments)
struct GBufferOut {
    @location(0) position: vec4<f32>,   // world-space XYZ, W=1
    @location(1) normal:   vec4<f32>,   // world-space normal XYZ, W=0
    @location(2) albedo:   vec4<f32>,   // base color RGBA
}

@fragment
fn fs_gbuffer(in: VertexOut) -> GBufferOut {
    var out: GBufferOut;

    // ── Albedo ────────────────────────────────────────────────────────────────
    var base_color = material.albedo;
    if material.has_albedo_tex != 0u {
        base_color = textureSample(albedo_tex, tex_sampler, in.uv);
    }
    out.albedo = base_color;

    // ── World-space normal (with optional normal map) ─────────────────────────
    var n = normalize(in.world_normal);
    if material.has_normal_tex != 0u {
        let tbn = mat3x3<f32>(
            normalize(in.world_tangent),
            normalize(in.world_bitangent),
            n,
        );
        let ts_normal = textureSample(normal_tex, tex_sampler, in.uv).rgb * 2.0 - 1.0;
        n = normalize(tbn * ts_normal);
    }
    out.normal = vec4<f32>(n, 0.0);

    // ── World-space position ──────────────────────────────────────────────────
    out.position = vec4<f32>(in.world_pos, 1.0);

    return out;
}
