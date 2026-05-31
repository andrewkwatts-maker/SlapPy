// particle_slump.wgsl
// ---------------------------------------------------------------
// GPU port of ParticleField._slump_loose (see particle_field.py).
//
// CPU reference (bottom-up sweep, per row):
//
//   for y in range(H-2, 0, -1):
//       row_loose = loose[y]
//       below_empty = ~solid[y+1]
//       fall = row_loose & below_empty & (rng < fall_prob)
//       # apply fall: mask[y+1,x] = mask[y,x]; mask[y,x,3]=0; loose flips
//       still = row_loose & ~below_empty
//       left_lower  = still & ~solid[y+1,:-1] & ~solid[y, :-1]  (shifted)
//       right_lower = still & ~solid[y+1, 1:] & ~solid[y,  1:]
//       random_choice picks one of L/R when both valid
//       gate by (rng < side_prob)
//       # apply slump sideways
//
// Two passes — ping-pong storage buffers. Pass 1 = vertical fall;
// pass 2 = sideways slump. Each thread reads from ``mask_in`` /
// ``loose_in`` and writes ``mask_out`` / ``loose_out`` with pull
// semantics — every thread owns ONE output pixel and decides what
// (if anything) flowed into it this pass. Pull semantics dodges
// the race condition where two source pixels want to move into the
// same destination: each destination pixel resolves the conflict
// locally via a tie-break draw against rng_in[(y, x)].
//
// RNG: per-pixel ``rng_in`` is a u32 PCG32 state that BOTH the
// source pixel and any destination pixel hash to derive the same
// per-pixel roll. ``rng_out`` advances the source pixel's state
// once per pass. Reads use ``rng_in`` only — no in-pass races.
//
// Bindings (group 0)
// ------------------
//   binding 0  mask_in       : array<u32>          storage read   (packed rgba8 H*W)
//   binding 1  mask_out      : array<u32>          storage write  (packed rgba8 H*W)
//   binding 2  loose_in      : array<u32>          storage read   (0 / 1 H*W)
//   binding 3  loose_out     : array<u32>          storage write  (0 / 1 H*W)
//   binding 4  fixed_mask    : array<u32>          storage read   (0 / 1 H*W)
//   binding 5  rng_in        : array<u32>          storage read   (PCG32 H*W)
//   binding 6  rng_out       : array<u32>          storage write  (PCG32 H*W)
//   binding 7  params        : Params              uniform
//
// Workgroup size: 8 x 8 = 64 threads. 2D dispatch over (W, H).
// ---------------------------------------------------------------

struct Params {
    fall_prob       : f32,
    side_prob       : f32,
    slump_step      : f32,  // unused in v1 (drop-threshold reserved for follow-up)
    width           : u32,
    height          : u32,
    protect_y_above : u32,  // rows with y < protect_y_above are skipped (untouched)
    pass_kind       : u32,  // 0 = fall, 1 = slump
    _pad            : u32,
};

@group(0) @binding(0) var<storage, read>  mask_in    : array<u32>;
@group(0) @binding(1) var<storage, read_write> mask_out   : array<u32>;
@group(0) @binding(2) var<storage, read>  loose_in   : array<u32>;
@group(0) @binding(3) var<storage, read_write> loose_out  : array<u32>;
@group(0) @binding(4) var<storage, read>  fixed_mask : array<u32>;
@group(0) @binding(5) var<storage, read>  rng_in     : array<u32>;
@group(0) @binding(6) var<storage, read_write> rng_out    : array<u32>;
@group(0) @binding(7) var<uniform>        params     : Params;

// -- PCG32 helpers --------------------------------------------------
// Keep in lockstep with the CPU mirror in particle_gpu._pcg32_step.

fn pcg32(state: u32) -> u32 {
    return state * 747796405u + 2891336453u;
}

fn pcg32_u01(state: u32) -> f32 {
    // Output in [0, 1) — same form used by particle_slide.wgsl.
    let s = state;
    let shift = ((s >> 28u) + 4u);
    var word = ((s >> shift) ^ s) * 277803737u;
    word = (word >> 22u) ^ word;
    return f32(word >> 8u) * (1.0 / 16777216.0);
}

// Hash a base seed with a salt so different rolls (vertical vs.
// sideways vs. tie-break) at the same pixel don't collide.
fn rng_roll(seed: u32, salt: u32) -> f32 {
    return pcg32_u01(pcg32(seed ^ (salt * 2654435761u)));
}

fn idx(x: u32, y: u32) -> u32 {
    return y * params.width + x;
}

fn is_solid_in(x: i32, y: i32) -> bool {
    if (x < 0 || y < 0 ||
        u32(x) >= params.width || u32(y) >= params.height) {
        // Treat out-of-bounds as solid (walls). Matches CPU's
        // y in range(H-2, 0, -1) which never falls below H-2.
        return true;
    }
    let p = mask_in[idx(u32(x), u32(y))];
    let a = (p >> 24u) & 0xFFu;
    return a > 0u;
}

fn is_loose_in(x: i32, y: i32) -> bool {
    if (x < 0 || y < 0 ||
        u32(x) >= params.width || u32(y) >= params.height) {
        return false;
    }
    return loose_in[idx(u32(x), u32(y))] != 0u;
}

fn is_fixed(x: i32, y: i32) -> bool {
    if (x < 0 || y < 0 ||
        u32(x) >= params.width || u32(y) >= params.height) {
        return true;
    }
    return fixed_mask[idx(u32(x), u32(y))] != 0u;
}

fn mask_at_in(x: u32, y: u32) -> u32 {
    return mask_in[idx(x, y)];
}

fn rng_at_in(x: i32, y: i32) -> u32 {
    if (x < 0 || y < 0 ||
        u32(x) >= params.width || u32(y) >= params.height) {
        return 0u;
    }
    return rng_in[idx(u32(x), u32(y))];
}

