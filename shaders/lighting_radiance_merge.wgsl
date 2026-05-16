// Radiance Cascade: Pass 2 — Merge
// Interpolate coarser cascade level (2× spacing) into finer level.
// Fine probe reads from coarse probe and blends with factor 0.5.

@group(0) @binding(0) var fine_tex:   texture_storage_2d<rgba16float, read_write>;
@group(0) @binding(1) var coarse_tex: texture_2d<f32>;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let fine_dims = textureDimensions(fine_tex);
    if (gid.x >= fine_dims.x || gid.y >= fine_dims.y) { return; }
    let coord = vec2<i32>(gid.xy);

    // Sample coarse at half-resolution (bilinear via scaled UV)
    let coarse_dims = textureDimensions(coarse_tex);
    let uv = (vec2<f32>(gid.xy) + 0.5) / vec2<f32>(fine_dims);
    let coarse_coord = vec2<i32>(uv * vec2<f32>(coarse_dims));
    let clamped = clamp(coarse_coord, vec2<i32>(0), vec2<i32>(coarse_dims) - 1);
    let coarse_val = textureLoad(coarse_tex, clamped, 0);

    let fine_val = textureLoad(fine_tex, coord);

    // Merge: blend fine with coarse (coarse fills in "missed" rays)
    let merged = mix(fine_val, coarse_val, 0.3);
    textureStore(fine_tex, coord, merged);
}
