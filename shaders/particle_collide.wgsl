// particle_collide.wgsl
// ---------------------------------------------------------------
// GPU port of ParticleField._collide (see particle_field.py).
//
// Per AIRBORNE particle (phase == 0):
//   - Bounds check: if x OOB-x or y >= H -> mark SETTLING (phase=2)
//     and return. If y < 0 -> return (sky, no collide yet).
//   - For non-drill materials moving upward (vel.y < 0): skip
//     (avoid catching on launch surface).
//   - Swept DDA from (prev_x, prev_y) -> (x, y), one alpha probe per
//     step. First step with mask alpha>0 = hit.
//   - On hit: capture impact_vel = vel, snap pos to (hit_x, hit_y-1),
//     phase -> LANDED. For fluid materials (is_fluid bit set):
//     vel.y = 0 then phase reverts to AIRBORNE. For solid materials:
//     shrink rigidify_at by (1 - impact_stickiness).
//
// Notes
// -----
// The drill path (mat.drill_max_px > 0) is NOT implemented here.
// Callers must route such particles through the CPU path (see
// particle_gpu.py::gpu_collide). For the parity-test materials
// (sand, default drill_max_px=0) this is a no-op.
//
// Layout
// ------
//   group(0) binding(0)  storage read_write  pos          : array<vec2<f32>>
//   group(0) binding(1)  storage read_write  vel          : array<vec2<f32>>
//   group(0) binding(2)  storage read_write  phase        : array<i32>
//   group(0) binding(3)  storage read_write  impact_vel   : array<vec2<f32>>
//   group(0) binding(4)  storage read_write  rigidify_at  : array<i32>
//   group(0) binding(5)  storage read        kinetic_age  : array<i32>
//   group(0) binding(6)  storage read        material_id  : array<i32>
//   group(0) binding(7)  storage read        mask_alpha   : array<u32>   // H*W, alpha>0 = solid
//   group(0) binding(8)  storage read        mat_props    : array<vec4<f32>>
//                                                          // .x = is_fluid (0/1)
//                                                          // .y = impact_stickiness
//                                                          // .z = drill_max_px (0 = no drill)
//                                                          // .w = unused
//   group(0) binding(9)  uniform             params       : Params
//
// Workgroup size: 64 (matches particle_integrate.wgsl rationale).
// ---------------------------------------------------------------

struct Params {
    dt:          f32,
    n_particles: u32,
    width:       u32,
    height:      u32,
};

@group(0) @binding(0) var<storage, read_write> pos         : array<vec2<f32>>;
@group(0) @binding(1) var<storage, read_write> vel         : array<vec2<f32>>;
@group(0) @binding(2) var<storage, read_write> phase       : array<i32>;
@group(0) @binding(3) var<storage, read_write> impact_vel  : array<vec2<f32>>;
@group(0) @binding(4) var<storage, read_write> rigidify_at : array<i32>;
@group(0) @binding(5) var<storage, read>       kinetic_age : array<i32>;
@group(0) @binding(6) var<storage, read>       material_id : array<i32>;
@group(0) @binding(7) var<storage, read>       mask_alpha  : array<u32>;
@group(0) @binding(8) var<storage, read>       mat_props   : array<vec4<f32>>;
@group(0) @binding(9) var<uniform>             params      : Params;

const PHASE_AIRBORNE : i32 = 0;
const PHASE_LANDED   : i32 = 1;
const PHASE_SETTLING : i32 = 2;

