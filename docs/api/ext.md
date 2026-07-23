<!-- handauthored: do not regenerate -->
# pharos_engine.ext — API Reference

> Hand-written reference for the optional-extensions subpackage.
> `ext` is the canonical home for the heavier / optional engine
> subpackages (iso, net, ai, animation, input, ui).
>
> **Note on the single-file modules.** Prior to v0.3 the ext namespace
> also carried thin re-export shims for four single-file modules
> (`ext.lighting`, `ext.fluid_sim`, `ext.angle_sprite`,
> `ext.split_screen`). Those shims were removed in the Sprint 3 dead-
> code purge. Import the canonical modules directly:
>
> ```python
> from pharos_engine.lighting     import LightingSystem, PointLight
> from pharos_engine.fluid_sim    import GlobalFluidSim
> from pharos_engine.angle_sprite import AngleSpriteMap
> from pharos_engine.split_screen import Viewport, SplitScreenManager
> ```

## Overview

`pharos_engine.ext` groups the optional / heavier **subpackages** — one
namespace where "everything that requires an extra dependency" lives, so
the ARCHITECTURE doc can point at one directory rather than several.
`__all__` lists six subpackage names:

```python
__all__ = [
    "iso", "net", "ai", "animation", "input", "ui",
]
```

`__all__` lists module names, not symbols — `from pharos_engine.ext
import *` gives you the subpackages. The actual classes / functions
live one level deeper.

## Canonical single-file modules (importable directly)

These live at the top of `pharos_engine`, not under `.ext.`:

### `pharos_engine.lighting` — GPU lighting system

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

### `pharos_engine.fluid_sim` — global fluid simulation

The **Eulerian / global** fluid path (not the PBF particle sim under
`pharos_engine.fluid`, which is a separate subpackage — see
[`fluid_design.md`](../fluid_design.md)).

| Symbol | Role |
|---|---|
| `FluidSimConfig` | Dataclass: viscosity, dissipation, advection scheme, voxel grid size. |
| `GlobalFluidSim` | Step / render driver. One per scene. |
| `fog_config()` | Pre-tuned `FluidSimConfig` for ground fog. |
| `water_config()` | Pre-tuned `FluidSimConfig` for shallow water. |
| `smoke_config()` | Pre-tuned `FluidSimConfig` for combat smoke. |

### `pharos_engine.angle_sprite` — angle-blended sprites

| Symbol | Role |
|---|---|
| `AngleEntry` | One discrete facing angle + its sprite frame. |
| `AngleSpriteMap` | Maps a continuous facing angle to the nearest discrete sprite (with optional blend). |
| `make_angle_map_from_spritesheet(path, angle_count, …)` | Slice a strip-sheet into N evenly-spaced angle entries. |

Requires Pillow (in the base install). Used by `pharos_engine.iso` for
per-viewpoint sprite swapping on camera rotation.

### `pharos_engine.split_screen` — N-player split screen

| Symbol | Role |
|---|---|
| `Viewport` | Camera + screen rect for one local player. |
| `SplitScreenManager` | Lays N viewports out (1×1, 1×2, 2×2, …) and dispatches input per-viewport. |

Pure-CPU; no extras required.

## Subpackage catalogue (under `pharos_engine.ext`)

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
`InputManager`, gamepad+keyboard providers.

### `ext.ui` — editor UI

Re-exports `pharos_editor.ui`. The `ext.ui.editor` sub-shim re-exports
`pharos_editor.ui.editor` (full surface in [`ui_editor.md`](ui_editor.md))
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
`ModuleNotFoundError` the first time the missing dependency is touched.

## Design notes

No separate `ext_design.md` ships — `ext` is a namespace grouping the
optional / heavier subpackages, not a substantive subpackage of its
own. For the canonical modules behind each subpackage, follow the
linked design docs in the per-module catalogue (`ext.iso` →
[`iso.md`](iso.md); `ext.animation` → [`animation.md`](animation.md);
etc.).
