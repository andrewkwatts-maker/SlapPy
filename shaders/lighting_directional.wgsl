// Directional light — additive contribution to light accumulation buffer.
// Computes Z-height shadow offset then adds (color * intensity * shadow_factor) to accum.
//
// Binding 3: fluid density texture (rgba8unorm, R=density).  When a fluid
// simulation is active, this contains the current density field.  We march a
// short ray in the light direction and accumulate density to compute
// Beer-Lambert transmittance, which both attenuates occluded areas and creates
// the brightened halo (god ray) effect around the light direction.
// When no fluid is active a 1×1 zero-density dummy is bound — transmittance = 1.
struct DirectionalLight {
    dir_x: f32, dir_y: f32,
    elevation: f32, intensity: f32,
    color_r: f32, color_g: f32, color_b: f32,
    cast_shadows: u32,
};
struct Params {
    light: DirectionalLight,
    shadow_scale: f32,
    width: u32, height: u32,
    _pad: u32,
};
@group(0) @binding(0) var<uniform>            params      : Params;
@group(0) @binding(1) var                     z_tex       : texture_2d<f32>;
@group(0) @binding(2) var<storage,read_write> accum       : array<vec4<f32>>;
@group(0) @binding(3) var                     density_tex : texture_2d<f32>;

// God-ray ray march constants
const FLUID_SCATTER_COEFF : f32 = 1.2;   // how strongly density scatters/absorbs light
const GODRAY_STEPS        : i32 = 8;     // march steps along shadow ray
const GODRAY_STEP_PX      : f32 = 4.0;  // pixels per step

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= params.width || gid.y >= params.height) { return; }

    let z = textureLoad(z_tex, vec2<i32>(gid.xy), 0).r;

    var shadow_factor = 1.0;
    if (params.light.cast_shadows != 0u && z > 0.0) {
        let tan_elev  = tan(params.light.elevation);
        let shadow_len = z / max(tan_elev, 0.01) * params.shadow_scale;
        let sx = i32(gid.x) + i32(params.light.dir_x * shadow_len);
        let sy = i32(gid.y) + i32(params.light.dir_y * shadow_len);
        if (sx >= 0 && sy >= 0 && u32(sx) < params.width && u32(sy) < params.height) {
            let sz = textureLoad(z_tex, vec2<i32>(sx, sy), 0).r;
            if (sz > z) { shadow_factor = 0.3; }
        }
    }

    // ── God-ray fluid attenuation ─────────────────────────────────────────────
    // March GODRAY_STEPS steps along the light direction, sampling the fluid
    // density texture.  Accumulate Beer-Lambert transmittance.
    // If density_tex is the 1×1 dummy, textureLoad clamps to (0,0) → density=0
    // → transmittance stays 1.0 (no effect).
    var transmittance = 1.0;
    let density_dims = textureDimensions(density_tex, 0);
    if (density_dims.x > 1u) {
        // A real density field is bound.
        let step_x = params.light.dir_x * GODRAY_STEP_PX;
        let step_y = params.light.dir_y * GODRAY_STEP_PX;
        var px = f32(gid.x);
        var py = f32(gid.y);
        for (var s = 0; s < GODRAY_STEPS; s++) {
            px -= step_x;   // march backwards toward light source
            py -= step_y;
            let ix = clamp(i32(px), 0, i32(density_dims.x) - 1);
            let iy = clamp(i32(py), 0, i32(density_dims.y) - 1);
            let density = textureLoad(density_tex, vec2<i32>(ix, iy), 0).r;
            transmittance *= exp(-density * FLUID_SCATTER_COEFF * GODRAY_STEP_PX);
        }
    }

    let col = vec3<f32>(params.light.color_r, params.light.color_g, params.light.color_b);
    let contrib = vec4<f32>(col * params.light.intensity * shadow_factor * transmittance, 0.0);
    let idx = gid.y * params.width + gid.x;
    accum[idx] = accum[idx] + contrib;
}
