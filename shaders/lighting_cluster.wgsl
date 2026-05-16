// 2D Clustered Lighting — tile-based light binning for many point lights.
//
// Overview
// --------
// Rather than running one full-screen compute dispatch per light (O(L) passes,
// each touching every pixel), this shader splits work into two passes:
//
//   Pass 1 — cull_lights (entry point: cull_lights)
//     One thread per tile. Tests each light's circle against the tile AABB.
//     Appends the light index to tile_light_indices and increments
//     tile_light_count via atomics. Each tile stores at most
//     max_lights_per_tile (64) indices.
//
//   Pass 2 — apply_cluster (entry point: apply_cluster)
//     One thread per pixel. Looks up its tile, iterates only the lights
//     recorded for that tile, accumulates the contribution, and writes the
//     result additively into accum_tex.
//
// Binding layout
// --------------
//   group 0, binding 0 — ClusterUniforms (uniform)
//   group 0, binding 1 — lights[]          (storage, read)
//   group 0, binding 2 — tile_light_count  (storage, read_write, atomic<u32>)
//   group 0, binding 3 — tile_light_indices(storage, read_write)
//   group 0, binding 4 — scene_tex         (texture_2d<f32>)       [Pass 2 only]
//   group 0, binding 5 — accum_tex         (texture_storage_2d)    [Pass 2 only]
//
// Coordinate system
// -----------------
// Pixel space: (0,0) = top-left, X right, Y down (matches wgpu texture coords).
// Light positions must be supplied in the same pixel-space coordinate system.
// No camera / view matrix is applied here; the caller must convert world
// positions to screen pixels before uploading the light buffer.
//
// Attenuation model
// -----------------
// Quadratic falloff: atten = (1 - dist/radius)^2, clamped to [0, 1].
// This matches the existing point-light shader (lighting_point.wgsl) so that
// switching between the two paths produces identical output.

// ---------------------------------------------------------------------------
// Structs
// ---------------------------------------------------------------------------

struct PointLightData {
    // XY position in screen-pixel coordinates.
    pos: vec2<f32>,
    // Effective radius in pixels.  Pixels outside this radius receive zero
    // contribution from this light.
    radius: f32,
    // Additive RGB colour (linear, HDR-range allowed).
    color: vec3<f32>,
    // Multiplier applied to the colour before accumulation.
    intensity: f32,
    // Explicit padding to satisfy WGSL's 16-byte struct alignment rule.
    // The GPU layout for PointLightData is:
    //   offset  0 — pos      (8 bytes)
    //   offset  8 — radius   (4 bytes)
    //   offset 12 — _pad0    (4 bytes)  ← fills 16-byte vec4 slot
    //   offset 16 — color    (12 bytes)
    //   offset 28 — intensity(4 bytes)  ← completes second 16-byte slot
    // Total: 32 bytes / light, 4-byte aligned throughout.
    _pad0: f32,
}

struct ClusterUniforms {
    // Framebuffer dimensions in pixels.
    screen_size: vec2<u32>,
    // Side length of each square tile in pixels.  Must match the workgroup
    // size used to dispatch cull_lights (currently 8).
    tile_size: u32,
    // Number of valid entries in the lights[] array.
    num_lights: u32,
    // Maximum number of light indices stored per tile.  When a tile's count
    // reaches this value, additional lights are silently discarded rather
    // than causing an out-of-bounds write.
    max_lights_per_tile: u32,
    // Padding to reach 32 bytes (WGSL uniform structs must be multiples of
    // the largest member alignment, which is 4 bytes; 32 bytes is a
    // convenient round size).
    _pad: vec3<u32>,
}

// ---------------------------------------------------------------------------
// Bindings shared by both passes
// ---------------------------------------------------------------------------

@group(0) @binding(0) var<uniform>            uniforms:           ClusterUniforms;
@group(0) @binding(1) var<storage, read>      lights:             array<PointLightData>;
// Atomic counts: one u32 per tile.  Size = tiles_x * tiles_y.
@group(0) @binding(2) var<storage, read_write> tile_light_count:  array<atomic<u32>>;
// Flat index list: tile_light_indices[tile * max_lights_per_tile + k] = light_index.
@group(0) @binding(3) var<storage, read_write> tile_light_indices: array<u32>;

// ---------------------------------------------------------------------------
// Pass-2-only bindings
// ---------------------------------------------------------------------------

// Read-only copy of the rendered scene (used by apply_cluster to read pixel
// colour, though in this deferred-accumulation design we only accumulate
// light and leave the combine pass to do scene × light).  Provided here so
// the shader has access to the correct screen dimensions at runtime via
// textureDimensions().
@group(0) @binding(4) var scene_tex:  texture_2d<f32>;
// Read-write accumulation texture (rgba16float).  apply_cluster adds its
// light contribution on top of whatever was already stored here.
@group(0) @binding(5) var accum_tex:  texture_storage_2d<rgba16float, read_write>;

