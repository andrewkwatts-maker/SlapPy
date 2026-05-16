// Stable 2D Eulerian fluid simulation step.
// Semi-Lagrangian advection + simplified pressure projection (Jacobi iteration).
// Only processes pixels where fluid_tag != 0u.
//
// NOTE: {{PIXEL_STRUCT}} is replaced at runtime by ShaderGen.inject_into_shader().

{{PIXEL_STRUCT}}

struct FluidParams {
    dt           : f32,  // timestep (seconds)
    width        : u32,  // grid width in pixels
    height       : u32,  // grid height in pixels
    viscosity_global : f32,  // global viscosity scale applied on top of per-pixel viscosity
}

// Binding layout:
//   binding 0 – pixels storage buffer (read_write): position-indexed PixelData
//   binding 1 – velocity field (r32float storage texture, read_write):
//               interleaved as two layers: layer 0 = u (vel_x), layer 1 = v (vel_y)
//               Stored as a 1D storage buffer of vec2f for simplicity/portability.
//   binding 2 – uniform FluidParams

@group(0) @binding(0) var<storage, read_write> pixels   : array<PixelData>;
@group(0) @binding(1) var<storage, read_write> vel_field: array<vec2f>;   // vel_field[y*width+x] = vec2f(u, v)
@group(0) @binding(2) var<uniform>             params   : FluidParams;

// ────────────────────────────────────────────────────────────────
// Helper: flat index, clamped to grid boundaries
fn idx(x: i32, y: i32) -> u32 {
    let cx = clamp(x, 0, i32(params.width)  - 1);
    let cy = clamp(y, 0, i32(params.height) - 1);
    return u32(cy) * params.width + u32(cx);
}

// Bilinear sample of velocity at continuous position (px, py) in pixel coordinates
fn sample_vel(px: f32, py: f32) -> vec2f {
    let x0 = i32(floor(px));
    let y0 = i32(floor(py));
    let x1 = x0 + 1;
    let y1 = y0 + 1;
    let fx = px - floor(px);
    let fy = py - floor(py);

    let v00 = vel_field[idx(x0, y0)];
    let v10 = vel_field[idx(x1, y0)];
    let v01 = vel_field[idx(x0, y1)];
    let v11 = vel_field[idx(x1, y1)];

    return mix(mix(v00, v10, fx), mix(v01, v11, fx), fy);
}

// Bilinear sample of a scalar channel from pixels (used for density / colour advection)
fn sample_density(px: f32, py: f32) -> f32 {
    let x0 = i32(floor(px));
    let y0 = i32(floor(py));
    let x1 = x0 + 1;
    let y1 = y0 + 1;
    let fx = px - floor(px);
    let fy = py - floor(py);

    let d00 = pixels[idx(x0, y0)].density;
    let d10 = pixels[idx(x1, y0)].density;
    let d01 = pixels[idx(x0, y1)].density;
    let d11 = pixels[idx(x1, y1)].density;

    return mix(mix(d00, d10, fx), mix(d01, d11, fx), fy);
}

// ────────────────────────────────────────────────────────────────
// Workgroup shared memory for pressure Jacobi iteration
var<workgroup> ws_div : array<f32, 64>;   // divergence cache (8×8 tile)

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid     : vec3u,
        @builtin(local_invocation_id)  lid_xyz : vec3u,
        @builtin(local_invocation_index) lid    : u32) {

    let x = i32(gid.x);
    let y = i32(gid.y);
    let w = i32(params.width);
    let h = i32(params.height);

    if x >= w || y >= h { return; }

    let flat = u32(y) * params.width + u32(x);
    let p    = pixels[flat];

    // Skip non-fluid pixels
    if p.fluid_tag == 0u { return; }

    // ── Step 1: Semi-Lagrangian advection ──────────────────────
    // Read current velocity at this cell
    let vel  = vel_field[flat];
    let dt   = params.dt;

    // Trace particle back in time
    let px_back = f32(x) - dt * vel.x;
    let py_back = f32(y) - dt * vel.y;

    // Sample velocity at back-traced position (advect velocity field)
    let new_vel = sample_vel(px_back, py_back);

    // Advect density scalar
    let new_density = sample_density(px_back, py_back);

    // ── Step 2: Apply viscosity diffusion (explicit Euler) ──────
    // Laplacian of velocity using 4-neighbours
    let vis = p.viscosity * params.viscosity_global;

    let v_l  = vel_field[idx(x - 1, y)];
    let v_r  = vel_field[idx(x + 1, y)];
    let v_u  = vel_field[idx(x, y - 1)];
    let v_d  = vel_field[idx(x, y + 1)];
    let laplacian = v_l + v_r + v_u + v_d - 4.0 * vel;
    let diffused_vel = new_vel + dt * vis * laplacian;

    // Write diffused velocity back to vel_field
    vel_field[flat] = diffused_vel;

    // Also sync velocity into PixelData channels for render/readback
    pixels[flat].vel_x   = diffused_vel.x;
    pixels[flat].vel_y   = diffused_vel.y;
    pixels[flat].density = new_density;

    // ── Step 3: Compute divergence of the velocity field ────────
    // We need a barrier so all writes from step 2 are visible.
    workgroupBarrier();

    // Re-read neighbours (may have been updated in this workgroup)
    let u_l = vel_field[idx(x - 1, y)].x;
    let u_r = vel_field[idx(x + 1, y)].x;
    let v_u2 = vel_field[idx(x, y - 1)].y;
    let v_d2 = vel_field[idx(x, y + 1)].y;
    let div  = 0.5 * ((u_r - u_l) + (v_d2 - v_u2));

    // Store divergence in shared mem and in the struct
    ws_div[lid] = div;
    pixels[flat].divergence = div;

    workgroupBarrier();

    // ── Step 4: Pressure Jacobi iteration (1 iteration per pass) ─
    // p_new[i,j] = (p[i-1,j] + p[i+1,j] + p[i,j-1] + p[i,j+1] - div) / 4
    let p_l   = pixels[idx(x - 1, y)].pressure;
    let p_r   = pixels[idx(x + 1, y)].pressure;
    let p_up  = pixels[idx(x, y - 1)].pressure;
    let p_dn  = pixels[idx(x, y + 1)].pressure;
    let new_pressure = (p_l + p_r + p_up + p_dn - div) * 0.25;
    pixels[flat].pressure = new_pressure;

    workgroupBarrier();

    // ── Step 5: Pressure projection (subtract pressure gradient) ──
    // Correct velocity to be divergence-free
    let gp_x = 0.5 * (pixels[idx(x + 1, y)].pressure - pixels[idx(x - 1, y)].pressure);
    let gp_y = 0.5 * (pixels[idx(x, y + 1)].pressure - pixels[idx(x, y - 1)].pressure);

    let proj_vel = vel_field[flat] - vec2f(gp_x, gp_y);
    vel_field[flat]  = proj_vel;
    pixels[flat].vel_x = proj_vel.x;
    pixels[flat].vel_y = proj_vel.y;
}
