// pharos_render :: Postprocess — motion-blur tile-max velocity reduction.
//
// Nova3D delta port (S1-W3/W4, 2026-07-23) — source in
// nova3d assets/shaders/motion_blur_tilemax.comp @ ee410bd.
//
// Two entry points: tile-max (reduce NxN pixels → 1 tile max velocity)
// and neighbour-max (3x3 dilation of the tile buffer, per McGuire 2012).

struct TileMaxUniforms {
    screen_size: vec2<f32>,
    tile_size:   u32,
    _pad0:       u32,
};

@group(0) @binding(0) var<uniform> u: TileMaxUniforms;
@group(0) @binding(1) var velocity_in: texture_storage_2d<rg16float, read>;
@group(0) @binding(2) var tile_out:    texture_storage_2d<rg16float, write>;

@compute @workgroup_size(8, 8, 1)
fn cs_tile_max(@builtin(global_invocation_id) gid: vec3<u32>) {
    let tile = vec2<i32>(gid.xy);
    var max_vel = vec2<f32>(0.0);
    var max_len: f32 = 0.0;
    let base_x = tile.x * i32(u.tile_size);
    let base_y = tile.y * i32(u.tile_size);
    for (var y: i32 = 0; y < i32(u.tile_size); y = y + 1) {
        for (var x: i32 = 0; x < i32(u.tile_size); x = x + 1) {
            let px = vec2<i32>(base_x + x, base_y + y);
            if (px.x >= i32(u.screen_size.x) || px.y >= i32(u.screen_size.y)) {
                continue;
            }
            let v = textureLoad(velocity_in, px).rg;
            let l = dot(v, v);
            if (l > max_len) {
                max_len = l;
                max_vel = v;
            }
        }
    }
    textureStore(tile_out, tile, vec4<f32>(max_vel, 0.0, 1.0));
}

@compute @workgroup_size(8, 8, 1)
fn cs_neighbour_max(@builtin(global_invocation_id) gid: vec3<u32>) {
    let coord = vec2<i32>(gid.xy);
    var max_vel = vec2<f32>(0.0);
    var max_len: f32 = 0.0;
    for (var y: i32 = -1; y <= 1; y = y + 1) {
        for (var x: i32 = -1; x <= 1; x = x + 1) {
            let v = textureLoad(velocity_in, coord + vec2<i32>(x, y)).rg;
            let l = dot(v, v);
            if (l > max_len) {
                max_len = l;
                max_vel = v;
            }
        }
    }
    textureStore(tile_out, coord, vec4<f32>(max_vel, 0.0, 1.0));
}