// ---------------------------------------------------------------------------
// Helper: number of tiles along X axis
// ---------------------------------------------------------------------------

fn tiles_x() -> u32 {
    return (uniforms.screen_size.x + uniforms.tile_size - 1u) / uniforms.tile_size;
}

// ---------------------------------------------------------------------------
// Pass 1 — Light culling / binning
//
// Dispatch: ceil(screen_w / tile_size) × ceil(screen_h / tile_size) × 1
// Workgroup: 8 × 8 × 1  (each invocation = one tile)
// ---------------------------------------------------------------------------

@compute @workgroup_size(8, 8, 1)
fn cull_lights(@builtin(global_invocation_id) gid: vec3<u32>) {
    let tile_x = gid.x;
    let tile_y = gid.y;

    // Discard invocations beyond the tile grid (can happen when screen
    // dimensions are not multiples of tile_size).
    let tx = tiles_x();
    let tiles_y = (uniforms.screen_size.y + uniforms.tile_size - 1u) / uniforms.tile_size;
    if tile_x >= tx || tile_y >= tiles_y { return; }

    let tile_idx = tile_y * tx + tile_x;

    // AABB of this tile in pixel space.
    let ts = f32(uniforms.tile_size);
    let tile_min = vec2<f32>(f32(tile_x) * ts, f32(tile_y) * ts);
    let tile_max = tile_min + vec2<f32>(ts);

    let max_per_tile = uniforms.max_lights_per_tile;

    for (var i = 0u; i < uniforms.num_lights; i = i + 1u) {
        let light = lights[i];

        // 2D circle-AABB intersection test:
        // Find the closest point on the tile AABB to the light centre, then
        // check whether it lies within the light radius.
        let closest = clamp(light.pos, tile_min, tile_max);
        let diff    = closest - light.pos;
        let dist_sq = dot(diff, diff);

        if dist_sq < light.radius * light.radius {
            // Atomically reserve a slot.  If the tile is already full, skip
            // rather than writing out of bounds.
            let slot = atomicAdd(&tile_light_count[tile_idx], 1u);
            if slot < max_per_tile {
                tile_light_indices[tile_idx * max_per_tile + slot] = i;
            } else {
                // Undo the increment to keep the count accurate for the
                // apply pass.  Without this, a full tile would report a
                // count above max_lights_per_tile and apply_cluster would
                // clamp it anyway, but the count would be misleading for
                // any future diagnostic readback.
                atomicSub(&tile_light_count[tile_idx], 1u);
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Pass 2 — Per-pixel light accumulation
//
// Dispatch: ceil(screen_w / 8) × ceil(screen_h / 8) × 1
// Workgroup: 8 × 8 × 1  (each invocation = one pixel)
// ---------------------------------------------------------------------------

@compute @workgroup_size(8, 8, 1)
fn apply_cluster(@builtin(global_invocation_id) gid: vec3<u32>) {
    let px = gid.xy;

    // Guard: out-of-bounds pixels (tile padding at screen edges).
    let screen_size = textureDimensions(scene_tex);
    if px.x >= screen_size.x || px.y >= screen_size.y { return; }

    // Identify this pixel's tile.
    let tx       = tiles_x();
    let tile_idx = (px.y / uniforms.tile_size) * tx + (px.x / uniforms.tile_size);

    // How many lights were binned into this tile?
    // tile_light_count is declared as array<atomic<u32>>, but atomic<u32>
    // and u32 share the same memory representation; we can read the value
    // without atomicLoad because Pass 1 is fully complete before Pass 2 is
    // dispatched (different command encoder submissions or explicit barrier).
    let count = atomicLoad(&tile_light_count[tile_idx]);

    // Accumulate light contributions for this pixel.
    var total_light = vec3<f32>(0.0);
    let px_f = vec2<f32>(px);
    let max_per_tile = uniforms.max_lights_per_tile;

    for (var k = 0u; k < count; k = k + 1u) {
        let li    = tile_light_indices[tile_idx * max_per_tile + k];
        let light = lights[li];

        let dist  = length(px_f - light.pos);
        // Quadratic falloff: matches the existing lighting_point.wgsl model.
        // atten = (1 - dist/radius)^2
        let t     = max(0.0, 1.0 - dist / light.radius);
        let atten = t * t;

        total_light = total_light + light.color * (light.intensity * atten);
    }

    // Additive blend into the shared accumulation texture.
    // The combine pass (lighting_combine.wgsl) reads accum_tex and computes:
    //   lit = scene_tex * (ambient + accum)
    let prev = textureLoad(accum_tex, vec2<i32>(px));
    textureStore(accum_tex, vec2<i32>(px), vec4<f32>(prev.rgb + total_light, prev.a));
}
