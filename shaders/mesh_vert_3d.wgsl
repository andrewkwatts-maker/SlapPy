// mesh_vert_3d.wgsl
// Vertex shader for opaque 3-D mesh rendering.
// Group 0: per-draw MVP uniforms (isolated from all 2D pipeline bindings).

// ── Uniform structs ────────────────────────────────────────────────────────
struct MeshUniforms {
    model:         mat4x4<f32>, // model → world
    view:          mat4x4<f32>, // world → view
    proj:          mat4x4<f32>, // view  → clip  (perspective)
    normal_matrix: mat4x4<f32>, // transpose(inverse(model)) — transforms normals
}

@group(0) @binding(0) var<uniform> uniforms: MeshUniforms;

// ── Vertex input ───────────────────────────────────────────────────────────
struct VertexInput {
    @location(0) position: vec3<f32>,
    @location(1) normal:   vec3<f32>,
    @location(2) uv:       vec2<f32>,
    @location(3) tangent:  vec4<f32>, // xyz = tangent, w = handedness (±1)
}

// ── Vertex → fragment interpolants ────────────────────────────────────────
struct VertexOutput {
    @builtin(position) clip_pos:     vec4<f32>,
    @location(0)       world_pos:    vec3<f32>,
    @location(1)       world_normal: vec3<f32>,
    @location(2)       uv:           vec2<f32>,
    @location(3)       tangent:      vec3<f32>,
    @location(4)       bitangent:    vec3<f32>,
}

// ── Entry point ────────────────────────────────────────────────────────────
@vertex
fn vs_main(v: VertexInput) -> VertexOutput {
    // World-space position.
    let world_pos4 = uniforms.model * vec4<f32>(v.position, 1.0);
    let world_pos  = world_pos4.xyz;

    // Clip-space position.
    let clip_pos = uniforms.proj * uniforms.view * world_pos4;

    // World-space normal — use the normal matrix to handle non-uniform scale.
    // Only the upper-left 3×3 of normal_matrix is meaningful; w component is 0.
    let world_normal = normalize(
        (uniforms.normal_matrix * vec4<f32>(v.normal, 0.0)).xyz
    );

    // World-space tangent — transformed the same way as normals.
    let world_tangent = normalize(
        (uniforms.normal_matrix * vec4<f32>(v.tangent.xyz, 0.0)).xyz
    );

    // Gram-Schmidt re-orthogonalise against the normal after transformation.
    let t = normalize(world_tangent - dot(world_tangent, world_normal) * world_normal);

    // Bitangent: handedness stored in tangent.w preserves mirrored UVs.
    let b = cross(world_normal, t) * v.tangent.w;

    var out: VertexOutput;
    out.clip_pos     = clip_pos;
    out.world_pos    = world_pos;
    out.world_normal = world_normal;
    out.uv           = v.uv;
    out.tangent      = t;
    out.bitangent    = b;
    return out;
}
