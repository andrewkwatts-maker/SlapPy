// pharos_render :: VCR Stage 2 — Raster + accumulate.
//
// Extended-frustum raster pass. Standard vertex path emits
// world-space triangle fragments; the fragment shader consults the
// reservoir to test whether a virtual sub-camera ray of this pixel
// hits *this* triangle. If yes, add colour + throughput.
//
// Nova3D §5 Stage 2. Implementation notes:
// - "hits" is a cone/plane intersection test — cheap and conservative.
// - Contributions below VCR_ALPHA_DROP_THRESHOLD are discarded
//   immediately (never touch the reservoir).
// - The fragment writes-and-then-reads the same reservoir slot, so
//   the pipeline binds it with rgba32float atomic-write access
//   through a storage image.

struct FrameUniforms {
    view: mat4x4<f32>,
    proj: mat4x4<f32>,
    view_proj: mat4x4<f32>,
    camera_position: vec4<f32>,
};

@group(0) @binding(0) var<uniform> frame: FrameUniforms;
@group(1) @binding(0) var reservoir: texture_storage_3d<rgba32float, read_write>;

struct VertexIn {
    @location(0) position: vec3<f32>,
    @location(1) normal:   vec3<f32>,
    @location(2) uv:       vec2<f32>,
    @location(3) tangent:  vec4<f32>,
};

struct VertexOut {
    @builtin(position) clip: vec4<f32>,
    @location(0) world_pos: vec3<f32>,
    @location(1) world_normal: vec3<f32>,
    @location(2) base_colour: vec3<f32>,
};

@vertex
fn vs_main(v: VertexIn) -> VertexOut {
    var out: VertexOut;
    out.clip = frame.view_proj * vec4<f32>(v.position, 1.0);
    out.world_pos = v.position;
    out.world_normal = normalize(v.normal);
    // Sprint 6 keeps material lookup shallow; Sprint 8 wires the
    // full material graph.
    out.base_colour = vec3<f32>(0.7, 0.72, 0.75);
    return out;
}

@fragment
fn fs_main(in: VertexOut) -> @location(0) vec4<f32> {
    // For each pixel in the extended frustum, consult its reservoir
    // and add throughput for any slot whose cone contains this fragment.
    let uv = vec2<i32>(i32(in.clip.x), i32(in.clip.y));
    let dims = textureDimensions(reservoir);
    if (uv.x < 0 || uv.y < 0 || uv.x >= i32(dims.x) || uv.y >= i32(dims.y)) {
        return vec4<f32>(0.0);
    }
    var accum: vec3<f32> = vec3<f32>(0.0);
    for (var k: u32 = 0u; k < VCR_K_SLOTS; k = k + 1u) {
        let lo = textureLoad(reservoir, vec3<i32>(uv, i32(k * 2u)));
        let hi = textureLoad(reservoir, vec3<i32>(uv, i32(k * 2u + 1u)));
        let slot_pos = lo.xyz;
        let slot_dir = hi.xyz;
        let slot_cone = hi.w;
        let to_frag = normalize(in.world_pos - slot_pos);
        let cos_cone = cos(slot_cone);
        if (dot(slot_dir, to_frag) > cos_cone) {
            // Distance falloff (inverse-square, clamped).
            let d = distance(in.world_pos, slot_pos);
            let atten = 1.0 / max(d * d, 0.01);
            let contribution = in.base_colour * atten;
            if (max(contribution.x, max(contribution.y, contribution.z)) > VCR_ALPHA_DROP_THRESHOLD) {
                accum = accum + contribution;
            }
        }
    }
    return vec4<f32>(accum, 1.0);
}
