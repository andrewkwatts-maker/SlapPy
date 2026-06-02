# SlapPyEngine v0.3 — Engine Surface Reference

> Auto-generated from runtime introspection of `slappyengine.__all__` and the
> `_subpackages` set declared in `python/slappyengine/__init__.py`.
> **Do not hand-edit.** Re-run `python scripts/gen_engine_surface_doc.py` to
> refresh after surface changes.

v0.3 is the first "Rust engine, Python wrapper" release. Hot paths are
native; Python is glue, ergonomics, and config. Ships on PyPI as
`slappy-engine`.

* Engine version (runtime): `0.3.0b0`
* Native `_core` available: `True`
* Top-level names in `__all__`: **75**
* Declared subpackages: **21**


## Top-level surface (`import slappyengine`)

Every name below is reachable as `slappyengine.<Name>`. Module column is relative to `slappyengine.`. Signatures shown where introspectable.

### Core (entity / scene / engine)

| Name | Kind | Module | Signature | Description |
|---|---|---|---|---|
| `Camera` | class | `camera` | `(position: 'tuple[float, float]' = (0.0, 0.0), zoom: 'float' = 1.0)` |  |
| `Engine` | class | `engine` | `(config_path: 'str | None' = None, **overrides)` |  |
| `Entity` | class | `entity` | `(name: str = '', position: tuple[float, float] = (0.0, 0.0))` |  |
| `Scene` | class | `scene` | `(name: 'str' = 'Scene')` |  |
| `engine_config` | function | `config` | `(path: 'str | None' = None) -> 'Config'` | Return the module-level singleton :class:`Config`. |

### Scripting

| Name | Kind | Module | Signature | Description |
|---|---|---|---|---|
| `Script` | class | `script` | `()` | Base class for entity behaviour scripts. |
| `ScriptComponent` | class | `script` | `()` | Script that is also a Component — can be added via entity.add_component(). |

### Components

| Name | Kind | Module | Signature | Description |
|---|---|---|---|---|
| `CollisionComponent` | class | `components` | `(shape=None, layer: 'int' = 0, mask: 'int' = 65535, on_collide: "'Callable | None'" = N...` | Collision shape registration component. |
| `Component` | class | `components` | `(*args, **kwargs)` | Structural protocol for all components. |
| `ComponentBase` | class | `components` | `()` | No-op base class for components. |
| `DataComponent` | class | `data_component` | `(**fields: 'Any') -> 'None'` | Generic key-value data store with reactive field watchers. |
| `PhysicsComponent` | class | `components` | `(velocity: 'tuple[float, float]' = (0.0, 0.0), gravity_scale: 'float' = 1.0) -> 'None'` | Simple 2-D kinematic physics component. |

### Events & data

| Name | Kind | Module | Signature | Description |
|---|---|---|---|---|
| `EventBus` | class | `event_bus` | `() -> 'None'` | Lightweight synchronous pub-sub event bus. |

### Physics & collision

| Name | Kind | Module | Signature | Description |
|---|---|---|---|---|
| `AABBShape` | dataclass | `collision` | `(width: 'float', height: 'float', offset_x: 'float' = 0.0, offset_y: 'float' = 0.0) -> ...` | AABBShape(width: 'float', height: 'float', offset_x: 'float' = 0.0, offset_y: 'float' = 0.0) |
| `CircleShape` | dataclass | `collision` | `(radius: 'float', offset_x: 'float' = 0.0, offset_y: 'float' = 0.0) -> None` | CircleShape(radius: 'float', offset_x: 'float' = 0.0, offset_y: 'float' = 0.0) |
| `CollisionManager` | class | `collision` | `() -> 'None'` | Backwards-compatible façade that exposes the spec-requested API |
| `CollisionWorld` | class | `collision` | `()` | Broad-phase AABB/Circle collision world. |

### Fluid simulation

| Name | Kind | Module | Signature | Description |
|---|---|---|---|---|
| `FluidSimConfig` | dataclass | `fluid_sim` | `(pad_pixels: 'int' = 64, lod_mode: 'str' = 'exp', lod_zones: 'int' = 4, viscosity: 'flo...` | All parameters that define a fluid type and simulation fidelity. |
| `GlobalFluidSim` | class | `fluid_sim` | `(gpu: "'GPUContext'", screen_w: 'int', screen_h: 'int', cfg: 'FluidSimConfig | None' = ...` | Scene-wide fluid simulation running in GPU world space. |

### Lighting

