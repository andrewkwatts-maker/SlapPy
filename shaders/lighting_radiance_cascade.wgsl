// Radiance Cascade GI — 2D probe grid for indirect lighting
// Learned from Nova3D RadianceCascade.hpp — adapted for 2D flat lighting
//
// Each cascade level has probes spaced 2^k pixels apart.
// Cascade 0: 8px spacing, 64 rays/probe
// Cascade 1: 16px spacing, 32 rays/probe
// Cascade 2: 32px spacing, 16 rays/probe
// Cascade 3: 64px spacing, 8 rays/probe
//
// Merge pass: cascade k+1 fills in cascade k where rays find nothing

struct CascadeUniforms {
    screen_size: vec2<u32>,
    cascade_level: u32,
    probe_spacing: u32,      // 8 << cascade_level
    rays_per_probe: u32,     // 64 >> cascade_level
    max_ray_length: f32,
    _pad: vec2<u32>,
}

@group(0) @binding(0) var<uniform> u: CascadeUniforms;
@group(0) @binding(1) var scene_tex: texture_2d<f32>;     // scene color (emission source)
@group(0) @binding(2) var probe_tex: texture_storage_2d<rgba16float, read_write>; // probe radiance
@group(0) @binding(3) var upper_tex: texture_2d<f32>;     // upper cascade (for merge)

const PI = 3.14159265358979;
const TWO_PI = 6.28318530717959;

// Pass 1: Trace rays from each probe
@compute @workgroup_size(8, 8, 1)
fn trace_probes(@builtin(global_invocation_id) gid: vec3<u32>) {
    // gid.xy = probe index at this cascade level
    let probe_world = vec2<f32>(gid.xy) * f32(u.probe_spacing) + f32(u.probe_spacing) * 0.5;
    let screen = vec2<i32>(u.screen_size);

    var radiance = vec3<f32>(0.0);
    let angle_step = TWO_PI / f32(u.rays_per_probe);

    for (var r = 0u; r < u.rays_per_probe; r++) {
        let angle = f32(r) * angle_step;
        let ray_dir = vec2<f32>(cos(angle), sin(angle));

        // March ray through scene
        var hit_color = vec3<f32>(0.0);
        for (var t = 1.0; t < u.max_ray_length; t += 1.5) {
            let sample_pos = probe_world + ray_dir * t;
            let px = vec2<i32>(sample_pos);
            if px.x < 0 || px.y < 0 || px.x >= screen.x || px.y >= screen.y { break; }

            let scene_color = textureLoad(scene_tex, px, 0).rgb;
            // If pixel is bright (emissive), it's a light source
            let luminance = dot(scene_color, vec3<f32>(0.299, 0.587, 0.114));
            if luminance > 0.8 {
                hit_color = scene_color;
                break;
            }
        }
        radiance += hit_color;
    }
    radiance /= f32(u.rays_per_probe);

    textureStore(probe_tex, vec2<i32>(gid.xy), vec4<f32>(radiance, 1.0));
}

// Pass 2: Merge upper cascade into lower (bilinear probe lookup)
@compute @workgroup_size(8, 8, 1)
fn merge_cascade(@builtin(global_invocation_id) gid: vec3<u32>) {
    let probe_idx = vec2<i32>(gid.xy);
    let self_radiance = textureLoad(probe_tex, probe_idx).rgb;

    // Sample upper cascade at corresponding position (half the probes)
    let upper_idx = vec2<f32>(probe_idx) * 0.5;
    let upper_size = vec2<f32>(textureDimensions(upper_tex));
    let upper_uv = (upper_idx + 0.5) / upper_size;
    let upper_radiance = textureSampleLevel(upper_tex,
        // Use a sampler — simplified: just nearest
        vec2<f32>(upper_idx) / upper_size, 0.0).rgb;

    // Blend: if self ray hit nothing, use upper cascade
    let blended = mix(upper_radiance, self_radiance,
                      step(0.001, length(self_radiance)));
    textureStore(probe_tex, probe_idx, vec4<f32>(blended, 1.0));
}

// Pass 3: Apply cascade 0 radiance to scene pixels (bilinear probe lookup)
@group(0) @binding(4) var accum_tex: texture_storage_2d<rgba16float, read_write>;

@compute @workgroup_size(8, 8, 1)
fn apply_gi(@builtin(global_invocation_id) gid: vec3<u32>) {
    let px = vec2<i32>(gid.xy);
    let screen = vec2<u32>(u.screen_size);
    if u32(px.x) >= screen.x || u32(px.y) >= screen.y { return; }

    // Bilinear sample from probe grid
    let probe_pos = vec2<f32>(px) / f32(u.probe_spacing);
    let probe_f = floor(probe_pos);
    let probe_frac = probe_pos - probe_f;

    let probe_size = vec2<i32>(textureDimensions(probe_tex));
    let p00 = clamp(vec2<i32>(probe_f), vec2<i32>(0), probe_size - 1);
    let p11 = clamp(p00 + vec2<i32>(1), vec2<i32>(0), probe_size - 1);
    let p10 = vec2<i32>(p11.x, p00.y);
    let p01 = vec2<i32>(p00.x, p11.y);

    let gi = mix(
        mix(textureLoad(probe_tex, p00).rgb, textureLoad(probe_tex, p10).rgb, probe_frac.x),
        mix(textureLoad(probe_tex, p01).rgb, textureLoad(probe_tex, p11).rgb, probe_frac.x),
        probe_frac.y
    );

    let prev = textureLoad(accum_tex, px);
    textureStore(accum_tex, px, vec4<f32>(prev.rgb + gi * 0.3, prev.a));
}
