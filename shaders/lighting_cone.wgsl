// Cone/spotlight with penumbra
struct ConeLight {
    pos_x: f32, pos_y: f32, dir_x: f32, dir_y: f32,
    half_angle: f32, outer_half_angle: f32, radius: f32,
    color_r: f32, color_g: f32, color_b: f32, intensity: f32, _pad: f32
};
struct Params { light: ConeLight, width: u32, height: u32, _pad2: vec2<f32> };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var<storage, read_write> accum: array<vec4<f32>>;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= params.width || gid.y >= params.height) { return; }
    let dx = f32(gid.x) - params.light.pos_x;
    let dy = f32(gid.y) - params.light.pos_y;
    let dist = sqrt(dx*dx + dy*dy);
    if (dist > params.light.radius || dist < 0.001) { return; }
    let pixel_dir = vec2(dx, dy) / dist;
    let light_dir = vec2(params.light.dir_x, params.light.dir_y);
    let dot_val = dot(pixel_dir, light_dir);
    let cos_inner = cos(params.light.half_angle);
    let cos_outer = cos(params.light.outer_half_angle);
    if (dot_val < cos_outer) { return; }
    let cone_factor = smoothstep(cos_outer, cos_inner, dot_val);
    let dist_factor = 1.0 - (dist / params.light.radius);
    let atten = cone_factor * dist_factor * params.light.intensity;
    let col = vec3(params.light.color_r, params.light.color_g, params.light.color_b) * atten;
    let idx = gid.y * params.width + gid.x;
    accum[idx] = accum[idx] + vec4(col, 0.0);
}
