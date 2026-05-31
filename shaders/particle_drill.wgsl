// particle_drill.wgsl
// ---------------------------------------------------------------
// GPU port of ParticleField._drill_through (see particle_field.py).
//
// Per "bullet in flight" (phase == AIRBORNE, mat.drill_max_px > 0 and
// KE > binding_force at the swept-hit pixel found by _collide):
//
//   1. Entry crater: clear a disc of radius
//          cr = mat.drill_entry_crater + rand(-jitter, +jitter)
//      around (x, hit_y). Each cleared pixel costs one
//      drill_velocity_loss multiply and one KE check (lodge bullet if
//      KE falls below binding_force * 0.5).
//   2. Drill walk: DDA step (dx, dy) = vel.normalised, clear one
//      pixel per step, multiply vel by drill_velocity_loss per pixel,
//      KE check after each. Stop on out-of-bounds, on empty pixel
//      (exited the wall), or on lodge.
//   3. Ejecta: round(drilled * mat.drill_eject_gain * mat.mass_conservation)
//      particles spawned with material id sampled from the drilled
//      WALL pixel colours. Direction = -vel ±60°, speed [80, 220].
//      Append to a global atomic counter; CPU resolves into spawn_batch.
//
// NOT IN THIS KERNEL (deferred):
//   - Per-pixel deflection (mat.drill_deflection > 0)
//   - Fracture pass (mat.drill_fracture_threshold < 1.0)
//   - Isolated-pixel detach pass — runs CPU-side after the GPU readback
//     because it needs a neighbour-shift scan that benefits more from
//     numpy's vectorised primitives than from a per-bullet workgroup.
//
// DETERMINISM NOTE — ACCEPTED DESIGN CONSTRAINT:
// When two bullets drill overlapping regions in the same frame, the
// ORDER in which their writes to mask/material_grid/loose land is
// undefined (GPU dispatches are not serialised across workgroups).
// The CPU path has the same property: it iterates particles in index
// order, so two bullets clearing the SAME pixel both succeed but the
// observable "who cleared it" depends on iteration order. Both paths
// converge as long as no two bullets clear the same pixel in the
// same frame — the parity test enforces this by spacing bullets apart.
//
// Layout
// ------
//   group(0) binding(0)  storage rw  pos                : array<vec2<f32>>
//   group(0) binding(1)  storage rw  vel                : array<vec2<f32>>
//   group(0) binding(2)  storage rw  phase              : array<i32>
//   group(0) binding(3)  storage rw  color              : array<u32>  // rgba8 packed (a in MSB)
//   group(0) binding(4)  storage r   material_id        : array<i32>
//   group(0) binding(5)  storage rw  mask               : array<u32>  // rgba8 packed pixel
//   group(0) binding(6)  storage rw  material_grid      : array<i32>  // i32 mirror of i8 grid
//   group(0) binding(7)  storage rw  loose              : array<u32>  // 0/1 per pixel
//   group(0) binding(8)  storage rw  ejecta_count       : atomic<u32>
//   group(0) binding(9)  storage rw  ejecta             : EjectaOut
//   group(0) binding(10) storage r   mat_props          : array<vec4<f32>>
//   group(0) binding(11) uniform     params             : Params
//   group(0) binding(12) storage r   radius             : array<f32>
//
// Workgroup size: 64 — one thread per particle. Drill is variable-work
// per particle (some do 0 px, some do drill_max_px), but each particle
// is independent (modulo overlapping wall writes), so we let each
// thread run its own loop. No workgroup-shared state.
// ---------------------------------------------------------------

struct Params {
    n_particles:        u32,
    width:              u32,
    height:             u32,
    max_ejecta:         u32,
    rng_seed:           u32,
    dt:                 f32,
    _pad0:              u32,
    _pad1:              u32,
};

// mat_props is laid out as PAIRS of vec4<f32> per material:
//   mat_props[2*mid + 0] = (drill_max_px, drill_velocity_loss,
//                           drill_eject_gain, binding_force)
//   mat_props[2*mid + 1] = (entry_crater, entry_crater_jitter,
//                           mass_conservation, _pad)

struct EjectaOut {
    // SoA-style layout. CPU reads the first ejecta_count rows.
    // Each "row" is one ejecta particle. Stored as flat arrays so we
    // can readback each separately without per-particle padding.
    // Layout: [pos_x, pos_y, vel_x, vel_y, mid, r, g, b, _pad] = 9 u32s
    // per ejecta. We keep this in one big buffer + decode CPU-side.
    data: array<u32>,
};

