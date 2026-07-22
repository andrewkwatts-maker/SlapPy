# SlapPyEngine v0.3 — Engine Surface Reference

> Auto-generated from runtime introspection of `pharos_engine.__all__` and the
> `_subpackages` set declared in `python/pharos_engine/__init__.py`.
> **Do not hand-edit.** Re-run `python scripts/gen_engine_surface_doc.py` to
> refresh after surface changes.

v0.3 is the first "Rust engine, Python wrapper" release. Hot paths are
native; Python is glue, ergonomics, and config. Ships on PyPI as
`pharos-engine`.

* Engine version (runtime): `0.3.0b0`
* Native `_core` available: `True`
* Top-level names in `__all__`: **91**
* Declared subpackages: **25**

## Update 2026-07-07 (TT5)

Re-ran `scripts/gen_engine_surface_doc.py` to close v0.4 gate #2
("engine surface doc matches `__all__`"). This is the second refresh
after the NN6 pass (2026-07-06). Delta since NN6:

* **+3 top-level names** (88 -> 91): `DiagnosticEvent`,
  `DiagnosticsCollector`, `get_global_collector` — the OO6 diagnostics
  aggregator surface + RR4/SS6 extensions.
* **+3 declared subpackages** (22 -> 25): `math`, `visual_scripting`,
  and the `zones` / `math` set literals in `_subpackages` — the
  script's live parse now reports 25 (previous hand-authored count of
  22 was stale; no set-literal edits since NN6, only the doc counter).
* No removals — every pre-NN6 name is still present in `__all__`.
* `App` gained ten new methods since NN6 (introspected via
  `dir(App)`): `start_recording`, `stop_recording`,
  `take_screenshot`, `enable_ssao`, `enable_shadows` (NN3);
  `enable_diagnostics`, `disable_diagnostics`, `get_diagnostics`,
  `diagnostics_events`, `diagnostics_stats` (QQ4); plus
  `diagnostics_report` (SS6). See the **App runtime surface** callout
  below for the full method list.
* `World3D` gained raycast + sweep + BVH + debug helpers
  (NN4 / OO2 / QQ7): `raycast`, `sweep_aabb`, `RaycastHit`,
  `SweepHit`, `build_bvh`, `draw_debug`, `debug_stats`. These live on
  `pharos_engine.gpu` / render-side objects and are surfaced through
  `App.spawn_camera(...).world` in application code — not directly in
  `pharos_engine.__all__`.

Gate #2 verdict: **GREEN** — the generator ran clean, produced
9 passing tripwire tests
(`SlapPyEngineTests/tests/test_docs_engine_surface_complete.py` +
`test_docs_inventory.py`), and the runtime-introspected counts match
the doc's stated counts. Regeneration is now a one-command loop:
`PYTHONPATH=python python scripts/gen_engine_surface_doc.py`.

### App runtime surface (HH1 + NN3 + QQ4 + SS6)

`App` is the ergonomic 2-line render entry (`launch().load_model(...).run()`),
but it also exposes a broader lifecycle + recording + diagnostics API.
Introspected via `dir(App)` at TT5-time:

| Method | Origin | Purpose |
|---|---|---|
| `load_model`, `load_texture` | HH1 | Import asset -> handle. |
| `spawn_camera`, `spawn_light` | HH1 | Scene helpers. |
| `enable_hud` | HH1 | Toggle overlay HUD. |
| `run`, `stop`, `close`, `render_frame` | HH1 | Loop control. |
| `is_running`, `is_closed`, `is_headless`, `elapsed`, `frame_count` | HH1 | Introspection. |
| `add_before_tick`, `add_after_tick`, `add_before_frame_render` | HH1 | Lifecycle hooks. |
| `get_bounding_box_of_all_models` | HH1 | Scene extent query. |
| `start_recording`, `stop_recording`, `take_screenshot` | NN3 | Capture surface. |
| `enable_ssao`, `enable_shadows` | NN3 | Post-process toggles. |
| `enable_diagnostics`, `disable_diagnostics` | QQ4 | Diagnostics on/off. |
| `get_diagnostics`, `diagnostics_events`, `diagnostics_stats` | QQ4 | Query aggregator. |
| `diagnostics_report` | SS6 | Save Markdown diagnostics report. |


