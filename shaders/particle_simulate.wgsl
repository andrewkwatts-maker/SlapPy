// GPU particle simulation — one thread per particle.
// Physics integration: gravity, drag, wind, turbulence (curl noise).
// Spawn logic is driven from the CPU side; dead particles are
// identified by lifetime <= 0.0.
//
// Bind-group layout (group 0):
//   binding 0  SimParams      uniform
//   binding 1  particles      storage read_write
//   binding 2  dead_list      storage read_write
//   binding 3  EmitterConfig  uniform   [NEW]
//   binding 4  TurbulenceConfig uniform [NEW]

// ─────────────────────────────────────────────────────────────────────────────
// Structs
// ─────────────────────────────────────────────────────────────────────────────

// 64-byte (16-byte aligned) particle record.
// Layout (byte offsets):
//   0  pos         vec2<f32>   8 B
//   8  vel         vec2<f32>   8 B
//  16  color       vec4<f32>  16 B
//  32  lifetime    f32         4 B
//  36  age         f32         4 B
//  40  size        f32         4 B
//  44  rotation    f32         4 B
//  48  angular_vel f32         4 B  [NEW: replaces first 4 B of _pad0]
//  52  _pad0       f32         4 B
//  56  _pad1       vec2<f32>   8 B
//  64  <end>
struct Particle {
    pos:         vec2<f32>,  // world-space position (pixels)
    vel:         vec2<f32>,  // velocity (pixels / second)
    color:       vec4<f32>,  // RGBA premultiplied
    lifetime:    f32,        // remaining seconds (≤ 0 → dead)
    age:         f32,        // elapsed seconds since spawn
    size:        f32,        // particle size in pixels
    rotation:    f32,        // rotation in radians
    angular_vel: f32,        // angular velocity (radians / second) [NEW]
    _pad0:       f32,        // explicit padding
    _pad1:       vec2<f32>,  // explicit padding — keeps struct at 64 B
}

struct SimParams {
    // ── per-frame physics ──────────────────────────────────────
    dt:               f32,  // delta time (seconds)
    gravity_x:        f32,  // gravity acceleration (pixels/s²)
    gravity_y:        f32,
    drag:             f32,  // linear drag: vel *= exp(-drag * dt)
    wind_x:           f32,  // wind force added to velocity each frame
    wind_y:           f32,
    // ── spawn control ─────────────────────────────────────────
    spawn_active:     u32,  // 1 = spawner is active this frame
    num_particles:    u32,  // total slots in the particles buffer
    // ── spawn parameters (used when spawn_active = 1) ─────────
    spawn_pos_x:      f32,
    spawn_pos_y:      f32,
    spawn_rate:       f32,  // particles per second (informational)
    spawn_spread:     f32,  // position spread radius
    spawn_vel_x:      f32,
    spawn_vel_y:      f32,
    spawn_vel_spread: f32,
    spawn_lifetime:   f32,
    spawn_size:       f32,
    spawn_color_r:    f32,
    spawn_color_g:    f32,
    spawn_color_b:    f32,
    spawn_color_a:    f32,
    // ── misc ───────────────────────────────────────────────────
    frame_index:      u32,  // pseudo-random seed
    time:             f32,  // total elapsed time (seconds) [replaces _pad]
    _pad2:            u32,
}

// 3D emitter configuration.
// pos.w    — shape type: 0=point, 1=sphere, 2=box, 3=cone
// extents  — xyz = half-extents (box) / radius (sphere) / cone angle rad (cone),
//            w   = cone height
// velocity_dir.xyz — normalised emission direction
// velocity_dir.w   — speed_min
// speed_range.x    — speed_max
// speed_range.y    — spread_angle (radians from velocity_dir)
struct EmitterConfig {
    pos:          vec4<f32>,  // xyz=world position, w=shape type
    extents:      vec4<f32>,  // xyz=half-extents/radius/cone-angle, w=cone_height
    velocity_dir: vec4<f32>,  // xyz=emission direction, w=speed_min
    speed_range:  vec4<f32>,  // x=speed_max, y=spread_angle, zw=_pad
}

