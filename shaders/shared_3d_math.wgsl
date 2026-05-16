// shared_3d_math.wgsl
// Pure helper functions for 3D rendering — no entry point, no bindings.
// The Python shader loader inlines this into any shader that needs it.
// All math uses f32; no f64.

// ── Quaternion → 4×4 rotation matrix ──────────────────────────────────────
// q is (x, y, z, w) — Hamilton convention, unit quaternion assumed.
fn quat_to_mat4(q: vec4<f32>) -> mat4x4<f32> {
    let x = q.x; let y = q.y; let z = q.z; let w = q.w;
    let x2 = x + x; let y2 = y + y; let z2 = z + z;
    let xx = x * x2; let xy = x * y2; let xz = x * z2;
    let yy = y * y2; let yz = y * z2; let zz = z * z2;
    let wx = w * x2; let wy = w * y2; let wz = w * z2;
    return mat4x4<f32>(
        vec4<f32>(1.0 - (yy + zz), xy + wz,         xz - wy,         0.0),
        vec4<f32>(xy - wz,         1.0 - (xx + zz),  yz + wx,         0.0),
        vec4<f32>(xz + wy,         yz - wx,           1.0 - (xx + yy), 0.0),
        vec4<f32>(0.0,             0.0,               0.0,             1.0),
    );
}

// ── Transform a point (applies translation) ────────────────────────────────
fn mat4_mul_point(m: mat4x4<f32>, p: vec3<f32>) -> vec3<f32> {
    let r = m * vec4<f32>(p, 1.0);
    return r.xyz;
}

// ── Transform a direction (ignores translation) ────────────────────────────
fn mat4_mul_dir(m: mat4x4<f32>, d: vec3<f32>) -> vec3<f32> {
    let r = m * vec4<f32>(d, 0.0);
    return r.xyz;
}

// ── Fresnel-Schlick approximation ─────────────────────────────────────────
// cos_theta: dot(V, H) clamped to [0,1].
// F0: base reflectivity at normal incidence.
fn fresnel_schlick(cos_theta: f32, F0: vec3<f32>) -> vec3<f32> {
    let t = clamp(1.0 - cos_theta, 0.0, 1.0);
    let t2 = t * t;
    let t5 = t2 * t2 * t;
    return F0 + (vec3<f32>(1.0) - F0) * t5;
}

// ── GGX / Trowbridge-Reitz normal distribution function ───────────────────
fn distribution_ggx(N: vec3<f32>, H: vec3<f32>, roughness: f32) -> f32 {
    let a  = roughness * roughness;
    let a2 = a * a;
    let NdotH  = max(dot(N, H), 0.0);
    let NdotH2 = NdotH * NdotH;
    let denom = NdotH2 * (a2 - 1.0) + 1.0;
    // PI approximated with a constant to avoid the import.
    let PI: f32 = 3.14159265358979;
    return a2 / (PI * denom * denom);
}

// ── Schlick-GGX geometry sub-function ─────────────────────────────────────
fn geometry_schlick_ggx(NdotV: f32, roughness: f32) -> f32 {
    let r = roughness + 1.0;
    let k = (r * r) / 8.0;
    return NdotV / (NdotV * (1.0 - k) + k);
}

// ── Smith geometry function ────────────────────────────────────────────────
fn geometry_smith(N: vec3<f32>, V: vec3<f32>, L: vec3<f32>, roughness: f32) -> f32 {
    let NdotV = max(dot(N, V), 0.0);
    let NdotL = max(dot(N, L), 0.0);
    let ggx1 = geometry_schlick_ggx(NdotV, roughness);
    let ggx2 = geometry_schlick_ggx(NdotL, roughness);
    return ggx1 * ggx2;
}

// ── Cook-Torrance PBR shading ─────────────────────────────────────────────
// Returns the outgoing radiance for a single punctual light.
// albedo    : linear-space surface colour (pre-multiplied by texture sample if any).
// metallic  : 0 = dielectric, 1 = conductor.
// roughness : perceptual roughness [0,1].
// N         : surface normal (world space, normalised).
// V         : view direction (world space, normalised, pointing toward camera).
// L         : light direction (world space, normalised, pointing toward light).
// light_color     : linear RGB of the light source.
// light_intensity : scalar multiplier (candela / lux equivalent, scene-unit).
fn pbr_cook_torrance(
    albedo: vec3<f32>,
    metallic: f32,
    roughness: f32,
    N: vec3<f32>,
    V: vec3<f32>,
    L: vec3<f32>,
    light_color: vec3<f32>,
    light_intensity: f32,
) -> vec3<f32> {
    let PI: f32 = 3.14159265358979;
    let H = normalize(V + L);

    let NdotL = max(dot(N, L), 0.0);

    // Base reflectivity: 0.04 for dielectrics, albedo for metals.
    let F0 = mix(vec3<f32>(0.04), albedo, metallic);

    // Cook-Torrance specular BRDF terms.
    let D = distribution_ggx(N, H, roughness);
    let G = geometry_smith(N, V, L, roughness);
    let F = fresnel_schlick(max(dot(H, V), 0.0), F0);

    let numerator   = D * G * F;
    let denominator = 4.0 * max(dot(N, V), 0.0) * NdotL + 0.0001;
    let specular    = numerator / denominator;

    // Diffuse: metals have no diffuse (energy absorbed into free electrons).
    let kD = (vec3<f32>(1.0) - F) * (1.0 - metallic);
    let diffuse = kD * albedo / PI;

    let radiance = light_color * light_intensity;
    return (diffuse + specular) * radiance * NdotL;
}
