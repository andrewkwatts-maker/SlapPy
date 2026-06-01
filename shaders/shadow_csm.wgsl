// shadow_csm.wgsl — Cascaded Shadow Maps (CSM) compute pass
// Generates a shadow mask texture for use by the 3D PBR lighting pipeline.
//
// Algorithm overview:
//   For each screen pixel:
//     1. Reconstruct view-space position from the G-buffer depth + inv_proj.
//     2. Select the tightest cascade whose split distance covers the pixel's
//        view-space Z.
//     3. Project the world position into that cascade's light-clip space.
//     4. Sample the cascade shadow map with a 3×3 PCF kernel (9 taps).
//     5. Write the averaged shadow factor to shadow_mask (r8unorm).
//        1.0 = fully lit, 0.0 = fully in shadow.
//
// Bind groups:
//   group(0) binding(0) — CsmParams     (uniform)
//   group(0) binding(1) — depth_tex     texture_2d<f32>       (scene depth, r32float)
//   group(0) binding(2) — shadow_maps   texture_2d_array<f32> (4 cascade depth maps)
//   group(0) binding(3) — InvProjBuf    (uniform, 64-byte mat4x4)
//   group(0) binding(4) — shadow_mask   texture_storage_2d<r8unorm, write>

// ── Uniform structs ────────────────────────────────────────────────────────

// CsmParams — 336 bytes total (std140 compatible)
//   cascade_vp   : array<mat4x4<f32>, 4>   offset   0  (256 bytes)
//   split_dists  : vec4<f32>               offset 256  ( 16 bytes)
//   light_dir    : vec3<f32>               offset 272  ( 12 bytes)
//   num_cascades : u32                     offset 284  (  4 bytes)
//   depth_bias   : f32                     offset 288  (  4 bytes)
//   pcf_radius   : f32                     offset 292  (  4 bytes)
//   width        : u32                     offset 296  (  4 bytes)
//   height       : u32                     offset 300  (  4 bytes)
//   pcss_enabled : u32                     offset 304  (  4 bytes) — 0 = PCF only, 1 = PCSS
//   light_size   : f32                     offset 308  (  4 bytes) — PCSS light angular size (world units)
//   near         : f32                     offset 312  (  4 bytes) — shadow camera near plane
//   pcf_samples  : u32                     offset 316  (  4 bytes) — Vogel-disk tap count (0 = legacy 3×3 grid)
struct CsmParams {
    cascade_vp:   array<mat4x4<f32>, 4>,
    split_dists:  vec4<f32>,
    light_dir:    vec3<f32>,
    num_cascades: u32,
    depth_bias:   f32,
    pcf_radius:   f32,
    width:        u32,
    height:       u32,
    pcss_enabled: u32,
    light_size:   f32,
    near:         f32,
    pcf_samples:  u32,
}

// Thin wrapper so inv_proj occupies its own 64-byte uniform slot.
struct InvProjBuf {
    mat: mat4x4<f32>,
}

// ── Bindings ───────────────────────────────────────────────────────────────

@group(0) @binding(0) var<uniform> params      : CsmParams;
@group(0) @binding(1) var          depth_tex   : texture_2d<f32>;
@group(0) @binding(2) var          shadow_maps : texture_2d_array<f32>;
@group(0) @binding(3) var<uniform> inv_proj    : InvProjBuf;
@group(0) @binding(4) var          shadow_mask : texture_storage_2d<r8unorm, write>;

// ── Helper: reconstruct view-space position from NDC depth ─────────────────
// ndc_xy  : pixel centre in [-1, 1] (x right, y up, WGPU convention)
// depth   : raw depth value from depth_tex (0..1, perspective)
// Returns : view-space position (z is negative in front of camera, RH coords)
fn view_pos_from_depth(ndc_xy: vec2f, depth: f32) -> vec3f {
    // Build NDC position. WGPU uses z in [0,1] for the depth buffer.
    let ndc  = vec4f(ndc_xy, depth, 1.0);
    // Unproject to view space.
    let view = inv_proj.mat * ndc;
    return view.xyz / view.w;
}

