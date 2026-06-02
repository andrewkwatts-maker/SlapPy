// deform_impact.wgsl — per-pixel stress/strain impact deformation
// Each pixel has stress (accumulated force) and strain (displacement from rest)
// Elastic mode: stress decays toward zero at spring_decay rate (bounce back)
// Plastic mode: strain accumulates permanently, stress decays quickly

struct ImpactEvent {
    center_x: f32,
    center_y: f32,
    force:    f32,
    radius:   f32,
    mode:     u32,  // 0 = elastic, 1 = plastic
    _pad0: u32,
    _pad1: u32,
    _pad2: u32,
};

struct Params {
    width:        u32,
    height:       u32,
    impact_count: u32,
    spring_decay: f32,  // 0..1, how fast elastic stress decays toward 0
    dt:           f32,
    _pad0: u32,
    _pad1: u32,
    _pad2: u32,
};

// Per-pixel state: stress (accumulated elastic force), strain (permanent plastic displacement)
// stored in a separate r32float texture (not the color alpha)
// stress: current elastic displacement — decays to 0 over time
// strain: permanent plastic deformation — does not decay

@group(0) @binding(0) var<storage, read_write> stress_strain: array<vec2<f32>>; // [stress, strain]
@group(0) @binding(1) var<storage, read>       impacts: array<ImpactEvent>;
@group(0) @binding(2) var<uniform>             params: Params;
@group(0) @binding(3) var                      color_tex: texture_storage_2d<rgba8unorm, read_write>;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if gid.x >= params.width || gid.y >= params.height { return; }
    let idx = gid.y * params.width + gid.x;
    let px = f32(gid.x);
    let py = f32(gid.y);

    var ss = stress_strain[idx];
    var stress = ss.x;
    var strain = ss.y;

    // Apply all impacts this frame
    for (var i: u32 = 0u; i < params.impact_count; i++) {
        let imp = impacts[i];
        let dx = px - imp.center_x;
        let dy = py - imp.center_y;
        let dist = sqrt(dx * dx + dy * dy);
        if dist >= imp.radius { continue; }

        // Cosine falloff — strongest at center, zero at radius edge
        let t = 1.0 - dist / imp.radius;
        let falloff = t * t * (3.0 - 2.0 * t);  // smoothstep
        let impact_at_pixel = imp.force * falloff;

        if imp.mode == 1u {
            // Plastic: accumulate permanent strain, immediate alpha reduction
            strain = strain + impact_at_pixel * 0.01;
        } else {
            // Elastic: spike stress, will decay via spring_decay
            stress = stress + impact_at_pixel * 0.005;
        }
    }

    // Spring decay for elastic stress
    stress = stress * params.spring_decay;

    // Apply combined deformation to alpha channel
    let total_deform = clamp(stress + strain, 0.0, 1.0);
    let orig_color = textureLoad(color_tex, vec2<i32>(i32(gid.x), i32(gid.y)));
    // Alpha reduction: fully intact = 255, fully destroyed = 0
    let new_alpha = clamp(orig_color.a - total_deform, 0.0, 1.0);
    textureStore(color_tex, vec2<i32>(i32(gid.x), i32(gid.y)),
                 vec4<f32>(orig_color.r, orig_color.g, orig_color.b, new_alpha));

    stress_strain[idx] = vec2<f32>(stress, strain);
}
