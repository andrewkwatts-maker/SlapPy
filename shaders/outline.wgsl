struct Params {
    outline_r: f32,
    outline_g: f32,
    outline_b: f32,
    outline_a: f32,
    threshold: f32,
    width:     u32,
    height:    u32,
    _pad:      u32,
}

@group(0) @binding(0) var<uniform> params     : Params;
@group(0) @binding(1) var          input_tex  : texture_2d<f32>;
@group(0) @binding(2) var          smp        : sampler;
@group(0) @binding(3) var          output_tex : texture_storage_2d<rgba8unorm, write>;

@compute @workgroup_size(8, 8, 1)
fn main(@builtin(global_invocation_id) gid: vec3u) {
    let x = i32(gid.x);
    let y = i32(gid.y);
    let w = i32(params.width);
    let h = i32(params.height);
    if x >= w || y >= h { return; }

    let center = textureLoad(input_tex, vec2i(x, y), 0);
    let center_alpha = center.a;

    // An edge pixel has alpha above the threshold while at least one
    // cardinal neighbour has alpha below the threshold.
    var is_edge = false;
    if center_alpha >= params.threshold {
        let offsets = array<vec2i, 4>(
            vec2i( 0, -1),
            vec2i( 0,  1),
            vec2i(-1,  0),
            vec2i( 1,  0),
        );
        for (var i = 0; i < 4; i++) {
            let nx = clamp(x + offsets[i].x, 0, w - 1);
            let ny = clamp(y + offsets[i].y, 0, h - 1);
            let neighbour_alpha = textureLoad(input_tex, vec2i(nx, ny), 0).a;
            if neighbour_alpha < params.threshold {
                is_edge = true;
                break;
            }
        }
    }

    if is_edge {
        textureStore(output_tex, vec2i(x, y),
            vec4f(params.outline_r, params.outline_g, params.outline_b, params.outline_a));
    } else {
        textureStore(output_tex, vec2i(x, y), center);
    }
}