// ── Helper: PCF shadow test for one cascade ────────────────────────────────
// Samples a 3×3 neighbourhood around the projected UV and averages the result.
// Returns 1.0 if fully lit, 0.0 if fully occluded.
fn pcf_shadow(
    light_pos_ndc: vec3f,   // position in light clip-space [-1,1] xy, [0,1] z
    cascade_idx:   i32,
    depth_bias:    f32,
    pcf_radius:    f32,
) -> f32 {
    // Convert light NDC xy to shadow-map UV [0,1].
    let uv_center = light_pos_ndc.xy * vec2f(0.5, -0.5) + vec2f(0.5);
    let ref_depth = light_pos_ndc.z - depth_bias;

    // Shadow map texel size in UV space.
    let shadow_dims = vec2f(textureDimensions(shadow_maps, 0));
    let texel_size  = pcf_radius / shadow_dims;

    var lit = 0.0;
    // 3×3 kernel — 9 taps.
    for (var ky = -1; ky <= 1; ky++) {
        for (var kx = -1; kx <= 1; kx++) {
            let offset   = vec2f(f32(kx), f32(ky)) * texel_size;
            let sample_uv = uv_center + offset;

            // Clamp to [0,1] so border pixels don't sample across the edge.
            let clamped_uv = clamp(sample_uv, vec2f(0.0), vec2f(1.0));
            let texel_coord = vec2i(vec2f(shadow_dims) * clamped_uv);

            let shadow_depth = textureLoad(shadow_maps, texel_coord, cascade_idx, 0).r;
            // 1.0 if the surface is closer to the light than what the shadow map recorded.
            lit += select(0.0, 1.0, ref_depth <= shadow_depth);
        }
    }
    return lit / 9.0;
}

// ── Vogel-disk PCF (Persson 2012) ──────────────────────────────────────────
// Vogel/golden-angle spiral gives a low-discrepancy disk distribution that
// looks smoother than a 3×3 grid for the same tap budget.  The per-pixel
// rotation derived from a hashed UV breaks up banding by varying the spiral
// orientation across screen space.
//
// Formula (Persson 2012, "Low-Level Thinking in High-Level Shading Languages"):
//   r     = sqrt((n + 0.5) / N) * radius
//   theta = n * GOLDEN_ANGLE + per_pixel_rotation
//   offset_uv = (r * cos(theta), r * sin(theta)) * texel_size
//
// GOLDEN_ANGLE = π * (3 − √5) ≈ 2.39996323 radians.
const VOGEL_GOLDEN_ANGLE: f32 = 2.3999632;

// Hash a vec2 into a scalar in [0, 2π) for per-pixel spiral rotation.
// Avoids visible spiral banding by giving every screen pixel a unique phase.
fn vogel_rotation(uv: vec2<f32>) -> f32 {
    let h = fract(sin(dot(uv, vec2<f32>(12.9898, 78.233))) * 43758.5453);
    return h * 6.2831853;  // 2π
}

// Vogel-disk PCF — N taps spiraling outward on a unit disk.  Each tap is
// scaled by `pcf_radius` (in texels) and rotated by a per-pixel phase to
// hide spiral structure.  Returns 1.0 if fully lit, 0.0 if fully occluded.
fn vogel_pcf_shadow(
    light_pos_ndc: vec3f,
    cascade_idx:   i32,
    depth_bias:    f32,
    pcf_radius:    f32,
    num_taps:      u32,
) -> f32 {
    let uv_center = light_pos_ndc.xy * vec2f(0.5, -0.5) + vec2f(0.5);
    let ref_depth = light_pos_ndc.z - depth_bias;

    let shadow_dims = vec2f(textureDimensions(shadow_maps, 0));
    let texel_size  = pcf_radius / shadow_dims;
    let phase       = vogel_rotation(uv_center);
    let inv_n       = 1.0 / f32(num_taps);

    var lit = 0.0;
    for (var i = 0u; i < num_taps; i++) {
        let n     = f32(i);
        let r     = sqrt((n + 0.5) * inv_n);
        let theta = n * VOGEL_GOLDEN_ANGLE + phase;
        let offset_uv = vec2f(r * cos(theta), r * sin(theta)) * texel_size;
        let sample_uv = clamp(uv_center + offset_uv, vec2f(0.0), vec2f(1.0));
        let texel_coord = vec2i(shadow_dims * sample_uv);

        let shadow_depth = textureLoad(shadow_maps, texel_coord, cascade_idx, 0).r;
        lit += select(0.0, 1.0, ref_depth <= shadow_depth);
    }
    return lit * inv_n;
}

// ── PCSS: Poisson disk samples (32 samples) ───────────────────────────────

