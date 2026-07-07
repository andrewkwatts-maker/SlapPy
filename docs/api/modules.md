<!-- handauthored: do not regenerate -->
# slappyengine.modules — API Reference

> Hand-written reference for the shipped pixel-struct extension modules.
> Each subclasses :class:`slappyengine.struct_registry.StructModule` to
> reserve a named block of channels in the packed per-pixel WGSL struct
> that drives the compute-shader per-pixel simulation. Sibling reference:
> [`compute.md`](compute.md) is the dispatch layer that consumes the
> assembled struct; the :class:`StructRegistry` that owns registration
> lives in `slappyengine.struct_registry`.

## Overview

`slappyengine.modules` is a small catalogue of the "batteries-included"
pixel-struct modules the engine ships with. The per-pixel simulation
runs on a single packed WGSL struct — one flat SoA record per pixel —
and each :class:`StructModule` subclass reserves a named block of
channels in that struct plus declares which compute passes it depends
on. New modules are opt-in and register themselves into a shared
:class:`StructRegistry` at startup; the registry then computes the WGSL
layout (offsets + stride) and locks itself before shader compile.

Every module ships with default channel values so entities that opt in
without explicitly initialising a field get a documented starting state
(e.g. `PhysicsModule` densities default to `1.0`, `HealthModule` health
to `1.0`).

## Public surface

```python
from slappyengine.modules import (
    FluidParamsModule,
    HealthModule,
    PhysicsModule,
    PixelPhysicsModule,
)
```

Lazy-loaded via the module-level `__getattr__` — importing
`slappyengine.modules` does **not** import the submodule for a module
class until you actually access its name.

## Module contract

Every entry below is a class-based :class:`StructModule` subclass with
four class attributes:

- `name: str` — logical namespace used in WGSL access (`p.health.hp`).
- `channels: list[tuple[str, str]]` — ordered `(field, wgsl_type)`
  pairs; types drawn from `f32`, `u32`, `i32`, `vec2f`, `vec3f`,
  `vec4f`.
- `compute_passes: list[str]` — compute-shader files that this module's
  channels feed into.
- `default_values: dict[str, float]` — initial value written per pixel
  at spawn.

There are no instance methods — the class object itself is the
metadata bundle registered into a :class:`StructRegistry`.

## Classes

### `FluidParamsModule`

_class — defined in `slappyengine.modules.fluid_params`_

Per-pixel PBF fluid parameters. Channels:

| Channel | WGSL | Default | Notes |
|---|---|---|---|
| `viscosity` | `f32` | `0.001` | Kinematic viscosity coefficient. |
| `pressure` | `f32` | `0.0` | Solved pressure field. |
| `divergence` | `f32` | `0.0` | Velocity divergence, driven by the projection pass. |
| `fluid_tag` | `u32` | `0` | Fluid type enum: `1=water`, `2=lava`, `3=gas`. |

Compute passes: `["fluid"]`.

### `HealthModule`

_class — defined in `slappyengine.modules.health`_

Per-pixel damage bookkeeping.

| Channel | WGSL | Default | Notes |
|---|---|---|---|
| `health` | `f32` | `1.0` | `0.0` = dead, `1.0` = full. |
| `max_health` | `f32` | `1.0` | Cap used for regen clamps. |
| `tag` | `u32` | `0` | Bitmask of pixel tags (per-project semantics). |

Compute passes: `["health_sum"]` — a reduction pass consumed by HUD
health-bar overlays.

### `PhysicsModule`

_class — defined in `slappyengine.modules.physics`_

Per-pixel rigid-body physical properties. Kept minimal on purpose;
callers that need the full velocity + friction + elasticity + phase
bundle should use :class:`PixelPhysicsModule` instead.

| Channel | WGSL | Default | Notes |
|---|---|---|---|
| `strength` | `f32` | `1.0` | Tensile strength. |
| `stiffness` | `f32` | `1.0` | Young's-modulus proxy. |
| `density` | `f32` | `1.0` | Mass per unit area. |
| `vel_x` | `f32` | `0.0` | Velocity X in pixels/sec. |
| `vel_y` | `f32` | `0.0` | Velocity Y in pixels/sec. |

Compute passes: `["rigid"]`.

### `PixelPhysicsModule`

_class — defined in `slappyengine.modules.pixel_physics`_

