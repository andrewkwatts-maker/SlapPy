// pharos_render :: Postprocess — GTAO temporal reprojection.
//
// Nova3D delta port (S1-W7, 2026-07-23) — source in
// nova3d assets/shaders/gtao_temporal.comp @ d95ad1c.
//
// Ping-pong AO history buffer. Reprojects the previous frame's AO
// with the motion vector, clamps to the current frame's neighbourhood
// (±0.1) to kill ghosting, then EMA-blends against the current frame
// with a motion-speed-tightened alpha.

struct GtaoTemporalUniforms {
    screen_size:     vec2<f32>,
    temporal_alpha:  f32,
    velocity_blend:  f32,
};

@group(0) @binding(0) var<uniform> u: GtaoTemporalUniforms;
@group(0) @binding(1) var current_ao:      texture_storage_2d<rgba16float, read>;
@group(0) @binding(2) var history_ao:      texture_storage_2d<rgba16float, read>;
@group(0) @binding(3) var output_ao:       texture_storage_2d<rgba16float, write>;
@group(0) @binding(4) var motion_vectors:  texture_storage_2d<rg16float,   read>;

@compute @workgroup_size(8, 8, 1)
fn cs_main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let coord = vec2<i32>(gid.xy);
    if (coord.x >= i32(u.screen_size.x) || coord.y >= i32(u.screen_size.y)) {
        return;
    }
    let current = textureLoad(current_ao, coord);
    let velocity = textureLoad(motion_vectors, coord).rg;

    let prev_uv = (vec2<f32>(coord) + vec2<f32>(0.5)) / u.screen_size - velocity;
    let prev_coord = vec2<i32>(prev_uv * u.screen_size);
    let oob = prev_coord.x < 0 || prev_coord.y < 0 ||
              prev_coord.x >= i32(u.screen_size.x) ||
              prev_coord.y >= i32(u.screen_size.y);
    var history: vec4<f32>;
    if (oob) {
        history = current;
    } else {
        history = textureLoad(history_ao, prev_coord);
    }

    // Neighbourhood clamp to prevent ghosting.
    history.r = clamp(history.r, current.r - 0.1, current.r + 0.1);

    let speed = length(velocity);
    var alpha = u.temporal_alpha + speed * u.velocity_blend;
    alpha = clamp(alpha, 0.0, 1.0);

    let blended = mix(history, current, alpha);
    textureStore(output_ao, coord, blended);
}