| Name | Kind | Module | Signature | Description |
|---|---|---|---|---|
| `ConeLight` | dataclass | `lighting` | `(position: 'tuple[float, float]' = (0.0, 0.0), direction: 'tuple[float, float]' = (1.0,...` | Spotlight / vehicle headlight. Illuminates a cone sector. |
| `DirectionalLight` | dataclass | `lighting` | `(direction: 'tuple[float, float]' = (0.707, 0.707), elevation: 'float' = 0.785, color: ...` | Sun/moon light. Casts parallel shadows using Z-height offset. |
| `FlashLight` | dataclass | `lighting` | `(position: 'tuple[float, float]' = (0.0, 0.0), radius: 'float' = 80.0, color: 'tuple[fl...` | Short-lived point burst — muzzle flash, explosion. Auto-removed when expired. |
| `LightingSystem` | class | `lighting` | `(gpu: "'GPUContext'", width: 'int', height: 'int')` | Manages all scene lights and dispatches the lighting compute pipeline each frame. |
| `PointLight` | dataclass | `lighting` | `(position: 'tuple[float, float]' = (0.0, 0.0), z: 'float' = 100.0, radius: 'float' = 20...` | Radial light with Z height for 3D distance attenuation. |

### Layers

| Name | Kind | Module | Signature | Description |
|---|---|---|---|---|
| `Layer` | class | `layer` | `(name: 'str' = 'Layer', mode: 'str' = '2D')` |  |
| `Layer2D` | class | `layer` | `(name: 'str' = 'layer', width: 'int' = 64, height: 'int' = 64)` | Layer subclass for 2D pixel-art rendering. mode is always '2D'. |
| `Layer3D` | class | `layer` | `(name: 'str' = 'layer')` | Layer subclass for 3D mesh rendering. mode is always '3D'. |
| `LayerDataBuffer` | class | `layer` | `(name: 'str', width: 'int', height: 'int', struct_fields: 'list[str]')` | Layer2D that also carries per-pixel struct data for compute shaders. |

### Landscape & tiles

| Name | Kind | Module | Signature | Description |
|---|---|---|---|---|
| `Landscape` | class | `landscape` | `(tile_size: 'int' = 256, tile_dir: 'str | Path' = '.', cache_size: 'int | None' = None)...` |  |
| `Tile` | class | `landscape` | `(coord: 'TileCoord', tile_size: 'int') -> 'None'` |  |
| `TileCoord` | class | `landscape` | `(x: 'int', y: 'int') -> 'None'` |  |

### Asset residency & streaming

| Name | Kind | Module | Signature | Description |
|---|---|---|---|---|
| `ResidencyManager` | class | `residency.manager` | `(ctx=None, buf_mgr=None, tex_mgr=None, save_dir: 'str | Path' = '.')` |  |

### Assets

| Name | Kind | Module | Signature | Description |
|---|---|---|---|---|
| `Asset` | class | `asset` | `(name: 'str' = '', position=(0.0, 0.0), size=(64, 64))` |  |
| `AssetDatabase` | class | `assets.database` | `()` | Singleton asset registry. Call AssetDatabase.instance() to get the shared instance. |

### Rendering

| Name | Kind | Module | Signature | Description |
|---|---|---|---|---|
| `CubeArray` | class | `cube_array` | `(name: str = '', position=(0.0, 0.0), size=(64, 64))` |  |
| `RenderTarget` | class | `render_target` | `(name: str = '', position=(0.0, 0.0), size=(64, 64))` |  |

### Post-processing

