// sdf_scene.wgsl — GPU SDF primitive tree evaluator
//
// Defines the SdfPrimitive SSBO layout, per-primitive SDF functions, CSG
// combinators, and the scene_sdf / scene_normal evaluators.
//
// WGSL has no #include directive.  This file is a shared module: at pipeline
// build time the Python shader loader copies its full contents into any shader
// that needs scene evaluation (e.g. sdf_raymarching.wgsl).  The two bindings
// below exist only so this file is valid as a standalone compute module for
// unit testing; consuming shaders re-declare the same bindings in their own
// @group(0).
//
// Binding layout:
//   @group(0) @binding(0) — primitives     array<SdfPrimitive>  (storage, read)
//   @group(0) @binding(1) — scene_uniforms SceneUniforms        (uniform)
//
// Primitive type constants (must match src/sdf.rs SdfPrimType enum):
//   PRIM_SPHERE       = 0
//   PRIM_BOX          = 1
//   PRIM_CYLINDER     = 2
//   PRIM_CAPSULE      = 3
//   PRIM_CONE         = 4
//   PRIM_TORUS        = 5
//   PRIM_PLANE        = 6
//   PRIM_ROUNDED_BOX  = 7
//
// CSG op constants (must match src/sdf.rs CsgOp enum):
//   CSG_UNION           = 0
//   CSG_SUBTRACT        = 1
//   CSG_INTERSECT       = 2
//   CSG_SMOOTH_UNION    = 3
//   CSG_SMOOTH_SUBTRACT = 4
//   CSG_SMOOTH_INTERSECT= 5

// ── Primitive type constants ──────────────────────────────────────────────────

const PRIM_SPHERE:      u32 = 0u;
const PRIM_BOX:         u32 = 1u;
const PRIM_CYLINDER:    u32 = 2u;
const PRIM_CAPSULE:     u32 = 3u;
const PRIM_CONE:        u32 = 4u;
const PRIM_TORUS:       u32 = 5u;
const PRIM_PLANE:       u32 = 6u;
const PRIM_ROUNDED_BOX: u32 = 7u;

// ── CSG op constants ──────────────────────────────────────────────────────────

const CSG_UNION:            u32 = 0u;
const CSG_SUBTRACT:         u32 = 1u;
const CSG_INTERSECT:        u32 = 2u;
const CSG_SMOOTH_UNION:     u32 = 3u;
const CSG_SMOOTH_SUBTRACT:  u32 = 4u;
const CSG_SMOOTH_INTERSECT: u32 = 5u;

// ── GPU data structures ───────────────────────────────────────────────────────

// Each primitive is 48 bytes (3 × vec4<f32> + 2 × u32 + 2 × u32 pad).
// GPU layout — must match SdfPrimitive::to_gpu_bytes() in src/sdf.rs:
//   center   : vec4<f32>   offset  0  (xyz = world-space centre, w = param0)
//   params   : vec4<f32>   offset 16  (x=half_y, y=half_z, z=smooth_k, w=round_r)
//   prim_type: u32          offset 32
//   csg_op   : u32          offset 36
//   _pad0    : u32          offset 40  (reserved)
//   _pad1    : u32          offset 44  (reserved)
//
// param0 semantics per primitive type:
//   SPHERE       — center.w = radius
//   BOX          — center.w = half_x, params.xy = half_y / half_z
//   CYLINDER     — center.w = radius, params.x  = half_height
//   CAPSULE      — center.xyz = endpoint A, params.xyz = endpoint B, center.w = radius
//   CONE         — center.w = half_height, params.x = tan(half_angle)
//   TORUS        — center.w = major_radius, params.x = minor_radius
//   PLANE        — center.xyz = plane normal (unit), center.w = d (dot(n, point_on_plane))
//   ROUNDED_BOX  — center.w = half_x, params.xy = half_y / half_z, params.w = corner_r
struct SdfPrimitive {
    center:    vec4<f32>,   // xyz = centre, w = param0
    params:    vec4<f32>,   // x=half_y, y=half_z, z=smooth_k, w=round_r
    prim_type: u32,
    csg_op:    u32,
    _pad0:     u32,
    _pad1:     u32,
}

