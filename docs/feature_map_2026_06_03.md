# Feature Map — SlapPyEngine (2026-06-03)

> Read-only audit. Subpackage surfaces, notebook editor panels (every
> button / slider / checkbox), cross-system flow walk-throughs, and a
> gap analysis ranking the top holes to fill before v0.4.
>
> No source edits accompany this document. Cross-links throughout to
> existing API references in `docs/api/`, the sprint planning doc
> ([`sprint_plan_2026_06_03.md`](sprint_plan_2026_06_03.md)), and the
> Nova3D pattern audit ([`ui_pattern_audit_2026_06_03.md`](ui_pattern_audit_2026_06_03.md)).
>
> WIP-frozen perimeters per memory note `project_sprint_2026_05_29.md`:
> `python/slappyengine/softbody/` and `python/slappyengine/fluid/` are
> NOT touched — surfaces listed below were read from `__init__.py`
> without exercising the modules.

---

## 1. Subpackage map

Status legend (matches the sprint plan):

* **SHIPPED** — production-ready, hardened, hand-authored docs, ≥1 demo,
  exercised by `test_hardening_*.py` AND a `docs/api/<name>.md`.
* **WORKING** — functional and runnable but missing one of
  {hardening / docs / demo / round-trip parity}.
* **SKELETON** — surface exists, real implementation thin or partial.
* **GAP** — declared in the roadmap but not implemented (or actively
  WIP-frozen).

Tests-count cells count `def test_*` symbols across files matching the
subpackage prefix. Where a subpackage shares a hardening file we cite it
explicitly. Hand-authored design-doc cells use the
`docs/<name>_design.md` convention; auto-generated references live under
`docs/api/`.

### 1.1 Simulation core (engine substrate)

| Subpackage | Status | Public surface (count) | Description | Tests | API ref | Design doc |
|---|---|---|---|---|---|---|
| `dynamics` | SHIPPED | 58 names — `Body`, `JointSpec`, 7 kinds, `RagdollSpec`, `RopeSpec`, `IKChainSpec`, `Humanoid*`, `World`, `SoftBodyWorld`, `Material`, `MotorSpec`, `SpringSpec`, `BoneSpec`, builders (`make_*` / `build_*`), serializers (`*_to_dict` / `*_from_dict`), `solve_ik`, `resolve_joint`, `save_world` / `load_world`, `SCHEMA_VERSION`, `KIND_PARAM_KEYS`, layer constants | XPBD substrate + ragdoll / rope / IK / humanoid builders + JSON round-trip. Hardening rounds 7-13. | 167 (`test_dynamics_*.py` + `test_hardening_dynamics*.py`) | [`api/dynamics.md`](api/dynamics.md) (auto-gen) | [`dynamics_design.md`](dynamics_design.md), [`dynamics_quickstart.md`](dynamics_quickstart.md) |
| `topology` | SHIPPED | 3 — `BACKGROUND_LABEL`, `connected_components`, `connected_components_grid` | Connected-components / union-find primitives lifted from the bond solver. | 20 (`test_hardening_topology.py`) | [`api/topology.md`](api/topology.md) | (n/a — single-page API) |
| `numerics` | SHIPPED | (no `__all__`; exports `vcycle_poisson`, `sor_smooth`, `compute_residual`) | Multigrid V-cycle + Red-Black SOR smoother. 2.4× speedup. | 24 (`test_hardening_numerics.py`) + perf | [`api/numerics.md`](api/numerics.md) | [`numerics_design.md`](numerics_design.md) |
| `zones` | SHIPPED | 4 — `RectZone`, `ThresholdZone`, `ZoneManager`, `ZoneProtocol` | Named AABB regions with enter / exit callbacks, material tags, scalar threshold events. 10.9× spatial-hash backend. | 18 + spatial | [`api/zones.md`](api/zones.md) | [`zones_design.md`](zones_design.md) |
| `thermal` | SHIPPED | 3 — `HeatField`, `HeatSourceProtocol`, `exchange_two_regions` | Pairwise boundary heat exchange. | 25 (`test_hardening_thermal.py`) | [`api/thermal.md`](api/thermal.md) | (n/a) |
| `softbody` | WORKING (WIP-frozen) | 22 — `BeamSoA`, `BodyMeta`, `MATERIALS`, `Material`, `NodeSoA`, `SoftBodyRenderConfig`, `SoftBodyRenderer`, `SoftBodyWorld`, `SpatialHash`, `VehicleHandle`, `VehicleSpec`, `WheelSpec`, `apply_drivetrain_torque`, `build_contact_pairs`, `build_vehicle`, `load_catalog`, `make_lattice_body`, `make_layered_creature`, `project_contact_pairs`, `render_world_gif`, `resolve_contacts`, `step` | BeamNG-style XPBD lattice + vehicle/body builders. **WIP-frozen until the physics reconciliation sprint.** | — (frozen) | (n/a) | [`softbody_design.md`](softbody_design.md) |
| `fluid` | WORKING (WIP-frozen) | 29 — `FluidWorld`, `ParticleSoA`, `FluidMaterial`, `FluidRenderer`, 6 catalog materials (`WATER`, `LAVA`, `ICE`, `STONE`, `SAND`, `DUST`, `GRAVEL`), `pbf_step`, `apply_fluid_buoyancy[_iterative]`, `compute_density_normals`, `extract_isolines`, `poly6` / `spiky_grad` (+ coefficients), `thermal_step`, `project_fluid_softbody_contacts`, `slerp_normals`, `sample_density_grid`, `EDGE_TABLE`, `MATERIALS`, `load_catalog`, `render_world_gif` | Position-Based Fluids 2D solver. **WIP-frozen.** | — (frozen) | (n/a) | [`fluid_design.md`](fluid_design.md) |
| `physics` (legacy) | WORKING | 18 — `HullTree`, `PhysicsWorld`, `PhysicsBody`, `CellGridPool`, `CELL_GRID_SIZE`, `CELL_PIXEL_STRUCT`, `BoundaryExchange`, `ContactPair`, `PhysicsYaml`, `TIER_T0`/`T1`/`T2`, `NO_CELL_GRID`, `NO_PARENT`, `load_physics_config`, `make_circle_silhouette`, `make_rect_silhouette`, `silhouette_to_cells` | Hierarchical-hull per-pixel solver. Slated for Phase D strip. | scattered (`test_blast.py`, `test_particle_field*`, etc.) | [`physics_module.md`](physics_module.md) | [`per_pixel_sim_audit_2026_05_31.md`](per_pixel_sim_audit_2026_05_31.md) |

### 1.2 Rendering & GPU

