// pharos_render :: Cascaded Shadow Maps sampling helper.
//
// Consumed by the forward + gbuffer fragment shaders when
// `SHADOWS_ENABLED == true` is injected via wgsl_define_block.
//
// The main render path uploads:
//   group 2, binding 0 : storage<uniform> read CsmUniforms
//   group 2, binding 1 : texture_depth_2d_array (4 cascades)
//   group 2, binding 2 : sampler_comparison
//
// Sprint 5 landing.

struct CsmCascade {
    view_proj: mat4x4<f32>,
    near: f32,
    far: f32,
    _pad: vec2<f32>,
};

struct CsmUniforms {
    cascades: array<CsmCascade, 4>,
    cascade_count: u32,
    _pad_a: vec3<f32>,
};

@group(2) @binding(0) var<uniform> csm: CsmUniforms;
@group(2) @binding(1) var shadow_map: texture_depth_2d_array;
@group(2) @binding(2) var shadow_sampler: sampler_comparison;

fn pick_cascade(view_z: f32) -> u32 {
    // Pick the smallest cascade whose slice covers view_z.
    var picked: u32 = csm.cascade_count - 1u;
    for (var i: u32 = 0u; i < csm.cascade_count; i = i + 1u) {
        if (view_z <= csm.cascades[i].far) {
            picked = i;
            break;
        }
    }
    return picked;
}

fn sample_shadow(world_pos: vec3<f32>, view_z: f32) -> f32 {
    let cascade = pick_cascade(view_z);
    let clip = csm.cascades[cascade].view_proj * vec4<f32>(world_pos, 1.0);
    let ndc = clip.xyz / clip.w;
    let uv = vec2<f32>(ndc.x * 0.5 + 0.5, -ndc.y * 0.5 + 0.5);
    // Outside cascade bounds -> lit.
    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) {
        return 1.0;
    }
    let bias = 0.0015;
    let ref_depth = ndc.z - bias;
    // 3x3 PCF for soft edges.
    var sum: f32 = 0.0;
    let texel = 1.0 / f32(textureDimensions(shadow_map).x);
    for (var dy: i32 = -1; dy <= 1; dy = dy + 1) {
        for (var dx: i32 = -1; dx <= 1; dx = dx + 1) {
            let offset = vec2<f32>(f32(dx), f32(dy)) * texel;
            sum = sum + textureSampleCompare(shadow_map, shadow_sampler, uv + offset, i32(cascade), ref_depth);
        }
    }
    return sum / 9.0;
}
