// particle_detach.wgsl
// ---------------------------------------------------------------
// GPU port of the "isolated solid pixel" detach pass from
// ParticleField._drill_through (see particle_field.py — the
// "Detach isolated pixels" section at the bottom of that method).
//
// The CPU reference is a numpy 4-direction shift-and-sum: for every
// solid alpha>0 pixel, count its 4-neighbour solid pixels; if all
// four neighbours are alpha==0 the pixel is free-floating and gets
// detached (mask cleared + falling particle spawned).
//
// The CPU path scans only a small window around each drill impact;
// this GPU pass generalises to the ENTIRE mask, which lets it run as
// a periodic global "cleanup" sweep that catches dangling pixels
// produced by slumps, bake conflicts, multiple bullets, etc.
//
// What this kernel DOES
// ---------------------
//   Per pixel (one thread per pixel, 8x8 workgroups):
//     1. Read mask alpha at (x, y).
//     2. Skip if alpha == 0 OR fixed_mask[y, x] != 0.
//     3. Count solid 4-neighbours (up / down / left / right).
//     4. If count == 0: atomically reserve a slot in detach_counter,
//        then write (pos, packed colour, material id) to the SoA
//        output buffers at that slot.
//
// What this kernel does NOT do
// ----------------------------
//   * Clear the mask. The mask write is deferred to the CPU — once
//     the CPU reads back the counter + pos arrays it can vectorise
//     the mask[ys, xs, 3] = 0 with one numpy call, which is cheaper
//     than dispatching a second pass + paying another readback.
//   * Spawn the particles. spawn_batch is a Python call that grows
//     the SoA — same logic, CPU side.
//
// Bindings (storage buffer layout — packed u32 mask matches the
// established convention from particle_drill.wgsl).
// ---------------------
//   group(0) binding(0)  storage r   mask           : array<u32>  // rgba8 packed (a in MSB)
//   group(0) binding(1)  storage r   material_grid  : array<i32>  // i32 mirror of i8 grid
//   group(0) binding(2)  storage r   fixed_mask     : array<u32>  // 0/1 per pixel
//   group(0) binding(3)  storage rw  detach_counter : atomic<u32>
//   group(0) binding(4)  storage rw  detach_pos     : array<vec2<f32>>
//   group(0) binding(5)  storage rw  detach_color   : array<u32>  // rgba8 packed
//   group(0) binding(6)  storage rw  detach_mid     : array<i32>
//   group(0) binding(7)  uniform     params         : Params
//
// Determinism note
// ----------------
// Atomic counter ordering is undefined across workgroups — that's
// fine because the CPU sorts (or simply uses) the detached set as a
// SET, not a sequence. The CPU/GPU parity test sorts (y, x) before
// comparing.
// ---------------------------------------------------------------

struct Params {
    width:         u32,
    height:        u32,
    max_detach:    u32,
    fallback_mid:  i32,
};

@group(0) @binding(0) var<storage, read>       mask           : array<u32>;
@group(0) @binding(1) var<storage, read>       material_grid  : array<i32>;
@group(0) @binding(2) var<storage, read>       fixed_mask     : array<u32>;
@group(0) @binding(3) var<storage, read_write> detach_counter : atomic<u32>;
@group(0) @binding(4) var<storage, read_write> detach_pos     : array<vec2<f32>>;
@group(0) @binding(5) var<storage, read_write> detach_color   : array<u32>;
@group(0) @binding(6) var<storage, read_write> detach_mid     : array<i32>;
@group(0) @binding(7) var<uniform>             params         : Params;

fn pixel_idx(x: i32, y: i32) -> u32 {
    return u32(y) * params.width + u32(x);
}

fn in_bounds(x: i32, y: i32) -> bool {
    return x >= 0 && y >= 0 && u32(x) < params.width && u32(y) < params.height;
}

fn alpha_at(x: i32, y: i32) -> u32 {
    // Out-of-bounds reads count as 0 (empty) — same as the CPU 1-pixel
    // border treatment in _drill_through.
    if (!in_bounds(x, y)) {
        return 0u;
    }
    let p = mask[pixel_idx(x, y)];
    return (p >> 24u) & 0xFFu;
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let x = i32(gid.x);
    let y = i32(gid.y);
    if (!in_bounds(x, y)) {
        return;
    }
    let pidx = pixel_idx(x, y);
    let pix = mask[pidx];
    let a = (pix >> 24u) & 0xFFu;
    if (a == 0u) {
        return;
    }
    // Skip pixels marked fixed (terrain placed by fill_ground etc.).
    if (fixed_mask[pidx] != 0u) {
        return;
    }
    // Count solid 4-neighbours. CPU reference treats anything off the
    // 1-pixel inset border as a "skip" — but since the result there is
    // identical (border pixels have one or more out-of-bounds = 0
    // neighbours, and the original CPU window inset by 1 already
    // excludes them), we can simply count OOB as 0 and still match.
    var nb : u32 = 0u;
    nb = nb + alpha_at(x,     y - 1);
    nb = nb + alpha_at(x,     y + 1);
    nb = nb + alpha_at(x - 1, y    );
    nb = nb + alpha_at(x + 1, y    );
    if (nb != 0u) {
        return;
    }
    // CPU window inset by 1 pixel means border pixels (x==0, y==0,
    // x==W-1, y==H-1) are NOT considered — match that here so a single
    // detached pixel sitting on the canvas edge doesn't get spawned
    // by GPU but skipped by CPU.
    if (x == 0 || y == 0 || u32(x) == params.width - 1u || u32(y) == params.height - 1u) {
        return;
    }
    let slot = atomicAdd(&detach_counter, 1u);
    if (slot >= params.max_detach) {
        // Overflow — CPU clamps to max_detach. Leaving the counter
        // incremented mirrors the drill kernel's behaviour.
        return;
    }
    detach_pos[slot] = vec2<f32>(f32(x), f32(y));
    // Pack pixel rgb into the output u32. Alpha bits are stored as
    // 255 so the CPU can decode rgb identically to other paths.
    let r = pix & 0xFFu;
    let g = (pix >> 8u) & 0xFFu;
    let b = (pix >> 16u) & 0xFFu;
    detach_color[slot] = (255u << 24u) | (b << 16u) | (g << 8u) | r;
    let wm = material_grid[pidx];
    var mid_out = wm;
    if (wm < 0) {
        mid_out = params.fallback_mid;
    }
    detach_mid[slot] = mid_out;
}
