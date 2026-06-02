// Radiance Cascade: Pass 3 — Temporal EMA blend
// Blends current cascade probe texture with history using exponential moving average.
// Reads current (storage), reads history (texture), writes EMA result to both
// current (to be consumed by apply pass) and history (for next frame).
//
// Bindings:
//   group(0) binding(0) — current_cascade   texture_storage_2d<rgba16float, read_write>
//   group(0) binding(1) — history_cascade   texture_storage_2d<rgba16float, read_write>
//   group(0) binding(2) — TemporalParams    uniform

struct TemporalParams {
    width:       u32,
    height:      u32,
    blend:       f32,  // fraction of current kept (0.05 = 5% new, 95% history)
    _pad:        f32,
}

@group(0) @binding(0) var current_cascade : texture_storage_2d<rgba16float, read_write>;
@group(0) @binding(1) var history_cascade : texture_storage_2d<rgba16float, read_write>;
@group(0) @binding(2) var<uniform>          u              : TemporalParams;

@compute @workgroup_size(8, 8)
fn temporal_main(@builtin(global_invocation_id) gid: vec3u) {
    let x = gid.x;
    let y = gid.y;
    if x >= u.width || y >= u.height { return; }
    let px = vec2i(i32(x), i32(y));

    let current = textureLoad(current_cascade, px);
    let history = textureLoad(history_cascade, px);

    // EMA: blend = fraction of current frame added
    // blend=1.0 → no history; blend=0.05 → heavy smoothing
    let blended = mix(history, current, clamp(u.blend, 0.0, 1.0));

    // Write blended result back as both current output (for apply pass)
    // and history (for next frame).
    textureStore(current_cascade, px, blended);
    textureStore(history_cascade, px, blended);
}