| Subpackage | Status | Public surface (count) | Description | Tests | API ref | Design doc |
|---|---|---|---|---|---|---|
| `gi` | SHIPPED | 3 — `RadianceCascadeSystem`, `ReSTIRSystem`, `SVGFDenoiser` | Radiance cascades + ReSTIR reservoir reuse + SVGF denoiser (GPU + CPU paths). | scattered (`test_lighting_*.py` × 16 files) | [`api/gi.md`](api/gi.md) | [`gi_design.md`](gi_design.md) |
| `post_process` | SHIPPED | 14 — `PostProcessChain`, `PostProcessExecutor`, `PostProcessParams`, `PostProcessPass`/`Base`/`Protocol`, `ContactShadowsPass`, `GTAOPass`, `ShadowCSM`, `TAAPass`, `VolumetricFog`, `arcade_chain`, `cinematic_chain`, `iso_strategy_chain` | 14 passes (bloom/GTAO/TAA/DoF/MB/SSR/volumetric/CSM/...) + preset chains. | 28 (`test_hardening_postprocess.py` + `test_post_process_*`) | [`api/post_process.md`](api/post_process.md) | [`post_process_design.md`](post_process_design.md) + [`lighting_presets.md`](lighting_presets.md) |
| `material` | WORKING | 20 — `NodeMaterial`, `NodeDef`, `NodeProtocol`, `KNOWN_NODE_TYPES`/`PORT_TYPES`, `validate_node_graph`, `MaterialMap`, `MaterialDef`, `ColorRange`, 12 node-factory functions (`UVNode`, `PixelColorNode`, `AddNode`, `MultiplyNode`, `LerpNode`, `ClampNode`, `GravityWarpNode`, `SampleTextureNode`, `FinalColorNode`, `DiscardNode`, `PixelChannelNode`) | NodeMaterial runtime + factories + MaterialMap color-range catalog. **No visual node-graph editor** (Sprint 4 target). | 59 (`test_hardening_node_material.py` + `test_node_material*`) | [`api/material.md`](api/material.md) | [`material_design.md`](material_design.md) + [`material_catalog.md`](material_catalog.md) |
| `gpu` | SHIPPED | 15 — `GPUContext`, `RenderPipeline`, `MeshPipeline`, `MeshRenderer`, `EntityRenderer`, `ClusterPipeline`, `Cluster3DSystem`, `BufferManager`, `TextureManager`, `MaterialBuffer`, `PbrMaterial`, `GpuMesh`, `MeshVertex`, `IBLSystem`, `SdfRenderer` | wgpu context + mesh / PBR / cluster pipelines + SDF renderer + IBL + adaptive quality. | 26 (`test_hardening_gpu.py`) + `test_gpu_*.py` + `test_render_pipeline.py` | [`api/gpu.md`](api/gpu.md) | (none — see [`api/gpu.md`](api/gpu.md)) |
| `compute` | SHIPPED | 11 — `AABB`, `AssetComputeAPI`, `ComputeKernelProtocol`, `ComputePass`, `ComputePipeline`, `PixelAPI`, `PixelMutator`, `ReadbackBuffer`, `SpatialCompute`, `StatsCompute`, `StatsResult` | ComputePass / Pipeline + readback + mutator + stats + spatial reductions + per-asset facade. | 47 (`test_hardening_compute_pipeline.py` + `test_compute*.py` + `test_ast_compiler.py`) | [`api/compute.md`](api/compute.md) | (n/a) |
| `residency` | SHIPPED | 11 — `ResidencyManager`, `SLAP_MAGIC`, `SLAP_VERSION`, `compress_array`/`raw`, `decompress_array`/`raw`, `read_asset_from_slap`, `read_world_slap`, `write_asset_to_slap`, `write_world_slap` | 3-tier GPU / RAM / DISK + `.slap` binary format. | 43 (`test_hardening_residency.py` + `test_residency.py`) | [`api/residency.md`](api/residency.md) | (n/a) |

### 1.3 Authoring + integration

| Subpackage | Status | Public surface (count) | Description | Tests | API ref | Design doc |
|---|---|---|---|---|---|---|
| `studio` | SHIPPED | 14 — `Stage`, `Renderable`, `softbody_stage`, `fluid_stage`, `fluid_with_softbody_stage`, `humanoid_stage`, `dynamics_stage`, `record`, `anchor`, `centroid`, `kick`, `translate`, `terrain_overlay`, `output_path` | High-level scene scaffolding wrapping the rebuild physics stack into ~15-line demos. | 6 (`test_studio_dynamics_stage.py`) | [`api/studio.md`](api/studio.md) | [`studio_design.md`](studio_design.md), [`studio_quickstart.md`](studio_quickstart.md) |
| `iso` | SHIPPED | 7 — `IsoCamera`, `IsoCell`, `IsoEntity`, `IsoGrid`, `IsoScene`, `IsoTileDef`, `IsoViewpoint` (+ `iso.combat` submodule) | Isometric grid renderer with viewpoint rotation + Stone Keep combat. | 24 (`test_hardening_iso.py` + `test_iso_combat.py`) | [`api/iso.md`](api/iso.md) | (n/a) |
| `audio_runtime` | WORKING | (no `__all__`) — `AudioBackend`, real / stub-backend selection helpers | sounddevice soft-import shim. **Backend boundary (resampling / underrun) un-audited per roadmap.** | 4 (`test_audio_runtime.py`) | [`api/audio_runtime.md`](api/audio_runtime.md) | (n/a) |
| `telemetry` | SHIPPED | 11 — `TelemetryEvent`, `EventEmitterProtocol`, `EventSubscriberProtocol`, `emit`, `subscribe`, `unsubscribe`, `get_event_history`, `clear_history`, `set_history_capacity`, `enable_pattern_index`, `is_pattern_index_enabled` | 86 ns no-subscriber emit, 6.42× bucket-index dispatch. | 25 (`test_hardening_telemetry.py` + `test_telemetry*.py`) | [`api/telemetry.md`](api/telemetry.md) | [`telemetry_design.md`](telemetry_design.md) |
| `testing` | SHIPPED | 5 — `BASELINES_DIR`, `DIFF_DIR`, `assert_scene_matches`, `diff_pngs`, `render_scene_to_png` | Visual-regression harness (image diff vs baseline). | 16 (`test_hardening_testing.py`) + visual reference suite | [`api/testing.md`](api/testing.md) | (n/a) |
| `animation` | WORKING | 6 — `AnimState`, `AnimTransition`, `AnimUpdate`, `AnimationGraph`, `ControlPoint`, `ProceduralRig` | State-machine graph + procedural rig + video-frame import. **No blend tree / FBX / GLTF importer / IK retargeting** (Sprint 3 target). | 21 + 15 (`test_hardening_animation.py` + `test_animation.py`) | [`api/animation.md`](api/animation.md) | (none — gap; Sprint 3 will add `animation_design.md`) |
| `ai` | WORKING | 6 — `CodeSyncWatcher`, `LLMBackendProtocol`, `LLMClient`, `ScriptGenerator`, `code_to_prompt`, `prompt_to_code` | Ollama integration: prompt ↔ code sync watcher + script generator. **No top-level surface entry, no `docs/api/ai.md`** (roadmap mid-term v0.4). | scattered (used by Code Mode tests) | **MISSING — `docs/api/ai.md`** | (n/a) |
| `ext` | WORKING | 10 namespaces — `ai`, `angle_sprite`, `animation`, `fluid_sim`, `input`, `iso`, `lighting`, `net`, `split_screen`, `ui` | Back-compat shim namespace re-exporting older import paths. | scattered (Ochema-compat tripwire) | [`api/ext.md`](api/ext.md) | (n/a) |
| `net` | SKELETON | 7 — `GameSession`, `InputFrame`, `LockstepSync`, `Peer`, `PeerState`, `RoomCode`, `SessionConfig` | Peer / session / discovery / sync scaffolding. **No `docs/api/network.md`, no `hello_multiplayer.py`, no hardening round.** | (none) | **MISSING — `docs/api/network.md`** | (n/a) |
| `assets` | SHIPPED | (no `__all__`) — `AssetDatabase` singleton + validation | Asset DB. | 22 (`test_hardening_assetdb.py`) | (none — covered in [`api/_template.md`](api/_template.md) shape) | (n/a) |
| `modules` | SKELETON | 4 — `FluidParamsModule`, `HealthModule`, `PhysicsModule`, `PixelPhysicsModule` | Game-side plugin scaffold. | (none direct) | (none) | (n/a) |
| `tools` | WORKING | (no `__all__`) — `sprite_audit`, `audio_tools`, `texture_tools`, `track_tools`, `video`, `gen_placeholders`, `sprite_tools` | CPU-only utilities for asset audit + placeholder gen. | 15 (`test_hardening_sprite_audit.py`) + `test_sprite_audit_*.py` | [`api/tools.md`](api/tools.md) (auto-gen) | [`sprite_audit_recipe.md`](sprite_audit_recipe.md) |