## Top-level surface (`import pharos_engine`)

Every name below is reachable as `pharos_engine.<Name>`. Module column is relative to `pharos_engine.`. Signatures shown where introspectable.

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
| `AssetImportDispatcher` | class | `asset_import.dispatcher` | `() -> 'None'` | Dispatch an asset path to the correct importer by extension. |
| `ImportResult` | dataclass | `asset_import.import_result` | `(kind: 'str', meshes: 'list[Any]' = <factory>, textures: 'list[TextureData]' = <factory...` | Uniform return type from every asset importer. |
| `TextureData` | dataclass | `asset_import.import_result` | `(pixels: 'np.ndarray', width: 'int', height: 'int', channels: 'int', format: 'str' = 'R...` | CPU-side texture buffer. |
| `import_asset` | function | `asset_import.dispatcher` | `(path: 'str | Path') -> 'ImportResult'` | Free-function dispatch — uses a lazy shared dispatcher instance. |

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
| `App` | class | `app` | `(config: 'AppConfig | None' = None, *, config_path: 'str | Path | None' = None) -> 'None'` | Runtime shell: window + tick loop + hooks + asset handles. |
| `AppConfig` | dataclass | `app` | `(window_title: 'str' = 'SlapPyEngine', window_size: 'tuple[int, int]' = (1280, 720), fu...` | Runtime configuration for :class:`App`. |
| `BlurPass` | function | `(top-level)` | `(radius: 'int' = 2)` | Return a :class:`PostProcessPass` configured for blur. |
| `CameraHandle` | dataclass | `app` | `(position: 'tuple[float, float, float]' = (0.0, 0.0, 5.0), look_at: 'tuple[float, float...` | Active-camera handle. |
| `DiagnosticEvent` | dataclass | `diagnostics` | `(level: 'str', subsystem: 'str', message: 'str', timestamp: 'float', exc_info: 'Optiona...` | One captured logging record, distilled for HUD / tooling display. |
| `DiagnosticsCollector` | class | `diagnostics` | `(max_events: 'int' = 500, min_level: 'str' = 'WARNING') -> 'None'` | Rolling-buffer aggregator for ``pharos_engine.*`` log records. |
| `HAS_NATIVE` | constant |  |  | Returns True when the argument is true, False otherwise. |
| `LightHandle` | dataclass | `app` | `(position: 'tuple[float, float, float]' = (0.0, 0.0, 0.0), color: 'tuple[float, float, ...` | Spawned light entity handle. |
| `ModelHandle` | dataclass | `app` | `(path: 'str' = '', position: 'tuple[float, float, float]' = (0.0, 0.0, 0.0), rotation: ...` | Mutable transform + trace log for a loaded model. |
| `OutlinePass` | function | `(top-level)` | `(color=(1.0, 0.0, 0.0, 1.0), threshold=0.1)` | Return a :class:`PostProcessPass` configured for outline rendering. |
| `PixelatePass` | function | `(top-level)` | `(block_size: 'int' = 4)` | Return a :class:`PostProcessPass` configured for pixelation. |
| `TextureHandle` | dataclass | `app` | `(path: 'str' = '', id: 'int' = -1, width: 'int' = 0, height: 'int' = 0, channels: 'int'...` | Handle to a loaded texture / bitmap asset. |
| `get_global_collector` | function | `diagnostics` | `() -> 'DiagnosticsCollector'` | Return the process-wide :class:`DiagnosticsCollector` (lazy init). |
| `launch` | function | `app` | `(on_begin: 'Callable[[App], None] | None' = None, on_tick: 'Callable[[App, float], None...` | One-shot launcher for the 2-line render pattern. |
| `load_model` | function | `app` | `(path: 'str | Path') -> 'ModelHandle'` | Load a model into the implicit global app (creates one if absent). |
| `load_texture` | function | `app` | `(path: 'str | Path') -> 'TextureHandle'` | Load a texture into the implicit global app (creates one if absent). |

