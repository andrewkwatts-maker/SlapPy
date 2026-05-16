// ReSTIR Pass 4: Final shading — evaluate selected light from reservoir

struct GpuLight {
    position: vec4<f32>, direction: vec4<f32>, color: vec4<f32>, params: vec4<f32>,
};
struct Reservoir {
    light_index: u32, weight_sum: f32, W: f32, M: f32,
    sample_pos: vec2<f32>, sample_n: vec2<f32>,
};
struct RestirUniforms {
    width: u32, height: u32, n_lights: u32, max_candidates: u32,
    frame_count: u32, _pad0: u32, _pad1: u32, _pad2: u32,
};

@group(0) @binding(0) var<storage, read> reservoirs: array<Reservoir>;
@group(0) @binding(1) var gbuf_pos:    texture_2d<f32>;
@group(0) @binding(2) var gbuf_normal: texture_2d<f32>;
@group(0) @binding(3) var gbuf_albedo: texture_2d<f32>;
@group(0) @binding(4) var<storage, read> lights: array<GpuLight>;
@group(0) @binding(5) var output_tex: texture_storage_2d<rgba16float, write>;
@group(0) @binding(6) var<uniform>      u:        RestirUniforms;

fn luminance(c: vec3<f32>) -> f32 { return dot(c, vec3<f32>(0.2126, 0.7152, 0.0722)); }

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= u.width || gid.y >= u.height) { return; }
    let idx = gid.y * u.width + gid.x;
    let coord = vec2<i32>(gid.xy);

    let pos    = textureLoad(gbuf_pos,    coord, 0).xyz;
    let normal = textureLoad(gbuf_normal, coord, 0).xyz;
    let albedo = textureLoad(gbuf_albedo, coord, 0).rgb;
    let res    = reservoirs[idx];

    if (res.M < 0.5 || length(normal) < 0.1 || res.light_index >= u.n_lights) {
        textureStore(output_tex, coord, vec4<f32>(0.0, 0.0, 0.0, 1.0));
        return;
    }

    let light    = lights[res.light_index];
    let to_light = light.position.xyz - pos;
    let dist     = length(to_light);
    let l_dir    = to_light / max(dist, 0.001);
    let n_dot_l  = max(0.0, dot(normalize(normal), l_dir));
    let range    = max(light.params.x, 0.001);
    let atten    = max(0.0, 1.0 - dist / range);
    let radiance = light.color.rgb * light.color.w * atten * atten;

    // Lambertian BRDF x visibility x MIS weight (W from reservoir)
    let shading = radiance * albedo * n_dot_l * res.W;

    textureStore(output_tex, coord, vec4<f32>(shading, 1.0));
}
