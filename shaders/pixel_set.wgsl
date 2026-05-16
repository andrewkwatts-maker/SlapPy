{{PIXEL_STRUCT}}

struct MutateParams {
    pixel_count:    u32,
    tag_mask:       u32,     // 0 = match all
    stride_u32s:    u32,
    channel_offset: u32,     // target channel offset (in u32 units)
    value:          f32,     // value to set
    filter_op:      u32,     // 0=tag, 1=channel_gt, 2=channel_lt, 3=channel_eq (approx)
    filter_ch_off:  u32,     // filter channel offset (u32 units) for filter_op 1-3
    filter_value:   f32,     // threshold for filter_op 1-3
}

@group(0) @binding(0) var<storage, read_write> pixels : array<u32>;
@group(0) @binding(1) var<uniform>             params : MutateParams;

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3u) {
    let idx = gid.x;
    if idx >= params.pixel_count { return; }

    let base = idx * params.stride_u32s;

    // Tag filter
    var pass_filter = true;
    if params.tag_mask != 0u {
        let tag = pixels[base + 6u];
        pass_filter = pass_filter && ((tag & params.tag_mask) != 0u);
    }

    // Channel comparison filter
    if params.filter_op != 0u {
        let fval = bitcast<f32>(pixels[base + params.filter_ch_off]);
        switch params.filter_op {
            case 1u: { pass_filter = pass_filter && (fval > params.filter_value); }
            case 2u: { pass_filter = pass_filter && (fval < params.filter_value); }
            case 3u: { pass_filter = pass_filter && (abs(fval - params.filter_value) < 0.001); }
            default: {}
        }
    }

    if pass_filter {
        pixels[base + params.channel_offset] = bitcast<u32>(params.value);
    }
}