@group(0) @binding(0)  var<storage, read_write> pos           : array<vec2<f32>>;
@group(0) @binding(1)  var<storage, read_write> vel           : array<vec2<f32>>;
@group(0) @binding(2)  var<storage, read_write> phase         : array<i32>;
@group(0) @binding(3)  var<storage, read_write> color         : array<u32>;
@group(0) @binding(4)  var<storage, read>       material_id   : array<i32>;
@group(0) @binding(5)  var<storage, read_write> mask          : array<u32>;
@group(0) @binding(6)  var<storage, read_write> material_grid : array<i32>;
@group(0) @binding(7)  var<storage, read_write> loose         : array<u32>;
@group(0) @binding(8)  var<storage, read_write> ejecta_count  : atomic<u32>;
@group(0) @binding(9)  var<storage, read_write> ejecta        : EjectaOut;
@group(0) @binding(10) var<storage, read>       mat_props     : array<vec4<f32>>;
@group(0) @binding(11) var<uniform>             params        : Params;
@group(0) @binding(12) var<storage, read>       radius        : array<f32>;

// ── Phase constants (mirror Phase enum) ────────────────────────────────
const PHASE_AIRBORNE : i32 = 0;
const PHASE_LANDED   : i32 = 1;
const PHASE_BAKED    : i32 = 3;

const EJECTA_STRIDE  : u32 = 9u;  // u32s per ejecta record

// ── Helpers ───────────────────────────────────────────────────────────

fn pixel_idx(x: i32, y: i32) -> u32 {
    return u32(y) * params.width + u32(x);
}

fn in_bounds(x: i32, y: i32) -> bool {
    return x >= 0 && y >= 0 && u32(x) < params.width && u32(y) < params.height;
}

// rgba8 unpack: packed as (a << 24) | (b << 16) | (g << 8) | r — little-endian uint8 ndarray.
fn unpack_rgba(p: u32) -> vec4<u32> {
    return vec4<u32>(
        p & 0xFFu,
        (p >> 8u) & 0xFFu,
        (p >> 16u) & 0xFFu,
        (p >> 24u) & 0xFFu,
    );
}

fn pack_rgba(r: u32, g: u32, b: u32, a: u32) -> u32 {
    return (a << 24u) | (b << 16u) | (g << 8u) | r;
}

fn set_alpha(p: u32, a: u32) -> u32 {
    return (p & 0x00FFFFFFu) | (a << 24u);
}

// Simple PCG-ish hash for per-bullet jitter / ejecta picks.
fn hash_u32(x: u32) -> u32 {
    var h = x ^ params.rng_seed;
    h = h * 747796405u + 2891336453u;
    let w = ((h >> ((h >> 28u) + 4u)) ^ h) * 277803737u;
    return (w >> 22u) ^ w;
}

fn rand_unit(seed: ptr<function, u32>) -> f32 {
    *seed = hash_u32(*seed);
    return f32((*seed) & 0x00FFFFFFu) / f32(0x01000000u);
}

fn rand_range(seed: ptr<function, u32>, lo: f32, hi: f32) -> f32 {
    return lo + (hi - lo) * rand_unit(seed);
}

