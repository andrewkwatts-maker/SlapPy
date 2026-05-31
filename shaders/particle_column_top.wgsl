// particle_column_top.wgsl
// ---------------------------------------------------------------
// Helper pass for particle_slide.wgsl. Precomputes the y-coordinate
// of the topmost solid pixel in every column of the per-pixel mask
// so each slide thread can do an O(1) lookup instead of scanning
// the column.
//
// Mirror of ParticleField._column_top (see particle_field.py):
//   col = mask[:, x, 3]
//   nz = np.flatnonzero(col)
//   return H if nz.size == 0 else int(nz[0])
//
// One thread per column. We pack the mask alpha channel into a u32
// buffer of size (H * W) — alpha[y * W + x] is 0 or non-zero. Each
// thread walks y from 0 upward looking for the first non-zero alpha
// and writes that y to column_top[x]; if none found, writes H.
//
// Layout
// ------
//   group(0) binding(0)  storage read         alpha       : array<u32>     // (H*W) packed alpha
//   group(0) binding(1)  storage read_write   column_top  : array<i32>     // (W,)
//   group(0) binding(2)  uniform              params      : Params         // (W, H)
//
// Workgroup size: 64 — matches particle_integrate / particle_slide
// for consistency. Typical world widths (256–4096) divide cleanly.
// ---------------------------------------------------------------

struct Params {
    width:   u32,
    height:  u32,
    _pad0:   u32,
    _pad1:   u32,
};

@group(0) @binding(0) var<storage, read>       alpha       : array<u32>;
@group(0) @binding(1) var<storage, read_write> column_top  : array<i32>;
@group(0) @binding(2) var<uniform>              params      : Params;

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let x = gid.x;
    if (x >= params.width) {
        return;
    }
    let W = params.width;
    let H = params.height;
    // Scan column top-down. Mirrors np.flatnonzero(col)[0].
    var top: i32 = i32(H);  // "empty column" sentinel matches CPU
    for (var y: u32 = 0u; y < H; y = y + 1u) {
        if (alpha[y * W + x] != 0u) {
            top = i32(y);
            break;
        }
    }
    column_top[x] = top;
}