## Subpackages

These are the modules exposed via `pharos_engine.__getattr__` — accessing `pharos_engine.<name>` lazy-imports them. Each row lists the public attributes currently exposed by the subpackage and its inner modules.

### `pharos_engine.ai`

AI subpackage — lazy-loaded (requires [ai] extra: httpx).

**Public attributes:** `LLMBackendProtocol`

**Inner modules:** `_protocol`, `code_sync`, `llm_client`, `ollama_manager`, `script_gen`

### `pharos_engine.animation`

Animation subpackage — lazy-loaded.

**Public attributes:** `graph`, `procedural`

**Inner modules:** `clip`, `graph`, `procedural`, `skeleton_runtime`, `skinner`, `video_import`

### `pharos_engine.asset_import`

pharos_engine.asset_import — 3D-asset / texture importer subpackage.

**Public attributes:** `AssetImportDispatcher`, `ImportDependencyError`, `ImportResult`, `MtlMaterialDef`, `Skeleton`, `SkeletonNode`, `SkinnedMeshData`, `TextureData`, `cubemap_importer`, `dispatcher`, `gltf_importer`, `import_asset`, `import_cubemap`, `import_fbx`, `import_gltf`, `import_hdr_cubemap`, `import_obj`, `import_obj_with_materials`, `import_ply`, `import_result`, `import_stl`, `import_texture`, `load_model`, `load_texture`, `mtl_resolver`, `mtl_to_material`, `obj_importer`, `parse_mtl`, `resolve_mtl_references`, `skinned_mesh`, `stub_importer`, `texture_importer`

**Inner modules:** `cubemap_importer`, `dispatcher`, `gltf_importer`, `import_result`, `mtl_resolver`, `obj_importer`, `samples`, `skinned_mesh`, `stub_importer`, `texture_importer`

### `pharos_engine.assets`

**Public attributes:** `database`

**Inner modules:** `_validation`, `database`

### `pharos_engine.audio_runtime`

audio_runtime — internal plumbing around the `sounddevice` backend.

**Public attributes:** `Any`, `AudioBackend`, `Protocol`, `get_backend`, `logging`, `np`

### `pharos_engine.compute`

Compute subpackage — lazy-loaded to avoid eager wgpu/numpy imports.

**Public attributes:** `ComputeKernelProtocol`, `asset_compute`, `mutator`, `pipeline`, `readback`, `spatial`, `stats`

**Inner modules:** `_protocol`, `_validation`, `asset_compute`, `ast_compiler`, `effect`, `hull`, `library`, `mutator`, `pipeline`, `readback`, `shader_cache`, `spatial`, `stats`, `wgsl_chunks`

### `pharos_engine.dynamics`

Unified dynamics primitives layered on top of the XPBD substrate.

**Public attributes:** `Body`, `BoneSpec`, `DynamicsWorldLike`, `Humanoid`, `IKChainSpec`, `JointSpec`, `KIND_PARAM_KEYS`, `LAYER_BONE`, `LAYER_MUSCLE`, `LAYER_SKIN`, `Material`, `MotorSpec`, `OVERDAMPING_THRESHOLD`, `RagdollSpec`, `RopeSpec`, `SCHEMA_VERSION`, `SoftBodyWorld`, `SpringSpec`, `World`, `WorldLike`, `body`, `body_from_dict`, `body_to_dict`, `bone_spec_from_dict`, `bone_spec_to_dict`, `build_flesh_wrap`, `build_humanoid`, `build_ragdoll`, `build_rope`, `estimate_effective_damping`, `humanoid`, `humanoid_from_dict`, `humanoid_to_dict`, `ik`, `ik_chain_from_dict`, `ik_chain_to_dict`, `joint`, `joint_from_dict`, `joint_to_dict`, `load_world`, `make_distance`, `make_humanoid`, `make_motor`, `make_spring`, `material`, `material_from_dict`, `material_to_dict`, `motor`, `motor_from_dict`, `motor_to_dict`, `place_feet_on_terrain`, `ragdoll`, `ragdoll_spec_from_dict`, `ragdoll_spec_to_dict`, `resolve_joint`, `resolve_joint_specs`, `rope`, `rope_spec_from_dict`, `rope_spec_to_dict`, `save_world`, `serialize`, `solve_ik`, `spring`, `spring_from_dict`, `spring_to_dict`, `world`, `world_from_dict`, `world_to_dict`, `wrap_in_flesh`

