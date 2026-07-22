// SDF 3D Extrude — GPU-generate a 3D slab mesh from a 2D silhouette mask.
//
// For each pixel in the mask texture that is above a threshold alpha,
// emit a tiny cube face quad in the output vertex buffer.
// This produces a voxel-slab 3D mesh from a 2D pixel image.
//
// Dispatch: one workgroup per 8×8 tile of the mask texture.
//   dispatch_x = ceil(mask_width  / 8)
//   dispatch_y = ceil(mask_height / 8)
//   dispatch_z = 1
//
// Bindings:
//   @group(0) @binding(0) — ExtrudeUniforms (uniform)
//   @group(0) @binding(1) — mask (texture_2d<f32>)
//   @group(0) @binding(2) — vertex_out (storage buffer, read_write) — packed f32 array
//   @group(0) @binding(3) — vertex_count (atomic u32)
//
// Output vertex layout — each vertex is 12 contiguous f32 values:
//   [ pos.x, pos.y, pos.z,          (floats 0-2)
//     normal.x, normal.y, normal.z, (floats 3-5)
//     uv.s, uv.t,                   (floats 6-7)
//     tangent.x, tangent.y, tangent.z, tangent.w ]  (floats 8-11)
//
// Each solid pixel emits up to 6 quads (top + bottom + ≤4 sides).
// Each quad = 4 vertices × 12 f32 = 48 floats.
// Max floats per pixel = 6 × 48 = 288.
// Size vertex_out as:  mask_width × mask_height × 288 × sizeof(f32).
//
// ─────────────────────────────────────────────────────────────────────────────
// CPU-SIDE FALLBACK DESCRIPTION
// ─────────────────────────────────────────────────────────────────────────────
// When a GPU context is unavailable the same mesh can be generated on CPU
// (see SdfExtruder._extrude_cpu in python/pharos_engine/gpu/sdf_extruder.py).
//
// Algorithm outline:
//   1. Normalise the alpha mask to [0.0, 1.0].
//   2. For each pixel (col c, row r) whose value >= threshold:
//        x_world = (c - width/2)  * scale
//        y_world = (r - height/2) * scale
//        z_top   = +depth/2
//        z_bot   = -depth/2
//      a. Always emit a top face quad  (z = z_top, normal = +Z).
//      b. Always emit a bottom face quad (z = z_bot, normal = -Z).
//      c. For each of the 4 cardinal neighbours:
//           if the neighbour pixel is empty (or out of bounds),
//           emit the shared wall quad with the appropriate ±X/±Y normal.
//   3. Each quad contributes 4 vertices + 6 indices (two CCW triangles).
//   4. Pack vertices into a GpuMesh and call mesh.upload(device).
//
// This mirrors the GPU kernel exactly and produces an identical mesh.
// ─────────────────────────────────────────────────────────────────────────────

// ── Uniforms ──────────────────────────────────────────────────────────────────

struct ExtrudeUniforms {
    mask_width:  u32,
    mask_height: u32,
    depth:       f32,   // extrude depth — Z extent of the slab
    scale:       f32,   // world-unit size per pixel in XY
    threshold:   f32,   // alpha threshold in [0, 1]; pixels above this are "solid"
    _pad0:       f32,
    _pad1:       f32,
    _pad2:       f32,
}

// ── Bindings ──────────────────────────────────────────────────────────────────

@group(0) @binding(0) var<uniform>              uniforms     : ExtrudeUniforms;
@group(0) @binding(1) var                       mask         : texture_2d<f32>;
@group(0) @binding(2) var<storage, read_write>  vertex_out   : array<f32>;
@group(0) @binding(3) var<storage, read_write>  vertex_count : atomic<u32>;

// ── Constants ─────────────────────────────────────────────────────────────────

// Floats per vertex:  3 pos + 3 normal + 2 uv + 4 tangent = 12
const FLOATS_PER_VERTEX: u32 = 12u;
// Vertices per quad
const VERTS_PER_QUAD:    u32 = 4u;
// Floats per quad = 4 × 12 = 48
const FLOATS_PER_QUAD:   u32 = 48u;

