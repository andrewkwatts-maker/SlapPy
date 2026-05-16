// material_dispatch.wgsl
// Workgroup: 64 threads, 1D dispatch
// Bind group 0:
//   binding 0: pixel storage buffer (array<u32>, read_write) — f32 fields accessed via bitcast
//   binding 1: material table (array<u32>, read)
//              layout per material (8 u32s / 32 bytes):
//              [r_min, r_max, g_min, g_max, b_min, b_max, material_index, _pad]
//              color ranges are 0–255 integers
//   binding 2: uniform Params
// Dispatch: ceil(pixel_count / 64) workgroups

struct Params {
    pixel_count:    u32,
    material_count: u32,
    stride:         u32,  // pixel stride in u32 units
    tag_offset:     u32,  // offset of tag field within a pixel (in u32 units)
}

@group(0) @binding(0) var<storage, read_write> pixel_buf  : array<u32>;
@group(0) @binding(1) var<storage, read>       mat_table  : array<u32>;
@group(0) @binding(2) var<uniform>             params     : Params;

@compute @workgroup_size(64, 1, 1)
fn main(@builtin(global_invocation_id) gid: vec3u) {
    let pixel_idx = gid.x;
    if pixel_idx >= params.pixel_count { return; }

    let base = pixel_idx * params.stride;

    // Read R/G/B as f32 then convert to 0–255 uint
    let r = u32(bitcast<f32>(pixel_buf[base + 0u]) * 255.0 + 0.5);
    let g = u32(bitcast<f32>(pixel_buf[base + 1u]) * 255.0 + 0.5);
    let b = u32(bitcast<f32>(pixel_buf[base + 2u]) * 255.0 + 0.5);

    // Walk material table looking for first range match
    for (var mat = 0u; mat < params.material_count; mat++) {
        let off = mat * 8u;
        let r_min = mat_table[off + 0u];
        let r_max = mat_table[off + 1u];
        let g_min = mat_table[off + 2u];
        let g_max = mat_table[off + 3u];
        let b_min = mat_table[off + 4u];
        let b_max = mat_table[off + 5u];
        let mat_idx = mat_table[off + 6u];

        if r >= r_min && r <= r_max &&
           g >= g_min && g <= g_max &&
           b >= b_min && b <= b_max {
            // Write material index into tag field (stored as f32 bit-cast from u32)
            pixel_buf[base + params.tag_offset] = bitcast<u32>(f32(mat_idx));
            return;
        }
    }
    // No match — leave tag unchanged (0 is the "untagged" sentinel; do not overwrite)
}