struct TurbulenceConfig {
    strength: f32,  // force multiplier (pixels/s² per unit curl)
    speed:    f32,  // time scale for animated noise
    scale:    f32,  // spatial frequency of the noise field
    _pad:     f32,
}

// ─────────────────────────────────────────────────────────────────────────────
// Bindings
// ─────────────────────────────────────────────────────────────────────────────

@group(0) @binding(0) var<uniform>             params      : SimParams;
@group(0) @binding(1) var<storage, read_write> particles   : array<Particle>;
@group(0) @binding(2) var<storage, read_write> dead_list   : array<atomic<u32>>;
@group(0) @binding(3) var<uniform>             emitter     : EmitterConfig;
@group(0) @binding(4) var<uniform>             turbulence  : TurbulenceConfig;

// ─────────────────────────────────────────────────────────────────────────────
// RNG helpers (existing)
// ─────────────────────────────────────────────────────────────────────────────

// Cheap integer hash — Wang hash variant
fn wang_hash(seed: u32) -> u32 {
    var s = seed;
    s = (s ^ 61u) ^ (s >> 16u);
    s = s * 9u;
    s = s ^ (s >> 4u);
    s = s * 0x27d4eb2du;
    s = s ^ (s >> 15u);
    return s;
}

// Map a u32 to a float in [0, 1)
fn hash_to_f32(h: u32) -> f32 {
    return f32(h & 0x00ffffffu) / f32(0x01000000u);
}

// ─────────────────────────────────────────────────────────────────────────────
// Emitter shape sampling (NEW)
// ─────────────────────────────────────────────────────────────────────────────

// Returns three independent floats in [0, 1) from a single seed.
fn rand3(seed: u32) -> vec3<f32> {
    let h0 = wang_hash(seed);
    let h1 = wang_hash(h0 + 1u);
    let h2 = wang_hash(h1 + 1u);
    return vec3<f32>(hash_to_f32(h0), hash_to_f32(h1), hash_to_f32(h2));
}

// Sample a point from the emitter shape.
// Returns a 3-D position; callers that live in 2-D space use only .xy.
fn sample_emitter(seed: u32) -> vec3<f32> {
    let shape = u32(emitter.pos.w);
    let base  = emitter.pos.xyz;
    let r     = rand3(seed);

    if shape == 0u {
        // ── Point ────────────────────────────────────────────────────────────
        return base;

    } else if shape == 1u {
        // ── Sphere surface ────────────────────────────────────────────────────
        // Uniform sphere surface via Wang hash → spherical coordinates.
        // theta in [0, pi], phi in [0, 2*pi]
        let radius = emitter.extents.x;
        let cosTheta = 1.0 - 2.0 * r.x;          // maps [0,1] → [1,-1]
        let sinTheta = sqrt(max(0.0, 1.0 - cosTheta * cosTheta));
        let phi      = 6.2831853 * r.y;           // 2π
        let dir = vec3<f32>(sinTheta * cos(phi), sinTheta * sin(phi), cosTheta);
        return base + dir * radius;

    } else if shape == 2u {
        // ── Box interior ──────────────────────────────────────────────────────
        // r in [0,1]³ → mapped to [-1,1]³ → scaled by half-extents
        let offset = (r * 2.0 - vec3<f32>(1.0)) * emitter.extents.xyz;
        return base + offset;

    } else {
        // ── Cone surface (shape == 3) ─────────────────────────────────────────
        // emitter.extents.x = half-angle (radians), emitter.extents.w = height
        // emitter.velocity_dir.xyz = cone axis direction
        let half_angle  = emitter.extents.x;
        let cone_height = emitter.extents.w;
        let axis        = normalize(emitter.velocity_dir.xyz);

        // Pick a random angle within the cone aperture and a random azimuth.
        let theta = half_angle * r.x;             // [0, half_angle]
        let phi   = 6.2831853 * r.y;              // [0, 2π]
        let t     = r.z * cone_height;            // distance along axis

        // Build an orthonormal frame around the axis.
        // Choose a non-parallel reference vector for the cross product.
        var ref_vec = vec3<f32>(1.0, 0.0, 0.0);
        if abs(axis.x) > 0.9 {
            ref_vec = vec3<f32>(0.0, 1.0, 0.0);
        }
        let tangent   = normalize(cross(axis, ref_vec));
        let bitangent = cross(axis, tangent);

        // Direction on cone surface.
        let sinT   = sin(theta);
        let cosT   = cos(theta);
        let dir    = axis * cosT + tangent * (sinT * cos(phi)) + bitangent * (sinT * sin(phi));
        return base + dir * t;
    }
}