**Inner modules:** `_validation`, `body`, `humanoid`, `ik`, `joint`, `material`, `motor`, `ragdoll`, `rope`, `serialize`, `spring`, `world`

### `pharos_engine.ext`

SlapPyEngine.ext — optional extension modules.

**Public attributes:** _(none exposed at package level)_

**Inner modules:** `ai`, `angle_sprite`, `animation`, `fluid_sim`, `input`, `iso`, `lighting`, `net`, `split_screen`, `ui`

### `pharos_engine.gpu`

GPU subpackage — lazy-loaded to avoid eager wgpu imports.

**Public attributes:** `buffer_manager`, `context`, `entity_renderer`, `pbr_material`, `render_pipeline`, `sdf_extruder`, `texture_manager`

**Inner modules:** `_validation`, `adaptive_quality`, `buffer_manager`, `cluster_3d`, `cluster_pipeline`, `context`, `entity_renderer`, `ibl`, `ibl_prefilter`, `material_buffer`, `mesh`, `mesh_pipeline`, `mesh_renderer`, `pbr_material`, `render_pipeline`, `sdf_extruder`, `sdf_renderer`, `texture_manager`

### `pharos_engine.input`

SlapPyEngine.input

**Public attributes:** `ActionMap`, `InputManager`, `action_map`

**Inner modules:** `_manager`, `_manager_validation`, `_validation`, `action_map`

### `pharos_engine.iso`

SlapPyEngine.iso — Isometric 2D-grid-with-Z rendering subsystem.

**Public attributes:** `IsoCamera`, `IsoCell`, `IsoEntity`, `IsoGrid`, `IsoScene`, `IsoTileDef`, `IsoViewpoint`, `iso_camera`, `iso_entity`, `iso_grid`, `iso_scene`, `projection`

**Inner modules:** `_validation`, `combat`, `iso_camera`, `iso_entity`, `iso_grid`, `iso_scene`, `projection`

### `pharos_engine.material`

Material subpackage — lazy-loaded.

**Public attributes:** `NodeProtocol`, `graph_schema`, `map`, `node_material`

**Inner modules:** `_node_validation`, `_protocol`, `graph_schema`, `map`, `node_material`

### `pharos_engine.math`

pharos_engine.math — Symbolic + numeric formula evaluation.

**Public attributes:** `AnimationCurve`, `Bezier`, `Catmull`, `Expression`, `Formula`, `Integer`, `Keyframe`, `Variable`, `Vec2`, `Vec3`, `Vec4`, `compile_formula`, `curves`, `ease`, `evaluate`, `formula`, `vector`

**Inner modules:** `_validation`, `curves`, `formula`, `vector`

### `pharos_engine.modules`

Modules subpackage — lazy-loaded.

**Public attributes:** _(none exposed at package level)_

**Inner modules:** `fluid_params`, `health`, `physics`, `pixel_physics`

### `pharos_engine.numerics`

Generic numerical primitives.

**Public attributes:** `compute_residual`, `np`, `sor_smooth`, `validate_2d_array`, `validate_matching_shape`, `validate_omega`, `validate_positive_float`, `validate_positive_int`, `vcycle_poisson`

