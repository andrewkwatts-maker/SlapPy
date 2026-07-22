// pharos_render :: G-buffer pass (Nova3D VCR §5 Stage 0)
//
// Writes four screen-space material targets that the VCR pipeline
// consumes:
//   RT0: position.xyz + material_id.a       (Rgba16Float)
//   RT1: normal.xyz   + roughness.a         (Rgba16Float)
//   RT2: base_colour.rgb + metallic.a       (Rgba8UnormSrgb)
//   RT3: IoR + absorption + flags packed    (Rgba16Float)
//
// Sprint 4 skeleton — Sprint 5 lands per-material bind groups and
// texture sampling. This shader compiles + validates on the wgpu path;
// runtime behaviour is a flat clear of every RT until scene walker
// submits real geometry.

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
    @location(0) world_pos: vec3<f32>,
    @location(1) world_normal: vec3<f32>,
    @location(2) uv: vec2<f32>,
};

@vertex
fn vs_main(v: VertexIn) -> VertexOut {
    var out: VertexOut;
    // No per-mesh model matrix in Sprint 4; scene walker uploads that in Sprint 5.
    out.clip = frame.view_proj * vec4<f32>(v.position, 1.0);
    out.world_pos = v.position;
    out.world_normal = v.normal;
    out.uv = v.uv;
    return out;
}

struct FragOut {
    @location(0) pos_matid: vec4<f32>,
    @location(1) normal_rough: vec4<f32>,
    @location(2) base_metallic: vec4<f32>,
    @location(3) ior_absorb_flags: vec4<f32>,
};

// -- Sprint 1 Nova3D bug intake: degenerate TBN guard --
//
// Nova3D bug: Assimp-imported untextured meshes rendered black because
// tangent = (0,0,0). normalize((0,0,0)) is NaN, so the whole shading
// output collapsed to NaN. Guard length before constructing TBN, fall
// back to the geometric normal when the tangent basis is degenerate.
const PHAROS_TBN_EPS: f32 = 1.0e-6;

fn guarded_tbn(t_in: vec3<f32>, b_in: vec3<f32>, n_in: vec3<f32>) -> mat3x3<f32> {
    let n_geom = normalize(n_in);
    let t_len = length(t_in);
    let b_len = length(b_in);
    if (t_len > PHAROS_TBN_EPS && b_len > PHAROS_TBN_EPS) {
        return mat3x3<f32>(t_in / t_len, b_in / b_len, n_geom);
    }
    // Degenerate: reconstruct an orthonormal basis around the
    // geometric normal so downstream math stays finite.
    var up: vec3<f32> = vec3<f32>(0.0, 1.0, 0.0);
    if (abs(n_geom.y) > 0.9) { up = vec3<f32>(1.0, 0.0, 0.0); }
    let t_fallback = normalize(cross(up, n_geom));
    let b_fallback = normalize(cross(n_geom, t_fallback));
    return mat3x3<f32>(t_fallback, b_fallback, n_geom);
}

@fragment
fn fs_main(in: VertexOut) -> FragOut {
    var o: FragOut;
    o.pos_matid       = vec4<f32>(in.world_pos, 0.0);
    o.normal_rough    = vec4<f32>(normalize(in.world_normal), 0.5);
    o.base_metallic   = vec4<f32>(0.7, 0.7, 0.75, 0.0);
    o.ior_absorb_flags = vec4<f32>(1.45, 0.0, 0.0, 0.0);
    return o;
}