// Sample an initial velocity from emitter config, using 3 floats from seed.
fn sample_emitter_velocity(seed: u32) -> vec3<f32> {
    let r           = rand3(seed);
    let speed_min   = emitter.velocity_dir.w;
    let speed_max   = emitter.speed_range.x;
    let spread      = emitter.speed_range.y;
    let axis        = normalize(emitter.velocity_dir.xyz);
    let speed       = speed_min + (speed_max - speed_min) * r.x;

    // Cone-spread the direction around the emission axis.
    let theta = spread * r.y;
    let phi   = 6.2831853 * r.z;

    var ref_vec = vec3<f32>(1.0, 0.0, 0.0);
    if abs(axis.x) > 0.9 {
        ref_vec = vec3<f32>(0.0, 1.0, 0.0);
    }
    let tangent   = normalize(cross(axis, ref_vec));
    let bitangent = cross(axis, tangent);

    let sinT  = sin(theta);
    let cosT  = cos(theta);
    let dir   = axis * cosT + tangent * (sinT * cos(phi)) + bitangent * (sinT * sin(phi));
    return dir * speed;
}

// ─────────────────────────────────────────────────────────────────────────────
// Turbulence — 3-D curl noise (NEW)
// ─────────────────────────────────────────────────────────────────────────────

// Deterministic 3-D → 3-D hash for gradient noise.
fn hash3(p: vec3<f32>) -> vec3<f32> {
    // Convert each component to a u32 bit pattern, fold together, re-hash.
    var ip = vec3<u32>(
        bitcast<u32>(p.x + 1000.0),
        bitcast<u32>(p.y + 1000.0),
        bitcast<u32>(p.z + 1000.0),
    );
    // Mix the three channels with Wang hash and XOR.
    let hx = wang_hash(ip.x ^ (ip.y * 1234567u) ^ (ip.z * 7654321u));
    let hy = wang_hash(ip.y ^ (ip.z * 2345678u) ^ (ip.x * 8765432u));
    let hz = wang_hash(ip.z ^ (ip.x * 3456789u) ^ (ip.y * 9876543u));
    return vec3<f32>(hash_to_f32(hx), hash_to_f32(hy), hash_to_f32(hz)) * 2.0 - vec3<f32>(1.0);
}

// Trilinear interpolation helper.
fn trilerp(c000: f32, c100: f32, c010: f32, c110: f32,
           c001: f32, c101: f32, c011: f32, c111: f32,
           t: vec3<f32>) -> f32 {
    let tx = t.x;
    let ty = t.y;
    let tz = t.z;
    let c00 = mix(c000, c100, tx);
    let c10 = mix(c010, c110, tx);
    let c01 = mix(c001, c101, tx);
    let c11 = mix(c011, c111, tx);
    let c0  = mix(c00,  c10,  ty);
    let c1  = mix(c01,  c11,  ty);
    return mix(c0, c1, tz);
}

// Quintic smoothstep for gradient noise (C2 continuity).
fn smoothstep5(t: vec3<f32>) -> vec3<f32> {
    return t * t * t * (t * (t * 6.0 - vec3<f32>(15.0)) + vec3<f32>(10.0));
}

