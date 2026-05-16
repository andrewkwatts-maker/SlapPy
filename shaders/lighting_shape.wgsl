// Shape light — uses a mask texture; white pixels emit, black don't
// Useful for neon signs, glowing windows, area lights

struct ShapeLightData {
    pos: vec2<f32>,          // center of the mask in screen space
    color: vec3<f32>,
    intensity: f32,
    size: vec2<f32>,         // mask dimensions (width, height)
    falloff: f32,            // attenuation beyond mask edge
    _pad: f32,
}

@group(0) @binding(0) var<storage, read> lights: array<ShapeLightData>;
@group(0) @binding(1) var<uniform> num_lights: u32;
@group(0) @binding(2) var mask_tex: texture_2d<f32>;     // shape mask (white=emit)
@group(0) @binding(3) var samp: sampler;
@group(0) @binding(4) var accum_tex: texture_storage_2d<rgba16float, read_write>;

@compute @workgroup_size(8, 8, 1)
fn shape_light_main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let px = vec2<i32>(gid.xy);
    let screen_size = vec2<i32>(textureDimensions(accum_tex));
    if px.x >= screen_size.x || px.y >= screen_size.y { return; }

    var total = vec3<f32>(0.0);
    let p = vec2<f32>(px) + 0.5;

    for (var i = 0u; i < num_lights; i++) {
        let light = lights[i];
        let rel = p - light.pos;
        let uv = rel / light.size + 0.5;

        // Only sample if within mask bounds
        if all(uv >= vec2<f32>(0.0)) && all(uv <= vec2<f32>(1.0)) {
            let mask_val = textureSampleLevel(mask_tex, samp, uv, 0.0).r;
            let dist = length(rel);
            let atten = max(0.0, 1.0 - dist / (length(light.size) * 0.5 + light.falloff));
            total += light.color * light.intensity * mask_val * atten;
        }
    }

    let prev = textureLoad(accum_tex, px);
    textureStore(accum_tex, px, vec4<f32>(prev.rgb + total, prev.a));
}
