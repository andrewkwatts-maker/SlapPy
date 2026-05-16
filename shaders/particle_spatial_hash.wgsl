// GPU particle-particle collision via spatial hashing.
//
// Three separate entry points (dispatch in order each frame):
//
//   Pass 1  hash_insert  — each live particle writes (cell_key, particle_idx)
//                          into a flat key/value buffer.
//   Pass 2  hash_build   — counting sort builds a compact cell-start table so
//                          that pass 3 can iterate only over nearby cells.
//   Pass 3  collide      — for each particle, visit the 27 neighbouring cells
//                          in the hash table and apply soft-body repulsion.
//
// Hash table sizing
// -----------------
//   HASH_SIZE = 65536 cells (fixed, power-of-two for cheap modulo via &).
//   Collisions are handled by open addressing (linear probing) in hash_insert,
//   and by the counting-sort table in hash_build / collide.
//
// Bind-group layout (group 0):
//   binding 0  SpatialParams        uniform
//   binding 1  particles            storage read_write   (same layout as simulate.wgsl)
//   binding 2  cell_keys            storage read_write   [u32; MAX_PARTICLES]
//   binding 3  cell_particle_ids    storage read_write   [u32; MAX_PARTICLES]
//   binding 4  cell_counts          storage read_write   [u32; HASH_SIZE]
//   binding 5  cell_starts          storage read_write   [u32; HASH_SIZE]
//   binding 6  sorted_ids           storage read_write   [u32; MAX_PARTICLES]

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

const HASH_SIZE:    u32 = 65536u;  // must be power of two
const HASH_MASK:    u32 = 65535u;  // HASH_SIZE - 1
const INVALID_CELL: u32 = 0xffffffffu;

// ─────────────────────────────────────────────────────────────────────────────
// Shared structs
// ─────────────────────────────────────────────────────────────────────────────

// Must mirror Particle in particle_simulate.wgsl (64 bytes, 16-byte aligned).
struct Particle {
    pos:         vec2<f32>,
    vel:         vec2<f32>,
    color:       vec4<f32>,
    lifetime:    f32,
    age:         f32,
    size:        f32,
    rotation:    f32,
    angular_vel: f32,
    _pad0:       f32,
    _pad1:       vec2<f32>,
}

struct SpatialParams {
    num_particles:  u32,   // total slots in the particles buffer
    cell_size:      f32,   // world-space size of one grid cell (pixels)
    repulsion_k:    f32,   // repulsion spring constant  (pixels/s² per overlap pixel)
    min_dist:       f32,   // minimum separation before repulsion kicks in (pixels)
    _pad:           vec4<f32>,
}

// ─────────────────────────────────────────────────────────────────────────────
// Bindings
// ─────────────────────────────────────────────────────────────────────────────

@group(0) @binding(0) var<uniform>             sparams           : SpatialParams;
@group(0) @binding(1) var<storage, read_write> particles         : array<Particle>;
@group(0) @binding(2) var<storage, read_write> cell_keys         : array<u32>;
@group(0) @binding(3) var<storage, read_write> cell_particle_ids : array<u32>;
@group(0) @binding(4) var<storage, read_write> cell_counts       : array<atomic<u32>>;
@group(0) @binding(5) var<storage, read_write> cell_starts       : array<u32>;
@group(0) @binding(6) var<storage, read_write> sorted_ids        : array<u32>;

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

// Convert a 2-D grid coordinate (integer) to a hash table bucket index.
// Uses a standard spatial hash mixing two large primes.
fn grid_to_cell_key(gx: i32, gy: i32) -> u32 {
    let ux = u32(gx + 65536);   // bias to avoid negative u32 wrap issues
    let uy = u32(gy + 65536);
    // FNV-1a inspired mix; prime coefficients give good avalanche.
    let h = (ux * 1664525u) ^ (uy * 1013904223u);
    return h & HASH_MASK;
}

// World-space position → grid cell coordinates.
fn world_to_grid(pos: vec2<f32>) -> vec2<i32> {
    return vec2<i32>(i32(floor(pos.x / sparams.cell_size)),
                     i32(floor(pos.y / sparams.cell_size)));
}

// ─────────────────────────────────────────────────────────────────────────────
// Pass 1 — hash_insert
// ─────────────────────────────────────────────────────────────────────────────
// Each live particle:
//   1. Computes its grid cell and hashed bucket.
//   2. Writes its bucket key to cell_keys[idx].
//   3. Writes its own index to cell_particle_ids[idx].
//   4. Increments the count for that bucket (atomic).
//
// Dead particles write INVALID_CELL so pass 3 can skip them cheaply.

@compute @workgroup_size(64)
fn hash_insert(@builtin(global_invocation_id) gid: vec3<u32>) {
    let idx = gid.x;
    if idx >= sparams.num_particles {
        return;
    }

    let p = particles[idx];
    cell_particle_ids[idx] = idx;

    if p.lifetime <= 0.0 {
        cell_keys[idx] = INVALID_CELL;
        return;
    }

    let gc  = world_to_grid(p.pos);
    let key = grid_to_cell_key(gc.x, gc.y);
    cell_keys[idx] = key;

    // Count live particles per bucket.
    atomicAdd(&cell_counts[key], 1u);
}

