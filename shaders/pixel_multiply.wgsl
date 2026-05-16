{{PIXEL_STRUCT}}

struct MutateParams {
    pixel_count:    u32,
    tag_mask:       u32,
    stride_u32s:    u32,
    channel_offset: u32,
    value:          f32,     // multiplier
    filter_op:      u32,
    filter_ch_off:  u32,
    filter_value:   f32,
}

@group(0) @binding(0) var<storage, read_write> pixels : array<u32>;
@group(0) @binding(1) var<uniform>             params : MutateParams;

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3u) {
    let idx = gid.x;
    if idx >= params.pixel_count { return; }
    let base = idx * params.stride_u32s;

    var pass_filter = true;
    if params.tag_mask != 0u {
        pass_filter = (pixels[base + 6u] & params.tag_mask) != 0u;
    }
    if params.filter_op != 0u {
        let fval = bitcast<f32>(pixels[base + params.filter_ch_off]);
        if params.filter_op == 1u { pass_filter = pass_filter && (fval > params.filter_value); }
        if params.filter_op == 2u { pass_filter = pass_filter && (fval < params.filter_value); }
    }

    if pass_filter {
        let cur = bitcast<f32>(pixels[base + params.channel_offset]);
        pixels[base + params.channel_offset] = bitcast<u32>(cur * params.value);
    }
}
