{{PIXEL_STRUCT}}

struct HistParams {
    pixel_count: u32,
    channel_offset: u32,
    tag_mask: u32,
    stride_u32s: u32,
    val_min: f32,
    val_max: f32,
    bin_count: u32,
    _pad: u32,
}

@group(0) @binding(0) var<storage, read>       raw_pixels : array<u32>;
@group(0) @binding(1) var<uniform>             params     : HistParams;
@group(0) @binding(2) var<storage, read_write> histogram  : array<atomic<u32>>;

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3u) {
    let idx = gid.x;
    if idx >= params.pixel_count { return; }
    let base = idx * params.stride_u32s;
    let ch_u32 = raw_pixels[base + params.channel_offset];
    let ch_val = bitcast<f32>(ch_u32);

    var tag_ok: bool = true;
    if params.tag_mask != 0u {
        let tag = raw_pixels[base + 6u];
        tag_ok = (tag & params.tag_mask) != 0u;
    }
    if !tag_ok { return; }

    let range = params.val_max - params.val_min;
    if range <= 0.0 { return; }
    let bin = u32(clamp(
        (ch_val - params.val_min) / range * f32(params.bin_count),
        0.0, f32(params.bin_count - 1u)
    ));
    atomicAdd(&histogram[bin], 1u);
}