// "Does pixel (x, y) want to fall straight down this pass?"
// Mirrors CPU's   fall = row_loose & below_empty & (rng < fall_prob)
fn would_fall(x: i32, y: i32) -> bool {
    if (x < 0 || y < 0 ||
        u32(x) >= params.width || u32(y) >= params.height) {
        return false;
    }
    if (u32(y) < params.protect_y_above) {
        return false;
    }
    if (u32(y) + 1u >= params.height) {
        return false;          // CPU loop stops at H - 2
    }
    if (!is_loose_in(x, y)) {
        return false;
    }
    if (is_solid_in(x, y + 1)) {
        return false;          // pixel below is solid → can't fall
    }
    let r = rng_roll(rng_at_in(x, y), 0u);
    return r < params.fall_prob;
}

// Sideways slump intent — returns -1 (left), +1 (right), or 0 (none).
// Mirrors CPU's direction-balanced left/right pick.
fn slump_direction(x: i32, y: i32) -> i32 {
    if (x < 0 || y < 0 ||
        u32(x) >= params.width || u32(y) >= params.height) {
        return 0;
    }
    if (u32(y) < params.protect_y_above) {
        return 0;
    }
    if (u32(y) + 1u >= params.height) {
        return 0;
    }
    if (!is_loose_in(x, y)) {
        return 0;
    }
    if (!is_solid_in(x, y + 1)) {
        return 0;              // CPU restricts slump to ``still`` (no fall)
    }
    let seed = rng_at_in(x, y);
    let can_left = (x - 1 >= 0)
                 && !is_solid_in(x - 1, y)
                 && !is_solid_in(x - 1, y + 1);
    let can_right = (u32(x + 1) < params.width)
                  && !is_solid_in(x + 1, y)
                  && !is_solid_in(x + 1, y + 1);
    if (!can_left && !can_right) {
        return 0;
    }
    var go_left  = can_left;
    var go_right = can_right;
    if (can_left && can_right) {
        // Coin flip — mirrors CPU random_choice tie-breaker.
        let coin = rng_roll(seed, 1u);
        if (coin < 0.5) {
            go_right = false;
        } else {
            go_left = false;
        }
    }
    // Final probability gate per side (CPU applies a per-side roll).
    if (go_left) {
        let rl = rng_roll(seed, 2u);
        if (rl < params.side_prob) {
            return -1;
        }
    }
    if (go_right) {
        let rr = rng_roll(seed, 3u);
        if (rr < params.side_prob) {
            return 1;
        }
    }
    return 0;
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let x = gid.x;
    let y = gid.y;
    if (x >= params.width || y >= params.height) {
        return;
    }

    let self_idx = idx(x, y);
    let self_mask = mask_at_in(x, y);
    let self_loose = loose_in[self_idx];

    // Default — keep self. Advance rng_out so it lock-steps with the
    // CPU mirror (one advance per pass).
    var out_mask  = self_mask;
    var out_loose = self_loose;

    // Fixed pixels NEVER move — the original crater bowl stays open.
    if (is_fixed(i32(x), i32(y))) {
        mask_out[self_idx]  = self_mask;
        loose_out[self_idx] = self_loose;
        rng_out[self_idx]   = pcg32(rng_in[self_idx]);
        return;
    }

    let xi = i32(x);
    let yi = i32(y);

    if (params.pass_kind == 0u) {
        // ── Pass 1: vertical fall ────────────────────────────────────
        // SOURCE: if THIS pixel decides to fall, clear it.
        if (would_fall(xi, yi)) {
            out_mask  = self_mask & 0x00FFFFFFu;   // alpha = 0
            out_loose = 0u;
        } else if (yi - 1 >= 0 && !is_solid_in(xi, yi)) {
            // DEST: if the pixel above decided to fall AND we're empty,
            // pull its value down. We re-evaluate the source decision
            // using the same rng_in so the source/dest threads agree.
            if (would_fall(xi, yi - 1)) {
                out_mask  = mask_at_in(x, u32(yi - 1));
                out_loose = 1u;
            }
        }
    } else {
        // ── Pass 2: sideways slump ───────────────────────────────────
        // SOURCE: if THIS pixel chooses L or R, clear it.
        let my_dir = slump_direction(xi, yi);
        if (my_dir != 0) {
            out_mask  = self_mask & 0x00FFFFFFu;
            out_loose = 0u;
        } else if (!is_solid_in(xi, yi)) {
            // DEST: check both neighbours; if either wants to move
            // INTO me, accept the pull. If BOTH want me, tie-break
            // against my own rng_in slot.
            var pulled_from = 0;   // 0 = none, -1 = from left, +1 = from right
            if (xi - 1 >= 0) {
                let dl = slump_direction(xi - 1, yi);
                if (dl == 1) { pulled_from = -1; }
            }
            if (u32(xi + 1) < params.width) {
                let dr = slump_direction(xi + 1, yi);
                if (dr == -1) {
                    if (pulled_from == 0) {
                        pulled_from = 1;
                    } else {
                        // Both sides want me — tie-break.
                        let pick = rng_roll(rng_in[self_idx], 4u);
                        if (pick >= 0.5) {
                            pulled_from = 1;
                        }
                    }
                }
            }
            if (pulled_from == -1) {
                out_mask  = mask_at_in(u32(xi - 1), y);
                out_loose = 1u;
            } else if (pulled_from == 1) {
                out_mask  = mask_at_in(u32(xi + 1), y);
                out_loose = 1u;
            }
        }
    }

    mask_out[self_idx]  = out_mask;
    loose_out[self_idx] = out_loose;
    rng_out[self_idx]   = pcg32(rng_in[self_idx]);
}