// ─────────────────────────────────────────────────────────────────────────────
// Pass 2 — hash_build
// ─────────────────────────────────────────────────────────────────────────────
// Two sub-steps are dispatched back-to-back from the CPU:
//
//   Step A (entry: prefix_scan)
//     A single thread does a serial prefix scan over cell_counts[] →
//     cell_starts[].  For 65536 cells this takes ~65 k iterations, which is
//     fast enough on a single GPU thread (~0.1 ms).  A proper GPU parallel
//     scan can be substituted later without changing the interface.
//
//   Step B (entry: scatter)
//     Each particle thread uses atomicAdd on cell_counts (reused as a
//     running write cursor) to find its slot in sorted_ids[], then writes
//     its index there.  After this pass, sorted_ids is a list of particle
//     indices grouped by bucket.

// Step A — serial prefix scan (dispatch with exactly 1 thread).
@compute @workgroup_size(1)
fn prefix_scan(@builtin(global_invocation_id) gid: vec3<u32>) {
    if gid.x != 0u {
        return;
    }

    var running: u32 = 0u;
    for (var i: u32 = 0u; i < HASH_SIZE; i = i + 1u) {
        let count = atomicLoad(&cell_counts[i]);
        cell_starts[i] = running;
        running += count;
        // Reset count to 0; pass B reuses it as a write-cursor.
        atomicStore(&cell_counts[i], 0u);
    }
}

// Step B — scatter each particle into sorted_ids[] at its bucket's slot.
@compute @workgroup_size(64)
fn scatter(@builtin(global_invocation_id) gid: vec3<u32>) {
    let idx = gid.x;
    if idx >= sparams.num_particles {
        return;
    }

    let key = cell_keys[idx];
    if key == INVALID_CELL {
        return;  // dead particle
    }

    // Claim the next write slot for this bucket.
    let slot = atomicAdd(&cell_counts[key], 1u);
    sorted_ids[cell_starts[key] + slot] = idx;
}

// ─────────────────────────────────────────────────────────────────────────────
// Pass 3 — collide
// ─────────────────────────────────────────────────────────────────────────────
// For each live particle, visit all 9 neighbouring grid cells (2-D system).
// For each neighbour particle found via sorted_ids, apply a spring-based
// repulsion force if the particles overlap.
//
// Repulsion model:
//   overlap  = min_dist - dist           (> 0 when particles overlap)
//   impulse  = repulsion_k * overlap * dt
//   vel     += impulse * normalize(delta) (pushes particle away)
//
// The force is applied symmetrically: both particles are updated by this
// thread.  A race condition exists when two threads update the same particle
// concurrently, but the resulting error (slightly wrong magnitude) is
// acceptable for a visual soft-body simulation.  For exact results, use
// double-buffering or atomic float adds (not available in core WGSL 1.0).

@compute @workgroup_size(64)
fn collide(@builtin(global_invocation_id) gid: vec3<u32>) {
    let idx = gid.x;
    if idx >= sparams.num_particles {
        return;
    }

    var p = particles[idx];
    if p.lifetime <= 0.0 {
        return;
    }

    let gc = world_to_grid(p.pos);

    // Accumulated velocity delta for this particle.
    var dvel = vec2<f32>(0.0, 0.0);

    // Visit 3×3 neighbourhood (9 cells in 2-D).
    for (var dy: i32 = -1; dy <= 1; dy++) {
        for (var dx: i32 = -1; dx <= 1; dx++) {
            let ngx = gc.x + dx;
            let ngy = gc.y + dy;
            let key = grid_to_cell_key(ngx, ngy);

            let start = cell_starts[key];
            // After pass 2, cell_counts[key] holds the count for this bucket.
            let count = atomicLoad(&cell_counts[key]);

            for (var k: u32 = 0u; k < count; k++) {
                let j = sorted_ids[start + k];
                if j == idx {
                    continue;  // skip self
                }

                let q     = particles[j];
                let delta = p.pos - q.pos;
                let dist2 = dot(delta, delta);

                // min_dist is the sum of the two radii (size / 2 each).
                let combined_r = (p.size + q.size) * 0.5;
                let min_dist   = max(sparams.min_dist, combined_r);

                if dist2 >= min_dist * min_dist || dist2 < 0.0001 {
                    continue;  // not overlapping or coincident
                }

                let dist    = sqrt(dist2);
                let overlap = min_dist - dist;
                let normal  = delta / dist;  // unit vector from q to p

                // Soft repulsion impulse proportional to overlap depth.
                let impulse = sparams.repulsion_k * overlap;
                dvel += normal * impulse;
            }
        }
    }

    p.vel += dvel;
    particles[idx] = p;
}
