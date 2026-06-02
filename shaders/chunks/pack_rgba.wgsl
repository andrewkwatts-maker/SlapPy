// pack_rgba.wgsl — RGBA <-> u32 conversion helpers.
//
// Layout: little-endian per-byte packing where byte 0 = R, 1 = G, 2 = B, 3 = A.
// Mirrors WGSL's built-in unpack4x8unorm/pack4x8unorm but kept here so shaders
// can include this chunk without depending on the built-ins (handy when the
// surrounding pass already works on raw u32 storage buffers).

fn unpack_rgba(packed: u32) -> vec4<f32> {
    let r = f32( packed         & 0xFFu) / 255.0;
    let g = f32((packed >>  8u) & 0xFFu) / 255.0;
    let b = f32((packed >> 16u) & 0xFFu) / 255.0;
    let a = f32((packed >> 24u) & 0xFFu) / 255.0;
    return vec4<f32>(r, g, b, a);
}

fn pack_rgba(color: vec4<f32>) -> u32 {
    let c = clamp(color, vec4<f32>(0.0), vec4<f32>(1.0)) * 255.0 + vec4<f32>(0.5);
    let r = u32(c.r);
    let g = u32(c.g);
    let b = u32(c.b);
    let a = u32(c.a);
    return r | (g << 8u) | (b << 16u) | (a << 24u);
}
