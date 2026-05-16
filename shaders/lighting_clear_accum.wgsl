// Clear the light accumulation buffer to zero before each lighting pass.
struct Params { width: u32, height: u32, _pad: vec2<u32> };
@group(0) @binding(0) var<uniform>           params : Params;
@group(0) @binding(1) var<storage,read_write> accum  : array<vec4<f32>>;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= params.width || gid.y >= params.height) { return; }
    accum[gid.y * params.width + gid.x] = vec4<f32>(0.0);
}