fn alpha_at(cx: i32, cy: i32) -> u32 {
    // Bounds already checked by caller; index into row-major (y*W + x).
    let idx = u32(cy) * params.width + u32(cx);
    return mask_alpha[idx];
}

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = gid.x;
    if (i >= params.n_particles) {
        return;
    }
    if (phase[i] != PHASE_AIRBORNE) {
        return;
    }

    let W = i32(params.width);
    let H = i32(params.height);

    let px = pos[i].x;
    let py = pos[i].y;
    let x  = i32(px);
    let y  = i32(py);

    if (x < 0 || x >= W || y >= H) {
        // OOB sides or fell through bottom -> SETTLING (CPU sets the
        // phase, also flips landed+settled flags via _set_phase). The
        // GPU mirrors only the phase write; the CPU readback path is
        // responsible for re-deriving landed/settled from phase.
        phase[i] = PHASE_SETTLING;
        return;
    }
    if (y < 0) {
        return;
    }

    let mid = material_id[i];
    let mp  = mat_props[mid];
    let is_fluid    = mp.x > 0.5;
    let stickiness  = mp.y;
    let drill_max   = mp.z;

    let vx = vel[i].x;
    let vy = vel[i].y;

    // Non-drill materials moving upward skip collision (don't catch on
    // their own launch surface). Drill materials hit ceilings too.
    if (drill_max == 0.0 && vy < 0.0) {
        return;
    }

    // Swept DDA from prev pixel to current pixel.
    let prev_x = i32(px - vx * params.dt);
    let prev_y = i32(py - vy * params.dt);
    let dx = x - prev_x;
    let dy = y - prev_y;
    let abs_dx = abs(dx);
    let abs_dy = abs(dy);
    var steps = abs_dx;
    if (abs_dy > steps) {
        steps = abs_dy;
    }
    if (steps < 1) {
        steps = 1;
    }

    var hit_x: i32 = -1;
    var hit_y: i32 = -1;
    for (var s: i32 = 0; s <= steps; s = s + 1) {
        // Python `//` is floor-div. For non-negative numerators this
        // matches WGSL i32 `/`, but for negative dx/dy floor-div and
        // trunc-div differ. Replicate Python semantics explicitly.
        let cx = prev_x + py_floordiv(dx * s, steps);
        let cy = prev_y + py_floordiv(dy * s, steps);
        if (cx < 0 || cx >= W || cy < 0 || cy >= H) {
            continue;
        }
        if (alpha_at(cx, cy) > 0u) {
            hit_x = cx;
            hit_y = cy;
            break;
        }
    }

    if (hit_x < 0) {
        return;
    }

    // Drill path: deferred to a separate kernel. For drill materials
    // with KE > binding_force the CPU path carves the mask, which we
    // cannot replicate in this shader. Leave the particle untouched
    // for this frame; callers ensure drill materials are routed
    // through the CPU path (see particle_gpu.gpu_collide).
    if (drill_max > 0.0) {
        return;
    }

    impact_vel[i] = vec2<f32>(vx, vy);
    pos[i] = vec2<f32>(f32(hit_x), f32(hit_y - 1));
    phase[i] = PHASE_LANDED;

    if (is_fluid) {
        vel[i].y = 0.0;
        phase[i] = PHASE_AIRBORNE;
    } else {
        // Solid impact: collapse remaining kinetic time by (1 - impact_stickiness).
        let remaining_raw = rigidify_at[i] - kinetic_age[i];
        var remaining = remaining_raw;
        if (remaining < 0) {
            remaining = 0;
        }
        let shrink = 1.0 - stickiness;
        // i32 truncates toward 0 — matches Python int(remaining * shrink)
        // for non-negative remaining and 0 <= shrink <= 1.
        let new_remaining = i32(f32(remaining) * shrink);
        rigidify_at[i] = kinetic_age[i] + new_remaining;
    }
}

// Python's floor division for i32: a // b. For positive b, equals
// trunc-div when sign(a) == sign(b), else trunc-div - 1 when the
// division has a remainder. WGSL `/` truncates toward zero.
fn py_floordiv(a: i32, b: i32) -> i32 {
    let q = a / b;
    let r = a - q * b;
    // If remainder is non-zero and signs of remainder and divisor differ,
    // subtract 1. (Equivalent to: a // b in Python.)
    if (r != 0 && ((r < 0) != (b < 0))) {
        return q - 1;
    }
    return q;
}
