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
