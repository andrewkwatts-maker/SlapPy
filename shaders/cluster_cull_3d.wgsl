// cluster_cull_3d.wgsl
// Sphere-AABB light culling — bins 3D point lights into the 16×9×24 cluster
// grid built by cluster_build_3d.wgsl.
//
// Overview
// --------
// One thread per light.  Each thread tests its light's view-space sphere
// against every cluster AABB.  When the sphere overlaps a cluster the light
// index is appended (atomically) to that cluster's slot in light_grid, and
// light_count_grid is incremented.
//
// Must be dispatched AFTER cluster_build_3d has finished writing the cluster
// AABBs.  The CPU is responsible for enforcing this ordering (separate command
// encoder submissions or an explicit pipeline barrier between the two passes).
//
// Sphere-AABB intersection
// ------------------------
// For each cluster AABB [min_pt, max_pt]:
//   closest = clamp(sphere_center, min_pt, max_pt)
//   dist_sq = dot(closest - sphere_center, closest - sphere_center)
//   overlap = dist_sq < radius²
//
// light_grid layout
// -----------------
// For cluster c, the light indices occupy:
//   light_grid[c * (MAX_LIGHTS_PER_CLUSTER + 1) + 0]  — reserved (unused, kept
//     for potential future use as a count mirror; use light_count_grid for count)
//   light_grid[c * (MAX_LIGHTS_PER_CLUSTER + 1) + 1]  — first light index
//   light_grid[c * (MAX_LIGHTS_PER_CLUSTER + 1) + 2]  — second light index
//   ...
//   light_grid[c * (MAX_LIGHTS_PER_CLUSTER + 1) + MAX_LIGHTS_PER_CLUSTER]
//
// The fragment shader (mesh_frag_clustered_pbr.wgsl) reads light indices as:
//   light_grid[cluster_idx * (MAX_LIGHTS_PER_CLUSTER + 1u) + i]
// where i runs from 0 to light_count_grid[cluster_idx] - 1, matching the
// convention used when writing (slot 0 = first valid index).
//
// Dispatch
// --------
// Dispatch ceil(light_count / 64) workgroups of size (64, 1, 1).
// Each invocation handles one light.
//
// Binding layout
// --------------
//   group(0) binding(0) — ClusterCullUniforms  (uniform)
//   group(0) binding(1) — lights[]             (storage, read)
//   group(0) binding(2) — clusters[]           (storage, read)     [from build pass]
//   group(0) binding(3) — light_grid[]         (storage, read_write)
//   group(0) binding(4) — light_count_grid[]   (storage, read_write, atomic<u32>)

// ---------------------------------------------------------------------------
// Constants  (must match cluster_build_3d.wgsl and mesh_frag_clustered_pbr.wgsl)
// ---------------------------------------------------------------------------

const MAX_LIGHTS:             u32 = 256u;
const MAX_LIGHTS_PER_CLUSTER: u32 = 64u;
const TOTAL_CLUSTERS:         u32 = 3456u;  // 16 * 9 * 24

// ---------------------------------------------------------------------------
// Structs
// ---------------------------------------------------------------------------

// A single 3D point light in view space.
// Both fields are vec4<f32> to satisfy WGSL 16-byte struct alignment without
// extra explicit padding.
struct GpuLight3D {
    // xyz = view-space position, w = effective radius.
    pos_radius:       vec4<f32>,
    // xyz = linear RGB colour, w = intensity multiplier.
    color_intensity:  vec4<f32>,
}

struct ClusterCullUniforms {
    // World-to-view matrix.  Multiply world-space light positions by this to
    // get the view-space positions used for cluster intersection testing.
    view:        mat4x4<f32>,
    // Number of valid entries in the lights[] array.
    light_count: u32,
    // Explicit padding to 32-byte boundary.
    _pad0: u32,
    _pad1: u32,
    _pad2: u32,
}

// Re-declare ClusterAABB here so this shader compiles independently.
// The actual data is written by cluster_build_3d.wgsl.
struct ClusterAABB {
    min_pt: vec4<f32>,  // xyz = view-space min, w = _pad
    max_pt: vec4<f32>,  // xyz = view-space max, w = _pad
}

// ---------------------------------------------------------------------------
// Bindings
// ---------------------------------------------------------------------------

@group(0) @binding(0) var<uniform>             u:                ClusterCullUniforms;
@group(0) @binding(1) var<storage, read>       lights:           array<GpuLight3D>;
@group(0) @binding(2) var<storage, read>       clusters:         array<ClusterAABB>;
// Flat light index list.  Stride per cluster = MAX_LIGHTS_PER_CLUSTER + 1 u32s.
@group(0) @binding(3) var<storage, read_write> light_grid:       array<u32>;
// Atomic per-cluster light counts.  One u32 per cluster.
@group(0) @binding(4) var<storage, read_write> light_count_grid: array<atomic<u32>>;

// ---------------------------------------------------------------------------
// Helper: sphere–AABB overlap test
// ---------------------------------------------------------------------------

fn sphere_aabb_overlap(center: vec3<f32>, radius: f32,
                        aabb_min: vec3<f32>, aabb_max: vec3<f32>) -> bool {
    // Find the closest point on the AABB to the sphere centre.
    let closest = clamp(center, aabb_min, aabb_max);
    let d        = closest - center;
    return dot(d, d) < radius * radius;
}

// ---------------------------------------------------------------------------
// Compute entry point
// ---------------------------------------------------------------------------
// Each invocation handles one light and tests it against all TOTAL_CLUSTERS.

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) id: vec3<u32>) {
    let light_idx = id.x;

    // Bounds guard — discard padding invocations.
    if light_idx >= min(u.light_count, MAX_LIGHTS) { return; }

    let light = lights[light_idx];

    // Transform light position from world space to view space.
    let world_pos4  = vec4<f32>(light.pos_radius.xyz, 1.0);
    let view_pos4   = u.view * world_pos4;
    let view_center = view_pos4.xyz;
    let radius      = light.pos_radius.w;

    // Test against every cluster AABB.
    for (var c = 0u; c < TOTAL_CLUSTERS; c = c + 1u) {
        let aabb = clusters[c];
        if sphere_aabb_overlap(view_center, radius,
                               aabb.min_pt.xyz, aabb.max_pt.xyz) {
            // Atomically reserve a slot in this cluster.
            // Stride = MAX_LIGHTS_PER_CLUSTER + 1 (slot 0 = first index).
            let slot = atomicAdd(&light_count_grid[c], 1u);
            if slot < MAX_LIGHTS_PER_CLUSTER {
                // Write light index at slot offset within the cluster's range.
                light_grid[c * (MAX_LIGHTS_PER_CLUSTER + 1u) + slot] = light_idx;
            } else {
                // Cluster is full — undo the increment so that the count
                // remains accurate for the fragment shader's min() clamp and
                // for any diagnostic CPU readbacks.
                atomicSub(&light_count_grid[c], 1u);
            }
        }
    }
}