// Value gradient noise in [-1, 1].
fn grad_noise(p: vec3<f32>) -> f32 {
    let i  = floor(p);
    let f  = fract(p);
    let u  = smoothstep5(f);

    // Lattice corner gradients — dot(hash, f-corner).
    let g000 = hash3(i + vec3<f32>(0.0, 0.0, 0.0));
    let g100 = hash3(i + vec3<f32>(1.0, 0.0, 0.0));
    let g010 = hash3(i + vec3<f32>(0.0, 1.0, 0.0));
    let g110 = hash3(i + vec3<f32>(1.0, 1.0, 0.0));
    let g001 = hash3(i + vec3<f32>(0.0, 0.0, 1.0));
    let g101 = hash3(i + vec3<f32>(1.0, 0.0, 1.0));
    let g011 = hash3(i + vec3<f32>(0.0, 1.0, 1.0));
    let g111 = hash3(i + vec3<f32>(1.0, 1.0, 1.0));

    let d000 = dot(g000, f - vec3<f32>(0.0, 0.0, 0.0));
    let d100 = dot(g100, f - vec3<f32>(1.0, 0.0, 0.0));
    let d010 = dot(g010, f - vec3<f32>(0.0, 1.0, 0.0));
    let d110 = dot(g110, f - vec3<f32>(1.0, 1.0, 0.0));
    let d001 = dot(g001, f - vec3<f32>(0.0, 0.0, 1.0));
    let d101 = dot(g101, f - vec3<f32>(1.0, 0.0, 1.0));
    let d011 = dot(g011, f - vec3<f32>(0.0, 1.0, 1.0));
    let d111 = dot(g111, f - vec3<f32>(1.0, 1.0, 1.0));

    return trilerp(d000, d100, d010, d110, d001, d101, d011, d111, u);
}

// Curl of a 3-D gradient noise field, approximated by finite differences.
// The curl of (Fz.y - Fy.z, Fx.z - Fz.x, Fy.x - Fx.y) is divergence-free.
// We use three offset noise fields as F components.
fn curl_noise(p: vec3<f32>, t: f32) -> vec3<f32> {
    let eps = 0.01;
    let pt  = p + vec3<f32>(0.0, 0.0, t);  // animate by shifting z with time

    // Three independent noise fields via positional offsets.
    let Fx_py = grad_noise(pt + vec3<f32>(0.0, eps, 0.0));
    let Fx_my = grad_noise(pt - vec3<f32>(0.0, eps, 0.0));
    let Fx_pz = grad_noise(pt + vec3<f32>(0.0, 0.0, eps));
    let Fx_mz = grad_noise(pt - vec3<f32>(0.0, 0.0, eps));

    let Fy_px = grad_noise(pt + vec3<f32>(eps, 0.0, 0.0) + vec3<f32>(31.41, 0.0, 0.0));
    let Fy_mx = grad_noise(pt - vec3<f32>(eps, 0.0, 0.0) + vec3<f32>(31.41, 0.0, 0.0));
    let Fy_pz = grad_noise(pt + vec3<f32>(0.0, 0.0, eps) + vec3<f32>(31.41, 0.0, 0.0));
    let Fy_mz = grad_noise(pt - vec3<f32>(0.0, 0.0, eps) + vec3<f32>(31.41, 0.0, 0.0));

    let Fz_px = grad_noise(pt + vec3<f32>(eps, 0.0, 0.0) + vec3<f32>(0.0, 47.85, 0.0));
    let Fz_mx = grad_noise(pt - vec3<f32>(eps, 0.0, 0.0) + vec3<f32>(0.0, 47.85, 0.0));
    let Fz_py2 = grad_noise(pt + vec3<f32>(0.0, eps, 0.0) + vec3<f32>(0.0, 47.85, 0.0));
    let Fz_my2 = grad_noise(pt - vec3<f32>(0.0, eps, 0.0) + vec3<f32>(0.0, 47.85, 0.0));

    let inv2eps = 1.0 / (2.0 * eps);
    let curl_x = (Fz_py2 - Fz_my2) * inv2eps - (Fy_pz - Fy_mz) * inv2eps;
    let curl_y = (Fx_pz  - Fx_mz)  * inv2eps - (Fz_px - Fz_mx) * inv2eps;
    let curl_z = (Fy_px  - Fy_mx)  * inv2eps - (Fx_py - Fx_my) * inv2eps;

    return vec3<f32>(curl_x, curl_y, curl_z);
}