### 1.4 UI

| Subpackage | Status | Public surface (count) | Description | Tests | API ref | Design doc |
|---|---|---|---|---|---|---|
| `ui` | WORKING | 3 — `HtmlOverlay`, `SceneUIEntity`, `draw_stat_bar` (+ submodules) | `scene_ui`, `hud_widgets`, `debug_overlay`, `html_overlay`, `project_manager`, `widgets` family. | scattered (`test_scene_ui.py`) | (none top-level — see sub) | (none) |
| `ui.theme` | SHIPPED | 26 — `Color`, `Font`, `Gradient`, `NineSlice`, `Palette`, `RadiusScale`, `SemanticTokens`, `ShaderEffect`, `SpacingScale`, `SVGIcon`, `ThemeSpec`, `TransitionScale`, `ZIndexScale`, `apply_theme`, `dot_grid`, `frosted_panel`, `get_active_theme`, `glass_blur`, `highlighter_stroke`, `list_registered_themes`, `noise_glitter`, `paper_shadow`, `parchment`, `register_theme`, `ruled_paper`, `watercolor_wash` | Primitive infrastructure for the diary theme family — nine-slice, SVG icon, procedural shader effects, ThemeSpec + registry. | 56 (`test_theme_primitives.py`) | [`api/ui_theme.md`](api/ui_theme.md) | [`theme_teengirl_notebook_2026_06_03.md`](theme_teengirl_notebook_2026_06_03.md), [`theme_diary_family_2026_06_03.md`](theme_diary_family_2026_06_03.md) |
| `ui.theme.creatures` | SHIPPED | 16 — `Creature`, `CreatureScheduler`, `CreatureBusAdapter`, `IdleEventEmitter`, `AnimationCurve`, `Keyframe`, `SlotPolicy`, `SlotRegion`, `RenderFn`, `DrawList`, `EVENT_TO_CREATURE_ANIMS`, `register_creature`, `set_enabled`, `set_reduced_motion`, `tick`, `trigger` | Idle-animation subsystem (fox, butterfly, sparkle, …) with scheduler + event-bus adapter. | 82 (`test_creature_*.py` × 3 files) | (none — see [`idle_animation_system_2026_06_03.md`](idle_animation_system_2026_06_03.md)) | [`idle_animation_system_2026_06_03.md`](idle_animation_system_2026_06_03.md) + [`woodland_creature_catalog_2026_06_03.md`](woodland_creature_catalog_2026_06_03.md) |
| `ui.theme.themes` | SHIPPED | 8 — `BULLET_JOURNAL`, `COTTAGECORE_GARDEN`, `COZY_DIARY`, `KAWAII_PLANNER`, `SCRAPBOOK_SUMMER`, `TEENGIRL_NOTEBOOK`, `register_all_themes`, `register_starter_themes` | Six built-in diary theme variants. | 56 (`test_theme_starter_variants.py` + `test_theme_extended_variants.py`) | (none — covered in theme family doc) | [`theme_diary_family_2026_06_03.md`](theme_diary_family_2026_06_03.md) |
| `ui.widgets` | SHIPPED | 29 — `StickerButton`, `WashiPanel`, `NotebookTab`, `HighlighterSlider`, `HeartCheckbox`, `DoodleSeparator`, plus `Button`, `Checkbox`, `Dial`, `Dropdown`, `ImageWidget`, `Label`, `LayoutBox`, `Panel`, `ProgressBar`, `ScrollView`, `Slider`, `StatBar`, `Theme`, `Widget`, `NotebookTheme`, `add_sticker_corner`, `list_sticker_corners`, `remove_sticker_corner`, `register_theme_listener`, `unregister_theme_listener`, `resolve_theme`, `set_active_theme`, `get_active_theme` | Notebook-themed DPG widget primitives + theme registry. | 58 (`test_widgets.py` + `test_ui_widgets_notebook.py`) | [`api/ui_widgets.md`](api/ui_widgets.md) | (none — covered in widgets API ref) |
| `ui.editor` | WORKING | 14 lazy exports — `AnimGraphPanel`, `BehaviorPanel`, `EditorShell`, `LayerLightingPanel`, `LayerPanel`, `MaterialEditor`, `MeshInspector`, `NodeGraphPanel`, `NotebookInspector`, `NotebookMaterialEditor`, `NotebookWelcome`, `PropertyInspector`, `TagPainter`, `ViewportPanel` (note: 11 notebook-themed panels live in the same dir but are not lazy-mapped from `__all__`) | DearPyGui editor shell + notebook panel family. **No build-pipeline UI, no input-remap UI, no visual material graph canvas** — see Sprint 7 / Sprint 4. | 162 across 11 `test_editor_notebook_*.py` + 23 (`test_editor_theme_switcher.py`) + 13 (`test_editor.py`, `test_editor_shell_theme_wiring.py`, `test_editor_property_inspector_dataclass.py`, `test_editor_material_editor_kinds.py`, `test_editor_dynamics_*.py`, `test_editor_scene_outliner_dynamics.py`, `test_editor_spawn_menu.py`) | [`api/ui_editor.md`](api/ui_editor.md) | [`notebook_editor_manual_2026_06_03.md`](notebook_editor_manual_2026_06_03.md) + [`ui_pattern_audit_2026_06_03.md`](ui_pattern_audit_2026_06_03.md) |

### 1.5 GAPs declared in roadmap but absent on disk

| Planned name | Status | Notes / source-doc citation |
|---|---|---|
| `ecs/` formalisation | GAP | Sprint 2 target. Today: `Component` Protocol + `ComponentBase` only, no scheduler / sparse-set storage. |
| `vfx/` (particle / effect authoring) | GAP | Sprint 5 target. `particles.py` ships emitter + GPU pool; no shape / curve / force-field wrapper API. |
| `i18n.py` | GAP | Sprint 7 target. Every HUD / editor label is English-literal. |
| `save_version.py` (engine-wide save migration) | GAP | Sprint 7 target. `dynamics.save_world` carries `SCHEMA_VERSION` but no version-chain migration helper. |
| `scene/loader.py` (progress-bar scene loading) | GAP | Sprint 7 target. |
| Profiler overlay | GAP | Sprint 6 target. `telemetry` ships events; no F3 in-engine flame graph yet. |
| Build pipeline UI | GAP | Sprint 7 target. `build_gen.py` + `content_encrypt.py` are CLIs. |
| Input-remap UI | GAP | Sprint 7 target. `ActionMap` data class exists; no editor panel. |

**Subpackage totals:** 30 subpackages mapped (8 simulation, 5 rendering / GPU, 11 authoring / integration, 6 UI) + 8 planned-but-absent layers. Plus `docs/api/` references for 23 of these.

---

## 2. Editor panel map

The Notebook editor ships eleven panel classes (10 notebook-themed siblings of the Nova3D panels + one new `ThemeSwitcherPanel`). Per panel, every button / slider / checkbox / menu item is enumerated below with **file + line of the construction call**, **current behaviour**, and **delta vs the spec** (`docs/ui_pattern_audit_2026_06_03.md` §1 + `docs/theme_teengirl_notebook_2026_06_03.md` §4).

Behaviour vocabulary:

* **WORKS** — callback wired to engine state; user action causes the documented effect.
* **STUB** — callback runs but only mutates the panel's own bookkeeping (e.g. updates a `call_log`, prints a status message); does not yet reach the engine.
* **TODO** — declared in the spec but no widget on disk (gap).

### 2.1 `NotebookToolbar` — stationery-tray reskin

`python/slappyengine/ui/editor/notebook_toolbar.py` — `NotebookToolbar`

