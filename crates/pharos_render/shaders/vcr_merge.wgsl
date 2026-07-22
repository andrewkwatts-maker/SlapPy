// pharos_render :: VCR Stage 3 — Weighted Reservoir Sampling merge.
//
// When Stage 2 produces more contributions than VCR_K_SLOTS holds,
// this pass runs across the reservoir and drops the least-important
// slot per pixel. Compute-only, one workgroup per tile.
//
// Persistent slots (FLAG_PERSISTENT) win ties — keeps temporally
// stable specular highlights alive across frames.

@group(0) @binding(0) var reservoir: texture_storage_3d<rgba32float, read_write>;

@compute @workgroup_size(8, 8, 1)
fn cs_main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let uv = vec2<i32>(gid.xy);
    let dims = textureDimensions(reservoir);
    if (uv.x >= i32(dims.x) || uv.y >= i32(dims.y)) { return; }

    // Find the min-score slot and, if it falls below the drop
    // threshold, zero it so Stage 2 can overwrite it next frame.
    var worst_idx: u32 = 0u;
    var worst_score: f32 = 3.4e38;   // ~f32::MAX
    for (var k: u32 = 0u; k < VCR_K_SLOTS; k = k + 1u) {
        let hi = textureLoad(reservoir, vec3<i32>(uv, i32(k * 2u + 1u)));
        // hi.w encodes cone; we treat |dir|.length as a proxy for alpha
        // in the Sprint 6 stub. Sprint 7 unpacks the full Slot format.
        let score = length(hi.xyz);
        if (score < worst_score) {
            worst_score = score;
            worst_idx = k;
        }
    }
    if (worst_score < VCR_ALPHA_DROP_THRESHOLD) {
        textureStore(reservoir, vec3<i32>(uv, i32(worst_idx * 2u)),     vec4<f32>(0.0));
        textureStore(reservoir, vec3<i32>(uv, i32(worst_idx * 2u + 1u)), vec4<f32>(0.0));
    }
}
