<!-- handauthored: do not regenerate -->
# pharos_engine.ext — API Reference

> Hand-written reference for the optional-extensions subpackage.
> `ext` is the canonical home for the heavier / optional engine modules
> (lighting, fluid, animation, networking, AI tooling, editor UI…).
> Every module here is a thin **re-export shim** over a canonical
> top-level module — both paths work, and downstream games may freely
> mix them.

```python
# Both of these resolve to the same symbols:
from pharos_engine.ext.lighting import LightingSystem, PointLight
from pharos_engine.lighting     import LightingSystem, PointLight
```

## Overview

The shim layout exists for two reasons:

1. It gives the engine a single namespace (`pharos_engine.ext`) where
   "everything that requires an extra dependency" lives, so the
   ARCHITECTURE doc can point at one directory rather than nine.
2. It preserves the long-standing import paths consumed by
   **Ochema Circuit** and **Bullet Strata** while the engine
   internally repackages modules. The memory note
   `project_editor_sprint.md` calls this out: the shims add ~zero bytes
   to the wheel and are load-bearing for back-compat — do not delete.

`pharos_engine.ext.__all__` lists ten names, one per subordinate module
or subpackage:

```python
__all__ = [
    "lighting", "fluid_sim", "angle_sprite", "split_screen",
    "iso", "net", "ai", "animation", "input", "ui",
]
```

`__all__` lists module names, not symbols — `from pharos_engine.ext
import *` gives you the modules. The actual re-exported classes /
functions live one level deeper.

## Module-by-module catalogue

### `ext.lighting` — GPU lighting system

Pure re-export of `pharos_engine.lighting`. Surface:

| Symbol | Role |
|---|---|
| `LightingSystem` | Deferred accumulation pipeline; clear → per-light add → combine → blit. Wired into the engine draw loop. |
| `DirectionalLight` | Sun-style infinite light; CSM shadow map. |
| `PointLight` | Spherical falloff; Karis attenuation. |
| `ConeLight` | Spot / projector light with inner+outer cone. |
| `ShapeLight` | Polygonal area light. |
| `FlashLight` | Brief one-frame burst — reuses the point-light pool. |
| `GravityWarpSource` | Lensing distortion source (post-process input). |
| `RadianceCascadeConfig` | Per-cascade tuning for the radiance-cascade GI path. |

Requires wgpu; safe to import without a GPU but the dispatch methods
will raise on first use. See [`gi.md`](gi.md) for the compute side of
the lighting kernels.

### `ext.fluid_sim` — global fluid simulation

Re-exports the **Eulerian / global** fluid path (not the PBF particle
sim under `pharos_engine.fluid`, which is a separate subpackage —
see [`fluid_design.md`](../fluid_design.md)).

| Symbol | Role |
|---|---|
| `FluidSimConfig` | Dataclass: viscosity, dissipation, advection scheme, voxel grid size. |
| `GlobalFluidSim` | Step / render driver. One per scene. |
| `fog_config()` | Pre-tuned `FluidSimConfig` for ground fog. |
| `water_config()` | Pre-tuned `FluidSimConfig` for shallow water. |
| `smoke_config()` | Pre-tuned `FluidSimConfig` for combat smoke. |

Both the `ext.fluid_sim` shim and the canonical `pharos_engine.fluid_sim`
module are off-limits to the constraint in the sprint brief — do **not**
edit these. Documenting the surface is fine; the docs reference the
public-API contract rather than reaching into implementation.

### `ext.angle_sprite` — angle-blended sprites

Re-exports `pharos_engine.angle_sprite`.

| Symbol | Role |
|---|---|
| `AngleEntry` | One discrete facing angle + its sprite frame. |
| `AngleSpriteMap` | Maps a continuous facing angle to the nearest discrete sprite (with optional blend). |
| `make_angle_map_from_spritesheet(path, angle_count, …)` | Slice a strip-sheet into N evenly-spaced angle entries. |

Requires Pillow (in the base install). Used by `pharos_engine.iso` for
per-viewpoint sprite swapping on camera rotation.

