// pharos_render :: Postprocess — Depth-of-field Circle-of-Confusion.
//
// Nova3D delta port (S1-W1/W2, 2026-07-23) — HLSL/GLSL source in
// nova3d assets/shaders/dof_coc.comp @ 40b8a9a.
//
// Per-pixel CoC = |aperture * focalLength * (viewZ - focalDistance)|
//                 / (viewZ * (focalDistance - focalLength))
// written in pixels using sensor-height projection.
//
// R = CoC radius in pixels (signed: negative foreground, positive background)
// G = linear view-space depth
// BA = unused

struct DofUniforms {
    inv_projection: mat4x4<f32>,
    screen_size:    vec2<f32>,
    focal_distance: f32,
    focal_length:   f32,
    aperture:       f32,
    sensor_height:  f32,
    max_coc_pixels: f32,
    _pad0:          f32,
};

@group(0) @binding(0) var<uniform> u: DofUniforms;
@group(0) @binding(1) var depth_tex: texture_2d<f32>;
@group(0) @binding(2) var depth_smp: sampler;
@group(0) @binding(3) var coc_out:   texture_storage_2d<rgba16float, write>;

fn linearise_depth(raw: f32) -> f32 {
    let clip = vec4<f32>(0.0, 0.0, raw * 2.0 - 1.0, 1.0);
    let view = u.inv_projection * clip;
    return -view.z / view.w;
}

@compute @workgroup_size(8, 8, 1)
fn cs_main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let coord = vec2<i32>(gid.xy);
    if (coord.x >= i32(u.screen_size.x) || coord.y >= i32(u.screen_size.y)) {
        return;
    }
    let uv = (vec2<f32>(coord) + vec2<f32>(0.5)) / u.screen_size;
    let raw = textureSampleLevel(depth_tex, depth_smp, uv, 0.0).r;
    let view_z = linearise_depth(raw);

    // Thin-lens formula.
    let f  = u.focal_length;
    let fd = u.focal_distance;
    let A  = f / u.aperture;
    let d  = max(view_z, 0.001);
    let coc_metres = A * f * (d - fd) / (d * (fd - f));

    // Metres → pixels via sensor height.
    var coc_pixels = coc_metres / u.sensor_height * u.screen_size.y;
    coc_pixels = clamp(coc_pixels, -u.max_coc_pixels, u.max_coc_pixels);

    textureStore(coc_out, coord, vec4<f32>(coc_pixels, view_z, 0.0, 1.0));
}
