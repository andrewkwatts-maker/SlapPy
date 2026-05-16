// cluster_build_3d.wgsl
// 3D frustum cluster AABB builder.
//
// Overview
// --------
// Partitions the view frustum into a 16×9×24 grid (3 456 total clusters).
// Each cluster is an axis-aligned bounding box (AABB) expressed in view space.
// Run this shader once whenever the camera projection changes; the results are
// consumed by cluster_cull_3d.wgsl, which bins lights into the clusters, and
// by mesh_frag_clustered_pbr.wgsl, which looks up the active light list for
// each fragment.
//
// Grid conventions
// ----------------
//   X tiles  — 16 columns, uniform in screen-space NDC X [-1, 1]
//   Y tiles  —  9 rows,    uniform in screen-space NDC Y [-1, 1]
//   Z slices — 24 slices,  exponential (logarithmic) along view-space -Z
//
// Exponential depth slicing
// -------------------------
// Slice i spans the depth range [z_near(i), z_near(i+1)] where:
//
//   z_near(i) = near * (far / near) ^ (i / 24)       (view-space magnitude)
//
// This distributes more slices near the camera (where lighting detail matters)
// and fewer at distance.
//
// Dispatch
// --------
// Dispatch (1, 1, 24) workgroups.
// Workgroup size is (16, 9, 1).
// Each invocation handles one XY tile and loops over the assigned Z slice:
//   global_id.x = tile_x  [0, 15]
//   global_id.y = tile_y  [0,  8]
//   global_id.z = slice   [0, 23]  (from the dispatch Z dimension)
//
// Binding layout
// --------------
//   group(0) binding(0) — ClusterBuildUniforms  (uniform)
//   group(0) binding(1) — clusters[]            (storage, read_write)

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TILES_X: u32 = 16u;
const TILES_Y: u32 = 9u;
const TILES_Z: u32 = 24u;
// Total clusters = 16 * 9 * 24 = 3456
const TOTAL_CLUSTERS: u32 = 3456u;

// ---------------------------------------------------------------------------
// Structs
// ---------------------------------------------------------------------------

struct ClusterBuildUniforms {
    // Inverse projection matrix — transforms clip-space coordinates to
    // view-space coordinates.  Build this on the CPU as inverse(proj).
    inv_proj: mat4x4<f32>,
    // Framebuffer dimensions in pixels.  Used to convert tile corners to NDC.
    screen_w: f32,
    screen_h: f32,
    // Camera near and far plane distances (positive magnitudes).
    near: f32,
    far:  f32,
    // Grid dimensions — must equal the constants above.  Stored here so the
    // CPU can validate they match without hard-coding them on both sides.
    tiles_x: u32,
    tiles_y: u32,
    tiles_z: u32,
    // Explicit padding to reach the next 16-byte boundary.
    _pad: u32,
}

struct ClusterAABB {
    // View-space minimum corner of this cluster.  w channel is unused (_pad).
    min_pt: vec4<f32>,
    // View-space maximum corner of this cluster.  w channel is unused (_pad).
    max_pt: vec4<f32>,
}

// ---------------------------------------------------------------------------
// Bindings
// ---------------------------------------------------------------------------

@group(0) @binding(0) var<uniform>            u:        ClusterBuildUniforms;
@group(0) @binding(1) var<storage, read_write> clusters: array<ClusterAABB>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Unproject a screen-space pixel coordinate at the given view-space depth (z
// is a positive magnitude; the actual view-space Z is negated internally).
// Returns the view-space XYZ position.
fn unproject_screen(px: vec2<f32>, view_z: f32) -> vec3<f32> {
    // Convert pixel position to NDC in [-1, 1].
    let ndc_x =  (px.x / u.screen_w) * 2.0 - 1.0;
    let ndc_y = -((px.y / u.screen_h) * 2.0 - 1.0); // Y flipped (screen Y down)

    // Build a clip-space point at the far end of the NDC depth range.
    // We will scale the result to match the requested view_z below.
    let clip = vec4<f32>(ndc_x, ndc_y, -1.0, 1.0);
    var view = u.inv_proj * clip;
    view = view / view.w;

    // view.xyz now lies on the far plane (or wherever -Z=1 maps).
    // Scale so that the view-space Z equals -view_z (camera looks down -Z).
    let scale = -view_z / view.z;
    return view.xyz * scale;
}

// ---------------------------------------------------------------------------
// Compute entry point
// ---------------------------------------------------------------------------
// Workgroup (16, 9, 1) — one thread per XY cluster, Z comes from dispatch.
// Dispatch as (1, 1, TILES_Z) to cover all 24 depth slices.

@compute @workgroup_size(16, 9, 1)
fn main(@builtin(global_invocation_id) id: vec3<u32>) {
    let tile_x = id.x;
    let tile_y = id.y;
    let tile_z = id.z; // provided by the dispatch Z dimension

    // Bounds guard — reject any extra invocations beyond the grid.
    if tile_x >= TILES_X || tile_y >= TILES_Y || tile_z >= TILES_Z {
        return;
    }

    // ── Flat cluster index ────────────────────────────────────────────────
    // Layout: cluster[x + y*TILES_X + z*TILES_X*TILES_Y]
    let cluster_idx = tile_x
                    + tile_y * TILES_X
                    + tile_z * (TILES_X * TILES_Y);

    // ── Screen-space tile corners (pixels) ───────────────────────────────
    let tile_w = u.screen_w / f32(TILES_X);
    let tile_h = u.screen_h / f32(TILES_Y);

    let px_min = vec2<f32>(f32(tile_x)       * tile_w,
                           f32(tile_y)       * tile_h);
    let px_max = vec2<f32>(f32(tile_x + 1u)  * tile_w,
                           f32(tile_y + 1u)  * tile_h);

    // ── Exponential depth slice boundaries ───────────────────────────────
    // z_near_i = near * (far/near)^(i/TILES_Z)
    // Expressed as positive view-space magnitudes; actual view Z is negative.
    let ratio    = u.far / u.near;
    let z_near_i = u.near * pow(ratio, f32(tile_z)      / f32(TILES_Z));
    let z_far_i  = u.near * pow(ratio, f32(tile_z + 1u) / f32(TILES_Z));

    // ── Unproject the four tile corners at near and far depth ─────────────
    // We need the 8 view-space corners to compute a tight AABB.
    let v000 = unproject_screen(px_min, z_near_i);
    let v100 = unproject_screen(px_max, z_near_i);
    let v010 = unproject_screen(vec2<f32>(px_min.x, px_max.y), z_near_i);
    let v110 = unproject_screen(vec2<f32>(px_max.x, px_min.y), z_near_i);

    let v001 = unproject_screen(px_min, z_far_i);
    let v101 = unproject_screen(px_max, z_far_i);
    let v011 = unproject_screen(vec2<f32>(px_min.x, px_max.y), z_far_i);
    let v111 = unproject_screen(vec2<f32>(px_max.x, px_min.y), z_far_i);

    // ── Build AABB from the 8 view-space corners ──────────────────────────
    var aabb_min = min(min(min(v000, v100), min(v010, v110)),
                       min(min(v001, v101), min(v011, v111)));
    var aabb_max = max(max(max(v000, v100), max(v010, v110)),
                       max(max(v001, v101), max(v011, v111)));

    // ── Write to the cluster buffer ───────────────────────────────────────
    clusters[cluster_idx].min_pt = vec4<f32>(aabb_min, 0.0);
    clusters[cluster_idx].max_pt = vec4<f32>(aabb_max, 0.0);
}