struct SceneUniforms {
    prim_count: u32,
    _pad:       vec3<u32>,
}

// ── Bindings ──────────────────────────────────────────────────────────────────

@group(0) @binding(0) var<storage, read> primitives     : array<SdfPrimitive>;
@group(0) @binding(1) var<uniform>       scene_uniforms : SceneUniforms;

// ── Math constants ────────────────────────────────────────────────────────────

const SDF_EPS: f32 = 0.001;    // central-difference step for normals

// ── SDF primitive functions ───────────────────────────────────────────────────

// Signed distance to a sphere.
fn sdf_sphere(p: vec3<f32>, center: vec3<f32>, r: f32) -> f32 {
    return length(p - center) - r;
}

// Signed distance to an axis-aligned box, optionally rounded (r > 0 rounds edges).
// b: positive half-extents (x, y, z).
fn sdf_box(p: vec3<f32>, center: vec3<f32>, b: vec3<f32>, r: f32) -> f32 {
    let q = abs(p - center) - b + r;
    return length(max(q, vec3<f32>(0.0))) + min(max(q.x, max(q.y, q.z)), 0.0) - r;
}

// Signed distance to an upright cylinder centred at `center`.
// h: half-height along Y; r: radius in XZ.
fn sdf_cylinder(p: vec3<f32>, center: vec3<f32>, h: f32, r: f32) -> f32 {
    let d = abs(vec2<f32>(length((p - center).xz), (p - center).y)) - vec2<f32>(r, h);
    return length(max(d, vec2<f32>(0.0))) + min(max(d.x, d.y), 0.0);
}

// Signed distance to a capsule (line-segment swept sphere).
// a, b: the two endpoint centres; r: radius.
fn sdf_capsule(p: vec3<f32>, a: vec3<f32>, b: vec3<f32>, r: f32) -> f32 {
    let pa = p - a;
    let ba = b - a;
    let h  = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h) - r;
}

// Signed distance to an upright cone with its tip at center + (0, h, 0) and
// its open base at center - (0, h, 0).  angle: half-apex angle in radians.
fn sdf_cone(p: vec3<f32>, center: vec3<f32>, h: f32, angle: f32) -> f32 {
    // Shift to local frame with origin at the tip.
    let lp    = p - (center + vec3<f32>(0.0, h, 0.0));
    let q     = vec2<f32>(length(lp.xz), -lp.y);
    let c     = vec2<f32>(sin(angle), cos(angle));
    let tip_d = q - c * clamp(dot(q, c), 0.0, 2.0 * h);
    let base  = vec2<f32>(q.x - clamp(q.x, 0.0, c.x / c.y * 2.0 * h), q.y + 2.0 * h);
    let s     = select(1.0, -1.0, cross(vec3<f32>(c, 0.0), vec3<f32>(q, 0.0)).z < 0.0);
    return s * sqrt(min(dot(tip_d, tip_d), dot(base, base)));
}

// Signed distance to a torus lying in the XZ plane, centred at `center`.
// r_major: ring radius; r_minor: tube radius.
fn sdf_torus(p: vec3<f32>, center: vec3<f32>, r_major: f32, r_minor: f32) -> f32 {
    let lp = p - center;
    let q  = vec2<f32>(length(lp.xz) - r_major, lp.y);
    return length(q) - r_minor;
}

// Signed distance to an infinite plane.
// n: outward unit normal; d: signed offset (d = dot(n, any_point_on_plane)).
fn sdf_plane(p: vec3<f32>, n: vec3<f32>, d: f32) -> f32 {
    return dot(p, n) - d;
}

// ── CSG combinators ───────────────────────────────────────────────────────────

// Smooth minimum (smin) — used for smooth union, subtract, and intersect.
// k: blending radius; larger k = softer transition.

fn csg_smooth_union(d1: f32, d2: f32, k: f32) -> f32 {
    let h = clamp(0.5 + 0.5 * (d2 - d1) / k, 0.0, 1.0);
    return mix(d2, d1, h) - k * h * (1.0 - h);
}

