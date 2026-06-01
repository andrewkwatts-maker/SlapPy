<!-- handauthored: do not regenerate -->
# slappyengine.compute — API Reference

> Hand-written reference for the GPU compute subpackage.
> Covers the dispatch pipeline, bulk pixel mutation, stats reduction,
> spatial primitives, and the per-asset compute API. For the renderer
> side of the GPU surface see `slappyengine.gpu`; for the lighting
> compute kernels see [`gi.md`](gi.md).

```python
from slappyengine.compute import (
    ComputePass, ComputePipeline,
    ReadbackBuffer,
    StatsCompute, StatsResult,
    SpatialCompute, AABB,
    PixelMutator,
    AssetComputeAPI, PixelAPI,
)
```

All names are lazy-loaded via `__getattr__` — importing
`slappyengine.compute` is cheap, the wgpu / numpy modules only land when
you actually touch a symbol. This keeps headless CI fast.

## Shared infrastructure

Every dispatcher in this subpackage takes the same four constructor
arguments:

| Name | Role |
|------|------|
| `ctx: GPUContext` | wgpu device + queue wrapper (buffer / encoder factory). |
| `registry: StructRegistry` | Per-asset struct layout — owns `stride_bytes()` and `_compute_layout()` (channel name → byte offset). |
| `shader_gen: ShaderGen` | Injects the registry's WGSL struct definition into each shader template (`inject_into_shader(src)`). |
| `tag_registry: TagRegistry \| None` | Optional name → bitmask resolver for tag-filtered dispatches. |

Pipelines are cached by SHA-256 of the post-injection WGSL source
(`ComputePipeline._pipeline_cache`) or by template filename (every
other dispatcher), so the first dispatch compiles and subsequent calls
re-bind uniform buffers only. Workgroup size is hard-coded to **64**;
group count is `ceil(pixel_count / 64)`.

## ComputePass

Lightweight bag of `(source, entry_point, label)`. Two factories:

- `ComputePass.from_wgsl(path, entry_point="main")` — read a WGSL file
  and label the pass with its path.
- `ComputePass.from_source(source, entry_point="main", label="")` —
  inline WGSL string, typically used by the AST compiler in `PixelAPI.apply`.

## ComputePipeline

Owns the generic compute-dispatch path against a single layer's pixel
buffer.

- `bind_layer(layer, pixel_buf)` — must be called before `dispatch`
  or `sum_channel`. Sets the layer used for the pixel-count workgroup
  calculation.
- `await dispatch(pass_, readback_channels=None) -> dict` — inject the
  registry struct into `pass_.source`, compile (cached), dispatch, and
  optionally read back the listed channels. The result is a
  `{channel_name: np.ndarray}` dict where each array is the
  strided-out per-pixel column for that channel.
- `await sum_channel(channel, filter_tag=None, layer=0) -> float` —
  one-call reduction against the shipped `shaders/health_sum.wgsl`.
  The shader writes a fixed-point `×1000` u32 atomic accumulator, so
  the returned float has ~1e-3 absolute precision but no overflow
  risk for typical HP / mass channels.

## ReadbackBuffer

Standard GPU → CPU staging-buffer pattern in one class.

```python
rb = ReadbackBuffer(device, size_bytes)
raw = await rb.read_from(source_buf, dtype=np.float32)
rb.destroy()
```

`read_from` issues a `copy_buffer_to_buffer` of the entire allocation
into the staging buffer, calls `map_sync(MapMode.READ)`, copies the
mapped range out as a numpy array, and unmaps. **Always pair with
`destroy()`** — wgpu does not GC the staging allocation.

## StatsCompute + StatsResult

`StatsCompute.compute_stats(pixel_buf, pixel_count, channel, ops,
filter_tag=None, bounds=None, hull=None) -> StatsResult` runs
`shaders/stats_reduction.wgsl` once and gathers `sum / min / max /
count` in parallel via `asyncio.gather`. `mean` is derived on the host
(`sum / count`). The shader uses fixed-point ×1000 atomics on `sum` —
same precision/overflow caveats as `ComputePipeline.sum_channel`.

`StatsResult` fields: `mean`, `sum`, `min`, `max`, `count`, `std`,
`mode`, `requested_ops` (passthrough of the `ops` list). `std` and
`mode` are reserved — the current shader does not compute them, so
they stay at their dataclass defaults.

When `bounds` is supplied, the shader filters samples to the AABB
using a sqrt-derived `width` (assumes a square asset); pass an
explicit width when you need exact rectangular gating.

## SpatialCompute + AABB

`AABB(min_x, min_y, max_x, max_y)` is a plain dataclass with
`width()`, `height()`, `center()`, `contains(x, y)` helpers.

