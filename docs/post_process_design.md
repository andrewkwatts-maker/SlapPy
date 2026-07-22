# pharos_engine.post_process — Design Reference

`pharos_engine.post_process` is the engine's **declarative post-process
chain**: a list of GPU compute passes that operate on the lighting /
tonemap framebuffer between the renderer and the swap chain. Every
shipped pass — TAA, Bloom, GTAO, Tonemap, SSR, DoF, Outline, Vignette,
Motion Blur, Shadow CSM, Volumetric Fog, Auto-Exposure, plus the
"warp" / pixelate / night-vision / chromatic-aberration / gravity-warp
gimmicks — composes through the same `PostProcessChain` and is walked
by a single `PostProcessExecutor`.

For the runtime API surface (pass classes, chain helpers, preset
factories), see the companion [API reference](api/post_process.md).

## Why a declarative chain?

Earlier revisions of the engine wired post-process passes directly into
the renderer's draw loop. Each new pass meant:

1. A new fragment shader.
2. A bespoke `EntityRenderer.draw_post_*` method.
3. Hand-managed ping-pong RTs.
4. Hand-managed UBO packing in three different shapes.

The chain refactor (Sprint 1, pre-v0.3) collapsed all four concerns
into one shape:

- **One compute shader** per pass, in `shaders/<pass_name>.wgsl`.
- **One pass dataclass** with a `make_pass()` factory.
- **One executor** that walks the chain, manages a single RT pair, and
  caches compute pipelines.
- **One UBO convention** with two declarative variants (see below).

The result: adding a new pass is one new shader + one new pass class
inheriting `PostProcessPassBase`, and the chain wiring is mechanical.

## Chain composition

```python
from pharos_engine.post_process import PostProcessChain, BloomPass, TonemapPass

chain = PostProcessChain()
chain.add_bloom(threshold=1.0, knee=0.5, intensity=0.05)
chain.add_tonemap(exposure_ev=0.0, mode=0)   # ACES filmic
chain.add_outline(color=(0, 0, 0, 1), threshold=0.1, use_sobel=True)
```

The chain owns an ordered list of `PostProcessPass` records. Each
record carries:

- `shader_path` — file under `shaders/` to dispatch.
- `params` — a Python dict for executor-packed UBOs (legacy passes).
- `raw_params_bytes` — pre-packed UBO bytes (TAA, GTAO, Bloom — passes
  with non-trivial layouts that single-source the struct in their own
  class via `struct.pack`).
- `label` — chain key (`"bloom"`, `"taa"`) used by `remove(label)` and
  the round-8 dependency declarations.
- `depends_on` — labels that must precede this pass, mirroring
  `RenderPass.depends_on`. The `iso_strategy_chain` preset uses this so
  the topological executor schedules correctly even if a caller
  re-orders the chain.

`PostProcessChain.passes` returns the **enabled** subset in insertion
order; passes flip themselves off by setting `pass_.enabled = False`
rather than being removed (cheaper at runtime than `remove`/`add`).

## UBO layout convention

Every pass that takes parameters packs them into a std140-aligned
uniform buffer object. Two conventions coexist:

### A. Executor-packed (`params` dict)

The pass owner declares `params` as a flat Python dict; the executor's
`_make_params_buffer` packs every value as `f32` / `u32` in dict-
insertion order with 16-byte std140 padding. This is the **legacy**
path — easy to author, but fragile to schema drift because the WGSL
binding has to match the dict-ordering bit-for-bit.

```python
chain.add_pixelate(block_size=4)
# Internally: PostProcessPass(shader_path="pixelate.wgsl",
#                             params={"block_size": 4})
```

### B. Pre-packed (`raw_params_bytes`)

The pass class single-sources the UBO layout via `struct.pack` in its
own `make_pass()` factory and hands the resulting bytes to
`PostProcessPass.raw_params_bytes`. The executor sees only the bytes —
no dict, no per-field traversal — and writes them straight to the
uniform buffer.

This is the **canonical** path for any non-trivial UBO. TAA, GTAO, and
Bloom all use it. The class then carries its WGSL binding in the
header comment for documentation and matches the struct layout
byte-for-byte. Drift is caught by
`SlapPyEngineTests/tests/test_post_process_base.py::test_bloom_params_to_bytes_matches_legacy_struct_pack`.

#### Worked example — Bloom (16-byte std140 UBO)

```wgsl
struct BloomParams {
    threshold : f32,   // @ offset 0
    knee      : f32,   // @ offset 4
    intensity : f32,   // @ offset 8
    _pad      : f32,   // @ offset 12
};
@group(0) @binding(2) var<uniform> params : BloomParams;
```

Python side (`bloom.py`):

