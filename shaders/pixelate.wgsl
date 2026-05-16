struct Params { block_size: u32, width: u32, height: u32, _pad: u32, }

@group(0) @binding(0) var input_tex  : texture_2d<f32>;
@group(0) @binding(1) var output_tex : texture_storage_2d<rgba8unorm, write>;
@group(0) @binding(2) var<uniform>  params    : Params;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3u) {
    let x = gid.x; let y = gid.y;
    if x >= params.width || y >= params.height { return; }
    let bx = (x / params.block_size) * params.block_size;
    let by = (y / params.block_size) * params.block_size;
    let color = textureLoad(input_tex, vec2i(i32(bx), i32(by)), 0);
    textureStore(output_tex, vec2i(i32(x), i32(y)), color);
}