**Inner modules:** `_validation`

### `pharos_engine.post_process`

Post-process subpackage — lazy-loaded to avoid eager wgpu imports.

**Public attributes:** `chain`

**Inner modules:** `_pass_base`, `_protocol`, `_ubo`, `_validation`, `auto_exposure`, `bloom`, `chain`, `chain_baker`, `chain_manifest`, `contact_shadows`, `dof`, `executor`, `gtao`, `motion_blur`, `outline`, `preset_chains`, `shadow_csm`, `ssr`, `taa`, `tonemap`, `vignette`, `volumetric_fog`

### `pharos_engine.projects`

pharos_engine.projects — Nova3D-style multi-project management.

**Public attributes:** `PROJECT_FILE_NAME`, `Project`, `ProjectFormatError`, `ProjectMetadata`, `ProjectRegistry`, `find_project_root`, `format`, `get_default_registry`, `is_project_dir`, `project`, `read_project`, `registry`, `scaffold_project`, `scaffolding`, `write_project`

**Inner modules:** `format`, `project`, `registry`, `scaffolding`

### `pharos_engine.residency`

Residency subpackage — lazy-loaded to avoid eager imports.

**Public attributes:** `manager`

**Inner modules:** `_validation`, `compression`, `manager`, `slap_format`

### `pharos_engine.telemetry`

pharos_engine.telemetry

**Public attributes:** `Any`, `Callable`, `Deque`, `Dict`, `EventEmitterProtocol`, `EventSubscriberProtocol`, `List`, `Optional`, `TelemetryEvent`, `Tuple`, `clear_history`, `dataclass`, `deque`, `emit`, `enable_pattern_index`, `field`, `fnmatch`, `get_event_history`, `is_pattern_index_enabled`, `set_history_capacity`, `subscribe`, `threading`, `time`, `unsubscribe`, `validate_bool`, `validate_callable`, `validate_non_negative_int`, `validate_positive_int`, `validate_str`

**Inner modules:** `_protocol`, `_validation`, `sink`

### `pharos_engine.testing`

pharos_engine.testing — visual regression harness.

**Public attributes:** `Any`, `BASELINES_DIR`, `DIFF_DIR`, `Path`, `assert_scene_matches`, `diff_pngs`, `logging`, `np`, `render_scene_to_png`, `validate_baseline_name`, `validate_non_negative_float`, `validate_non_negative_int`, `validate_pathlike`, `validate_positive_int`, `validate_tolerance`

**Inner modules:** `_validation`

### `pharos_engine.thermal`

Heat diffusion + pairwise heat exchange — Phase B public surface.

**Public attributes:** `HeatField`, `HeatSourceProtocol`, `Iterable`, `Tuple`, `exchange_two_regions`, `math`, `np`, `validate_diffusivity`, `validate_finite_float`, `validate_grid_2d_float`, `validate_non_negative_float`, `validate_positive_float`, `validate_positive_int`

**Inner modules:** `_protocol`, `_validation`

### `pharos_engine.tools`

**Public attributes:** _(none exposed at package level)_

**Inner modules:** `_sprite_audit_validation`, `audio_tools`, `gen_placeholders`, `sprite_audit`, `sprite_tools`, `texture_tools`, `track_tools`, `video`

### `pharos_editor.ui`

UI subpackage — lazy-loaded to avoid eager numpy/wgpu imports.

**Public attributes:** `hud_widgets`, `scene_ui`

**Inner modules:** `debug_overlay`, `editor`, `hotkey_conflicts`, `hotkey_remap`, `html_overlay`, `hud_widgets`, `plugin_registry`, `plugin_samples`, `project_manager`, `runtime`, `scene_ui`, `theme`, `user_overrides`, `widgets`

### `pharos_engine.visual_scripting`

Visual scripting — graph data model + Python code generation.

