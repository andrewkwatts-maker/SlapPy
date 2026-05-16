// Fullscreen blit — sample a texture and output it to the current render attachment.
// Generates a fullscreen triangle from vertex_index without a vertex buffer.
@group(0) @binding(0) var t : texture_2d<f32>;
@group(0) @binding(1) var s : sampler;

struct VertexOut {
    @builtin(position) pos : vec4<f32>,
    @location(0)       uv  : vec2<f32>,
};

@vertex
fn vs_main(@builtin(vertex_index) vi: u32) -> VertexOut {
    // Generate a fullscreen triangle: covers [-1,1] in NDC
    let x  = f32((vi & 1u) << 1u) - 1.0;  // -1, 3, -1
    let y  = 1.0 - f32((vi >> 1u) << 1u); // 1, 1, -3  ... simplified below
    let xs = array<f32, 3>(-1.0,  3.0, -1.0);
    let ys = array<f32, 3>( 1.0,  1.0, -3.0);
    var out : VertexOut;
    out.pos = vec4<f32>(xs[vi], ys[vi], 0.0, 1.0);
    out.uv  = vec2<f32>((xs[vi] + 1.0) * 0.5, (1.0 - ys[vi]) * 0.5);
    return out;
}

@fragment
fn fs_main(in: VertexOut) -> @location(0) vec4<f32> {
    return textureSample(t, s, in.uv);
}