Full per-pixel physics record — packed to an 8-float / 32-byte layout
for GPU alignment. Use this instead of :class:`PhysicsModule` when the
project needs friction, elasticity, temperature, or state-transition
tracking.

| Channel | WGSL | Default | Notes |
|---|---|---|---|
| `vel_x` | `f32` | `0.0` | Pixel velocity X (px/s). |
| `vel_y` | `f32` | `0.0` | Pixel velocity Y (px/s). |
| `mass` | `f32` | `0.0` | `0` = static; `>0` = dynamic. |
| `friction` | `f32` | `0.0` | Surface friction `[0, 1]`. |
| `elasticity` | `f32` | `0.0` | Restitution `[0, 1]`. |
| `temperature` | `f32` | `0.0` | Kelvin; drives state transitions + emission. |
| `state` | `u32` | `0` | Material phase: `0=solid`, `1=liquid`, `2=gas`, `3=plasma`. |
| `_pad` | `u32` | `0` | 32-byte alignment padding — do not touch. |

Compute passes: `["pixel_physics"]`.

## Usage

```python
from slappyengine.modules import (
    FluidParamsModule, HealthModule,
    PhysicsModule, PixelPhysicsModule,
)
from slappyengine.struct_registry import StructRegistry

# Assemble a registry with two modules; the always-present `color`
# vec4f slot is added by StructRegistry itself.
reg = StructRegistry()
reg.register(HealthModule)
reg.register(PhysicsModule)

# Read back the packed WGSL layout.
assert reg.channel_offset("color") == 0        # always slot 0
assert reg.channel_offset("health") > 0
assert reg.stride_bytes() % 16 == 0            # 16-byte stride

# Lock before shader compile — subsequent register() calls will raise.
reg.lock()

# Inspect a module's declared metadata without registering it.
assert HealthModule.name == "health"
assert HealthModule.default_values["health"] == 1.0
assert "fluid" in FluidParamsModule.compute_passes

# PhysicsModule vs PixelPhysicsModule — pick one, not both:
# their channel sets overlap on vel_x / vel_y and StructRegistry will
# reject the second .register() with a ValueError.
```

## Skip the wrapper

`slappyengine.modules` is pure Python metadata — no runtime work.
Grep of `slappyengine._core_facade.RUST_MODULE_MAP` shows **no**
`modules` entry.

The `StructRegistry` that owns registration **does** call into the
Rust-backed WGSL layout computer:
:func:`slappyengine._core.struct_layout.compute_layout` (see
`RUST_MODULE_MAP["struct_layout"]` — `src/struct_layout.rs`). That
lookup is fast enough that the pure-Python fallback in
:meth:`StructRegistry._compute_layout` matches within a millisecond on
a laptop, so games that ship without the compiled `_core` still
assemble correct layouts.

Callers who want to bypass :class:`StructRegistry` and hand-assemble a
struct layout can call
:func:`slappyengine._core.struct_layout.compute_layout(channels)`
directly with an `[(name, wgsl_type), ...]` list — the module classes
here are just curated payloads for that call.

## Conventions

- **Class-based, not instance-based.** :class:`StructModule` subclasses
  are the metadata bundle; do not instantiate them.
- **One-shot registration.** :meth:`StructRegistry.register` must be
  called before :meth:`StructRegistry.lock`; after lock (invoked once
  during shader compile) further registrations raise `RuntimeError`.
- **Channel names are globally unique.** Two modules cannot expose a
  channel with the same name in the same registry —
  :meth:`StructRegistry.register` raises `ValueError` on collision.
- **Lazy import.** Every module class is loaded lazily via
  `__getattr__`; a project that only registers `HealthModule` does not
  pay the import cost of the other three.

## See also

- [`compute.md`](compute.md) — the dispatch layer that consumes the
  assembled per-pixel struct via named compute passes.
- [`../rust_migration_plan.md`](../rust_migration_plan.md) — Rust ROI
  reference; the metadata classes here are intentionally not on the
  migration roadmap. The WGSL layout compute *is* Rust-backed via
  `struct_layout.rs` (already landed).
- [`../feature_map_2026_06_03.md`](../feature_map_2026_06_03.md) — the
  compute + pixel-struct subsystem row in the engine feature map has
  the current per-module wiring status.
