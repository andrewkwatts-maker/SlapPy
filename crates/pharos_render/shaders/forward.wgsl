// pharos_render :: forward pass (baseline non-VCR path)
//
// Simple Lambert + view-dependent tint. This is the fallback pipeline
// used for editor preview + CI headless render tests. Sprint 6 lands
// the VCR composite pass as the default; forward stays available for
// deterministic reference renders.

struct FrameUniforms {
    view: mat4x4<f32>,
    proj: mat4x4<f32>,
    view_proj: mat4x4<f32>,
    camera_position: vec4<f32>,
};

@group(0) @binding(0) var<uniform> frame: FrameUniforms;

struct VertexIn {
    @location(0) position: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) uv: vec2<f32>,
    @location(3) tangent: vec4<f32>,
};

struct VertexOut {
    @builtin(position) clip: vec4<f32>,
    @location(0) world_normal: vec3<f32>,
    @location(1) uv: vec2<f32>,
};

@vertex
fn vs_main(v: VertexIn) -> VertexOut {
    var out: VertexOut;
    out.clip = frame.view_proj * vec4<f32>(v.position, 1.0);
    out.world_normal = v.normal;
    out.uv = v.uv;
    return out;
}

// -- Sprint 1 Nova3D bug intake: degenerate TBN guard --
//
// See gbuffer.wgsl for the full rationale. Duplicated here because
// WGSL has no import mechanism; both sites must stay in sync.
const PHAROS_TBN_EPS: f32 = 1.0e-6;

fn guarded_tbn(t_in: vec3<f32>, b_in: vec3<f32>, n_in: vec3<f32>) -> mat3x3<f32> {
    let n_geom = normalize(n_in);
    let t_len = length(t_in);
    let b_len = length(b_in);
    if (t_len > PHAROS_TBN_EPS && b_len > PHAROS_TBN_EPS) {
        return mat3x3<f32>(t_in / t_len, b_in / b_len, n_geom);
    }
    var up: vec3<f32> = vec3<f32>(0.0, 1.0, 0.0);
    if (abs(n_geom.y) > 0.9) { up = vec3<f32>(1.0, 0.0, 0.0); }
    let t_fallback = normalize(cross(up, n_geom));
    let b_fallback = normalize(cross(n_geom, t_fallback));
    return mat3x3<f32>(t_fallback, b_fallback, n_geom);
}

@fragment
fn fs_main(in: VertexOut) -> @location(0) vec4<f32> {
    let sun = normalize(vec3<f32>(0.4, 0.8, 0.4));
    let n = normalize(in.world_normal);
    let lambert = max(dot(n, sun), 0.05);
    let base = vec3<f32>(0.75, 0.7, 0.65);
    return vec4<f32>(base * lambert, 1.0);
}
