// pharos_render :: VCR Stage 5 (optional) — Temporal reuse.
//
// Reprojects last frame's reservoir through motion vectors with a
// bilateral depth-discontinuity filter. Slots flagged Persistent
// survive Stage 3's WRS drop, keeping specular highlights temporally
// stable.
//
// Nova3D §5 Stage 5. Skipped when VCR_TEMPORAL_ENABLED == false.

@group(0) @binding(0) var reservoir_prev: texture_storage_3d<rgba32float, read>;
@group(0) @binding(1) var reservoir_curr: texture_storage_3d<rgba32float, read_write>;
@group(0) @binding(2) var motion_vector:  texture_2d<f32>;
@group(0) @binding(3) var depth_curr:     texture_depth_2d;
@group(0) @binding(4) var depth_prev:     texture_depth_2d;

const DEPTH_TOLERANCE: f32 = 0.005;

@compute @workgroup_size(8, 8, 1)
fn cs_main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (!VCR_TEMPORAL_ENABLED) { return; }

    let uv = vec2<i32>(gid.xy);
    let dims = textureDimensions(reservoir_curr);
    if (uv.x >= i32(dims.x) || uv.y >= i32(dims.y)) { return; }

    let mv = textureLoad(motion_vector, uv, 0).xy;
    let prev_uv = vec2<i32>(vec2<f32>(uv) + mv);
    if (prev_uv.x < 0 || prev_uv.y < 0 || prev_uv.x >= i32(dims.x) || prev_uv.y >= i32(dims.y)) { return; }

    // Bilateral test: only reproject if depth continuity holds.
    let d_curr = textureLoad(depth_curr, uv, 0);
    let d_prev = textureLoad(depth_prev, prev_uv, 0);
    if (abs(d_curr - d_prev) > DEPTH_TOLERANCE) { return; }

    // Copy each slot from previous to current if the current slot is
    // empty (score < threshold). Persistent slots get priority.
    for (var k: u32 = 0u; k < VCR_K_SLOTS; k = k + 1u) {
        let prev_lo = textureLoad(reservoir_prev, vec3<i32>(prev_uv, i32(k * 2u)));
        let prev_hi = textureLoad(reservoir_prev, vec3<i32>(prev_uv, i32(k * 2u + 1u)));
        let curr_hi = textureLoad(reservoir_curr, vec3<i32>(uv,      i32(k * 2u + 1u)));
        if (length(curr_hi.xyz) < 0.01 && length(prev_hi.xyz) > 0.01) {
            textureStore(reservoir_curr, vec3<i32>(uv, i32(k * 2u)),     prev_lo);
            textureStore(reservoir_curr, vec3<i32>(uv, i32(k * 2u + 1u)), prev_hi);
        }
    }
}