// ── Internal helpers ──────────────────────────────────────────────────────────

// Sample the mask at integer texel coords; returns alpha in [0,1].
// Out-of-bounds coords are treated as 0 (empty).
fn sample_mask(col: i32, row: i32) -> f32 {
    let w = i32(uniforms.mask_width);
    let h = i32(uniforms.mask_height);
    if col < 0 || col >= w || row < 0 || row >= h {
        return 0.0;
    }
    let texel = textureLoad(mask, vec2<i32>(col, row), 0);
    // Use red channel (luminance mask) or alpha channel, whichever has data.
    // Convention: store mask in alpha; fall back to red for greyscale images.
    return max(texel.a, texel.r);
}

// Write a single vertex into vertex_out at `base_float_idx`.
// The 12 floats are laid out as: pos(3) normal(3) uv(2) tangent(4).
fn write_vertex(
    base: u32,
    pos:    vec3<f32>,
    normal: vec3<f32>,
    uv:     vec2<f32>,
    tangent: vec4<f32>,
) {
    vertex_out[base + 0u]  = pos.x;
    vertex_out[base + 1u]  = pos.y;
    vertex_out[base + 2u]  = pos.z;
    vertex_out[base + 3u]  = normal.x;
    vertex_out[base + 4u]  = normal.y;
    vertex_out[base + 5u]  = normal.z;
    vertex_out[base + 6u]  = uv.x;
    vertex_out[base + 7u]  = uv.y;
    vertex_out[base + 8u]  = tangent.x;
    vertex_out[base + 9u]  = tangent.y;
    vertex_out[base + 10u] = tangent.z;
    vertex_out[base + 11u] = tangent.w;
}

// Emit one quad (4 vertices) starting at `base_float_idx`.
// Corners v0..v3 are in counter-clockwise order when viewed from outside.
// UV corners follow the same winding: (0,1) (1,1) (1,0) (0,0).
fn emit_quad(
    base:    u32,
    v0: vec3<f32>,  v1: vec3<f32>,
    v2: vec3<f32>,  v3: vec3<f32>,
    normal:  vec3<f32>,
    tangent: vec4<f32>,
) {
    write_vertex(base + 0u  * FLOATS_PER_VERTEX, v0, normal, vec2<f32>(0.0, 1.0), tangent);
    write_vertex(base + 1u  * FLOATS_PER_VERTEX, v1, normal, vec2<f32>(1.0, 1.0), tangent);
    write_vertex(base + 2u  * FLOATS_PER_VERTEX, v2, normal, vec2<f32>(1.0, 0.0), tangent);
    write_vertex(base + 3u  * FLOATS_PER_VERTEX, v3, normal, vec2<f32>(0.0, 0.0), tangent);
}

// ── Compute entry point ───────────────────────────────────────────────────────

