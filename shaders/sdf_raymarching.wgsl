// sdf_raymarching.wgsl — 3D SDF sphere-tracer compute shader
//
// Generates a ray per pixel from camera parameters, marches it against the
// SDF scene, and writes world-space hit position + normal into storage textures
// for downstream deferred shading (e.g. sdf_gbuffer_write.wgsl).
//
// Bind groups:
//   @group(0) @binding(0) — primitives       array<SdfPrimitive>                (storage, read)
//   @group(0) @binding(1) — scene_uniforms   SceneUniforms                      (uniform)
//   @group(0) @binding(2) — rm_uniforms      RaymarchUniforms                   (uniform)
//   @group(0) @binding(3) — hit_pos_tex      texture_storage_2d<rgba32float, write>
//                           world-space hit position (xyz) + total march distance (w)
//   @group(0) @binding(4) — hit_normal_tex   texture_storage_2d<rgba16float, write>
//                           world-space surface normal (xyz) + hit flag (w: 0=miss, 1=hit)
//
// Dispatch: ceil(width/8) × ceil(height/8) × 1 workgroups.
//
// NOTE: This shader is self-contained.  The SDF functions from sdf_scene.wgsl
// are duplicated here verbatim (WGSL has no #include directive).  The Python
// shader loader performs the copy at pipeline construction time so the
// canonical definitions stay in sdf_scene.wgsl.

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

// ── Math constants ────────────────────────────────────────────────────────────

const SDF_EPS:    f32 = 0.001;   // central-difference step for normals
const SDF_NORMAL_H: f32 = 0.001; // alias used by the normal estimator

// ── GPU data structures ───────────────────────────────────────────────────────

struct SdfPrimitive {
    center:    vec4<f32>,   // xyz = centre, w = param0
    params:    vec4<f32>,   // x=half_y / minor_r, y=half_z, z=smooth_k, w=round_r
    prim_type: u32,
    csg_op:    u32,
    _pad0:     u32,
    _pad1:     u32,
}

struct SceneUniforms {
    prim_count: u32,
    _pad:       vec3<u32>,
}

// Camera and raymarcher parameters.
// GPU layout (96 bytes, all vec4-padded):
//   cam_pos   : vec4<f32>  offset  0   (xyz = world-space position, w unused)
//   cam_dir   : vec4<f32>  offset 16   (xyz = normalised forward vector, w unused)
//   cam_right : vec4<f32>  offset 32   (xyz = normalised right vector, w unused)
//   cam_up    : vec4<f32>  offset 48   (xyz = normalised up vector, w unused)
//   fov_y     : f32        offset 64   (vertical field-of-view in radians)
//   max_steps : u32        offset 68   (sphere-trace iteration cap, default 128)
//   max_dist  : f32        offset 72   (far plane / bail-out distance)
//   hit_eps   : f32        offset 76   (hit threshold, default 0.001)
//   width     : u32        offset 80   (output texture width in pixels)
//   height    : u32        offset 84   (output texture height in pixels)
//   _pad0     : u32        offset 88
//   _pad1     : u32        offset 92
struct RaymarchUniforms {
    cam_pos:   vec4<f32>,
    cam_dir:   vec4<f32>,
    cam_right: vec4<f32>,
    cam_up:    vec4<f32>,
    fov_y:     f32,
    max_steps: u32,
    max_dist:  f32,
    hit_eps:   f32,
    width:     u32,
    height:    u32,
    _pad0:     u32,
    _pad1:     u32,
}

// ── Bindings ──────────────────────────────────────────────────────────────────

@group(0) @binding(0) var<storage, read> primitives     : array<SdfPrimitive>;
@group(0) @binding(1) var<uniform>       scene_uniforms : SceneUniforms;
@group(0) @binding(2) var<uniform>       rm_uniforms    : RaymarchUniforms;
@group(0) @binding(3) var                hit_pos_tex    : texture_storage_2d<rgba32float, write>;
@group(0) @binding(4) var                hit_normal_tex : texture_storage_2d<rgba16float, write>;

// ── SDF primitive functions (copied from sdf_scene.wgsl) ─────────────────────

fn sdf_sphere(p: vec3<f32>, center: vec3<f32>, r: f32) -> f32 {
    return length(p - center) - r;
}

