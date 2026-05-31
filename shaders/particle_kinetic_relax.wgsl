// particle_kinetic_relax.wgsl
// ---------------------------------------------------------------
// GPU port of ParticleField._kinetic_relax (see particle_field.py).
//
// CPU reference (the *vectorised* numpy form, NOT the legacy loop):
//
//   eligible = (material is solid) & ~bake_flag & ~settled
//   strength[i] = max(material.kinetic_fluidity * clamp(1 - age/rig, 0, 1),
//                     0.4)
//   for each pair (a, b) with |pa - pb| in (0, rest):
//       f = (rest - d) * 0.4 * 0.5 * (g_a + g_b)
//       push[a] += normal * f
//       push[b] -= normal * f
//   pos[eligible] += push
//
// This shader produces the SAME push buffer (per-particle vec2<f32>) so
// the CPU side can do ``pos += push`` after readback. Each thread is
// responsible for ONE particle and walks its OWN cell only — mirroring
// the CPU vectorised reference which enumerates intra-cell pairs and
// drops cross-boundary ones (visual heuristic, see particle_field.py
// _kinetic_relax). Each pair (i, j) is therefore visited once by
// thread i and once by thread j; the two threads compute equal-and-
// opposite push vectors, so no atomics on the push buffer are needed.
//
// NOTE: a full 3x3 neighbour walk would catch more pairs and look
// nicer; that change can land in a follow-up sprint once we relax
// parity to "visual equivalence" rather than numeric tolerance.
//
// Bind-group layout (group 0):
//   binding  0  pos          : array<vec2<f32>>      storage read
//   binding  1  cell_start   : array<i32>            storage read
//   binding  2  cell_count   : array<i32>            storage read
//   binding  3  sorted_ids   : array<i32>            storage read
//   binding  4  cell_id      : array<i32>            storage read
//   binding  5  material_id  : array<i32>            storage read
//   binding  6  phase        : array<i32>            storage read
//   binding  7  bake_flag    : array<u32>            storage read   (0 / 1)
//   binding  8  rigidify_at  : array<i32>            storage read
//   binding  9  kinetic_age  : array<i32>            storage read
//   binding 10  push         : array<vec2<f32>>      storage read_write
//   binding 11  mat_props    : array<vec2<f32>>      storage read
//                                                    // .x = kinetic_fluidity
//                                                    // .y = is_fluid (0/1)
//   binding 12  params       : Params                uniform
//
// Notes
// -----
// * ``cell_id[i]`` is the cell key used to bin particle i — this lets
//   the GPU skip the world->cell math and matches whatever the CPU side
//   chose (we just upload it). Particles that fall outside the padded
//   grid hash to -1 (i.e. ineligible).
// * ``phase`` is upcast from int8 to int32 for storage-buffer alignment.
// * ``bake_flag`` is bool on the CPU; upcast to u32 here.
// * The push buffer is zeroed by the host before dispatch.
//
// Workgroup size: 64 (same rationale as particle_integrate.wgsl).
// ---------------------------------------------------------------

struct Params {
    rest_distance:     f32,
    baseline_strength: f32,
    cell_size:         f32,
    n_particles:       u32,
    grid_w:            i32,
    grid_h:            i32,
    _pad0:             u32,
    _pad1:             u32,
};

@group(0) @binding(0)  var<storage, read>       pos         : array<vec2<f32>>;
@group(0) @binding(1)  var<storage, read>       cell_start  : array<i32>;
@group(0) @binding(2)  var<storage, read>       cell_count  : array<i32>;
@group(0) @binding(3)  var<storage, read>       sorted_ids  : array<i32>;
@group(0) @binding(4)  var<storage, read>       cell_id     : array<i32>;
@group(0) @binding(5)  var<storage, read>       material_id : array<i32>;
@group(0) @binding(6)  var<storage, read>       phase       : array<i32>;
@group(0) @binding(7)  var<storage, read>       bake_flag   : array<u32>;
@group(0) @binding(8)  var<storage, read>       rigidify_at : array<i32>;
@group(0) @binding(9)  var<storage, read>       kinetic_age : array<i32>;
@group(0) @binding(10) var<storage, read_write> push        : array<vec2<f32>>;
@group(0) @binding(11) var<storage, read>       mat_props   : array<vec2<f32>>;
@group(0) @binding(12) var<uniform>             params      : Params;

// Eligibility: solid (non-fluid) material, not baked, not settled.
// Returns the per-particle strength on success, or -1.0 if ineligible.
fn strength_for(i: u32) -> f32 {
    let mid = material_id[i];
    if (mid < 0) {
        return -1.0;
    }
    let mp = mat_props[mid];
    let kf      = mp.x;       // kinetic_fluidity
    let is_flu  = mp.y;       // 1.0 if fluid, else 0.0
    if (is_flu > 0.5) {
        return -1.0;
    }
    if (bake_flag[i] != 0u) {
        return -1.0;
    }
    // ParticleField derives ``settled`` from ``phase >= SETTLING``.
    // SETTLING = 2 in the Phase enum. Anything at SETTLING or beyond
    // (BAKED = 3) is excluded — matches the CPU mask ``~self.settled``.
    if (phase[i] >= 2) {
        return -1.0;
    }
    let rig = max(f32(rigidify_at[i]), 1.0);
    let age = f32(kinetic_age[i]);
    let lerp = clamp(1.0 - age / rig, 0.0, 1.0);
    let kinetic_s = kf * lerp;
    return max(kinetic_s, params.baseline_strength);
}

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = gid.x;
    if (i >= params.n_particles) {
        return;
    }

    let g_i = strength_for(i);
    if (g_i < 0.0) {
        return;
    }

    let my_cell = cell_id[i];
    if (my_cell < 0) {
        return;   // outside the padded grid
    }

    let gx = params.grid_w;
    let gy = params.grid_h;
    let n_cells = gx * gy;

    let cx = my_cell % gx;
    let cy = my_cell / gx;

    let p_i = pos[i];
    let rest = params.rest_distance;
    let rest2 = rest * rest;

    var accum = vec2<f32>(0.0, 0.0);

    // Intra-cell only (matches CPU vectorised reference).
    let key = my_cell;
    if (key >= 0 && key < n_cells) {
        let start = cell_start[key];
        let count = cell_count[key];
        for (var k: i32 = 0; k < count; k = k + 1) {
            let j_idx = sorted_ids[start + k];
            if (j_idx < 0) {
                continue;
            }
            let j = u32(j_idx);
            if (j == i) {
                continue;
            }

            let g_j = strength_for(j);
            if (g_j < 0.0) {
                continue;
            }

            let d_vec = p_i - pos[j];
            let d2 = dot(d_vec, d_vec);
            if (d2 >= rest2 || d2 <= 0.0) {
                continue;
            }
            let d = sqrt(d2);
            // f = (rest - d) * 0.4 * 0.5 * (g_i + g_j)
            let f = (rest - d) * 0.4 * 0.5 * (g_i + g_j);
            let normal = d_vec / d;
            accum = accum + normal * f;
        }
    }

    // Silence unused-binding warnings if we later collapse params or
    // skip neighbours entirely.
    _ = gy;
    _ = gx;
    _ = cx;
    _ = cy;

    // Only thread i writes to push[i]; no atomics required.
    push[i] = accum;
}
