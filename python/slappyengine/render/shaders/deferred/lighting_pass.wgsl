// lighting_pass.wgsl — Nova3D pillar 2 (DDD4).
//
// Fullscreen fragment. Reads the three G-buffer targets, iterates the
// bound light array (Point / Directional / Spot), and writes an HDR
// colour to the light-accumulation attachment. The tonemap pass
// consumes that HDR image.
//
// Bindings:
//   @group(0) @binding(0) — camera UBO (view/proj/eye)
//   @group(0) @binding(1) — lights SSBO (count + array<Light, N>)
//   @group(1) @binding(0) — g_albedo             (rgba8unorm sampled)
//   @group(1) @binding(1) — g_normal_roughness   (rgba16float sampled)
//   @group(1) @binding(2) — g_position_metallic  (rgba16float sampled)
//   @group(1) @binding(3) — gbuffer sampler
//
// Fullscreen triangle trick — no vertex buffer needed. The 3-vert
// triangle covers the whole clip space; UVs derive from clip xy.

struct Camera {
    view: mat4x4<f32>,
    proj: mat4x4<f32>,
    eye:  vec4<f32>,
};

// Matches Rust `Light` in _core.deferred_cluster.
struct Light {
    // xyz = position (or direction for kind=1), w = kind (0=point,1=dir,2=spot).
    position_kind: vec4<f32>,
    // rgb = colour, a = intensity.
    color_intensity: vec4<f32>,
    // x = range, y = inner_cone_cos, z = outer_cone_cos, w = shadow_index.
    params: vec4<f32>,
    // xyz = spot_direction, w = unused.
    direction: vec4<f32>,
};

struct LightBuffer {
    count: u32,
    _pad0: u32,
    _pad1: u32,
    _pad2: u32,
    lights: array<Light, 256>,
};

@group(0) @binding(0) var<uniform> u_camera: Camera;
@group(0) @binding(1) var<uniform> u_lights: LightBuffer;

@group(1) @binding(0) var g_albedo:            texture_2d<f32>;
@group(1) @binding(1) var g_normal_roughness:  texture_2d<f32>;
@group(1) @binding(2) var g_position_metallic: texture_2d<f32>;
@group(1) @binding(3) var g_sampler:           sampler;

struct VSOut {
    @builtin(position) clip_pos: vec4<f32>,
    @location(0)       uv:       vec2<f32>,
};

// Fullscreen triangle covering NDC [-1,1] with UVs in [0,1].
@vertex
fn vs_main(@builtin(vertex_index) vid: u32) -> VSOut {
    var out: VSOut;
    let x = f32((vid << 1u) & 2u);
    let y = f32(vid & 2u);
    out.uv = vec2<f32>(x, y);
    out.clip_pos = vec4<f32>(x * 2.0 - 1.0, 1.0 - y * 2.0, 0.0, 1.0);
    return out;
}

fn decode_normal(oct: vec2<f32>) -> vec3<f32> {
    let f = oct * 2.0 - vec2<f32>(1.0);
    var n = vec3<f32>(f.x, f.y, 1.0 - abs(f.x) - abs(f.y));
    let t = max(-n.z, 0.0);
    let sx = select(t, -t, n.x < 0.0);
    let sy = select(t, -t, n.y < 0.0);
    n.x = n.x + sx;
    n.y = n.y + sy;
    return normalize(n);
}

// Trowbridge-Reitz GGX normal distribution.
fn ndf_ggx(n_dot_h: f32, roughness: f32) -> f32 {
    let a  = roughness * roughness;
    let a2 = a * a;
    let d  = (n_dot_h * n_dot_h) * (a2 - 1.0) + 1.0;
    return a2 / (3.14159265 * d * d);
}

// Schlick approximation of Fresnel.
fn fresnel_schlick(cos_theta: f32, f0: vec3<f32>) -> vec3<f32> {
    return f0 + (vec3<f32>(1.0) - f0) * pow(1.0 - cos_theta, 5.0);
}

