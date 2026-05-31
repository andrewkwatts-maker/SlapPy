// particle_slide.wgsl
// ---------------------------------------------------------------
// GPU port of ParticleField._slide (see particle_field.py).
//
// Per LANDED-but-not-settled particle (phase == 1):
//   1. vel.x *= material.friction_per_sec ^ dt
//   2. vel.y  = 0
//   3. pos.x += vel.x * dt
//   4. Snap pos.y to the topmost solid pixel of the current column
//      (walks up from current y while mask alpha > 0).
//   5. Roll-downhill redirect — pick the side with the largest drop
//      within 5 columns; redirect if drop >= step threshold (step
//      depends on whether the particle is fast or slow).
//   6. Tumble kick — random vy impulse for materials with
//      tumble_kick > 0, re-airbornes the particle (phase = AIRBORNE).
//   7. Settle threshold — if |vx| < threshold * (1 ± jitter), enter
//      SETTLING phase and zero vx.
//
// Layout
// ------
//   group(0) binding(0)  storage read_write   pos          : array<vec2<f32>>
//   group(0) binding(1)  storage read_write   vel          : array<vec2<f32>>
//   group(0) binding(2)  storage read_write   phase        : array<i32>
//   group(0) binding(3)  storage read         material_id  : array<i32>
//   group(0) binding(4)  storage read         column_top   : array<i32>    // (W,)
//   group(0) binding(5)  storage read         mat_props    : array<vec4<f32>>
//                              .x = friction_per_sec
//                              .y = settle_speed_threshold
//                              .z = settle_jitter
//                              .w = tumble_kick
//   group(0) binding(6)  storage read_write   rng_state    : array<u32>    // pcg32 state per particle
//   group(0) binding(7)  uniform              params       : Params
//
// Workgroup size: 64 — see particle_integrate.wgsl rationale.
//
// RNG: PCG32 (one-shot multiply + xorshift) per particle. State is
// initialised on the CPU at spawn time and advanced here each step.
// Each particle has its own state so no thread serialisation is
// needed. We need up to 3 uniform draws per step (left/right tie,
// tumble kick magnitude, settle threshold jitter).
// ---------------------------------------------------------------

struct Params {
    dt:           f32,
    n_particles:  u32,
    width:        u32,
    height:       u32,
};

@group(0) @binding(0) var<storage, read_write> pos         : array<vec2<f32>>;
@group(0) @binding(1) var<storage, read_write> vel         : array<vec2<f32>>;
@group(0) @binding(2) var<storage, read_write> phase       : array<i32>;
@group(0) @binding(3) var<storage, read>       material_id : array<i32>;
@group(0) @binding(4) var<storage, read>       column_top  : array<i32>;
@group(0) @binding(5) var<storage, read>       mat_props   : array<vec4<f32>>;
@group(0) @binding(6) var<storage, read_write> rng_state   : array<u32>;
@group(0) @binding(7) var<uniform>              params      : Params;

// Phase enum values (see Phase in particle_field.py).
const PHASE_AIRBORNE : i32 = 0;
const PHASE_LANDED   : i32 = 1;
const PHASE_SETTLING : i32 = 2;
const PHASE_BAKED    : i32 = 3;

// PCG32 — single-state variant. Cheap, decent quality, easy in WGSL.
// Returns a u32 of pseudo-random bits and advances the state.
fn pcg32(state_ptr: ptr<function, u32>) -> u32 {
    let oldstate = *state_ptr;
    // PCG-XSH-RS, 32-bit state variant.
    *state_ptr = oldstate * 747796405u + 2891336453u;
    var word = ((oldstate >> ((oldstate >> 28u) + 4u)) ^ oldstate) * 277803737u;
    word = (word >> 22u) ^ word;
    return word;
}

// Uniform float in [0, 1).
fn rng_uniform01(state_ptr: ptr<function, u32>) -> f32 {
    let bits = pcg32(state_ptr);
    // 24 bits of mantissa → max 16777216 distinct values, [0, 1).
    return f32(bits >> 8u) * (1.0 / 16777216.0);
}

