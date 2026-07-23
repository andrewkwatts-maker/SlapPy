// pharos_render :: Postprocess — TAA resolve.
//
// Nova3D delta port (S1-W8, 2026-07-23) — source in
// nova3d engine/graphics/TAA.cpp @ fbf134c (Halton(2,3) jitter + resolve).
//
// Fullscreen resolve pass. Reprojects the previous frame's colour
// with a motion vector, clamps to the current pixel's neighbourhood
// (3x3 min/max box, per Karis / INSIDE), and blends with a fixed
// temporal alpha. Halton-jittered sub-pixel sample lives on the CPU
// (see postprocess::taa::halton23).

struct TaaUniforms {
    screen_size:      vec2<f32>,
    temporal_alpha:   f32,
    velocity_reject:  f32,
};

@group(0) @binding(0) var<uniform> u: TaaUniforms;
@group(0) @binding(1) var current_color: texture_storage_2d<rgba16float, read>;
@group(0) @binding(2) var history_color: texture_storage_2d<rgba16float, read>;
@group(0) @binding(3) var motion_vec:    texture_storage_2d<rg16float,   read>;
@group(0) @binding(4) var output_color:  texture_storage_2d<rgba16float, write>;

fn rgb_to_ycocg(rgb: vec3<f32>) -> vec3<f32> {
    let y  =  0.25 * rgb.r + 0.5 * rgb.g + 0.25 * rgb.b;
    let co =  0.5  * rgb.r              - 0.5  * rgb.b;
    let cg = -0.25 * rgb.r + 0.5 * rgb.g - 0.25 * rgb.b;
    return vec3<f32>(y, co, cg);
}

fn ycocg_to_rgb(ycocg: vec3<f32>) -> vec3<f32> {
    let r = ycocg.x + ycocg.y - ycocg.z;
    let g = ycocg.x           + ycocg.z;
    let b = ycocg.x - ycocg.y - ycocg.z;
    return vec3<f32>(r, g, b);
}

@compute @workgroup_size(8, 8, 1)
fn cs_main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let coord = vec2<i32>(gid.xy);
    if (coord.x >= i32(u.screen_size.x) || coord.y >= i32(u.screen_size.y)) {
        return;
    }

    // Current pixel + 3x3 neighbourhood in YCoCg.
    var min_c = vec3<f32>( 1e6);
    var max_c = vec3<f32>(-1e6);
    var current = vec3<f32>(0.0);
    for (var y: i32 = -1; y <= 1; y = y + 1) {
        for (var x: i32 = -1; x <= 1; x = x + 1) {
            let s = textureLoad(current_color, coord + vec2<i32>(x, y)).rgb;
            let yc = rgb_to_ycocg(s);
            min_c = min(min_c, yc);
            max_c = max(max_c, yc);
            if (x == 0 && y == 0) {
                current = yc;
            }
        }
    }

    let velocity = textureLoad(motion_vec, coord).rg;
    let prev_uv  = (vec2<f32>(coord) + vec2<f32>(0.5)) / u.screen_size - velocity;
    let prev_coord = vec2<i32>(prev_uv * u.screen_size);
    let oob = prev_coord.x < 0 || prev_coord.y < 0 ||
              prev_coord.x >= i32(u.screen_size.x) ||
              prev_coord.y >= i32(u.screen_size.y);

    var history_ycocg: vec3<f32>;
    if (oob) {
        history_ycocg = current;
    } else {
        history_ycocg = rgb_to_ycocg(textureLoad(history_color, prev_coord).rgb);
    }

    // Neighbourhood clip.
    history_ycocg = clamp(history_ycocg, min_c, max_c);

    // Motion-tightened alpha: fast motion → mostly current.
    let speed = length(velocity);
    let reject = smoothstep(0.0, u.velocity_reject, speed);
    let alpha  = mix(u.temporal_alpha, 1.0, reject);

    let blended_ycocg = mix(history_ycocg, current, alpha);
    let rgb = ycocg_to_rgb(blended_ycocg);
    textureStore(output_color, coord, vec4<f32>(rgb, 1.0));
}
