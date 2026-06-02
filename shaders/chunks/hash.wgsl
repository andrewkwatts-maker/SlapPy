// hash.wgsl — Cheap integer hashes and PRNG helpers shared across passes.
//
// These are the standard "wellons" / PCG-flavoured integer hashes plus a few
// utilities for turning u32 state into [0, 1) floats and 2-/3-component
// vectors.  None of these are cryptographic — they're tuned for visual noise.

// 32-bit integer hash (Murmur-style finalizer).
fn hash_u(v: u32) -> u32 {
    var x = v;
    x ^= x >> 16u;
    x *= 0x45d9f3bu;
    x ^= x >> 16u;
    return x;
}

// Map a u32 hash to a float in [0, 1).
fn hash_to_f32(h: u32) -> f32 {
    return f32(h & 0x00FFFFFFu) / f32(0x01000000u);
}

// 2D integer hash → [0, 1) float, seeded.
fn hash2(x: u32, y: u32, seed: u32) -> f32 {
    return hash_to_f32(hash_u(hash_u(x) ^ hash_u(y ^ seed)));
}

// LCG-style PRNG step.  `state` is updated in place; the returned float is in
// [0, 1).  Usage:
//     var rng_state: u32 = seed;
//     let r = rand_f32(&rng_state);
fn rand_f32(state: ptr<function, u32>) -> f32 {
    *state = (*state) * 747796405u + 2891336453u;
    var word = ((*state) >> (((*state) >> 28u) + 4u)) ^ (*state);
    word = word * 277803737u;
    return f32((word >> 22u) ^ word) / 4294967295.0;
}