### `ext.split_screen` — N-player split screen

Re-exports `pharos_engine.split_screen`.

| Symbol | Role |
|---|---|
| `Viewport` | Camera + screen rect for one local player. |
| `SplitScreenManager` | Lays N viewports out (1×1, 1×2, 2×2, …) and dispatches input per-viewport. |

Pure-CPU; no extras required.

### `ext.iso` — isometric rendering

`from pharos_engine.iso import *` (subpackage shim). The full surface is
documented in [`iso.md`](iso.md) — `IsoViewpoint`, `IsoTileDef`,
`IsoCell`, `IsoGrid`, `IsoEntity`, `IsoCamera`, `IsoScene`, plus the
`iso.combat` Stone Keep module. The shim re-uses the canonical
`__all__`, so a star-import picks up every public name.

### `ext.net` — P2P networking

Requires the `[network]` extra. Re-exports `pharos_engine.net`. The
surface is small (matchmaking + reliable-UDP transport + ack ledger);
see the source for details — it has not had a hand-authored API ref
yet (deferred).

### `ext.ai` — AI code tools

Requires the `[ai]` extra (Ollama + tree-sitter). Re-exports
`pharos_engine.ai`:

| Symbol | Role |
|---|---|
| `OllamaManager` | Local-LLM lifecycle (start / stop / health check). |
| `LLMClient` | Chat-style request/response client over Ollama. |
| `CodeSync` | Round-trips scripts between disk and live engine. |
| `ScriptGen` | Templated script-from-prompt generation. |

Per memory `project_editor_sprint.md` this is the back-end for the
editor's "Code Mode" panel.

### `ext.animation` — full animation system

Re-exports `pharos_engine.animation`. Surface documented in
[`animation.md`](animation.md): `AnimationGraph`, `AnimState`,
`AnimTransition`, `AnimUpdate`, `ProceduralRig`, `ControlPoint`. The
`[video]` extra unlocks the video-frame importer (`AnimationGraph
.from_video(path)`).

### `ext.input` — action-map / bindings layer

Re-exports `pharos_engine.input`. Subpackage with `ActionMap`,
`InputManager`, gamepad+keyboard providers. The top-level
`pharos_engine.input` shim survives for older imports; the canonical
path is `pharos_engine.input` for now.

### `ext.ui` — editor UI

Re-exports `pharos_engine.ui`. The `ext.ui.editor` sub-shim re-exports
`pharos_engine.ui.editor` (full surface in [`ui_editor.md`](ui_editor.md))
and requires the `[editor]` extra (PyQt6 + qtawesome) before any
class is instantiated — importing the module is cheap, instantiating
`EditorShell` is not.

## Extras matrix

| Extra | Modules unlocked |
|---|---|
| (base) | `lighting`, `fluid_sim`, `angle_sprite`, `split_screen`, `iso`, `input`, `animation` (basic) |
| `[network]` | `net` |
| `[ai]` | `ai` |
| `[editor]` | `ui.editor` |
| `[video]` | `animation.from_video` (video-frame import) |

Importing any module without its extra produces a clear
`ModuleNotFoundError` the first time the missing dependency is touched;
the shim itself never raises on import.

## Stability guarantee

The `ext` re-export shims are part of the **stable** API surface
covered by the v0.3 contract — renaming a canonical module is a
breaking change unless the `ext` shim continues to point at the new
location. See `docs/sprint_1_game_compat_2026_05_30.md` for the
contract check that runs against Ochema Circuit and Bullet Strata on
every release.

## Design notes

No separate `ext_design.md` ships — `ext` is a re-export namespace,
not a substantive subpackage. The design (one namespace for
"everything that requires an extra dependency", load-bearing back-
compat for Ochema / Bullet Strata import paths, ~zero wheel-size cost
because every entry is a thin shim) is documented inline above.

For the canonical modules behind each shim, follow the linked design
docs in the per-module catalogue (`ext.lighting` → `lighting`
internals; `ext.iso` → [`../api/iso.md`](iso.md); `ext.animation` →
[`animation.md`](animation.md); etc.).