| Widget | Label | Type | Line | Behaviour | Spec target |
|---|---|---|---|---|---|
| Tool 1 | "Select" (heart-arrow SVG) | StickerButton | 218-225 | WORKS — calls `set_active("select")` → fires `on_tool_changed` → shell wires to `_on_tool_changed` which updates `_active_tool` + status bar | Cursor / pick mode |
| Tool 2 | "Move" (four-arrow flower SVG) | StickerButton | 218-225 | WORKS — same dispatch, key `T` | Translate gizmo mode |
| Tool 3 | "Rotate" (spiral SVG) | StickerButton | 218-225 | WORKS — key `R` | Rotate gizmo mode |
| Tool 4 | "Scale" (bow-tie SVG) | StickerButton | 218-225 | WORKS — key `C` | Scale gizmo mode |
| Active-tool indicator | Washi-tape underline | NineSlice texture | 532-552 | WORKS — tape texture rebakes on theme change; rendered via `_rebuild_tape_textures` | Underline beneath the active stamp |
| Creature slot | 32×32 right-margin region | SlotRegion | 233-240 | STUB — region reserved (claimed by `fox_01`) but the scheduler render call is **not invoked** by the toolbar itself; needs to be ticked by `EditorShell` per frame | Napping fox decoration |
| ❌ Snap toggle | (absent) | — | — | TODO — Nova3D `EditorToolbar` had a snap button (`docs/ui_pattern_audit_2026_06_03.md` §1.2) — not ported to the notebook variant | Ruler-clip icon |
| ❌ 2D/3D mode toggle | (absent) | — | — | TODO — Nova3D had a mode toggle; missing here (the shell tracks `_editor_mode` but nothing flips it) | Bookmark switch |

### 2.2 `NotebookOutliner` — pressed-flowers bestiary

`python/slappyengine/ui/editor/notebook_outliner.py` — `NotebookOutliner`

| Widget | Label | Type | Line | Behaviour | Spec target |
|---|---|---|---|---|---|
| Search input | "Search the bestiary…" | input_text | 354-360 | WORKS — `_on_search_changed` filters `iter_rows()` | Search bar |
| Washi underline strip | `===` decoration | text | 365 | WORKS — purely decorative | Decorative |
| Per-row name button | entity name | button | 604-610 | WORKS — `_handle_select` mirrors selection to `on_select` callback → shell → inspector + gizmo | Field-journal entry select |
| Per-row visibility | "<3" heart checkbox | checkbox | 616-622 | WORKS — mutates `entity.visible` in place | Open-eye glyph |
| Per-row lock | "key" mini checkbox | checkbox | 627-633 | WORKS — mutates `entity.locked` in place | Padlock sketch |
| First-entity sparkle | (sticker corner) | add_sticker_corner | 643-647 | WORKS — pinned by `_handle_select` | "Primary specimen" mark |
| Empty-state hint | "No entries yet…" + fox sticker | text + corner | 533-551 | WORKS — empty fixture | Onboarding cue |
| Section divider | `~ ~ ~ ~ ~` | text | 508-511 | WORKS — between buckets | Wavy doodle |
| ❌ `+ Add` button | (absent on outliner) | — | — | TODO per audit §1.3 — Nova3D outliner hosted the `+ Add` popup; here the spawn menu is a separate panel (`NotebookSpawnMenu`) without an outliner-embedded launcher | Affordance gap |
| ❌ Delete action | (absent) | — | — | TODO — `Delete` shortcut routes through shell, but no in-outliner trash button | Discoverability gap |

### 2.3 `NotebookInspector` — field-journal entry

`python/slappyengine/ui/editor/notebook_inspector.py` — `NotebookInspector`

Sections render dynamically via `_render_body` based on `_iter_fields()`; the widget choice is dispatched by `_render_field`. The table enumerates dispatch types, not literal widgets (count varies per target).

| Type | Widget | Line | Behaviour | Notes |
|---|---|---|---|---|
| Title row | "Field Journal" text | 233-235 | WORKS — static | Theme-tinted |
| Type header | `Type: <ClassName>` | 327-330 | WORKS | Debug aid |
| Transform section | WashiPanel — `position`, `rotation`, `scale`, etc. | 334-340 | WORKS via builder closures | First section (wavy separator after) |
| Properties section | WashiPanel — primitives | 341-347 | WORKS via builder closures | Second section (dotted separator after) |
| References section | WashiPanel — dataclass / engine objects | 348-353 | WORKS; nested `NotebookInspector` recurses | Third section |
| float field | HighlighterSlider | 580-612 | WORKS — `_write_back(name, float)` mutates target | Falls back to `input_float` |
| bool field | HeartCheckbox | 530-559 | WORKS — `_write_back(name, bool)` | Falls back to `add_checkbox` |
| int field | input_int | 561-578 | WORKS | Body font handwritten |
| str field | input_text + washi underline | 614-642 | WORKS — `_write_back(name, str)` | Decorative underline |
| Path field | input_text + "[clip]" paperclip button | 644-669 | **STUB** — clip button only appends `("path_picker", name)` to `call_log`; **no file dialog** | TODO: open OS file picker |
| Color field | color_edit + "[sticker]" preview | 671-698 | WORKS — write-back to target | Sticker preview is decorative-only |
| Float tuple | input_floatx | 700-719 | WORKS | Multi-axis |
| List[str] | listbox | 721-738 | **STUB** — read-only; no item add/remove | Append/remove TODO |
| List[int] | input_text (CSV) | 740-770 | WORKS — parses CSV on commit | Round-trip OK |
| Help `?` button | small button + popup | 857-898 | STUB — popup contains class docstring snippet; per-field doc lookup is naive (first-line fallback) | TODO: pull real attribute docstring |
| Reference `?` button | small button + popup | 826-849 | STUB — only shows `repr(value)` | TODO: drill-down navigation |
| Empty state | "[badger] Pick a critter…" | 355-369 | WORKS | Empty fixture |

### 2.4 `NotebookGizmoOverlay` — coloured-pencil sketches

`python/slappyengine/ui/editor/notebook_gizmos.py` — `NotebookGizmoOverlay`

The overlay paints into a draw-list-protocol object (DPG drawlist OR mock) and does its own hit-testing. There are no DPG buttons; the "widgets" below are the *handle keys* exposed by `hit_test`.

| Handle key | Drawn by | Line | Behaviour | Spec target |
|---|---|---|---|---|
| `x_axis` (translate) | `_render_translate` red pencil arrow + heart endpoint | 571-617 | WORKS — hit-tested, hover shimmer + highlighter underline when active | Doodled measurement arrow |
| `y_axis` (translate) | `_render_translate` blue pencil arrow + heart endpoint | 571-617 | WORKS | Doodled measurement arrow |
| `xy_center` (translate) | `_render_translate` centre heart | 614-616 | WORKS — hit-tested | Free-move heart |
| `rotate_handle` | `_render_rotate` accent heart at ring top | 622-666 | WORKS — hover shimmer, highlighter sweep when dragging | Compass-traced arc |
| `rotate_ring` | dashed pencil ring + sparkle ticks | 622-666 | WORKS — hit-test within 5 px band | Half-finished compass arc |
| `scale_tl` / `tr` / `bl` / `br` | bow-tie corner brackets | 670-725 | WORKS — hit-tested per corner | Crop-mark brackets |
| `scale_center` | centre heart with frame-pulse oscillation | 720-725 | WORKS — pulses while `_active_key` set | Pulse heart |
| `set_entity` / `set_camera` / `set_tool` / `set_mode` | (no widgets) | 422-452 | STUB — compat shims for Nova3D `GizmoOverlay`; the notebook overlay tracks state via `render(target_world_pos, mode)` directly. `set_mode` records `_mode_3d` but the overlay is 2D-only. | 3D-mode rendering deferred |
| Hover shimmer ring | `_maybe_emit_hover_shimmer` | 729-753 | WORKS | Lemon shimmer |
| Active underline | highlighter line below dragged handle | 755-778 | WORKS — translate handles only | Highlighter stroke |
| ❌ 3D-mode triad | (absent) | — | TODO — Nova3D drew three rings + axis triad in 3D; notebook overlay only honours 2D. `set_mode("3D")` is recorded then ignored. | Deferred (no editor 3D path yet) |

