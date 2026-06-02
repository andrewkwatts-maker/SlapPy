// deform_material_sample.wgsl
// Helper functions for sampling a PixelMaterialMap in deformation shaders.
// Include via: // #include "deform_material_sample.wgsl"

struct MaterialSample {
    elastic_threshold: f32,
    strength:          f32,
    repair_rate:       f32,
    flags:             u32,
};

// Flag constants
const FLAG_STRUCTURAL: u32 = 1u;
const FLAG_GLASS:      u32 = 2u;
const FLAG_ORGANIC:    u32 = 4u;
const FLAG_NO_REPAIR:  u32 = 8u;
const FLAG_ARMOR:      u32 = 16u;

fn sample_material(
    mat_tex: texture_storage_2d<rgba32float, read>,
    coord: vec2<i32>,
    threshold_min: f32,
    threshold_max: f32,
) -> MaterialSample {
    let raw = textureLoad(mat_tex, coord);
    var ms: MaterialSample;
    ms.elastic_threshold = threshold_min + raw.r * (threshold_max - threshold_min);
    ms.strength          = raw.g;
    ms.repair_rate       = raw.b;
    ms.flags             = u32(raw.a * 255.0);
    return ms;
}

fn has_flag(ms: MaterialSample, flag: u32) -> bool {
    return (ms.flags & flag) != 0u;
}

fn effective_threshold(ms: MaterialSample, base_threshold: f32) -> f32 {
    var t = ms.elastic_threshold;
    if has_flag(ms, FLAG_STRUCTURAL) { t = t * 2.0; }
    if has_flag(ms, FLAG_ARMOR)      { t = t * 4.0; }
    if has_flag(ms, FLAG_GLASS)      { t = t * 0.1; }
    return t;
}