const POISSON_DISK_32: array<vec2<f32>, 32> = array<vec2<f32>, 32>(
    vec2(-0.613392, 0.617481), vec2(0.170019, -0.040254),
    vec2(-0.299417, 0.791925), vec2(0.645680, 0.493210),
    vec2(-0.651784, 0.717887), vec2(0.421003, 0.027070),
    vec2(-0.817194, -0.271096), vec2(-0.705374, -0.668203),
    vec2(0.977050, -0.108615), vec2(0.063326, 0.142369),
    vec2(0.203528, 0.214331), vec2(-0.667531, 0.326090),
    vec2(-0.098422, -0.295755), vec2(-0.885922, 0.215369),
    vec2(0.566637, 0.605213), vec2(0.039766, -0.396100),
    vec2(0.751946, 0.453352), vec2(0.078707, -0.715323),
    vec2(-0.075838, -0.529344), vec2(0.724479, -0.580798),
    vec2(0.222999, -0.215125), vec2(-0.467574, -0.405438),
    vec2(-0.248268, -0.814753), vec2(0.354411, -0.887570),
    vec2(0.175817, 0.382366), vec2(0.487472, -0.063082),
    vec2(-0.084078, 0.898312), vec2(0.488876, -0.783441),
    vec2(0.470016, 0.217933), vec2(-0.696890, -0.549791),
    vec2(-0.149693, 0.605762), vec2(0.034211, 0.979980),
);

// ── PCSS pass A: blocker search (16 samples from the Poisson disk) ────────
// Returns the average depth of blockers closer than receiver_depth, or -1.0
// if there are no blockers (surface is fully lit).
fn blocker_search(
    shadow_map:     texture_2d_array<f32>,
    shadow_uv:      vec2<f32>,
    cascade_idx:    i32,
    receiver_depth: f32,
    light_size:     f32,
    near:           f32,
) -> f32 {
    let shadow_dims = vec2<f32>(textureDimensions(shadow_map, 0));
    let search_radius = light_size * (receiver_depth - near) / receiver_depth;
    var total_depth = 0.0;
    var count = 0.0;
    for (var i = 0u; i < 16u; i++) {
        let offset_uv = POISSON_DISK_32[i] * search_radius;
        let sample_uv = clamp(shadow_uv + offset_uv, vec2<f32>(0.0), vec2<f32>(1.0));
        let texel     = vec2<i32>(shadow_dims * sample_uv);
        let blocker_depth = textureLoad(shadow_map, texel, cascade_idx, 0).r;
        if blocker_depth < receiver_depth {
            total_depth += blocker_depth;
            count += 1.0;
        }
    }
    return select(-1.0, total_depth / count, count > 0.0);
}

// ── PCSS pass B: PCF with penumbra-scaled kernel (32 Poisson samples) ────
// light_ndc  : position in light clip-space [-1,1] xy, [0,1] z
// light_size : angular size of the light source (world units)
// near       : shadow camera near-plane distance (world units)
// Returns 1.0 if fully lit, 0.0 if fully occluded.
fn pcss_shadow(
    light_ndc:   vec3<f32>,
    cascade_idx: i32,
    depth_bias:  f32,
    light_size:  f32,
    near:        f32,
) -> f32 {
    let shadow_uv    = light_ndc.xy * vec2<f32>(0.5, -0.5) + vec2<f32>(0.5);
    let receiver_depth = light_ndc.z - depth_bias;

    let avg_blocker = blocker_search(
        shadow_maps, shadow_uv, cascade_idx, receiver_depth, light_size, near,
    );
    // No blockers found — surface is fully lit.
    if avg_blocker < 0.0 { return 1.0; }

    // Penumbra width proportional to (receiver − blocker) distance.
    let penumbra = (receiver_depth - avg_blocker) / avg_blocker * light_size * 4.0;

    let shadow_dims = vec2<f32>(textureDimensions(shadow_maps, 0));
    var lit = 0.0;
    for (var i = 0u; i < 32u; i++) {
        let offset_uv = POISSON_DISK_32[i] * penumbra;
        let sample_uv = clamp(shadow_uv + offset_uv, vec2<f32>(0.0), vec2<f32>(1.0));
        let texel     = vec2<i32>(shadow_dims * sample_uv);
        let shadow_depth = textureLoad(shadow_maps, texel, cascade_idx, 0).r;
        lit += select(0.0, 1.0, receiver_depth <= shadow_depth);
    }
    return lit / 32.0;
}

