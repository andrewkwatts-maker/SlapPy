// hull_transform.wgsl
// Rigid-transform integration for every hull in the scene.  Runs every frame
// at all tiers (T0/T1/T2); one thread per hull; cheap.

struct Params {
    dt:      f32,
    n_hulls: u32,
    _pad0:   u32,
    _pad1:   u32,
};

struct HullTransform {
    position: vec2<f32>,
    angle:    f32,
    _pad0:    f32,
    velocity: vec2<f32>,
    omega:    f32,
    fixed:    u32,
};

@group(0) @binding(0) var<uniform>             params: Params;
@group(0) @binding(1) var<storage, read_write> hulls:  array<HullTransform>;

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = gid.x;
    if i >= params.n_hulls { return; }
    var h = hulls[i];
    if h.fixed != 0u { return; }       // grounds don't integrate
    h.position = h.position + h.velocity * params.dt;
    h.angle    = h.angle    + h.omega    * params.dt;
    hulls[i] = h;
}