**Public attributes:** `AbsNode`, `AddNode`, `BUILTIN_NODES`, `BUILTIN_REGISTRY`, `ClampNode`, `CrossNode`, `DefaultWgslEmitContext`, `DotNode`, `Edge`, `FresnelNode`, `GradientRampNode`, `GraphValidationError`, `LerpNode`, `MATERIAL_CATEGORY`, `MATERIAL_NODE_TYPES`, `MaterialNode`, `MaterialOutputNode`, `MultiplyNode`, `NODE_KINDS`, `Node`, `NodeGraph`, `NodeKind`, `NodePort`, `NodeRegistry`, `NormalizeNode`, `PORT_KINDS`, `PerlinNoiseNode`, `PortKind`, `PowerNode`, `SaturateNode`, `SqrtNode`, `TextureSampleNode`, `TimeNode`, `UVOffsetNode`, `WgslEmitContext`, `WorleyNoiseNode`, `codegen_python`, `get_node`, `graph`, `graph_to_python`, `list_nodes`, `material_nodes`, `node`, `palette`, `ports_compatible`, `python_to_graph`, `register_material_nodes`

**Inner modules:** `codegen`, `codegen_python`, `golden_utils`, `graph`, `material_nodes`, `node`, `palette`

### `pharos_engine.zones`

pharos_engine.zones — Generic zone primitives.

**Public attributes:** `Any`, `Callable`, `EnterExitCallback`, `EntityId`, `Hashable`, `Iterable`, `Position`, `RectZone`, `ThresholdCallback`, `ThresholdZone`, `ZoneManager`, `ZoneProtocol`, `dataclasses`, `validate_finite_float`, `validate_non_negative_float`, `validate_positive_float`

**Inner modules:** `_protocol`, `_validation`

## Stability notes

### Stable (v0.3 — committed contract)

- The 91 top-level lazy exports listed above.
- The 25 declared subpackages: `ai`, `animation`, `asset_import`, `assets`, `audio_runtime`, `compute`, `dynamics`, `ext`, `gpu`, `input`, `iso`, `material`, `math`, `modules`, `numerics`, `post_process`, `projects`, `residency`, `telemetry`, `testing`, `thermal`, `tools`, `ui`, `visual_scripting`, `zones`.

### Beta (may evolve)

- Anything inside a subpackage that is **not** re-exported at the top level. Subpackage internals may move between point releases; pin a specific `pharos-engine` version if you rely on them directly.
- `pharos_engine.ext.*` — back-compat shim namespace; superseded by the top-level lazy exports.

### Deprecated (kept for back-compat, will be removed)

- Anything not present in `__all__` or `_subpackages`. Old modules live on disk for migration but are not part of the contract.

## Getting started

```python
import pharos_engine as sle

engine = sle.Engine(title="My Game", width=640, height=360)
layer = engine.add_layer("world", sle.Layer2D(tile_size=16))
engine.run()
```

See the `examples/` directory for runnable scenes that exercise the surface above (hello world, lighting, physics, layered character, multiplayer, HUD, landscape, baking, 3D layers, editor).

## Game integration tripwires

Downstream games (e.g. Ochema Circuit, Bullet Strata) pin the names they import from this engine. When a game ships against a new engine name, add a tripwire test that asserts the name remains importable — removing any locked name breaks that game.

Today the locked names are simply everything in `pharos_engine.__all__` plus the declared subpackages, both of which are exercised by `SlapPyEngineTests/tests/test_docs_engine_surface_complete.py`.

<!-- BEGIN: AUTO-GENERATED SUBPACKAGE API LINKS -->

## Per-subpackage API references

The following per-subpackage reference docs are auto-generated by `scripts/gen_subpackage_api_docs.py`. Each one lists every public class / function / constant with full signatures and parsed `Raises:` sections — paste one into an LLM prompt to get accurate context for that subpackage.