- `await bounds(pixel_buf, pixel_count, width, filter_tag=None,
  filter_channel=None, threshold=0.0) -> AABB` — runs
  `shaders/bounds_reduction.wgsl`. When `filter_channel` is set, only
  pixels whose channel value exceeds `threshold` contribute. The init
  values are `1e38 / -1e38` bit-cast through u32 atomics so the
  shader can use `atomicMin` / `atomicMax`.
- `await convex_hull(pixel_buf, pixel_count, width, filter_channel=None,
  threshold=0.0, filter_tag=None) -> list[(x, y)]` — reads the whole
  pixel buffer back, filters on CPU, and dispatches to the Rust
  `_core.convex_hull`. Falls back to a pure-Python monotone-chain
  implementation when `_core` is unavailable (slow; **testing only**).

## PixelMutator

GPU-accelerated bulk mutation against three shipped shader templates:
`pixel_set.wgsl`, `pixel_multiply.wgsl`, `pixel_add.wgsl`.

| Method | Effect |
|--------|--------|
| `set(*, filter_tag=None, channel, value)` | Write `value` into `channel` for every pixel passing the tag mask. |
| `multiply(*, filter_tag=None, channel, factor)` | In-place `channel *= factor`. |
| `add(*, filter_tag=None, filter_channel_gt=None, filter_channel_lt=None, channel, delta, clamp=False)` | In-place `channel += delta`; supports tag mask **and** a single channel-threshold gate (gt or lt). `clamp=True` clamps the result to `[0, 1]`. |

All three take a `channel` keyword that must exist in the
`StructRegistry` layout — unknown names raise `KeyError`. `bind_layer`
must be called before any mutation. The uniform buffer layout
(`3I I f I I f` base + optional `4I` extra) is fixed in
`_make_params_buf` and matches the params struct in every shader
template.

## AssetComputeAPI + PixelAPI

The asset-level facade: ties a `ComputePipeline` + `StatsCompute` +
`SpatialCompute` (`AssetComputeAPI`) or a `PixelMutator` (`PixelAPI`)
to a specific `Asset` and routes layer-index lookups through the
engine's `BufferManager`. The buffer manager is injected lazily — the
engine calls `bind_buffer_manager()` after GPU init, so constructing
an asset before the GPU is up does not fail.

`AssetComputeAPI` surface:

- `await sum_channel(channel, filter_tag=None, layer=0) -> float`
- `await stats(channel, ops, filter_tag=None, bounds=None, hull=None) -> StatsResult`
- `await bounds(filter_tag=None, filter_channel=None, threshold=0.0, layer=0) -> AABB`
- `await convex_hull(filter_channel=None, threshold=0.0, filter_tag=None, layer=0) -> list[(x, y)]`
- `await dispatch(compute_pass, readback_channels=None, layer=0) -> dict`

`PixelAPI` mirrors `PixelMutator.set / multiply / add` plus
`apply(*, filter, mutation, target_channel, layer=0)`. The
`apply` entrypoint compiles a pair of Python lambdas
(`filter`, `mutation`) into WGSL via
`slappyengine.compute.ast_compiler.compile_apply_shader` and
dispatches them against `shaders/pixel_apply_expr.wgsl`. Lambda
compilation failures raise `ValueError` wrapping the underlying
`ASTCompilerError`.

## Common dispatch pattern

```python
api = engine.asset_compute(asset)            # AssetComputeAPI
hp = await api.sum_channel("hp", filter_tag="enemy")

pix = engine.pixel_api(asset)                # PixelAPI
pix.multiply(channel="hp", factor=0.9, filter_tag="enemy")
pix.add(channel="hp", delta=-1.0, clamp=True,
        filter_channel_gt=("burn", 0.0))

bbox = await api.bounds(filter_channel="hp", threshold=0.0)
stats = await api.stats("hp", ops=["sum", "min", "max"])
```

The shared rhythm: bind once via the API constructor → keyword-only
mutators with `filter_*` gating → await-style readbacks. Every
public method validates channel names against the asset's
`StructRegistry`, so authoring errors fail at dispatch with a clear
`KeyError` rather than producing silent zeros.

## Inner modules

- `slappyengine.compute.pipeline` — `ComputePass`, `ComputePipeline`.
- `slappyengine.compute.readback` — `ReadbackBuffer`.
- `slappyengine.compute.stats` — `StatsCompute`, `StatsResult`.
- `slappyengine.compute.spatial` — `SpatialCompute`, `AABB`.
- `slappyengine.compute.mutator` — `PixelMutator`.
- `slappyengine.compute.asset_compute` — `AssetComputeAPI`, `PixelAPI`.
- `slappyengine.compute.ast_compiler` — lambda → WGSL transpiler used
  by `PixelAPI.apply`; `ASTCompilerError` surfaces authoring errors.
- `slappyengine.compute.effect` / `hull` / `library` / `shader_cache`
  / `wgsl_chunks` — internal helpers, not part of the public surface.
