<!-- handauthored: do not regenerate -->
# slappyengine.gi — API Reference

> Hand-written reference for the GI (Global Illumination) subpackage.
> Covers radiance cascades, ReSTIR reservoir reuse, and the SVGF denoiser
> (GPU + CPU paths). For numerical primitives see
> [`numerics.md`](numerics.md); for the post-process side of the lighting
> pipeline see [`post_process.md`](post_process.md).


## Overview

GI primitives layered on top of the Nova3D WGSL compute kernels. Each
system holds GPU resources but degrades gracefully when no `wgpu`
adapter is available (`init_gpu` swallows the import failure and the
runtime path becomes a no-op), so they can be constructed and unit-
tested on headless CI.

## Classes

### `RadianceCascadeSystem`

_class — defined in `slappyengine.gi.cascade`_

Manages a 4-pass radiance cascade GI dispatch (probe-based diffuse
indirect). The cascade hierarchy stores SH L1 coefficients per probe
and interpolates trilinearly across levels for screen-space apply.

#### Constructor signature

```python
RadianceCascadeSystem(
    width: int,
    height: int,
    num_cascades: int = 4,
    base_probe_spacing: int = 8,
    rays_per_probe_l0: int = 512,
    temporal_blend: float = 0.05,
) -> None
```

#### Passes

1. **Inject** (`lighting_radiance_inject.wgsl`) — shoot
   `rays_per_probe_l0 / 4^level` rays from each probe in cascade `level`
   and accumulate scene radiance into the SH L1 basis. Probe spacing
   doubles each level (`base_probe_spacing * 2^level`).
2. **Merge** (`lighting_radiance_merge.wgsl`) — walk from coarsest to
   finest cascade and trilinearly blend the coarser SH coefficients
   into the finer texture. Fills in the long-range bounce that
   per-probe ray budgets cannot reach directly.
3. **Temporal** — EMA blend the current cascade against history with
   `persistence = 1 − temporal_blend` (0.95 by default). Currently a
   CPU-side stub; the GPU path is reserved for a follow-up sprint.
4. **Apply** (`lighting_radiance_apply.wgsl`) — per-pixel trilinear
   probe sample, added to the lighting accumulator.

#### Methods

- `init_gpu(self, gpu) -> None` — allocate the per-level cascade and
  history textures (`rgba16float`, probe grid flattened with 4 SH
  coefficients side-by-side). Swallows `wgpu` import failures so a
  headless engine still constructs successfully.
- `dispatch(self, encoder, scene_texture, lighting_accumulator) -> None`
  — run all four passes against the supplied command encoder.

#### References

- Sannikov, A. *Radiance Cascades — A Novel Approach to Calculating
  Global Illumination*. (2023). The "cascade of probes at exponentially
  doubling spacing" idea this implementation tracks.
- Ramamoorthi, R. & Hanrahan, P. *An Efficient Representation for
  Irradiance Environment Maps*. SIGGRAPH 2001. SH L1 basis.

### `ReSTIRSystem`

_class — defined in `slappyengine.gi.restir`_

Reservoir-based importance sampling for ~1000-SPP-quality indirect
illumination from a small per-pixel ray budget. Four GPU passes
exchange 32-byte reservoirs (8 × f32: `light_index`, `weight_sum`,
`W`, `M`, `sample_pos.xy`, `sample_n.xy`) through ping-pong storage
buffers.

#### Constructor signature

```python
ReSTIRSystem(
    width: int = 0,
    height: int = 0,
    max_candidates: int = 32,
) -> None
```

#### Passes

1. **Initial RIS** (`restir_initial.wgsl`) — generate up to
   `max_candidates` light samples per pixel and stream them through a
   weighted-reservoir update against the unshadowed contribution.
2. **Temporal reuse** (`restir_temporal.wgsl`) — merge the previous
   frame's reservoir at the reprojected position, bounded by an `M`
   cap to limit history bias.
3. **Spatial reuse** (`restir_spatial.wgsl`) — combine neighbouring
   reservoirs that pass a position + normal similarity gate, again
   capped to prevent runaway variance reduction.
4. **Final shade** (`restir_final.wgsl`) — read the final reservoir,
   evaluate the BRDF, and write the shaded output.

#### Methods

- `init_gpu(self, gpu, width: int, height: int) -> None` — allocate
  the two ping-pong reservoir storage buffers
  (`width * height * 32` bytes each).
- `dispatch(self, encoder, gbuffer_pos, gbuffer_normal, gbuffer_albedo,
  light_buf, output_tex, frame_count: int = 0) -> None` — runs the
  4-pass pipeline; even/odd `frame_count` toggles which reservoir
  buffer is current vs history.

#### References

- Bitterli et al. *Spatiotemporal reservoir resampling for real-time
  ray tracing with dynamic direct lighting*. SIGGRAPH 2020.
- Ouyang et al. *ReSTIR GI: Path Resampling for Real-Time Path Tracing*.
  HPG 2021. The indirect-illumination extension this system implements.

### `SVGFDenoiser`

_class — defined in `slappyengine.gi.svgf`_

