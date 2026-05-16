struct Camera {
    view_proj: mat4x4<f32>,
}

struct VertexInput {
    @location(0) pos:   vec2<f32>,
    @location(1) uv:    vec2<f32>,
}

struct InstanceInput {
    @location(2) world_pos:      vec2<f32>,
    @location(3) world_size:     vec2<f32>,
    @location(4) opacity:        f32,
    @location(5) frame:          f32,
    @location(6) rotation_rad:   f32,
    @location(7) scale:          f32,
}

struct VertexOutput {
    @builtin(position) clip_pos: vec4<f32>,
    @location(0)       uv:       vec2<f32>,
    @location(1)       opacity:  f32,
}

@group(0) @binding(0) var<uniform> camera: Camera;

@vertex
fn vs_main(vert: VertexInput, inst: InstanceInput) -> VertexOutput {
    // Scale the local quad offset, then rotate it around the entity centre.
    let local = vert.pos * inst.world_size * inst.scale;
    let cos_a = cos(inst.rotation_rad);
    let sin_a = sin(inst.rotation_rad);
    let rotated = vec2<f32>(
        local.x * cos_a - local.y * sin_a,
        local.x * sin_a + local.y * cos_a,
    );
    let world_pos = inst.world_pos + rotated;
    var out: VertexOutput;
    out.clip_pos = camera.view_proj * vec4<f32>(world_pos, 0.0, 1.0);
    out.uv       = vert.uv;
    out.opacity  = inst.opacity;
    return out;
}