// ── Main ──────────────────────────────────────────────────────────────

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = gid.x;
    if (i >= params.n_particles) {
        return;
    }
    // Bullets in flight only: phase == AIRBORNE.
    if (phase[i] != PHASE_AIRBORNE) {
        return;
    }
    let mid = material_id[i];
    // mat_props is packed as two vec4 per material — index 2*mid and 2*mid+1.
    let mp0 = mat_props[2u * u32(mid)];
    let mp1 = mat_props[2u * u32(mid) + 1u];
    let drill_max_px        = mp0.x;
    let drill_velocity_loss = mp0.y;
    let drill_eject_gain    = mp0.z;
    let binding_force       = mp0.w;
    let entry_crater        = mp1.x;
    let entry_crater_jitter = mp1.y;
    let mass_conservation   = mp1.z;
    if (drill_max_px <= 0.0) {
        return;
    }

    // CPU has already done the swept DDA and decided to call _drill_through
    // at (hit_x, hit_y). On the GPU side we replicate that swept lookup
    // here so the kernel is self-contained — see _collide() body.
    let prev_x = i32(floor(pos[i].x - vel[i].x * params.dt));
    let prev_y = i32(floor(pos[i].y - vel[i].y * params.dt));
    let cur_x  = i32(floor(pos[i].x));
    let cur_y  = i32(floor(pos[i].y));
    let dxw = cur_x - prev_x;
    let dyw = cur_y - prev_y;
    var steps = max(abs(dxw), abs(dyw));
    if (steps < 1) { steps = 1; }
    var hit_x : i32 = -1;
    var hit_y : i32 = -1;
    for (var s : i32 = 0; s <= steps; s = s + 1) {
        let cx = prev_x + (dxw * s) / steps;
        let cy = prev_y + (dyw * s) / steps;
        if (!in_bounds(cx, cy)) { continue; }
        let p = mask[pixel_idx(cx, cy)];
        if (((p >> 24u) & 0xFFu) > 0u) {
            hit_x = cx;
            hit_y = cy;
            break;
        }
    }
    if (hit_x < 0) {
        return;
    }
    // KE gate: only drill if KE > binding_force.
    let vsq0 = vel[i].x * vel[i].x + vel[i].y * vel[i].y;
    let r0   = max(1.0, radius[i]);
    let ke0 = 0.5 * (r0 * r0) * vsq0;
    if (ke0 <= binding_force) {
        return;
    }

    let bullet_mid = mid;
    let vx0 = vel[i].x;
    let vy0 = vel[i].y;
    let speed0 = sqrt(vsq0);
    if (speed0 <= 0.0) {
        phase[i] = PHASE_LANDED;
        return;
    }
    var dxn = vx0 / speed0;
    var dyn = vy0 / speed0;

    var px = f32(hit_x) + 0.5;
    var py = f32(hit_y) + 0.5;
    var drilled : i32 = 0;

    var vx = vx0;
    var vy = vy0;

    // Track sampled colour + material id from the drill line (we keep a
    // small ring of up to 32 samples; ejecta picks index hash%count).
    var line_colours : array<u32, 32>;
    var line_mids    : array<i32, 32>;
    var line_n       : u32 = 0u;

    // Per-bullet RNG seed.
    var rng_state : u32 = hash_u32(i ^ 0xA5A5A5A5u);

    // ── Entry crater ────────────────────────────────────────────────
    var crater_stopped : bool = false;
    let cr_base = i32(entry_crater);
    if (cr_base > 0) {
        var cr = cr_base;
        let jit = i32(entry_crater_jitter);
        if (jit > 0) {
            let j = i32(rand_range(&rng_state, f32(-jit), f32(jit + 1)));
            cr = max(0, cr + j);
        }
        let cr2 = cr * cr;
        for (var ddy : i32 = -cr; ddy <= cr; ddy = ddy + 1) {
            if (crater_stopped) { break; }
            for (var ddx : i32 = -cr; ddx <= cr; ddx = ddx + 1) {
                if (ddx * ddx + ddy * ddy > cr2) { continue; }
                let cx = hit_x + ddx;
                let cy = hit_y + ddy;
                if (!in_bounds(cx, cy)) { continue; }
                let pidx = pixel_idx(cx, cy);
                let pix = mask[pidx];
                if (((pix >> 24u) & 0xFFu) > 0u) {
                    // Record colour + mid.
                    if (line_n < 32u) {
                        line_colours[line_n] = pix & 0x00FFFFFFu;
                        let wm = material_grid[pidx];
                        var rec_mid = wm;
                        if (wm < 0) { rec_mid = bullet_mid; }
                        line_mids[line_n] = rec_mid;
                        line_n = line_n + 1u;
                    }
                    mask[pidx] = set_alpha(pix, 0u);
                    loose[pidx] = 0u;
                    drilled = drilled + 1;
                    vx = vx * drill_velocity_loss;
                    vy = vy * drill_velocity_loss;
                    let vsq = vx * vx + vy * vy;
                    let ke = 0.5 * (r0 * r0) * vsq;
                    if (ke < binding_force * 0.5) {
                        // Lodge bullet here.
                        let bc = color[i];
                        let r = bc & 0xFFu;
                        let g = (bc >> 8u) & 0xFFu;
                        let b = (bc >> 16u) & 0xFFu;
                        mask[pidx] = pack_rgba(r, g, b, 255u);
                        pos[i] = vec2<f32>(f32(cx), f32(cy));
                        phase[i] = PHASE_BAKED;
                        crater_stopped = true;
                        break;
                    }
                }
            }
        }
    }
    if (crater_stopped) {
        vel[i] = vec2<f32>(vx, vy);
        // Fall through to ejecta spawn below using drilled count.
    } else {
        // ── Drill walk ──────────────────────────────────────────────
        // CPU semantics (see ParticleField._drill_through):
        //   * If the while-loop exits because drilled == drill_max_px
        //     (loop CONDITION became false, the Python `else:` branch
        //     fires), pos is updated to (px, py).
        //   * If the loop BREAKS (out-of-bounds, exited wall, lodge),
        //     pos is NOT updated by _drill_through — the bullet stays
        //     wherever _collide left it.
        //   * The lodge path overrides pos AND phase explicitly.
        // We mirror this exactly: only write pos on the "drilled out
        // the entire allowance" path or the lodge path.
        let dmax = i32(drill_max_px);
        var natural_exit : bool = true;
        loop {
            if (drilled >= dmax) { break; }  // natural — pos gets written below
            let xi = i32(floor(px));
            let yi = i32(floor(py));
            if (!in_bounds(xi, yi)) {
                natural_exit = false;
                break;
            }
            let pidx = pixel_idx(xi, yi);
            let pix = mask[pidx];
            if (((pix >> 24u) & 0xFFu) == 0u) {
                natural_exit = false;
                break;  // exited wall
            }
            if (line_n < 32u) {
                line_colours[line_n] = pix & 0x00FFFFFFu;
                let wm = material_grid[pidx];
                var rec_mid = wm;
                if (wm < 0) { rec_mid = bullet_mid; }
                line_mids[line_n] = rec_mid;
                line_n = line_n + 1u;
            }
            mask[pidx] = set_alpha(pix, 0u);
            loose[pidx] = 0u;
            drilled = drilled + 1;
            vx = vx * drill_velocity_loss;
            vy = vy * drill_velocity_loss;
            let vsq = vx * vx + vy * vy;
            let ke = 0.5 * (r0 * r0) * vsq;
            if (ke < binding_force * 0.5) {
                let bc = color[i];
                let r = bc & 0xFFu;
                let g = (bc >> 8u) & 0xFFu;
                let b = (bc >> 16u) & 0xFFu;
                mask[pidx] = pack_rgba(r, g, b, 255u);
                pos[i] = vec2<f32>(f32(xi), f32(yi));
                phase[i] = PHASE_BAKED;
                vel[i] = vec2<f32>(vx, vy);
                natural_exit = false;
                break;
            }
            px = px + dxn;
            py = py + dyn;
        }
        if (natural_exit) {
            // Exhausted drill_max_px — CPU's `else` clause writes pos.
            pos[i] = vec2<f32>(px, py);
            phase[i] = PHASE_AIRBORNE;
        }
        // Always write vel (CPU does too — vel mutates per drilled pixel).
        vel[i] = vec2<f32>(vx, vy);
    }

    // ── Ejecta spawn ───────────────────────────────────────────────
    let n_eject_f = round(f32(drilled) * drill_eject_gain * mass_conservation);
    let n_eject = i32(n_eject_f);
    if (n_eject > 0 && line_n > 0u) {
        let base_angle = atan2(-vy0, -vx0);
        let cone = 1.0471975512;  // pi/3
        for (var k : i32 = 0; k < n_eject; k = k + 1) {
            // Reserve one slot in the global counter.
            let slot = atomicAdd(&ejecta_count, 1u);
            if (slot >= params.max_ejecta) {
                // Overflow — undo the increment by leaving the counter
                // saturated; CPU clamps the readback to max_ejecta.
                break;
            }
            let pick = hash_u32(rng_state + u32(k) * 7919u) % line_n;
            let col = line_colours[pick];
            let emid = line_mids[pick];
            let ang = base_angle + rand_range(&rng_state, -cone, cone);
            let spd = rand_range(&rng_state, 80.0, 220.0);
            let evx = cos(ang) * spd;
            let evy = sin(ang) * spd;

            let base = slot * EJECTA_STRIDE;
            ejecta.data[base + 0u] = bitcast<u32>(f32(hit_x));
            ejecta.data[base + 1u] = bitcast<u32>(f32(hit_y));
            ejecta.data[base + 2u] = bitcast<u32>(evx);
            ejecta.data[base + 3u] = bitcast<u32>(evy);
            ejecta.data[base + 4u] = bitcast<u32>(emid);
            ejecta.data[base + 5u] = col & 0xFFu;          // r
            ejecta.data[base + 6u] = (col >> 8u) & 0xFFu;  // g
            ejecta.data[base + 7u] = (col >> 16u) & 0xFFu; // b
            ejecta.data[base + 8u] = 0u;
        }
    }
}