fn csg_smooth_sub(d1: f32, d2: f32, k: f32) -> f32 {
    // Subtract d2 from d1: carve d2's shape out of d1.
    return csg_smooth_union(d1, -d2, k);
}

fn csg_smooth_int(d1: f32, d2: f32, k: f32) -> f32 {
    let h = clamp(0.5 - 0.5 * (d2 - d1) / k, 0.0, 1.0);
    return mix(d2, d1, h) + k * h * (1.0 - h);
}

// ── Scene evaluator ───────────────────────────────────────────────────────────

// Evaluate the combined scene SDF at point `p` by iterating over all
// primitives and applying their CSG operations left-to-right.
//
// The first primitive always seeds the accumulator (union with +INF starts
// cleanly for any CSG op on the second element).
fn scene_sdf(p: vec3<f32>) -> f32 {
    var d: f32 = 1e20;   // +infinity seed

    let count = scene_uniforms.prim_count;
    for (var i = 0u; i < count; i++) {
        let prim = primitives[i];
        let c    = prim.center.xyz;

        // ── Evaluate the primitive's own distance ─────────────────────────────
        var prim_d: f32;
        switch prim.prim_type {
            case PRIM_SPHERE: {
                prim_d = sdf_sphere(p, c, prim.center.w);
            }
            case PRIM_BOX: {
                let b = vec3<f32>(prim.center.w, prim.params.x, prim.params.y);
                prim_d = sdf_box(p, c, b, 0.0);
            }
            case PRIM_CYLINDER: {
                prim_d = sdf_cylinder(p, c, prim.params.x, prim.center.w);
            }
            case PRIM_CAPSULE: {
                // For capsule: center.xyz = endpoint A, params.xyz = endpoint B
                let b_pt = prim.params.xyz;
                prim_d = sdf_capsule(p, c, b_pt, prim.center.w);
            }
            case PRIM_CONE: {
                prim_d = sdf_cone(p, c, prim.center.w, prim.params.x);
            }
            case PRIM_TORUS: {
                prim_d = sdf_torus(p, c, prim.center.w, prim.params.x);
            }
            case PRIM_PLANE: {
                prim_d = sdf_plane(p, c, prim.center.w);
            }
            case PRIM_ROUNDED_BOX: {
                let b = vec3<f32>(prim.center.w, prim.params.x, prim.params.y);
                prim_d = sdf_box(p, c, b, prim.params.w);
            }
            default: {
                prim_d = 1e20;
            }
        }

        // ── Apply CSG op against the running accumulator ───────────────────────
        let k = prim.params.z;   // smooth_k (ignored for hard ops)
        switch prim.csg_op {
            case CSG_UNION: {
                d = min(d, prim_d);
            }
            case CSG_SUBTRACT: {
                d = max(d, -prim_d);
            }
            case CSG_INTERSECT: {
                d = max(d, prim_d);
            }
            case CSG_SMOOTH_UNION: {
                d = csg_smooth_union(d, prim_d, k);
            }
            case CSG_SMOOTH_SUBTRACT: {
                d = csg_smooth_sub(d, prim_d, k);
            }
            case CSG_SMOOTH_INTERSECT: {
                d = csg_smooth_int(d, prim_d, k);
            }
            default: {
                d = min(d, prim_d);
            }
        }
    }

    return d;
}

// ── Surface normal via central differences ────────────────────────────────────

// Estimate the scene-SDF gradient at `p` using 6-sample central differences.
// Returns a unit-length outward normal.
fn scene_normal(p: vec3<f32>) -> vec3<f32> {
    let e = SDF_EPS;
    let n = vec3<f32>(
        scene_sdf(p + vec3<f32>( e, 0.0, 0.0)) - scene_sdf(p - vec3<f32>( e, 0.0, 0.0)),
        scene_sdf(p + vec3<f32>(0.0,  e, 0.0)) - scene_sdf(p - vec3<f32>(0.0,  e, 0.0)),
        scene_sdf(p + vec3<f32>(0.0, 0.0,  e)) - scene_sdf(p - vec3<f32>(0.0, 0.0,  e)),
    );
    return normalize(n);
}