// Smith GGX geometric shadowing (correlated form, cheap variant).
fn g_smith(n_dot_v: f32, n_dot_l: f32, roughness: f32) -> f32 {
    let k = (roughness + 1.0) * (roughness + 1.0) / 8.0;
    let gv = n_dot_v / (n_dot_v * (1.0 - k) + k);
    let gl = n_dot_l / (n_dot_l * (1.0 - k) + k);
    return gv * gl;
}

fn shade_one_light(
    L_dir: vec3<f32>,
    L_colour: vec3<f32>,
    atten: f32,
    N: vec3<f32>,
    V: vec3<f32>,
    albedo: vec3<f32>,
    metallic: f32,
    roughness: f32,
) -> vec3<f32> {
    let H = normalize(L_dir + V);
    let n_dot_l = max(dot(N, L_dir), 0.0);
    let n_dot_v = max(dot(N, V), 0.0);
    let n_dot_h = max(dot(N, H), 0.0);
    let v_dot_h = max(dot(V, H), 0.0);

    let f0 = mix(vec3<f32>(0.04), albedo, metallic);
    let f  = fresnel_schlick(v_dot_h, f0);
    let d  = ndf_ggx(n_dot_h, roughness);
    let g  = g_smith(n_dot_v, n_dot_l, roughness);

    let spec = (d * g * f) / max(4.0 * n_dot_l * n_dot_v, 1e-4);
    let kd   = (vec3<f32>(1.0) - f) * (1.0 - metallic);
    let diff = kd * albedo / 3.14159265;

    return (diff + spec) * L_colour * atten * n_dot_l;
}

@fragment
fn fs_main(in: VSOut) -> @location(0) vec4<f32> {
    let alb  = textureSample(g_albedo,            g_sampler, in.uv);
    let nr   = textureSample(g_normal_roughness,  g_sampler, in.uv);
    let pm   = textureSample(g_position_metallic, g_sampler, in.uv);

    // Sky / cleared pixels — material_mask == 0.
    if (alb.a < 0.001) {
        return vec4<f32>(alb.rgb, 1.0);
    }

    let albedo    = alb.rgb;
    let N         = decode_normal(nr.xy);
    let roughness = nr.z;
    let world_pos = pm.xyz;
    let metallic  = pm.w;
    let V         = normalize(u_camera.eye.xyz - world_pos);

    var lit = albedo * 0.03; // small constant ambient
    let n = min(u_lights.count, 256u);
    for (var i: u32 = 0u; i < n; i = i + 1u) {
        let light = u_lights.lights[i];
        let kind = light.position_kind.w;

        var L_dir: vec3<f32>;
        var atten: f32;
        if (kind < 0.5) {
            // Point light.
            let to_l = light.position_kind.xyz - world_pos;
            let d    = length(to_l);
            L_dir = to_l / max(d, 1e-4);
            let range = max(light.params.x, 1e-4);
            let falloff = clamp(1.0 - d / range, 0.0, 1.0);
            atten = falloff * falloff * light.color_intensity.a;
        } else if (kind < 1.5) {
            // Directional light — position_kind.xyz is -direction.
            L_dir = normalize(-light.position_kind.xyz);
            atten = light.color_intensity.a;
        } else {
            // Spot light.
            let to_l = light.position_kind.xyz - world_pos;
            let d    = length(to_l);
            L_dir = to_l / max(d, 1e-4);
            let spot_dir = normalize(light.direction.xyz);
            let cos_a = dot(-L_dir, spot_dir);
            let inner = light.params.y;
            let outer = light.params.z;
            let cone = clamp((cos_a - outer) / max(inner - outer, 1e-4), 0.0, 1.0);
            let range = max(light.params.x, 1e-4);
            let falloff = clamp(1.0 - d / range, 0.0, 1.0);
            atten = cone * falloff * falloff * light.color_intensity.a;
        }

        lit = lit + shade_one_light(
            L_dir,
            light.color_intensity.rgb,
            atten,
            N,
            V,
            albedo,
            metallic,
            roughness,
        );
    }

    return vec4<f32>(lit, 1.0);
}
