// Radiance Cascade: Pass 4 — Apply
// Per-pixel: sample cascade 0 probes via trilinear interpolation,
// add indirect GI contribution to the lighting accumulator.

struct ApplyUniforms {
    screen_w:  u32,
    screen_h:  u32,
    probe_w:   u32,
    probe_h:   u32,
    spacing:   f32,
    gi_scale:  f32,
    _pad0: f32, _pad1: f32,
};

@group(0) @binding(0) var cascade_tex:     texture_2d<f32>;
@group(0) @binding(1) var lighting_accum:  texture_storage_2d<rgba16float, read_write>;
@group(0) @binding(2) var<uniform>         u: ApplyUniforms;

fn sample_cascade_sh(px: f32, py: f32) -> vec4<f32> {
    // Bilinear sample from cascade SH texture
    let pw = f32(u.probe_w);
    let ph = f32(u.probe_h);
    // Map screen pixel → probe UV
    let probe_uv = vec2<f32>(px / f32(u.screen_w), py / f32(u.screen_h));
    let sh0_uv = vec2<f32>(probe_uv.x * pw * 4.0 / f32(textureDimensions(cascade_tex).x), probe_uv.y);
    let coord = vec2<i32>(i32(sh0_uv.x * f32(textureDimensions(cascade_tex).x)),
                          i32(sh0_uv.y * f32(textureDimensions(cascade_tex).y)));
    let clamped = clamp(coord, vec2<i32>(0), vec2<i32>(textureDimensions(cascade_tex)) - 1);
    return textureLoad(cascade_tex, clamped, 0);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= u.screen_w || gid.y >= u.screen_h) { return; }
    let coord = vec2<i32>(gid.xy);

    let sh = sample_cascade_sh(f32(gid.x), f32(gid.y));
    // SH L0 coefficient × 2π ≈ total irradiance
    let gi_rgb = sh.rgb * 3.14159 * u.gi_scale;

    let existing = textureLoad(lighting_accum, coord);
    textureStore(lighting_accum, coord, vec4<f32>(existing.rgb + gi_rgb, existing.a));
}
