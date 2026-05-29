// vignette.wgsl — Vignette post-process pass
//
// Darkens pixels toward the screen edges; centre is unaffected.
//
// Round-4 lighting polish (May 2026): adds a smoothstep-based radial
// falloff with explicit inner_radius and feather controls.  The legacy
// `1 - pow(dist*strength, 2)` curve is preserved bit-for-bit when
// `feather <= 0.0` is passed (backward-compat flag).
//
// Smooth path:
//   factor = 1 - strength * smoothstep(inner_radius, inner_radius + feather, dist)
//
// `dist` is normalised so 0 = centre and 1 = nearest screen edge (i.e.
// half-width or half-height, whichever is smaller).  This keeps the
// vignette circular irrespective of aspect ratio, which matches what
// players expect from a photographic lens vignette.
//
// Legacy path (feather <= 0):
//   norm  = length(uv - 0.5) / length(vec2(0.5, 0.5))
//   factor = clamp(1 - pow(norm * strength, 2), 0, 1)
// — reproduces the original shader byte-for-byte so existing scenes are
// unaffected when no inner_radius/feather is supplied.

struct Params {
    strength:     f32,
    width:        u32,
    height:       u32,
    inner_radius: f32,
    feather:      f32,
    _pad0:        u32,
    _pad1:        u32,
    _pad2:        u32,
}

@group(0) @binding(0) var<storage, read>       in_buf : array<vec4<f32>>;
@group(0) @binding(1) var<storage, read_write> out_buf: array<vec4<f32>>;
@group(0) @binding(2) var<uniform>             params : Params;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3u) {
    let x = gid.x;
    let y = gid.y;
    if x >= params.width || y >= params.height { return; }

    let idx = y * params.width + x;
    var col = in_buf[idx];

    // UV in [0, 1] → centred offset in [-0.5, 0.5]
    let uv = vec2<f32>(f32(x) / f32(params.width), f32(y) / f32(params.height));
    let offset = uv - vec2<f32>(0.5, 0.5);

    var factor: f32;

    if params.feather <= 0.0 {
        // ── Legacy hard-quadratic path (backward-compat) ─────────────
        // dist = 0 at centre, ~1.0 at corner (length(0.5,0.5) ≈ 0.707).
        let dist_legacy = length(offset) / length(vec2<f32>(0.5, 0.5));
        factor = clamp(1.0 - pow(dist_legacy * params.strength, 2.0), 0.0, 1.0);
    } else {
        // ── Smooth radial falloff (round 4) ──────────────────────────
        // Normalise so dist = 1 at the nearest edge midpoint (i.e. the
        // half-axis), giving a circular vignette regardless of aspect.
        // Using length() on the centred offset and dividing by 0.5
        // yields dist = 1 at the screen-edge midpoint.
        let dist_smooth = length(offset) / 0.5;

        // smoothstep ramps from 0 (at inner_radius) to 1 (at
        // inner_radius + feather), giving a band-limited transition
        // that avoids the pow(...)**2 banding the legacy curve produces
        // in 8-bit storage targets.
        let ramp = smoothstep(
            params.inner_radius,
            params.inner_radius + params.feather,
            dist_smooth,
        );
        factor = clamp(1.0 - params.strength * ramp, 0.0, 1.0);
    }

    out_buf[idx] = vec4<f32>(col.rgb * factor, col.a);
}