// Mirror of ParticleField._column_top via the precomputed buffer.
fn column_top_at(x: i32) -> i32 {
    if (x < 0 || x >= i32(params.width)) {
        return i32(params.height);
    }
    return column_top[x];
}

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = gid.x;
    if (i >= params.n_particles) {
        return;
    }
    // Only LANDED particles slide.
    if (phase[i] != PHASE_LANDED) {
        return;
    }

    let mid = material_id[i];
    let mp = mat_props[mid];
    let friction_per_sec   = mp.x;
    let settle_threshold   = mp.y;
    let settle_jitter      = mp.z;
    let tumble_kick        = mp.w;

    let W = i32(params.width);
    let H = i32(params.height);

    // ── (1)+(2) friction on vx, zero vy ─────────────────────────────
    var v = vel[i];
    v.x = v.x * pow(friction_per_sec, params.dt);
    v.y = 0.0;

    // ── (3) advance pos.x ──────────────────────────────────────────
    var p = pos[i];
    p.x = p.x + v.x * params.dt;

    // Load this thread's PCG state once into a function-local var so
    // the pointer-of-var pattern works (storage pointers can't be
    // passed to functions in WGSL 1.0).
    var rstate = rng_state[i];

    // ── (4) snap pos.y to column top using precomputed buffer ──────
    // CPU walks up from the current integer y while mask alpha > 0;
    // the column_top buffer already gives us the topmost solid row,
    // so we snap there directly. CPU semantics: if current y is
    // ABOVE the topmost solid pixel, the while-loop does nothing and
    // y stays put; only when the particle is at or below the top do
    // we snap. We mirror that:
    let xi = i32(p.x);
    if (xi >= 0 && xi < W) {
        let top = column_top_at(xi);
        var y_cur = i32(p.y);
        // CPU loop: while y > 0 and mask[y, x, 3] > 0: y -= 1
        // Without overhangs, this is equivalent to snapping to
        // (top - 1) whenever y_cur >= top, clamped to 0.
        if (y_cur >= top) {
            y_cur = max(0, top - 1);
        }

        // ── (5) roll-downhill redirect ─────────────────────────────
        let my_top = y_cur;
        var best_left_drop  : i32 = 0;
        var best_right_drop : i32 = 0;
        for (var d: i32 = 1; d < 6; d = d + 1) {
            let cxl = xi - d;
            if (cxl >= 0 && cxl < W) {
                let dl = column_top_at(cxl) - my_top;
                if (dl > best_left_drop) {
                    best_left_drop = dl;
                }
            }
            let cxr = xi + d;
            if (cxr >= 0 && cxr < W) {
                let dr = column_top_at(cxr) - my_top;
                if (dr > best_right_drop) {
                    best_right_drop = dr;
                }
            }
        }
        let fast_thresh = max(20.0, settle_threshold * 2.0);
        let is_fast = abs(v.x) > fast_thresh;
        let step = select(4, 2, is_fast);  // slow=4, fast=2

        if (best_left_drop >= step || best_right_drop >= step) {
            var direction: i32 = 0;
            if (best_left_drop > best_right_drop) {
                direction = -1;
            } else if (best_right_drop > best_left_drop) {
                direction = 1;
            } else {
                // Tie — coin flip via PCG. CPU: -1 if rng.random() < 0.5 else 1
                let r = rng_uniform01(&rstate);
                if (r < 0.5) {
                    direction = -1;
                } else {
                    direction = 1;
                }
            }
            var new_x = xi + direction;
            if (new_x < 0) { new_x = 0; }
            if (new_x > W - 1) { new_x = W - 1; }
            let new_y_raw = column_top_at(new_x) - 1;
            let new_y = max(0, new_y_raw);
            p.x = f32(new_x);
            p.y = f32(new_y);
        } else {
            p.y = f32(y_cur);
        }
    }

    // ── (6) tumble kick ────────────────────────────────────────────
    // Negative vy = upward (mirrors CPU). Re-airbornes the particle.
    var new_phase: i32 = PHASE_LANDED;
    if (tumble_kick > 0.0 && abs(v.x) > 5.0) {
        // CPU: rng.uniform(0.3, 1.0) → [0.3, 1.0)
        let u = rng_uniform01(&rstate);
        let scale = 0.3 + 0.7 * u;
        let kick = tumble_kick * abs(v.x) * scale;
        v.y = -kick;
        new_phase = PHASE_AIRBORNE;
    }

    // ── (7) settle threshold ───────────────────────────────────────
    // Jittered threshold. CPU draws unconditionally so RNG state
    // matches whether or not jitter > 0; we mirror that.
    var threshold = settle_threshold;
    if (settle_jitter > 0.0) {
        // CPU: rng.uniform(-jitter, jitter) → [-j, j)
        let u = rng_uniform01(&rstate);
        let j = -settle_jitter + 2.0 * settle_jitter * u;
        threshold = settle_threshold * (1.0 + j);
    }
    // Only settle if the tumble kick didn't re-airborne us. (CPU
    // checks abs(vx) < threshold AFTER the tumble kick mutates phase
    // — but tumble_kick doesn't touch vx, so the predicate evaluates
    // the same vx. We replicate.)
    if (abs(v.x) < threshold) {
        // Settle wins regardless of whether tumble re-airborned —
        // mirrors CPU which calls _set_phase(SETTLING) inside the
        // same iteration, overriding the earlier AIRBORNE write.
        new_phase = PHASE_SETTLING;
        v.x = 0.0;
    }

    // ── Write back ─────────────────────────────────────────────────
    pos[i] = p;
    vel[i] = v;
    if (new_phase != PHASE_LANDED) {
        phase[i] = new_phase;
    }
    rng_state[i] = rstate;
}
