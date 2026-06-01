<!-- handauthored: do not regenerate -->
# slappyengine.post_process — API Reference

> Hand-written reference for the post-process subpackage.
> Covers chain composition, per-pass param-struct conventions, and the
> canonical papers behind each technique. For GI denoising see
> [`gi.md`](gi.md).


The subpackage is **lazy-loaded**: `__init__.py` registers names in
`_LAZY_MAP` and resolves them through `__getattr__`, so
`import slappyengine` does not pull in `wgpu`. Pipeline shape: build a
:class:`PostProcessChain` (or call a preset factory), append
:class:`PostProcessPass` records front-to-back, hand the chain to a
:class:`PostProcessExecutor`, let the executor walk it once per frame
against a ping-pong RT pair.

## Public surface (`__all__`)

- `PostProcessChain`, `PostProcessPass` — composition primitives
  (`chain.py`).
- `PostProcessExecutor` — GPU walker (`executor.py`).
- `TAAPass`, `GTAOPass`, `ShadowCSM`, `VolumetricFog` — Sprint-3D /
  Sprint-4C / Nova3D-additions standalone passes.
- `cinematic_chain`, `arcade_chain`, `iso_strategy_chain` — preset
  factories (`preset_chains.py`).

Internal helpers also exposed per-module: `BloomPass`, `DofPass`,
`OutlinePass`, `VignettePass`, `AutoExposurePass`, `TonemapPass`,
`MotionBlurPass`, `SSRPass`.

## Classes

### `PostProcessPass`

_dataclass — defined in `slappyengine.post_process.chain`_

One compute pass.

```python
PostProcessPass(
    shader_path: str,
    params: dict | None = None,
    label: str = "",
    enabled: bool = True,
    entry_point: str = "main",
    raw_params_bytes: bytes | None = None,
    depends_on: list[str] = <factory>,
) -> None
```

- `shader_path` — file under `shaders/` to execute.
- `params` — python-side dict; the executor's `_make_params_buffer`
  packs it into a UBO. Ignored for UBO packing when
  `raw_params_bytes` is set (then used only for sideband data such as
  texture bindings).
- `label` — chain key used by `remove(label)` and the round-8
  dependency declarations.
- `enabled` — chain skips disabled passes via the `passes` property.
- `entry_point` — WGSL entry. Several passes use custom names
  (`taa_resolve_main`, `nv_grain_main`, `chromatic_aberration_main`,
  `ao_gtao_main`, `tonemap_main`).
- `raw_params_bytes` — pre-packed UBO (TAA, GTAO, Bloom) so layout is
  single-sourced in the owning class.
- `depends_on` — labels that must precede this pass. Mirrors
  `RenderPass.depends_on`; `iso_strategy_chain` populates it.

### `PostProcessChain`

_class — defined in `slappyengine.post_process.chain`_

Ordered chain with `add()`, `remove(label)`, and the `passes` property
(enabled subset, insertion order). Strongly-typed helpers for every
built-in effect — each ships with backward-compat defaults:

- `add_blur(radius=2)`, `add_pixelate(block_size=4)`,
  `add_gravity_warp(center, strength, radius)`,
  `add_night_vision(gain, grain_strength, vignette_strength, time)`.
- `add_vignette(strength, inner_radius, feather)` — round-4 smoothstep
  shoulder (`feather > 0`); `feather=0` reproduces the legacy
  `pow(d*s, 2)` curve bit-for-bit.
- `add_outline(color, threshold, softness=0.0, use_sobel=False)` —
  round-5 added Sobel detector + smoothstep softness.
- `add_chromatic_aberration(strength, center, falloff_power=1.0,
  falloff_amount=0.0)` — round-6 polynomial radial falloff
  (Lottes 2014); defaults match linear legacy.
- `add_tonemap(exposure_ev, mode, saturation, contrast, lift, gain,
  gamma, auto_ev=None)` — round-7 colour grading.
- `add_bloom(threshold, knee, intensity)` — wraps :class:`BloomPass`.
- `add_dof(focal_distance, focal_range, max_coc_radius, bokeh_samples,
  focus_transition, scene_tex=None, depth_tex=None)` — round-9
  `focus_transition` smoothstep ramp.

### `PostProcessExecutor`

_class — defined in `slappyengine.post_process.executor`_

Owns the ping-pong RT pair (`rgba8unorm`, recreated on resize),
caches compute pipelines by `f"{shader_path}::{entry_point}"`, and
packs UBOs from each pass's `params` dict. The
`_splice_runtime_params` hook patches dispatch-time fields (currently
`width`/`height` for `taa_resolve.wgsl`) into pre-packed UBOs without
touching the owning class's struct layout.

### `TAAPass`

_class — defined in `slappyengine.post_process.taa`_

Temporal anti-aliasing with a YCoCg neighbourhood AABB clip and an
optional Karis luminance-inverse blend.

