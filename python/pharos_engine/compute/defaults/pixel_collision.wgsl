// pixel_collision.wgsl — Per-pixel collision detection between two RGBA8 textures.
//
// Compares the alpha channels of two Layer2D textures within their overlapping
// AABB in world space.  For each solid pixel pair, increments atomic counters
// and accumulates the alpha gradient of layer_a to derive a contact normal.
//
// Dispatch: caller computes ((overlap_w + 7) / 8) × ((overlap_h + 7) / 8) workgroups.
// Readback: divide normal_{x,y}_acc by (10000.0 × contact_pixels) to get unit normal.

// ---------------------------------------------------------------------------
// Params uniform
// ---------------------------------------------------------------------------

struct CollisionParams {
    // Layer A bounding box in world pixels (top-left origin)
    a_x: u32,
    a_y: u32,
    a_w: u32,
    a_h: u32,
    // Layer B bounding box in world pixels
    b_x: u32,
    b_y: u32,
    b_w: u32,
    b_h: u32,
    // Alpha threshold for a "solid" pixel (0–255 range; compared as threshold/255.0)
    alpha_threshold: u32,
    _pad: vec3u,
}

// ---------------------------------------------------------------------------
// Result storage — all fields are atomic so every workgroup thread can
// contribute without races.  Python reads these as plain u32/i32 after the
// dispatch finishes.
//
//   normal_x_acc / (10000.0 × contact_pixels)  → unit normal X
//   normal_y_acc / (10000.0 × contact_pixels)  → unit normal Y
// ---------------------------------------------------------------------------

struct CollisionResult {
    hit:             atomic<u32>,   // 1 when any collision pixel found (saturates at 1)
    contact_pixels:  atomic<u32>,   // total count of overlapping solid pixels
    normal_x_acc:    atomic<i32>,   // fixed-point × 10000 gradient accumulator, X axis
    normal_y_acc:    atomic<i32>,   // fixed-point × 10000 gradient accumulator, Y axis
}

// ---------------------------------------------------------------------------
// Bindings
// ---------------------------------------------------------------------------

@group(0) @binding(0) var<uniform>            params:  CollisionParams;
@group(0) @binding(1) var                     layer_a: texture_2d<f32>;
@group(0) @binding(2) var                     layer_b: texture_2d<f32>;
@group(0) @binding(3) var<storage, read_write> result: CollisionResult;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Sample the alpha channel of a texture at integer coordinates, clamped to
// the texture dimensions so out-of-bounds reads return 0.0.
fn sample_alpha(tex: texture_2d<f32>, coord: vec2i) -> f32 {
    let dim = vec2i(textureDimensions(tex));
    if coord.x < 0 || coord.y < 0 || coord.x >= dim.x || coord.y >= dim.y {
        return 0.0;
    }
    // mip level 0; alpha is channel 3 (w)
    return textureLoad(tex, coord, 0).w;
}

// ---------------------------------------------------------------------------
// Compute entry point
// ---------------------------------------------------------------------------

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3u) {

    // -----------------------------------------------------------------------
    // 1. Compute the overlap rectangle in world space.
    // -----------------------------------------------------------------------

    let overlap_x0 = max(params.a_x, params.b_x);
    let overlap_y0 = max(params.a_y, params.b_y);

    let a_x1 = params.a_x + params.a_w;
    let b_x1 = params.b_x + params.b_w;
    let a_y1 = params.a_y + params.a_h;
    let b_y1 = params.b_y + params.b_h;

    let overlap_x1 = min(a_x1, b_x1);
    let overlap_y1 = min(a_y1, b_y1);

    // No overlap at all — nothing to do.
    if overlap_x1 <= overlap_x0 || overlap_y1 <= overlap_y0 {
        return;
    }

    let overlap_w = overlap_x1 - overlap_x0;
    let overlap_h = overlap_y1 - overlap_y0;

    // -----------------------------------------------------------------------
    // 2. Guard threads outside the overlap rectangle.
    // -----------------------------------------------------------------------

    if gid.x >= overlap_w || gid.y >= overlap_h {
        return;
    }

    // -----------------------------------------------------------------------
    // 3. Compute per-texture local coordinates for this pixel.
    //
    //    world_px = (gid.x + overlap_x0, gid.y + overlap_y0)
    //    local_a  = world_px - (a_x, a_y)
    //    local_b  = world_px - (b_x, b_y)
    // -----------------------------------------------------------------------

    let local_ax = i32(gid.x + overlap_x0 - params.a_x);
    let local_ay = i32(gid.y + overlap_y0 - params.a_y);
    let local_bx = i32(gid.x + overlap_x0 - params.b_x);
    let local_by = i32(gid.y + overlap_y0 - params.b_y);

    let alpha_a = sample_alpha(layer_a, vec2i(local_ax, local_ay));
    let alpha_b = sample_alpha(layer_b, vec2i(local_bx, local_by));

    let threshold = f32(params.alpha_threshold) / 255.0;

    // -----------------------------------------------------------------------
    // 4. Collision pixel test.
    // -----------------------------------------------------------------------

    if alpha_a > threshold && alpha_b > threshold {

        // Mark a hit and count overlapping solid pixels.
        atomicStore(&result.hit, 1u);          // saturating — any pixel sets it
        atomicAdd(&result.contact_pixels, 1u);

        // -------------------------------------------------------------------
        // 5. Accumulate the alpha gradient of layer_a in the overlap region.
        //    Gradient is computed via central differences; edge pixels use
        //    one-sided differences implicitly (out-of-bounds returns 0).
        //
        //    grad_x = alpha(x+1, y) − alpha(x−1, y)
        //    grad_y = alpha(x,   y+1) − alpha(x,   y−1)
        //
        //    Both components are accumulated as fixed-point × 10000 i32 values.
        //    Python normalises by dividing by (10000 × contact_pixels).
        // -------------------------------------------------------------------

        let ap1x = sample_alpha(layer_a, vec2i(local_ax + 1, local_ay));
        let am1x = sample_alpha(layer_a, vec2i(local_ax - 1, local_ay));
        let ap1y = sample_alpha(layer_a, vec2i(local_ax, local_ay + 1));
        let am1y = sample_alpha(layer_a, vec2i(local_ax, local_ay - 1));

        let grad_x = ap1x - am1x;
        let grad_y = ap1y - am1y;

        atomicAdd(&result.normal_x_acc, i32(grad_x * 10000.0));
        atomicAdd(&result.normal_y_acc, i32(grad_y * 10000.0));
    }
}
