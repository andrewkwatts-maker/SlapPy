struct Params { radius: u32, width: u32, height: u32, _pad: u32, }

@group(0) @binding(0) var input_tex  : texture_2d<f32>;
@group(0) @binding(1) var output_tex : texture_storage_2d<rgba8unorm, write>;
@group(0) @binding(2) var<uniform>  params    : Params;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3u) {
    let x = i32(gid.x); let y = i32(gid.y);
    let w = i32(params.width); let h = i32(params.height);
    if x >= w || y >= h { return; }
    let r = i32(params.radius);
    var sum = vec4f(0.0);
    var count = 0.0;
    for (var dy = -r; dy <= r; dy++) {
        for (var dx = -r; dx <= r; dx++) {
            let nx = clamp(x + dx, 0, w - 1);
            let ny = clamp(y + dy, 0, h - 1);
            sum += textureLoad(input_tex, vec2i(nx, ny), 0);
            count += 1.0;
        }
    }
    textureStore(output_tex, vec2i(x, y), sum / count);
}
