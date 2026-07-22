# pharos_engine.gi — Design Reference

`pharos_engine.gi` is the engine's **global-illumination** subpackage —
three independent GPU systems that compose into a Nova3D-style indirect
lighting path:

1. **Radiance cascades** — probe-based diffuse indirect, exponentially
   doubling probe spacing.
2. **ReSTIR** — reservoir-based importance sampling for ~1000-SPP-quality
   direct + indirect lighting on a small per-pixel ray budget.
3. **SVGF** — spatiotemporal variance-guided filtering that denoises the
   noisy output of either of the above.

The three systems are deliberately independent: a game can ship
cascades-only (cheap diffuse), ReSTIR-only (sharp direct), or any
combination, gated by config. None of them depend on each other's
buffers — they each consume the engine's standard G-buffer (world-space
position, normal, albedo) and write into the lighting accumulator.

For the runtime API surface (constructors, dispatch signatures, UBO
layouts), see the companion [API reference](api/gi.md).

## Pipeline shape (high level)

```text
   gbuffer (pos, normal, albedo) ───┐
                                    ▼
   ┌──────────────────────────┐  ┌──────────────────┐
   │ RadianceCascadeSystem    │  │ ReSTIRSystem     │
   │ (4 passes: inject,       │  │ (4 passes: initial│
   │  merge, temporal, apply) │  │  RIS, temporal,   │
   │                          │  │  spatial, final)  │
   └────────────┬─────────────┘  └─────────┬────────┘
                ▼                          ▼
            lighting_acc (noisy radiance, rgba16float)
                          │
                          ▼
                    ┌──────────────┐
                    │ SVGFDenoiser │
                    │ (5 passes)   │
                    └──────┬───────┘
                           ▼
                       final framebuffer
```

Every system follows the same lifecycle:

- Cheap Python `__init__` (no GPU allocation).
- `init_gpu(gpu, ...)` allocates wgpu textures and storage buffers; a
  `wgpu` import failure (e.g. headless CI) is swallowed and the runtime
  path becomes a silent no-op so unit tests can construct the system
  without an adapter.
- `dispatch(encoder, ...)` runs the per-frame pass chain against a
  caller-owned `wgpu.CommandEncoder`.

The lifecycle pattern is asserted by
`PharosEngineTests/tests/test_gi_*` — the headless construction case is
load-bearing for CI.

## Radiance cascades

Probe-based diffuse indirect inspired by Sannikov 2023. The cascade
hierarchy stores spherical-harmonic L1 coefficients per probe and
trilinearly samples across levels for the screen-space apply pass.

### Why cascades?

Naïve per-pixel ray tracing is too expensive for full-screen indirect.
Probe-based methods amortise rays across a sparse grid, but a single
probe grid loses long-range bounces (probes too far apart to see each
other). The cascade trick — multiple probe grids at exponentially
doubling spacing — lets each level capture a different distance band:
the L0 level catches short-range contact-shadow detail; coarser levels
contribute the long-range bounce. Trilinear interpolation across levels
blends them seamlessly at apply time.

### Four passes per frame

1. **Inject** (`lighting_radiance_inject.wgsl`) — shoot
   `rays_per_probe_l0 / 4^level` rays from each probe and accumulate
   scene radiance into the SH L1 basis.
2. **Merge** (`lighting_radiance_merge.wgsl`) — walk coarse→fine and
   trilinearly blend coarse SH into finer textures.
3. **Temporal** — EMA blend the current cascade against history
   (`persistence = 1 - temporal_blend`, default 0.95). Today this is a
   CPU-side stub; the GPU path is reserved for a follow-up sprint.
4. **Apply** (`lighting_radiance_apply.wgsl`) — per-pixel trilinear
   probe sample, added to the lighting accumulator.

### Performance notes

- **GPU pipeline cache.** Sprint *lighting-next* (2026-05-25) hoisted
  pipeline creation out of `dispatch` and into `init_gpu`. Pre-fix
  profile showed `device.create_compute_pipeline` consuming ~30% of the
  cascade frame at 1080p — now amortised to zero per-frame cost.
- **Probe-grid memory.** Each cascade texture is `(probe_grid_w *
  probe_grid_h) × 4 SH coefficients × rgba16float` — at the default 4
  cascades, this stays under ~32 MB at 1080p, fitting in mid-tier VRAM
  budgets without eviction.

## ReSTIR

Reservoir-based importance sampling — Bitterli et al. 2020 (direct
lighting), Ouyang et al. 2021 (GI extension). Four GPU passes exchange
32-byte reservoirs through ping-pong storage buffers.

### Reservoir wire format

```text
 0  light_index     : f32   index into the scene's light buffer
 4  weight_sum      : f32   accumulated sample weights this RIS round
 8  W               : f32   ReSTIR's unbiased estimator weight
12  M               : f32   history length (Bitterli's "confidence")
16  sample_pos.x    : f32   world-space sample position
20  sample_pos.y    : f32
24  sample_n.x      : f32   world-space sample normal
28  sample_n.y      : f32
```

Total: 32 bytes (`_RESERVOIR_STRIDE = 32` in `restir.py`). The buffer is
sized `width * height * 32`; ping-pong toggles on `frame_count & 1`.

### Four passes

1. **Initial RIS** — generate up to `max_candidates` light samples and
   stream them through a weighted-reservoir update against the
   unshadowed contribution.
2. **Temporal reuse** — merge the previous frame's reservoir at the
   reprojected position, bounded by an `M` cap to limit history bias.
3. **Spatial reuse** — combine neighbouring reservoirs that pass a
   position + normal similarity gate, again capped to prevent runaway
   variance reduction.
4. **Final shade** — read the final reservoir, evaluate the BRDF, write
   the shaded output.

