// gbuffer_write.wgsl — Nova3D pillar 2 (DDD4).
//
// Writes the geometry pass into three MRT colour targets + a depth
// attachment in a single draw:
//
//   @location(0) : rgba8unorm   — albedo.rgb + material_mask (a)
//   @location(1) : rgba16float  — octahedral-encoded normal.xy in .xy,
//                                 roughness in .z, unused .w = 0
//   @location(2) : rgba16float  — world position .xyz + metallic .w
//
// Vertex inputs (interleaved, stride 8*4 = 32 B):
//   @location(0) : vec3<f32> world position
//   @location(1) : vec3<f32> world normal
//   @location(2) : vec2<f32> uv
//
// The MaterialParams UBO carries the per-draw PBR constants so this same
// shader survives until DDD5 lands the material graph.

struct Camera {
    view:      mat4x4<f32>,
    proj:      mat4x4<f32>,
    eye:       vec4<f32>,
};

struct MaterialParams {
    // xyz = albedo, w = material_mask (0..1 packed as u8 on read).
    albedo_mask: vec4<f32>,
    // x = metallic, y = roughness, z = ao, w = emissive_scale.
    mrae:        vec4<f32>,
};

@group(0) @binding(0) var<uniform> u_camera:   Camera;
@group(0) @binding(1) var<uniform> u_material: MaterialParams;

struct VSOut {
    @builtin(position) clip_pos:  vec4<f32>,
    @location(0)       world_pos: vec3<f32>,
    @location(1)       world_nrm: vec3<f32>,
    @location(2)       uv:        vec2<f32>,
};

@vertex
fn vs_main(
    @location(0) in_pos: vec3<f32>,
    @location(1) in_nrm: vec3<f32>,
    @location(2) in_uv:  vec2<f32>,
) -> VSOut {
    var out: VSOut;
    let world = vec4<f32>(in_pos, 1.0);
    out.clip_pos  = u_camera.proj * (u_camera.view * world);
    out.world_pos = world.xyz;
    out.world_nrm = normalize(in_nrm);
    out.uv        = in_uv;
    return out;
}

// Octahedral encoding — packs a unit vector into 2 floats. Matches
// Nova3D's `GBuffer.hpp:encode_octahedral` byte-for-byte after the
// f16 quantise. See http://jcgt.org/published/0003/02/01/paper.pdf .
fn oct_wrap(v: vec2<f32>) -> vec2<f32> {
    let sx = select(-1.0, 1.0, v.x >= 0.0);
    let sy = select(-1.0, 1.0, v.y >= 0.0);
    return (vec2<f32>(1.0) - abs(vec2<f32>(v.y, v.x))) * vec2<f32>(sx, sy);
}

fn encode_normal(n: vec3<f32>) -> vec2<f32> {
    let nn = n / (abs(n.x) + abs(n.y) + abs(n.z));
    var xy = nn.xy;
    if (nn.z < 0.0) {
        xy = oct_wrap(xy);
    }
    return xy * 0.5 + vec2<f32>(0.5);
}

struct GBufferOut {
    @location(0) albedo:            vec4<f32>,
    @location(1) normal_roughness:  vec4<f32>,
    @location(2) position_metallic: vec4<f32>,
};

@fragment
fn fs_main(in: VSOut) -> GBufferOut {
    var out: GBufferOut;
    out.albedo = vec4<f32>(
        u_material.albedo_mask.rgb,
        u_material.albedo_mask.a,
    );
    let oct = encode_normal(normalize(in.world_nrm));
    out.normal_roughness = vec4<f32>(
        oct.x,
        oct.y,
        u_material.mrae.y,
        0.0,
    );
    out.position_metallic = vec4<f32>(
        in.world_pos,
        u_material.mrae.x,
    );
    return out;
}