| Name | Kind | Module | Signature | Description |
|---|---|---|---|---|
| `PostProcessChain` | class | `post_process.chain` | `()` | Ordered chain of post-process compute passes. Fully wired in M10. |
| `PostProcessPass` | dataclass | `post_process.chain` | `(shader_path: 'str', params: 'dict' = None, label: 'str' = '', enabled: 'bool' = True, ...` | PostProcessPass(shader_path: 'str', params: 'dict' = None, label: 'str' = '', enabled: 'bool' = True,... |

### UI

| Name | Kind | Module | Signature | Description |
|---|---|---|---|---|
| `SceneUIEntity` | class | `ui.scene_ui` | `(name: 'str' = 'UI', position=(0.0, 0.0), size=(200, 100))` |  |
| `draw_stat_bar` | function | `ui.hud_widgets` | `(draw: "'ImageDraw'", x: 'int', y: 'int', w: 'int', h: 'int', value: 'float', max_value...` | Draw a filled stat bar (HP, energy, armour, etc.) onto a PIL ImageDraw. |

### Animation

| Name | Kind | Module | Signature | Description |
|---|---|---|---|---|
| `AnimState` | dataclass | `animation.graph` | `(name: 'str', clip_indices: 'list[int]' = <factory>, loop: 'bool' = True, fps: 'float' ...` | AnimState(name: 'str', clip_indices: 'list[int]' = <factory>, loop: 'bool' = True, fps: 'float' = 24.0) |
| `AnimTransition` | dataclass | `animation.graph` | `(from_state: 'str', to_state: 'str', condition: 'Callable[[], bool]' = <function AnimTr...` | AnimTransition(from_state: 'str', to_state: 'str', condition: 'Callable[[], bool]' = <function... |
| `AnimUpdate` | dataclass | `animation.graph` | `(state_name: 'str', frame_index: 'int', blend_fraction: 'float') -> None` | AnimUpdate(state_name: 'str', frame_index: 'int', blend_fraction: 'float') |
| `AnimationGraph` | class | `animation.graph` | `()` |  |
| `ControlPoint` | dataclass | `animation.procedural` | `(name: 'str', uv: 'tuple[float, float]', parent: 'str | None' = None, constraint: 'str'...` | ControlPoint(name: 'str', uv: 'tuple[float, float]', parent: 'str | None' = None, constraint: 'str' =... |
| `ProceduralRig` | class | `animation.procedural` | `()` | Dot-based procedural rigging. IK solver implemented in M7 (Rust). |

### Materials

| Name | Kind | Module | Signature | Description |
|---|---|---|---|---|
| `AddNode` | function | `material.node_material` | `() -> 'NodeDef'` |  |
| `ClampNode` | function | `material.node_material` | `(min_val: 'float' = 0.0, max_val: 'float' = 1.0) -> 'NodeDef'` |  |
| `ColorRange` | dataclass | `material.map` | `(r: 'tuple[int, int]' = (0, 255), g: 'tuple[int, int]' = (0, 255), b: 'tuple[int, int]'...` | ColorRange(r: 'tuple[int, int]' = (0, 255), g: 'tuple[int, int]' = (0, 255), b: 'tuple[int, int]' = (0, 255)) |
| `DiscardNode` | function | `material.node_material` | `() -> 'NodeDef'` |  |
| `FinalColorNode` | function | `material.node_material` | `() -> 'NodeDef'` |  |
| `GravityWarpNode` | function | `material.node_material` | `(strength: 'float' = 2.0, radius: 'float' = 0.3) -> 'NodeDef'` |  |
| `LerpNode` | function | `material.node_material` | `() -> 'NodeDef'` |  |
| `MaterialDef` | dataclass | `material.map` | `(name: 'str', color_range: 'ColorRange', alpha_meaning: 'str' = 'opacity', behaviors: '...` | MaterialDef(name: 'str', color_range: 'ColorRange', alpha_meaning: 'str' = 'opacity', behaviors:... |
| `MaterialMap` | class | `material.map` | `()` |  |
| `MultiplyNode` | function | `material.node_material` | `() -> 'NodeDef'` |  |
| `NodeDef` | dataclass | `material.node_material` | `(node_type: 'str', params: 'dict', id: 'str' = <factory>) -> None` | NodeDef(node_type: 'str', params: 'dict', id: 'str' = <factory>) |
| `NodeMaterial` | class | `material.node_material` | `(name: 'str')` |  |
| `PixelChannelNode` | function | `material.node_material` | `(channel: 'str') -> 'NodeDef'` |  |
| `PixelColorNode` | function | `material.node_material` | `() -> 'NodeDef'` |  |
| `SampleTextureNode` | function | `material.node_material` | `() -> 'NodeDef'` |  |
| `UVNode` | function | `material.node_material` | `() -> 'NodeDef'` |  |

### SDF & 3D

| Name | Kind | Module | Signature | Description |
|---|---|---|---|---|
| `PbrMaterial` | dataclass | `gpu.pbr_material` | `(metallic: 'float' = 0.0, roughness: 'float' = 0.5, albedo_color: 'tuple[float, float, ...` | PbrMaterial(metallic: 'float' = 0.0, roughness: 'float' = 0.5, albedo_color: 'tuple[float, float, float,... |
| `SdfCanvas` | class | `sdf_shapes` | `(layer) -> 'None'` | Accumulate 2-D SDF shapes and render them into a layer texture. |
| `SdfExtruder` | class | `gpu.sdf_extruder` | `(gpu=None) -> 'None'` | Converts a 2D pixel mask into a GpuMesh using GPU extrusion. |

### Angle sprites

| Name | Kind | Module | Signature | Description |
|---|---|---|---|---|
| `AngleEntry` | dataclass | `angle_sprite` | `(angle_deg: 'float', layer_index: 'int', state_tag: 'str' = '') -> None` | One keyframe in the angle blend space. |
| `AngleSpriteMap` | dataclass | `angle_sprite` | `(blend_mode: 'str' = 'lerp', entries: 'list[AngleEntry]' = <factory>) -> None` | Maps rotation angles to sprite layers with optional lerp blending. |
| `make_angle_map_from_spritesheet` | function | `angle_sprite` | `(num_angles: 'int', layer_start: 'int' = 0, blend_mode: 'str' = 'lerp', angle_offset: '...` | Convenience: create an AngleSpriteMap for num_angles equally-spaced viewpoints. |

### Input

| Name | Kind | Module | Signature | Description |
|---|---|---|---|---|
| `ActionMap` | dataclass | `input.action_map` | `(player_id: 'int', _bindings: 'dict[str, str]' = <factory>, _reverse: 'dict[str, list[s...` | Maps string action names to key names for one player. |

### Split-screen

| Name | Kind | Module | Signature | Description |
|---|---|---|---|---|
| `SplitScreenManager` | class | `split_screen` | `(screen_w: 'int', screen_h: 'int', num_players: 'int', cameras: 'list | None' = None) -...` | Divides the window into N player viewports. |
| `Viewport` | dataclass | `split_screen` | `(player_id: 'int', x: 'int', y: 'int', width: 'int', height: 'int', camera: 'Any', bord...` | One player's screen region, in pixel coordinates. |

### Other

| Name | Kind | Module | Signature | Description |
|---|---|---|---|---|
| `BlurPass` | function | `(top-level)` | `(radius: 'int' = 2)` | Return a :class:`PostProcessPass` configured for blur. |
| `HAS_NATIVE` | constant |  |  | Returns True when the argument is true, False otherwise. |
| `OutlinePass` | function | `(top-level)` | `(color=(1.0, 0.0, 0.0, 1.0), threshold=0.1)` | Return a :class:`PostProcessPass` configured for outline rendering. |
| `PixelatePass` | function | `(top-level)` | `(block_size: 'int' = 4)` | Return a :class:`PostProcessPass` configured for pixelation. |

## Subpackages

These are the modules exposed via `slappyengine.__getattr__` — accessing `slappyengine.<name>` lazy-imports them. Each row lists the public attributes currently exposed by the subpackage and its inner modules.

### `slappyengine.ai`

AI subpackage — lazy-loaded (requires [ai] extra: httpx).

**Public attributes:** _(none exposed at package level)_

**Inner modules:** `code_sync`, `llm_client`, `ollama_manager`, `script_gen`

### `slappyengine.animation`

Animation subpackage — lazy-loaded.

**Public attributes:** `graph`, `procedural`

**Inner modules:** `graph`, `procedural`, `video_import`

### `slappyengine.assets`

**Public attributes:** `database`

**Inner modules:** `_validation`, `database`

### `slappyengine.audio_runtime`

audio_runtime — internal plumbing around the `sounddevice` backend.

**Public attributes:** `Any`, `AudioBackend`, `Protocol`, `get_backend`, `logging`, `np`

### `slappyengine.compute`

Compute subpackage — lazy-loaded to avoid eager wgpu/numpy imports.

**Public attributes:** `asset_compute`, `mutator`, `pipeline`, `readback`, `spatial`, `stats`

**Inner modules:** `asset_compute`, `ast_compiler`, `effect`, `hull`, `library`, `mutator`, `pipeline`, `readback`, `shader_cache`, `spatial`, `stats`, `wgsl_chunks`

### `slappyengine.dynamics`

Unified dynamics primitives layered on top of the XPBD substrate.

**Public attributes:** `Body`, `BoneSpec`, `Humanoid`, `IKChainSpec`, `JointSpec`, `KIND_PARAM_KEYS`, `LAYER_BONE`, `LAYER_MUSCLE`, `LAYER_SKIN`, `Material`, `MotorSpec`, `OVERDAMPING_THRESHOLD`, `RagdollSpec`, `RopeSpec`, `SCHEMA_VERSION`, `SoftBodyWorld`, `SpringSpec`, `World`, `body`, `build_ragdoll`, `build_rope`, `estimate_effective_damping`, `humanoid`, `ik`, `joint`, `load_world`, `make_humanoid`, `make_motor`, `make_spring`, `material`, `motor`, `place_feet_on_terrain`, `ragdoll`, `resolve_joint`, `rope`, `save_world`, `serialize`, `solve_ik`, `spring`, `world`, `world_from_dict`, `world_to_dict`, `wrap_in_flesh`

**Inner modules:** `_validation`, `body`, `humanoid`, `ik`, `joint`, `material`, `motor`, `ragdoll`, `rope`, `serialize`, `spring`, `world`

### `slappyengine.ext`

SlapPyEngine.ext — optional extension modules.

**Public attributes:** _(none exposed at package level)_

**Inner modules:** `ai`, `angle_sprite`, `animation`, `fluid_sim`, `input`, `iso`, `lighting`, `net`, `split_screen`, `ui`

### `slappyengine.gpu`

GPU subpackage — lazy-loaded to avoid eager wgpu imports.

**Public attributes:** `buffer_manager`, `context`, `entity_renderer`, `pbr_material`, `render_pipeline`, `sdf_extruder`, `texture_manager`

**Inner modules:** `adaptive_quality`, `buffer_manager`, `cluster_3d`, `cluster_pipeline`, `context`, `entity_renderer`, `ibl`, `material_buffer`, `mesh`, `mesh_pipeline`, `mesh_renderer`, `pbr_material`, `render_pipeline`, `sdf_extruder`, `sdf_renderer`, `texture_manager`

### `slappyengine.input`

SlapPyEngine.input

**Public attributes:** `ActionMap`, `InputManager`, `action_map`

**Inner modules:** `_manager`, `_validation`, `action_map`

### `slappyengine.iso`

SlapPyEngine.iso — Isometric 2D-grid-with-Z rendering subsystem.

**Public attributes:** `IsoCamera`, `IsoCell`, `IsoEntity`, `IsoGrid`, `IsoScene`, `IsoTileDef`, `IsoViewpoint`, `iso_camera`, `iso_entity`, `iso_grid`, `iso_scene`, `projection`

**Inner modules:** `_validation`, `combat`, `iso_camera`, `iso_entity`, `iso_grid`, `iso_scene`, `projection`

### `slappyengine.material`

Material subpackage — lazy-loaded.

**Public attributes:** `map`, `node_material`

**Inner modules:** `graph_schema`, `map`, `node_material`

### `slappyengine.modules`

Modules subpackage — lazy-loaded.

**Public attributes:** _(none exposed at package level)_

**Inner modules:** `fluid_params`, `health`, `physics`, `pixel_physics`

### `slappyengine.numerics`

Generic numerical primitives.

**Public attributes:** `compute_residual`, `np`, `sor_smooth`, `validate_2d_array`, `validate_matching_shape`, `validate_omega`, `validate_positive_float`, `validate_positive_int`, `vcycle_poisson`

**Inner modules:** `_validation`

### `slappyengine.post_process`

Post-process subpackage — lazy-loaded to avoid eager wgpu imports.

**Public attributes:** `chain`

**Inner modules:** `_validation`, `auto_exposure`, `bloom`, `chain`, `dof`, `executor`, `gtao`, `motion_blur`, `outline`, `preset_chains`, `shadow_csm`, `ssr`, `taa`, `tonemap`, `vignette`, `volumetric_fog`

### `slappyengine.residency`

Residency subpackage — lazy-loaded to avoid eager imports.

**Public attributes:** `manager`

**Inner modules:** `_validation`, `compression`, `manager`, `slap_format`

### `slappyengine.telemetry`

slappyengine.telemetry

**Public attributes:** `Any`, `Callable`, `Deque`, `Dict`, `List`, `Optional`, `TelemetryEvent`, `Tuple`, `clear_history`, `dataclass`, `deque`, `emit`, `enable_pattern_index`, `field`, `fnmatch`, `get_event_history`, `is_pattern_index_enabled`, `set_history_capacity`, `subscribe`, `threading`, `time`, `unsubscribe`, `validate_bool`, `validate_callable`, `validate_non_negative_int`, `validate_str`

**Inner modules:** `_validation`

### `slappyengine.testing`

slappyengine.testing — visual regression harness.

**Public attributes:** `Any`, `BASELINES_DIR`, `DIFF_DIR`, `Path`, `assert_scene_matches`, `diff_pngs`, `logging`, `np`, `render_scene_to_png`, `validate_baseline_name`, `validate_non_negative_float`, `validate_non_negative_int`, `validate_pathlike`, `validate_positive_int`, `validate_tolerance`

**Inner modules:** `_validation`

### `slappyengine.thermal`

Heat diffusion + pairwise heat exchange — Phase B public surface.

**Public attributes:** `HeatField`, `Iterable`, `Tuple`, `exchange_two_regions`, `math`, `np`, `validate_diffusivity`, `validate_finite_float`, `validate_grid_2d_float`, `validate_non_negative_float`, `validate_positive_float`, `validate_positive_int`

**Inner modules:** `_validation`

### `slappyengine.tools`

**Public attributes:** _(none exposed at package level)_

**Inner modules:** `_sprite_audit_validation`, `audio_tools`, `gen_placeholders`, `sprite_audit`, `sprite_tools`, `texture_tools`, `track_tools`, `video`

### `slappyengine.ui`

UI subpackage — lazy-loaded to avoid eager numpy/wgpu imports.

**Public attributes:** `hud_widgets`, `scene_ui`

**Inner modules:** `debug_overlay`, `editor`, `html_overlay`, `hud_widgets`, `project_manager`, `scene_ui`, `widgets`

### `slappyengine.zones`

slappyengine.zones — Generic zone primitives.

**Public attributes:** `Any`, `Callable`, `EnterExitCallback`, `EntityId`, `Hashable`, `Iterable`, `Position`, `RectZone`, `ThresholdCallback`, `ThresholdZone`, `ZoneManager`, `dataclasses`, `validate_finite_float`, `validate_non_negative_float`, `validate_positive_float`

**Inner modules:** `_validation`

## Stability notes

### Stable (v0.3 — committed contract)

- The 75 top-level lazy exports listed above.
- The 21 declared subpackages: `ai`, `animation`, `assets`, `audio_runtime`, `compute`, `dynamics`, `ext`, `gpu`, `input`, `iso`, `material`, `modules`, `numerics`, `post_process`, `residency`, `telemetry`, `testing`, `thermal`, `tools`, `ui`, `zones`.

### Beta (may evolve)

- Anything inside a subpackage that is **not** re-exported at the top level. Subpackage internals may move between point releases; pin a specific `slappy-engine` version if you rely on them directly.
- `slappyengine.ext.*` — back-compat shim namespace; superseded by the top-level lazy exports.

### Deprecated (kept for back-compat, will be removed)

- Anything not present in `__all__` or `_subpackages`. Old modules live on disk for migration but are not part of the contract.

## Getting started

```python
import slappyengine as sle

engine = sle.Engine(title="My Game", width=640, height=360)
layer = engine.add_layer("world", sle.Layer2D(tile_size=16))
engine.run()
```

See the `SlapPyEngineExamples/examples/` directory for runnable scenes that exercise the surface above (hello world, lighting, physics, layered character, multiplayer, HUD, landscape, baking, 3D layers, editor).

## Game integration tripwires

Downstream games (e.g. Ochema Circuit, Bullet Strata) pin the names they import from this engine. When a game ships against a new engine name, add a tripwire test that asserts the name remains importable — removing any locked name breaks that game.

Today the locked names are simply everything in `slappyengine.__all__` plus the declared subpackages, both of which are exercised by `SlapPyEngineTests/tests/test_docs_engine_surface_complete.py`.

<!-- BEGIN: AUTO-GENERATED SUBPACKAGE API LINKS -->

## Per-subpackage API references

The following per-subpackage reference docs are auto-generated by `scripts/gen_subpackage_api_docs.py`. Each one lists every public class / function / constant with full signatures and parsed `Raises:` sections — paste one into an LLM prompt to get accurate context for that subpackage.

- [`slappyengine.dynamics`](api/dynamics.md)
- [`slappyengine.zones`](api/zones.md)
- [`slappyengine.topology`](api/topology.md)
- [`slappyengine.numerics`](api/numerics.md)
- [`slappyengine.thermal`](api/thermal.md)
- [`slappyengine.iso`](api/iso.md)
- [`slappyengine.telemetry`](api/telemetry.md)
- [`slappyengine.testing`](api/testing.md)
- [`slappyengine.tools`](api/tools.md)

<!-- END: AUTO-GENERATED SUBPACKAGE API LINKS -->
