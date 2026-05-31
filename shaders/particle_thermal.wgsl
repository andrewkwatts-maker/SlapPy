// particle_thermal.wgsl
// ---------------------------------------------------------------
// GPU port of ParticleField._thermal_step (see particle_field.py
// and physics/thermal.py).
//
// Per particle, this kernel does what step_temperatures +
// detect_phase_changes do on the CPU:
//
//   1. Relax temperature toward the material's ambient:
//        T += (ambient - T) * decay_per_sec * dt
//   2. Phase changes — if T >= melt_at and melt_to_id != -1, swap
//      material_id to melt_to_id; else if T <= freeze_at and
//      freeze_to_id != -1, swap to freeze_to_id.
//   3. When the material id changes, the particle's packed RGBA8
//      colour is overwritten with the new material's colour (the
//      CPU path mirrors this).
//
// The "melt_to_id == -1 → no transition" sentinel matches the
// CPU code's "profile.melt_to_material is None" branch. The
// Python builder turns those into -1 before upload so this
// shader can stay branch-free except for the sentinel check.
//
// Layout
// ------
//   group(0) binding(0)  storage read_write   temperature  : array<f32>
//   group(0) binding(1)  storage read_write   material_id  : array<i32>
//   group(0) binding(2)  storage read_write   color        : array<u32>
//                                                            // packed rgba8 (r in low byte)
//   group(0) binding(3)  storage read         thermal_props: array<ThermalProps>
//   group(0) binding(4)  uniform              params       : Params
//
// Workgroup size: 64. Matches the other particle kernels
// (integrate / health_sum / stats_reduction) — multiple of the
// SIMD width on every backend and keeps occupancy high for the
// expected particle counts.
// ---------------------------------------------------------------

struct ThermalProps {
    // .x = ambient_temperature
    // .y = decay_per_sec
    // .z = melt_at
    // .w = freeze_at
    scalars      : vec4<f32>,
    // .x = melt_to_id (-1 = no melt transition)
    // .y = freeze_to_id (-1 = no freeze transition)
    // .z = packed rgba8 colour (low byte = r)
    // .w = pad
    ints         : vec4<i32>,
    // Sentinel flags (1 = enabled, 0 = disabled). The CPU treats
    // ``melt_at is None`` as "never melt" and ``freeze_at is None``
    // as "never freeze"; we forward that with a flag so the shader
    // doesn't have to invent a magic threshold value.
    has_melt     : u32,
    has_freeze   : u32,
    _pad0        : u32,
    _pad1        : u32,
};

struct Params {
    dt          : f32,
    n_particles : u32,
    _pad0       : u32,
    _pad1       : u32,
};

@group(0) @binding(0) var<storage, read_write> temperature   : array<f32>;
@group(0) @binding(1) var<storage, read_write> material_id   : array<i32>;
@group(0) @binding(2) var<storage, read_write> color         : array<u32>;
@group(0) @binding(3) var<storage, read>       thermal_props : array<ThermalProps>;
@group(0) @binding(4) var<uniform>             params        : Params;

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = gid.x;
    if (i >= params.n_particles) {
        return;
    }

    let mid = material_id[i];
    // Defensive bound — the CPU clips out-of-range ids to 0.
    let n_props = i32(arrayLength(&thermal_props));
    var safe_mid = mid;
    if (safe_mid < 0) {
        safe_mid = 0;
    }
    if (safe_mid >= n_props) {
        safe_mid = n_props - 1;
    }
    let props = thermal_props[safe_mid];

    let ambient = props.scalars.x;
    let decay   = props.scalars.y;
    let melt_at = props.scalars.z;
    let freeze_at = props.scalars.w;

    var T = temperature[i];
    T = T + (ambient - T) * decay * params.dt;
    temperature[i] = T;

    // Phase change — melt has priority over freeze (matches CPU
    // order in detect_phase_changes).
    var new_mid = mid;
    if (props.has_melt == 1u && props.ints.x != -1 && T >= melt_at) {
        new_mid = props.ints.x;
    } else if (props.has_freeze == 1u && props.ints.y != -1 && T <= freeze_at) {
        new_mid = props.ints.y;
    }

    if (new_mid != mid) {
        material_id[i] = new_mid;
        // Look up the new material's packed colour and overwrite
        // this particle's colour. Same defensive bound check.
        var nm = new_mid;
        if (nm < 0) {
            nm = 0;
        }
        if (nm >= n_props) {
            nm = n_props - 1;
        }
        let new_props = thermal_props[nm];
        color[i] = u32(new_props.ints.z);
    }
}