// ── Compute entry point ────────────────────────────────────────────────────

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let px = gid.x;
    let py = gid.y;
    if px >= params.width || py >= params.height { return; }

    // ── 1. Load scene depth ────────────────────────────────────────────────
    let raw_depth = textureLoad(depth_tex, vec2i(i32(px), i32(py)), 0).r;

    // Skybox / far-plane pixels are at depth == 1.0 (or very close).
    // They receive no shadow — write 1.0 and exit early.
    if raw_depth >= 0.9999 {
        textureStore(shadow_mask, vec2i(i32(px), i32(py)), vec4f(1.0));
        return;
    }

    // ── 2. Reconstruct view-space position ────────────────────────────────
    // Convert pixel to NDC [-1, 1].  WGPU: y=0 is top, NDC y=+1 is up.
    let ndc_x = (f32(px) + 0.5) / f32(params.width)  *  2.0 - 1.0;
    let ndc_y = (f32(py) + 0.5) / f32(params.height) * -2.0 + 1.0;
    let view_p = view_pos_from_depth(vec2f(ndc_x, ndc_y), raw_depth);

    // View-space Z is negative in front of camera (right-handed convention).
    // Use |view_z| for cascade comparison against positive split distances.
    let view_z = -view_p.z;

    // ── 3. Select cascade ──────────────────────────────────────────────────
    // Iterate from the finest cascade outward; pick the first cascade whose
    // far split distance is beyond the current pixel's view depth.
    var cascade_idx = i32(params.num_cascades) - 1;  // fallback: coarsest
    let num = i32(params.num_cascades);
    for (var i = 0; i < num; i++) {
        // split_dists[i] is the far-plane of cascade i in view-space Z.
        if view_z < params.split_dists[i] {
            cascade_idx = i;
            break;
        }
    }

    // ── 4. Project into light clip space ──────────────────────────────────
    // We reconstruct world position from view position by inverting the view
    // transform.  However, since CSM VP matrices encode the full world→light
    // clip transform, we need world-space position.  We get it by applying
    // the inverse-view (not supplied as a separate matrix), but instead we
    // embed world-pos reconstruction in the GPU by passing inv_proj which
    // goes from clip → view.  For the directional-light projection we need
    // world space.  A common compact solution: store the camera-view-inverse
    // in the upper-left 3×3 of inv_proj (orthonormal, so transposing is its
    // inverse rotation) and derive the translation from inv_proj * (0,0,0,1).
    //
    // Here we do the proper reconstruction:
    //   world_pos = inv_view * view_pos
    // Since inv_proj already took us to view space from clip space, we need
    // the camera world position.  We obtain that from inv_proj * origin.
    let cam_world = (inv_proj.mat * vec4f(0.0, 0.0, 0.0, 1.0)).xyz;

    // Reconstruct world position: rotate view_p back using the transposed
    // rotation block (columns 0-2, rows 0-2 of inv_proj).
    let inv_rot = mat3x3<f32>(
        inv_proj.mat[0].xyz,
        inv_proj.mat[1].xyz,
        inv_proj.mat[2].xyz,
    );
    let world_p = inv_rot * view_p + cam_world;

    // Project world position into cascade light clip space.
    let light_clip = params.cascade_vp[cascade_idx] * vec4f(world_p, 1.0);

    // Perspective divide (directional lights are orthographic so w≈1, but
    // handle correctly for generality).
    let light_ndc = light_clip.xyz / light_clip.w;

    // ── 5. Bounds check — outside the cascade frustum → assume lit ─────────
    if any(light_ndc.xy < vec2f(-1.0)) || any(light_ndc.xy > vec2f(1.0))
       || light_ndc.z < 0.0 || light_ndc.z > 1.0 {
        textureStore(shadow_mask, vec2i(i32(px), i32(py)), vec4f(1.0));
        return;
    }

    // ── 6. Shadow sampling — PCSS / Vogel PCF / legacy 3×3 grid ────────────
    // Selection precedence:
    //   1. pcss_enabled == 1 → PCSS (penumbra-scaled Poisson PCF)
    //   2. pcf_samples  >  0 → Vogel-disk PCF with N taps (Persson 2012)
    //   3. otherwise         → legacy fixed 3×3 grid (9 taps, back-compat)
    var shadow_factor: f32;
    if params.pcss_enabled != 0u {
        shadow_factor = pcss_shadow(
            light_ndc,
            cascade_idx,
            params.depth_bias,
            params.light_size,
            params.near,
        );
    } else if params.pcf_samples > 0u {
        shadow_factor = vogel_pcf_shadow(
            light_ndc,
            cascade_idx,
            params.depth_bias,
            params.pcf_radius,
            params.pcf_samples,
        );
    } else {
        shadow_factor = pcf_shadow(
            light_ndc,
            cascade_idx,
            params.depth_bias,
            params.pcf_radius,
        );
    }

    // ── 7. Write result ────────────────────────────────────────────────────
    // r8unorm stores the shadow factor: 1.0 = fully lit, 0.0 = fully shadowed.
    textureStore(shadow_mask, vec2i(i32(px), i32(py)), vec4f(shadow_factor, 0.0, 0.0, 1.0));
}