@compute @workgroup_size(8, 8, 1)
fn extrude_main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let col = i32(gid.x);
    let row = i32(gid.y);

    // Guard: out-of-texture bounds
    if col >= i32(uniforms.mask_width) || row >= i32(uniforms.mask_height) {
        return;
    }

    // Skip empty pixels
    let alpha = sample_mask(col, row);
    if alpha < uniforms.threshold {
        return;
    }

    // World-space XY position of this pixel's bottom-left corner.
    // Centred so that the whole mask straddles the origin.
    let half_w = f32(uniforms.mask_width)  * 0.5;
    let half_h = f32(uniforms.mask_height) * 0.5;
    let s      = uniforms.scale;
    let x0     = (f32(col) - half_w) * s;
    let y0     = (f32(row) - half_h) * s;
    let x1     = x0 + s;
    let y1     = y0 + s;
    let z_top  =  uniforms.depth * 0.5;
    let z_bot  = -uniforms.depth * 0.5;

    // Count the quads this pixel needs to emit.
    let emit_north = sample_mask(col,     row - 1) < uniforms.threshold;
    let emit_south = sample_mask(col,     row + 1) < uniforms.threshold;
    let emit_west  = sample_mask(col - 1, row    ) < uniforms.threshold;
    let emit_east  = sample_mask(col + 1, row    ) < uniforms.threshold;

    // Always emit top + bottom; conditionally emit up to 4 side faces.
    var num_quads: u32 = 2u;
    if emit_north { num_quads += 1u; }
    if emit_south { num_quads += 1u; }
    if emit_west  { num_quads += 1u; }
    if emit_east  { num_quads += 1u; }

    // Atomically claim space in the output buffer.
    // vertex_count tracks VERTICES (not floats), four per quad.
    let first_vertex = atomicAdd(&vertex_count, num_quads * VERTS_PER_QUAD);
    var base_float   = first_vertex * FLOATS_PER_VERTEX;

    // ── Top face (z = +depth/2, normal = +Z, tangent = +X) ───────────────────
    emit_quad(
        base_float,
        vec3<f32>(x0, y0, z_top), vec3<f32>(x1, y0, z_top),
        vec3<f32>(x1, y1, z_top), vec3<f32>(x0, y1, z_top),
        vec3<f32>(0.0, 0.0, 1.0),
        vec4<f32>(1.0, 0.0, 0.0, 1.0),
    );
    base_float += FLOATS_PER_QUAD;

    // ── Bottom face (z = -depth/2, normal = -Z, tangent = -X) ────────────────
    // Winding flipped (CCW viewed from -Z = reversed XY scan direction).
    emit_quad(
        base_float,
        vec3<f32>(x0, y1, z_bot), vec3<f32>(x1, y1, z_bot),
        vec3<f32>(x1, y0, z_bot), vec3<f32>(x0, y0, z_bot),
        vec3<f32>(0.0, 0.0, -1.0),
        vec4<f32>(-1.0, 0.0, 0.0, 1.0),
    );
    base_float += FLOATS_PER_QUAD;

    // ── North face (row-1 empty, normal = -Y, tangent = +X) ──────────────────
    if emit_north {
        emit_quad(
            base_float,
            vec3<f32>(x0, y0, z_bot), vec3<f32>(x1, y0, z_bot),
            vec3<f32>(x1, y0, z_top), vec3<f32>(x0, y0, z_top),
            vec3<f32>(0.0, -1.0, 0.0),
            vec4<f32>(1.0, 0.0, 0.0, 1.0),
        );
        base_float += FLOATS_PER_QUAD;
    }

    // ── South face (row+1 empty, normal = +Y, tangent = -X) ──────────────────
    if emit_south {
        emit_quad(
            base_float,
            vec3<f32>(x1, y1, z_bot), vec3<f32>(x0, y1, z_bot),
            vec3<f32>(x0, y1, z_top), vec3<f32>(x1, y1, z_top),
            vec3<f32>(0.0, 1.0, 0.0),
            vec4<f32>(-1.0, 0.0, 0.0, 1.0),
        );
        base_float += FLOATS_PER_QUAD;
    }

    // ── West face (col-1 empty, normal = -X, tangent = -Z) ───────────────────
    if emit_west {
        emit_quad(
            base_float,
            vec3<f32>(x0, y1, z_bot), vec3<f32>(x0, y0, z_bot),
            vec3<f32>(x0, y0, z_top), vec3<f32>(x0, y1, z_top),
            vec3<f32>(-1.0, 0.0, 0.0),
            vec4<f32>(0.0, 0.0, -1.0, 1.0),
        );
        base_float += FLOATS_PER_QUAD;
    }

    // ── East face (col+1 empty, normal = +X, tangent = +Z) ───────────────────
    if emit_east {
        emit_quad(
            base_float,
            vec3<f32>(x1, y0, z_bot), vec3<f32>(x1, y1, z_bot),
            vec3<f32>(x1, y1, z_top), vec3<f32>(x1, y0, z_top),
            vec3<f32>(1.0, 0.0, 0.0),
            vec4<f32>(0.0, 0.0, 1.0, 1.0),
        );
        // base_float += FLOATS_PER_QUAD;  // last face — no further writes
    }
}
