// auto_exposure.wgsl — Automatic exposure (auto-EV) pre-pass
//
// Lottes 2017 / Karis 2013 style auto-exposure:
//   1. For every pixel, compute BT.709 luminance L = dot(rgb, (0.2126, 0.7152, 0.0722))
//   2. Accumulate log(max(L, eps)) into a shared workgroup reduction
//   3. After all workgroups finish, the host divides the sum by the pixel count
//      to obtain the geometric-mean log-luminance ("log-average luminance").
//   4. Derived EV = log2(target_grey / exp(log_avg)) clamped to [min_ev, max_ev].
//   5. Smooth across frames: ev = ev * (1 - smoothing) + derived * smoothing.
//
// This shader is the *reduction kernel* only. The smoothing / clamp / final
// EV derivation runs on the CPU and is uploaded into the tonemap params on the
// next frame. The CPU reference path in `auto_exposure.py` performs the same
// math without touching the GPU.
//
// Binding convention:
//   binding 0 = input_tex     (texture_2d<f32>, scene-linear HDR)
//   binding 1 = output_tex    (storage texture, write — unused, kept for pass
//                              compatibility with the post-process executor)
//   binding 2 = params uniform (Params struct, 16 bytes)
//   binding 3 = accumulator    (atomic<u32> array of length 2; [sum_fixed, count])
//
// The fixed-point sum stores (log_lum + LOG_BIAS) * LOG_SCALE so the host can
// recover the floating-point sum as: float_sum = (atomic_sum / LOG_SCALE) - count * LOG_BIAS.
// LOG_BIAS = 16.0 (covers log of 1e-7 .. 1e7), LOG_SCALE = 1024.

struct Params {
    width      : u32,
    height     : u32,
    log_bias   : f32,
    log_scale  : f32,
}

@group(0) @binding(0) var input_tex  : texture_2d<f32>;
@group(0) @binding(1) var output_tex : texture_storage_2d<rgba8unorm, write>;
@group(0) @binding(2) var<uniform> params : Params;
@group(0) @binding(3) var<storage, read_write> accumulator : array<atomic<u32>, 2>;

// BT.709 luminance.
fn luminance(c: vec3f) -> f32 {
    return dot(c, vec3f(0.2126, 0.7152, 0.0722));
}

@compute @workgroup_size(8, 8)
fn auto_exposure_main(@builtin(global_invocation_id) gid: vec3u) {
    let x = gid.x;
    let y = gid.y;
    if x >= params.width || y >= params.height { return; }

    let src = textureLoad(input_tex, vec2i(i32(x), i32(y)), 0);
    let lum = max(luminance(src.rgb), 1e-7);
    let log_lum = log(lum);

    // Map (log_lum + log_bias) * log_scale into u32 atomic accumulator.
    let biased = (log_lum + params.log_bias) * params.log_scale;
    let fixed  = u32(max(biased, 0.0));
    atomicAdd(&accumulator[0], fixed);
    atomicAdd(&accumulator[1], 1u);

    // Pass-through write so downstream passes can chain off the same texture.
    textureStore(output_tex, vec2i(i32(x), i32(y)), src);
}
