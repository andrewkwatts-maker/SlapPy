// deform_crack.wgsl — crack propagation pass
//
// Runs AFTER deform_impact.wgsl.  Each thread handles one ray of one impact
// and writes crack patterns into the alpha channel of color_tex.
//
// Two crack modes (mode 0 = RADIAL, mode 1 = GRAIN):
//   RADIAL — trace N rays outward from the impact center at evenly-spaced
//             angles with per-step jitter for an organic look.
//   GRAIN  — same as RADIAL but ray direction is biased each step toward the
//             gradient of grain_tex (r32float), so cracks follow weak grain
//             lines (darker pixels = weaker material).

struct CrackImpact {
    center_x:  f32,
    center_y:  f32,
    force:     f32,
    radius:    f32,   // max crack length in pixels
    mode:      u32,   // 0 = RADIAL, 1 = GRAIN
    ray_count: u32,   // number of crack rays
    _pad0:     u32,
    _pad1:     u32,
};

struct Params {
    width:        u32,
    height:       u32,
    impact_count: u32,
    jitter:       f32,   // 0..1 — how much rays deviate from straight per step
    frame_seed:   u32,   // per-frame random seed for jitter variation
    _pad0:        u32,
    _pad1:        u32,
    _pad2:        u32,
};

@group(0) @binding(0) var<storage, read>  impacts:   array<CrackImpact>;
@group(0) @binding(1) var<uniform>        params:    Params;
@group(0) @binding(2) var                 color_tex: texture_storage_2d<rgba8unorm, read_write>;
@group(0) @binding(3) var                 grain_tex: texture_storage_2d<r32float, read>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Simple integer hash → [0, 1) float.
fn hash_f32(n: u32) -> f32 {
    var x: u32 = n;
    x = x ^ (x >> 16u);
    x = x * 0x45d9f3bu;
    x = x ^ (x >> 16u);
    return f32(x & 0xFFFFu) / 65535.0;
}

// Load grain strength at integer pixel coords; clamps to texture boundary.
fn grain_at(ix: i32, iy: i32, w: i32, h: i32) -> f32 {
    let cx = clamp(ix, 0, w - 1);
    let cy = clamp(iy, 0, h - 1);
    return textureLoad(grain_tex, vec2<i32>(cx, cy)).r;
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

// Workgroup of 64 threads.  Each thread owns one ray of one impact.
// gid.x = impact_index * MAX_RAYS + ray_index
const MAX_RAYS: u32 = 16u;

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let impact_idx: u32 = gid.x / MAX_RAYS;
    let ray_idx:    u32 = gid.x % MAX_RAYS;

    if impact_idx >= params.impact_count { return; }
    let imp = impacts[impact_idx];
    if ray_idx >= imp.ray_count { return; }

    let w: i32 = i32(params.width);
    let h: i32 = i32(params.height);

    // -----------------------------------------------------------------------
    // Initial ray angle — evenly spaced around full circle.
    // -----------------------------------------------------------------------
    let tau: f32 = 6.28318530718;
    let base_angle: f32 = f32(ray_idx) * (tau / f32(imp.ray_count));

    // Per-ray jitter seed (combines frame seed, impact index, ray index).
    let seed: u32 = params.frame_seed ^ (impact_idx * 1234567u + ray_idx * 7654321u);
    // Map hash to ±jitter/2 radians for the initial angle perturbation.
    let init_jitter: f32 = (hash_f32(seed) - 0.5) * params.jitter;
    let angle: f32 = base_angle + init_jitter;

    var dx: f32 = cos(angle);
    var dy: f32 = sin(angle);

    // -----------------------------------------------------------------------
    // Step along the ray.
    // -----------------------------------------------------------------------
    let steps: i32 = i32(imp.radius);
    var px: f32 = imp.center_x;
    var py: f32 = imp.center_y;

    for (var s: i32 = 0; s < steps; s++) {
        let ix: i32 = i32(px);
        let iy: i32 = i32(py);

        // Bounds check — stop ray if it leaves the texture.
        if ix < 0 || ix >= w || iy < 0 || iy >= h { break; }

        let coord: vec2<i32> = vec2<i32>(ix, iy);

        // t = 1 at the impact center, 0 at the tip.
        let t: f32 = 1.0 - f32(s) / f32(max(1, steps));

        // Crack strength tapers with distance (quadratic falloff).
        let crack_strength: f32 = imp.force * 0.002 * t * t;

        // ---- Write crack to the centre pixel ----
        var pixel = textureLoad(color_tex, coord);

        // Stop propagating if the pixel is already fully destroyed.
        if pixel.a <= 0.0 { break; }

        pixel.a = max(0.0, pixel.a - crack_strength);
        textureStore(color_tex, coord, pixel);

        // ---- Brush perpendicular neighbours for crack width ----
        // Width = 3 pixels near the base (t > 0.6), 1 pixel at the tip.
        // Only sample every 3rd step to avoid redundant writes.
        if t > 0.6 && (s % 3) == 0 {
            // Perpendicular direction: (-dy, dx) and (dy, -dx).
            let nx_a = vec2<i32>(ix + i32(round(-dy)), iy + i32(round(dx)));
            let nx_b = vec2<i32>(ix + i32(round( dy)), iy + i32(round(-dx)));

            if nx_a.x >= 0 && nx_a.x < w && nx_a.y >= 0 && nx_a.y < h {
                var np = textureLoad(color_tex, nx_a);
                np.a = max(0.0, np.a - crack_strength * 0.5);
                textureStore(color_tex, nx_a, np);
            }
            if nx_b.x >= 0 && nx_b.x < w && nx_b.y >= 0 && nx_b.y < h {
                var np = textureLoad(color_tex, nx_b);
                np.a = max(0.0, np.a - crack_strength * 0.5);
                textureStore(color_tex, nx_b, np);
            }
        }

        // ---- Per-step jitter ----
        // Re-seed per step so the jitter is different at every pixel.
        let step_seed: u32 = seed ^ u32(s) * 2246822519u;
        let step_jitter: f32 = (hash_f32(step_seed) - 0.5) * params.jitter * 0.3;
        // Rotate direction by step_jitter (small-angle approximation is fine).
        let cos_j: f32 = cos(step_jitter);
        let sin_j: f32 = sin(step_jitter);
        let ndx: f32 = dx * cos_j - dy * sin_j;
        let ndy: f32 = dx * sin_j + dy * cos_j;
        dx = ndx;
        dy = ndy;

        // ---- GRAIN mode: bias direction toward grain map gradient ----
        // Darker grain_tex pixels = weaker material; gradient points from
        // strong (bright) toward weak (dark) regions.
        if imp.mode == 1u {
            let g_here:  f32 = grain_at(ix,     iy,     w, h);
            let g_right: f32 = grain_at(ix + 1, iy,     w, h);
            let g_down:  f32 = grain_at(ix,     iy + 1, w, h);

            // Gradient pointing toward darker (weaker) areas.
            let gx: f32 = g_here - g_right;
            let gy: f32 = g_here - g_down;
            let glen: f32 = sqrt(gx * gx + gy * gy) + 0.001;

            // Blend 30% toward the grain gradient direction.
            dx = dx + (gx / glen) * 0.3;
            dy = dy + (gy / glen) * 0.3;

            // Re-normalise to prevent direction drift.
            let dlen: f32 = sqrt(dx * dx + dy * dy) + 0.001;
            dx = dx / dlen;
            dy = dy / dlen;
        }

        px += dx;
        py += dy;
    }
}
