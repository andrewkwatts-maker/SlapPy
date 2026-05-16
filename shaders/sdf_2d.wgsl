// 2D SDF primitives — smooth shapes, glow, drop-shadow for 2D layers
// Used to draw vector-quality shapes into pixel layer textures.
//
// Binding layout (group 0):
//   binding 0: SdfUniforms  (uniform)
//   binding 1: array<SdfShape>  (storage, read)
//   binding 2: layer_tex  (texture_storage_2d<rgba8unorm, read_write>)
//
// Dispatch: ceil(width/8) × ceil(height/8) × 1 workgroups.

// ── SDF primitive functions ───────────────────────────────────────────────────

// Signed distance to a circle (negative inside).
fn sdf_circle(p: vec2<f32>, center: vec2<f32>, radius: f32) -> f32 {
    return length(p - center) - radius;
}

// Signed distance to a rounded rectangle.
// half_size: (half_width, half_height); corner_r: corner radius (0 = sharp).
fn sdf_box(p: vec2<f32>, center: vec2<f32>, half_size: vec2<f32>, corner_r: f32) -> f32 {
    let q = abs(p - center) - half_size + corner_r;
    return length(max(q, vec2<f32>(0.0))) + min(max(q.x, q.y), 0.0) - corner_r;
}

// Signed distance to a line segment with half-thickness.
// a, b: endpoints; thickness: half-width of the stroke.
fn sdf_segment(p: vec2<f32>, a: vec2<f32>, b: vec2<f32>, thickness: f32) -> f32 {
    let pa = p - a;
    let ba = b - a;
    let h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h) - thickness;
}

// Signed distance to an annular ring (hollow circle).
// radius: centre-line radius; thickness: half-width of the ring band.
fn sdf_ring(p: vec2<f32>, center: vec2<f32>, radius: f32, thickness: f32) -> f32 {
    return abs(length(p - center) - radius) - thickness;
}

// ── Rendering helpers ─────────────────────────────────────────────────────────

// Smooth anti-aliased fill from an SDF value.
// Returns 1.0 fully inside, 0.0 fully outside, with a smooth aa_width-wide
// transition at the boundary.
fn sdf_fill(d: f32, aa_width: f32) -> f32 {
    return 1.0 - smoothstep(-aa_width, aa_width, d);
}

// Glow / halo effect — exponential falloff outside the shape edge.
// radius controls the halo spread; intensity is a multiplier.
fn sdf_glow(d: f32, radius: f32, intensity: f32) -> f32 {
    return intensity * exp(-max(d, 0.0) / radius);
}

// Blurred drop-shadow for a circle-shaped shadow.
// shadow_offset: (dx, dy) pixels the shadow is displaced from the shape.
// blur: softness radius in pixels.
fn sdf_shadow(p: vec2<f32>, center: vec2<f32>, shape_r: f32,
              shadow_offset: vec2<f32>, blur: f32) -> f32 {
    let shadow_d = length(p - center - shadow_offset) - shape_r;
    return 0.5 * (1.0 - smoothstep(-blur, blur, shadow_d));
}

// ── GPU data structures ───────────────────────────────────────────────────────

struct SdfShape {
    // Shape selector: 0=circle, 1=box, 2=segment, 3=ring
    kind:          u32,
    // Centre point. For segment (kind=2) this encodes the stroke half-thickness
    // in center.x — the actual endpoints are in param_a / param_b.
    center:        vec2<f32>,
    // kind 0 (circle):  (radius, unused)
    // kind 1 (box):     (half_width, half_height)
    // kind 2 (segment): endpoint A (ax, ay)
    // kind 3 (ring):    (radius, unused)
    param_a:       vec2<f32>,
    // kind 0 (circle):  unused
    // kind 1 (box):     (corner_radius, unused)
    // kind 2 (segment): endpoint B (bx, by)
    // kind 3 (ring):    (thickness, unused)
    param_b:       vec2<f32>,
    fill_color:    vec4<f32>,
    glow_color:    vec4<f32>,
    glow_radius:   f32,
    shadow_alpha:  f32,
    shadow_offset: vec2<f32>,
    aa_width:      f32,
    _pad:          vec3<f32>,
}

struct SdfUniforms {
    num_shapes: u32,
    _pad:       vec3<u32>,
}

@group(0) @binding(0) var<uniform>          uniforms  : SdfUniforms;
@group(0) @binding(1) var<storage, read>    shapes    : array<SdfShape>;
@group(0) @binding(2) var                   layer_tex : texture_storage_2d<rgba8unorm, read_write>;

// ── Compute entry point ───────────────────────────────────────────────────────

@compute @workgroup_size(8, 8, 1)
fn sdf_draw(@builtin(global_invocation_id) gid: vec3<u32>) {
    let px   = vec2<i32>(gid.xy);
    let size = vec2<i32>(textureDimensions(layer_tex));
    if px.x >= size.x || px.y >= size.y { return; }

    let p = vec2<f32>(px) + 0.5;           // pixel centre in texel space
    var out_color = textureLoad(layer_tex, px);

    for (var i = 0u; i < uniforms.num_shapes; i++) {
        let s = shapes[i];
        var d: f32;

        // Evaluate the appropriate SDF primitive.
        switch s.kind {
            case 0u: {
                // Circle: param_a.x = radius
                d = sdf_circle(p, s.center, s.param_a.x);
            }
            case 1u: {
                // Rounded box: param_a = half-extents, param_b.x = corner radius
                d = sdf_box(p, s.center, s.param_a, s.param_b.x);
            }
            case 2u: {
                // Segment: param_a = endpoint A, param_b = endpoint B,
                //          center.x = stroke half-thickness
                d = sdf_segment(p, s.param_a, s.param_b, s.center.x);
            }
            case 3u: {
                // Ring: param_a.x = outer radius, param_b.x = ring half-thickness
                d = sdf_ring(p, s.center, s.param_a.x, s.param_b.x);
            }
            default: {
                d = 9999.0;
            }
        }

        // 1. Drop shadow (rendered first, underneath fill and glow)
        if s.shadow_alpha > 0.0 {
            // Use the same primitive radius / half-extent as the fill shape but
            // evaluate the circle approximation of its shadow at the offset position.
            let shadow_d = sdf_circle(p, s.center + s.shadow_offset, s.param_a.x);
            let shadow   = s.shadow_alpha * sdf_fill(shadow_d + 4.0, 6.0);
            out_color = vec4<f32>(
                mix(out_color.rgb, vec3<f32>(0.0), shadow),
                out_color.a
            );
        }

        // 2. Glow halo (additive, sits behind the opaque fill)
        if s.glow_radius > 0.0 {
            let glow = sdf_glow(d, s.glow_radius, 1.0);
            out_color = vec4<f32>(
                out_color.rgb + s.glow_color.rgb * glow * s.glow_color.a,
                out_color.a
            );
        }

        // 3. Filled shape (alpha-blended over existing colour)
        let fill  = sdf_fill(d, s.aa_width);
        let alpha = fill * s.fill_color.a;
        out_color = vec4<f32>(
            mix(out_color.rgb, s.fill_color.rgb, alpha),
            out_color.a
        );
    }

    textureStore(layer_tex, px, out_color);
}
