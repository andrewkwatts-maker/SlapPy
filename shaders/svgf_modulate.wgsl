// svgf_modulate.wgsl — SVGF Pass 8: Albedo modulation
// Multiplies the denoised irradiance by the albedo to reconstruct final radiance.
// output = filtered_irradiance × albedo
//
// Bindings:
//   group(0) binding(0) — filtered_color texture_2d<f32>               (denoised irradiance)
//   group(0) binding(1) — albedo_tex      texture_2d<f32>               (albedo / base colour)
//   group(0) binding(2) — output_tex      texture_storage_2d<rgba16float, write>

@group(0) @binding(0) var filtered_color: texture_2d<f32>;
@group(0) @binding(1) var albedo_tex:     texture_2d<f32>;
@group(0) @binding(2) var output_tex:     texture_storage_2d<rgba16float, write>;

// ── Kernel ────────────────────────────────────────────────────────────────────

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let dims = textureDimensions(filtered_color);
    if (gid.x >= dims.x || gid.y >= dims.y) { return; }
    let coord = vec2<i32>(gid.xy);

    let irradiance = textureLoad(filtered_color, coord, 0).rgb;
    let albedo     = textureLoad(albedo_tex,     coord, 0).rgb;
    let result     = irradiance * albedo;

    textureStore(output_tex, coord, vec4<f32>(result, 1.0));
}
