// pharos_render :: Postprocess — motion-blur scatter-as-gather pass.
//
// Nova3D delta port (S1-W3/W4, 2026-07-23) — source in
// nova3d assets/shaders/motion_blur_scatter.comp @ ee410bd.
//
// For each pixel, walks along the dominant motion vector (pixel or
// tile-max, whichever has more energy) and accumulates a shutter-open
// integration of screen-space velocity.

struct ScatterUniforms {
    screen_size:    vec2<f32>,
    num_samples:    u32,
    tile_size:      u32,
    shutter_angle:  f32,
    velocity_scale: f32,
    _pad0:          vec2<f32>,
};

@group(0) @binding(0) var<uniform> u: ScatterUniforms;
@group(0) @binding(1) var color_in:      texture_storage_2d<rgba16float, read>;
@group(0) @binding(2) var velocity_in:   texture_storage_2d<rg16float,   read>;
@group(0) @binding(3) var tile_neigh:    texture_storage_2d<rg16float,   read>;
@group(0) @binding(4) var color_out:     texture_storage_2d<rgba16float, write>;

fn hash1(co: vec2<f32>) -> f32 {
    return fract(sin(dot(co, vec2<f32>(12.9898, 78.233))) * 43758.5453);
}

@compute @workgroup_size(8, 8, 1)
fn cs_main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let coord = vec2<i32>(gid.xy);
    if (coord.x >= i32(u.screen_size.x) || coord.y >= i32(u.screen_size.y)) {
        return;
    }
    let pixel_vel = textureLoad(velocity_in, coord).rg * u.velocity_scale;
    let tile_coord = coord / i32(u.tile_size);
    let tile_vel   = textureLoad(tile_neigh, tile_coord).rg * u.velocity_scale;

    var dominant: vec2<f32>;
    if (dot(tile_vel, tile_vel) > dot(pixel_vel, pixel_vel)) {
        dominant = tile_vel;
    } else {
        dominant = pixel_vel;
    }
    dominant = dominant * u.shutter_angle;

    let speed = length(dominant);
    if (speed < 0.5) {
        textureStore(color_out, coord, textureLoad(color_in, coord));
        return;
    }

    var accum:  vec4<f32> = vec4<f32>(0.0);
    var weight: f32       = 0.0;
    let jitter = hash1(vec2<f32>(coord));

    for (var i: u32 = 0u; i < u.num_samples; i = i + 1u) {
        let t = (f32(i) + jitter) / f32(u.num_samples) - 0.5;
        var sc = coord + vec2<i32>(round(dominant * t));
        sc = clamp(sc, vec2<i32>(0), vec2<i32>(u.screen_size) - vec2<i32>(1));
        let s_col = textureLoad(color_in, sc);
        let s_vel = textureLoad(velocity_in, sc).rg * u.velocity_scale;
        let w = clamp(length(s_vel), 0.0, 1.0);
        accum  = accum  + s_col * w;
        weight = weight + w;
    }

    var result: vec4<f32>;
    if (weight > 0.0) {
        result = accum / weight;
    } else {
        result = textureLoad(color_in, coord);
    }
    textureStore(color_out, coord, result);
}
