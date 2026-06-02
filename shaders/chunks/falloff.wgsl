// falloff.wgsl — smoothstep / falloff helpers used by deformation, lighting,
// and decal passes.  All inputs are assumed pre-normalized to [0, 1] unless
// noted otherwise.

// Classic Hermite smoothstep: 3t^2 - 2t^3.  Equivalent to the built-in
// smoothstep(0.0, 1.0, t) but spelled out so it can be inlined without the
// edge-comparison overhead.
fn smooth_falloff(t: f32) -> f32 {
    let x = clamp(t, 0.0, 1.0);
    return x * x * (3.0 - 2.0 * x);
}

// Radial smooth falloff: returns 1.0 at dist == 0, 0.0 at dist >= radius,
// smoothly easing in between.  Safe when radius <= 0 (returns 0).
fn radial_falloff(dist: f32, radius: f32) -> f32 {
    if (radius <= 0.0) { return 0.0; }
    let t = 1.0 - clamp(dist / radius, 0.0, 1.0);
    return t * t * (3.0 - 2.0 * t);
}

// Quintic smoothstep (Perlin's improved version): 6t^5 - 15t^4 + 10t^3.
// C2-continuous; preferred when the falloff feeds a derivative-sensitive pass.
fn smoother_falloff(t: f32) -> f32 {
    let x = clamp(t, 0.0, 1.0);
    return x * x * x * (x * (x * 6.0 - 15.0) + 10.0);
}
