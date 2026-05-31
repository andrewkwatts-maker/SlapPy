// particle_bake.wgsl
// ---------------------------------------------------------------
// GPU port of ParticleField's settle bake call site — the
// polygon-shape branch of bake_settled_particles (see
// physics/baked_terrain.py and ParticleField.step around the
// shape_masks build).
//
// Per particle this kernel does what the CPU loop in
// bake_settled_particles does for the polygon path:
//
//   1. Skip unless (phase == SETTLING && bake_flag == 0).
//   2. Look up the precomputed shape mask in the atlas using
//      (shape_global_idx, scale_bin, rotation_bin) → AtlasEntry
//      (offset/width/height). Atlas is built CPU-side once per
//      shape × scale × rotation combination.
//   3. For each pixel in the mask: compute world (nx, ny), if
//      mask bit is set write packed RGBA into mask_out,
//      material_id into material_grid_out, 1 into loose_out.
//   4. Set bake_flag[i] = 1 so the next frame's tick skips it.
//
// Atlas layout
// ------------
// Shapes-from-all-materials are flattened to a global shape index.
// Per (shape_global_idx, scale_bin, rotation_bin) tuple we keep one
// AtlasEntry record:
//
//     offset_px : u32   // start offset into shape_atlas (flat u32 array)
//     width     : u32   // mask width  (px)
//     height    : u32   // mask height (px)
//     _pad      : u32
//
// Total entries = N_SHAPES * N_SCALES * N_ROTATIONS. The Python
// builder picks SCALE_BIN = clamp(bake_radius+1, 1, MAX_SCALE) and
// ROT_BIN = (int)floor(rotation / (2π) * N_ROTATIONS) % N_ROTATIONS.
//
// Splat
// -----
// Non-uniform scale (splat_squash > 0 || splat_stretch > 0) is NOT
// supported here — Sprint 4. Particles whose material has splat
// remain on the CPU path (the caller filters them out).
//
// Race ordering
// -------------
// Two particles whose polygons overlap can stamp the same pixel.
// WGSL plain storage-buffer writes are last-write-wins with
// undefined ordering across workgroups — matches the CPU's
// iteration-order non-determinism (the python loop is "for i in
// nonzero(to_bake)[0]" which is also write-order dependent when
// stamps overlap). Tolerance test in
// tests/test_particle_field_gpu_parity.py allows ~5% pixel diff.
//
// Layout
// ------
//   group(0) binding(0)  storage read         pos                : array<vec2<f32>>
//   group(0) binding(1)  storage read         phase              : array<i32>
//   group(0) binding(2)  storage read_write   bake_flag          : array<u32>
//   group(0) binding(3)  storage read         color              : array<u32>   // packed rgba8
//   group(0) binding(4)  storage read         material_id        : array<i32>
//   group(0) binding(5)  storage read         shape_atlas_idx    : array<i32>   // per-particle entry id
//   group(0) binding(6)  storage read         shape_atlas        : array<u32>   // 1 byte per mask px, packed as u32
//   group(0) binding(7)  storage read         shape_atlas_meta   : array<vec4<u32>>  // (offset, width, height, _pad)
//   group(0) binding(8)  storage read_write   mask_out           : array<u32>   // (H*W) packed rgba8
//   group(0) binding(9)  storage read_write   material_grid_out  : array<i32>   // (H*W)
//   group(0) binding(10) storage read_write   loose_out          : array<u32>   // (H*W) 0/1
//   group(0) binding(11) uniform              params             : Params
//
// Workgroup size: 64. Matches collide / thermal / kinetic_relax for
// SIMD-friendly occupancy.
// ---------------------------------------------------------------

struct Params {
    n_particles : u32,
    width       : u32,
    height      : u32,
    n_entries   : u32,
};

@group(0) @binding(0)  var<storage, read>       pos               : array<vec2<f32>>;
@group(0) @binding(1)  var<storage, read>       phase             : array<i32>;
@group(0) @binding(2)  var<storage, read_write> bake_flag         : array<u32>;
@group(0) @binding(3)  var<storage, read>       color             : array<u32>;
@group(0) @binding(4)  var<storage, read>       material_id       : array<i32>;
@group(0) @binding(5)  var<storage, read>       shape_atlas_idx   : array<i32>;
@group(0) @binding(6)  var<storage, read>       shape_atlas       : array<u32>;
@group(0) @binding(7)  var<storage, read>       shape_atlas_meta  : array<vec4<u32>>;
@group(0) @binding(8)  var<storage, read_write> mask_out          : array<u32>;
@group(0) @binding(9)  var<storage, read_write> material_grid_out : array<i32>;
@group(0) @binding(10) var<storage, read_write> loose_out         : array<u32>;
@group(0) @binding(11) var<uniform>             params            : Params;

const PHASE_SETTLING : i32 = 2;

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = gid.x;
    if (i >= params.n_particles) {
        return;
    }

    // Gate: only particles whose phase is SETTLING and which haven't
    // baked yet. Matches the CPU mask
    //   to_bake = settled & landed & ~bake_flag
    // (settled <=> phase >= SETTLING; LANDED is implied because
    // phase progresses LANDED -> SETTLING in _slide, so SETTLING
    // particles have already been landed).
    if (phase[i] != PHASE_SETTLING) {
        return;
    }
    if (bake_flag[i] != 0u) {
        return;
    }

    // Entry lookup. -1 => particle has no shape registered (e.g. a
    // material with fragment_family=None). Skip — the CPU path falls
    // back to a 1-pixel stamp for these, but Sprint 3's GPU port is
    // polygon-only.
    let entry_id = shape_atlas_idx[i];
    if (entry_id < 0) {
        return;
    }
    let e = u32(entry_id);
    if (e >= params.n_entries) {
        return;
    }

    let meta_e = shape_atlas_meta[e];
    let offset = meta_e.x;
    let mw     = meta_e.y;
    let mh     = meta_e.z;
    if (mw == 0u || mh == 0u) {
        return;
    }

    let W = i32(params.width);
    let H = i32(params.height);
    let px = i32(pos[i].x);
    let py = i32(pos[i].y);

    // CPU centres the mask on (x, y) via (sx, sy) = (x - mw/2, y - mh/2).
    let sx = px - i32(mw) / 2;
    let sy = py - i32(mh) / 2;

    let packed_rgba = color[i] | 0xFF000000u;  // force alpha = 255
    let mat_id      = material_id[i];

    for (var dy: u32 = 0u; dy < mh; dy = dy + 1u) {
        for (var dx: u32 = 0u; dx < mw; dx = dx + 1u) {
            let bit = shape_atlas[offset + dy * mw + dx];
            if (bit == 0u) {
                continue;
            }
            let nx = sx + i32(dx);
            let ny = sy + i32(dy);
            if (nx < 0 || nx >= W || ny < 0 || ny >= H) {
                continue;
            }
            let pix = u32(ny) * params.width + u32(nx);
            // Plain (non-atomic) writes — ordering between particles
            // whose polygons overlap is undefined. See header comment.
            mask_out[pix]          = packed_rgba;
            material_grid_out[pix] = mat_id;
            loose_out[pix]         = 1u;
        }
    }

    bake_flag[i] = 1u;
}
