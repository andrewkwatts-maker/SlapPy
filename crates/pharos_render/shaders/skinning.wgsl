// pharos_render :: skeletal skinning helper.
//
// Consumed by the G-buffer + forward vertex shaders when the mesh has
// a skeleton attached. The bone palette is uploaded as a storage
// buffer at group 1, binding 0; the vertex declares 4 bone indices
// (packed u16) + 4 weights (fp32).
//
// Sprint 5 landing. Callers weave `apply_skinning(position, normal)`
// into their vertex output pipeline.

struct BonePalette {
    matrices: array<mat4x4<f32>>,
};

@group(1) @binding(0) var<storage, read> bone_palette: BonePalette;

struct SkinIn {
    bone_indices: vec4<u32>,   // 0..bone_count
    bone_weights: vec4<f32>,   // sum ~= 1.0
};

fn apply_skinning_position(position: vec3<f32>, s: SkinIn) -> vec3<f32> {
    let w = s.bone_weights;
    let m0 = bone_palette.matrices[s.bone_indices.x];
    let m1 = bone_palette.matrices[s.bone_indices.y];
    let m2 = bone_palette.matrices[s.bone_indices.z];
    let m3 = bone_palette.matrices[s.bone_indices.w];
    let blended =
        (m0 * w.x) +
        (m1 * w.y) +
        (m2 * w.z) +
        (m3 * w.w);
    return (blended * vec4<f32>(position, 1.0)).xyz;
}

fn apply_skinning_normal(normal: vec3<f32>, s: SkinIn) -> vec3<f32> {
    let w = s.bone_weights;
    let m0 = bone_palette.matrices[s.bone_indices.x];
    let m1 = bone_palette.matrices[s.bone_indices.y];
    let m2 = bone_palette.matrices[s.bone_indices.z];
    let m3 = bone_palette.matrices[s.bone_indices.w];
    // Normal deform: ignore translation column.
    let blended3 = mat3x3<f32>(
        m0[0].xyz * w.x + m1[0].xyz * w.y + m2[0].xyz * w.z + m3[0].xyz * w.w,
        m0[1].xyz * w.x + m1[1].xyz * w.y + m2[1].xyz * w.z + m3[1].xyz * w.w,
        m0[2].xyz * w.x + m1[2].xyz * w.y + m2[2].xyz * w.z + m3[2].xyz * w.w,
    );
    return normalize(blended3 * normal);
}
