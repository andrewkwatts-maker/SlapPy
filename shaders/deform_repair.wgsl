// deform_repair.wgsl — per-pixel radial repair pass
// Restores alpha toward original_alpha within a radius.
// One thread per pixel; each repair event is processed per-pixel.

struct RepairEvent {
    center_x:  f32,
    center_y:  f32,
    radius:    f32,
    rate:      f32,   // alpha units restored per dispatch (0..255)
    mode:      u32,   // 0 = radial (falloff), 1 = uniform fill, 2 = full pixel
    _pad0: u32,
    _pad1: u32,
    _pad2: u32,
};

struct Params {
    width:        u32,
    height:       u32,
    event_count:  u32,
    _pad: u32,
};

@group(0) @binding(0) var<storage, read>  events:       array<RepairEvent>;
@group(0) @binding(1) var<uniform>        params:       Params;
@group(0) @binding(2) var                 color_tex:    texture_storage_2d<rgba8unorm, read_write>;
@group(0) @binding(3) var                 original_tex: texture_storage_2d<rgba8unorm, read>;
// optional: material map for no-repair flag check
// @group(0) @binding(4) var              mat_tex:      texture_storage_2d<rgba32float, read>;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if gid.x >= params.width || gid.y >= params.height { return; }
    let coord = vec2<i32>(i32(gid.x), i32(gid.y));
    let px = f32(gid.x);
    let py = f32(gid.y);

    var pixel = textureLoad(color_tex, coord);
    let original = textureLoad(original_tex, coord);

    for (var i: u32 = 0u; i < params.event_count; i++) {
        let ev = events[i];
        let dx = px - ev.center_x;
        let dy = py - ev.center_y;
        let dist = sqrt(dx * dx + dy * dy);

        var weight: f32 = 0.0;
        if ev.mode == 2u {
            // Full pixel mode: repair entire layer regardless of position
            weight = 1.0;
        } else if dist < ev.radius {
            if ev.mode == 0u {
                // Radial falloff: smoothstep
                let t = 1.0 - dist / ev.radius;
                weight = t * t * (3.0 - 2.0 * t);
            } else {
                // Uniform fill within radius
                weight = 1.0;
            }
        }

        if weight <= 0.0 { continue; }

        // Restore alpha toward original, capped at original
        let repair_amount = ev.rate * weight;
        let target_alpha = min(original.a, pixel.a + repair_amount);
        pixel.a = target_alpha;
    }

    textureStore(color_tex, coord, pixel);
}
