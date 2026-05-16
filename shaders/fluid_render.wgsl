// Fluid render overlay — drawn after scene combine, before final blit.
// Reads density_tex (rgba8unorm: R=density, G=temperature) and outputs
// a tinted RGBA overlay blended additively onto the lit scene.
//
// God-ray contribution: density^2 attenuation is written into god_ray_buf
// so the lighting system can pick it up for directional light scattering.
//
// Caustics: stub — compute pass not yet wired.

struct RenderParams {
    sim_w        : u32,
    sim_h        : u32,
    screen_w     : u32,
    screen_h     : u32,
    pad_x        : u32,
    pad_y        : u32,
    tint_r       : f32,
    tint_g       : f32,
    tint_b       : f32,
    alpha_scale  : f32,
    caustics_enabled : u32,
    _pad         : u32,
};

@group(0) @binding(0) var<uniform>              params       : RenderParams;
@group(0) @binding(1) var                       density_tex  : texture_storage_2d<rgba8unorm, read>;
@group(0) @binding(2) var                       scene_in     : texture_storage_2d<rgba8unorm, read>;
@group(0) @binding(3) var                       scene_out    : texture_storage_2d<rgba8unorm, write>;
@group(0) @binding(4) var<storage, read_write>  god_ray_buf  : array<f32>;
// binding 5: caustic_tex (texture_2d<f32>) — stub, sampled but not wired yet

@compute @workgroup_size(8, 8)
fn fluid_render_main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= params.screen_w || gid.y >= params.screen_h) { return; }

    // Map screen pixel → simulation pixel (offset by pad).
    let sim_x = gid.x + params.pad_x;
    let sim_y = gid.y + params.pad_y;
    let sim_coord = vec2<i32>(i32(sim_x), i32(sim_y));

    let den_sample = textureLoad(density_tex, sim_coord);
    let density     = den_sample.r;
    // let temperature = den_sample.g;  // available for future shading

    let scene_color = textureLoad(scene_in, vec2<i32>(i32(gid.x), i32(gid.y))).rgb;

    // Tint overlay: fluid color, alpha proportional to density
    let tint = vec3<f32>(params.tint_r, params.tint_g, params.tint_b);
    let alpha = clamp(density * params.alpha_scale, 0.0, 1.0);

    // Additive blend: scene + fluid tint weighted by alpha
    let out_color = scene_color + tint * alpha * 0.6;

    textureStore(scene_out, vec2<i32>(i32(gid.x), i32(gid.y)),
                 vec4<f32>(clamp(out_color, vec3<f32>(0.0), vec3<f32>(1.0)), 1.0));

    // God-ray contribution: density² attenuation written to storage buffer.
    // The lighting system reads this when building directional light bind groups.
    let screen_idx = gid.y * params.screen_w + gid.x;
    god_ray_buf[screen_idx] = density * density;

    // Caustics: stub — compute pass not yet wired.
    // if (params.caustics_enabled != 0u) { ... }
}