```python
TAAPass(
    alpha: float = 0.1,
    variance_clip_gamma: float = 1.0,
    motion_weight: float = 1.0,
    karis_weight: bool = False,
    tight_variance_clip: bool = True,
    sharpening: float = 0.0,
) -> None
```

**UBO layout** (`TaaParams`, 32 bytes — Sprint 3D round 4):
`blend_factor:f32@0`, `sharpening:f32@4`, `width:u32@8` (spliced),
`height:u32@12` (spliced), `karis_weight:u32@16` (0/1),
`tight_variance_clip:u32@20` (0/1), `variance_clip_gamma:f32@24`,
`_pad:u32@28` (16-byte alignment).

`tight_variance_clip` defaults `True` since Sprint 5C — the round-4
mean ± γ·σ envelope (Salvi 2016) cut thin-geometry shimmer by 19.5%
ghost and +1 dB PSNR on disocclusion bands. `False` restores the
round-3 min/max envelope. `karis_weight` opts into the Karis 2014
luminance-inverse blend that suppresses single-frame fireflies.

**Methods**: `from_config(cfg)`; `make_pass(frame_tex, history_tex,
motion_tex)` packs the UBO + binds textures; `resolve_numpy(current,
history, motion_uv=None)` is the pure-NumPy CPU reference used by the
regression suite.

**References**: Salvi 2016 *An Excursion in Temporal Supersampling*
(variance clip); Karis 2014 *High Quality Temporal Supersampling*
(luminance-inverse weighting).

### `BloomPass`

_class — defined in `slappyengine.post_process.bloom`_

Lottes 2017 smooth-knee extraction; the soft curve avoids popping when
emissive pixels sweep across the threshold. Reference luma is
`max(R,G,B)` so saturated pure-channel emissives still bloom.

**UBO layout** (16 bytes, std140): `threshold:f32@0`, `knee:f32@4`,
`intensity:f32@8`, `_pad:f32@12`. `knee == 0` collapses the soft
branch to `max(luma - threshold, 0)`, reproducing the legacy hard
cutoff bit-for-bit.

**Module helpers** (Sprint 3D — COD 2014 pyramid):

- `smooth_threshold(rgb, threshold, knee)` — CPU reference of the
  Lottes curve.
- `downsample_mn13(rgb, karis_clamp=False)` — 13-tap "partial-Karis"
  downsample. `karis_clamp=True` only on the first mip (firefly
  suppression); later mips stay linear so weights sum to 1.
- `upsample_tent9(low, dst_shape)` — 9-tap 3×3 tent
  (corners 1, edges 2, centre 4; sum 16). Sums to 1 exactly.
- `downsample_box2(rgb)` — legacy 2×2 box, kept for PSNR comparisons.

**References**: Lottes 2017 *Advanced Techniques and Optimization of
HDR Color Pipelines* (smooth-knee threshold); Jimenez 2014 *Next
Generation Post Processing in CoD: Advanced Warfare* (13-tap
downsample + tent upsample pyramid).

### `GTAOPass`

_class — defined in `slappyengine.post_process.gtao`_

Ground-truth ambient occlusion with Jiménez 2016 distance-aware radius
and §2.3 multibounce.

```python
GTAOPass(
    num_directions: int = 8, num_steps: int = 4,
    radius: float = 2.0, intensity: float = 1.0, bias: float = 0.05,
    max_pixel_radius: float = 64.0, inv_proj: tuple = <identity-mat4>,
    depth_falloff: float = 0.0, min_radius_scale: float = 0.25,
    multibounce: bool = True,
) -> None
```

**UBO layout** (`GtaoParams`, 112 bytes): `inv_proj:mat4x4@0` (64 B),
`radius:f32@64`, `max_pixel_radius:f32@68`, `num_directions:u32@72`,
`num_steps:u32@76`, `power:f32@80`, `bias:f32@84`, `width:u32@88`
(spliced), `height:u32@92` (spliced), `depth_falloff:f32@96`,
`min_radius_scale:f32@100`, `multibounce:u32@104` (0/1),
`_pad0:u32@108`.

**Quality knobs**:

- `intensity` maps to `power = 1/intensity` (higher intensity darkens
  faster; full-lit stays at 1.0).
- `depth_falloff = 0` disables per-pixel radius adaptation
  (pre-adaptive shader behaviour). Practical range 0.05–0.5 m⁻¹.
- `min_radius_scale ∈ [0,1]` lower-bounds the adapted scale so near
  pixels do not collapse to sub-pixel radii.
- `multibounce=True` reads albedo and brightens crevice visibility
  per channel using the cubic-poly fit `f(v) = a·v² + b·v + c`. At
  `albedo=0` the lerp is a no-op; the `max` clamp keeps multibounce
  ≥ single-bounce.

**Functions**:

- `compute_adaptive_radius(world_radius, view_depth, depth_falloff,
  min_radius_scale=0.25, max_radius_scale=1.0)` — per-pixel scale
  `1 - exp(-depth_falloff · z)`, clamped.
