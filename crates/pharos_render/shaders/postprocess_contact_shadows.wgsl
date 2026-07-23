// pharos_render :: Postprocess — screen-space contact shadows.
//
// Nova3D delta port (S1-W5, 2026-07-23) — source in
// nova3d assets/shaders/contact_shadows.comp @ f4b2fe5.
//
// Ray-marches from each visible surface toward the dominant directional
// light and tests for depth-buffer occlusion. Fades out as the light's
// angular radius grows (dusk sun etc.).

struct ContactShadowsUniforms {
    view_proj:            mat4x4<f32>,
    inv_view_proj:        mat4x4<f32>,
    light_dir_ws:         vec3<f32>,
    light_angular_radius: f32,
    screen_size:          vec2<f32>,
    max_angle_fade:       f32,
    max_steps:            u32,
    thickness:            f32,
    step_size:            f32,
    near_plane:           f32,
    far_plane:            f32,
};

@group(0) @binding(0) var<uniform> u: ContactShadowsUniforms;
@group(0) @binding(1) var depth_buffer:  texture_storage_2d<r32float, read>;
@group(0) @binding(2) var shadow_out:    texture_storage_2d<r8unorm,  write>;

fn linear_depth(raw: f32) -> f32 {
    let ndc = raw * 2.0 - 1.0;
    return 2.0 * u.near_plane * u.far_plane /
           (u.far_plane + u.near_plane - ndc * (u.far_plane - u.near_plane));
}

fn ndc_to_world(ndc: vec3<f32>) -> vec3<f32> {
    let clip = vec4<f32>(ndc, 1.0);
    let world = u.inv_view_proj * clip;
    return world.xyz / world.w;
}

@compute @workgroup_size(8, 8, 1)
fn cs_main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let coord = vec2<i32>(gid.xy);
    if (coord.x >= i32(u.screen_size.x) || coord.y >= i32(u.screen_size.y)) {
        return;
    }

    let angular_fade = 1.0 - smoothstep(0.0, u.max_angle_fade, u.light_angular_radius);
    if (angular_fade < 0.01) {
        textureStore(shadow_out, coord, vec4<f32>(1.0));
        return;
    }

    let raw = textureLoad(depth_buffer, coord).r;
    if (raw >= 1.0) {
        textureStore(shadow_out, coord, vec4<f32>(1.0));
        return;
    }

    let uv = (vec2<f32>(coord) + vec2<f32>(0.5)) / u.screen_size;
    let ndc = vec3<f32>(uv * 2.0 - 1.0, raw * 2.0 - 1.0);
    let world_pos = ndc_to_world(ndc);

    let offset_pos = world_pos + u.light_dir_ws * 0.02;
    let clip_offset = u.view_proj * vec4<f32>(offset_pos, 1.0);
    let ndc_offset = clip_offset.xyz / clip_offset.w;
    let uv_offset = ndc_offset.xy * 0.5 + vec2<f32>(0.5);
    let uv_step = normalize(uv_offset - uv) * (u.step_size / u.screen_size);

    var shadow: f32 = 1.0;
    var sample_uv = uv + uv_step;
    let start_lin = linear_depth(raw);

    for (var i: u32 = 0u; i < u.max_steps; i = i + 1u) {
        if (sample_uv.x < 0.0 || sample_uv.y < 0.0 ||
            sample_uv.x > 1.0 || sample_uv.y > 1.0) {
            break;
        }
        let sc = vec2<i32>(sample_uv * u.screen_size);
        let s_raw = textureLoad(depth_buffer, sc).r;
        let s_lin = linear_depth(s_raw);
        let t = f32(i + 1u) / f32(u.max_steps);
        let expected = start_lin + t * 5.0;
        if (s_lin < expected && (expected - s_lin) < u.thickness) {
            shadow = 0.0;
            break;
        }
        sample_uv = sample_uv + uv_step;
    }

    textureStore(shadow_out, coord, vec4<f32>(shadow * angular_fade));
}
