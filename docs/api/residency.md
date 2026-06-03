<!-- handauthored: do not regenerate -->
# slappyengine.residency — API Reference

> Hand-written reference for the asset-streaming + on-disk-format
> subpackage. Covers the GPU/RAM/DISK three-tier residency manager,
> the LZ4-with-zlib-fallback compression layer, and the `.slap` binary
> asset format used for both individual evictions and bundled world
> saves.

```python
from slappyengine.residency import (
    ResidencyManager,
    compress_array, decompress_array,
    compress_raw, decompress_raw,
    write_asset_to_slap, read_asset_from_slap,
    write_world_slap, read_world_slap,
    SLAP_MAGIC, SLAP_VERSION,
)
```

## Overview

All names are lazy-loaded via `__getattr__` (see
`residency/__init__.py`). The lazy loader tolerates `ImportError` for
optional Rust-backed siblings — anything but `ResidencyManager`
silently degrades to `None` if its module is missing, so games that
don't ship the streaming subsystem can still import the subpackage
without an early crash.

## Three-tier residency model

The manager classifies every asset into one of three tiers based on
distance from the camera:

| Tier | Storage | Trigger |
|---|---|---|
| `"gpu"` | wgpu texture/buffer | `dist ≤ streaming_radius_gpu` |
| `"ram"` | `layer._ram_pixel_data` (NumPy) | `streaming_radius_gpu < dist ≤ streaming_radius_ram` |
| `"disk"` | `<save_dir>/<entity.id>.slap` | `dist > streaming_radius_ram` |

The two radii and the VRAM / RAM budgets come from
`engine_config().residency` (YAML-driven — `vram_budget_mb`,
`ram_budget_mb`, `streaming_radius_gpu`, `streaming_radius_ram`).

### CacheMode (Ochema / Bullet Strata compat)

```python
class CacheMode(enum.Enum):
    GPU  = "gpu"
    RAM  = "ram"
    DISK = "disk"
```

Asset code (notably **Ochema Circuit** and **Bullet Strata**) reads
`Asset.cache_mode` to decide eviction priority and lazy-load policy
independently of the manager. The string values match
`ResidencyManager.TIER_*`, so a tier from the manager can be compared
directly against a `CacheMode` value.

## ResidencyManager

```python
mgr = ResidencyManager(ctx=gpu_ctx, buf_mgr=buf_mgr, tex_mgr=tex_mgr,
                       save_dir="./saves/world_01")
```

All four constructor arguments are optional. `save_dir` accepts either
a `str` or a `pathlib.Path`; the empty string raises `ValueError`, and
any other type raises `TypeError` (see `residency._validation`). The
directory is created with `parents=True, exist_ok=True`.

### Public API

| Method | Effect | Raises |
|---|---|---|
| `tier(entity) -> str` | Look up the entity's current tier (defaults to `"gpu"`). | `TypeError` if `entity` is `None` or lacks `.id` / `.layers`. |
| `update(camera_pos, entities)` | Re-tier every `Asset` in `entities` against `camera_pos`. | `TypeError` / `ValueError` from `validate_finite_2tuple` (rejects NaN/inf and wrong arity) and `validate_entity_list`. |
| `evict_to_ram(entity)` | Force a GPU→RAM transition (reads back the GPU texture if `ctx.readback_buffer_sync` is available; otherwise `_ram_pixel_data = None`). | `TypeError` on bad entity. |
| `evict_to_disk(entity)` | Force an all-the-way eviction. Automatically routes through `evict_to_ram` first if the entity is on GPU. | `TypeError` on bad entity. |
| `prefetch(entity)` | Promote to GPU regardless of current tier. | `TypeError` on bad entity. |

`update` is the typical entry point — call it once per frame (or once
per N frames) with the camera position and the list of streamable
entities. Non-`Asset` entries are silently skipped, so it is safe to
pass `scene.entities` wholesale.

### Internal promotion / demotion

- `_promote_disk_to_ram(entity)` reads `<save_dir>/<entity.id>.slap`
  via `read_asset_from_slap` and copies the resulting layer image data
  back into the entity. Missing file → no-op.
- `_promote_ram_to_gpu(entity)` re-uploads every layer with non-None
  `_image_data` via `tex_mgr.upload_layer`. No-op without a
  `TextureManager`.
- `_write_to_disk(entity)` shells out to `write_asset_to_slap`.
- `_free_ram(entity)` clears `layer._ram_pixel_data` on every layer.

The promotion path expects the engine to set `layer._gpu_texture`
when a texture is live on GPU — `evict_to_ram` checks both that
attribute and the presence of `ctx.readback_buffer_sync` before
attempting a CPU readback. Any readback failure is swallowed (data
falls back to `None`).

### Validation surface

`residency._validation` exports the four validators used by every
public method:

| Validator | Checks |
|---|---|
| `validate_entity(name, ctx, value)` | non-None + has `.id` + `.layers`. |
| `validate_entity_list(name, ctx, value)` | list/tuple of validatable entities. |
| `validate_finite_2tuple(name, ctx, value)` | length 2, all finite floats. |
| `validate_save_dir(name, ctx, value)` | `str` or `Path`, non-empty. |

These are not in the public `__all__` but their error contracts are
part of the manager's documented `Raises:` blocks.

## Compression layer

`residency.compression` exports four pure-function entry points:

