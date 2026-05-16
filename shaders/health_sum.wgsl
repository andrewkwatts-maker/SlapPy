{{PIXEL_STRUCT}}

struct Params {
    pixel_count: u32,
    tag_mask: u32,      // 0 = match all
    _pad0: u32,
    _pad1: u32,
}

@group(0) @binding(0) var<storage, read>       pixels : array<PixelData>;
@group(0) @binding(1) var<uniform>             params : Params;
@group(0) @binding(2) var<storage, read_write> result : array<atomic<u32>>;
// result[0] stores the sum as a u32 (bit-cast from f32 accumulated as fixed-point ×1000)

var<workgroup> local_sum: array<f32, 64>;

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3u,
        @builtin(local_invocation_index) lid: u32) {
    let idx = gid.x;
    var val: f32 = 0.0;
    if idx < params.pixel_count {
        let p = pixels[idx];
        if params.tag_mask == 0u || (p.tag & params.tag_mask) != 0u {
            val = p.health;
        }
    }
    local_sum[lid] = val;
    workgroupBarrier();
    // Parallel reduction within workgroup
    var stride: u32 = 32u;
    loop {
        if stride == 0u { break; }
        if lid < stride {
            local_sum[lid] += local_sum[lid + stride];
        }
        workgroupBarrier();
        stride = stride >> 1u;
    }
    if lid == 0u {
        // Store sum as fixed-point ×1000 in u32 (avoids atomic float)
        let sum_fixed = u32(local_sum[0] * 1000.0);
        atomicAdd(&result[0], sum_fixed);
    }
}
