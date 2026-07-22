// viewport_basic.wgsl — minimal Blinn-Phong shader used by the editor's
// 3D viewport panel (CCC1). Renders a shaded cube (position + normal
// interleaved vertex attributes) lit by a single point light plus a
// constant ambient term.
//
// Uniform block layout (std140-friendly, 256 bytes rounded):
//   mat4  model       (64 B)
//   mat4  view        (64 B)
//   mat4  proj        (64 B)
//   vec4  light_pos   (16 B)   // xyz = world-space position, w = intensity
//   vec4  light_color (16 B)   // xyz = RGB, w = ambient strength
//   vec4  cam_pos     (16 B)   // xyz = world-space eye
//   vec4  base_color  (16 B)   // xyz = albedo, w = specular strength

struct Uniforms {
    model:       mat4x4<f32>,
    view:        mat4x4<f32>,
    proj:        mat4x4<f32>,
    light_pos:   vec4<f32>,
    light_color: vec4<f32>,
    cam_pos:     vec4<f32>,
    base_color:  vec4<f32>,
};

@group(0) @binding(0) var<uniform> u: Uniforms;

struct VSOut {
    @builtin(position) clip_pos: vec4<f32>,
    @location(0) world_pos: vec3<f32>,
    @location(1) world_nrm: vec3<f32>,
};

@vertex
fn vs_main(
    @location(0) in_pos: vec3<f32>,
    @location(1) in_nrm: vec3<f32>,
) -> VSOut {
    var out: VSOut;
    let world = u.model * vec4<f32>(in_pos, 1.0);
    let view  = u.view  * world;
    out.clip_pos  = u.proj * view;
    out.world_pos = world.xyz;
    // For rigid model matrices (rotation + translation) the upper 3x3
    // preserves normals under multiplication, so we skip the inverse-
    // transpose. The cube's transforms only ever rotate, so this is safe.
    let n4 = u.model * vec4<f32>(in_nrm, 0.0);
    out.world_nrm = normalize(n4.xyz);
    return out;
}

@fragment
fn fs_main(in: VSOut) -> @location(0) vec4<f32> {
    let N = normalize(in.world_nrm);
    let L_dir = u.light_pos.xyz - in.world_pos;
    let L_dist = length(L_dir);
    let L = L_dir / max(L_dist, 1e-4);
    let V = normalize(u.cam_pos.xyz - in.world_pos);
    let H = normalize(L + V);

    let ambient_k = u.light_color.w;
    let intensity = u.light_pos.w;
    // Simple inverse-square with a floor so nearby lights don't blow out.
    let atten = intensity / (1.0 + L_dist * L_dist * 0.05);

    let diff = max(dot(N, L), 0.0);
    let spec = pow(max(dot(N, H), 0.0), 32.0) * u.base_color.w;

    let ambient  = u.base_color.xyz * ambient_k;
    let diffuse  = u.base_color.xyz * u.light_color.xyz * diff * atten;
    let specular = u.light_color.xyz * spec * atten;

    let col = ambient + diffuse + specular;
    return vec4<f32>(col, 1.0);
}