// ─────────────────────────────────────────────────────────────────────────────
// Simulate entry point
// ─────────────────────────────────────────────────────────────────────────────

@compute @workgroup_size(64)
fn simulate(@builtin(global_invocation_id) gid: vec3<u32>) {
    let idx = gid.x;
    if idx >= params.num_particles {
        return;
    }

    var p  = particles[idx];
    let dt = params.dt;

    // ── Dead particle ────────────────────────────────────────────────────────
    if p.lifetime <= 0.0 {
        // Tally the dead slot count so the CPU can query it cheaply.
        atomicAdd(&dead_list[0], 1u);

        // If the spawner is active, re-initialise this slot.
        if params.spawn_active == 1u {
            // Per-particle seed: mix particle index and frame index.
            let seed0 = wang_hash(idx ^ (params.frame_index * 2654435761u));

            // ── Position from emitter shape ───────────────────────────────────
            let spawn3d = sample_emitter(seed0);
            p.pos = spawn3d.xy;

            // ── Velocity from emitter config or legacy spawn params ───────────
            // Use emitter velocity if a non-zero direction is set.
            let has_emitter_vel = dot(emitter.velocity_dir.xyz, emitter.velocity_dir.xyz) > 0.0001;
            if has_emitter_vel {
                let vel3d = sample_emitter_velocity(wang_hash(seed0 + 99u));
                p.vel = vel3d.xy;
            } else {
                // Fall back to the legacy 2-D spawn parameters.
                let seed1 = wang_hash(seed0 + 1u);
                let seed2 = wang_hash(seed1 + 1u);
                let seed3 = wang_hash(seed2 + 1u);
                let seed4 = wang_hash(seed3 + 1u);
                let rx  = hash_to_f32(seed1) * 2.0 - 1.0;
                let ry  = hash_to_f32(seed2) * 2.0 - 1.0;
                let rvx = hash_to_f32(seed3) * 2.0 - 1.0;
                let rvy = hash_to_f32(seed4) * 2.0 - 1.0;
                p.pos = vec2<f32>(
                    params.spawn_pos_x + rx * params.spawn_spread,
                    params.spawn_pos_y + ry * params.spawn_spread,
                );
                p.vel = vec2<f32>(
                    params.spawn_vel_x + rvx * params.spawn_vel_spread,
                    params.spawn_vel_y + rvy * params.spawn_vel_spread,
                );
            }

            p.color       = vec4<f32>(params.spawn_color_r, params.spawn_color_g,
                                      params.spawn_color_b, params.spawn_color_a);
            p.lifetime    = params.spawn_lifetime;
            p.age         = 0.0;
            p.size        = params.spawn_size;
            p.rotation    = 0.0;
            p.angular_vel = 0.0;
        }

        particles[idx] = p;
        return;
    }

    // ── Live particle — integrate physics ────────────────────────────────────

    // Apply gravity and wind.
    let gravity = vec2<f32>(params.gravity_x, params.gravity_y);
    let wind    = vec2<f32>(params.wind_x,    params.wind_y);
    p.vel += (gravity + wind) * dt;

    // Exponential drag: vel *= exp(-drag * dt)
    let drag_factor = exp(-params.drag * dt);
    p.vel *= drag_factor;

    // ── Turbulence (curl noise) ───────────────────────────────────────────────
    if turbulence.strength > 0.0 {
        // Lift the 2-D position into 3-D noise space; z = 0 for this system.
        let world3 = vec3<f32>(p.pos * turbulence.scale, 0.0);
        let t      = params.time * turbulence.speed;
        let turb   = curl_noise(world3, t);
        // Apply only the XY components of the 3-D curl to the 2-D velocity.
        p.vel += turb.xy * turbulence.strength * dt;
    }

    // Euler position integration.
    p.pos += p.vel * dt;

    // ── Rotation update ───────────────────────────────────────────────────────
    p.rotation += p.angular_vel * dt;

    // Age the particle.
    p.age      += dt;
    p.lifetime -= dt;

    particles[idx] = p;
}
