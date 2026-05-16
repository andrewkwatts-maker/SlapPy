{{PIXEL_STRUCT}}

struct StatsParams {
    pixel_count: u32,
    channel_offset: u32,   // byte offset of the target channel in PixelData (÷4 for f32 index)
    tag_mask: u32,          // 0 = match all
    stride_u32s: u32,       // stride_bytes ÷ 4
    min_x: f32,
    min_y: f32,
    max_x: f32,
    max_y: f32,
    width: u32,
    _pad0: u32,
    _pad1: u32,
    _pad2: u32,
}

// Raw pixel buffer as u32 array (we read f32 fields by offset)
@group(0) @binding(0) var<storage, read>       raw_pixels : array<u32>;
@group(0) @binding(1) var<uniform>             params     : StatsParams;
@group(0) @binding(2) var<storage, read_write> out_sum    : array<atomic<u32>>;  // [0]=sum×1000
@group(0) @binding(3) var<storage, read_write> out_min    : array<atomic<u32>>;  // [0]=min as bits
@group(0) @binding(4) var<storage, read_write> out_max    : array<atomic<u32>>;  // [0]=max as bits
@group(0) @binding(5) var<storage, read_write> out_count  : array<atomic<u32>>;  // [0]=count

var<workgroup> wg_sum:   array<f32, 64>;
var<workgroup> wg_min:   array<f32, 64>;
var<workgroup> wg_max:   array<f32, 64>;
var<workgroup> wg_count: array<u32, 64>;

@compute @workgroup_size(64)
fn main(
    @builtin(global_invocation_id)   gid: vec3u,
    @builtin(local_invocation_index) lid: u32,
) {
    let idx = gid.x;
    var val:   f32 = 0.0;
    var valid: u32 = 0u;

    if idx < params.pixel_count {
        // Read tag from the raw u32 array — assumes tag field follows color (offset 4 u32s after base)
        // Tag is stored at known offset; for this shader we read via stride
        let base = idx * params.stride_u32s;
        // Read the float channel value at channel_offset (in u32 units = channel_offset_bytes ÷ 4)
        let ch_u32 = raw_pixels[base + params.channel_offset];
        let ch_val = bitcast<f32>(ch_u32);

        // Read tag — tag is at the health_module offset, which we locate by searching u32 fields
        // For simplicity: tag is always at the 6th u32 (after color vec4f=4u32, health=1u32, max_health=1u32)
        // This is computed correctly by the struct layout; params.channel_offset tells us where to look.
        // The tag field offset must be passed separately if needed; here we use the standard position.
        // Check tag mask if set
        var tag_val: u32 = 0xFFFFFFFFu;
        // tag is at base + 6 (after color[4] + health[1] + max_health[1])
        // This is approximated here — full implementation uses a dedicated tag_offset param
        if params.tag_mask != 0u {
            tag_val = raw_pixels[base + 6u];  // approximate — M4 will parameterize
        }

        if params.tag_mask == 0u || (tag_val & params.tag_mask) != 0u {
            // Optional spatial bounds check
            if params.max_x > params.min_x {
                let px_x = f32(idx % params.width);
                let px_y = f32(idx / params.width);
                if px_x >= params.min_x && px_x <= params.max_x &&
                   px_y >= params.min_y && px_y <= params.max_y {
                    val = ch_val;
                    valid = 1u;
                }
            } else {
                val = ch_val;
                valid = 1u;
            }
        }
    }

    wg_sum[lid]   = val;
    wg_min[lid]   = select(1e38, val, valid == 1u);
    wg_max[lid]   = select(-1e38, val, valid == 1u);
    wg_count[lid] = valid;
    workgroupBarrier();

    // Parallel reduction
    var s: u32 = 32u;
    loop {
        if s == 0u { break; }
        if lid < s {
            wg_sum[lid]   += wg_sum[lid + s];
            wg_min[lid]    = min(wg_min[lid], wg_min[lid + s]);
            wg_max[lid]    = max(wg_max[lid], wg_max[lid + s]);
            wg_count[lid] += wg_count[lid + s];
        }
        workgroupBarrier();
        s = s >> 1u;
    }

    if lid == 0u {
        atomicAdd(&out_sum[0],   u32(wg_sum[0] * 1000.0));
        atomicMin(&out_min[0],   bitcast<u32>(wg_min[0]));
        atomicMax(&out_max[0],   bitcast<u32>(wg_max[0]));
        atomicAdd(&out_count[0], wg_count[0]);
    }
}