```python
class BloomPass(PostProcessPassBase):
    label: ClassVar[str] = "bloom"
    SHADER: ClassVar[str] = "bloom.wgsl"
    PARAMS_LAYOUT: ClassVar = ("3fI", ["threshold", "knee", "intensity", "_pad"])
    # struct.pack("3fI", 1.0, 0.5, 0.05, 0)  ->  b"\x00\x00\x80?\x00\x00\x00?\xcd\xccL=\x00\x00\x00\x00"
```

Layout is the **single source of truth**: changing `PARAMS_LAYOUT` and
the WGSL struct in lockstep is the only legal mutation; the executor
never inspects field names again.

#### Worked example — TAA (32-byte UBO, splice fields)

```wgsl
struct TaaParams {
    blend_factor          : f32,  // @ 0
    sharpening            : f32,  // @ 4
    width                 : u32,  // @ 8   ← spliced by executor
    height                : u32,  // @ 12  ← spliced by executor
    karis_weight          : u32,  // @ 16
    tight_variance_clip   : u32,  // @ 20
    variance_clip_gamma   : f32,  // @ 24
    _pad                  : u32,  // @ 28
};
```

The `width` and `height` fields are dispatch-time values the pass class
can't know at construction. Instead of forcing every pass to re-pack
its UBO every frame, the executor's `_splice_runtime_params` hook
**patches those bytes in place** at the known offsets:

```python
def _splice_runtime_params(self, pass_: PostProcessPass, w: int, h: int) -> bytes:
    body = pass_.raw_params_bytes
    if pass_.shader_path.endswith("taa_resolve.wgsl"):
        return body[:8] + struct.pack("II", w, h) + body[16:]
    # ... GTAO and ContactShadows have the same shape
    return body
```

The splice is one byte-substring per affected pass — zero allocation,
no field-name lookup. The convention is "the owning class knows the
struct layout including the spliced fields' offsets; the executor only
knows where to write the dispatch-time values".

### Why both UBO paths?

The pre-packed path is strictly better for new passes — but converting
every legacy pass would have meant a coordinated rewrite of the executor,
every pass class, and every WGSL binding. The base class
`PostProcessPassBase` supports both via `PARAMS_LAYOUT` (pre-packed) vs
`params_dict()` (legacy executor packing). Subclasses opt into direct
packing by declaring `PARAMS_LAYOUT`; otherwise the legacy
params-dict route stays intact bit-for-bit. Sprint 2026-06 migrated
Bloom, Outline, and Tonemap; TAA / GTAO / ContactShadows / SSR are
queued.

## Executor pipeline

```text
                     ┌──────────────────────────────────┐
                     │ PostProcessExecutor.run(scene_tex,│
                     │                       depth_tex)  │
                     └────────────────┬─────────────────┘
                                      ▼
       ┌────────────────────────────────────────────────────┐
       │  for each enabled pass in chain.passes:            │
       │     1. Look up cached compute pipeline             │
       │        (key = "shader_path::entry_point")          │
       │        or compile + cache it.                      │
       │     2. Pack UBO via _make_params_buffer            │
       │        OR copy raw_params_bytes + splice runtime   │
       │        fields.                                     │
       │     3. Make bind group: input RT, output RT,       │
       │        UBO, + extra texture bindings declared by   │
       │        the pass (TAA history, GTAO depth, ...).    │
       │     4. dispatch_workgroups(...)                    │
       │     5. Swap input/output RT (ping-pong).           │
       └────────────────────────────────────────────────────┘
                                      ▼
                          final RT → swap chain
```

### Ping-pong RT pair

The executor owns two `rgba8unorm` render-targets sized to the
viewport. Each pass reads the "current" RT and writes the "other" one;
they swap roles at the end of every pass. Two RTs is the minimum that
supports an arbitrarily long chain without per-pass allocation.

A `resize(width, height)` call recreates both RTs in lockstep — the
executor never holds stale-sized targets after a window resize.

### Pipeline cache

Compute pipelines are cached by the key
`f"{shader_path}::{entry_point}"`. The first dispatch of a given pass
compiles the WGSL and creates the pipeline; subsequent dispatches reuse
the cached `wgpu.GPUComputePipeline`. Pipeline creation is the
expensive step (driver compilation + state validation), so amortising
it to zero per-frame cost is the executor's most important optimisation.

The cache is keyed on the file path, not the file contents, so a
shader edit during development still requires an `executor.invalidate()`
call to refresh. This is intentional — auto-invalidating on every
frame would cripple performance.

### Splice executor

The runtime-field splice (`_splice_runtime_params`) is the executor's
escape hatch for fields that depend on dispatch context (width, height,
camera matrices for screen-space passes) without forcing the owning
class to re-pack its UBO every frame.

Today the splice supports:

- `taa_resolve.wgsl` — width/height at offsets 8, 12.
- `gtao_main.wgsl` — width/height at offsets 88, 92.
- `contact_shadows.wgsl` — same pattern.

