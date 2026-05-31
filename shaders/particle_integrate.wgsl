// particle_integrate.wgsl
// ---------------------------------------------------------------
// GPU port of ParticleField._integrate (see particle_field.py).
//
// Per AIRBORNE particle (phase == 0):
//   vel *= material.air_drag_per_sec ^ dt
//   vel.y += gravity * material.gravity_scale * dt
//   pos += vel * dt
//
// Layout
// ------
//   group(0) binding(0)  storage read_write   pos        : array<vec2<f32>>
//   group(0) binding(1)  storage read_write   vel        : array<vec2<f32>>
//   group(0) binding(2)  storage read         material_id: array<i32>
//   group(0) binding(3)  storage read         phase      : array<i32>     // i32 mirror of i8
//   group(0) binding(4)  storage read         mat_props  : array<vec2<f32>>
//                                                          // .x = gravity_scale
//                                                          // .y = air_drag_per_sec
//   group(0) binding(5)  uniform              params     : Params
//
// Workgroup size: 64 — matches health_sum / stats_reduction. Multiple of
// typical SIMD width (32/64) on every major backend (Vulkan/Metal/DX12),
// keeps occupancy high for a small kernel, and amortises dispatch
// overhead for the expected particle counts (hundreds-to-thousands).
// ---------------------------------------------------------------

struct Params {
    gravity:     f32,
    dt:          f32,
    n_particles: u32,
    _pad0:       u32,
};

@group(0) @binding(0) var<storage, read_write> pos         : array<vec2<f32>>;
@group(0) @binding(1) var<storage, read_write> vel         : array<vec2<f32>>;
@group(0) @binding(2) var<storage, read>       material_id : array<i32>;
@group(0) @binding(3) var<storage, read>       phase       : array<i32>;
@group(0) @binding(4) var<storage, read>       mat_props   : array<vec2<f32>>;
@group(0) @binding(5) var<uniform>              params      : Params;

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = gid.x;
    if (i >= params.n_particles) {
        return;
    }
    // AIRBORNE only. CPU integrates `air_mask = ~landed`; particle is
    // landed when phase >= LANDED (1). So airborne ↔ phase == 0.
    if (phase[i] != 0) {
        return;
    }

    let mid = material_id[i];
    let mp  = mat_props[mid];
    let gravity_scale     = mp.x;
    let air_drag_per_sec  = mp.y;

    var v = vel[i];

    // vel *= air_drag_per_sec ** dt
    // pow() in WGSL handles base > 0; drag values in BUILTIN_MATERIALS
    // are all in (0, 1].
    let drag = pow(air_drag_per_sec, params.dt);
    v = v * drag;

    // vel.y += gravity * gravity_scale * dt
    v.y = v.y + params.gravity * gravity_scale * params.dt;

    vel[i] = v;
    pos[i] = pos[i] + v * params.dt;
}
