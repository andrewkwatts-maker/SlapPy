struct DecalParams {
    center_u:     f32,
    center_v:     f32,
    radius:       f32,
    blend_mode:   u32,
    width:        u32,
    height:       u32,
    decal_width:  u32,
    decal_height: u32,
    ch0_offset:   u32,
    ch0_delta:    f32,
    ch1_offset:   u32,
    ch1_delta:    f32,
    stride:       u32,
    _pad0:        u32,
    _pad1:        u32,
    _pad2:        u32,
}

@group(0) @binding(0) var<uniform>             params     : DecalParams;
@group(0) @binding(1) var                      decal_tex  : texture_2d<f32>;
@group(0) @binding(2) var                      smp        : sampler;
@group(0) @binding(3) var<storage, read_write> pixel_buf  : array<u32>;
@group(0) @binding(4) var                      visual_tex : texture_storage_2d<rgba8unorm, write>;

@compute @workgroup_size(8, 8, 1)
fn main(@builtin(global_invocation_id) gid: vec3u) {
    let x = gid.x;
    let y = gid.y;
    if x >= params.width || y >= params.height { return; }

    let pu = (f32(x) + 0.5) / f32(params.width);
    let pv = (f32(y) + 0.5) / f32(params.height);

    let du = pu - params.center_u;
    let dv = pv - params.center_v;
    if (du * du + dv * dv) >= (params.radius * params.radius) { return; }

    var decal_u = (du + params.radius) / (2.0 * params.radius);
    var decal_v = (dv + params.radius) / (2.0 * params.radius);
    decal_u = clamp(decal_u, 0.0, 1.0);
    decal_v = clamp(decal_v, 0.0, 1.0);

    let decal_color = textureSampleLevel(decal_tex, smp, vec2f(decal_u, decal_v), 0.0);
    if decal_color.a <= 0.01 { return; }

    let base = (y * params.width + x) * params.stride;

    let r0 = bitcast<f32>(pixel_buf[base + 0u]);
    let g0 = bitcast<f32>(pixel_buf[base + 1u]);
    let b0 = bitcast<f32>(pixel_buf[base + 2u]);
    let a0 = bitcast<f32>(pixel_buf[base + 3u]);
    let target = vec4f(r0, g0, b0, a0);

    var blended: vec4f;
    switch params.blend_mode {
        case 1u: {
            blended = target * decal_color;
        }
        case 2u: {
            blended = target + decal_color * decal_color.a;
        }
        default: {
            blended = mix(target, decal_color, decal_color.a);
        }
    }

    pixel_buf[base + 0u] = bitcast<u32>(blended.r);
    pixel_buf[base + 1u] = bitcast<u32>(blended.g);
    pixel_buf[base + 2u] = bitcast<u32>(blended.b);
    pixel_buf[base + 3u] = bitcast<u32>(blended.a);

    textureStore(visual_tex, vec2i(i32(x), i32(y)), blended);

    if params.ch0_offset != 0xFFFFFFFFu {
        let cur0 = bitcast<f32>(pixel_buf[base + params.ch0_offset]);
        pixel_buf[base + params.ch0_offset] = bitcast<u32>(cur0 + params.ch0_delta * decal_color.a);
    }
    if params.ch1_offset != 0xFFFFFFFFu {
        let cur1 = bitcast<f32>(pixel_buf[base + params.ch1_offset]);
        pixel_buf[base + params.ch1_offset] = bitcast<u32>(cur1 + params.ch1_delta * decal_color.a);
    }
}