fn sdf_box(p: vec3<f32>, center: vec3<f32>, b: vec3<f32>, r: f32) -> f32 {
    let q = abs(p - center) - b + r;
    return length(max(q, vec3<f32>(0.0))) + min(max(q.x, max(q.y, q.z)), 0.0) - r;
}

fn sdf_cylinder(p: vec3<f32>, center: vec3<f32>, h: f32, r: f32) -> f32 {
    let d = abs(vec2<f32>(length((p - center).xz), (p - center).y)) - vec2<f32>(r, h);
    return length(max(d, vec2<f32>(0.0))) + min(max(d.x, d.y), 0.0);
}

fn sdf_capsule(p: vec3<f32>, a: vec3<f32>, b: vec3<f32>, r: f32) -> f32 {
    let pa = p - a;
    let ba = b - a;
    let h  = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h) - r;
}

fn sdf_cone(p: vec3<f32>, center: vec3<f32>, h: f32, angle: f32) -> f32 {
    let lp    = p - (center + vec3<f32>(0.0, h, 0.0));
    let q     = vec2<f32>(length(lp.xz), -lp.y);
    let c     = vec2<f32>(sin(angle), cos(angle));
    let tip_d = q - c * clamp(dot(q, c), 0.0, 2.0 * h);
    let base  = vec2<f32>(q.x - clamp(q.x, 0.0, c.x / c.y * 2.0 * h), q.y + 2.0 * h);
    let s     = select(1.0, -1.0, cross(vec3<f32>(c, 0.0), vec3<f32>(q, 0.0)).z < 0.0);
    return s * sqrt(min(dot(tip_d, tip_d), dot(base, base)));
}

fn sdf_torus(p: vec3<f32>, center: vec3<f32>, r_major: f32, r_minor: f32) -> f32 {
    let lp = p - center;
    let q  = vec2<f32>(length(lp.xz) - r_major, lp.y);
    return length(q) - r_minor;
}

fn sdf_plane(p: vec3<f32>, n: vec3<f32>, d: f32) -> f32 {
    return dot(p, n) - d;
}

// ── CSG combinators ───────────────────────────────────────────────────────────

fn csg_smooth_union(d1: f32, d2: f32, k: f32) -> f32 {
    let h = clamp(0.5 + 0.5 * (d2 - d1) / k, 0.0, 1.0);
    return mix(d2, d1, h) - k * h * (1.0 - h);
}

fn csg_smooth_sub(d1: f32, d2: f32, k: f32) -> f32 {
    return csg_smooth_union(d1, -d2, k);
}

fn csg_smooth_int(d1: f32, d2: f32, k: f32) -> f32 {
    let h = clamp(0.5 - 0.5 * (d2 - d1) / k, 0.0, 1.0);
    return mix(d2, d1, h) + k * h * (1.0 - h);
}

// ── Scene evaluator ───────────────────────────────────────────────────────────

