@group(1) @binding(0) var entity_tex:     texture_2d<f32>;
@group(1) @binding(1) var entity_sampler: sampler;

struct FragInput {
    @location(0) uv:      vec2<f32>,
    @location(1) opacity: f32,
}

@fragment
fn fs_main(in: FragInput) -> @location(0) vec4<f32> {
    let color = textureSample(entity_tex, entity_sampler, in.uv);
    let alpha = color.a * in.opacity;
    if alpha < 0.01 { discard; }
    return vec4<f32>(color.rgb, alpha);
}