### Why both temporal and spatial?

Temporal alone leaks history across disocclusions (ghost trails behind
moving objects). Spatial alone has no inter-frame coherence (flickering
on still frames). Combining them with bounded `M` caps gives the
1000-SPP visual quality at ~1 SPP cost that ReSTIR is famous for.

## SVGF — Spatiotemporal Variance-Guided Filtering

The denoising stage. Schied et al. 2017 (HPG) is the canonical paper.
Both GPU and CPU paths ship — the CPU reference (`denoise_numpy`) is the
oracle the unit tests score against, exact to the WGSL's float ordering
modulo SIMD non-associativity.

### Five passes

1. **Temporal** — EMA blend on color + per-pixel luminance moments
   (m1, m2), saturating at `MAX_HISTORY = 32`.
2. **Variance** — `max(m2 - m1², 0)` per pixel.
3. **À-trous wavelet** (×5 iterations, step widths `1, 2, 4, 8, 16`) —
   3×3 Gaussian (`[1,2,1;2,4,2;1,2,1]/16`) with multiplicative
   edge-stops on:
   - **Luminance:** `exp(-|Δl| / (σ·√var))`
   - **Normal:** `max(n·n', 0)^φ_n`
   - **Depth:** `exp(-|Δz| · φ_z)`
   - **Wrap-rejection mask:** rolled samples that crossed an image edge
     get zero weight (otherwise the wraparound from `np.roll` would
     leak the opposite side of the image into the neighbourhood).
4. **Modulate** — multiply the denoised illuminance by surface albedo,
   recovering the textured final colour.

### Why à-trous + edge-stops?

À-trous lets a small 3×3 kernel act at multiple scales via the step
width — five iterations at widths `1, 2, 4, 8, 16` cover a 33-pixel
support without the cost of an actual 33×33 convolution. The edge-stops
prevent blurring across geometry/material boundaries, which is the
whole game in denoising — over-blur produces a smooth but wrong image,
under-blur leaves noise.

### CPU path provenance

The `denoise_numpy` reference landed in Sprint 2B (commit `4edb294`).
It exists for three reasons:

1. **Unit-test oracle.** WGSL kernels are tested against the numpy
   output, not against hand-curated baselines, so the test is
   self-checking.
2. **Headless examples.** Demos that run in CI without a GPU adapter
   need a working denoiser to produce meaningful screenshots for the
   visual-regression suite.
3. **Documentation.** The numpy code is a 200-line precise statement
   of what the shaders do; reviewers reading the WGSL can keep the
   numpy open as a reference.

## Module constants and tuning

The SVGF defaults match the WGSL kernels byte-for-byte (constant pin
asserted by the test suite):

| Constant | Value | Purpose |
|---|---|---|
| `PHI_COLOR` | 10.0 | Luminance edge-stop weight |
| `PHI_NORMAL` | 128.0 | Exponent on `dot(n, n')` |
| `PHI_DEPTH` | 1.0 | Depth edge-stop weight |
| `SIGMA_LUM` | 4.0 | Variance scale inside wavelet edge-stop |
| `TEMPORAL_ALPHA` | 0.1 | EMA blend weight for new frames |
| `MAX_HISTORY` | 32 | History-length cap for the temporal pass |

These are exposed as module-level names so a tuning sprint can override
them without forking the class — `pharos_engine.gi.svgf.PHI_COLOR = 5.0`
takes effect on the next `denoise_numpy` call.

## When to migrate to Rust

All three systems are GPU-bound; the Python side is just dispatch
orchestration. The Rust migration plan
([`rust_migration_plan.md`](rust_migration_plan.md)) does not target the
GI subpackage — the per-frame Python overhead is sub-millisecond
already, and porting WGSL kernels to Rust would not move the needle.
The natural next step is the **temporal cascade pass on GPU** to remove
the CPU readback, not a Rust port.

## See also

- [`api/gi.md`](api/gi.md) — public API surface for the three systems.
- [`api/post_process.md`](api/post_process.md) — the post-process side
  of the lighting pipeline (TAA / Bloom / GTAO consume the GI output).
- [`post_process_design.md`](post_process_design.md) — the chain
  composition, UBO conventions, and splice executor that the GI output
  flows into.
- [`api/numerics.md`](api/numerics.md) — multigrid primitives the
  cascade restriction operators could reuse if cascade temporal moves
  to a Poisson-based smoother.
- [`numerics_design.md`](numerics_design.md) — the multigrid V-cycle
  architecture and Rust-migration story.
- [`lighting_presets.md`](lighting_presets.md) — ready-to-use chains
  that bundle the GI passes with bloom / tonemap / outline.

## References

- Sannikov, A. (2023). *Radiance Cascades — A Novel Approach to
  Calculating Global Illumination.* The cascade-of-probes-at-doubling-
  spacing idea this implementation tracks.
- Ramamoorthi, R. & Hanrahan, P. (2001). *An Efficient Representation
  for Irradiance Environment Maps.* SIGGRAPH. SH L1 basis.
- Bitterli et al. (2020). *Spatiotemporal Reservoir Resampling for
  Real-Time Ray Tracing with Dynamic Direct Lighting.* SIGGRAPH.
- Ouyang et al. (2021). *ReSTIR GI: Path Resampling for Real-Time Path
  Tracing.* HPG. The indirect-illumination extension this system
  implements.
- Schied et al. (2017). *Spatiotemporal Variance-Guided Filtering:
  Real-Time Reconstruction for Path-Traced Global Illumination.* HPG.
- Dammertz et al. (2010). *Edge-Avoiding À-Trous Wavelet Transform for
  Fast Global Illumination Filtering.* HPG. The wavelet
  decomposition + edge-stop framework SVGF builds on.
