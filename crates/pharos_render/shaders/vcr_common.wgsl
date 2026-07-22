// pharos_render :: VCR common definitions.
//
// Ported from Nova3D's design/vcr_pipeline.html §4 (Data layout) and
// §5 (Pipeline stages). Shared by all six VCR shader stages: seed,
// accumulate, merge, composite, temporal (optional), gbuffer feed.
//
// SSoT constants (VCR_K_SLOTS, VCR_RES_SCALE, VCR_ALPHA_DROP_THRESHOLD,
// VCR_COVERAGE_OPT_OUT, VCR_TEMPORAL_ENABLED) are injected by
// pharos_render::vcr::config::wgsl_define_block at pipeline creation
// time — do NOT edit them here.

// One reservoir slot. `precision = Half` layout (32 B):
//   pos       : fp16.xyz  (offset from world texel center; 6 B)
//   dir       : oct16     (unit vec3 encoded as 2xf16; 4 B)
//   cone      : fp16      (roughness-derived cone half-angle; 2 B)
//   alpha     : fp16      (accumulated throughput; 2 B)
//   phase     : fp16      (Beer-Lambert phase; 2 B)
//   distance  : fp16      (accumulated ray length; 2 B)
//   density   : fp16      (accumulated volumetric density; 2 B)
//   flags     : u16       (Persistent | Occluded | Diffractive | ...; 2 B)
//   material  : u32       (encoded material id + subslot; 4 B)
//   _pad      : u32                                                   (4 B)
//                                                              total: 32 B
//
// Storage: rgba32f textures. Slot i occupies texels (x, y, i*2) and
// (x, y, i*2+1) of a 3D texture whose z depth = K_SLOTS * 2. This
// layout lets us bind the reservoir as texture_storage_3d in every
// stage.

struct Slot {
    pos: vec3<f32>,
    matid: f32,             // packed material id (fp for texture I/O)
    dir: vec3<f32>,         // decoded from oct16 in seed; kept fp for merges
    cone: f32,
    alpha: f32,
    distance: f32,
    density: f32,
    flags: u32,
};

fn slot_zero() -> Slot {
    var s: Slot;
    s.pos = vec3<f32>(0.0);
    s.matid = 0.0;
    s.dir = vec3<f32>(0.0, 1.0, 0.0);
    s.cone = 0.0;
    s.alpha = 0.0;
    s.distance = 0.0;
    s.density = 0.0;
    s.flags = 0u;
    return s;
}

// -- Slot flag bits --
const FLAG_PERSISTENT:  u32 = 1u << 0u;
const FLAG_OCCLUDED:    u32 = 1u << 1u;
const FLAG_DIFFRACTIVE: u32 = 1u << 2u;
const FLAG_TIR:         u32 = 1u << 3u;  // total internal reflection
const FLAG_SEEDED:      u32 = 1u << 4u;

// -- Reservoir sampling --
//
// WRS (Weighted Reservoir Sampling): keep K best slots by streaming
// weight. Nova3D uses reservoir index = argmin(alpha) instead of
// argmax(weight) so persistent slots that accumulate alpha over time
// dominate — see VCR §5 Stage 3.
fn slot_score(s: Slot) -> f32 {
    // Higher = more valuable to keep. Persistent slots get a bonus so
    // temporal-stable specular highlights survive across frames.
    var bonus: f32 = 1.0;
    if ((s.flags & FLAG_PERSISTENT) != 0u) { bonus = 4.0; }
    return s.alpha * bonus;
}

// -- Sprint 1 Nova3D bug intake: pack/unpack helpers --
//
// Nova3D bug: accum shader called packOctU16 without defining it —
// duplicated helper declarations across stages diverged and one stage
// lost its copy after a refactor. Every pack/unpack helper lives here
// as the SSoT. Concatenated into every VCR stage at compile time via
// pharos_render::vcr::config::wgsl_define_block callers (they prepend
// this file's contents to each stage source).
//
// Octahedral encoding of a unit vec3 into 2xf16 (packed into a single
// u32). See Cigolle et al. 2014 "A Survey of Efficient Representations
// for Independent Unit Vectors".

fn signNotZero2(v: vec2<f32>) -> vec2<f32> {
    let sx = select(-1.0, 1.0, v.x >= 0.0);
    let sy = select(-1.0, 1.0, v.y >= 0.0);
    return vec2<f32>(sx, sy);
}

fn octEncode(n_in: vec3<f32>) -> vec2<f32> {
    let n = n_in / (abs(n_in.x) + abs(n_in.y) + abs(n_in.z));
    var uv: vec2<f32> = n.xy;
    if (n.z < 0.0) {
        uv = (vec2<f32>(1.0) - abs(vec2<f32>(n.y, n.x))) * signNotZero2(n.xy);
    }
    return uv;
}

fn octDecode(uv: vec2<f32>) -> vec3<f32> {
    var n: vec3<f32> = vec3<f32>(uv, 1.0 - abs(uv.x) - abs(uv.y));
    if (n.z < 0.0) {
        let s = signNotZero2(n.xy);
        n = vec3<f32>((1.0 - abs(vec2<f32>(n.y, n.x))) * s, n.z);
    }
    return normalize(n);
}

/// Pack a unit vec3 into two f16 lanes stored in a single u32.
/// Matches Nova3D `packOctU16`.
fn packOctU16(n: vec3<f32>) -> u32 {
    let uv = octEncode(n) * 0.5 + vec2<f32>(0.5);
    let ux = u32(clamp(uv.x, 0.0, 1.0) * 65535.0 + 0.5);
    let uy = u32(clamp(uv.y, 0.0, 1.0) * 65535.0 + 0.5);
    return (uy << 16u) | (ux & 0xFFFFu);
}

/// Recover a unit vec3 from a two-f16-lane u32.
/// Matches Nova3D `unpackOctU16`.
fn unpackOctU16(packed: u32) -> vec3<f32> {
    let ux = f32(packed & 0xFFFFu) / 65535.0;
    let uy = f32((packed >> 16u) & 0xFFFFu) / 65535.0;
    let uv = vec2<f32>(ux, uy) * 2.0 - vec2<f32>(1.0);
    return octDecode(uv);
}