### 2.5 `NotebookCodePanel` — diary-page Code Mode

`python/slappyengine/ui/editor/notebook_code_panel.py` — `NotebookCodePanel`

| Widget | Label | Type | Line | Behaviour | Spec target |
|---|---|---|---|---|---|
| Bookmark ribbon | per-file tabs | button per file | 521-545 | WORKS — switching tabs swaps prompt / code buffers via `set_file` | Notebook tabs |
| `+ New` tab button | "+ New" | button | 537-545 | **STUB** — only appends `("new_file_clicked",)` to `call_log`; **no scaffold action** | TODO: create blank `.py` + `.prompt` pair |
| Prompt pane | left page "Dear diary..." | input_text (multiline) | 620-639 | WORKS — buffered on every keystroke via `_on_prompt_edited` | Lined paper |
| Code pane | right page generated Python | input_text (multiline) | 674-694 | WORKS — read-only unless pinned; writes via `_on_code_edited` | Dot-grid paper |
| Footer "Regenerate" | regen button | button | 718-723 | WORKS when Ollama probe succeeds — runs `prompt_to_code` async, writes back to file. Soft no-op + status message when Ollama is missing. | AI prompt → code |
| Footer "Explain" | explain button | button | 727-734 | WORKS-or-soft-noop — runs `code_to_prompt`; same Ollama gating | AI code → prompt |
| Footer "Pin" | pin button | button | 736-741 | WORKS — flips `_code_pinned` (read-only ↔ editable on code pane) | Editor toggle |
| Footer "Saved" | saved button | button | 745-751 | **STUB** — only flips `_saved_indicator` bool + logs; **no engine save call** | TODO: should fire save / butterfly hook |
| Status line | bottom text | text | 757-762 | WORKS — `_set_status` updates the label | Margin note |
| Sticker corner (Regenerate) | doodle arrow TR | sticker_corner | 769-775 | WORKS — gentle onboarding hint | Doodled arrow |

### 2.6 `NotebookSpawnMenu` — trading-card deck

`python/slappyengine/ui/editor/notebook_spawn_menu.py` — `NotebookSpawnMenu` + `SPAWN_CARDS` (10 entries)

| Widget | Label | Type | Line | Behaviour | Spec target |
|---|---|---|---|---|---|
| Card 1 | "Rope" (portrait + Summon!) | child_window + StickerButton | 771-858 | WORKS — `summon("rope")` → opens NotebookInspector-backed modal on a `RopeSpawnSpec` | Rope spec |
| Card 2 | "Ragdoll" | … | 771-858 | WORKS — `RagdollSpawnSpec` | Ragdoll spec |
| Card 3 | "Humanoid" | … | 771-858 | WORKS — `HumanoidSpawnSpec` | Humanoid spec |
| Card 4 | "IK Chain" | … | 771-858 | WORKS — `IKChainSpawnSpec` | IK chain |
| Card 5 | "Rect Zone" | … | 771-858 | WORKS — `RectZoneSpec` | Rect zone |
| Card 6 | "Threshold Zone" | … | 771-858 | WORKS — `ThresholdZoneSpec` | Threshold zone |
| Card 7 | "Point Light" | … | 771-858 | **STUB** — opens modal; `on_spawn("light_point", spec_dict)` fires but **the editor shell does not wire a light-creation handler** (verified: `EditorShell` callbacks only handle dynamics card ids) | Light wiring TODO |
| Card 8 | "Sun" | … | 771-858 | **STUB** — same; no directional-light handler | Light wiring TODO |
| Card 9 | "Material" | … | 771-858 | **STUB** — opens modal; **no `Material.create` plumb from the spec to a registered material** | Material wiring TODO |
| Card 10 | "Particle Emitter" | … | 771-858 | **STUB** — opens modal; **no `vfx` system to bind the emitter to** (Sprint 5 GAP) | VFX gap |
| Modal "Summon!" | submit button | button | 697-702 | WORKS — fires `on_spawn(card_id, spec_dict)` then closes modal | Submit |
| Modal "Cancel" | cancel button | button | 703-707 | WORKS — closes modal | Discard |
| Hover shimmer | `noise_glitter` texture | (set_hover) | 546-577 | WORKS — lazily baked, cached per card | Sparkle on hover |
| Title washi tape | `===` decoration | text | 738-741 | WORKS — decorative | Decorative |

### 2.7 `NotebookMaterialEditor` — colour-story page

`python/slappyengine/ui/editor/notebook_material_editor.py` — `NotebookMaterialEditor`

| Widget | Label | Type | Line | Behaviour | Spec target |
|---|---|---|---|---|---|
| Title row | "Colour Story" | text | 421 | WORKS | Page header |
| Sticker | per-material glyph ("[droplet]", "[mountain]", "[heart]", …) | text | 524-530 | WORKS — heuristic lookup | Mood sticker |
| Mood line | "Soft and squishy — bounces back…" | text | 533-541 | WORKS — name-keyword lookup | Hand-written description |
| 96×96 preview pane | "[preview 96×96]" stand-in | text token | 544-555 | **STUB** — placeholder text + colour; **no radial-gradient drawlist** | TODO: real preview render |
| Swatch row | per-stop color_edit (×2 for softbody / material_map, ×3 for fluid) | color_edit | 587-596 | WORKS — round-trips writes to target via NotebookInspector | Colour story |
| Gradient strip | `===` between swatches | text | 612-617 | WORKS — decorative only | Decorative |
| Editable fields | nested NotebookInspector | NotebookInspector | 680-684 | WORKS — reflects the active material's dataclass | Field editing |
| Empty state | "[swatch] Pick a material…" | text | 498-513 | WORKS | Empty fixture |
| ❌ "Save as material" | (absent) | — | — | TODO per Sprint 4 — no `.material` save action | YAML round-trip Sprint 4 |
| ❌ Visual node-graph canvas | (absent) | — | — | TODO — `NodeMaterial` runtime exists but no drag-and-drop authoring canvas (Sprint 4 deliverable) | Material graph editor |

### 2.8 `NotebookWelcome` — diary front cover

`python/slappyengine/ui/editor/notebook_welcome.py` — `NotebookWelcome`

| Widget | Label | Type | Line | Behaviour | Spec target |
|---|---|---|---|---|---|
| Title | "* SlapPy *" | text | 298-302 | WORKS — accent-tinted | Diary title |
| Subtitle | "(a teeny game-making notebook)" | text | 304-310 | WORKS | Tagline |
| Demo card 1 | "ragdoll" (fox glyph) | button | 408-419 | WORKS — `_on_demo_card_clicked("ragdoll")` → `on_open_demo` → shell resolves to `examples/hello_ragdoll.py` | Quick-start demo |
| Demo card 2 | "rope" (bunny glyph) | button | 408-419 | WORKS — opens `hello_rope.py` | Quick-start demo |
| Demo card 3 | "studio" (butterfly glyph) | button | 408-419 | WORKS — opens `hello_studio.py` | Quick-start demo |
| Start drawing | "<3 Start drawing!" | button | 343-350 | WORKS — fires `on_start_blank` → `Engine.new_scene()` → mark seen + dismiss | New blank scene |
| Theme swatch | 6× 32×32 swatches (TG / CD / BJ / SS / CG / KP) | button | 436-447 | WORKS — `_on_theme_swatch_clicked` calls `apply_theme(id)`, marks seen, dismisses | Hot-swap theme |
| Hide checkbox | "Don't show this again" | HeartCheckbox | 380 | WORKS — writes back to `settings.welcome_shown` | First-run gate |
| Sticker TL | sparkle corner | sticker_corner | 281-287 | WORKS | Decorative |
| Sticker BR | heart corner | sticker_corner | 288-294 | WORKS | Decorative |
| Sparkle creature pulse | scheduler trigger | tick_sparkle | 187-227 | STUB — `bind_creature_scheduler` is exposed but the welcome panel itself does NOT auto-tick; the shell's render loop must call `tick_sparkle` (verified: shell does not currently do this — Easter-egg gap) | Header twinkle |

