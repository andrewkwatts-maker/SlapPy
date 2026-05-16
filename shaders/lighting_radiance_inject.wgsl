// Radiance Cascade: Pass 1 — Inject
// For each probe at cascade level L, shoot N rays in 2D hemisphere,
// accumulate incoming radiance from scene texture, store as SH L1 (4 floats).
// Probe grid stored as (probe_w×4) × probe_h rgba16float texture.
// SH L1 basis: Y0=constant, Yx=x-oriented, Yy=y-oriented, Yz=z-oriented

struct CascadeUniforms {
    screen_w:   f32,
    screen_h:   f32,
    probe_w:    f32,
    probe_h:    f32,
    spacing:    f32,  // pixels per probe
    n_rays:     f32,
    level:      f32,
    _pad:       f32,
};

@group(0) @binding(0) var scene_tex:  texture_2d<f32>;
@group(0) @binding(1) var probe_tex:  texture_storage_2d<rgba16float, write>;
@group(0) @binding(2) var<uniform>   u: CascadeUniforms;

const PI: f32 = 3.14159265358979;
const TWO_PI: f32 = 6.28318530718;

// SH L1 basis evaluated at direction (dx, dy, dz)
fn sh_basis(d: vec3<f32>) -> vec4<f32> {
    return vec4<f32>(
        0.282095,         // Y0,0
        0.488603 * d.y,   // Y1,-1
        0.488603 * d.z,   // Y1,0
        0.488603 * d.x,   // Y1,1
    );
}

fn wang_hash(seed: u32) -> u32 {
    var s = seed;
    s = (s ^ 61u) ^ (s >> 16u);
    s = s * 9u;
    s = s ^ (s >> 4u);
    s = s * 0x27d4eb2du;
    return s ^ (s >> 15u);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let pw = u32(u.probe_w);
    let ph = u32(u.probe_h);
    if (gid.x >= pw || gid.y >= ph) { return; }

    // Probe world-space center (screen pixels)
    let probe_cx = (f32(gid.x) + 0.5) * u.spacing;
    let probe_cy = (f32(gid.y) + 0.5) * u.spacing;

    let n_rays = u32(u.n_rays);
    var sh = vec4<f32>(0.0);
    var w_total = 0.0;

    for (var i = 0u; i < n_rays; i++) {
        // Stratified angle sampling
        let angle = (f32(i) + 0.5) / f32(n_rays) * TWO_PI;
        // Jitter
        let jitter_hash = wang_hash(gid.x * 1000u + gid.y * 7u + i * 13u + u32(u.level) * 99991u);
        let jitter = (f32(jitter_hash & 0xFFFFu) / 65535.0 - 0.5) / f32(n_rays) * TWO_PI;
        let a = angle + jitter;

        let dx = cos(a);
        let dy = sin(a);
        let dir = vec3<f32>(dx, dy, 0.0);

        // March ray to find radiance
        var radiance = vec3<f32>(0.0);
        let max_steps = 64u;
        let step_size = u.spacing * 0.5;

        for (var step = 1u; step <= max_steps; step++) {
            let t = f32(step) * step_size;
            let sx = probe_cx + dx * t;
            let sy = probe_cy + dy * t;
            if (sx < 0.0 || sy < 0.0 || sx >= u.screen_w || sy >= u.screen_h) {
                break;
            }
            let coord = vec2<i32>(i32(sx), i32(sy));
            let sample = textureLoad(scene_tex, coord, 0);
            // Use alpha as emission mask: emissive pixels have high alpha or high luminance
            let lum = dot(sample.rgb, vec3<f32>(0.2126, 0.7152, 0.0722));
            if (lum > 0.5 || sample.a > 0.9) {
                radiance = sample.rgb;
                break;
            }
        }

        // Accumulate SH coefficients
        let weight = 1.0 / f32(n_rays);
        sh += sh_basis(dir) * (radiance.x + radiance.y + radiance.z) / 3.0 * weight;
        w_total += weight;
    }

    // Write 4 SH coefficients side by side (probe_w*4 wide texture)
    let base_x = i32(gid.x) * 4;
    let py = i32(gid.y);
    textureStore(probe_tex, vec2<i32>(base_x + 0, py), vec4<f32>(sh.x, sh.x, sh.x, 1.0));
    textureStore(probe_tex, vec2<i32>(base_x + 1, py), vec4<f32>(sh.y, sh.y, sh.y, 1.0));
    textureStore(probe_tex, vec2<i32>(base_x + 2, py), vec4<f32>(sh.z, sh.z, sh.z, 1.0));
    textureStore(probe_tex, vec2<i32>(base_x + 3, py), vec4<f32>(sh.w, sh.w, sh.w, 1.0));
}
