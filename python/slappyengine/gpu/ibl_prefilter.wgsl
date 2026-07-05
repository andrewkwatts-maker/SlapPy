// ibl_prefilter.wgsl — GGX importance-sampled cubemap prefilter (KK5)
// Extend of ibl.py — sibling shader loaded by IBLPrefilter.
//
// Runs one compute dispatch per mip level. Each texel of the output
// face is convolved with a GGX kernel whose roughness is fixed for
// the whole mip. Mip 0 is a mirror (roughness = 0); the last mip
// (default 4) is fully rough (roughness = 1).
//
// Bindings:
//   group(0) binding(0) — env_src      texture_2d<f32>       (HDR latlong)
//   group(0) binding(1) — env_samp     sampler               (linear-clamp)
//   group(0) binding(2) — mip_out      texture_storage_2d<rgba16float, write>
//   group(0) binding(3) — u            PrefilterUniforms     (uniform)

struct PrefilterUniforms {
    roughness:    f32,
    mip_level:    u32,
    face_size:    u32,
    sample_count: u32,
}

@group(0) @binding(0) var          env_src:  texture_2d<f32>;
@group(0) @binding(1) var          env_samp: sampler;
@group(0) @binding(2) var          mip_out:  texture_storage_2d<rgba16float, write>;
@group(0) @binding(3) var<uniform> u:        PrefilterUniforms;

const PI: f32 = 3.14159265358979;

// Van der Corput radical inverse — base 2, bit-reversed.
fn radical_inverse_vdc(bits_in: u32) -> f32 {
    var b = bits_in;
    b = (b << 16u) | (b >> 16u);
    b = ((b & 0x55555555u) << 1u) | ((b & 0xAAAAAAAAu) >> 1u);
    b = ((b & 0x33333333u) << 2u) | ((b & 0xCCCCCCCCu) >> 2u);
    b = ((b & 0x0F0F0F0Fu) << 4u) | ((b & 0xF0F0F0F0u) >> 4u);
    b = ((b & 0x00FF00FFu) << 8u) | ((b & 0xFF00FF00u) >> 8u);
    return f32(b) * 2.3283064365386963e-10;
}

fn hammersley(i: u32, n: u32) -> vec2<f32> {
    return vec2<f32>(f32(i) / f32(n), radical_inverse_vdc(i));
}

// GGX / Trowbridge-Reitz half-vector importance sample.
fn importance_sample_ggx(xi: vec2<f32>, roughness: f32) -> vec3<f32> {
    let a         = roughness * roughness;
    let phi       = 2.0 * PI * xi.x;
    let cos_theta = sqrt((1.0 - xi.y) / max(1.0 + (a * a - 1.0) * xi.y, 1e-6));
    let sin_theta = sqrt(max(1.0 - cos_theta * cos_theta, 0.0));
    return vec3<f32>(cos(phi) * sin_theta, sin(phi) * sin_theta, cos_theta);
}

// Build an orthonormal TBN frame from a normal vector.
fn build_tbn(normal: vec3<f32>) -> mat3x3<f32> {
    let up        = select(vec3<f32>(1.0, 0.0, 0.0),
                           vec3<f32>(0.0, 1.0, 0.0),
                           abs(normal.y) < 0.999);
    let tangent   = normalize(cross(up, normal));
    let bitangent = cross(normal, tangent);
    return mat3x3<f32>(tangent, bitangent, normal);
}

// Sample HDR equirectangular env map for a world-space direction.
fn sample_env(dir: vec3<f32>) -> vec3<f32> {
    let uv = vec2<f32>(
        atan2(dir.z, dir.x) / (2.0 * PI) + 0.5,
        asin(clamp(dir.y, -1.0, 1.0)) / PI + 0.5,
    );
    return textureSampleLevel(env_src, env_samp, uv, 0.0).rgb;
}

// Convert output-texel pixel index into a world direction on the sphere.
fn pixel_to_dir(px: vec2<u32>, size: u32) -> vec3<f32> {
    let uv    = (vec2<f32>(px) + 0.5) / f32(size);
    let phi   = uv.x * 2.0 * PI;
    let theta = (1.0 - uv.y) * PI;
    return vec3<f32>(sin(theta) * cos(phi), cos(theta), sin(theta) * sin(phi));
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= u.face_size || gid.y >= u.face_size) { return; }

    let r   = pixel_to_dir(gid.xy, u.face_size);
    let tbn = build_tbn(r);

    var prefiltered = vec3<f32>(0.0);
    var total_w     = 0.0;

    for (var i = 0u; i < u.sample_count; i++) {
        let xi      = hammersley(i, u.sample_count);
        let h_local = importance_sample_ggx(xi, u.roughness);
        let h_world = normalize(tbn * h_local);
        let l       = normalize(2.0 * dot(r, h_world) * h_world - r);
        let n_dot_l = max(dot(r, l), 0.0);
        if (n_dot_l > 0.0) {
            prefiltered += sample_env(l) * n_dot_l;
            total_w     += n_dot_l;
        }
    }

    let result = select(sample_env(r), prefiltered / total_w, total_w > 0.0);
    textureStore(mip_out, vec2<i32>(gid.xy), vec4<f32>(result, 1.0));
}
