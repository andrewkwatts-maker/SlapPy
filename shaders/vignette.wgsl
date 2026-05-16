// vignette.wgsl — Vignette post-process pass
// Darkens pixels toward the screen edges; center is unaffected.

struct Params {
    strength: f32,
    width:    u32,
    height:   u32,
    _pad:     u32,
}

@group(0) @binding(0) var<storage, read>       in_buf : array<vec4<f32>>;
@group(0) @binding(1) var<storage, read_write> out_buf: array<vec4<f32>>;
@group(0) @binding(2) var<uniform>             params : Params;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3u) {
    let x = gid.x;
    let y = gid.y;
    if x >= params.width || y >= params.height { return; }

    let idx = y * params.width + x;
    var col = in_buf[idx];

    // UV in [0, 1] → centered offset in [-0.5, 0.5]
    let uv = vec2<f32>(f32(x) / f32(params.width), f32(y) / f32(params.height));
    let offset = uv - vec2<f32>(0.5, 0.5);

    // Distance from center: 0 at center, ~0.707 at corner
    // Normalise so dist = 1 exactly at the corner
    let dist = length(offset) / length(vec2<f32>(0.5, 0.5));

    let factor = clamp(1.0 - pow(dist * params.strength, 2.0), 0.0, 1.0);

    out_buf[idx] = vec4<f32>(col.rgb * factor, col.a);
}