### 2.9 `NotebookStatusBar` — marginalia row

`python/slappyengine/ui/editor/notebook_status_bar.py` — `NotebookStatusBar`

| Widget | Label / role | Type | Line | Behaviour | Spec target |
|---|---|---|---|---|---|
| Upper washi divider | (decorative) | separator | 508-510 | WORKS | Divider |
| Composite label | `"tool: <id> | N selected | world: (x, y) | <fps> fps | <save> | theme: <id>"` | text | 518-522 | WORKS — recomposes on every setter | Marginalia line |
| Theme indicator | 16×16 sticker button (theme glyph) | button | 524-530 | WORKS — calls `on_theme_indicator_click` → shell opens theme switcher | Theme switch entry |
| Lower washi divider | (decorative) | separator | 531-533 | WORKS | Divider |
| Transient message overlay | 3-second fade-out | (composite) | 320-358 | WORKS — `set_message(text, kind)` + `tick(dt)` driven; `tick` MUST be called by the shell every frame (verified: shell does not yet plumb `dt` into the bar — minor gap) | Save / error feedback |
| Tool setter | `set_active_tool(id)` | — | 267-273 | WORKS — push from `_on_tool_changed` | Tool reflection |
| Selection setter | `set_selection_count(n)` | — | 274-287 | WORKS — pushed by shell on outliner select | Selection mirror |
| World cursor setter | `set_world_cursor(x, y)` | — | 289-294 | STUB — exposed but **shell does not currently push cursor coordinates** | Cursor mirror |
| FPS setter | `set_fps(fps)` | — | 296-302 | STUB — exposed but **shell does not currently push fps** | Perf mirror |
| Save-state setter | `set_save_state(saved)` | — | 304-309 | WORKS — `_save_project` flips it | Save reflection |
| Theme name setter | `set_active_theme_name(name)` | — | 311-318 | WORKS — pushed by shell on theme switch | Theme reflection |

### 2.10 `NotebookHotkeys` — global hotkey table

`python/slappyengine/ui/editor/notebook_hotkeys.py` — `NotebookHotkeys` + `BINDINGS` (16 entries)

| Key | Command id | Behaviour | Notes |
|---|---|---|---|
| `ctrl+s` | `editor.save` | WORKS — routes to `_save_project` | Tested |
| `ctrl+z` | `editor.undo` | WORKS — routes to `_undo` | Tested |
| `ctrl+y` | `editor.redo` | **STUB** — dispatcher hits the local action table for `redo` → MISS, then engine hook → MISS, so the status bar prints `cmd: editor.redo`. **No actual undo-stack redo on disk.** | TODO |
| `ctrl+n` | `editor.new` | **STUB** — same routing miss; status message only | TODO |
| `ctrl+o` | `editor.open` | **STUB** — same; no file dialog | TODO |
| `f1` | `editor.help` | **STUB** — no help panel | TODO |
| `f3` | `editor.profiler_toggle` | **STUB** — no profiler overlay (Sprint 6 GAP) | TODO |
| `f5` | `editor.run` | WORKS — routes to `_toggle_play` | Play mode |
| `f11` | `editor.toggle_fullscreen` | **STUB** — no fullscreen handler | TODO |
| `s` | `editor.tool_select` | **STUB** — no shell handler today; toolbar reacts via its own `handle_shortcut` but the hotkey table routes to a missing engine hook | Routing gap |
| `t` | `editor.tool_move` | STUB | Same routing gap |
| `r` | `editor.tool_rotate` | STUB | Same |
| `c` | `editor.tool_scale` | STUB | Same |
| `h` | `editor.toggle_hud` | STUB — no HUD toggle in shell | TODO |
| `ctrl+shift+f` | `editor.easter_feed_fox` | WORKS — gates on `easter_eggs` flag, fires `scheduler.trigger("fox_01", "feed")` if scheduler bound | Easter egg |
| `ctrl+shift+b` | `editor.easter_baby_porcupine_roll` | WORKS — fires `scheduler.trigger("porcupine_01", "ball_up")` | Easter egg |

### 2.11 `ThemeSwitcherPanel` — live theme hot-swap

`python/slappyengine/ui/editor/theme_switcher_panel.py` — `ThemeSwitcherPanel`

| Widget | Label | Type | Line | Behaviour | Spec target |
|---|---|---|---|---|---|
| Header | "Theme" + active name | text + text | 394-399 | WORKS | Header |
| Theme card (×6) | 3-stripe palette + sticker + "Apply" button | child_window | 451-481 | WORKS — `_on_theme_card_clicked` → `apply_theme(id)` then refreshes panel | Card grid |
| Wavy separator | DoodleSeparator | sep | 483-493 | WORKS | Section divider |
| Creature roster | one HeartCheckbox per creature in active theme's `metadata["creature_roster"]` | HeartCheckbox | 519-551 | WORKS — `_on_creature_toggle` forwards to `scheduler.set_enabled(creature_id, flag)` when scheduler bound | Per-creature opt-out |
| Dotted separator | DoodleSeparator | sep | 483-493 | WORKS | Section divider |
| Animations master | "Animations" | HeartCheckbox | 553-572 | WORKS — forwards to `scheduler.set_animations_enabled` | Master switch |
| Reduced motion | "Reduced motion" | checkbox | 575-582 | WORKS — forwards to `scheduler.set_reduced_motion` | Accessibility |
| Easter eggs | "Easter eggs" | checkbox | 585-592 | WORKS — forwards to `scheduler.set_easter_eggs`; gates `NotebookHotkeys` easter-egg dispatch | Accessibility |
| Refresh editor | "Refresh editor" | StickerButton | 594-614 | WORKS — fires `on_refresh` callback then `self.refresh()` (rebuild cards + roster) | Soft reload |

**Button audit total:** ~110 distinct widgets across 11 panels (toolbar 4 + outliner 5 + inspector 9 dispatch types + gizmo 9 handle keys + code 7 + spawn 12 + material 7 + welcome 8 + status 6 + hotkeys 16 + theme switcher 10).

---

## 3. Cross-system flow map

### 3.1 First-run → welcome → pick project → enter editor