- [`pharos_engine.dynamics`](api/dynamics.md)
- [`pharos_engine.zones`](api/zones.md)
- [`pharos_engine.topology`](api/topology.md)
- [`pharos_engine.numerics`](api/numerics.md)
- [`pharos_engine.thermal`](api/thermal.md)
- [`pharos_engine.iso`](api/iso.md)
- [`pharos_engine.telemetry`](api/telemetry.md)
- [`pharos_engine.testing`](api/testing.md)
- [`pharos_engine.tools`](api/tools.md)

<!-- END: AUTO-GENERATED SUBPACKAGE API LINKS -->

## Per-subpackage design references

Hand-authored design docs that complement the API references above.
Each design doc covers architecture, decision rationale, performance
notes, and the Rust-migration story for its subpackage. Subpackages
without a separate design doc carry their architectural prose inline
in the API reference's "Design notes" section (linked from the
"See also" block at the bottom of each `docs/api/*.md`).

| Subpackage | API ref | Design ref |
|---|---|---|
| `pharos_engine.dynamics` | [`api/dynamics.md`](api/dynamics.md) | [`dynamics_design.md`](dynamics_design.md) |
| `pharos_engine.softbody` | inline (`__init__.py` docstring) | [`softbody_design.md`](softbody_design.md) |
| `pharos_engine.fluid` | inline (`__init__.py` docstring) | [`fluid_design.md`](fluid_design.md) |
| `pharos_engine.gi` | [`api/gi.md`](api/gi.md) | [`gi_design.md`](gi_design.md) |
| `pharos_engine.post_process` | [`api/post_process.md`](api/post_process.md) | [`post_process_design.md`](post_process_design.md) |
| `pharos_engine.studio` | [`api/studio.md`](api/studio.md) | [`studio_design.md`](studio_design.md) |
| `pharos_engine.material` | [`api/material.md`](api/material.md) | [`material_design.md`](material_design.md) |
| `pharos_engine.numerics` | [`api/numerics.md`](api/numerics.md) | [`numerics_design.md`](numerics_design.md) |
| `pharos_engine.projects` | [`api/projects.md`](api/projects.md) | no separate doc — see API ref §Overview |
| `pharos_engine.telemetry` | [`api/telemetry.md`](api/telemetry.md) | [`telemetry_design.md`](telemetry_design.md) |
| `pharos_engine.zones` | [`api/zones.md`](api/zones.md) | [`zones_design.md`](zones_design.md) |
| `pharos_engine.animation` | [`api/animation.md`](api/animation.md) | no separate doc — see API ref §Design notes |
| `pharos_engine.audio_runtime` | [`api/audio_runtime.md`](api/audio_runtime.md) | no separate doc — see API ref §Design notes |
| `pharos_engine.compute` | [`api/compute.md`](api/compute.md) | no separate doc — see API ref §Design notes |
| `pharos_engine.ext` | [`api/ext.md`](api/ext.md) | no separate doc — see API ref §Design notes |
| `pharos_engine.gpu` | [`api/gpu.md`](api/gpu.md) | no separate doc — see API ref §Design notes |
| `pharos_engine.iso` | [`api/iso.md`](api/iso.md) | no separate doc — see API ref §Design notes |
| `pharos_engine.residency` | [`api/residency.md`](api/residency.md) | no separate doc — see API ref §Design notes |
| `pharos_engine.testing` | [`api/testing.md`](api/testing.md) | no separate doc — see API ref §Design notes |
| `pharos_engine.thermal` | [`api/thermal.md`](api/thermal.md) | no separate doc — see API ref §Design notes |
| `pharos_engine.topology` | [`api/topology.md`](api/topology.md) | no separate doc — see API ref §Design notes |
| `pharos_editor.ui.editor` | [`api/ui_editor.md`](api/ui_editor.md) | no separate doc — see API ref §Design notes |
| `pharos_engine.tools` | [`api/tools.md`](api/tools.md) | no separate doc — surface is the `sprite_audit` CPU utility (see [`sprite_audit_recipe.md`](sprite_audit_recipe.md)) |