| Function | Effect |
|---|---|
| `compress_array(arr)` | `arr.astype(float32).tobytes()` → LZ4 (level 0) if `lz4.frame` is importable, else zlib (level 1). |
| `decompress_array(data, shape, dtype=np.float32)` | Inverse; reshapes back to `shape`. |
| `compress_raw(data)` | Same LZ4-or-zlib path on already-`bytes` input. |
| `decompress_raw(data)` | Inverse of `compress_raw`. |

The fallback is silent — if `lz4` is missing the file just uses
zlib, both readable by either path. **Compression level 0 / 1 is
deliberate**: throughput dominates over size for streaming workloads.

## .slap binary format

Container for one or many serialised assets, written by
`write_world_slap` and read by `read_world_slap`. The single-asset
helpers (`write_asset_to_slap` / `read_asset_from_slap`) wrap the
world helpers with a length-1 list.

### Magic + version

```python
SLAP_MAGIC   = b"SLAP"
SLAP_VERSION = 1
```

`read_world_slap` raises `ValueError("Not a .slap file: bad magic …")`
or `ValueError("Unsupported .slap version: …")` on mismatch.

### File layout

```
+---- header (12 bytes) -----------------------------------------+
| magic   : 4s          ("SLAP")                                 |
| version : <I          (1)                                      |
| count   : <I          (number of assets)                       |
+---- directory (variable, one entry per asset) -----------------+
| name_len : <I                                                  |
| name     : utf-8 bytes (name_len)                              |
| offset   : <Q          (absolute file offset of the data block)|
+---- data blocks (one per asset, at the directory offsets) -----+
| meta_len   : <I                                                |
| meta       : JSON utf-8 — {name, position, size, z_order}      |
| layer_cnt  : <I                                                |
| layer[0..N] :                                                  |
|   visual_len : <I                                              |
|   visual     : PNG bytes (Pillow-encoded RGBA)                 |
|   struct_len : <I                                              |
|   struct     : LZ4/zlib(float32 pixel_data flattened)          |
|   meta_len   : <I                                              |
|   meta       : JSON utf-8 — {name, opacity, visible, size,     |
|                              channel_map}                      |
+----------------------------------------------------------------+
```

The directory is written **before** any data block so a reader can
seek straight to a named asset without parsing intermediate blocks
— useful for partial loads (e.g. residency promotion of a single
entity out of a 100-asset world save).

### Encoding details

- **Visual data** (`layer._image_data`) round-trips as a PNG embedded
  in the layer block; an empty layer encodes as a zero-length visual
  segment.
- **Pixel-struct data** (`layer._pixel_data` or `layer._data_array`)
  is flattened to `float32`, LZ4-compressed via `compress_array`, and
  reshaped on read using the `size` field from the layer meta (assumed
  to be `[width, height]`). The channel count is inferred from
  `pixel_data.size // (w*h)`.
- **Asset meta** captures `name`, `position`, `size`, `z_order`. Layer
  meta captures `name`, `opacity`, `visible`, `size`, `channel_map`.
- All length prefixes are little-endian `<I` (u32); offsets are
  little-endian `<Q` (u64).

### Reader contract

`read_world_slap(path) -> list[dict]` returns one dict per asset:

```python
{
  "name":     str,
  "position": [float, float],
  "size":     [int, int],
  "z_order":  int,
  "meta":     {...},                # the raw asset meta JSON
  "layers":   [
    {
      "name":        str,
      "opacity":     float,
      "visible":     bool,
      "size":        [int, int],
      "channel_map": dict,
      "image_data":  np.ndarray | None,   # H×W×4 uint8 RGBA, or None
      "pixel_data":  np.ndarray | None,   # H×W×C float32, or 1-D if size is missing
    },
    ...
  ],
}
```

`read_asset_from_slap` raises `ValueError("No assets found in …")` if
the file is well-formed but empty.

## Lifecycle

The engine constructs **one** `ResidencyManager` at startup
(`Engine._init_residency`) and forwards `Engine.tick()` →
`ResidencyManager.update(camera_pos, scene.entities)`. Games that
want manual control (e.g. Bullet Strata's checkpoint-on-save flow)
typically:

1. Call `mgr.evict_to_disk(entity)` for everything in the soon-to-be-
   unloaded zone.
2. Call `mgr.prefetch(entity)` for entities in the inbound zone
   *before* the camera teleport, so the GPU upload is amortised across
   the teleport frames.
3. Skip `mgr.update(...)` for the teleport frame itself — let the
   distance-based tiering re-stabilise on the next frame.

The `.slap` directory is rooted at the `save_dir` argument; one
manager per save slot avoids cross-contamination between
parallel world loads.

## Design notes

No separate `residency_design.md` ships — the architectural decisions
(three-tier GPU/RAM/DISK model with distance-based promotion, LZ4
compression level 0/1 chosen for throughput-over-size, directory-
first .slap layout so partial loads can seek straight to a named
asset, soft-fail readbacks that fall back to `_ram_pixel_data = None`)
are documented inline above.

If a future sprint adds streaming over the network, predictive
prefetch, or tier-specific budgets per-asset (rather than per-manager),
promote that material to a dedicated `residency_design.md` and link
both ways.

## See also

- [`gpu.md`](gpu.md) — `BufferManager` / `TextureManager` are the
  GPU-tier owners the residency manager hands eviction work to.
- [`compute.md`](compute.md) — compute-side readbacks share the same
  staging-buffer pattern.
