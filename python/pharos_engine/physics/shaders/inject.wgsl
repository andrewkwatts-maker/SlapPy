// inject.wgsl
// Impact-velocity splatter kernel.  Writes velocity + pressure + heat into
// the contact zone using a smoothstep falloff.
//
// PixelState uses the canonical 16-float layout (three bond fields appended
// to the original 13-channel layout); see ``physics/cell.py`` for the
// authoritative channel order.

struct PixelState {
    u:              vec2<f32>,
    v:              vec2<f32>,
    perm_strain_xx: f32,
    perm_strain_yy: f32,
    perm_strain_xy: f32,
    pressure:       f32,
    damage:         f32,
    density:        f32,
    stretch:        f32,
    tear:           f32,
    heat:           f32,
    bond_n:         f32,
    bond_e:         f32,
    bond_s:         f32,
};
struct Params {
    width: u32, height: u32,
    cx: f32, cy: f32, vx: f32, vy: f32,
    radius: f32, magnitude: f32,
    friction_heat: f32, _p: f32,
};
@group(0) @binding(0) var<uniform>             params: Params;
@group(0) @binding(1) var<storage, read_write> state: array<PixelState>;
@group(0) @binding(2) var<storage, read>       mask:  array<u32>;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if gid.x >= params.width || gid.y >= params.height { return; }
    let m = f32(mask[gid.y * params.width + gid.x] & 0xFFu) / 255.0;
    if m < 0.05 { return; }
    let dx = f32(gid.x) - params.cx;
    let dy = f32(gid.y) - params.cy;
    let dist = sqrt(dx * dx + dy * dy);
    if dist >= params.radius { return; }
    let t = 1.0 - dist / params.radius;
    let falloff = t * t * (3.0 - 2.0 * t);
    let idx = gid.y * params.width + gid.x;
    var s = state[idx];
    s.v = s.v + vec2<f32>(params.vx, params.vy) * params.magnitude * falloff;
    s.pressure = s.pressure + params.magnitude * falloff * 0.3;
    // Impact heat (direct contact heat) + friction heat (sliding work).
    // Grazing impacts produce much more friction heat than head-on impacts;
    // hot spots concentrate where surfaces slide rather than bounce.
    s.heat = s.heat + (params.magnitude * 0.2 + params.friction_heat) * falloff;
    state[idx] = s;
}
