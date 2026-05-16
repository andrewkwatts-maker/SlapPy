{{PIXEL_STRUCT}}

struct BoundsParams {
    pixel_count: u32,
    tag_mask: u32,
    stride_u32s: u32,
    channel_offset: u32,   // for threshold filter (0 = use tag only)
    threshold: f32,
    use_threshold: u32,    // 1 = filter by channel > threshold; 0 = use tag_mask only
    width: u32,
    _pad: u32,
}

@group(0) @binding(0) var<storage, read>       raw_pixels : array<u32>;
@group(0) @binding(1) var<uniform>             params     : BoundsParams;
@group(0) @binding(2) var<storage, read_write> out_bounds : array<atomic<u32>>;
// out_bounds[0]=min_x [1]=min_y [2]=max_x [3]=max_y
// min stored as bit-cast f32 (initialized to large), max stored as u32

var<workgroup> wg_min_x: array<f32, 64>;
var<workgroup> wg_min_y: array<f32, 64>;
var<workgroup> wg_max_x: array<f32, 64>;
var<workgroup> wg_max_y: array<f32, 64>;

@compute @workgroup_size(64)
fn main(
    @builtin(global_invocation_id)   gid: vec3u,
    @builtin(local_invocation_index) lid: u32,
) {
    let idx = gid.x;
    var valid = false;
    var px_x = 0.0; var px_y = 0.0;

    if idx < params.pixel_count {
        let base = idx * params.stride_u32s;
        // Pixel 2D coordinates from flat index
        px_x = f32(idx % params.width);
        px_y = f32(idx / params.width);

        var pass_tag  = true;
        var pass_thr  = true;

        if params.tag_mask != 0u {
            let tag = raw_pixels[base + 6u];
            pass_tag = (tag & params.tag_mask) != 0u;
        }
        if params.use_threshold != 0u {
            let ch_val = bitcast<f32>(raw_pixels[base + params.channel_offset]);
            pass_thr = ch_val > params.threshold;
        }
        valid = pass_tag && pass_thr;
    }

    wg_min_x[lid] = select(1e38, px_x, valid);
    wg_min_y[lid] = select(1e38, px_y, valid);
    wg_max_x[lid] = select(-1e38, px_x, valid);
    wg_max_y[lid] = select(-1e38, px_y, valid);
    workgroupBarrier();

    var s: u32 = 32u;
    loop {
        if s == 0u { break; }
        if lid < s {
            wg_min_x[lid] = min(wg_min_x[lid], wg_min_x[lid + s]);
            wg_min_y[lid] = min(wg_min_y[lid], wg_min_y[lid + s]);
            wg_max_x[lid] = max(wg_max_x[lid], wg_max_x[lid + s]);
            wg_max_y[lid] = max(wg_max_y[lid], wg_max_y[lid + s]);
        }
        workgroupBarrier();
        s = s >> 1u;
    }

    if lid == 0u {
        // For min: atomicMin on u32 bit-cast works for positive floats only (IEEE property)
        atomicMin(&out_bounds[0], bitcast<u32>(wg_min_x[0]));
        atomicMin(&out_bounds[1], bitcast<u32>(wg_min_y[0]));
        atomicMax(&out_bounds[2], bitcast<u32>(wg_max_x[0]));
        atomicMax(&out_bounds[3], bitcast<u32>(wg_max_y[0]));
    }
}
