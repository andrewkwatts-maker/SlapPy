// collision_mask.wgsl — Layer 2 pixel collision detection
// The mask texture has r=entity_id (u16 packed into u32 red channel)
// This shader scans for adjacent pixels with different non-zero entity IDs

struct HitRecord {
    id_a: u32,
    id_b: u32,
    pixel_x: u32,
    pixel_y: u32,
};

struct HitBuffer {
    count: atomic<u32>,
    hits: array<HitRecord, 4096>,
};

@group(0) @binding(0) var mask_tex: texture_2d<u32>;
@group(0) @binding(1) var<storage, read_write> hit_buf: HitBuffer;
@group(0) @binding(2) var<uniform> dims: vec2<u32>;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= dims.x || gid.y >= dims.y) { return; }

    let center_id = textureLoad(mask_tex, vec2<i32>(gid.xy), 0).r;
    if (center_id == 0u) { return; }

    let offsets = array<vec2<i32>, 4>(
        vec2(1, 0), vec2(0, 1), vec2(-1, 0), vec2(0, -1)
    );

    for (var i = 0; i < 4; i++) {
        let nb = vec2<i32>(gid.xy) + offsets[i];
        if (nb.x < 0 || nb.y < 0 || nb.x >= i32(dims.x) || nb.y >= i32(dims.y)) { continue; }
        let nb_id = textureLoad(mask_tex, nb, 0).r;
        if (nb_id == 0u || nb_id == center_id) { continue; }

        // Canonicalize pair so (a < b) to avoid duplicates
        let a = min(center_id, nb_id);
        let b = max(center_id, nb_id);

        let slot = atomicAdd(&hit_buf.count, 1u);
        if (slot < 4096u) {
            hit_buf.hits[slot] = HitRecord(a, b, gid.x, gid.y);
        }
    }
}
