// Point light — additive contribution to light accumulation buffer.
// Uses true 3D distance for attenuation so elevated lights (z > 0) cast correct falloff.
struct PointLightData {
    pos_x: f32, pos_y: f32, z: f32, radius: f32,
    color_r: f32, color_g: f32, color_b: f32, intensity: f32,
};
struct Params { light: PointLightData, width: u32, height: u32, _pad: vec2<u32> };
@group(0) @binding(0) var<uniform>           params : Params;
@group(0) @binding(1) var<storage,read_write> accum  : array<vec4<f32>>;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= params.width || gid.y >= params.height) { return; }
    let dx     = f32(gid.x) - params.light.pos_x;
    let dy     = f32(gid.y) - params.light.pos_y;
    let dist3d = sqrt(dx*dx + dy*dy + params.light.z * params.light.z);
    let r2     = params.light.radius * params.light.radius;
    let atten  = params.light.intensity / (1.0 + dist3d * dist3d / r2);
    if (atten < 0.001) { return; }
    let col = vec3<f32>(params.light.color_r, params.light.color_g, params.light.color_b) * atten;
    let idx = gid.y * params.width + gid.x;
    accum[idx] = accum[idx] + vec4<f32>(col, 0.0);
}
