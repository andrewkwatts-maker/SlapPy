{{PIXEL_STRUCT}}

struct ExprParams {
    pixel_count: u32,
    tag_mask:    u32,
    stride_u32s: u32,
    target_off:  u32,   // target channel offset (u32 units)
}

@group(0) @binding(0) var<storage, read_write> pixels : array<u32>;
@group(0) @binding(1) var<uniform>             params : ExprParams;

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3u) {
    let idx = gid.x;
    if idx >= params.pixel_count { return; }
    let base = idx * params.stride_u32s;

    if params.tag_mask != 0u {
        if (pixels[base + 6u] & params.tag_mask) == 0u { return; }
    }

    // User expression injected here:
    // Each channel accessible as a local variable e.g. `let health = ...`
    // The expression result is stored back to the target channel.
    {{MUTATION_EXPR}}
}