1. `Engine.run_editor()` → `EditorShell.setup_theme_subsystem()`
   ([shell.py:210](../python/slappyengine/ui/editor/shell.py#L210)) registers the six diary themes, applies `ui_settings.default_theme`, builds the `CreatureScheduler`, registers built-in creatures, installs the `CreatureBusAdapter`, spawns the `IdleEventEmitter`, and stages the `ThemeSwitcherPanel`.
2. `EditorShell.setup()` calls `setup_notebook_panels()` which constructs the toolbar, outliner, inspector, and gizmo overlay.
3. `dpg.create_context()` runs (line 384) and the layout is built.
4. If `ui_settings.welcome_shown == False`, the shell calls `show_welcome()` which lazily constructs `NotebookWelcome` and binds it to the creature scheduler.
5. User clicks "Start drawing!" → `_on_start_blank` → `Engine.new_scene()` → `mark_seen()` → `dismiss()` (deletes panel, removes sticker corners).
6. Welcome closes; the toolbar, outliner, inspector, gizmo, code panel, content browser, and status bar are now live.

**Flow status:** WORKS end-to-end for "Start drawing"; demo-card path WORKS (resolves `<id>` → `examples/hello_<id>.py`); theme-swatch path WORKS (calls `apply_theme(id)`).

### 3.2 Select entity in outliner → property inspector populates

1. User clicks the per-row name button → `_handle_select(entity)` ([notebook_outliner.py:657](../python/slappyengine/ui/editor/notebook_outliner.py#L657)).
2. `_on_select` chained callback fires → `EditorShell._on_entity_selected(entity)`.
3. Shell stashes `self._selected_entity = entity`, pushes `set_selection_count(1)` to the status bar, calls `_inspector.set_target(entity)` and `_gizmo_overlay.set_entity(entity)`.
4. `NotebookInspector.set_target` triggers `refresh()` which wipes the current body and re-runs `_render_body` → categorises fields into Transform / Properties / References → builds three `WashiPanel`s with the appropriate widget per type.
5. Gizmo overlay's next `render(target_world_pos, mode)` paints around the entity.

**Flow status:** WORKS for dataclass and `__dict__` targets. Edge case: nested dataclasses recurse via `_render_reference_field` → child `NotebookInspector`, verified by `test_editor_notebook_inspector.py::test_render_nested_dataclass_field`.

### 3.3 Toolbar tool click → gizmo overlay mode changes

1. User clicks "Rotate" sticker button or presses `R`.
2. `StickerButton.callback` (constructor closure) calls `NotebookToolbar.set_active("rotate")`.
3. `set_active` mutates `_active_tool`, fires `on_tool_changed("rotate")` → `EditorShell._on_tool_changed("rotate")`.
4. Shell pushes `set_active_tool("rotate")` to the status bar, sets `self._active_tool = "rotate"`, calls `_gizmo_overlay.set_tool("rotate")` (compat shim).
5. Next frame the editor calls `gizmo_overlay.render(entity.position, "rotate")` → dashed pencil ring + sparkle ticks.

**Flow status:** WORKS for translate / rotate / scale modes. **Gap:** the hotkey table's `s` / `t` / `r` / `c` route via `NotebookHotkeys` → dispatcher → MISS (no action under `editor.tool_*`) → status message only. The toolbar's own `handle_shortcut` is the only path that actually changes the active tool — it is currently routed by the shell's keyboard-shortcut router but not by the global `NotebookHotkeys` registry.

### 3.4 Save → butterfly creature flutters via event bus

1. User presses `Ctrl+S` (registered in `NotebookHotkeys.BINDINGS`).
2. `NotebookHotkeys.handle_key_event("s", ["ctrl"])` → canonical `"ctrl+s"` → command `"editor.save"`.
3. Dispatcher routes to `EditorShell._save_project()`.
4. `_save_project` calls `engine._project_manager.save()` → saves disk-side; updates `_scene_saved = True`; pushes `set_save_state(True)` to status bar.
5. Status bar repaints the "saved" segment + green tint.
6. Event bus emits `engine.scene_saved` (via project manager).
7. `CreatureBusAdapter` listens → dispatches `EVENT_TO_CREATURE_ANIMS["engine.scene_saved"]` = "butterfly flutter" (per `idle_animation_system_2026_06_03.md`).
8. `CreatureScheduler.trigger("butterfly_01", "flutter")` → animation plays at next render tick.

**Flow status:** WORKS for the save path. **Status bar transient message + butterfly cue depend on the shell's per-frame `dt` tick → the shell does not currently pipe `dt` to `notebook_status_bar.tick(dt)`**, so the transient fade is frozen until the user moves the mouse / fires another save (minor gap).

### 3.5 Spawn menu summon → entity added → outliner refresh

1. User opens spawn menu (today: separate panel; see audit gap §2.6).
2. Clicks "Summon!" on a Rope card → `NotebookSpawnMenu.summon("rope")` → `_open_summon_modal` → modal with embedded `NotebookInspector` on a `RopeSpawnSpec`.
3. User adjusts fields → inspector writes back to the spec.
4. User clicks modal "Summon!" → `submit_modal()` → `on_spawn("rope", spec_dict)` callback fires.
5. `EditorShell._on_spawn_action_*` (per-card-id handler) builds the dynamics entity via `slappyengine.dynamics.build_rope(...)`, adds it to `engine.scene`, and notifies the outliner.
6. Outliner picks up the new entity on its next `refresh()` call.

**Flow status:** WORKS for the dynamics-builder cards (rope / ragdoll / humanoid / ik_chain). **STUB for non-dynamics cards** (lights / material / emitter / zones) — the modal opens and the `on_spawn` callback fires, but the shell does not have a handler that consumes the resulting spec dict for these card ids. See §4 below.

---

## 4. Gap analysis

### 4.1 Dead buttons (callback = no-op or status-message-only)

| Panel | Widget | Source line | Why it's dead |
|---|---|---|---|
| `NotebookCodePanel` | `+ New` tab | [521-545](../python/slappyengine/ui/editor/notebook_code_panel.py#L521) | Only appends `("new_file_clicked",)` to `call_log` |
| `NotebookCodePanel` | "Saved" footer button | [745-751](../python/slappyengine/ui/editor/notebook_code_panel.py#L745) | Only flips `_saved_indicator` local bool — no engine save |
| `NotebookInspector` | "[clip]" path picker | [659-665](../python/slappyengine/ui/editor/notebook_inspector.py#L659) | Only logs `("path_picker", name)` — no OS file dialog |
| `NotebookInspector` | `?` help popup | [880-898](../python/slappyengine/ui/editor/notebook_inspector.py#L880) | Pops a popup but doc lookup is naive class-docstring substring search |
| `NotebookSpawnMenu` | Point Light card | [771-858](../python/slappyengine/ui/editor/notebook_spawn_menu.py#L771) | Modal opens; `on_spawn("light_point", ...)` fires; shell has no handler |
| `NotebookSpawnMenu` | Sun card | [771-858](../python/slappyengine/ui/editor/notebook_spawn_menu.py#L771) | Same — no `light_directional` handler |
| `NotebookSpawnMenu` | Material card | [771-858](../python/slappyengine/ui/editor/notebook_spawn_menu.py#L771) | Same — no material registration path |
| `NotebookSpawnMenu` | Particle Emitter card | [771-858](../python/slappyengine/ui/editor/notebook_spawn_menu.py#L771) | No `vfx` system to bind to |
| `NotebookHotkeys` | `ctrl+y` (redo) | BINDINGS line [70](../python/slappyengine/ui/editor/notebook_hotkeys.py#L70) | No engine hook; status message only |
| `NotebookHotkeys` | `ctrl+n` (new) | BINDINGS line [71](../python/slappyengine/ui/editor/notebook_hotkeys.py#L71) | Same |
| `NotebookHotkeys` | `ctrl+o` (open) | BINDINGS line [72](../python/slappyengine/ui/editor/notebook_hotkeys.py#L72) | Same |
| `NotebookHotkeys` | `f1` (help) | BINDINGS line [73](../python/slappyengine/ui/editor/notebook_hotkeys.py#L73) | Same |
| `NotebookHotkeys` | `f3` (profiler) | BINDINGS line [74](../python/slappyengine/ui/editor/notebook_hotkeys.py#L74) | Sprint 6 GAP |
| `NotebookHotkeys` | `f11` (fullscreen) | BINDINGS line [76](../python/slappyengine/ui/editor/notebook_hotkeys.py#L76) | Same |
| `NotebookHotkeys` | `s` / `t` / `r` / `c` (tool letters) | BINDINGS [77-80](../python/slappyengine/ui/editor/notebook_hotkeys.py#L77) | Hotkey table routes to missing `editor.tool_*` handlers; toolbar has its own `handle_shortcut` |
| `NotebookHotkeys` | `h` (HUD toggle) | BINDINGS line [81](../python/slappyengine/ui/editor/notebook_hotkeys.py#L81) | No HUD toggle in shell |
| `NotebookMaterialEditor` | 96×96 preview pane | [546-555](../python/slappyengine/ui/editor/notebook_material_editor.py#L546) | Placeholder text token; no actual radial-gradient draw |
| `NotebookToolbar` | Creature slot | [233-240](../python/slappyengine/ui/editor/notebook_toolbar.py#L233) | Region reserved; no scheduler render call from inside the toolbar |
| `NotebookStatusBar` | `set_world_cursor` | [289-294](../python/slappyengine/ui/editor/notebook_status_bar.py#L289) | Exposed; shell doesn't push values |
| `NotebookStatusBar` | `set_fps` | [296-302](../python/slappyengine/ui/editor/notebook_status_bar.py#L296) | Same |
| `NotebookWelcome` | sparkle pulse via `tick_sparkle` | [187-227](../python/slappyengine/ui/editor/notebook_welcome.py#L187) | Method exists; shell doesn't tick it |

### 4.2 Lifecycle hooks that fail silently

| Hook | Where | Failure mode |
|---|---|---|
| `EditorShell._dispatch_editor_command` | [shell.py:154-191](../python/slappyengine/ui/editor/shell.py#L154) | Catches every exception silently — pre-`__init__` engine state crashes simply set the status bar to a "cmd: …" hint |
| `NotebookInspector._write_back` | [958-952](../python/slappyengine/ui/editor/notebook_inspector.py#L943) | Catches `AttributeError` / `TypeError` and swallows — read-only or `__slots__` attributes silently fail |
| `NotebookInspector.refresh` | [251-294](../python/slappyengine/ui/editor/notebook_inspector.py#L251) | Headless `dpg` failures broadly try / except — when a widget destroy fails the panel leaks theme listeners |
| `CreatureBusAdapter` event handlers | (per [`idle_animation_system_2026_06_03.md`](idle_animation_system_2026_06_03.md)) | Animation lookup miss is silently swallowed by the scheduler |
| `NotebookHotkeys._dispatcher` | [322-326](../python/slappyengine/ui/editor/notebook_hotkeys.py#L322) | Catches `Exception` around the dispatch call; user can't see which command failed |
| `NotebookCodePanel.regenerate` | [349-390](../python/slappyengine/ui/editor/notebook_code_panel.py#L349) | Async Ollama failure becomes a status line; no error log to disk |
| `NotebookSpawnMenu.submit_modal` | [605-624](../python/slappyengine/ui/editor/notebook_spawn_menu.py#L605) | Catches every callback exception so "Summon!" appears to succeed even when the shell handler crashed |

### 4.3 Subsystems lacking editor surfaces

| Subsystem | Editor surface today | What's missing |
|---|---|---|
| `animation` | Static `AnimGraphPanel` (Nova3D-only) | No notebook variant; no blend-tree editor; no transition graph canvas; no preview pane |
| `material` (graph) | `MaterialEditor` reflection inspector | No drag-and-drop node-graph canvas with live preview (Sprint 4) |
| `vfx` / particles | (none) | No emitter authoring panel, no force-field tray, no curve editor (Sprint 5 — module doesn't exist yet) |
| `telemetry` profiler | (none) | No F3 in-engine flame graph / per-frame timeline (Sprint 6) |
| `net` | (none) | No room / peer / session UI (roadmap mid-term) |
| `audio_runtime` | (none) | No backend chooser, no device picker, no sample-rate audit |
| `build_gen` / `content_encrypt` | (none — CLIs only) | No editor wizard for export → wheel / encrypted content bundle (Sprint 7) |
| `ai` | `NotebookCodePanel` is the only consumer | No model picker / token-budget viewer / prompt-library browser |
| `iso` | (none) | No iso-camera viewpoint switcher or tile-painter panel (the `tag_painter` module exists but is Nova3D-only and not notebook-themed) |
| `i18n` | (none) | No string-table panel (Sprint 7 — module doesn't exist yet) |
| `input` (ActionMap) | (none) | No keybinding remap UI (Sprint 7) |

### 4.4 Top-10 holes to fill before v0.4

Ranked by impact / unlock-the-next-sprint dependency, sourced from §4.1-4.3 + [`sprint_plan_2026_06_03.md`](sprint_plan_2026_06_03.md) + [`roadmap.md`](roadmap.md):

1. **Wire `NotebookSpawnMenu` lights / material / emitter / zone-rect / zone-threshold card handlers in `EditorShell`** — six dead cards on a 10-card deck is the biggest user-visible regression vs Nova3D's spawn menu (Sprint 2 / 4 / 5 prereq).
2. **Plumb `NotebookStatusBar.tick(dt)` + `set_world_cursor(x, y)` + `set_fps(fps)` from the shell render loop** — three setters exist on the bar but the shell doesn't pump them; trivial fix that lights up the marginalia row.
3. **Hotkey table routing** — wire `ctrl+y` / `ctrl+n` / `ctrl+o` / `f11` / `s`-`t`-`r`-`c` / `h` to actual shell or engine actions. Today they all dead-end into "cmd: …" status messages.
4. **Visual node-graph canvas for `material.NodeMaterial`** — Sprint 4 deliverable; today's `NotebookMaterialEditor` only reflects fields, has no graph authoring (no canvas, no connection lines, no node library palette).
5. **Animation graph editor + IK retargeting** — Sprint 3; `animation` subpackage is WORKING but lacks the editor canvas, blend-tree types, and GLTF importer.
6. **VFX system (`slappyengine.vfx`) + emitter authoring panel** — Sprint 5; `particles.py` exists but no high-level Effect / Emitter / ForceField / Curve API and no editor panel.
7. **Profiler overlay (F3)** — Sprint 6; `telemetry` ships events; need a `FrameProfiler` + DPG overlay widget.
8. **OS file picker for `NotebookInspector` Path fields and for `ctrl+o`** — single shared helper; covers two dead buttons.
9. **`docs/api/ai.md` + `docs/api/network.md`** — two subpackage references missing from the doc-inventory tripwire (catches the next `test_docs_inventory.py` lockfile bump).
10. **ECS scheduler formalisation** — Sprint 2; load-bearing for sprints 3-6. Today: `Component` Protocol + `ComponentBase` only; no `System` base, no `Scheduler`, no `ComponentRegistry`.

---

## 5. Cross-links

* Sprint planning: [`sprint_plan_2026_06_03.md`](sprint_plan_2026_06_03.md)
* Doc inventory tripwire: [`sprint_5_doc_inventory.md`](sprint_5_doc_inventory.md) — every doc under `docs/**/*.md` must appear there.
* Nova3D pattern audit (panel-level contracts + woodland/notebook translation): [`ui_pattern_audit_2026_06_03.md`](ui_pattern_audit_2026_06_03.md)
* Notebook editor user manual: [`notebook_editor_manual_2026_06_03.md`](notebook_editor_manual_2026_06_03.md)
* Engine surface v0.3 (75 names across 19 subpackages): [`engine_surface_v030.md`](engine_surface_v030.md)
* Roadmap (mid-term / long-term gaps): [`roadmap.md`](roadmap.md)
* Lifecycle hook contract: [`lifecycle_contract.md`](lifecycle_contract.md)
* Notebook theme design: [`theme_teengirl_notebook_2026_06_03.md`](theme_teengirl_notebook_2026_06_03.md), [`theme_diary_family_2026_06_03.md`](theme_diary_family_2026_06_03.md)
* Idle animation contract: [`idle_animation_system_2026_06_03.md`](idle_animation_system_2026_06_03.md)
* Per-subpackage API references: 23 files under [`docs/api/`](api/) — see §1 for per-row links.