Spatiotemporal variance-guided filtering for noisy GI buffers. Five
GPU passes (temporal → variance → 5× wavelet → modulate) with a
faithful NumPy mirror of the temporal + variance + à-trous stages for
CI and headless examples.

#### Constructor signature

```python
SVGFDenoiser(width: int = 0, height: int = 0) -> None
```

#### Module constants (defaults match the Nova3D WGSL kernels)

- `PHI_COLOR = 10.0` — luminance edge-stop weight.
- `PHI_NORMAL = 128.0` — exponent on `clamp(dot(n, n'), 0, 1)`.
- `PHI_DEPTH = 1.0` — depth edge-stop weight.
- `SIGMA_LUM = 4.0` — variance scale inside the wavelet edge-stop.
- `TEMPORAL_ALPHA = 0.1` — EMA blend weight for new frames (history
  weight is `1 - alpha`).
- `MAX_HISTORY = 32` — history-length cap used by the temporal pass.

#### Methods

- `reset_history(self) -> None` — clears the CPU temporal-accumulation
  history so the next `denoise_numpy` call treats its input as the
  first frame. Mirrors the implicit GPU reset on camera cut or window
  resize.
- `denoise_numpy(self, noisy, normal, depth) -> np.ndarray` — **CPU
  reference path** (Sprint 2B). Faithful NumPy mirror of the four WGSL
  passes used for unit tests, headless examples, and GPU-less
  fallbacks.
  - `noisy: (H, W, 3) float32` — noisy radiance for the current frame.
  - `normal: (H, W, 3) float32` — world-space surface normals.
  - `depth: (H, W) float32` — linear depth.
  - Returns `(H, W, 3) float32` denoised radiance.
- `init_gpu(self, gpu, width: int, height: int) -> None` — allocate
  the temporal accumulator (`rgba16float`), moments (`rg32float`),
  history length (`r16float`), per-pixel variance (`r16float`), and
  two wavelet ping-pong textures.
- `denoise(self, encoder, noisy_color, gbuffer_pos, gbuffer_normal,
  gbuffer_depth, albedo, output_tex) -> None` — full 5-pass GPU
  pipeline: temporal accumulation → variance estimation → 5 à-trous
  wavelet iterations at step widths 1, 2, 4, 8, 16 → albedo modulate.

#### CPU path details

The `denoise_numpy` path stores `{color, m1, m2, len}` arrays in
`self._cpu_history` between frames. Per pass:

- **Temporal**: EMA blend on color + per-pixel luminance moments,
  saturating at `MAX_HISTORY`.
- **Variance**: `max(m2 - m1², 0)` per pixel.
- **À-trous**: 5 iterations of a 3×3 Gaussian (`[1,2,1; 2,4,2; 1,2,1]/16`)
  with multiplicative edge-stops on luminance (`exp(-|Δl| / (σ·√var))`),
  normal (`max(n·n', 0)^φ_n`), and depth, plus a wrap-rejection mask so
  rolled samples that crossed an image edge get zero weight.

#### References

- Schied et al. *Spatiotemporal Variance-Guided Filtering: Real-Time
  Reconstruction for Path-Traced Global Illumination*. HPG 2017.
  The canonical SVGF paper this implementation tracks.
- Dammertz et al. *Edge-Avoiding À-Trous Wavelet Transform for fast
  Global Illumination Filtering*. HPG 2010. The wavelet
  decomposition + edge-stop framework SVGF builds on.

## Functions

_(none — all public surface is class-based.)_

## Constants

### `_RESERVOIR_STRIDE` (internal)

_int — defined in `slappyengine.gi.restir`_

Value: `32`. Bytes per reservoir record; not exported but documents
the GPU buffer layout (see ReSTIRSystem constructor signature above).

## Inner modules

- `slappyengine.gi.cascade` — `RadianceCascadeSystem`
- `slappyengine.gi.restir` — `ReSTIRSystem`
- `slappyengine.gi.svgf` — `SVGFDenoiser` + module constants

## Notes

- All three systems instantiate the same way: cheap Python constructor
  followed by an `init_gpu(...)` that catches `wgpu` import errors and
  flips an internal `_initialized` flag. `dispatch` / `denoise` become
  silent no-ops when initialisation failed, so a CI runner without a
  GPU adapter is fully supported.
- The CPU SVGF path landed in Sprint 2B (commit `4edb294`); the
  cascade pipelines are cached at `init_gpu` rather than per dispatch
  after the lighting-next sprint (2026-05-25).
- For the GPU-side WGSL sources, see `shaders/svgf_temporal.wgsl`,
  `shaders/svgf_variance.wgsl`, `shaders/svgf_wavelet.wgsl`,
  `shaders/svgf_modulate.wgsl`, `shaders/lighting_radiance_*.wgsl`,
  and `shaders/restir_*.wgsl`.

## See also

- [`../gi_design.md`](../gi_design.md) — architecture, pass-by-pass
  rationale, citations, and the headless / Rust-migration story.
- [`post_process.md`](post_process.md) — the post-process chain that
  consumes the GI output (TAA / Bloom / Tonemap).
- [`numerics.md`](numerics.md) — multigrid Poisson primitives the
  cascade restriction operators could reuse if cascade temporal moves
  to a Poisson-based smoother.
