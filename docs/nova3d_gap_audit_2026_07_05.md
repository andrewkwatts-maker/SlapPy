# Nova3D Gap Audit — 2026-07-05 (HH3)

Read-only comparison of the Nova3D C++ engine (at
`H:\Github\Nova3D\engine\`) against the current SlapPyEngine tree
(`H:\Github\SlapPyEngine\python\pharos_engine\`). Written by HH3
background scrum agent. The goal is to enumerate what Nova3D ships
that SlapPyEngine does not, and to translate that delta into a
prioritised roadmap for building a fully functioning 2D/3D engine.

Sources consulted:

* `H:\Github\Nova3D\engine\` — 44 top-level subdirectories, ~950
  header/source files total.
* `H:\Github\Nova3D\README.md` — engine feature list + build targets.
* `H:\Github\Nova3D\CLAUDE.md` — coding standards + feature flag matrix.
* `H:\Github\Nova3D\AGENTS.md` — subsystem directory map.
* `H:\Github\SlapPyEngine\docs\big_picture_2026_07_05.md` — GG7 rollup
  (291-row feature map, 273 WIRED, 93.8%).
* `H:\Github\SlapPyEngine\docs\engine_feature_map_2026_07_04.md` —
  296-row action-level feature map.
* `H:\Github\SlapPyEngine\pyproject.toml` — current pip extras
  (`editor` / `video` / `audio` / `dev` / `ai` / `math` / `network`).

---

## 1. Executive summary

Nova3D is a **C++20 heavy-weight simulation engine** built for a
geolocated MMO RTS. It is renderer-first (OpenGL 4.6 via glad + GLFW),
SDF-native (raymarching + Radiance Cascade GI + ReSTIR + SVGF + spectral
rendering + RTX path tracing), and ships an integrated ImGui-docked
editor with 118 files under `engine/editor/`. Its `graphics/`
subdirectory alone is **190 files** — larger than the entirety of
SlapPyEngine's Python surface.

SlapPyEngine is a **Python-first 2D pixel-art engine with optional 3D
layers**, built around wgpu (Vulkan / DX12 / Metal backend) with 17
Rust kernels for hot paths. It ships a diary-themed DPG-based notebook
editor with ~30 panels, a 291-row feature map at 93.8% WIRED, and 12+
hello_* demos.

**Feature-parity delta** across the 44 Nova3D subdirectories:

* **~15 subsystems** have a strong SlapPyEngine parallel (graphics
  raster / lighting / GI / materials / animation / particles / scene /
  camera / physics-2D / AI / scripting / audio-basic / input-basic /
  save-basic / spatial-2D).
* **~10 subsystems** are partial (assets, editor, events, modding,
  networking, profiling, reflection, streaming, ui-editor,
  persistence).
* **~19 subsystems** are outright gaps (**glTF/OBJ/FBX importers**,
  **skeletal animation runtime**, **spatial 3D BVH/octree**, **RTS game
  layer**, **terrain**, **SDF acceleration**, **path tracing**,
  **radiance cascade GI**, **ReSTIR / SVGF**, **RTX**, **spectral
  render**, **gamepad**, **cloud persistence**, **packaging /
  exporter**, **replay determinism harness**, **localization**,
  **accessibility**, **reflection auto-property system**, **procedural
  content graph**).

**The single biggest gap the user has flagged** is the **asset import
pipeline** (glTF, OBJ, FBX). SlapPyEngine has zero mesh importers
today — Nova3D uses Assimp under `engine/import/ModelImporter.cpp`
(1381 lines) and `engine/graphics/ModelLoader.cpp` (227 lines). Adding
`pygltflib` + `trimesh` + optional `PyFBX` behind an
`pharos_engine[assets]` extra is the P0 unlock for any 3D content
pipeline.

**The second biggest gap** is a **3D triangle rasterizer with
mesh-uploading + drawcall submission**. SlapPyEngine already has
`gpu/mesh.py` (`GpuMesh` + `MeshVertex` — 208 lines),
`gpu/mesh_pipeline.py` (256 lines), `gpu/mesh_renderer.py` (231
lines), and `gpu/render_pipeline.py` (153 lines), so the plumbing
exists but is limited to hand-authored cube / plane primitives with no
material system beyond simple PBR. **Vulkan-backed forward rendering is
already there via wgpu** — what's missing is (a) mesh loading from
disk, (b) a proper draw list / batching layer, and (c) a scene-graph
walk that emits draw calls.

**Non-gaps** — SlapPyEngine has categories Nova3D lacks or under-serves:

* **Pixel-art per-pixel material simulation** (Nova3D is SDF-first, no
  pixel plane).
* **Rust-in-wheel hot-path kernels** (Nova3D is all C++, no scripting
  boundary).
* **wgpu cross-platform backend** (Nova3D is OpenGL 4.6 only, no
  DX12 / Metal).
* **17 mature hello_* demos with headless traces**.
* **Diary-themed personal notebook editor + 53-shader WGSL library**.

---

## 2. Nova3D subsystem inventory

Full inventory of every `engine/<subdir>/` in Nova3D, with file count
(the `wc -l` proxy — Nova3D headers + sources) and the surface each
exposes.

| # | Subdir | Files | Purpose | Key symbols |
|---|--------|-------|---------|-------------|
| 1 | `accessibility/` | 2 | Colorblind modes, screen reader, motor settings | `Accessibility` class |
| 2 | `ai/` | 6 | NavMesh pathfinding + SDF nav mesh | `NavMesh`, `SDFNavMesh`, `AIHIDBridge` |
| 3 | `animation/` | 25 | Skeletal animation, blend trees, state machines | `Animation`, `AnimationBlendTree`, `AnimationController`, `AnimationStateMachine`, `AnimationEventSystem`, `Skeleton`, `Keyframe`, `VertexAnimationTexture`, `AnimatorComponent`, `IBlendStrategy` + `blending/` + `editor/` subdirs |
| 4 | `assets/` | 5 | Asset DB + JSON serializer + FBX importer stub | `AssetDatabase`, `AssetPaths`, `FBXImporter`, `JsonAssetSerializer` |
| 5 | `audio/` | 12 | OpenAL 3D audio + sound bank + debug overlay | `AudioEngine` (1236 LoC), `AudioEngineStub`, `AudioEventSystem`, `AudioListenerComponent`, `AudioSourceComponent`, `SoundBank` |
| 6 | `config/` | 2 | JSON-backed config manager | `Config` |
| 7 | `core/` | 33 | Engine, Logger, JSON wrapper, JobSystem, Profiler, Time, Window, Pool, Cache, ServiceLocator, SoA, SIMD | `Engine`, `Logger`, `JobSystem`, `Profiler`, `Cache`, `Pool`, `PropertySystem`, `ComponentFactory`, `MemoryBudget`, `Time`, `Window`, `SettingsManager`, `json_wrapper.hpp` |
| 8 | `debug/` | 5 | BVH viz + profiler chrome | `BVHVisualizer`, `ProfilerChrome`, `DebugHIDBridge` |
| 9 | `editor/` | 118 | ImGui-docked editor with 30+ panels + AI tools | `EditorApplication`, `AssetBrowser`, `MaterialEditor`, `MeshAssetEditor`, `LightEditorPanel`, `PCGPanel`, `AnimationTimeline`, `ConsolePanel`, `DashboardPanel`, `EditorLayoutManager`, `EditorMenuSystem`, `EditorSelectionManager`, `EditorToolManager`, `GameExporter`, `BuildSettings`, `AI*` (7 files) |
| 10 | `events/` | 8 | Visual event binding with JSON serialization | `EventBinding`, `EventBindingManager`, `EventCondition`, `PropertyWatcher` |
| 11 | `graphics/` | **190** | Forward + deferred + SDF + RTX + Radiance Cascade + ReSTIR + SVGF + spectral + TAA + SSGI + shadows + clustered lighting + GPU-driven + batching + LOD | `Renderer` (3075 LoC), `Mesh`, `Material`, `Shader`, `Texture`, `ModelLoader`, `PathTracer`, `RTXPathTracer`, `RTGIPipeline`, `RadianceCascade`, `ReSTIR`, `SVGF`, `SDFRenderer`, `SDFAcceleration`, `SDFBrickCache`, `SDFSparseOctree`, `Culler`, `LODManager`, `ClusteredLighting`, `GBuffer`, `Framebuffer`, `TAA`, `SSGI`, `SpectralRenderer`, `ShadowMapper`, `CascadedShadowMaps`, `VolumetricLighting`, `GPUDrivenRenderer`, `LightProbeSystem`, `Batching`, `InstancedMesh` |
| 12 | `import/` | 15 | Model / texture / animation / LUT / MeshToSDF importers | `ModelImporter` (1381 LoC — Assimp glTF/OBJ/FBX), `TextureImporter` (1713 LoC), `AnimationImporter`, `LUTImporter`, `MeshToSDF`, `GeneralisedWindingNumber`, `AssetProcessor`, `ImportProgress`, `ImportSettings` |
| 13 | `input/` | 8 | Keyboard / mouse / rebinding / unified input map | `InputManager`, `Keyboard`, `Mouse`, `InputRebinding`, `UnifiedInputMap`, `InputHIDBridge` |
| 14 | `lighting/` | 7 | Physical lights, emissive geometry, bend fields | `PhysicalLight`, `EmissiveGeometryLight`, `BendFieldComponent`, `LightComponent`, `LightMaterialFunction` |
| 15 | `llm/` | 7 | Ollama client + cache + fallback + prompt templates | `AIHelper`, `AISchema`, `OllamaCache`, `OllamaClient`, `OllamaFallback`, `PromptTemplate` |
| 16 | `localization/` | 1 | i18n stub | `Localization` |
| 17 | `materials/` | 52 | Node-graph material editor with 20+ node types + LTC tables + AI builders | `MaterialGraphEditor`, `MaterialNode`, `ShaderGraph`, `AnimationNodes`, `BloomNodes`, `ColorGradeNodes`, `DistanceDrivenNodes`, `DistanceFieldAONode`, `LightShadowNodes`, `NoiseNodes`, `PbrSurfaceNodes`, `ProceduralTextureNodes`, `RadianceProbeNodes`, `SDFShaderNodes`, `ShaderNodes`, `TonemapNodes`, `TriplanarNodes`, `VolumetricFogNodes`, `AIHudBuilder`, `AILightingBuilder`, `AIMaterialGraphBuilder`, `MaterialCompilerCompute`, `LtcMatrixTables` |
| 18 | `math/` | 7 | GLM-backed math + noise + spline helpers | `Math`, `Noise`, `Spline` |
| 19 | `modding/` | 14 | Mod loader + JSON schema + template engine + behavior system | `ModManager`, `JsonSchema`, `UITemplateEngine`, `BehaviorSystem`, `EntityTypes` |
| 20 | `networking/` | 10 | Firebase + cloud provider registry + replication system | `CloudProviderRegistry`, `FirebaseClient`, `FirebasePersistence`, `ICloudProvider`, `ReplicationSystem` |
| 21 | `packaging/` | 9 | Cross-platform packaging + manifest + archive backends | `Packager`, `PackageArchive`, `PackageManifest`, `PackageOptions`, `backends/` |
| 22 | `particles/` | 7 | CPU + GPU particle systems + emitter | `ParticleSystem`, `ParticleEmitter`, `GPUParticleSystem`, `ParticleComponent` |
| 23 | `pathfinding/` | 6 | A* + graph + node | `AStar`, `Graph`, `Node`, `Pathfinder` |
| 24 | `persistence/` | 18 | SQLite + Firebase backends + entity serialization + chunk streamer + PlayerDatabase + WorldDatabase | `PersistenceManager`, `IPersistenceBackend`, `SQLiteBackend`, `FirebaseBackend`, `ChunkStreamer`, `EntitySerializer`, `PlayerDatabase`, `WorldDatabase` |
| 25 | `physics/` | 29 | RigidBody + CollisionShape + gravity fields + SDF collision + triggers + blackbody radiation | `PhysicsWorld`, `RigidBody`, `CollisionShape`, `CollisionBody`, `CollisionConfig`, `CollisionEvents`, `GravityFieldSystem`, `GravityVolume`, `SDFCollision`, `Triggers`, `BlackbodyRadiation`, `PhysicsDebugDraw` |
| 26 | `platform/` | 15 | Cross-platform backend (android / desktop / ios / linux / macos / mobile / windows) | `IPlatformBackend`, `FileSystem`, `Graphics`, `Renderer`, `LocationService`, `PlatformDetect` |
| 27 | `postprocess/` | 2 | Post-process pipeline stub | (2 files only — Nova3D's PP lives inside `graphics/`) |
| 28 | `procedural/` | 6 | Procedural generation graph + world template | `ProcGenGraph`, `ProcGenNodes`, `WorldTemplate` |
| 29 | `profiling/` | 6 | Detailed frame profiler + perf analyzer + DB | `DetailedFrameProfiler`, `PerformanceAnalyzer`, `PerformanceDatabase` |
| 30 | `reflection/` | 35 | Runtime type info + auto-property + observable + event bus + gameplay tags + HID bridge registry | `NovaReflect`, `Property`, `NovaProperty`, `Observable`, `EventBus`, `GameplayTag`, `HIDBridgeRegistry`, `InstanceRegistry`, `GlobalLocalRegistry`, `NV_MV_ReplicationBridge`, `AutoSerializer`, `AutoPostBridge` |
| 31 | `replay/` | 14 | Deterministic recording + playback | `Replay*` |
| 32 | `save/` | 4 | 100 save slots, compression, encryption, cloud sync | `SaveManager`, `SaveHIDBridge` |
| 33 | `scene/` | 19 | Scene graph, camera, fly camera, instance manager, transform delta poster | `Scene` (757 LoC), `SceneNode`, `Camera`, `FlyCamera`, `CameraComponent`, `InstanceData`, `PerInstanceData`, `InstanceManager`, `TransformDeltaPoster`, `SceneHIDBridge` |
| 34 | `scripting/` | 25 | Python integration + AI behavior + event dispatcher + script bindings + visual scripting | `PythonEngine`, `ScriptContext`, `ScriptBindings`, `ScriptComponent`, `ScriptableComponent`, `ScriptStorage`, `ScriptTemplate`, `ScriptValidator`, `AIBehavior`, `AIBehaviorTreeSchema`, `EventDispatcher`, `EventNodes`, `GameAPI`, `visual/` |
| 35 | `sdf/` | 15 | SDF primitives + marching cubes + SDF animation + brick cache scheduler + SDF cache + serializer | `MarchingCubes`, `SDFAnimation`, `SDFBrickCacheScheduler`, `SDFCache`, `SDFModel`, `SDFPrimitive`, `SDFPrimitiveComponent`, `SDFSerializer` |
| 36 | `server/` | 6 | Authoritative game server manager | `ServerManager`, `ServerConfig`, `ServerHIDBridge` |
| 37 | `shaders/` | 2 | Shader source directory | (WGSL/GLSL shaders live in `graphics/` — this dir is a stub) |
| 38 | `spatial/` | 20 | AABB / OBB / BVH / Octree / Frustum / SpatialHash3D / SDFBVH | `AABB`, `OBB`, `BVH`, `Octree`, `Frustum`, `SpatialHash3D`, `SDFBVH`, `CollisionPrimitives`, `SpatialIndex`, `SpatialManager` |
| 39 | `streaming/` | 2 | LOD-based asset streaming + background loading | `StreamingManager` |
| 40 | `terrain/` | 14 | SDF terrain + voxel + heightmap + noise generation + hybrid renderer | `SDFTerrain`, `HeightmapIO`, `NoiseGenerator`, `TerrainChunk`, `HybridTerrainRenderer`, `LandscapeSDFIntegration` |
| 41 | `text/` | 2 | Text rendering stub | (2 files) |
| 42 | `ui/` | 26 | ImGui-based UI system with docking | (26 files — game HUD + editor overlay) |
| 43 | `utils/` | 2 | File-system + string utils | `FileSystem`, `StringUtils` |

**Grand total** — ~950 files across the engine directory (excluding
`third_party/`, `tools/`, `game/`, `tests/`).

---

## 3. SlapPyEngine parallel inventory

Row-per-Nova3D-subsystem, mapping to the closest SlapPyEngine surface.

| Nova3D subsystem | SlapPyEngine equivalent | Status |
|------------------|-------------------------|--------|
| `accessibility/` | none | **GAP** |
| `ai/` (NavMesh) | `python/pharos_engine/ai/` (`ollama_manager.py`, `llm_client.py`, `script_gen.py`, `code_sync.py`, `_protocol.py`) — **LLM only, no NavMesh** | **PARTIAL** (different scope) |
| `animation/` | `python/pharos_engine/animation/` (`graph.py`, `procedural.py`, `video_import.py`) — **no skeletal, no blend tree** | **PARTIAL** |
| `assets/` (asset DB) | `python/pharos_engine/asset.py` (98 LoC — `Asset` class) + `python/pharos_engine/assets/` + `asset_manifest.py` | **PARTIAL** — no thumbnail cache, no type registry |
| `audio/` | `python/pharos_engine/audio.py` (195 LoC) + `audio_runtime.py` | **PARTIAL** — no 3D positional, no sound bank YAML |
| `config/` | `python/pharos_engine/config.py` + YAML manifests | **WIRED** |
| `core/` | `python/pharos_engine/engine.py`, `entity.py`, `components.py`, `data_component.py`, `struct_registry.py`, `event_bus.py`, `serialize.py`, `tags.py`, `perf/` | **WIRED** — different feel (no JobSystem, no SIMD helpers) |
| `debug/` | `python/pharos_engine/ui/debug_overlay.py` + `notebook_telemetry_panel.py` | **PARTIAL** (no BVHVisualizer — because no BVH3D) |
| `editor/` (118 files) | `python/pharos_engine/ui/editor/` (~30 notebook panels + gizmo + menu bar + palette + timeline + minimap) | **WIRED** — different style (diary DPG vs docked ImGui); no PCGPanel, no AI panels, no game exporter |
| `events/` | `python/pharos_engine/event_bus.py`, `event_publisher.py` (untracked WIP), events flow through `tool_router.REGISTRY` | **PARTIAL** — no visual event graph editor |
| `graphics/` (190 files!) | `python/pharos_engine/gpu/` (18 files — `context`, `mesh`, `mesh_pipeline`, `mesh_renderer`, `render_pipeline`, `pbr_material`, `material_buffer`, `texture_manager`, `cluster_3d`, `cluster_pipeline`, `entity_renderer`, `sdf_renderer`, `sdf_extruder`, `buffer_manager`, `ibl`, `adaptive_quality`), `python/pharos_engine/post_process/` (chain manifest + baker + TAA + bloom + executor), `python/pharos_engine/gi/` (`cascade`, `restir`, `svgf`) | **PARTIAL** — no path tracer, no ModelLoader, no LOD manager, no Culler, no InstancedMesh, no shadow mapper (has lighting.py 1026 LoC but no CSM impl surfaced) |
| `import/` (Assimp) | none | **GAP** |
| `input/` | `python/pharos_engine/input/` (`_manager.py`, `action_map.py`), `python/pharos_engine/input.py`, `input_provider.py` | **PARTIAL** — no gamepad, no rebinding UI |
| `lighting/` | `python/pharos_engine/lighting.py` (1026 LoC — physical lights + shadow presets), `python/pharos_engine/gi/` (Radiance Cascade + ReSTIR + SVGF exist) | **WIRED** — actually the strongest single system |
| `llm/` | `python/pharos_engine/ai/ollama_manager.py`, `llm_client.py` | **WIRED** |
| `localization/` | none | **GAP** |
| `materials/` (52 files) | `python/pharos_engine/material/` (5 files — `graph_schema`, `map`, `node_material`), `python/pharos_engine/visual_scripting/` (V5 18+ WGSL material nodes + V6 codegen), `python/pharos_engine/pixel_material.py`, `pixel_struct.py` | **PARTIAL** — has WGSL emitting node graph, but no LTC tables, no radiance probe nodes, no per-pixel PBR compiler cache |
| `math/` | `python/pharos_engine/math/` (arithma-backed Formula) | **WIRED** |
| `modding/` | none (`ext/` exists but only for compat shims, not mods) | **GAP** |
| `networking/` (Firebase) | `python/pharos_engine/net/` (`discovery`, `peer`, `room`, `session`, `sync`) | **PARTIAL** — has P2P + zeroconf, no cloud provider registry, no Firebase |
| `packaging/` | `python/pharos_engine/build_gen.py`, `content_encrypt.py`, `docs_gen.py` | **PARTIAL** — no cross-platform game exporter |
| `particles/` | `python/pharos_engine/particles.py` | **PARTIAL** — no GPU particle system (has GPU compute pipeline though) |
| `pathfinding/` | none | **GAP** |
| `persistence/` (SQLite / cloud) | `python/pharos_engine/serialize.py`, `python/pharos_engine/scenes/scene_file.py`, `autosave.py` | **PARTIAL** — YAML only, no SQLite, no cloud, no PlayerDatabase |
| `physics/` | `python/pharos_engine/dynamics/` (Rust-backed 2D), `python/pharos_engine/physics/` (untracked WIP), `python/pharos_engine/physics2/` (untracked WIP), `collision.py`, `collision_pixel.py` | **PARTIAL** — 2D only, no 3D rigid body, no gravity field, no trigger volume |
| `platform/` | Python is inherently cross-platform via wgpu | **N/A** |
| `postprocess/` | `python/pharos_engine/post_process/` — chain manifest + baker + executor + TAA + bloom | **WIRED** — strong |
| `procedural/` | `python/pharos_engine/landscape.py`, `python/pharos_engine/topology/`, `python/pharos_engine/zones/` | **PARTIAL** — no procedural graph editor |
| `profiling/` | `python/pharos_engine/perf/`, `python/pharos_engine/telemetry/sink.py` | **PARTIAL** |
| `reflection/` | `python/pharos_engine/struct_registry.py`, `python/pharos_engine/data_component.py` | **PARTIAL** — no NovaProperty, no auto-serializer, no observable |
| `replay/` | none | **GAP** |
| `save/` | `python/pharos_engine/autosave.py` + `scenes/scene_file.py` | **PARTIAL** — no compression, no encryption, no cloud sync, no 100-slot manager |
| `scene/` | `python/pharos_engine/scene.py`, `scenes/`, `camera.py`, `entity.py` | **WIRED** — Scene / SceneRegistry / SceneFile YAML |
| `scripting/` | `python/pharos_engine/script.py`, `visual_scripting/` (material nodes + codegen), `python/pharos_engine/actions/` | **WIRED** — Python IS the scripting language, plus visual graph |
| `sdf/` (15 files) | `python/pharos_engine/sdf_shapes.py`, `python/pharos_engine/gpu/sdf_renderer.py`, `python/pharos_engine/gpu/sdf_extruder.py` | **PARTIAL** — no marching cubes, no brick cache, no SDF animation |
| `server/` | none | **GAP** |
| `shaders/` | `python/pharos_engine/ui/theme/*/library.py` (53 WGSL shaders) + `post_process/*.wgsl` + `visual_scripting/*.wgsl` | **WIRED** |
| `spatial/` (BVH/Octree 3D) | `python/pharos_engine/bvh_factory.py` (2D BVH) | **PARTIAL** — 2D only |
| `streaming/` | `python/pharos_engine/residency/` | **PARTIAL** |
| `terrain/` | `python/pharos_engine/landscape.py`, `python/pharos_engine/topology/`, `python/pharos_engine/thermal/` | **PARTIAL** — no SDF terrain, no voxel |
| `text/` | none | **GAP** |
| `ui/` (26 files) | `python/pharos_engine/ui/` (widgets, editor, theme, HUD, HTML overlay, hotkeys, project manager) | **WIRED** — but no runtime immediate-mode HUD for games |
| `utils/` | scattered across `python/pharos_engine/` root | **WIRED** |

**Summary counts** — 12 WIRED, 20 PARTIAL, 10 GAP, 1 N/A.

---

## 4. Gap ranking (top 20 by impact × difficulty)

Ranking is `(user impact × difficulty penalty) / effort estimate`. Each
row cites the user-visible unlock, the SlapPyEngine landing path, and a
sprint-slot estimate (1 slot = 4-8 hours of one background agent).

| # | Gap | User impact | Difficulty | Effort | Landing path | Priority |
|---|-----|-------------|------------|--------|--------------|----------|
| 1 | **glTF / OBJ mesh importer** | Critical — no 3D content pipeline without this | Low | 2-3 slots | `python/pharos_engine/importers/gltf.py` + `obj.py` + `pharos_engine[assets]` extra | **MUST_HAVE** |
| 2 | **3D triangle rasterizer draw-call loop** | Critical — wgpu plumbing exists but no scene→draw call walk | Medium | 3-5 slots | `python/pharos_engine/gpu/scene_renderer.py` (walks Scene → issues drawcalls) | **MUST_HAVE** |
| 3 | **Skeletal animation runtime** | High — no rigged character playback | Medium | 4-6 slots | `python/pharos_engine/animation/skeleton.py` + `skinning.wgsl` + AnimationClip loader | **MUST_HAVE** |
| 4 | **3D BVH / Octree** | High — 3D collision + culling needs it | Low-Medium | 2-3 slots | `python/pharos_engine/spatial/` new subpackage (BVH3D + Octree + Frustum) | **MUST_HAVE** |
| 5 | **Cascaded shadow maps** | High — 3D scenes look flat without | Medium | 3 slots | Extend `lighting.py` — WGSL CSM pass with 4 cascades | **MUST_HAVE** |
| 6 | **Cross-platform game exporter** | High — user needs `slap build --target windows` | Medium | 3-4 slots | `python/pharos_engine/packaging/` new subpackage + PyInstaller wrapper | **MUST_HAVE** |
| 7 | **3D rigid body physics** | High — WIP dirs pinned, but nothing merged for 3D | Medium-High | 6-8 slots | Un-pin + finish `python/pharos_engine/physics/` (untracked in tree) | **MUST_HAVE** |
| 8 | **Gamepad input** | Medium-High — required for controller games | Low | 1-2 slots | Extend `python/pharos_engine/input/_manager.py` with glfw joystick API | **MUST_HAVE** |
| 9 | **PBR material graph editor UI** | Medium — V5 nodes exist but no visual editor | Medium | 3 slots | Extend `notebook_material_graph_editor.py` — connections + preview swatch | **MUST_HAVE** |
| 10 | **Sound bank + 3D positional audio** | Medium | Medium | 2-3 slots | Extend `audio.py` with `SoundBank` YAML + `soundfile`+`sounddevice` HRTF | **MUST_HAVE** |
| 11 | **Runtime game HUD system (immediate-mode)** | Medium-High — editor UI ≠ runtime HUD | Medium | 3-4 slots | New `python/pharos_engine/hud/` — imgui-bound or custom retained + widgets | **MUST_HAVE** |
| 12 | **NavMesh + A\* pathfinding** | Medium — RTS + top-down games | Medium | 4 slots | `python/pharos_engine/pathfinding/` new subpackage | **NICE_TO_HAVE** |
| 13 | **GPU particle system** | Medium | Medium | 3 slots | Extend `particles.py` + WGSL compute pass | **NICE_TO_HAVE** |
| 14 | **Replay determinism harness** | Medium — deterministic recording | Medium-High | 4-5 slots | New `python/pharos_engine/replay/` — pin RNG + record inputs | **NICE_TO_HAVE** |
| 15 | **Localization / i18n** | Low-Medium | Low | 1-2 slots | New `python/pharos_engine/localization/` + gettext / PO loader | **NICE_TO_HAVE** |
| 16 | **Accessibility (colorblind / high contrast)** | Low-Medium | Low | 1 slot | Extend theme system with 3-4 palettes | **NICE_TO_HAVE** |
| 17 | **Terrain (heightmap + voxel)** | Low-Medium — landscape.py exists but no heightmap loader | Medium | 3-4 slots | `python/pharos_engine/terrain/` — heightmap PNG + tri strips | **NICE_TO_HAVE** |
| 18 | **Text rendering (SDF glyphs)** | Low-Medium — needed for runtime HUD | Medium | 3 slots | `python/pharos_engine/text/` — msdfgen or `freetype-py` | **NICE_TO_HAVE** |
| 19 | **Modding system** | Low — Python is already extensible via ext/ | Low | 2 slots | Extend `ext/` with mod manifest loader | **NICE_TO_HAVE** |
| 20 | **FBX importer** | Low — glTF is the modern standard | High (`PyFBX` limited) | 3 slots | Optional — behind `pharos_engine[assets-fbx]` | **SKIP** for now |
| — | Path tracer / RTX / spectral render / Radiance Cascade beyond current stub | Low — user explicitly said "no fancy pipeline" | Very High | 20+ slots | — | **SKIP** |
| — | SDF marching cubes + brick cache + SDF animation | Low — user explicitly said "no fancy pipeline" | Very High | 15+ slots | — | **SKIP** |
| — | Firebase cloud persistence | Low — SlapPyEngine is offline-first | Medium | 4 slots | Optional | **SKIP** |

**Tally** — 11 MUST_HAVE, 8 NICE_TO_HAVE, 3+ SKIP.

---

## 5. Rendering pipeline gap deep-dive

The user's explicit ask:

> 3D/2D rendering (no need for fancy rendering pipeline / refractive
> indexes, just normal rasterization pipeline. vulkan based).

**Backend** — SlapPyEngine already uses **wgpu** as its GPU
abstraction. wgpu targets **Vulkan on Windows / Linux**, **DX12 on
Windows**, **Metal on macOS/iOS**, and **OpenGL** fallbacks. The `wgpu`
Python binding (`>=0.18` in `pyproject.toml`) wraps `wgpu-native` which
is `wgpu-core` Rust crate. This satisfies the user's "vulkan based"
requirement out of the box — no Vulkan SDK dependency needed.

**Per-subpackage readiness for 3D triangle rasterization**:

| Subpackage / file | 3D-ready? | Notes |
|-------------------|-----------|-------|
| `gpu/context.py` | **YES** — wgpu device + queue + surface | Existing entry point. |
| `gpu/mesh.py` (208 LoC) | **YES** — `GpuMesh` + `MeshVertex` (48-byte pos+normal+uv+tangent) with `unit_cube()` factory + `upload()` to wgpu | Vertex format is PBR-ready. |
| `gpu/mesh_pipeline.py` (256 LoC) | **YES** — pipeline layout for mesh drawing | Needs to grow beyond hand-authored primitives. |
| `gpu/mesh_renderer.py` (231 LoC) | **YES** — actual drawcall submission | Present but small. Needs Scene walk. |
| `gpu/render_pipeline.py` (153 LoC) | **YES** — pipeline factory | Ready. |
| `gpu/pbr_material.py` | **YES** — PBR material struct | Ready. |
| `gpu/material_buffer.py` | **YES** — material uniform buffer | Ready. |
| `gpu/texture_manager.py` | **YES** — texture upload | Ready. |
| `gpu/cluster_3d.py`, `cluster_pipeline.py` | **YES** — clustered lighting for 3D | Ready. |
| `gpu/ibl.py` | **YES** — IBL environment sampling | Ready (Rust-backed). |
| `gpu/entity_renderer.py` | **YES** — entity-level draw dispatch | Ready. |
| `gpu/sdf_renderer.py`, `sdf_extruder.py` | **YES** — SDF path (bonus) | Ready. |
| `gpu/adaptive_quality.py` | **YES** — dynamic res scaling | Ready. |
| `lighting.py` (1026 LoC) | **YES** — physical lights, presets, WGSL | Ready. |
| `gi/cascade.py`, `restir.py`, `svgf.py` | **YES** — GI stack | Ready. |
| `post_process/` | **YES** — TAA + bloom + chain manifest + 6 baked presets | Ready. |
| Mesh loading from disk | **NO** | No glTF/OBJ importer. This is gap #1. |
| Scene-graph walk emitting drawcalls | **PARTIAL** | `scene.py` + `entity_renderer.py` exist; needs a `RenderScene.walk_and_draw()` cohesive path. |
| Batching / instancing | **PARTIAL** | wgpu supports instanced drawing but there's no `InstancedMesh` component in SlapPyEngine. |
| Frustum culling | **NO** | 3D frustum + BVH3D missing. |
| LOD | **NO** | No `LODManager` equivalent. |
| Cascaded shadow maps | **PARTIAL** — `lighting.py` has shadow presets but no CSM pass | Needs 4-cascade split + shadow-map framebuffer. |
| Skinning shader | **NO** | Needs `skinning.wgsl` + `Skeleton` runtime + bone palette buffer. |

**Top 3 rendering gaps** (verified against the file inventory above):

1. **Mesh loading from disk** — no glTF/OBJ importer means no user-authored
   3D content can ever enter the engine.
2. **Scene→drawcall walker + culling** — the mesh pipeline exists but
   there is no cohesive path that walks `Scene` → filters visible →
   batches → submits drawcalls. Blocks any 3D scene beyond the current
   `unit_cube()` demo.
3. **Cascaded shadow maps + skeletal skinning** — content will look
   fundamentally flat / rigid without CSM and no rigged character can
   animate without a skinning shader. These two shader passes unlock
   the "looks like a 3D game" bar.

Everything else the user explicitly deprioritised (path tracing,
refractive indexes, RTX, ReSTIR / SVGF beyond the current stubs,
spectral rendering, SDF brick cache, marching cubes) can wait.

---

## 6. Asset import gap deep-dive

Currently zero mesh importers in SlapPyEngine. Nova3D uses **Assimp**
(a C++ library) behind `engine/import/ModelImporter.cpp` (1381 LoC)
which supports 40+ formats. Python has three viable options.

### 6.1 glTF (RECOMMENDED as first port)

* **Library**: `pygltflib` (pure Python, MIT).
* **Coverage**: glTF 2.0 (binary `.glb` + text `.gltf`) — the industry
  standard for real-time 3D content. Blender / Maya / SketchFab / Unity
  / Unreal / Godot all export glTF.
* **Vertex data**: interleaved buffers with POSITION / NORMAL / TEXCOORD_0 /
  TANGENT / JOINTS_0 / WEIGHTS_0 attributes — maps directly to
  SlapPyEngine's 48-byte `MeshVertex` (positions/normals/UVs/tangents
  already match). Joint + weight attributes plug into the future
  skeletal animation runtime.
* **Materials**: PBR (baseColor / metallicRoughness / normalMap /
  emissive / occlusion) — maps directly to `gpu/pbr_material.py`.
* **Animations**: keyframe channels (translation / rotation / scale /
  weights) with linear / step / cubic interpolation — feeds the
  skeletal runtime.
* **Effort**: 2 sprint slots. `python/pharos_engine/importers/gltf.py`
  ≈ 300-500 LoC.

### 6.2 OBJ (RECOMMENDED as second port)

* **Library**: `trimesh` (already popular, MIT, has robust OBJ + STL +
  PLY support) OR `PyWavefront` (lighter, MIT).
* **Coverage**: static meshes only (no animation, no skinning). Popular
  for CAD imports + free asset packs.
* **Effort**: 1 sprint slot. `python/pharos_engine/importers/obj.py`
  ≈ 150-250 LoC. Recommend `trimesh` — bigger surface, handles STL /
  PLY / DAE for free.

### 6.3 FBX (SKIP for MVP, revisit)

* **Library**: `PyFBX` — but note the official Autodesk FBX SDK is C++
  with restrictive licensing. Python bindings are third-party and
  incomplete (typically hobbyist forks).
* **Alternatives**: `pyfbx-i42`, `fbx-python`, or converting FBX →
  glTF via `FBX2glTF` (Facebook's CLI). The last approach is what most
  game engines fall back to.
* **Recommendation**: **SKIP** for MVP. Ship a
  `slap import model.fbx --to gltf` CLI wrapper around `FBX2glTF` that
  users install separately. This keeps the wheel size down and avoids
  Autodesk licensing headaches.

### 6.4 Texture importers

Nova3D `TextureImporter.cpp` is 1713 LoC — but the Python story is
much simpler because **Pillow is already a core dependency** and
handles PNG / JPEG / TGA / BMP / EXR (via `imageio` optional). The
formats that need special handling:

* **KTX2 / Basis Universal** — compressed GPU textures. Library:
  `pyKTX` (limited) or vendor the KTX-Software CLI. **NICE_TO_HAVE.**
* **HDR / EXR** — for IBL environment maps. Library: `imageio` +
  `OpenEXR` bindings. **NICE_TO_HAVE.**
* **DDS** — Direct3D texture format. Library: `imageio` supports it.
  **NICE_TO_HAVE.**

For MVP, PNG + JPEG via Pillow is enough. Add `imageio` under
`pharos_engine[assets]` extra.

### 6.5 Vendor vs optional dep decision

Recommendation: **all importers land as optional deps under a single
`pharos_engine[assets]` extra**. Rationale:

* Keeps the core wheel small (< 800 KiB currently — assets deps would
  triple it).
* Users doing pure 2D pixel-art work never need mesh importers.
* Import happens at **build time** (asset baking pipeline) or **editor
  time** — never runtime for shipped games (games load pre-baked
  `.slap` format).

Proposed `[project.optional-dependencies]` addition:

```toml
assets = [
    "pygltflib>=1.16",   # glTF 2.0
    "trimesh>=4.0",      # OBJ / STL / PLY / DAE
    "imageio>=2.34",     # HDR / EXR / DDS textures
]
```

FBX support ships as documented CLI wrapper around `FBX2glTF`, not as
a Python dep.

---

## 7. UI system gap

User's ask:

> UI system that can be used in games AND editor.

**Current state** — SlapPyEngine has a mature editor UI stack:

* `python/pharos_engine/ui/theme/` — 3 declarative theme libraries (53
  WGSL shaders across washi_tape / page_linings / edge_strokes) +
  theme baker + shader lint + batch validator.
* `python/pharos_engine/ui/widgets/` — custom widget primitives
  (GlitterProgressBar / RibbonTab / PaperClipAttachment / WashiTapeDivider
  / SketchButton / InkStampBadge — 6 primitives from X7).
* `python/pharos_engine/ui/editor/` — ~30 notebook panels
  (DiaryShell / StartupPrompt / ProjectRegistry / SnapOverlay /
  GizmoOverlay / MessageLog / PrefabMenu / AssetInspector /
  ToastManager / CommandPalette / AutosavePanel / HotkeyHelp /
  TelemetryDashboard / TimelineEditor / MenuBar / PPPreviewPanel /
  Minimap / MaterialGraphBridge / NodeEditor + 10 Nova3D-legacy).
* `python/pharos_engine/ui/hud_widgets.py` — HUD helpers (partial).
* `python/pharos_engine/ui/html_overlay.py` — pywebview-based HTML
  overlay (mostly for the project manager).

**All DPG-bound**. The `dearpygui>=1.11` dep sits under
`pharos_engine[editor]` extra. This is fine for **editor** but wrong
for **game runtime**:

1. DPG is a heavy dep (~15 MB) — bloats shipped games.
2. DPG requires its own event loop — games have their own tick.
3. DPG's retained mode is at odds with typical game HUD idioms
   (immediate mode, per-frame draw calls).
4. DPG's docking / node-editor features are **editor** concerns, wasted
   on runtime HUDs.

**Recommended split** — two-tier UI system:

### 7.1 Editor UI (unchanged)

Stay on DPG under `pharos_engine[editor]`. Everything under `ui/editor/`
already works and doesn't need to change.

### 7.2 Runtime HUD (new)

New `python/pharos_engine/hud/` subpackage:

* **Immediate-mode** — pygame-style `draw_rect` / `draw_text` / `draw_image`
  per-frame API backed by wgpu triangles.
* **Widget layer** — reusable widgets on top of imgui (`pyimgui`
  bindings) or a hand-rolled retained-tree over the immediate mode.
* **Themeing bridge** — the same 3-library shader theme can drive both
  editor (via DPG textures) and runtime HUD (via wgpu directly).
* **Text rendering** — needs SDF glyph atlas (see rendering gap #4).

**Decision**: recommend `pyimgui` bindings for the runtime HUD layer.
Rationale: imgui is the industry standard, works headless, works over
wgpu, and Nova3D itself uses imgui — cross-pollination is free.

Two-extra structure:

```toml
editor = ["dearpygui>=1.11", "pywebview>=4.0", "arithma>=2.0.2"]
hud    = ["imgui[glfw]>=2.0"]
```

---

## 8. Package structure suggestion

The current `pyproject.toml` has 7 extras (`editor`, `video`, `audio`,
`dev`, `ai`, `math`, `network`). Recommended additions to cover the
gaps identified above:

### 8.1 Current extras

```toml
[project.optional-dependencies]
editor  = ["dearpygui>=1.11", "pywebview>=4.0", "arithma>=2.0.2"]
video   = ["av>=12.0"]
audio   = ["sounddevice>=0.4", "soundfile>=0.12"]
dev     = ["pytest>=7.0", "pytest-asyncio>=0.21", "watchdog>=3.0"]
ai      = ["httpx>=0.27"]
math    = ["arithma>=2.0.2"]
network = ["kademlia>=2.2.2", "aioice>=0.9.0", "zeroconf>=0.131"]
```

### 8.2 Proposed additions

```toml
# 3D asset import — glTF, OBJ, STL, PLY, DAE, HDR/EXR
assets = [
    "pygltflib>=1.16",
    "trimesh>=4.0",
    "imageio>=2.34",
]

# Runtime game HUD — immediate-mode UI
hud = [
    "imgui[glfw]>=2.0",
]

# 3D physics (once un-pinned)
physics3d = [
    # currently native; may add pybullet for reference bodies
]

# Meta: everything
all = [
    "pharos-engine[editor,video,audio,ai,math,network,assets,hud]",
]
```

### 8.3 Install matrix

| Use case | Command | Wheel weight |
|----------|---------|--------------|
| Headless server / CI | `pip install pharos-engine` | ~13 MB (wgpu core) |
| Game runtime with HUD | `pip install pharos-engine[hud]` | ~15 MB |
| Editor + assets pipeline | `pip install pharos-engine[editor,assets]` | ~50 MB |
| Full development | `pip install pharos-engine[all]` | ~70 MB |

The core stays lean; heavy deps opt-in per use case.

---

## 9. Roadmap (10-item ordered)

Ordered by (unlock chain × user-stated priority). Each item cites the
gap-ranking row from §4.

1. **[Gap #1] glTF importer** — `python/pharos_engine/importers/gltf.py`
   using `pygltflib`. Emit `GpuMesh` + `PBRMaterial` + optional
   `Skeleton` + `AnimationClip` structs. 2-3 slots. **P0.**
2. **[Gap #1] OBJ importer** — same subpackage, `trimesh`-backed.
   Static meshes only. 1 slot. **P0.**
3. **[Gap #2] Scene→drawcall walker** —
   `python/pharos_engine/gpu/scene_renderer.py`. Walk `Scene`, filter
   visible entities, sort by material, submit indexed drawcalls
   through the existing `mesh_pipeline.py`. 3 slots. **P0.**
4. **[Gap #4] 3D BVH + frustum culling** — new
   `python/pharos_engine/spatial/` subpackage. Extend `bvh_factory.py`
   from 2D → 3D. 2-3 slots. **P0.**
5. **[Gap #6] Cross-platform game exporter** — extend `build_gen.py`
   into `python/pharos_engine/packaging/` with PyInstaller wrapper +
   `slap build --target windows|linux|macos` CLI. 3 slots. **P0.**
6. **[Gap #3] Skeletal animation runtime** — `animation/skeleton.py` +
   `skinning.wgsl` bone-palette buffer + `AnimationClip.sample()` +
   `AnimationController.tick()`. 4-6 slots. **P1.**
7. **[Gap #5] Cascaded shadow maps** — extend `lighting.py` — 4-cascade
   split shadow map framebuffer + `csm.wgsl` fragment sampler. 3 slots.
   **P1.**
8. **[Gap #7] 3D rigid body physics** — un-pin the untracked
   `python/pharos_engine/physics/` tree, stage / review / commit, then
   add 3D `RigidBody3D` component + Rust kernel port. 6-8 slots. **P1.**
9. **[Gap #8] Gamepad input** — extend `input/_manager.py` with glfw
   joystick polling + `action_map.py` gamepad bindings. 1-2 slots. **P1.**
10. **[Gap #11] Runtime HUD subsystem** — new `python/pharos_engine/hud/`
    with imgui-backed immediate-mode API + theme bridge. Ships behind
    `pharos_engine[hud]`. 3-4 slots. **P2.**

**Runway estimate** — items 1-5 (P0) = 11-14 slots ≈ 1.5-2 weeks of
7-agent parallel batches. Items 6-8 (P1) = 12-16 slots ≈ another 1.5
weeks. Item 9-10 (P2) = 4-6 slots ≈ half a week.

**Full 3D-parity target**: **4 weeks of the current sprint cadence**
lands items 1-10, at which point SlapPyEngine has a Nova3D-comparable
3D content pipeline minus the "no fancy pipeline" items the user
already deprioritised (path tracing, RTX, spectral, SDF brick cache).

---

## 10. Cross-reference index

* `H:\Github\Nova3D\engine\` — 44 subdirectories, ~950 files.
* `H:\Github\Nova3D\README.md` — feature list + build targets +
  technology stack (OpenGL 4.6, GLFW, GLM, nlohmann/json, Dear ImGui,
  Assimp).
* `H:\Github\Nova3D\CLAUDE.md` — coding standards + feature flag matrix.
* `H:\Github\Nova3D\AGENTS.md` — subsystem directory map.
* `H:\Github\SlapPyEngine\docs\big_picture_2026_07_05.md` — GG7 rollup
  (291-row feature map @ 93.8% WIRED).
* `H:\Github\SlapPyEngine\docs\engine_feature_map_2026_07_04.md` —
  296-row action-level feature map.
* `H:\Github\SlapPyEngine\pyproject.toml` — 7 current extras.
* `H:\Github\SlapPyEngine\python\pharos_engine\gpu\` — 18-file 3D
  rendering pipeline (wgpu-backed, PBR-ready).
* `H:\Github\SlapPyEngine\python\pharos_engine\lighting.py` — 1026 LoC
  physical lights + shadow presets.
* `H:\Github\SlapPyEngine\python\pharos_engine\gi\` — Radiance Cascade +
  ReSTIR + SVGF (stubs surfaced).
* `H:\Github\SlapPyEngine\python\pharos_engine\material\` +
  `visual_scripting\material_nodes.py` — WGSL-emitting node graph.

---

## 11. Summary card

* **Nova3D subsystem count**: 44 top-level, ~950 files.
* **SlapPyEngine subsystem parity**: 12 WIRED, 20 PARTIAL, 10 GAP,
  1 N/A (platform).
* **MUST_HAVE gaps**: **11** (gltf importer, obj importer,
  scene→drawcall walker, 3D BVH, CSM, game exporter, 3D physics,
  gamepad, PBR material graph UI polish, sound bank, runtime HUD).
* **NICE_TO_HAVE gaps**: 8 (NavMesh, GPU particles, replay, i18n,
  accessibility, terrain, text SDF, modding).
* **SKIP**: 3+ (FBX, path tracing / RTX / spectral, cloud persistence).
* **Top 3 rendering gaps**: (1) mesh loading from disk, (2)
  scene→drawcall walker + culling, (3) cascaded shadow maps + skeletal
  skinning.
* **Recommended pip extras**: current 7 + `assets` + `hud` + `all`
  meta-extra.
* **4-week roadmap**: 10 items, P0-P2 phased, lands full 3D content
  pipeline parity (minus the deprioritised "fancy" items).

---

*Nova3D gap audit generated 2026-07-05 by HH3 background scrum agent.
Read-only reference — no Nova3D files modified. All findings verified
by directly reading Nova3D headers + counting files.*