Adding a new spliced field is a two-line change: declare the byte
offset, add a case to `_splice_runtime_params`. The owning class never
learns about it.

## Lazy import

`post_process/__init__.py` uses `_LAZY_MAP` + `__getattr__` so
`import pharos_engine` does not pull in `wgpu`. A fresh `python -c
"import pharos_engine"` does not touch `wgpu.GPUDevice` until a pass
constructor is actually referenced. This matters for headless CI and
for the `[editor]` / `[ai]` extras that ship without a GPU stack.

## Preset chains

Three preset factories ship in `preset_chains.py`:

- `cinematic_chain()` — `dof → bloom → tonemap → chromatic_aberration
  → vignette → outline`. Cutscenes / showcase demos.
- `arcade_chain()` — `bloom → tonemap → outline → vignette`. No DoF/CA
  (both blur the play-field). Used by Ochema Circuit + Bullet Strata.
- `iso_strategy_chain()` — `bloom → tonemap → vignette` with explicit
  `depends_on` declarations so the topological executor schedules them
  correctly even if a caller re-orders the chain. Stone Keep.

Each preset is one short factory function that builds a fully
populated `PostProcessChain` and never mutates global state — opting
out is as simple as building a bare chain.

## Backward-compat by default

Every round's added knob ships with a default that reproduces legacy
behaviour bit-for-bit. The list, with the no-op condition each one
honours:

| Round | Knob | No-op condition |
|---|---|---|
| 4 | `vignette.feather` | `feather=0` reproduces the legacy `pow(d*s, 2)` curve. |
| 4 | `taa.tight_variance_clip` | `False` restores the round-3 min/max envelope. |
| 5 | `outline.softness` / `use_sobel` | `softness=0`, `use_sobel=False` reproduces the round-4 hard edge. |
| 6 | `chromatic_aberration.falloff_power` / `_amount` | `falloff_power=1.0`, `falloff_amount=0.0` reproduces linear legacy. |
| 7 | `tonemap.saturation` / `contrast` / `lift` / `gain` / `gamma` | All identity defaults. |
| 9 | `dof.focus_transition` | `focus_transition=0` reproduces the round-8 step. |

This is the **stability contract** — a game that pins a chain through a
config file can upgrade the engine across rounds without visual drift
unless it opts in.

## When to migrate to Rust

Like GI, the post-process subpackage is GPU-bound. The Python side
amounts to:

1. Constructor: validate inputs, store dataclass fields.
2. `make_pass()`: `struct.pack` 16-112 bytes per frame.
3. Executor: walk a list, look up cached pipelines, splice 8 bytes,
   dispatch.

`struct.pack` on a 32-byte payload is ~600 ns; the executor's per-pass
overhead is similar. The total per-frame Python cost across an 8-pass
chain is well under a millisecond — within shouting distance of
"already free". The Rust-migration plan
([`rust_migration_plan.md`](rust_migration_plan.md)) does not target
this subpackage.

## See also

- [`api/post_process.md`](api/post_process.md) — every pass class,
  every preset factory, full UBO layouts.
- [`api/gi.md`](api/gi.md) — the GI denoiser output feeds into this
  chain.
- [`gi_design.md`](gi_design.md) — the GI pipeline architecture.
- [`lighting_presets.md`](lighting_presets.md) — ready-to-use chains
  composing the lighting-polish helpers into flagship game looks.
- [`api/gpu.md`](api/gpu.md) — `GPUContext` / `BufferManager` the
  executor builds against.
- `CONTRIBUTING.md` § "Adding a post-process pass" — the step-by-step
  recipe for new passes, including the WGSL companion and tests.

## References

- Salvi, M. (2016). *An Excursion in Temporal Supersampling.* GDC. The
  variance-clip envelope TAA's `tight_variance_clip` defaults to.
- Karis, B. (2014). *High Quality Temporal Supersampling.* SIGGRAPH
  Courses. The luminance-inverse blend for firefly suppression.
- Lottes, T. (2017). *Advanced Techniques and Optimization of HDR
  Color Pipelines.* GDC. The smooth-knee bloom threshold.
- Jiménez, J. (2014). *Next Generation Post Processing in CoD: Advanced
  Warfare.* SIGGRAPH. The 13-tap downsample + tent upsample pyramid
  Bloom uses.
- Jiménez et al. (2016). *Practical Realtime Strategies for Accurate
  Indirect Occlusion.* SIGGRAPH. GTAO radius + multibounce.
- Narkowicz, K. (2016). *ACES Filmic Tone Mapping Curve.* The default
  `tonemap.mode=0` curve.
- Reinhard et al. (2002). *Photographic Tone Reproduction for Digital
  Images.* SIGGRAPH. The `tonemap.mode=1` alternative.
- Lottes, T. (2014). *FXAA / chromatic-aberration falloff polynomial.*
  Round-6 chromatic aberration uses this falloff curve.
