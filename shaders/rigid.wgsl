// Simple rigid-body / particle physics step.
// For each pixel with density > 0, applies gravity, integrates velocity,
// and handles floor/ceiling/wall boundary conditions.
//
// NOTE: {{PIXEL_STRUCT}} is replaced at runtime by ShaderGen.inject_into_shader().

{{PIXEL_STRUCT}}

struct RigidParams {
    dt           : f32,  // timestep (seconds)
    width        : u32,  // grid width in pixels
    height       : u32,  // grid height in pixels
    gravity      : f32,  // gravitational acceleration (pixels/s²), positive = downward
    restitution  : f32,  // bounce coefficient at floor [0,1]  0=inelastic, 1=elastic
    friction     : f32,  // horizontal friction factor applied at floor contact [0,1]
    drag         : f32,  // linear air drag per second (velocity *= (1 - drag*dt))
    _pad         : u32,
}

@group(0) @binding(0) var<storage, read_write> pixels : array<PixelData>;
@group(0) @binding(1) var<uniform>             params : RigidParams;

// ────────────────────────────────────────────────────────────────
// Flat index helpers
fn flat(x: u32, y: u32) -> u32 {
    return y * params.width + x;
}

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3u) {
    let idx = gid.x;
    let total = params.width * params.height;
    if idx >= total { return; }

    let p = pixels[idx];

    // Only simulate pixels with mass (density > 0)
    if p.density <= 0.0 { return; }

    // Grid coordinates of this pixel
    let xi = idx % params.width;
    let yi = idx / params.width;

    let dt = params.dt;

    // ── Step 1: Apply air drag ─────────────────────────────────
    var vx = p.vel_x * (1.0 - params.drag * dt);
    var vy = p.vel_y * (1.0 - params.drag * dt);

    // ── Step 2: Apply gravity (downward = +y in screen space) ──
    vy += params.gravity * dt;

    // ── Step 3: Integrate position (pixel advection) ────────────
    // We represent position as the float offset from the pixel centre.
    // The pixel "moves" when the accumulated offset exceeds 1 pixel.
    // Here we use a simplified model: store velocity in PixelData and
    // let the CPU/render layer handle actual cell swaps. The shader
    // updates velocity and tags boundary contacts.

    // Compute candidate next position (in continuous space)
    let nx_f = f32(xi) + vx * dt;
    let ny_f = f32(yi) + vy * dt;

    // ── Step 4: Boundary collision response ─────────────────────

    // Floor (bottom edge, y = height - 1)
    let floor_y = f32(params.height) - 1.0;
    if ny_f >= floor_y {
        // Reflect and attenuate vertical velocity
        vy = -vy * params.restitution;
        // Clamp so we don't move below floor
        // Apply floor friction to horizontal component
        vx *= (1.0 - params.friction);
        // Zero out tiny bounce velocities to prevent jitter
        if abs(vy) < 0.01 { vy = 0.0; }
    }

    // Ceiling (top edge, y = 0)
    if ny_f < 0.0 {
        vy = abs(vy) * params.restitution;
        if abs(vy) < 0.01 { vy = 0.0; }
    }

    // Right wall (x = width - 1)
    let wall_x = f32(params.width) - 1.0;
    if nx_f >= wall_x {
        vx = -abs(vx) * params.restitution;
        if abs(vx) < 0.01 { vx = 0.0; }
    }

    // Left wall (x = 0)
    if nx_f < 0.0 {
        vx = abs(vx) * params.restitution;
        if abs(vx) < 0.01 { vx = 0.0; }
    }

    // ── Step 5: Stiffness / structural damping ──────────────────
    // High-stiffness pixels resist deformation; damp velocity proportional
    // to stiffness so rigid objects settle quickly.
    let stiff_damp = 1.0 - clamp(p.stiffness * 0.1 * dt, 0.0, 0.9);
    vx *= stiff_damp;
    vy *= stiff_damp;

    // ── Step 6: Write back updated velocity ─────────────────────
    pixels[idx].vel_x = vx;
    pixels[idx].vel_y = vy;

    // Update colour alpha based on health (visual feedback)
    // Health 1.0 → fully opaque, 0.0 → transparent
    var col = pixels[idx].color;
    col.w = clamp(p.health, 0.0, 1.0);
    pixels[idx].color = col;
}