fn scene_sdf(p: vec3<f32>) -> f32 {
    var d: f32 = 1e20;

    let count = scene_uniforms.prim_count;
    for (var i = 0u; i < count; i++) {
        let prim = primitives[i];
        let c    = prim.center.xyz;

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

        let k = prim.params.z;
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

fn scene_normal(p: vec3<f32>) -> vec3<f32> {
    let e = SDF_NORMAL_H;
    let n = vec3<f32>(
        scene_sdf(p + vec3<f32>( e, 0.0, 0.0)) - scene_sdf(p - vec3<f32>( e, 0.0, 0.0)),
        scene_sdf(p + vec3<f32>(0.0,  e, 0.0)) - scene_sdf(p - vec3<f32>(0.0,  e, 0.0)),
        scene_sdf(p + vec3<f32>(0.0, 0.0,  e)) - scene_sdf(p - vec3<f32>(0.0, 0.0,  e)),
    );
    return normalize(n);
}

// ── Soft shadow via cone marching ─────────────────────────────────────────────

// March from `pos` toward `light_dir` for up to `max_d` world units,
// returning a soft shadow factor in [0, 1] (0 = fully shadowed, 1 = fully lit).
//
// k: sharpness of the penumbra.  Typical range 2..32; higher = harder shadow.
// Uses the Quilez soft-shadow formula: accumulate minimum SDF / ray-distance ratio.
fn shadow_softness(pos: vec3<f32>, light_dir: vec3<f32>, max_d: f32, k: f32) -> f32 {
    var t:   f32 = 0.01;   // start slightly off the surface to avoid self-shadow
    var res: f32 = 1.0;

    for (var i = 0u; i < 64u; i++) {
        if t >= max_d { break; }
        let d = scene_sdf(pos + light_dir * t);
        if d < SDF_EPS {
            return 0.0;   // hard hit — fully in shadow
        }
        res = min(res, k * d / t);
        t  += d;
    }

    return clamp(res, 0.0, 1.0);
}

// ── Ambient occlusion via SDF stepping ───────────────────────────────────────

// Estimate AO at `pos` along `normal` by comparing expected vs actual SDF
// values at `num_steps` evenly spaced positions (each `step` units apart).
//
// Returns a visibility scalar in [0, 1] (1 = fully unoccluded).
// Typical usage: step=0.1, num_steps=5.
fn ambient_occlusion(pos: vec3<f32>, normal: vec3<f32>, step: f32, num_steps: u32) -> f32 {
    var ao:  f32 = 0.0;
    var wt:  f32 = 1.0;   // sample weight (decays with distance)

    for (var i = 1u; i <= num_steps; i++) {
        let dist     = step * f32(i);
        let expected = dist;                          // ideal SDF if completely open
        let actual   = scene_sdf(pos + normal * dist);
        ao  += wt * (expected - actual);
        wt  *= 0.5;                                   // halve the weight each step
    }

    return clamp(1.0 - ao, 0.0, 1.0);
}

// ── Ray generation ────────────────────────────────────────────────────────────

// Compute the world-space ray direction for pixel `px` in an image of size
// `dim`, using the camera basis vectors and vertical FoV stored in rm_uniforms.
fn ray_direction(px: vec2<u32>, dim: vec2<u32>) -> vec3<f32> {
    // NDC in [-1, 1] with Y up (flip pixel Y axis).
    let uv = (vec2<f32>(px) + 0.5) / vec2<f32>(dim) * 2.0 - 1.0;
    let ndc = vec2<f32>(uv.x, -uv.y);

    let aspect   = f32(dim.x) / f32(dim.y);
    let tan_half = tan(rm_uniforms.fov_y * 0.5);

    let ray_cam = vec3<f32>(
        ndc.x * aspect * tan_half,
        ndc.y * tan_half,
        1.0,
    );

    return normalize(
        rm_uniforms.cam_right.xyz * ray_cam.x +
        rm_uniforms.cam_up.xyz    * ray_cam.y +
        rm_uniforms.cam_dir.xyz   * ray_cam.z
    );
}

// ── Compute entry point ───────────────────────────────────────────────────────

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) id: vec3<u32>) {
    let px  = id.xy;
    let dim = vec2<u32>(rm_uniforms.width, rm_uniforms.height);

    // Bounds guard — discard threads outside the output texture.
    if px.x >= dim.x || px.y >= dim.y { return; }

    let ipx = vec2<i32>(px);
    let ro   = rm_uniforms.cam_pos.xyz;
    let rd   = ray_direction(px, dim);

    // ── Sphere trace ──────────────────────────────────────────────────────────
    var t:    f32  = 0.0;
    var hit:  bool = false;

    for (var i = 0u; i < rm_uniforms.max_steps; i++) {
        let p = ro + rd * t;
        let d = scene_sdf(p);

        if d < rm_uniforms.hit_eps {
            hit = true;
            break;
        }

        t += d;

        if t > rm_uniforms.max_dist { break; }
    }

    // ── Write output textures ─────────────────────────────────────────────────
    if hit {
        let hit_p = ro + rd * t;
        let norm  = scene_normal(hit_p);

        // hit_pos_tex: world-space hit position (xyz) + march distance (w)
        textureStore(hit_pos_tex,    ipx, vec4<f32>(hit_p, t));
        // hit_normal_tex: world-space normal (xyz) + hit flag (w=1)
        textureStore(hit_normal_tex, ipx, vec4<f32>(norm, 1.0));
    } else {
        // Miss — write zeroed position and flag w=0 to signal no geometry.
        textureStore(hit_pos_tex,    ipx, vec4<f32>(0.0, 0.0, 0.0, rm_uniforms.max_dist));
        textureStore(hit_normal_tex, ipx, vec4<f32>(0.0, 0.0, 0.0, 0.0));
    }
}