- `multibounce_visibility(visibility, albedo)` — Jiménez 2016 §2.3
  cubic approximation, called once per RGB channel.

**References**: Jiménez et al. 2016 *Practical Realtime Strategies
for Accurate Indirect Occlusion* SIGGRAPH (radius + multibounce);
Jiménez 2015 *Practical Real-Time Strategies for Accurate Indirect
Occlusion* SIGGRAPH (horizon-search formulation).

### `TonemapPass`

_dataclass — defined in `slappyengine.post_process.tonemap`_

Wraps `tonemap.wgsl` with the round-7 colour-grading knobs
(`saturation`, `contrast`, per-channel `lift`/`gain`, `gamma`) and
optional auto-exposure. `mode=0` ACES filmic (default), `mode=1`
Reinhard. With `auto_ev=None` the manual `exposure_ev` is forwarded
byte-for-byte. With an :class:`AutoExposurePass` attached, call
`derive_exposure_ev(scene)` once per frame and the next `make_pass()`
picks up the auto-derived EV via the `effective_ev` property.

**References**: Narkowicz 2016 *ACES Filmic Tone Mapping Curve*
(`mode=0`); Reinhard et al. 2002 *Photographic Tone Reproduction for
Digital Images* (`mode=1`).

### `ShadowCSM`, `VolumetricFog`, others

Standalone passes wrapping dedicated shaders (`lighting_shadow_csm.wgsl`,
`volumetric_fog.wgsl`, etc.). All follow the same constructor →
`make_pass` → optional `apply_cpu` pattern as TAA/GTAO/Bloom; see
source files for full UBO layouts:

- `AutoExposurePass` (`auto_exposure.py`) — geometric-mean log-luminance
  EV derivation.
- `DofPass` (`dof.py`) — round-9 `focus_transition` smoothstep CoC ramp.
- `MotionBlurPass` (`motion_blur.py`) — per-pixel velocity stretch.
- `OutlinePass` (`outline.py`) — Sobel + smoothstep silhouette.
- `SSRPass` (`ssr.py`) — screen-space reflections.
- `VignettePass` (`vignette.py`) — round-4 smoothstep shoulder.

## Functions

### Preset chain factories

_defined in `slappyengine.post_process.preset_chains`_

Each returns a fully populated `PostProcessChain` and never mutates
global state — opting out is as simple as building a bare chain.

- `cinematic_chain()` — "movie look":
  `dof → bloom → tonemap → chromatic_aberration → vignette → outline`.
  Round-9 DoF softness, round-6 polynomial CA falloff, round-4
  smoothstep vignette, round-5 Sobel outline. Cutscenes / showcase
  demos.
- `arcade_chain()` —
  `bloom → tonemap → outline → vignette`. No DoF/CA (both blur the
  play-field). Ochema Circuit + Bullet Strata.
- `iso_strategy_chain()` —
  `bloom → tonemap → vignette`. Declares
  `depends_on=['bloom']` on tonemap and `depends_on=['tonemap']` on
  vignette so the round-8 topological executor schedules them
  correctly even if a caller re-orders the chain. Stone Keep.

## Inner modules

- `chain` — `PostProcessChain`, `PostProcessPass`.
- `executor` — `PostProcessExecutor`, `_splice_runtime_params`.
- `taa` — `TAAPass` (32-byte UBO).
- `bloom` — `BloomPass`, COD 2014 pyramid helpers.
- `gtao` — `GTAOPass` (112-byte UBO), adaptive-radius helpers.
- `tonemap`, `auto_exposure`, `dof`, `outline`, `vignette`,
  `motion_blur`, `ssr`, `shadow_csm`, `volumetric_fog`,
  `preset_chains`.
- `_validation` — internal type/range validators shared by every
  pass constructor.

## Conventions

- **UBO single-source-of-truth.** Passes with non-trivial uniform
  layouts (TAA, GTAO, Bloom) pack the struct in `make_pass()` via
  `struct.pack` and hand the bytes to
  `PostProcessPass.raw_params_bytes`. The executor splices
  dispatch-time fields (currently width/height for TAA) via
  `_splice_runtime_params` rather than re-packing.
- **Backward-compat by default.** Every round's added knob (round-4
  variance clip, round-5 Sobel outline, round-6 CA falloff, round-7
  colour grading, round-9 DoF transition) ships with a default that
  reproduces legacy behaviour bit-for-bit; see each pass's docstring
  for the explicit no-op condition.
- **CPU reference paths.** TAA, Bloom, GTAO, Tonemap, and
  AutoExposure ship NumPy reference implementations
  (`resolve_numpy`, `apply_cpu`, `multibounce_visibility`, …) used by
  the headless regression suite to verify the WGSL shaders without a
  GPU.
- **Lazy import.** Top-level `__init__.py` uses `__getattr__` against
  `_LAZY_MAP` so importing the subpackage does not pull in `wgpu`.
