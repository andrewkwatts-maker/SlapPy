struct Params {
    center_x: f32,
    center_y: f32,
    strength: f32,
    radius:   f32,
    width:    u32,
    height:   u32,
    _pad0:    u32,
    _pad1:    u32,
}

@group(0) @binding(0) var<uniform> params     : Params;
@group(0) @binding(1) var          input_tex  : texture_2d<f32>;
@group(0) @binding(2) var          smp        : sampler;
@group(0) @binding(3) var          output_tex : texture_storage_2d<rgba8unorm, write>;

@compute @workgroup_size(8, 8, 1)
fn main(@builtin(global_invocation_id) gid: vec3u) {
    let x = gid.x;
    let y = gid.y;
    if x >= params.width || y >= params.height { return; }

    let w = f32(params.width);
    let h = f32(params.height);

    // UV with half-pixel offset so sample centres align to texel centres
    let uv = vec2f((f32(x) + 0.5) / w, (f32(y) + 0.5) / h);

    let center  = vec2f(params.center_x, params.center_y);
    let delta   = uv - center;
    let dist    = length(delta);

    let radius_sq   = max(params.radius * params.radius, 0.0001);
    let warp_factor = params.strength * exp(-(dist * dist) / radius_sq);

    var warped_uv: vec2f;
    if dist > 0.0001 {
        warped_uv = uv + normalize(delta) * warp_factor;
    } else {
        warped_uv = uv;
    }

    let color = textureSample(input_tex, smp, warped_uv);
    textureStore(output_tex, vec2i(i32(x), i32(y)), color);
}
